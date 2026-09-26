#include "PlayerEngine.h"

#include <QLoggingCategory>
#include <QRegularExpression>
#include <cmath>
#include <functional>
#include <QSize>
#include <QUrl>

#include <gst/app/gstappsink.h>
#include <gst/tag/tag.h>
#include <gst/video/video.h>

Q_LOGGING_CATEGORY(lcEngine, "jvp.engine")

namespace jvp {

QString pathToUri(const QString &path)
{
    if (path.startsWith(QLatin1String("http://")) || path.startsWith(QLatin1String("https://"))
        || path.startsWith(QLatin1String("file://")))
        return path;
    return QUrl::fromLocalFile(path).toString(QUrl::FullyEncoded);
}

namespace {
// playbin flags: video | audio | text | soft-volume | native-video(0x40, NVMM 유지)
constexpr int kFlagVideo = 0x1, kFlagAudio = 0x2, kFlagText = 0x4, kFlagSoftVolume = 0x10, kFlagNativeVideo = 0x40;
// NVDEC 추가 표면 수: 파이썬 버전은 32개로 4K에서 수백 MB를 썼습니다. 재생 안정성에는 8개면 충분합니다.
constexpr int kNvdecExtraSurfaces = 8;

void setRank(const char *name, int rank)
{
    GstPluginFeature *f = gst_registry_find_feature(gst_registry_get(), name, GST_TYPE_ELEMENT_FACTORY);
    if (f) {
        gst_plugin_feature_set_rank(f, rank);
        gst_object_unref(f);
    }
}
} // namespace

void PlayerEngine::initGStreamer()
{
    static bool done = false;
    if (done)
        return;
    done = true;
    gst_init(nullptr, nullptr);
    if (hasElement("nvv4l2decoder")) {
        // Jetson 하드웨어 디코더를 우선. 지원하지 않는 형식이면 decodebin이 소프트웨어 디코더로 넘어갑니다.
        setRank("nvv4l2decoder", GST_RANK_PRIMARY + 1000);
        setRank("nvvidconv", GST_RANK_PRIMARY + 1000);
        for (const char *p : {"av1parse", "h264parse", "h265parse", "vp9parse"})
            setRank(p, GST_RANK_PRIMARY + 1500);
        qCInfo(lcEngine) << "⚡ NVDEC 하드웨어 디코더 우선 사용";
    } else {
        qCInfo(lcEngine) << "ℹ️ NVDEC가 없어 소프트웨어 디코딩을 사용합니다";
    }
}

PlayerEngine::PlayerEngine(QObject *parent) : QObject(parent), m_bridge(new FrameBridge(this))
{
    initGStreamer();
}

PlayerEngine::~PlayerEngine() { stop(); }

GstElement *PlayerEngine::buildVideoSink(bool hw)
{
    GstElement *bin = gst_bin_new("video_out");
    GstElement *sink = gst_element_factory_make("appsink", "video_sink");
    GstElement *conv = nullptr;
    GstCaps *caps = nullptr;
    if (hw && hasElement("nvvidconv")) {
        // VIC 하드웨어가 NV12/P010 → RGBA 변환, 결과는 GPU 메모리(NVMM)에 그대로 → EGLImage로 화면에
        conv = gst_element_factory_make("nvvidconv", "hw_conv");
        caps = gst_caps_from_string("video/x-raw(memory:NVMM),format=RGBA");
    } else {
        conv = gst_element_factory_make("videoconvert", "sw_conv");
        caps = gst_caps_from_string("video/x-raw,format={I420,NV12}");
    }
    g_object_set(sink, "caps", caps, "sync", TRUE, "qos", TRUE, nullptr);
    gst_caps_unref(caps);
    gst_bin_add_many(GST_BIN(bin), conv, sink, nullptr);
    gst_element_link(conv, sink);
    GstPad *pad = gst_element_get_static_pad(conv, "sink");
    gst_element_add_pad(bin, gst_ghost_pad_new("sink", pad));
    gst_object_unref(pad);
    m_bridge->attach(sink);
    return bin;
}

GstElement *PlayerEngine::buildAudioSink(bool passthrough, int avOffsetMs)
{
    m_eq = m_nightDyn = m_nightGain = m_loudness = nullptr;
    if (passthrough) {
        // 압축 오디오(AC3/DTS)를 그대로 받는 싱크 — 효과·볼륨·배속 없음
        m_audioSink = gst_element_factory_make("pulsesink", "asink");
        return m_audioSink;
    }
    m_audioSink = gst_element_factory_make("autoaudiosink", "asink");
    if (!m_audioSink)
        m_audioSink = gst_element_factory_make("fakesink", "asink");
    if (avOffsetMs)
        g_object_set(m_audioSink, "ts-offset", gint64(avOffsetMs) * GST_MSECOND, nullptr);

    GstElement *conv = gst_element_factory_make("audioconvert", nullptr);
    GstElement *tempo = gst_element_factory_make("scaletempo", nullptr);   // 배속에서도 음정 유지
    GstElement *resample = gst_element_factory_make("audioresample", nullptr);
    if (!conv || !tempo || !resample)
        return m_audioSink;
    m_eq = gst_element_factory_make("equalizer-10bands", "eq");
    m_nightDyn = gst_element_factory_make("audiodynamic", "night_dynamic");
    m_nightGain = gst_element_factory_make("volume", "night_gain");
    m_loudness = gst_element_factory_make("volume", "loudness_gain");
    GstElement *limiter = gst_element_factory_make("rglimiter", nullptr);   // 이득을 올려도 찢어지지 않게
    if (m_nightDyn)
        g_object_set(m_nightDyn, "characteristics", 1 /* soft-knee */, "mode", 0 /* compressor */, nullptr);

    GstElement *bin = gst_bin_new("audio_out");
    QList<GstElement *> chain{conv, tempo};
    for (GstElement *e : {m_eq, m_nightDyn, m_nightGain, m_loudness, limiter})
        if (e)
            chain << e;
    chain << resample << m_audioSink;
    for (GstElement *e : chain)
        gst_bin_add(GST_BIN(bin), e);
    for (int i = 0; i + 1 < chain.size(); ++i)
        gst_element_link(chain[i], chain[i + 1]);
    GstPad *pad = gst_element_get_static_pad(conv, "sink");
    gst_element_add_pad(bin, gst_ghost_pad_new("sink", pad));
    gst_object_unref(pad);
    return bin;
}

bool PlayerEngine::open(const QString &uri, const OpenOptions &opt)
{
    stop();
    m_pipeline = gst_element_factory_make("playbin", "player");
    if (!m_pipeline)
        return false;
    m_hwOutput = opt.hwOutput && hasElement("nvvidconv");
    m_passthrough = opt.passthrough;
    m_keepAssRaw = opt.keepAssRaw;
    m_rate = opt.rate;
    m_decoder.clear();

    int flags = kFlagVideo | kFlagAudio | kFlagText | kFlagSoftVolume;
    if (m_hwOutput)
        flags |= kFlagNativeVideo;
    g_object_set(m_pipeline, "flags", flags, "uri", uri.toUtf8().constData(), nullptr);
    g_object_set(m_pipeline, "video-sink", buildVideoSink(m_hwOutput), nullptr);
    g_object_set(m_pipeline, "audio-sink", buildAudioSink(opt.passthrough, opt.avOffsetMs), nullptr);

    // 내장 자막은 appsink로 받아 오버레이가 그립니다 (playbin이 영상에 합성하지 않음).
    GstElement *textSink = gst_element_factory_make("appsink", "text_sink");
    g_object_set(textSink, "sync", FALSE, "async", FALSE, "emit-signals", TRUE, nullptr);
    g_signal_connect(textSink, "new-sample", G_CALLBACK(&PlayerEngine::onTextSample), this);
    g_object_set(m_pipeline, "text-sink", textSink, nullptr);

    g_signal_connect(m_pipeline, "deep-element-added", G_CALLBACK(&PlayerEngine::onDeepElementAdded), this);
    // 오디오/자막 트랙 수가 바뀌면 (스트리밍 스레드) → 메인 스레드로
    auto streams = +[](GstElement *, gpointer self) {
        auto *e = static_cast<PlayerEngine *>(self);
        QMetaObject::invokeMethod(e, &PlayerEngine::streamsChanged, Qt::QueuedConnection);
    };
    g_signal_connect(m_pipeline, "audio-changed", G_CALLBACK(streams), this);
    g_signal_connect(m_pipeline, "text-changed", G_CALLBACK(streams), this);
    GstBus *bus = gst_element_get_bus(m_pipeline);
    m_busWatch = gst_bus_add_watch(bus, &PlayerEngine::onBusMessage, this);
    gst_object_unref(bus);

    m_pendingSeek = opt.startNs;
    m_rateAppliedOnPreroll = qFuzzyCompare(opt.rate, 1.0);
    // 중간 위치에서 시작하거나 배속을 적용해야 하면 PAUSED로 준비한 뒤 ASYNC_DONE에서 탐색 → 재생
    const bool needPreroll = m_pendingSeek > 0 || !m_rateAppliedOnPreroll;
    return gst_element_set_state(m_pipeline, needPreroll ? GST_STATE_PAUSED : GST_STATE_PLAYING)
           != GST_STATE_CHANGE_FAILURE;
}

void PlayerEngine::stop()
{
    if (!m_pipeline)
        return;
    if (m_busWatch) {
        g_source_remove(m_busWatch);
        m_busWatch = 0;
    }
    gst_element_set_state(m_pipeline, GST_STATE_NULL);
    gst_object_unref(m_pipeline);
    m_pipeline = nullptr;
    m_eq = m_nightDyn = m_nightGain = m_loudness = m_audioSink = nullptr;
    m_bridge->clear();
    if (m_playing) {
        m_playing = false;
        emit playingChanged(false);
    }
}

void PlayerEngine::play()
{
    if (m_pipeline)
        gst_element_set_state(m_pipeline, GST_STATE_PLAYING);
}

void PlayerEngine::pause()
{
    if (m_pipeline)
        gst_element_set_state(m_pipeline, GST_STATE_PAUSED);
}

bool PlayerEngine::seek(qint64 ns, SeekMode mode)
{
    if (!m_pipeline || ns < 0)
        return false;
    // seek_simple은 배속을 1.0으로 되돌리므로 항상 현재 배속을 넘깁니다.
    return gst_element_seek(m_pipeline, m_rate, GST_FORMAT_TIME, seekFlags(mode), GST_SEEK_TYPE_SET, ns,
                            GST_SEEK_TYPE_NONE, GST_CLOCK_TIME_NONE);
}

bool PlayerEngine::setRate(double rate)
{
    m_rate = rate;
    if (!m_pipeline)
        return true;
    const qint64 pos = position();
    return gst_element_seek(m_pipeline, rate, GST_FORMAT_TIME, seekFlags(SeekMode::Accurate), GST_SEEK_TYPE_SET,
                            qMax<qint64>(0, pos), GST_SEEK_TYPE_NONE, GST_CLOCK_TIME_NONE);
}

void PlayerEngine::stepFrame(int direction)
{
    if (!m_pipeline)
        return;
    if (direction > 0) {
        gst_element_send_event(m_pipeline, gst_event_new_step(GST_FORMAT_BUFFERS, 1, qAbs(m_rate), TRUE, FALSE));
    } else {
        const qint64 pos = position();
        if (pos >= 0)
            seek(qMax<qint64>(0, pos - 40 * GST_MSECOND), SeekMode::Accurate);
    }
}

qint64 PlayerEngine::position() const
{
    gint64 pos = -1;
    if (m_pipeline && gst_element_query_position(m_pipeline, GST_FORMAT_TIME, &pos))
        return pos;
    return -1;
}

qint64 PlayerEngine::duration() const
{
    gint64 dur = -1;
    if (m_pipeline && gst_element_query_duration(m_pipeline, GST_FORMAT_TIME, &dur))
        return dur;
    return -1;
}

void PlayerEngine::setVolume(double linear)
{
    if (m_pipeline)
        g_object_set(m_pipeline, "volume", qBound(0.0, linear, 2.0), nullptr);
}

void PlayerEngine::setMuted(bool muted)
{
    if (m_pipeline)
        g_object_set(m_pipeline, "mute", muted, nullptr);
}

void PlayerEngine::setAvOffsetMs(int ms)
{
    if (m_audioSink && g_object_class_find_property(G_OBJECT_GET_CLASS(m_audioSink), "ts-offset"))
        g_object_set(m_audioSink, "ts-offset", gint64(ms) * GST_MSECOND, nullptr);
}

static int intProp(GstElement *e, const char *name)
{
    gint v = 0;
    if (e)
        g_object_get(e, name, &v, nullptr);
    return v;
}

int PlayerEngine::audioTrackCount() const { return intProp(m_pipeline, "n-audio"); }
int PlayerEngine::currentAudioTrack() const { return intProp(m_pipeline, "current-audio"); }
void PlayerEngine::setAudioTrack(int index)
{
    if (m_pipeline)
        g_object_set(m_pipeline, "current-audio", index, nullptr);
}
int PlayerEngine::textTrackCount() const { return intProp(m_pipeline, "n-text"); }
int PlayerEngine::currentTextTrack() const { return intProp(m_pipeline, "current-text"); }
void PlayerEngine::setTextTrack(int index)
{
    if (m_pipeline)
        g_object_set(m_pipeline, "current-text", index, nullptr);
}

QString PlayerEngine::textTrackLanguage(int index) const
{
    if (!m_pipeline)
        return {};
    GstTagList *tags = nullptr;
    g_signal_emit_by_name(m_pipeline, "get-text-tags", index, &tags);
    QString lang;
    if (tags) {
        gchar *code = nullptr;
        if (gst_tag_list_get_string(tags, GST_TAG_LANGUAGE_CODE, &code))
            lang = takeString(code);
        gst_tag_list_unref(tags);
    }
    return lang;
}

void PlayerEngine::setEqualizer(const QList<double> &bandsDb)
{
    if (!m_eq)
        return;
    for (int i = 0; i < bandsDb.size() && i < 10; ++i)
        g_object_set(m_eq, QByteArray("band" + QByteArray::number(i)).constData(), bandsDb[i], nullptr);
}

void PlayerEngine::setNightMode(bool on)
{
    // 큰 소리는 압축하고 전체를 끌어올려 작은 대사가 잘 들리게 (파이썬 버전과 같은 값)
    if (m_nightDyn)
        g_object_set(m_nightDyn, "threshold", on ? 0.12f : 1.0f, "ratio", on ? 0.25f : 1.0f, nullptr);
    if (m_nightGain)
        g_object_set(m_nightGain, "volume", on ? 2.2 : 1.0, nullptr);
}

void PlayerEngine::setLoudnessGainDb(double db)
{
    if (m_loudness)
        g_object_set(m_loudness, "volume", std::pow(10.0, db / 20.0), nullptr);
}

QString PlayerEngine::activeVideoDecoder() const { return m_decoder; }

static GstCaps *videoPadCaps(GstElement *pipeline)
{
    if (!pipeline)
        return nullptr;
    GstPad *pad = nullptr;
    g_signal_emit_by_name(pipeline, "get-video-pad", 0, &pad);
    if (!pad)
        return nullptr;
    GstCaps *caps = gst_pad_get_current_caps(pad);
    gst_object_unref(pad);
    return caps;
}

QString PlayerEngine::videoTransfer() const
{
    GstCaps *caps = videoPadCaps(m_pipeline);
    if (!caps)
        return {};
    QString result;
    GstVideoInfo info;
    if (gst_video_info_from_caps(&info, caps)) {
        if (info.colorimetry.transfer == GST_VIDEO_TRANSFER_SMPTE2084)
            result = QStringLiteral("pq");
        else if (info.colorimetry.transfer == GST_VIDEO_TRANSFER_ARIB_STD_B67)
            result = QStringLiteral("hlg");
    }
    gst_caps_unref(caps);
    return result;
}

QSize PlayerEngine::videoSize() const
{
    GstCaps *caps = videoPadCaps(m_pipeline);
    QSize s;
    GstVideoInfo info;
    if (caps && gst_video_info_from_caps(&info, caps))
        s = QSize(GST_VIDEO_INFO_WIDTH(&info), GST_VIDEO_INFO_HEIGHT(&info));
    if (caps)
        gst_caps_unref(caps);
    return s;
}

// ---- 콜백 ----------------------------------------------------------------------------

void PlayerEngine::onDeepElementAdded(GstBin *, GstBin *, GstElement *element, gpointer self)
{
    auto *e = static_cast<PlayerEngine *>(self);
    GstElementFactory *factory = gst_element_get_factory(element);
    const QString name = factory ? fromUtf8(GST_OBJECT_NAME(factory)) : QString();
    const QString klass = factory ? fromUtf8(gst_element_factory_get_metadata(factory, GST_ELEMENT_METADATA_KLASS)) : QString();
    if (name == QLatin1String("decodebin"))
        g_signal_connect(element, "autoplug-continue", G_CALLBACK(&PlayerEngine::onAutoplugContinue), self);
    if (name == QLatin1String("nvv4l2decoder")) {
        auto set = [&](const char *prop, auto value) {
            if (g_object_class_find_property(G_OBJECT_GET_CLASS(element), prop))
                g_object_set(element, prop, value, nullptr);
        };
        set("enable-max-performance", TRUE);
        set("num-extra-surfaces", kNvdecExtraSurfaces);
        set("drop-frame-interval", 0);
        set("max-errors", -1);
    }
    if (name == QLatin1String("dav1ddec") && g_object_class_find_property(G_OBJECT_GET_CLASS(element), "max-threads"))
        g_object_set(element, "max-threads", 6, nullptr);
    if (klass.contains(QLatin1String("Decoder")) && klass.contains(QLatin1String("Video"))) {
        const bool hw = name == QLatin1String("nvv4l2decoder");
        QMetaObject::invokeMethod(e, [e, name, hw] {
            e->m_decoder = name;
            e->m_decoderIsHw = hw;
            emit e->decoderSelected(name, hw);
        }, Qt::QueuedConnection);
    }
}

gboolean PlayerEngine::onAutoplugContinue(GstElement *, GstPad *, GstCaps *caps, gpointer self)
{
    // 내장 ASS/SSA 자막은 ssaparse가 텍스트로 바꾸기 전에 받아 원래 스타일·위치로 그립니다.
    auto *e = static_cast<PlayerEngine *>(self);
    if (e->m_keepAssRaw && caps && gst_caps_get_size(caps)) {
        const gchar *n = gst_structure_get_name(gst_caps_get_structure(caps, 0));
        if (g_str_equal(n, "application/x-ass") || g_str_equal(n, "application/x-ssa"))
            return FALSE;
    }
    return TRUE;
}

GstFlowReturn PlayerEngine::onTextSample(GstElement *sink, gpointer self)
{
    auto *e = static_cast<PlayerEngine *>(self);
    GstSample *sample = gst_app_sink_pull_sample(GST_APP_SINK(sink));
    if (!sample)
        return GST_FLOW_OK;
    GstBuffer *buf = gst_sample_get_buffer(sample);
    if (buf && GST_BUFFER_PTS_IS_VALID(buf)) {
        GstMapInfo map;
        if (gst_buffer_map(buf, &map, GST_MAP_READ)) {
            const QString raw = QString::fromUtf8(reinterpret_cast<const char *>(map.data), int(map.size));
            gst_buffer_unmap(buf, &map);
            const qint64 start = GST_BUFFER_PTS(buf) / GST_MSECOND;
            const qint64 dur = GST_BUFFER_DURATION_IS_VALID(buf) ? GST_BUFFER_DURATION(buf) / GST_MSECOND : 4000;
            const qint64 end = start + qMax<qint64>(200, dur);
            GstCaps *caps = gst_sample_get_caps(sample);
            const GstStructure *st = caps && gst_caps_get_size(caps) ? gst_caps_get_structure(caps, 0) : nullptr;
            const QString name = st ? fromUtf8(gst_structure_get_name(st)) : QString();
            if (name == QLatin1String("application/x-ass") || name == QLatin1String("application/x-ssa")) {
                QString header;
                const GValue *v = gst_structure_get_value(st, "codec_data");
                if (v && GST_VALUE_HOLDS_BUFFER(v)) {
                    GstBuffer *cd = gst_value_get_buffer(v);
                    GstMapInfo cm;
                    if (gst_buffer_map(cd, &cm, GST_MAP_READ)) {
                        header = QString::fromUtf8(reinterpret_cast<const char *>(cm.data), int(cm.size));
                        gst_buffer_unmap(cd, &cm);
                    }
                }
                emit e->embeddedAss(header, start, end, raw);
            } else {
                const gchar *fmt = st ? gst_structure_get_string(st, "format") : nullptr;
                QString text = raw;
                if (!fmt || !g_str_equal(fmt, "utf8")) {
                    // pango-markup → 순수 텍스트
                    static const QRegularExpression tag(QStringLiteral("<[^>]+>"));
                    text.remove(tag);
                    text.replace(QLatin1String("&lt;"), QLatin1String("<")).replace(QLatin1String("&gt;"), QLatin1String(">"))
                        .replace(QLatin1String("&amp;"), QLatin1String("&")).replace(QLatin1String("&quot;"), QLatin1String("\""))
                        .replace(QLatin1String("&apos;"), QLatin1String("'"));
                }
                if (!text.trimmed().isEmpty())
                    emit e->embeddedText(start, end, text.trimmed());
            }
        }
    }
    gst_sample_unref(sample);
    return GST_FLOW_OK;
}

gboolean PlayerEngine::onBusMessage(GstBus *, GstMessage *msg, gpointer self)
{
    static_cast<PlayerEngine *>(self)->handleMessage(msg);
    return TRUE;
}

void PlayerEngine::handleMessage(GstMessage *msg)
{
    switch (GST_MESSAGE_TYPE(msg)) {
    case GST_MESSAGE_EOS:
        emit endOfStream();
        break;
    case GST_MESSAGE_ERROR: {
        GError *err = nullptr;
        gchar *dbg = nullptr;
        gst_message_parse_error(msg, &err, &dbg);
        const QString message = err ? fromUtf8(err->message) : QStringLiteral("unknown error");
        const QString debug = takeString(dbg);
        if (err)
            g_error_free(err);
        // 오디오 싱크(패스스루)에서 난 오류인지
        bool fromAudio = false;
        for (GstObject *o = GST_MESSAGE_SRC(msg); o; o = GST_OBJECT_PARENT(o))
            if (o == GST_OBJECT(m_audioSink))
                fromAudio = true;
        emit errorOccurred(message, debug, fromAudio && m_passthrough);
        break;
    }
    case GST_MESSAGE_ASYNC_DONE:
        if (m_pendingSeek > 0) {
            const qint64 ns = m_pendingSeek;
            m_pendingSeek = 0;
            m_rateAppliedOnPreroll = true;
            seek(ns, SeekMode::Accurate);
            play();
        } else if (!m_rateAppliedOnPreroll) {
            m_rateAppliedOnPreroll = true;
            seek(0, SeekMode::Accurate);
            play();
        }
        emit asyncDone();
        break;
    case GST_MESSAGE_STATE_CHANGED:
        if (GST_MESSAGE_SRC(msg) == GST_OBJECT(m_pipeline)) {
            GstState oldState, newState, pending;
            gst_message_parse_state_changed(msg, &oldState, &newState, &pending);
            const bool playing = newState == GST_STATE_PLAYING;
            if (playing != m_playing) {
                m_playing = playing;
                emit playingChanged(playing);
            }
        }
        break;
    case GST_MESSAGE_STREAM_COLLECTION:
    case GST_MESSAGE_STREAMS_SELECTED:
        emit streamsChanged();
        break;
    case GST_MESSAGE_TOC: {
        GstToc *toc = nullptr;
        gboolean updated = FALSE;
        gst_message_parse_toc(msg, &toc, &updated);
        QVariantList chapters;
        std::function<void(GList *)> visit = [&](GList *entries) {
            for (GList *l = entries; l; l = l->next) {
                auto *entry = static_cast<GstTocEntry *>(l->data);
                if (gst_toc_entry_get_entry_type(entry) == GST_TOC_ENTRY_TYPE_CHAPTER) {
                    gint64 start = -1, stopTime = -1;
                    if (gst_toc_entry_get_start_stop_times(entry, &start, &stopTime) && start >= 0) {
                        QString title;
                        if (GstTagList *tags = gst_toc_entry_get_tags(entry)) {
                            gchar *t = nullptr;
                            if (gst_tag_list_get_string(tags, GST_TAG_TITLE, &t))
                                title = takeString(t);
                        }
                        if (title.isEmpty())
                            title = QStringLiteral("챕터 %1").arg(chapters.size() + 1);
                        chapters.append(QVariantMap{{"ns", qint64(start)}, {"title", title}});
                    }
                }
                visit(gst_toc_entry_get_sub_entries(entry));
            }
        };
        visit(gst_toc_get_entries(toc));
        gst_toc_unref(toc);
        if (!chapters.isEmpty())
            emit chaptersFound(chapters);
        break;
    }
    default:
        break;
    }
}

} // namespace jvp
