#include "Thumbnails.h"

#include "DecodeSelect.h"
#include "GstUtil.h"
#include "Paths.h"
#include "PlayerEngine.h"
#include "Scenes.h"

#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLoggingCategory>
#include <QSaveFile>

#include <gst/app/gstappsink.h>
#include <sys/stat.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <numeric>

Q_LOGGING_CATEGORY(lcThumbs, "jvp.thumbs")

namespace jvp {

namespace {
constexpr int kPlaybinVideo = 0x1, kPlaybinNativeVideo = 0x40;

QJsonArray toArray(const QList<qint64> &v)
{
    QJsonArray a;
    for (qint64 x : v)
        a.append(x);
    return a;
}

QList<qint64> fromArray(const QJsonValue &v)
{
    QList<qint64> out;
    for (const QJsonValue &x : v.toArray())
        out.append(x.toInteger(qint64(x.toDouble())));
    return out;
}

bool writeJsonAtomic(const QString &path, const QJsonObject &obj)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly))
        return false;
    f.write(QJsonDocument(obj).toJson(QJsonDocument::Indented));
    return f.commit();
}

// playbin + 사용자 영상 싱크 (NVDEC 출력(NVMM)을 nvvidconv로 줄인 뒤 CPU에서 최종 크기로)
GstElement *makePlaybin(const char *name, const QString &uri, const QString &sinkDesc, bool hw)
{
    GError *err = nullptr;
    GstElement *vbin = gst_parse_bin_from_description(sinkDesc.toUtf8().constData(), TRUE, &err);
    if (!vbin) {
        qCWarning(lcThumbs) << "영상 싱크 생성 실패:" << (err ? err->message : "");
        g_clear_error(&err);
        return nullptr;
    }
    GstElement *pb = gst_element_factory_make("playbin", name);
    if (!pb) {
        gst_object_unref(gst_object_ref_sink(vbin));
        return nullptr;
    }
    g_object_set(pb, "uri", uri.toUtf8().constData(), "video-sink", vbin, "audio-sink",
                 gst_element_factory_make("fakesink", nullptr), "flags",
                 hw ? (kPlaybinVideo | kPlaybinNativeVideo) : kPlaybinVideo, nullptr);
    if (!hw)
        decodeselect::forceSoftwareDecoding(pb);   // NVDEC가 못 여는 형식 → avdec_* 등 CPU 디코더
    return pb;
}

GstElement *findSink(GstElement *playbin)
{
    GstElement *vbin = nullptr;
    g_object_get(playbin, "video-sink", &vbin, nullptr);
    if (!vbin)
        return nullptr;
    GstElement *sink = gst_bin_get_by_name(GST_BIN(vbin), "sink");
    gst_object_unref(vbin);
    return sink;   // 참조를 가진 채 반환
}

struct Probe {
    qint64 duration = 0;
    double width = 0, height = 0;   // 화소 비율을 반영한 표시 크기
};

struct ParseState {
    GstElement *pipeline = nullptr;
    GMutex lock;
    QList<GstPad *> pads;
};

