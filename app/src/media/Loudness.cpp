#include "Loudness.h"

#include "DecodeSelect.h"
#include "GstUtil.h"
#include "PlayerEngine.h"

#include <QFileInfo>
#include <QLoggingCategory>
#include <QMetaObject>

#include <gst/app/gstappsink.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>

Q_LOGGING_CATEGORY(lcLoudness, "jvp.loudness")

namespace jvp::loudness {

namespace {
constexpr std::array<double, 3> kShelfB{1.53512485958697, -2.69169618940638, 1.19839281085285};
constexpr std::array<double, 3> kShelfA{1.0, -1.69065929318241, 0.73248077421585};
constexpr std::array<double, 3> kHpfB{1.0, -2.0, 1.0};
constexpr std::array<double, 3> kHpfA{1.0, -1.99004745483398, 0.99007225036621};

std::array<double, 5> convolve(const std::array<double, 3> &a, const std::array<double, 3> &b)
{
    std::array<double, 5> r{};
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            r[i + j] += a[i] * b[j];
    return r;
}

double blockLoudness(double meanSquare) { return -0.691 + 10.0 * std::log10(meanSquare); }

// audioiirfilter의 계수 속성은 (폐기 예정인) GValueArray입니다 — 다른 형식으로는 설정되지 않습니다.
void setCoefficients(GstElement *filter, const char *name, const std::array<double, 5> &values)
{
    G_GNUC_BEGIN_IGNORE_DEPRECATIONS
    GValueArray *arr = g_value_array_new(values.size());
    for (double x : values) {
        GValue v = G_VALUE_INIT;
        g_value_init(&v, G_TYPE_DOUBLE);
        g_value_set_double(&v, x);
        g_value_array_append(arr, &v);
        g_value_unset(&v);
    }
    g_object_set(filter, name, arr, nullptr);
    g_value_array_free(arr);
    G_GNUC_END_IGNORE_DEPRECATIONS
}

} // namespace

const std::array<double, 5> &kWeightB()
{
    static const auto b = convolve(kShelfB, kHpfB);
    return b;
}

const std::array<double, 5> &kWeightA()
{
    static const auto a = convolve(kShelfA, kHpfA);
    return a;
}

void LoudnessMeter::feed(const float *interleaved, size_t samples)
{
    const size_t frames = samples / 2;
    for (size_t f = 0; f < frames; ++f) {
        const double l = interleaved[2 * f], r = interleaved[2 * f + 1];
        m_pendingSum += l * l + r * r;
        if (++m_pendingFrames == kStep) {
            m_steps.push_back(m_pendingSum);
            m_pendingSum = 0.0;
            m_pendingFrames = 0;
        }
    }
}

std::optional<double> LoudnessMeter::integrated() const
{
    if (m_steps.size() < 4)
        return std::nullopt;
    std::vector<double> gated;
    for (size_t i = 0; i + 3 < m_steps.size(); ++i) {
        const double block = (m_steps[i] + m_steps[i + 1] + m_steps[i + 2] + m_steps[i + 3]) / (kRate * kBlockSec);
        if (block > 0 && blockLoudness(block) > kAbsoluteGate)
            gated.push_back(block);
    }
    if (gated.empty())
        return std::nullopt;
    double sum = 0;
    for (double b : gated)
        sum += b;
    const double relative = blockLoudness(sum / gated.size()) + kRelativeGate;
    double finalSum = 0;
    size_t n = 0;
    for (double b : gated) {
        if (blockLoudness(b) > relative) {
            finalSum += b;
            ++n;
        }
    }
    if (!n)
        return std::nullopt;
    return blockLoudness(finalSum / n);
}

double gainFor(std::optional<double> lufs, double target)
{
    if (!lufs)
        return 0.0;
    return std::max(-kMaxCutDb, std::min(kMaxBoostDb, target - *lufs));
}

MeterPipeline::MeterPipeline(const QString &uri)
{
    PlayerEngine::initGStreamer();
    m_pipeline = gst_pipeline_new("loudness");
    GstElement *src = gst_element_factory_make("uridecodebin", nullptr);
    m_conv = gst_element_factory_make("audioconvert", nullptr);
    GstElement *resample = gst_element_factory_make("audioresample", nullptr);
    GstElement *caps = gst_element_factory_make("capsfilter", nullptr);
    GstElement *kweight = gst_element_factory_make("audioiirfilter", nullptr);
    m_sink = gst_element_factory_make("appsink", nullptr);
    if (!src || !m_conv || !resample || !caps || !kweight || !m_sink) {
        for (GstElement *e : {src, m_conv, resample, caps, kweight, m_sink})
            if (e)
                gst_object_unref(e);
        m_conv = m_sink = nullptr;
        return;   // 파이프라인은 비어 있어 PLAYING에서 곧 오류 없이 멈추지 않도록 measureFile이 확인합니다
    }
    g_object_set(src, "uri", uri.toUtf8().constData(), nullptr);
    GstCaps *audio = gst_caps_from_string("audio/x-raw");
    g_object_set(src, "caps", audio, nullptr);
    gst_caps_unref(audio);
    // caps만으로는 영상 디코더가 붙는 것을 막지 못합니다 — 영상·자막 디코더는 고르지 않고 버립니다.
    g_signal_connect(src, "autoplug-select", G_CALLBACK(decodeselect::skipNonAudioDecoders), nullptr);
    g_signal_connect(src, "pad-added", G_CALLBACK(onPadAdded), this);
    g_signal_connect(src, "no-more-pads", G_CALLBACK(onNoMorePads), this);

    GstCaps *fmt = gst_caps_from_string(
        QStringLiteral("audio/x-raw,format=F32LE,layout=interleaved,rate=%1,channels=2").arg(kRate).toUtf8().constData());
    g_object_set(caps, "caps", fmt, nullptr);
    gst_caps_unref(fmt);
    setCoefficients(kweight, "b", kWeightB());
    setCoefficients(kweight, "a", kWeightA());
    g_object_set(m_sink, "sync", FALSE, "max-buffers", 32, nullptr);

    gst_bin_add_many(GST_BIN(m_pipeline), src, m_conv, resample, caps, kweight, m_sink, nullptr);
    gst_element_link_many(m_conv, resample, caps, kweight, m_sink, nullptr);
}

MeterPipeline::~MeterPipeline()
{
    if (m_pipeline) {
        gst_element_set_state(m_pipeline, GST_STATE_NULL);
        gst_object_unref(m_pipeline);
    }
}

void MeterPipeline::onPadAdded(GstElement *, GstPad *pad, gpointer self)
{
    auto *p = static_cast<MeterPipeline *>(self);
    GstCaps *caps = gst_pad_get_current_caps(pad);
    if (!caps)
        caps = gst_pad_query_caps(pad, nullptr);
    if (!caps)
        return;
    const bool isAudio = gst_caps_get_size(caps) > 0
                         && g_str_equal(gst_structure_get_name(gst_caps_get_structure(caps, 0)), "audio/x-raw");
    gst_caps_unref(caps);
    if (!isAudio)
        return;
    p->m_audio = true;
    GstPad *target = gst_element_get_static_pad(p->m_conv, "sink");
    if (!gst_pad_is_linked(target))
        gst_pad_link(pad, target);
    gst_object_unref(target);
}

void MeterPipeline::onNoMorePads(GstElement *, gpointer self) { static_cast<MeterPipeline *>(self)->m_complete = true; }

MeasureResult measureFile(const QString &path, const std::function<bool()> &cancelled, int timeoutSec)
{
    MeterPipeline mp(pathToUri(QFileInfo(path).absoluteFilePath()));
    if (!mp.sink())
        return {std::nullopt, QStringLiteral("GStreamer 요소가 없습니다 (audioiirfilter 등)")};
    GstElement *pipeline = mp.pipeline();
    GstAppSink *sink = GST_APP_SINK(mp.sink());
    LoudnessMeter meter;
    GstBus *bus = gst_element_get_bus(pipeline);
    gst_element_set_state(pipeline, GST_STATE_PLAYING);
    MeasureResult result;
    double waited = 0.0;
    while (!(cancelled && cancelled())) {
        if (GstSample *sample = gst_app_sink_try_pull_sample(sink, 200 * GST_MSECOND)) {
            GstBuffer *buf = gst_sample_get_buffer(sample);
            GstMapInfo info;
            if (buf && gst_buffer_map(buf, &info, GST_MAP_READ)) {
                meter.feed(reinterpret_cast<const float *>(info.data), info.size / sizeof(float));
                gst_buffer_unmap(buf, &info);
            }
            gst_sample_unref(sample);
            continue;
        }
        if (GstMessage *msg = gst_bus_pop_filtered(bus, GstMessageType(GST_MESSAGE_EOS | GST_MESSAGE_ERROR))) {
            if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ERROR) {
                GError *err = nullptr;
                gst_message_parse_error(msg, &err, nullptr);
                const QString text = err ? QString::fromUtf8(err->message) : QStringLiteral("오류");
                g_clear_error(&err);
                gst_message_unref(msg);
                if (mp.streamsComplete() && !mp.sawAudio())
                    result = {};                       // 스트림을 다 확인했는데 오디오가 없는 파일
                else
                    result = {std::nullopt, text};
                gst_object_unref(bus);
                return result;
            }
            gst_message_unref(msg);
            result.lufs = meter.integrated();
            break;
        }
        if (gst_app_sink_is_eos(sink)) {
            result.lufs = meter.integrated();
            break;
        }
        waited += 0.2;
        if (waited > timeoutSec) {
            result = {std::nullopt, QStringLiteral("시간 초과")};
            break;
        }
    }
    gst_object_unref(bus);
    return result;   // MeterPipeline 소멸자가 NULL로 내려 디코더를 반납합니다
}

} // namespace jvp::loudness

