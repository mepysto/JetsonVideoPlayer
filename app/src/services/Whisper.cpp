#include "Whisper.h"

#include "DecodeSelect.h"
#include "GstUtil.h"
#include "Paths.h"
#include "PlayerEngine.h"

#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QProcess>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QThread>

#include <gst/gst.h>
#include <unistd.h>

Q_LOGGING_CATEGORY(lcWhisper, "jvp.whisper")

namespace jvp::ai {

namespace {
const QRegularExpression &segmentRe()
{
    static const QRegularExpression re(
        QStringLiteral(R"(^\[(\d+):(\d+):(\d+)\.(\d+)\s*-->\s*(\d+):(\d+):(\d+)\.(\d+)\]\s*(.*)$)"));
    return re;
}

qint64 toMs(const QString &h, const QString &m, const QString &s, const QString &frac)
{
    // "25" → 250ms (파이썬 frac.ljust(3, "0")[:3])
    const QString f = (frac + QStringLiteral("000")).left(3);
    return ((h.toLongLong() * 60 + m.toLongLong()) * 60 + s.toLongLong()) * 1000 + f.toLongLong();
}

bool isExecutableFile(const QString &p)
{
    QFileInfo fi(p);
    return !p.isEmpty() && fi.isFile() && fi.isExecutable();
}

const QString kCancelled = QStringLiteral("취소됨");
} // namespace

QString whisperHome()
{
    const QString env = qEnvironmentVariable("JVP_WHISPER_DIR");
    return env.isEmpty() ? paths::dataDir() + QStringLiteral("/whisper.cpp") : env;
}

QString findWhisperBinary()
{
    const QStringList candidates{qEnvironmentVariable("JVP_WHISPER_BIN"),
                                 whisperHome() + QStringLiteral("/build/bin/whisper-cli"),
                                 QStandardPaths::findExecutable(QStringLiteral("whisper-cli"))};
    for (const QString &c : candidates)
        if (isExecutableFile(c))
            return c;
    return {};
}

QStringList listWhisperModels()
{
    static const QRegularExpression re(QStringLiteral("^ggml-(.+)\\.bin$"));
    QStringList names;
    const QDir dir(whisperHome() + QStringLiteral("/models"));
    for (const QString &f : dir.entryList(QDir::Files | QDir::NoDotAndDotDot)) {
        const auto m = re.match(f);
        if (m.hasMatch())
            names << m.captured(1);
    }
    names.sort();
    return names;
}

QString findWhisperModel(const QString &modelName)
{
    const QString modelDir = whisperHome() + QStringLiteral("/models");
    const QString preferred = modelDir + QStringLiteral("/ggml-%1.bin").arg(modelName);
    if (QFileInfo(preferred).isFile())
        return preferred;
    QStringList found;
    for (const QString &f : QDir(modelDir).entryList(QDir::Files))
        if (f.startsWith(QLatin1String("ggml-")) && f.endsWith(QLatin1String(".bin")))
            found << f;
    found.sort();
    return found.isEmpty() ? QString() : modelDir + QLatin1Char('/') + found.first();
}

bool whisperAvailable(const QString &modelName)
{
    return !findWhisperBinary().isEmpty() && !findWhisperModel(modelName).isEmpty();
}

QString modelNote(const QString &modelName)
{
    // 알려진 모델 설명 (Orin Nano 8GB, 60초 음성 실측)
    if (modelName == QLatin1String("small-q5_1"))
        return QStringLiteral("기본 — 60초 음성 4.6초, 메모리 약 1.0GB");
    if (modelName == QLatin1String("large-v3-turbo-q5_0"))
        return QStringLiteral("더 정확 — 60초 음성 6.4초, 메모리 약 1.4GB");
    return {};
}

QString languageName(const QString &code)
{
    static const QHash<QString, QString> names{{"ko", "한국어"}, {"en", "영어"},       {"ja", "일본어"},
                                               {"zh", "중국어"}, {"es", "스페인어"}, {"fr", "프랑스어"},
                                               {"de", "독일어"}, {"ru", "러시아어"}};
    return names.value(code, code);
}

std::optional<Segment> parseWhisperLine(const QString &line)
{
    const auto m = segmentRe().match(line.trimmed());
    if (!m.hasMatch())
        return std::nullopt;
    const QString text = m.captured(9).trimmed();
    if (text.isEmpty() || text == QLatin1String("[BLANK_AUDIO]") || text == QLatin1String("[Music]")
        || text == QStringLiteral("[음악]") || (text.startsWith('[') && text.endsWith(']')))
        return std::nullopt;
    const qint64 start = toMs(m.captured(1), m.captured(2), m.captured(3), m.captured(4));
    const qint64 end = toMs(m.captured(5), m.captured(6), m.captured(7), m.captured(8));
    if (end <= start)
        return std::nullopt;
    return Segment{start, end, text};
}

QString parseDetectedLanguage(const QString &line)
{
    static const QRegularExpression re(QStringLiteral("auto-detected language:\\s*([a-z]{2,3})"));
    const auto m = re.match(line);
    return m.hasMatch() ? m.captured(1) : QString();
}

QList<QPair<qint64, qint64>> planPasses(qint64 durationMs, qint64 startMs, qint64 firstChunkMs, qint64 chunkMs)
{
    startMs = std::max<qint64>(0, std::min(startMs, durationMs));
    if (startMs < 30000)
        startMs = 0;
    QList<QPair<qint64, qint64>> passes;
    const QPair<qint64, qint64> ranges[2] = {{startMs, durationMs}, {0, startMs}};
    for (const auto &r : ranges) {
        for (qint64 pos = r.first; pos < r.second;) {
            const qint64 size = passes.isEmpty() ? firstChunkMs : chunkMs;
            const qint64 length = std::min(size, r.second - pos);
            passes.append({pos, length});
            pos += length;
        }
    }
    return passes;
}

QString formatSrt(Segments events)
{
    std::sort(events.begin(), events.end());
    auto ts = [](qint64 ms) {
        const qint64 h = ms / 3600000, m = ms % 3600000 / 60000, s = ms % 60000 / 1000, r = ms % 1000;
        return QStringLiteral("%1:%2:%3,%4").arg(h, 2, 10, QLatin1Char('0')).arg(m, 2, 10, QLatin1Char('0'))
            .arg(s, 2, 10, QLatin1Char('0')).arg(r, 3, 10, QLatin1Char('0'));
    };
    QStringList lines;
    int n = 1;
    for (const auto &e : events)
        lines << QString::number(n++) << ts(e.startMs) + QStringLiteral(" --> ") + ts(e.endMs) << e.text << QString();
    return lines.join(QLatin1Char('\n'));
}

QString fileStem(const QString &path)
{
    // os.path.splitext: 앞쪽 점(숨김 파일)은 확장자로 보지 않습니다.
    const QString base = QFileInfo(path).fileName();
    int lead = 0;
    while (lead < base.size() && base[lead] == QLatin1Char('.'))
        ++lead;
    const int dot = base.lastIndexOf(QLatin1Char('.'));
    return dot > lead ? base.left(dot) : base;
}

QString cachedAiSubtitleStem(const QString &videoPath)
{
    const QString folder = QDir::cleanPath(QFileInfo(videoPath).absolutePath());
    const QByteArray h = QCryptographicHash::hash(folder.toUtf8(), QCryptographicHash::Sha1).toHex().left(8);
    return fileStem(videoPath) + QLatin1Char('.') + QString::fromLatin1(h);
}

QString aiSubtitlePathFor(const QString &videoPath, const QString &language, bool translate, bool folderWritable)
{
    const QString lang = translate ? QStringLiteral("en") : (language.isEmpty() ? QStringLiteral("auto") : language);
    if (folderWritable)
        return QDir::cleanPath(QFileInfo(videoPath).absolutePath()) + QLatin1Char('/') + fileStem(videoPath)
               + QStringLiteral(".ai.%1.srt").arg(lang);
    QDir().mkpath(paths::aiSubtitleCacheDir());
    return paths::aiSubtitleCacheDir() + QLatin1Char('/') + cachedAiSubtitleStem(videoPath)
           + QStringLiteral(".ai.%1.srt").arg(lang);
}

QString aiSubtitlePath(const QString &videoPath, const QString &language, bool translate)
{
    const QString folder = QFileInfo(videoPath).absolutePath();
    return aiSubtitlePathFor(videoPath, language, translate, ::access(QFile::encodeName(folder).constData(), W_OK) == 0);
}

namespace {
struct ExtractState {
    GstElement *conv = nullptr;
    std::atomic<bool> audio{false};
    std::atomic<bool> complete{false};
};

void onExtractPad(GstElement *, GstPad *pad, gpointer data)
{
    auto *st = static_cast<ExtractState *>(data);
    GstCaps *caps = gst_pad_get_current_caps(pad);
    if (!caps)
        caps = gst_pad_query_caps(pad, nullptr);
    const bool isAudio = caps && gst_caps_get_size(caps) > 0
                         && g_str_equal(gst_structure_get_name(gst_caps_get_structure(caps, 0)), "audio/x-raw");
    if (caps)
        gst_caps_unref(caps);
    if (!isAudio)
        return;
    st->audio = true;
    GstPad *target = gst_element_get_static_pad(st->conv, "sink");
    if (!gst_pad_is_linked(target))
        gst_pad_link(pad, target);
    gst_object_unref(target);
}
} // namespace

QString extractAudioWav(const QString &videoPath, const QString &wavPath, const std::function<bool()> &cancelled)
{
    // 파이썬 버전은 decodebin으로 영상까지 디코딩했지만, 여기서는 음량 측정과 같이 영상·자막 디코더를 고르지 않습니다
    // (빠르고, NVDEC가 못 여는 영상(HEVC 4:4:4 등) 때문에 음성 추출이 실패하지 않음).
    PlayerEngine::initGStreamer();
    GstElement *pipeline = gst_pipeline_new("ai_audio");
    GstElement *src = gst_element_factory_make("uridecodebin", nullptr);
    GstElement *conv = gst_element_factory_make("audioconvert", nullptr);
    GstElement *resample = gst_element_factory_make("audioresample", nullptr);
    GstElement *capsf = gst_element_factory_make("capsfilter", nullptr);
    GstElement *wavenc = gst_element_factory_make("wavenc", nullptr);
    GstElement *out = gst_element_factory_make("filesink", nullptr);
    if (!src || !conv || !resample || !capsf || !wavenc || !out) {
        for (GstElement *e : {src, conv, resample, capsf, wavenc, out})
            if (e)
                gst_object_unref(e);
        gst_object_unref(pipeline);
        return QStringLiteral("음성 추출 실패: GStreamer 요소가 없습니다");
    }
    ExtractState st;
    st.conv = conv;
    g_object_set(src, "uri", pathToUri(QFileInfo(videoPath).absoluteFilePath()).toUtf8().constData(), nullptr);
    GstCaps *audioCaps = gst_caps_from_string("audio/x-raw");
    g_object_set(src, "caps", audioCaps, nullptr);
    gst_caps_unref(audioCaps);
    g_signal_connect(src, "autoplug-select", G_CALLBACK(decodeselect::skipNonAudioDecoders), nullptr);
    g_signal_connect(src, "pad-added", G_CALLBACK(onExtractPad), &st);
    g_signal_connect(src, "no-more-pads", G_CALLBACK(+[](GstElement *, gpointer d) {
                         static_cast<ExtractState *>(d)->complete = true;
                     }),
                     &st);
    GstCaps *fmt = gst_caps_from_string("audio/x-raw,rate=16000,channels=1,format=S16LE");
    g_object_set(capsf, "caps", fmt, nullptr);
    gst_caps_unref(fmt);
    g_object_set(out, "location", QFile::encodeName(wavPath).constData(), nullptr);
    gst_bin_add_many(GST_BIN(pipeline), src, conv, resample, capsf, wavenc, out, nullptr);
    gst_element_link_many(conv, resample, capsf, wavenc, out, nullptr);

    GstBus *bus = gst_element_get_bus(pipeline);
    gst_element_set_state(pipeline, GST_STATE_PLAYING);
    QString error;
    while (true) {
        if (cancelled && cancelled()) {
            error = kCancelled;
            break;
        }
        GstMessage *msg = gst_bus_timed_pop_filtered(bus, 200 * GST_MSECOND,
                                                     GstMessageType(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
        if (!msg)
            continue;
        if (GST_MESSAGE_TYPE(msg) == GST_MESSAGE_ERROR) {
            GError *e = nullptr;
            gst_message_parse_error(msg, &e, nullptr);
            if (st.complete && !st.audio)
                error = QStringLiteral("영상에 음성 트랙이 없습니다.");
            else
                error = QStringLiteral("음성 추출 실패: %1").arg(e ? QString::fromUtf8(e->message) : QString());
            g_clear_error(&e);
        }
        gst_message_unref(msg);
        break;
    }
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(bus);
    gst_object_unref(pipeline);
    if (error.isEmpty() && QFileInfo(wavPath).size() <= 44)
        error = QStringLiteral("영상에 음성 트랙이 없습니다.");
    return error;
}

// ---- AiSubtitleJob ------------------------------------------------------------------------

AiSubtitleJob::AiSubtitleJob(const QString &videoPath, qint64 durationMs, qint64 startMs, const QString &language,
                             bool translate, const QString &modelName, QObject *parent)
    : QObject(parent), m_videoPath(videoPath), m_durationMs(durationMs), m_startMs(startMs), m_language(language),
      m_translate(translate), m_modelName(modelName)
{
    qRegisterMetaType<jvp::ai::Segments>();
}

AiSubtitleJob::~AiSubtitleJob()
{
    cancel();
    if (m_thread) {
        m_thread->wait();
        delete m_thread;
    }
}

void AiSubtitleJob::start()
{
    if (m_thread)
        return;
    m_thread = QThread::create([this] { run(); });
    m_thread->setObjectName(QStringLiteral("ai-subtitles"));
    m_thread->start(QThread::LowPriority);
}

void AiSubtitleJob::cancel() { m_cancelled = true; }

bool AiSubtitleJob::isRunning() const { return m_thread && m_thread->isRunning(); }

QString AiSubtitleJob::detectedLanguage() const { return m_detectedForOwner; }

void AiSubtitleJob::run()
{
    QString error, srtPath;
    QString detected;
    auto emitStatus = [this](const QString &text, double frac) {
        QMetaObject::invokeMethod(this, [this, text, frac] { emit status(text, frac); }, Qt::QueuedConnection);
    };
    QTemporaryDir workdir(QDir::tempPath() + QStringLiteral("/jvp_ai_XXXXXX"));
    [&] {
        const QString binary = findWhisperBinary(), model = findWhisperModel(m_modelName);
        if (binary.isEmpty() || model.isEmpty()) {
            error = QStringLiteral("whisper.cpp가 설치되어 있지 않습니다. ./scripts/setup_whisper.sh 를 실행하세요.");
            return;
        }
        emitStatus(QStringLiteral("🎧 음성 추출 중..."), 0.0);
        const QString wav = workdir.filePath(QStringLiteral("audio.wav"));
        error = extractAudioWav(m_videoPath, wav, [this] { return m_cancelled.load(); });
        if (!error.isEmpty())
            return;
        QElapsedTimer started;
        started.start();
        qint64 processed = 0;
        for (const auto &pass : planPasses(m_durationMs, m_startMs)) {
            if (m_cancelled)
                break;
            error = transcribe(binary, model, wav, pass.first, pass.second);
            if (!error.isEmpty())
                return;
            processed += pass.second;
            const double frac = m_durationMs ? double(processed) / m_durationMs : 0.0;
            emitStatus(QStringLiteral("🤖 AI 자막 생성 중 %1%").arg(qRound(frac * 100)), frac);
        }
        if (m_cancelled) {
            error = kCancelled;
            return;
        }
        if (m_events.isEmpty()) {
            error = QStringLiteral("인식된 대사가 없습니다.");
            return;
        }
        const QString lang = m_translate ? QStringLiteral("en") : (m_detected.isEmpty() ? m_language : m_detected);
        srtPath = aiSubtitlePath(m_videoPath, lang, m_translate);
        QFile f(srtPath);
        if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
            error = QStringLiteral("저장 실패: %1").arg(f.errorString());
            srtPath.clear();
            return;
        }
        f.write(formatSrt(m_events).toUtf8());
        qCInfo(lcWhisper).noquote() << QStringLiteral("🤖 [AI 자막] %1문장, %2초 → %3")
                                           .arg(m_events.size()).arg(started.elapsed() / 1000.0, 0, 'f', 1).arg(srtPath);
    }();
    if (m_cancelled && error.isEmpty())
        error = kCancelled;
    detected = m_detected;
    QMetaObject::invokeMethod(
        this,
        [this, srtPath, detected, error] {
            m_detectedForOwner = detected;
            emit done(srtPath, detected, error);
        }, Qt::QueuedConnection);
}

QString AiSubtitleJob::transcribe(const QString &binary, const QString &model, const QString &wav, qint64 offsetMs,
                                  qint64 lengthMs)
{
    const QString lang = !m_detected.isEmpty() ? m_detected : (m_language.isEmpty() ? QStringLiteral("auto") : m_language);
    QStringList args{"-m", model, "-f", wav, "-l", lang, "-ot", QString::number(offsetMs), "-d",
                     QString::number(lengthMs), "-t", "4"};
    if (m_translate)
        args << "-tr";
    QProcess proc;   // 작업 스레드에서 만들고 동기식으로 읽습니다 (이벤트 루프 불필요)
    proc.start(binary, args);
    if (!proc.waitForStarted(10000))
        return QStringLiteral("whisper-cli 실행 실패: %1").arg(proc.errorString());
    QByteArray outBuf, errBuf;
    Segments batch;
    QElapsedTimer lastFlush;
    lastFlush.start();
    auto consumeLines = [](QByteArray &buf, const std::function<void(const QString &)> &fn) {
        int nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
            fn(QString::fromUtf8(buf.left(nl)));
            buf.remove(0, nl + 1);
        }
    };
    auto onOut = [&](const QString &line) {
        if (auto seg = parseWhisperLine(line))
            batch.append(*seg);
    };
    auto onErr = [&](const QString &line) {
        const QString code = parseDetectedLanguage(line);
        if (!code.isEmpty() && m_detected.isEmpty())
            m_detected = code;
    };
    bool running = true;
    while (running) {
        if (m_cancelled) {
            proc.terminate();
            if (!proc.waitForFinished(3000))
                proc.kill();
            proc.waitForFinished(1000);
            return kCancelled;
        }
        proc.waitForReadyRead(100);
        running = proc.state() != QProcess::NotRunning;
        outBuf += proc.readAllStandardOutput();
        errBuf += proc.readAllStandardError();
        consumeLines(outBuf, onOut);
        consumeLines(errBuf, onErr);
        if (!batch.isEmpty() && lastFlush.elapsed() > 500) {
            flush(batch);
            lastFlush.restart();
        }
    }
    proc.waitForFinished(1000);
    outBuf += proc.readAllStandardOutput() + '\n';
    errBuf += proc.readAllStandardError() + '\n';
    consumeLines(outBuf, onOut);
    consumeLines(errBuf, onErr);
    if (!batch.isEmpty())
        flush(batch);
    // 파이썬 버전과 같이 종료 코드는 보지 않습니다 (일부 구간 실패는 다음 구간으로 넘어감)
    if (proc.exitStatus() == QProcess::CrashExit)
        qCWarning(lcWhisper) << "whisper-cli 비정상 종료 (구간" << offsetMs << "ms)";
    return {};
}

void AiSubtitleJob::flush(Segments &batch)
{
    m_events += batch;
    const Segments copy = batch;
    batch.clear();
    QMetaObject::invokeMethod(this, [this, copy] { emit segments(copy); }, Qt::QueuedConnection);
}

} // namespace jvp::ai