void onParsedPad(GstElement *, GstPad *pad, gpointer data)
{
    auto *st = static_cast<ParseState *>(data);
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

// 길이·크기·화소 비율을 디코딩 없이 읽습니다 (filesrc ! parsebin → 파싱된 caps + 길이 질의).
// GstDiscoverer는 디코더까지 붙여, 우선순위를 올려 둔 NVDEC가 못 여는 형식(HEVC 4:4:4 12비트 등)에서 실패합니다.
std::optional<Probe> probe(const QString &path, int timeoutSec = 5)
{
    ParseState st;
    g_mutex_init(&st.lock);
    st.pipeline = gst_pipeline_new("thumb_probe");
    GstElement *src = gst_element_factory_make("filesrc", nullptr);
    GstElement *parse = gst_element_factory_make("parsebin", nullptr);
    if (!src || !parse) {
        if (src)
            gst_object_unref(src);
        if (parse)
            gst_object_unref(parse);
        gst_object_unref(st.pipeline);
        g_mutex_clear(&st.lock);
        return std::nullopt;
    }
    g_object_set(src, "location", QFile::encodeName(QFileInfo(path).absoluteFilePath()).constData(), nullptr);
    gst_bin_add_many(GST_BIN(st.pipeline), src, parse, nullptr);
    gst_element_link(src, parse);
    g_signal_connect(parse, "pad-added", G_CALLBACK(onParsedPad), &st);

    gst_element_set_state(st.pipeline, GST_STATE_PAUSED);
    GstBus *bus = gst_element_get_bus(st.pipeline);
    GstMessage *msg = gst_bus_timed_pop_filtered(bus, GstClockTime(timeoutSec) * GST_SECOND,
                                                 GstMessageType(GST_MESSAGE_ASYNC_DONE | GST_MESSAGE_ERROR | GST_MESSAGE_EOS));
    const bool prerolled = msg && GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ASYNC_DONE;
    if (msg)
        gst_message_unref(msg);
    gst_object_unref(bus);
    Probe p;
    gint64 dur = 0;
    if (prerolled && gst_element_query_duration(st.pipeline, GST_FORMAT_TIME, &dur))
        p.duration = dur;
    g_mutex_lock(&st.lock);
    bool haveVideo = false;
    for (GstPad *pad : std::as_const(st.pads)) {
        if (!haveVideo) {
            GstCaps *caps = gst_pad_get_current_caps(pad);
            if (!caps)
                caps = gst_pad_query_caps(pad, nullptr);
            if (caps && gst_caps_get_size(caps) > 0) {
                const GstStructure *s = gst_caps_get_structure(caps, 0);
                int w = 0, h = 0, parN = 1, parD = 1;
                if (g_str_has_prefix(gst_structure_get_name(s), "video/") && gst_structure_get_int(s, "width", &w)
                    && gst_structure_get_int(s, "height", &h) && w > 0 && h > 0) {
                    if (!gst_structure_get_fraction(s, "pixel-aspect-ratio", &parN, &parD) || parN <= 0 || parD <= 0)
                        parN = parD = 1;
                    p.width = double(w) * parN / parD;
                    p.height = h;
                    haveVideo = true;
                }
            }
            if (caps)
                gst_caps_unref(caps);
        }
        gst_object_unref(pad);
    }
    st.pads.clear();
    g_mutex_unlock(&st.lock);
    gst_element_set_state(st.pipeline, GST_STATE_NULL);
    gst_object_unref(st.pipeline);
    g_mutex_clear(&st.lock);
    if (!haveVideo)
        return std::nullopt;
    return p;
}

void onDeepElementAdded(GstBin *, GstBin *, GstElement *element, gpointer)
{
    GstElementFactory *f = gst_element_get_factory(element);
    if (f && g_str_equal(gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(f)), "nvv4l2decoder")
        && g_object_class_find_property(G_OBJECT_GET_CLASS(element), "skip-frames"))
        g_object_set(element, "skip-frames", 1, nullptr);   // 비참조 프레임 건너뛰기
}
} // namespace

// ---- 인덱스 --------------------------------------------------------------------------

QString ThumbnailIndex::filePath(int i) const
{
    return (i >= 0 && i < files.size()) ? dir + QLatin1Char('/') + files[i] : QString();
}

QJsonObject ThumbnailIndex::toJson() const
{
    QJsonObject o{{"version", kThumbIndexVersion}, {"complete", true}, {"duration", duration},
                  {"positions", toArray(positions)}, {"files", QJsonArray::fromStringList(files)},
                  {"scenes", toArray(scenes)}};
    if (scenesPrecise)
        o.insert("scenes_precise", toArray(*scenesPrecise));
    return o;
}

ThumbnailIndex ThumbnailIndex::fromJson(const QJsonObject &o, const QString &dir)
{
    ThumbnailIndex idx;
    idx.dir = dir;
    idx.duration = o.value("duration").toInteger();
    idx.positions = fromArray(o.value("positions"));
    for (const QJsonValue &f : o.value("files").toArray())
        idx.files.append(f.toString());
    idx.scenes = fromArray(o.value("scenes"));
    if (o.contains("scenes_precise") && o.value("scenes_precise").isArray())
        idx.scenesPrecise = fromArray(o.value("scenes_precise"));
    return idx;
}

