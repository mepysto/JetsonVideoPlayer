// 자막 번역: tests/test_ai_translate.py 이식 + Claude API 요청 형태(가짜 서버) + NLLB 사이드카 통합 테스트
#include "Translator.h"
#include "fake_http_server.h"
#include "media_test_util.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMutex>
#include <QSet>
#include <QSignalSpy>
#include <QTest>
#include <QThread>

using namespace jvp::ai;

namespace {
Segments ev(int n, qint64 step = 1000)
{
    Segments out;
    for (int i = 0; i < n; ++i)
        out.append({i * step, i * step + 900, QStringLiteral("line %1").arg(i)});
    return out;
}

QStringList texts(const Segments &s)
{
    QStringList out;
    for (const auto &e : s)
        out << e.text;
    return out;
}

struct Shared {
    QMutex mutex;
    QList<int> calls;
    QString source;
    QStringList lines;
    bool stopped = false;
};

class FakeBackend : public TranslationBackend {
public:
    FakeBackend(std::shared_ptr<Shared> s, QSet<int> failSizes = {}, int delayMs = 0)
        : m_s(std::move(s)), m_fail(std::move(failSizes)), m_delay(delayMs) {}
    void start(const std::function<bool()> &) override {}
    std::optional<QStringList> translate(const QStringList &lines, const QStringList &, const QString &target,
                                         const QString &source) override
    {
        if (m_delay)
            QThread::msleep(m_delay);
        QMutexLocker lock(&m_s->mutex);
        m_s->calls << int(lines.size());
        if (m_s->source.isEmpty())
            m_s->source = source;
        m_s->lines += lines;
        if (m_fail.contains(int(lines.size())))
            return std::nullopt;
        QStringList out;
        for (const QString &l : lines)
            out << target + ":" + l;
        return out;
    }
    void stop() override
    {
        QMutexLocker lock(&m_s->mutex);
        m_s->stopped = true;
    }

private:
    std::shared_ptr<Shared> m_s;
    QSet<int> m_fail;
    int m_delay;
};

struct Done {
    Segments events;
    QString error;
    bool ok = false;
};

Done runJob(TranslationJob &job, int timeoutMs = 5000)
{
    Done d;
    QObject::connect(&job, &TranslationJob::done, [&](const Segments &e, const QString &err) {
        d.events = e;
        d.error = err;
        d.ok = true;
    });
    job.start();
    testutil::waitUntil([&] { return d.ok; }, timeoutMs);
    return d;
}
} // namespace

class TestTranslator : public QObject {
    Q_OBJECT
    QString m_home;
    QString m_realNllb;

private slots:
    void initTestCase()
    {
        m_home = testutil::isolateHome();
        m_realNllb = qEnvironmentVariable("JVP_NLLB_DIR");
        if (m_realNllb.isEmpty())
            m_realNllb = testutil::realHome() + "/.local/share/jetson_video_player/nllb";
        qunsetenv("JVP_NLLB_DIR");
        qunsetenv("ANTHROPIC_API_KEY");
        qunsetenv("ANTHROPIC_AUTH_TOKEN");
        qunsetenv("ANTHROPIC_BASE_URL");
    }

    void parseTranslationsCases()
    {
        QCOMPARE(parseTranslations(QStringLiteral("{\"translations\": [\"가\", \"나\"]}"), 2),
                 std::optional<QStringList>(QStringList{"가", "나"}));
        QCOMPARE(parseTranslations(QStringLiteral("설명... {\"translations\": [\"가\"]} 끝"), 1),
                 std::optional<QStringList>(QStringList{"가"}));   // 앞뒤 잡음 허용
        QVERIFY(!parseTranslations(QStringLiteral("{\"translations\": [\"가\"]}"), 2));   // 개수 불일치
        QVERIFY(!parseTranslations("not json", 1));
        QVERIFY(!parseTranslations("{\"translations\": [1]}", 1));
    }

    void planBatchesStartsNearPosition()
    {
        const auto events = ev(50);
        const auto batches = planBatches(events, 25500, 20);
        QCOMPARE(batches.first(), (QPair<int, int>{25, 31}));   // 현재 위치의 작은 첫 묶음
        QList<int> covered;
        for (const auto &b : batches)
            for (int i = b.first; i < b.second; ++i)
                covered << i;
        std::sort(covered.begin(), covered.end());
        QList<int> all;
        for (int i = 0; i < 50; ++i)
            all << i;
        QCOMPARE(covered, all);   // 빠짐·중복 없음
        QCOMPARE(planBatches(events, 0, 20).mid(0, 2), (QList<QPair<int, int>>{{0, 6}, {6, 26}}));
    }

