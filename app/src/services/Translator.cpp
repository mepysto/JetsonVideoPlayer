#include "Translator.h"

#include "Paths.h"

#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLoggingCategory>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QProcess>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QThread>
#include <QTimer>

Q_LOGGING_CATEGORY(lcTranslate, "jvp.translate")

namespace jvp::ai {

namespace {
const QString kCancelled = QStringLiteral("취소됨");

// 파이썬 len()과 같게 코드 포인트 수로 셉니다.
int cpLen(const QString &s) { return int(s.toUcs4().size()); }

bool endsSentence(const QString &w)
{
    static const QStringList ends{".", "?", "!", "。", "？", "！", "…", "\"", "”"};
    for (const QString &e : ends)
        if (w.endsWith(e))
            return true;
    return false;
}
} // namespace

// ---- 설치·설정 ----------------------------------------------------------------------------

QString nllbHome()
{
    const QString env = qEnvironmentVariable("JVP_NLLB_DIR");
    return env.isEmpty() ? paths::dataDir() + QStringLiteral("/nllb") : env;
}

QPair<QString, QString> nllbPaths() { return {nllbHome() + QStringLiteral("/pylib"), nllbHome() + QStringLiteral("/model")}; }

QString nllbCode(const QString &lang)
{
    static const QHash<QString, QString> codes{{"ko", "kor_Hang"}, {"en", "eng_Latn"}, {"ja", "jpn_Jpan"},
                                               {"zh", "zho_Hans"}, {"es", "spa_Latn"}, {"fr", "fra_Latn"},
                                               {"de", "deu_Latn"}, {"ru", "rus_Cyrl"}};
    return codes.value(lang);
}

QList<QPair<QString, QString>> targetLanguages()
{
    return {{"ko", "Korean (한국어)"}, {"en", "English"}, {"ja", "Japanese (日本語)"}, {"zh", "Simplified Chinese (简体中文)"}};
}

QString targetLanguageName(const QString &code)
{
    for (const auto &p : targetLanguages())
        if (p.first == code)
            return p.second;
    return {};
}

bool localAvailable()
{
    const auto [pylib, model] = nllbPaths();
    return QFileInfo(pylib + QStringLiteral("/ctranslate2")).isDir() && QFileInfo(model + QStringLiteral("/model.bin")).isFile()
           && QFileInfo(model + QStringLiteral("/sentencepiece.bpe.model")).isFile();
}

bool claudeAvailable()
{
    // 파이썬 SDK는 `ant auth login` 프로필(~/.config/anthropic)도 쓰지만, C++에서는 환경 변수 인증만 지원합니다.
    return !qEnvironmentVariable("ANTHROPIC_API_KEY").isEmpty() || !qEnvironmentVariable("ANTHROPIC_AUTH_TOKEN").isEmpty();
}

QString resolveBackend(const QString &preference)
{
    if ((preference == QLatin1String("local") || preference == QLatin1String("auto")) && localAvailable())
        return QStringLiteral("local");
    if ((preference == QLatin1String("claude") || preference == QLatin1String("auto")) && claudeAvailable())
        return QStringLiteral("claude");
    return {};
}

QString nllbWorkerScript()
{
    QStringList candidates{qEnvironmentVariable("JVP_NLLB_WORKER")};
    if (QCoreApplication::instance()) {
        const QString appDir = QCoreApplication::applicationDirPath();
        candidates << appDir + "/nllb_worker.py" << appDir + "/../share/jetson-player/nllb_worker.py"
                   << appDir + "/../tools/nllb_worker.py" << appDir + "/../../tools/nllb_worker.py";
    }
    // 개발 중(빌드 폴더에서 실행): 소스 트리의 app/tools
    candidates << QFileInfo(QStringLiteral(__FILE__)).absolutePath() + "/../../tools/nllb_worker.py";
    for (const QString &c : candidates)
        if (!c.isEmpty() && QFileInfo(c).isFile())
            return QFileInfo(c).canonicalFilePath();
    return {};
}

// ---- 문장 재분할·요청 구성 -------------------------------------------------------------------

Segments resegmentSentences(const Segments &input, int maxChars, qint64 maxGapMs)
{
    Segments events = input;
    std::sort(events.begin(), events.end());
    struct Word {
        qint64 start, end;
        QString text;
    };
    std::vector<Word> words;
    // 각 줄의 단어에 글자 위치 비율로 시각을 배분합니다.
    for (const auto &ev : events) {
        const QStringList tokens = ev.text.split(QRegularExpression(QStringLiteral("\\s+")), Qt::SkipEmptyParts);
        qint64 total = 0;
        for (const QString &t : tokens)
            total += cpLen(t) + 1;
        if (!total)
            total = 1;
        qint64 pos = 0;
        for (const QString &tok : tokens) {
            const qint64 wStart = ev.startMs + (ev.endMs - ev.startMs) * pos / total;
            pos += cpLen(tok) + 1;
            words.push_back({wStart, ev.startMs + (ev.endMs - ev.startMs) * pos / total, tok});
        }
    }
    Segments sentences;
    std::vector<Word> cur;
    auto curLen = [&] {
        qint64 n = 0;
        for (const auto &w : cur)
            n += cpLen(w.text) + 1;
        return n;
    };
    auto flush = [&] {
        if (cur.empty())
            return;
        QStringList parts;
        for (const auto &w : cur)
            parts << w.text;
        sentences.append({cur.front().start, std::max(cur.back().end, cur.front().start + 800), parts.join(' ')});
        cur.clear();
    };
    for (const auto &w : words) {
        if (!cur.empty() && (w.start - cur.back().end > maxGapMs || curLen() + cpLen(w.text) > maxChars))
            flush();
        cur.push_back(w);
        if (endsSentence(w.text))
            flush();
    }
    flush();
    return sentences;
}

QJsonObject translationSchema(int count)
{
    return QJsonObject{
        {"type", "object"},
        {"properties",
         QJsonObject{{"translations", QJsonObject{{"type", "array"}, {"items", QJsonObject{{"type", "string"}}},
                                                  {"minItems", count}, {"maxItems", count}}}}},
        {"required", QJsonArray{"translations"}},
        {"additionalProperties", false},
    };
}

QString systemPrompt(const QString &targetCode)
{
    return QStringLiteral(
               "You translate video subtitles. Translate each numbered line into %1. "
               "Keep each translation short enough to read as a subtitle, keep names consistent, and keep the tone of speech. "
               "Lines under 'context' are for understanding only and must not be translated. "
               "Return exactly one translation per numbered line, in the same order.")
        .arg(targetLanguageName(targetCode));
}

QString buildUserMessage(const QStringList &lines, const QStringList &context)
{
    QStringList parts;
    if (!context.isEmpty()) {
        QStringList c;
        for (const QString &x : context)
            c << "- " + x;
        parts << "context:\n" + c.join('\n');
    }
    QStringList numbered;
    for (int i = 0; i < lines.size(); ++i)
        numbered << QStringLiteral("%1. %2").arg(i + 1).arg(lines[i]);
    parts << "lines:\n" + numbered.join('\n');
    parts << QStringLiteral("Return JSON: {\"translations\": [%1 strings]}").arg(lines.size());
    return parts.join(QStringLiteral("\n\n"));
}

std::optional<QStringList> parseTranslations(const QString &text, int expected)
{
    const int start = text.indexOf('{'), end = text.lastIndexOf('}');
    if (start < 0 || end < start)
        return std::nullopt;
    QJsonParseError err{};
    const QJsonDocument doc = QJsonDocument::fromJson(text.mid(start, end - start + 1).toUtf8(), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject())
        return std::nullopt;
    const QJsonValue items = doc.object().value("translations");
    if (!items.isArray() || items.toArray().size() != expected)
        return std::nullopt;
    QStringList out;
    for (const QJsonValue &v : items.toArray()) {
        if (!v.isString())
            return std::nullopt;
        out << v.toString().trimmed();
    }
    return out;
}

QList<QPair<int, int>> planBatches(const Segments &events, qint64 positionMs, int size, int firstSize)
{
    const int n = int(events.size());
    int start = 0;
    for (int i = 0; i < n; ++i)
        if (events[i].endMs >= positionMs) {
            start = i;
            break;
        }
    QList<QPair<int, int>> batches;
    const QPair<int, int> ranges[2] = {{start, n}, {0, start}};
    for (const auto &r : ranges)
        for (int i = r.first; i < r.second;) {
            const int step = batches.isEmpty() ? firstSize : size;
            batches.append({i, std::min(i + step, r.second)});
            i += step;
        }
    return batches;
}

// ---- NLLB (사이드카) ----------------------------------------------------------------------------

NllbBackend::NllbBackend(int threads) : m_threads(threads) {}

NllbBackend::~NllbBackend() = default;

QJsonObject NllbBackend::readMessage(int timeoutMs)
{
    QElapsedTimer t;
    t.start();
    while (true) {
        const int nl = m_buffer.indexOf('\n');
        if (nl >= 0) {
            const QByteArray line = m_buffer.left(nl).trimmed();
            m_buffer.remove(0, nl + 1);
            const QJsonDocument doc = QJsonDocument::fromJson(line);
            if (doc.isObject())
                return doc.object();
            continue;   // 라이브러리가 stdout에 찍은 잡음은 건너뜀
        }
        if (m_cancelled && m_cancelled())
            throw TranslationError(kCancelled);
        if (m_proc->state() == QProcess::NotRunning) {
            const QString err = QString::fromUtf8(m_proc->readAllStandardError()).trimmed().split('\n').value(-1);
            throw TranslationError(QStringLiteral("번역 엔진이 종료되었습니다: %1").arg(err));
        }
        if (t.elapsed() > timeoutMs)
            throw TranslationError(QStringLiteral("번역 엔진 응답 시간 초과"));
        m_proc->waitForReadyRead(100);
        m_buffer += m_proc->readAllStandardOutput();
    }
}

void NllbBackend::start(const std::function<bool()> &cancelled)
{
    m_cancelled = cancelled;
    if (!localAvailable())
        throw TranslationError(QStringLiteral("번역 엔진이 설치되어 있지 않습니다. ./scripts/setup_translator.sh 를 실행하세요."));
    const QString script = nllbWorkerScript();
    const QString python = QStandardPaths::findExecutable(QStringLiteral("python3"));
    if (script.isEmpty() || python.isEmpty())
        throw TranslationError(QStringLiteral("번역 엔진 실행 파일(nllb_worker.py 또는 python3)을 찾을 수 없습니다."));
    m_proc = std::make_unique<QProcess>();
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert(QStringLiteral("JVP_NLLB_DIR"), nllbHome());   // 두 쪽이 같은 설치를 보도록
    env.insert(QStringLiteral("PYTHONUNBUFFERED"), QStringLiteral("1"));
    m_proc->setProcessEnvironment(env);
    m_proc->start(python, {QStringLiteral("-u"), script, QStringLiteral("--threads"), QString::number(m_threads)});
    if (!m_proc->waitForStarted(10000))
        throw TranslationError(QStringLiteral("번역 엔진 실행 실패: %1").arg(m_proc->errorString()));
    const QJsonObject hello = readMessage(180000);   // 모델 적재 (약 1.2GB)
    if (!hello.value("ready").toBool())
        throw TranslationError(hello.value("error").toString(QStringLiteral("번역 엔진을 시작하지 못했습니다.")));
}

std::optional<QStringList> NllbBackend::translate(const QStringList &lines, const QStringList &, const QString &target,
                                                  const QString &source)
{
    if (nllbCode(target).isEmpty())
        throw TranslationError(QStringLiteral("지원하지 않는 언어: %1").arg(target));
    const int id = m_nextId++;
    const QJsonObject req{{"id", id}, {"lines", QJsonArray::fromStringList(lines)}, {"source", source}, {"target", target}};
    m_proc->write(QJsonDocument(req).toJson(QJsonDocument::Compact) + '\n');
    m_proc->waitForBytesWritten(5000);
    while (true) {
        const QJsonObject resp = readMessage(600000);
        if (resp.value("id").toInt() != id)
            continue;
        if (resp.contains("error"))
            throw TranslationError(resp.value("error").toString());
        QStringList out;
        for (const QJsonValue &v : resp.value("translations").toArray())
            out << v.toString();
        if (out.size() != lines.size())
            return std::nullopt;
        return out;
    }
}

void NllbBackend::stop()
{
    // 모델 메모리(약 1.2GB)를 바로 돌려줍니다: stdin을 닫으면 사이드카가 끝납니다.
    if (!m_proc)
        return;
    m_proc->closeWriteChannel();
    if (!m_proc->waitForFinished(3000)) {
        m_proc->kill();
        m_proc->waitForFinished(1000);
    }
    m_proc.reset();
}

// ---- Claude API --------------------------------------------------------------------------------

ClaudeBackend::ClaudeBackend() = default;
ClaudeBackend::~ClaudeBackend() = default;

QString ClaudeBackend::apiBaseUrl()
{
    QString base = qEnvironmentVariable("ANTHROPIC_BASE_URL");
    if (base.isEmpty())
        base = QStringLiteral("https://api.anthropic.com");
    while (base.endsWith('/'))
        base.chop(1);
    return base;
}

void ClaudeBackend::start(const std::function<bool()> &cancelled)
{
    m_cancelled = cancelled;
    if (!claudeAvailable())
        throw TranslationError(QStringLiteral("Claude API 인증 정보가 없습니다 (ANTHROPIC_API_KEY)."));
    m_nam = std::make_unique<QNetworkAccessManager>();   // 작업 스레드 소속
}

QJsonObject ClaudeBackend::buildRequest(const QStringList &lines, const QStringList &context, const QString &target)
{
    // 구조화 출력으로 줄 수 보장, 거절 시 서버 측 대체 모델로 재시도 (파이썬 client.beta.messages.create와 같은 요청)
    return QJsonObject{
        {"model", kClaudeModel},
        {"max_tokens", 16000},
        {"fallbacks", "default"},
        {"system", systemPrompt(target)},
        {"messages", QJsonArray{QJsonObject{{"role", "user"}, {"content", buildUserMessage(lines, context)}}}},
        {"output_config", QJsonObject{{"effort", "low"},
                                      {"format", QJsonObject{{"type", "json_schema"}, {"schema", translationSchema(int(lines.size()))}}}}},
    };
}

std::optional<QStringList> ClaudeBackend::translate(const QStringList &lines, const QStringList &context,
                                                    const QString &target, const QString &)
{
    QNetworkRequest req(QUrl(apiBaseUrl() + QStringLiteral("/v1/messages?beta=true")));
    req.setHeader(QNetworkRequest::ContentTypeHeader, QStringLiteral("application/json"));
    req.setRawHeader("anthropic-version", "2023-06-01");
    req.setRawHeader("anthropic-beta", "server-side-fallback-2026-07-01");
    const QByteArray key = qgetenv("ANTHROPIC_API_KEY"), token = qgetenv("ANTHROPIC_AUTH_TOKEN");
    if (!key.isEmpty())
        req.setRawHeader("x-api-key", key);
    else
        req.setRawHeader("Authorization", "Bearer " + token);
    req.setTransferTimeout(600000);   // SDK 기본 10분
    const QByteArray body = QJsonDocument(buildRequest(lines, context, target)).toJson(QJsonDocument::Compact);

    // SDK처럼 연결 오류·408/409/429/5xx는 두 번까지 다시 시도합니다.
    for (int attempt = 0;; ++attempt) {
        QNetworkReply *reply = m_nam->post(req, body);
        QEventLoop loop;
        QObject::connect(reply, &QNetworkReply::finished, &loop, &QEventLoop::quit);
        QTimer poll;
        QObject::connect(&poll, &QTimer::timeout, &loop, [&] {
            if (m_cancelled && m_cancelled())
                reply->abort();
        });
        poll.start(100);
        loop.exec();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const QByteArray data = reply->readAll();
        const auto netError = reply->error();
        const QString errText = reply->errorString();
        reply->deleteLater();
        if (m_cancelled && m_cancelled())
            throw TranslationError(kCancelled);
        const bool retryable = status == 0 || status == 408 || status == 409 || status == 429 || status >= 500;
        if (status == 200 && netError == QNetworkReply::NoError) {
            const QJsonObject resp = QJsonDocument::fromJson(data).object();
            if (resp.value("stop_reason").toString() == QLatin1String("refusal"))
                return std::nullopt;
            QString text;
            for (const QJsonValue &b : resp.value("content").toArray())
                if (b.toObject().value("type").toString() == QLatin1String("text")) {
                    text = b.toObject().value("text").toString();
                    break;
                }
            return parseTranslations(text, int(lines.size()));
        }
        if (retryable && attempt < 2) {
            QThread::msleep(500u << attempt);
            continue;
        }
        if (status == 0)
            throw TranslationError(QStringLiteral("Connection error: %1").arg(errText));
        throw TranslationError(QStringLiteral("Error code: %1 - %2").arg(status).arg(QString::fromUtf8(data)));
    }
}

void ClaudeBackend::stop() { m_nam.reset(); }

std::unique_ptr<TranslationBackend> makeBackend(const QString &name)
{
    if (name == QLatin1String("local"))
        return std::make_unique<NllbBackend>();
    return std::make_unique<ClaudeBackend>();
}

// ---- TranslationJob ------------------------------------------------------------------------------

TranslationJob::TranslationJob(const Segments &events, const QString &target, std::unique_ptr<TranslationBackend> backend,
                               qint64 positionMs, const QString &source, bool resegment, const QString &savePath,
                               QObject *parent)
    : QObject(parent), m_target(target), m_source(source), m_savePath(savePath), m_backend(std::move(backend)),
      m_positionMs(positionMs)
{
    qRegisterMetaType<jvp::ai::Segments>();
    if (resegment) {
        m_events = resegmentSentences(events);
    } else {
        m_events = events;
        std::sort(m_events.begin(), m_events.end());
    }
}

TranslationJob::~TranslationJob()
{
    cancel();
    if (m_thread) {
        m_thread->wait();
        delete m_thread;
    }
}

void TranslationJob::start()
{
    if (m_thread)
        return;
    m_thread = QThread::create([this] { run(); });
    m_thread->setObjectName(QStringLiteral("ai-translate"));
    m_thread->start(QThread::LowPriority);
}

void TranslationJob::cancel() { m_cancelled = true; }

bool TranslationJob::isRunning() const { return m_thread && m_thread->isRunning(); }

QStringList TranslationJob::translateRange(int a, int b)
{
    // 묶음 번역. 줄 수가 맞지 않으면 반으로 나눠 재시도하고, 한 줄도 실패하면 원문을 둡니다.
    QStringList lines, context;
    for (int i = a; i < b; ++i)
        lines << QString(m_events[i].text).replace('\n', ' ');
    for (int i = std::max(0, a - kContextLines); i < a; ++i)
        context << QString(m_events[i].text).replace('\n', ' ');
    if (auto result = m_backend->translate(lines, context, m_target, m_source))
        return *result;
    if (b - a == 1)
        return lines;
    const int mid = (a + b) / 2;
    return translateRange(a, mid) + translateRange(mid, b);
}

void TranslationJob::run()
{
    QString error;
    QMap<int, Segment> translated;
    auto post = [this](auto fn) { QMetaObject::invokeMethod(this, fn, Qt::QueuedConnection); };
    try {
        if (m_events.isEmpty())
            throw TranslationError(QStringLiteral("번역할 자막이 없습니다."));
        post([this] { emit status(QStringLiteral("🌐 번역 엔진 준비 중..."), 0.0); });
        m_backend->start([this] { return m_cancelled.load(); });
        const int total = int(m_events.size());
        for (const auto &[a, b] : planBatches(m_events, m_positionMs)) {
            if (m_cancelled)
                break;
            const QStringList out = translateRange(a, b);
            Segments batch;
            for (int i = a; i < b && i - a < out.size(); ++i) {
                const QString &text = out[i - a];
                if (text.isEmpty())
                    continue;
                translated.insert(i, {m_events[i].startMs, m_events[i].endMs, text});
                batch.append(translated[i]);
            }
            const double frac = double(translated.size()) / total;
            post([this, batch] { emit segments(batch); });
            post([this, frac] { emit status(QStringLiteral("🌐 자막 번역 중 %1%").arg(qRound(frac * 100)), frac); });
        }
    } catch (const std::exception &e) {
        error = QString::fromStdString(e.what());
    }
    try {
        m_backend->stop();
    } catch (...) {
    }
    if (m_cancelled)
        error = kCancelled;
    const Segments result = translated.values();
    if (error.isEmpty() && !result.isEmpty() && !m_savePath.isEmpty()) {
        // 앱을 곧바로 닫아도 남도록 작업 스레드에서 바로 저장합니다.
        QFile f(m_savePath);
        if (f.open(QIODevice::WriteOnly | QIODevice::Truncate))
            f.write(formatSrt(result).toUtf8());
        else
            error = QStringLiteral("저장 실패: %1").arg(f.errorString());
    }
    if (!error.isEmpty() && error != kCancelled)
        qCWarning(lcTranslate) << "번역 실패:" << error;
    post([this, result, error] { emit done(result, error); });
}

} // namespace jvp::ai