QString thumbnailCacheDir(const QString &videoPath)
{
    // os.path.abspath와 같이 심볼릭 링크는 풀지 않고 경로만 정리합니다.
    const QString abs = QDir::cleanPath(QFileInfo(videoPath).absoluteFilePath());
    QString key = abs;
    struct stat st {};
    if (::stat(QFile::encodeName(videoPath).constData(), &st) == 0)
        key = QStringLiteral("%1|%2|%3").arg(abs).arg(qint64(st.st_size)).arg(qint64(st.st_mtim.tv_sec));
    const QByteArray h = QCryptographicHash::hash(key.toUtf8(), QCryptographicHash::Sha1).toHex().left(20);
    return paths::thumbRoot() + QLatin1Char('/') + QString::fromLatin1(h);
}

std::optional<ThumbnailIndex> loadThumbnailIndex(const QString &videoPath)
{
    const QString dir = thumbnailCacheDir(videoPath);
    QFile f(dir + QStringLiteral("/index.json"));
    if (!f.open(QIODevice::ReadOnly))
        return std::nullopt;
    const QJsonObject o = QJsonDocument::fromJson(f.readAll()).object();
    if (o.value("version").toInt() != kThumbIndexVersion || !o.value("complete").toBool())
        return std::nullopt;
    return ThumbnailIndex::fromJson(o, dir);
}

int thumbnailSampleCount(qint64 durationNs)
{
    return std::max(20, std::min(120, int(double(durationNs) / GST_SECOND / 10)));
}

int nearestThumbnail(const ThumbnailIndex &index, qint64 ns, bool preferAfter)
{
    const auto &pos = index.positions;
    if (pos.isEmpty())
        return -1;
    int i = int(std::upper_bound(pos.begin(), pos.end(), ns) - pos.begin()) - 1;   // bisect_right - 1
    i = std::max(0, std::min(int(pos.size()) - 1, i));
    if (preferAfter && pos[i] < ns && i + 1 < pos.size())
        ++i;
    else if (i + 1 < pos.size() && std::llabs(pos[i + 1] - ns) < std::llabs(ns - pos[i]))
        ++i;   // 다음 썸네일이 더 가까우면 그것을 사용
    return i;
}

// ---- ThumbnailJob ----------------------------------------------------------------------

ThumbnailJob::ThumbnailJob(const QString &path, QObject *parent) : QObject(parent), m_path(path)
{
    PlayerEngine::initGStreamer();
    qRegisterMetaType<jvp::ThumbnailIndex>();
}

ThumbnailJob::~ThumbnailJob()
{
    cancel();
    if (m_thread.joinable())
        m_thread.join();
}

void ThumbnailJob::cancel() { m_cancelled = true; }

void ThumbnailJob::start()
{
    if (m_running || m_thread.joinable())
        return;
    if (auto cached = loadThumbnailIndex(m_path)) {
        QMetaObject::invokeMethod(this, [this, idx = *cached] { emit done(idx); }, Qt::QueuedConnection);
        return;
    }
    m_running = true;
    m_thread = std::thread([this] {
        generate();
        m_running = false;
    });
}