    void jobTranslatesAllLinesInOrder()
    {
        auto s = std::make_shared<Shared>();
        TranslationJob job(ev(45), "ko", std::make_unique<FakeBackend>(s), 30000, "en", false);
        Segments got;
        connect(&job, &TranslationJob::segments, this, [&](const Segments &b) { got += b; });
        const Done d = runJob(job);
        QVERIFY(d.ok);
        QVERIFY(d.error.isEmpty());
        QVERIFY(s->stopped);
        QStringList expected;
        for (int i = 0; i < 45; ++i)
            expected << QStringLiteral("ko:line %1").arg(i);
        QCOMPARE(texts(d.events), expected);
        QCOMPARE(got.first().text, QString("ko:line 30"));   // 30초에 표시 중인 대사(30.0~30.9초)부터
    }

    void jobSplitsBatchWhenCountMismatch()
    {
        auto s = std::make_shared<Shared>();   // 14줄·7줄 묶음은 실패 → 3·4줄로 나눠 성공
        TranslationJob job(ev(20), "ko", std::make_unique<FakeBackend>(s, QSet<int>{14, 7}), 0, "en", false);
        const Done d = runJob(job);
        QCOMPARE(d.events.size(), 20);
        QCOMPARE(QSet<int>(s->calls.begin(), s->calls.end()), (QSet<int>{6, 14, 7, 3, 4}));
    }

    void jobKeepsOriginalWhenSingleLineFails()
    {
        auto s = std::make_shared<Shared>();
        TranslationJob job(ev(2), "ko", std::make_unique<FakeBackend>(s, QSet<int>{2, 1}), 0, "en", false);
        QCOMPARE(texts(runJob(job).events), (QStringList{"line 0", "line 1"}));
    }

    void jobCancel()
    {
        auto s = std::make_shared<Shared>();
        TranslationJob job(ev(200), "ko", std::make_unique<FakeBackend>(s, QSet<int>{}, 200), 0, "en", false);
        Done d;
        connect(&job, &TranslationJob::done, this, [&](const Segments &e, const QString &err) {
            d = {e, err, true};
        });
        job.start();
        QTest::qWait(50);
        job.cancel();
        QVERIFY(testutil::waitUntil([&] { return d.ok; }, 5000));
        QCOMPARE(d.error, QStringLiteral("취소됨"));
        QVERIFY(d.events.size() < 200);
    }

    void jobResegmentsAndPassesSourceLanguage()
    {
        auto s = std::make_shared<Shared>();
        const Segments events{{0, 4000, "from a long rest. So let's begin in a seated"}, {4000, 6000, "position."}};
        TranslationJob job(events, "ko", std::make_unique<FakeBackend>(s), 0, "ja");
        const Done d = runJob(job);
        QCOMPARE(s->source, QString("ja"));
        QCOMPARE(s->lines, (QStringList{"from a long rest.", "So let's begin in a seated position."}));
        QCOMPARE(d.events.size(), 2);
    }

    void resegmentSplitsMidLine()
    {
        const Segments events{
            {0, 4000, "from a long rest. So let's begin in a seated"},   // 문장이 줄 중간에서 끝남
            {4000, 6000, "position. Ready?"},
            {9000, 10000, "After a pause"},                              // 1.5초 넘게 비면 끊기
        };
        const auto out = resegmentSentences(events);
        QCOMPARE(texts(out), (QStringList{"from a long rest.", "So let's begin in a seated position.", "Ready?", "After a pause"}));
        QVERIFY(out[0].startMs == 0 && out[0].endMs > 0 && out[0].endMs < 4000);   // 줄 중간 시각으로 배분
        QVERIFY(out[1].startMs < 4000 && 4000 < out[1].endMs);                      // 두 줄에 걸친 문장
        QCOMPARE(out[3].startMs, 9000);
    }

    void resegmentLimitsLengthAndKeepsWords()
    {
        Segments events;
        for (int i = 0; i < 20; ++i)
            events.append({i * 1000, i * 1000 + 1000, QString("word ").repeated(5)});
        const auto out = resegmentSentences(events, 60);
        int words = 0;
        for (const auto &s : out) {
            QVERIFY(s.text.size() <= 60);
            words += int(s.text.split(' ', Qt::SkipEmptyParts).size());
        }
        QCOMPARE(words, 100);
    }