namespace jvp {

LoudnessJob::LoudnessJob(const QString &path, QObject *parent) : QObject(parent), m_path(path)
{
    PlayerEngine::initGStreamer();
}

LoudnessJob::~LoudnessJob()
{
    cancel();
    if (m_thread.joinable())
        m_thread.join();
}

void LoudnessJob::start()
{
    if (m_running || m_thread.joinable())
        return;
    m_running = true;
    m_thread = std::thread([this] {
        // 재생을 방해하지 않게 이 스레드만 우선순위를 낮춥니다 (리눅스는 스레드별 nice)
        setpriority(PRIO_PROCESS, static_cast<id_t>(syscall(SYS_gettid)), 15);
        const auto res = loudness::measureFile(m_path, [this] { return m_cancelled.load(); });
        m_running = false;
        if (m_cancelled)
            return;
        const QVariant lufs = res.lufs ? QVariant(*res.lufs) : QVariant();
        if (!res.ok())
            qCWarning(lcLoudness) << "음량 측정 실패:" << QFileInfo(m_path).fileName() << res.error;
        QMetaObject::invokeMethod(this, [this, lufs, err = res.error] { emit done(lufs, err); }, Qt::QueuedConnection);
    });
}

void LoudnessJob::cancel() { m_cancelled = true; }

} // namespace jvp