void ThumbnailJob::generate()
{
    auto fail = [this](const QString &why) {
        qCWarning(lcThumbs) << "⚠️ 썸네일 생성 실패" << QFileInfo(m_path).fileName() << why;
        if (!m_cancelled)
            QMetaObject::invokeMethod(this, [this, why] { emit failed(why); }, Qt::QueuedConnection);
    };
    const QString uri = pathToUri(QFileInfo(m_path).absoluteFilePath());
    const auto probed = probe(m_path);
    if (m_cancelled)
        return;
    if (!probed || probed->duration <= 0 || probed->width <= 0 || probed->height <= 0)
        return fail(QStringLiteral("영상 정보를 읽을 수 없습니다"));
    const qint64 duration = probed->duration;
    // 파이썬 round()와 같은 짝수 반올림
    const int thumbH = std::max(2, int(std::nearbyint(kThumbWidth * probed->height / probed->width / 2)) * 2);

    const QString outDir = thumbnailCacheDir(m_path);
    QDir().mkpath(outDir);
    // NVDEC → nvvidconv(NVMM에서 축소) 경로를 먼저 열고, 준비(preroll)에 실패하면 — NVDEC가 못 여는 형식
    // (HEVC 4:4:4·12비트 등) — 하드웨어 디코더를 건너뛰는 소프트웨어 경로로 다시 엽니다.
    GstElement *pb = nullptr, *sink = nullptr;
    auto open = [&](bool hw) {
        const QString head = hw ? QStringLiteral("nvvidconv ! video/x-raw,format=RGBA,width=%1,height=%2 ! ")
                                      .arg(kThumbWidth * 2).arg(thumbH * 2)
                                : QStringLiteral("videoconvert ! ");
        const QString desc = head + QStringLiteral("videoscale ! videoconvert ! video/x-raw,format=RGBA,width=%1,"
                                                   "height=%2,pixel-aspect-ratio=1/1 ! appsink name=sink sync=false "
                                                   "max-buffers=1")
                                        .arg(kThumbWidth).arg(thumbH);
        pb = makePlaybin("thumbnailer", uri, desc, hw);
        if (!pb)
            return false;
        sink = findSink(pb);
        gst_element_set_state(pb, GST_STATE_PAUSED);
        bool ok = sink && gst_element_get_state(pb, nullptr, nullptr, 10 * GST_SECOND) != GST_STATE_CHANGE_FAILURE;
        if (ok) {
            GstSample *s = gst_app_sink_try_pull_preroll(GST_APP_SINK(sink), 2 * GST_SECOND);
            ok = s != nullptr;
            if (s)
                gst_sample_unref(s);
        }
        if (!ok) {
            gst_element_set_state(pb, GST_STATE_NULL);
            if (sink)
                gst_object_unref(sink);
            gst_object_unref(pb);
            pb = sink = nullptr;
        }
        return ok;
    };
    const bool hw = hasElement("nvvidconv");
    bool opened = hw && open(true);
    if (!opened && !m_cancelled) {
        if (hw)
            qCInfo(lcThumbs) << "NVDEC로 열 수 없어 소프트웨어 디코딩으로 썸네일을 만듭니다:" << QFileInfo(m_path).fileName();
        opened = open(false);
    }
    if (m_cancelled && opened) {
        gst_element_set_state(pb, GST_STATE_NULL);
        gst_object_unref(sink);
        gst_object_unref(pb);
        return;
    }
    if (!opened)
        return m_cancelled ? void() : fail(QStringLiteral("썸네일 파이프라인 준비 실패"));

    const int n = thumbnailSampleCount(duration);
    QList<qint64> positions;
    QStringList files;
    std::vector<scenes::Signature> signatures;
    QElapsedTimer started;
    started.start();
    for (int i = 0; i < n && !m_cancelled; ++i) {
        const qint64 target = qint64(double(duration) * (i + 0.5) / n);
        gst_element_seek_simple(pb, GST_FORMAT_TIME, GstSeekFlags(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_KEY_UNIT), target);
        gst_element_get_state(pb, nullptr, nullptr, 3 * GST_SECOND);
        GstSample *sample = gst_app_sink_try_pull_preroll(GST_APP_SINK(sink), 2 * GST_SECOND);
        if (!sample)
            continue;
        GstBuffer *buf = gst_sample_get_buffer(sample);
        const qint64 pts = GST_BUFFER_PTS_IS_VALID(buf) ? qint64(GST_BUFFER_PTS(buf)) : target;
        if (!positions.isEmpty() && std::llabs(pts - positions.last()) < qint64(GST_SECOND / 2)) {
            gst_sample_unref(sample);
            continue;   // 같은 키프레임으로 다시 탐색된 경우
        }
        GstMapInfo map;
        if (!gst_buffer_map(buf, &map, GST_MAP_READ)) {
            gst_sample_unref(sample);
            continue;
        }
        const QString fname = QStringLiteral("%1.jpg").arg(files.size(), 3, 10, QLatin1Char('0'));
        bool saved = false;
        if (map.size >= size_t(kThumbWidth) * thumbH * 4) {
            const QImage img(map.data, kThumbWidth, thumbH, kThumbWidth * 4, QImage::Format_RGBA8888);
            saved = img.convertToFormat(QImage::Format_RGB888).save(outDir + QLatin1Char('/') + fname, "JPG", 80);
            if (saved)
                signatures.push_back(scenes::imageSignature(map.data, kThumbWidth, thumbH));
        }
        gst_buffer_unmap(buf, &map);
        gst_sample_unref(sample);
        if (!saved)
            continue;
        positions.append(pts);
        files.append(fname);
        if (files.size() % 10 == 0) {
            ThumbnailIndex snap;
            snap.dir = outDir;
            snap.duration = duration;
            snap.positions = positions;
            snap.files = files;
            QMetaObject::invokeMethod(this, [this, snap] { emit progress(snap); }, Qt::QueuedConnection);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));   // 재생 중인 영상의 디코딩/IO에 양보
    }
    // NVDEC 디코더 세션 반납
    gst_element_set_state(pb, GST_STATE_NULL);
    gst_object_unref(sink);
    gst_object_unref(pb);
    if (m_cancelled)
        return;
    if (files.isEmpty())
        return fail(QStringLiteral("썸네일을 하나도 추출하지 못했습니다"));

    // 추출 순서와 무관하게 시간순 정렬 후 장면 전환 검출
    std::vector<int> order(files.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) { return positions[a] < positions[b]; });
    ThumbnailIndex idx;
    idx.dir = outDir;
    idx.duration = duration;
    std::vector<scenes::Signature> sigs;
    for (int k : order) {
        idx.positions.append(positions[k]);
        idx.files.append(files[k]);
        sigs.push_back(signatures[size_t(k)]);
    }
    idx.scenes = scenes::detectSceneChanges(sigs, idx.positions, duration);
    if (!writeJsonAtomic(outDir + QStringLiteral("/index.json"), idx.toJson()))
        qCWarning(lcThumbs) << "index.json 저장 실패:" << outDir;
    qCInfo(lcThumbs).noquote() << QStringLiteral("🖼️ [썸네일] %1장, 장면 전환 %2곳 (%3초): %4")
                                      .arg(idx.files.size()).arg(idx.scenes.size())
                                      .arg(started.elapsed() / 1000.0, 0, 'f', 1).arg(QFileInfo(m_path).fileName());
    QMetaObject::invokeMethod(this, [this, idx] { emit done(idx); }, Qt::QueuedConnection);
}