    void jobSavesSrtInWorker()
    {
        const QString out = m_home + "/movie.ai.ko.srt";
        auto s = std::make_shared<Shared>();
        TranslationJob job(ev(3), "ko", std::make_unique<FakeBackend>(s), 0, "en", false, out);
        QVERIFY(runJob(job).error.isEmpty());
        QFile f(out);
        QVERIFY(f.open(QIODevice::ReadOnly));
        const QString text = QString::fromUtf8(f.readAll());
        QVERIFY(text.contains("ko:line 0") && text.contains("ko:line 2"));
        QVERIFY(text.startsWith("1\n00:00:00,000 --> 00:00:00,900\nko:line 0\n"));
    }

    void jobDoesNotSaveWhenCancelled()
    {
        const QString out = m_home + "/x.srt";
        auto s = std::make_shared<Shared>();
        TranslationJob job(ev(3), "ko", std::make_unique<FakeBackend>(s), 0, "en", false, out);
        job.cancel();
        const Done d = runJob(job);
        QCOMPARE(d.error, QStringLiteral("취소됨"));
        QVERIFY(!QFile::exists(out));
    }

    void emptyInputIsError()
    {
        auto s = std::make_shared<Shared>();
        TranslationJob job({}, "ko", std::make_unique<FakeBackend>(s));
        QCOMPARE(runJob(job).error, QStringLiteral("번역할 자막이 없습니다."));
    }

    void localAvailableRequiresLibraryAndModel()
    {
        const QString dir = m_home + "/nllb";
        qputenv("JVP_NLLB_DIR", dir.toUtf8());
        QVERIFY(!localAvailable());
        QDir().mkpath(dir + "/pylib/ctranslate2");
        QDir().mkpath(dir + "/model");
        QVERIFY(QFile(dir + "/model/model.bin").open(QIODevice::WriteOnly));
        QVERIFY(!localAvailable());   // 토크나이저 모델 없음
        QVERIFY(QFile(dir + "/model/sentencepiece.bpe.model").open(QIODevice::WriteOnly));
        QVERIFY(localAvailable());
        QCOMPARE(resolveBackend("auto"), QString("local"));
        QCOMPARE(resolveBackend("claude"), QString());
        qputenv("ANTHROPIC_API_KEY", "k");
        QCOMPARE(resolveBackend("claude"), QString("claude"));
        qunsetenv("JVP_NLLB_DIR");
        QCOMPARE(resolveBackend("auto"), QString("claude"));
        QCOMPARE(resolveBackend("local"), QString());
        qunsetenv("ANTHROPIC_API_KEY");
        QCOMPARE(resolveBackend("auto"), QString());
    }

