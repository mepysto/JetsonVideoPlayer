#include "MediaProbe.h"

#include "Codecs.h"
#include "GstUtil.h"
#include "Storage.h"

#include <QFileInfo>
#include <QLoggingCategory>
#include <gst/gst.h>

Q_LOGGING_CATEGORY(lcProbe, "jvp.probe")

namespace jvp::probe {

namespace {

// 디코딩 없이 컨테이너만 풀어 스트림 caps를 읽습니다 (filesrc ! parsebin).
// GstDiscoverer는 디코더까지 붙이므로, 우선순위를 올려 둔 NVDEC가 지원하지 않는 형식(4:4:4 등)에서
// 오류를 내 코덱 정보를 얻지 못합니다.
struct ProbeResult {
    bool ok = false;
    GstCaps *video = nullptr;
    GstCaps *audio = nullptr;
    ~ProbeResult()
    {
        if (video)
            gst_caps_unref(video);
        if (audio)
            gst_caps_unref(audio);
    }
};

struct ProbeState {
    GstElement *pipeline = nullptr;
    GMutex lock;
    QList<GstPad *> pads;
};

void onParsedPad(GstElement *, GstPad *pad, gpointer data)
{
    auto *st = static_cast<ProbeState *>(data);
    GstElement *sink = gst_element_factory_make("fakesink", nullptr);
    g_object_set(sink, "sync", FALSE, nullptr);
    gst_bin_add(GST_BIN(st->pipeline), sink);
    gst_element_sync_state_with_parent(sink);
    GstPad *sinkPad = gst_element_get_static_pad(sink, "sink");
    gst_pad_link(pad, sinkPad);
    gst_object_unref(sinkPad);
    g_mutex_lock(&st->lock);
    st->pads << GST_PAD(gst_object_ref(pad));
    g_mutex_unlock(&st->lock);
}

void probe(const QString &path, int timeoutSec, ProbeResult &out)
{
    ProbeState st;
    g_mutex_init(&st.lock);
    st.pipeline = gst_pipeline_new(nullptr);
    GstElement *src = gst_element_factory_make("filesrc", nullptr);
    GstElement *parse = gst_element_factory_make("parsebin", nullptr);
    if (!src || !parse) {
        if (src) gst_object_unref(src);
        if (parse) gst_object_unref(parse);
        gst_object_unref(st.pipeline);
        g_mutex_clear(&st.lock);
        return;
    }
    g_object_set(src, "location", QFileInfo(path).absoluteFilePath().toUtf8().constData(), nullptr);
    gst_bin_add_many(GST_BIN(st.pipeline), src, parse, nullptr);
    gst_element_link(src, parse);
    g_signal_connect(parse, "pad-added", G_CALLBACK(onParsedPad), &st);

    gst_element_set_state(st.pipeline, GST_STATE_PAUSED);
    GstBus *bus = gst_element_get_bus(st.pipeline);
    GstMessage *msg = gst_bus_timed_pop_filtered(bus, GstClockTime(timeoutSec) * GST_SECOND,
                                                 GstMessageType(GST_MESSAGE_ASYNC_DONE | GST_MESSAGE_ERROR | GST_MESSAGE_EOS));
    if (msg) {
        out.ok = GST_MESSAGE_TYPE(msg) != GST_MESSAGE_ERROR;
        if (!out.ok) {
            GError *err = nullptr;
            gst_message_parse_error(msg, &err, nullptr);
            qCDebug(lcProbe) << "스트림 분석 실패" << path << (err ? err->message : "");
            g_clear_error(&err);
        }
        gst_message_unref(msg);
    }
    gst_object_unref(bus);
    // NULL로 내리면 패드의 caps가 지워지므로 먼저 읽습니다.
    g_mutex_lock(&st.lock);
    for (GstPad *pad : std::as_const(st.pads)) {
        GstCaps *caps = gst_pad_get_current_caps(pad);
        if (!caps)
            caps = gst_pad_query_caps(pad, nullptr);
        if (caps && gst_caps_get_size(caps) > 0) {
            const QByteArray name = gst_structure_get_name(gst_caps_get_structure(caps, 0));
            if (name.startsWith("video/") && !out.video)
                out.video = gst_caps_ref(caps);
            else if (name.startsWith("audio/") && !out.audio)
                out.audio = gst_caps_ref(caps);
        }
        if (caps)
            gst_caps_unref(caps);
        gst_object_unref(pad);
    }
    // 스트림이 하나라도 나왔으면 (끝까지 준비되지 않았어도) 결과로 씁니다.
    out.ok = out.ok || out.video || out.audio;
    g_mutex_unlock(&st.lock);
    gst_element_set_state(st.pipeline, GST_STATE_NULL);
    gst_object_unref(st.pipeline);
    g_mutex_clear(&st.lock);
}

// GStreamer caps 이름 → ffprobe 코덱 이름 (codecs::nvdecSupports가 받는 이름)
QString codecFromCaps(const GstStructure *st)
{
    const QString name = QString::fromUtf8(gst_structure_get_name(st));
    if (name == QLatin1String("video/x-h265")) return QStringLiteral("hevc");
    if (name == QLatin1String("video/x-h264")) return QStringLiteral("h264");
    if (name == QLatin1String("video/x-vp8")) return QStringLiteral("vp8");
    if (name == QLatin1String("video/x-vp9")) return QStringLiteral("vp9");
    if (name == QLatin1String("video/x-av1")) return QStringLiteral("av1");
    if (name == QLatin1String("video/mpeg")) {
        int v = 0;
        gst_structure_get_int(st, "mpegversion", &v);
        return v == 4 ? QStringLiteral("mpeg4") : QStringLiteral("mpeg2video");
    }
    if (name == QLatin1String("image/jpeg")) return QStringLiteral("mjpeg");
    if (name.startsWith(QLatin1String("video/x-")))
        return name.mid(8);
    return name;
}

} // namespace

std::optional<VideoCodecInfo> videoCodec(const QString &path, int timeoutSec)
{
    ProbeResult r;
    probe(path, timeoutSec, r);
    if (!r.ok)
        return std::nullopt;
    VideoCodecInfo out;
    if (!r.video)
        return out;   // 영상 스트림 없음
    const GstStructure *st = gst_caps_get_structure(r.video, 0);
    out.codec = codecFromCaps(st);
    const gchar *profile = gst_structure_get_string(st, "profile");
    out.profile = profile ? QString::fromUtf8(profile) : QString();
    // 크로마·비트 깊이 → ffprobe pix_fmt 모양 (yuv420p / yuv420p10le)
    const gchar *chroma = gst_structure_get_string(st, "chroma-format");
    guint depth = 8;
    gst_structure_get_uint(st, "bit-depth-luma", &depth);
    QString c = QStringLiteral("420");
    if (chroma && QByteArray(chroma) == "4:4:4")
        c = QStringLiteral("444");
    else if (chroma && QByteArray(chroma) == "4:2:2")
        c = QStringLiteral("422");
    if (depth == 8 && out.profile.contains(QLatin1String("10")))   // 프로필 이름에만 깊이가 드러나는 경우
        depth = 10;
    out.pixFmt = depth > 8 ? QStringLiteral("yuv%1p%2le").arg(c).arg(depth) : QStringLiteral("yuv%1p").arg(c);
    return out;
}

HwSupport checkHwSupport(const QString &path)
{
    if (auto cached = hwCache().get(path))
        return {cached->first, cached->second};
    const auto info = videoCodec(path);
    if (!info)
        return {std::nullopt, QStringLiteral("코덱 분석 실패")};
    if (info->codec.isEmpty()) {
        hwCache().set(path, false, QStringLiteral("비디오 스트림 없음"));
        return {false, QStringLiteral("비디오 스트림 없음")};
    }
    const auto d = codecs::nvdecSupports(info->codec, info->pixFmt, info->profile);
    hwCache().set(path, d.supported, d.reason);
    return {d.supported, d.reason};
}

QString audioCodec(const QString &path, int timeoutSec)
{
    ProbeResult r;
    probe(path, timeoutSec, r);
    return r.audio ? QString::fromUtf8(gst_structure_get_name(gst_caps_get_structure(r.audio, 0))) : QString();
}

const QSet<QString> &passthroughCaps()
{
    static const QSet<QString> caps{QStringLiteral("audio/x-ac3"), QStringLiteral("audio/x-eac3"),
                                    QStringLiteral("audio/x-dts")};
    return caps;
}

QSet<QString> sinkPassthroughFormats(const char *factory)
{
    QSet<QString> out;
    GstElement *sink = gst_element_factory_make(factory, nullptr);
    if (!sink)
        return out;
    if (gst_element_set_state(sink, GST_STATE_READY) != GST_STATE_CHANGE_FAILURE) {
        GstPad *pad = gst_element_get_static_pad(sink, "sink");
        GstCaps *caps = pad ? gst_pad_query_caps(pad, nullptr) : nullptr;
        for (guint i = 0; caps && i < gst_caps_get_size(caps); ++i) {
            const QString name = QString::fromUtf8(gst_structure_get_name(gst_caps_get_structure(caps, i)));
            if (passthroughCaps().contains(name))
                out.insert(name);
        }
        if (caps)
            gst_caps_unref(caps);
        if (pad)
            gst_object_unref(pad);
    }
    gst_element_set_state(sink, GST_STATE_NULL);
    gst_object_unref(sink);
    return out;
}

} // namespace jvp::probe