// ---- SceneAnalysisJob ----------------------------------------------------------------------

SceneAnalysisJob::SceneAnalysisJob(const QString &path, QObject *parent) : QObject(parent), m_path(path)
{
    PlayerEngine::initGStreamer();
}

SceneAnalysisJob::~SceneAnalysisJob()
{
    cancel();
    if (m_thread.joinable())
        m_thread.join();
}

void SceneAnalysisJob::cancel() { m_cancelled = true; }

void SceneAnalysisJob::start()
{
    if (m_running || m_thread.joinable())
        return;
    m_running = true;
    m_thread = std::thread([this] {
        QString error;
        bool sawFrame = false;
        const bool hw = hasElement("nvvidconv");
        auto result = analyze(hw, &error, &sawFrame);
        if (!result && hw && !sawFrame && !m_cancelled) {
            // NVDEC가 못 여는 형식(HEVC 4:4:4·12비트 등): 소프트웨어 디코더로 다시 분석
            qCInfo(lcThumbs) << "NVDEC로 열 수 없어 소프트웨어 디코딩으로 장면을 분석합니다:" << error;
            error.clear();
            result = analyze(false, &error, &sawFrame);
        }
        if (!error.isEmpty())
            qCWarning(lcThumbs) << "⚠️ 장면 분석 실패:" << error;
        m_running = false;
        const bool ok = result.has_value() && !m_cancelled;
        const QList<qint64> scenes = ok ? *result : QList<qint64>();
        QMetaObject::invokeMethod(this, [this, scenes, ok] { emit done(scenes, ok); }, Qt::QueuedConnection);
    });
}