    void claudeRequestShapeAndRefusal()
    {
        bool refuse = false;
        FakeHttpServer server([&](const FakeRequest &) {
            if (refuse)
                return FakeResponse{200, R"({"stop_reason":"refusal","content":[]})"};
            const QJsonObject text{{"type", "text"}, {"text", QStringLiteral("{\"translations\": [\"안녕\", \"잘 가\"]}")}};
            return FakeResponse{200, QJsonDocument(QJsonObject{{"stop_reason", "end_turn"},
                                                               {"content", QJsonArray{text}}})
                                         .toJson(QJsonDocument::Compact)};
        });
        qputenv("ANTHROPIC_BASE_URL", server.baseUrl());
        qputenv("ANTHROPIC_API_KEY", "KEY");
        ClaudeBackend backend;
        backend.start([] { return false; });
        QCOMPARE(backend.translate({"hi", "bye"}, {"context"}, "ko", "en"), std::optional<QStringList>(QStringList{"안녕", "잘 가"}));
        QCOMPARE(server.requests.size(), 1);
        const FakeRequest &r = server.requests.first();
        QCOMPARE(r.method, QByteArray("POST"));
        QCOMPARE(r.target, QByteArray("/v1/messages?beta=true"));
        QCOMPARE(r.headers.value("x-api-key"), QByteArray("KEY"));
        QCOMPARE(r.headers.value("anthropic-version"), QByteArray("2023-06-01"));
        QCOMPARE(r.headers.value("anthropic-beta"), QByteArray("server-side-fallback-2026-07-01"));
        const QJsonObject body = QJsonDocument::fromJson(r.body).object();
        QCOMPARE(body.value("model").toString(), QString("claude-opus-5"));
        QCOMPARE(body.value("fallbacks").toString(), QString("default"));
        QCOMPARE(body.value("max_tokens").toInt(), 16000);
        QVERIFY(body.value("system").toString().contains("Korean (한국어)"));
        const QString user = body.value("messages").toArray().at(0).toObject().value("content").toString();
        QCOMPARE(user, QString("context:\n- context\n\nlines:\n1. hi\n2. bye\n\nReturn JSON: {\"translations\": [2 strings]}"));
        const QJsonObject oc = body.value("output_config").toObject();
        QCOMPARE(oc.value("effort").toString(), QString("low"));
        QCOMPARE(oc.value("format").toObject().value("type").toString(), QString("json_schema"));
        const QJsonObject schema = oc.value("format").toObject().value("schema").toObject()
                                       .value("properties").toObject().value("translations").toObject();
        QCOMPARE(schema.value("minItems").toInt(), 2);
        QCOMPARE(schema.value("maxItems").toInt(), 2);

        refuse = true;
        QVERIFY(!backend.translate({"x"}, {}, "ko", "en"));
        backend.stop();

        // 인증 토큰이면 Bearer
        qunsetenv("ANTHROPIC_API_KEY");
        qputenv("ANTHROPIC_AUTH_TOKEN", "TOK");
        refuse = false;
        ClaudeBackend b2;
        b2.start([] { return false; });
        b2.translate({"hi", "bye"}, {}, "ko", "en");
        QCOMPARE(server.requests.last().headers.value("authorization"), QByteArray("Bearer TOK"));
        b2.stop();
        qunsetenv("ANTHROPIC_AUTH_TOKEN");
        qunsetenv("ANTHROPIC_BASE_URL");
    }

    void claudeHttpErrorEndsJobWithMessage()
    {
        FakeHttpServer server([](const FakeRequest &) {
            return FakeResponse{401, R"({"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}})"};
        });
        qputenv("ANTHROPIC_BASE_URL", server.baseUrl());
        qputenv("ANTHROPIC_API_KEY", "BAD");
        TranslationJob job(ev(2), "ko", makeBackend("claude"), 0, "en", false);
        const Done d = runJob(job, 10000);
        QVERIFY(d.ok);
        QVERIFY2(d.error.contains("401") && d.error.contains("invalid x-api-key"), qPrintable(d.error));
        QCOMPARE(server.requests.size(), 1);   // 4xx는 재시도하지 않음
        qunsetenv("ANTHROPIC_API_KEY");
        qunsetenv("ANTHROPIC_BASE_URL");
    }

    void nllbSidecarTranslatesEnglishToKorean()
    {
        qputenv("JVP_NLLB_DIR", m_realNllb.toUtf8());
        if (!localAvailable() || nllbWorkerScript().isEmpty()) {
            qunsetenv("JVP_NLLB_DIR");
            QSKIP("NLLB 번역 엔진이 설치되어 있지 않습니다");
        }
        const Segments events{{0, 2000, "Hello, how are you?"}, {2500, 5000, "The weather is nice today."}};
        const QString out = m_home + "/nllb.ai.ko.srt";
        TranslationJob job(events, "ko", makeBackend("local"), 0, "en", true, out);
        QElapsedTimer t;
        t.start();
        const Done d = runJob(job, 180000);
        qInfo("NLLB: %.1f s, error='%s'", t.elapsed() / 1000.0, qPrintable(d.error));
        for (const auto &e : d.events)
            qInfo("  %lld-%lld %s", e.startMs, e.endMs, qPrintable(e.text));
        QVERIFY(d.ok);
        QVERIFY2(d.error.isEmpty(), qPrintable(d.error));
        QCOMPARE(d.events.size(), 2);
        for (const auto &e : d.events) {   // 한글 음절이 들어 있어야 함
            bool hangul = false;
            for (QChar c : e.text)
                hangul |= c.unicode() >= 0xAC00 && c.unicode() <= 0xD7A3;
            QVERIFY2(hangul, qPrintable(e.text));
        }
        QVERIFY(QFile::exists(out));
        qunsetenv("JVP_NLLB_DIR");
    }
};

QTEST_GUILESS_MAIN(TestTranslator)
#include "test_translator.moc"
