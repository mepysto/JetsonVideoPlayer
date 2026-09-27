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
    QList<GstCaps *> caps;   // 패드마다 처음 흘러온 CAPS 이벤트 (패드가 나온 직후에는 아직 caps가 없습니다)
};

void wakeWaiter(ProbeState *st)
{
    // 버스에서 기다리는 쪽을 깨워 준비 상태를 다시 확인하게 합니다.
    gst_element_post_message(st->pipeline, gst_message_new_application(nullptr, gst_structure_new_empty("jvp-probe")));
}

GstPadProbeReturn onPadEvent(GstPad *, GstPadProbeInfo *info, gpointer data)
{
    GstEvent *ev = GST_PAD_PROBE_INFO_EVENT(info);
    if (GST_EVENT_TYPE(ev) != GST_EVENT_CAPS)
        return GST_PAD_PROBE_OK;
    auto *st = static_cast<ProbeState *>(data);
    GstCaps *caps = nullptr;
    gst_event_parse_caps(ev, &caps);
    g_mutex_lock(&st->lock);
    st->caps << gst_caps_ref(caps);
    g_mutex_unlock(&st->lock);
    wakeWaiter(st);
    return GST_PAD_PROBE_REMOVE;
}

void onParsedPad(GstElement *, GstPad *pad, gpointer data)
{
    auto *st = static_cast<ProbeState *>(data);
    gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM, onPadEvent, st, nullptr);
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
    wakeWaiter(st);
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
    // 싱크는 패드가 나온 뒤에 붙으므로 파이프라인이 ASYNC_DONE을 보내지 않을 때가 많습니다.
    // parsebin이 알려 준 스트림 수(STREAM_COLLECTION)만큼 패드가 나오고 모두 caps를 받으면 바로 끝냅니다.
    GstBus *bus = gst_element_get_bus(st.pipeline);
    const gint64 deadline = g_get_monotonic_time() + gint64(timeoutSec) * G_USEC_PER_SEC;
    int expected = -1;
    for (;;) {
        const gint64 left = deadline - g_get_monotonic_time();
        if (left <= 0)
            break;
        GstMessage *msg = gst_bus_timed_pop_filtered(
            bus, GstClockTime(left) * GST_USECOND,
            GstMessageType(GST_MESSAGE_ASYNC_DONE | GST_MESSAGE_ERROR | GST_MESSAGE_EOS
                           | GST_MESSAGE_STREAM_COLLECTION | GST_MESSAGE_APPLICATION));
        if (!msg)
            break;
        bool done = false;
        switch (GST_MESSAGE_TYPE(msg)) {
        case GST_MESSAGE_ERROR: {
            GError *err = nullptr;
            gst_message_parse_error(msg, &err, nullptr);
            qCDebug(lcProbe) << "스트림 분석 실패" << path << (err ? err->message : "");
            g_clear_error(&err);
            done = true;
            break;
        }
        case GST_MESSAGE_STREAM_COLLECTION: {
            GstStreamCollection *c = nullptr;
            gst_message_parse_stream_collection(msg, &c);
            if (c) {
                expected = int(gst_stream_collection_get_size(c));
                gst_object_unref(c);
            }
            break;
        }
        case GST_MESSAGE_APPLICATION:
            break;
        default:   // ASYNC_DONE, EOS
            out.ok = true;
            done = true;
            break;
        }
        gst_message_unref(msg);
        if (!done && expected > 0) {
            g_mutex_lock(&st.lock);
            done = st.pads.size() >= expected && st.caps.size() >= st.pads.size();
            g_mutex_unlock(&st.lock);
        }
        if (done)
            break;
    }
    gst_object_unref(bus);
    // NULL로 내리면 패드의 caps가 지워지므로 먼저 읽습니다.
    // CAPS 이벤트로 받은 것을 쓰고, 시간 안에 오지 않았으면 패드에 있는 caps로 대신합니다.
    g_mutex_lock(&st.lock);
    QList<GstCaps *> found = st.caps;
    st.caps.clear();
    if (found.size() < st.pads.size()) {
        for (GstPad *pad : std::as_const(st.pads)) {
            GstCaps *caps = gst_pad_get_current_caps(pad);
            if (!caps)
                caps = gst_pad_query_caps(pad, nullptr);
            if (caps)
                found << caps;
        }
    }
    for (GstCaps *caps : std::as_const(found)) {
        if (gst_caps_get_size(caps) > 0) {
            const QByteArray name = gst_structure_get_name(gst_caps_get_structure(caps, 0));
            if (name.startsWith("video/") && !out.video)
                out.video = gst_caps_ref(caps);
            else if (name.startsWith("audio/") && !out.audio)
                out.audio = gst_caps_ref(caps);
        }
        gst_caps_unref(caps);
    }
    for (GstPad *pad : std::as_const(st.pads))
        gst_object_unref(pad);
    st.pads.clear();
    // 스트림이 하나라도 나왔으면 (끝까지 준비되지 않았어도) 결과로 씁니다.
    out.ok = out.ok || out.video || out.audio;
    g_mutex_unlock(&st.lock);
    gst_element_set_state(st.pipeline, GST_STATE_NULL);
    // 결과를 읽은 뒤 스트리밍 스레드가 더 넣은 것 (NULL로 내리면 스레드가 끝나므로 이제 잠금 없이 정리)
    for (GstCaps *caps : std::as_const(st.caps))
        gst_caps_unref(caps);
    for (GstPad *pad : std::as_const(st.pads))
        gst_object_unref(pad);
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