std::optional<QList<qint64>> SceneAnalysisJob::analyze(bool hw, QString *error, bool *sawFrame)
{
    *sawFrame = false;
    const QString uri = pathToUri(QFileInfo(m_path).absoluteFilePath());
    const QString head = hw ? QStringLiteral("nvvidconv ! video/x-raw,format=RGBA,width=320,height=180 ! ")
                            : QStringLiteral("videoconvert ! ");
    GstElement *pb = makePlaybin("scene_analyzer", uri,
                                 head + QStringLiteral("videoscale ! videoconvert ! video/x-raw,format=RGBA,width=16,"
                                                       "height=9 ! appsink name=sink sync=false max-buffers=8"),
                                 hw);
    if (!pb) {
        *error = QStringLiteral("파이프라인 생성 실패");
        return std::nullopt;
    }
    g_signal_connect(pb, "deep-element-added", G_CALLBACK(onDeepElementAdded), nullptr);
    GstElement *sinkEl = findSink(pb);
    GstAppSink *sink = GST_APP_SINK(sinkEl);
    GstBus *bus = gst_element_get_bus(pb);

    std::vector<float> diffs;
    QList<qint64> positions;
    std::vector<float> prev;
    qint64 duration = 0;
    double lastReport = 0.0;
    QElapsedTimer started;
    started.start();
    gst_element_set_state(pb, GST_STATE_PLAYING);
    bool finished = false;
    while (!m_cancelled && !finished) {
        while (GstMessage *msg = gst_bus_pop_filtered(
                   bus, GstMessageType(GST_MESSAGE_EOS | GST_MESSAGE_ERROR | GST_MESSAGE_ASYNC_DONE))) {
            if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ERROR) {
                GError *err = nullptr;
                gst_message_parse_error(msg, &err, nullptr);
                *error = err ? QString::fromUtf8(err->message) : QStringLiteral("오류");
                g_clear_error(&err);
                finished = true;
            } else if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ASYNC_DONE && duration == 0) {
                gint64 d = 0;
                if (gst_element_query_duration(pb, GST_FORMAT_TIME, &d))
                    duration = d;
            }
            // EOS는 appsink가 마지막 샘플까지 내보낸 뒤 is_eos로 확인합니다
            gst_message_unref(msg);
        }
        if (finished)
            break;
        GstSample *sample = gst_app_sink_try_pull_sample(sink, 100 * GST_MSECOND);
        if (!sample) {
            if (gst_app_sink_is_eos(sink))
                break;
            continue;
        }
        GstBuffer *buf = gst_sample_get_buffer(sample);
        *sawFrame = true;
        GstMapInfo map;
        if (gst_buffer_map(buf, &map, GST_MAP_READ)) {
            const int n = scenes::kSignatureW * scenes::kSignatureH;
            std::vector<float> sig(size_t(n) * 3);
            if (map.size >= size_t(n) * 4)
                for (int p = 0; p < n; ++p)
                    for (int c = 0; c < 3; ++c)
                        sig[size_t(p) * 3 + c] = map.data[p * 4 + c];
            gst_buffer_unmap(buf, &map);
            if (!prev.empty()) {
                double s = 0;
                for (size_t k = 0; k < sig.size(); ++k)
                    s += std::abs(sig[k] - prev[k]);
                diffs.push_back(float(s / sig.size()));
                positions.append(qint64(GST_BUFFER_PTS(buf)));
            }
            prev = std::move(sig);
        }
        if (duration > 0 && GST_BUFFER_PTS_IS_VALID(buf)) {
            const double p = std::min(1.0, double(GST_BUFFER_PTS(buf)) / duration);
            m_progress = p;
            if (p - lastReport >= 0.02) {
                lastReport = p;
                QMetaObject::invokeMethod(this, [this, p] { emit progress(p); }, Qt::QueuedConnection);
            }
        }
        gst_sample_unref(sample);
    }
    gst_element_set_state(pb, GST_STATE_NULL);   // NVDEC 디코더 세션 반납
    gst_object_unref(bus);
    if (sinkEl)
        gst_object_unref(sinkEl);
    gst_object_unref(pb);
    if (m_cancelled || !error->isEmpty())
        return std::nullopt;

    if (duration <= 0)
        duration = positions.isEmpty() ? 0 : positions.last();
    const auto found = scenes::sceneChangesFromDiffs(diffs, positions, duration, 6.0,
                                                     double(std::max<qint64>(3 * GST_SECOND, duration / 100)), 80);
    qCInfo(lcThumbs).noquote() << QStringLiteral("🎬 [정밀 장면 분석] 프레임 %1개, 장면 전환 %2곳 (%3초)")
                                      .arg(diffs.size() + 1).arg(found.size()).arg(started.elapsed() / 1000.0, 0, 'f', 1);
    const QString indexFile = thumbnailCacheDir(m_path) + QStringLiteral("/index.json");
    QFile f(indexFile);
    if (f.open(QIODevice::ReadOnly)) {
        QJsonParseError perr{};
        QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &perr);
        f.close();
        if (perr.error == QJsonParseError::NoError && doc.isObject()) {
            QJsonObject o = doc.object();
            o.insert("scenes_precise", toArray(found));
            writeJsonAtomic(indexFile, o);
        }
    }
    return found;
}

} // namespace jvp
