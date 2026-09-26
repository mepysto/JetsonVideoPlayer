// OpenSubtitles: tests/test_opensubtitles.py 이식 (로컬 가짜 HTTP 서버, 네트워크 사용 안 함)
#include "OpenSubtitles.h"
#include "Paths.h"
#include "fake_http_server.h"
#include "media_test_util.h"

#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTest>

#include <sys/stat.h>

using namespace jvp::opensubtitles;

namespace {
void writeFile(const QString &path, const QByteArray &data)
{
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(data);
}

const QByteArray kSearchJson = R"({"data": [
    {"attributes": {"language": "en", "download_count": 900, "moviehash_match": false, "release": "Other.Release",
                    "feature_details": {"title": "Movie", "year": 2019}, "files": [{"file_id": 11, "file_name": "a.srt"}]}},
    {"attributes": {"language": "ko", "download_count": 10, "moviehash_match": true, "release": "Exact.Release",
                    "feature_details": {"title": "Movie", "year": 2019}, "files": [{"file_id": 22, "file_name": "b.ass"}]}},
    {"attributes": {"language": "ko", "files": []}}
]})";
} // namespace

class TestOpenSubtitles : public QObject {
    Q_OBJECT
    QString m_home;

private slots:
    void initTestCase()
    {
        m_home = testutil::isolateHome();
        qunsetenv("JVP_OPENSUBTITLES_KEY");
    }

    void moviehashOfZeroFileIsItsSize()
    {
        writeFile(m_home + "/zero.bin", QByteArray(131072, '\0'));
        QCOMPARE(moviehash(m_home + "/zero.bin"), QString("0000000000020000"));
    }

    void moviehashSumsHeadAndTailWords()
    {
        QByteArray data(200000, '\0');
        data[0] = 1;                             // 앞 64KB 첫 단어 = 1
        for (int i = 1; i <= 8; ++i)
            data[data.size() - i] = char(0xFF);  // 뒤 64KB 마지막 단어 = 0xFFFFFFFFFFFFFFFF (오버플로 확인)
        writeFile(m_home + "/v.bin", data);
        const quint64 expected = quint64(200000) + 1 + 0xFFFFFFFFFFFFFFFFULL;
        QCOMPARE(moviehash(m_home + "/v.bin"), QStringLiteral("%1").arg(expected, 16, 16, QLatin1Char('0')));
        writeFile(m_home + "/s.bin", QByteArray(1000, 'x'));
        QString err;
        QVERIFY(moviehash(m_home + "/s.bin", &err).isEmpty());
        QVERIFY(!err.isEmpty());
    }

    void queryFromFilenameCases()
    {
        QCOMPARE(queryFromFilename("The.Movie.Name.2019.1080p.WEB-DL.x265-GRP.mkv"), QString("The Movie Name 2019"));
        QCOMPARE(queryFromFilename("[SubGroup] Show_Name - 05 (1080p).mkv"), QString("Show Name - 05"));
        QCOMPARE(queryFromFilename(QStringLiteral("드라마 12화.mp4")), QStringLiteral("드라마 12화"));
    }

    void searchSortsHashMatchFirstAndSendsKey()
    {
        const QString video = m_home + "/Movie.2019.1080p.mkv";
        writeFile(video, QByteArray(200000, '\0'));
        FakeHttpServer server([](const FakeRequest &r) {
            if (r.target.startsWith("/api/v1/subtitles"))
                return FakeResponse{200, kSearchJson};
            return FakeResponse{404, "{}"};
        });
        OpenSubtitlesClient client("KEY");
        client.setApiBase(server.baseUrl() + "/api/v1");
        QList<SubtitleResult> results;
        QString error;
        bool done = false;
        client.search(video, {"ko", "en"}, [&](const QList<SubtitleResult> &r, const QString &e) {
            results = r;
            error = e;
            done = true;
        });
        QVERIFY(testutil::waitUntil([&] { return done; }));
        QVERIFY2(error.isEmpty(), qPrintable(error));
        QCOMPARE(results.size(), 2);
        QCOMPARE(results[0].fileId, 22);
        QCOMPARE(results[1].fileId, 11);
        QVERIFY(results[0].hashMatch);
        QCOMPARE(results[0].title, QString("Movie (2019)"));
        QCOMPARE(results[0].release, QString("Exact.Release"));
        QCOMPARE(results[0].fileName, QString("b.ass"));
        const FakeRequest &r = server.requests.first();
        QCOMPARE(r.method, QByteArray("GET"));
        QVERIFY2(r.target.contains("moviehash=") && r.target.contains("languages=en%2Cko") && r.target.contains("query=Movie+2019"),
                 r.target.constData());
        QVERIFY(r.target.indexOf("languages=") < r.target.indexOf("moviehash=")
                && r.target.indexOf("moviehash=") < r.target.indexOf("query="));   // 키 이름 순
        QCOMPARE(r.headers.value("api-key"), QByteArray("KEY"));
        QVERIFY(r.headers.value("user-agent").startsWith("JetsonVideoPlayer"));
        QCOMPARE(r.headers.value("accept"), QByteArray("application/json"));
    }

    void downloadLogsInAndFetchesLink()
    {
        FakeHttpServer *srv = nullptr;
        FakeHttpServer server([&](const FakeRequest &r) {
            if (r.target.endsWith("/login"))
                return FakeResponse{200, R"({"token": "TOK"})"};
            if (r.target.endsWith("/download"))
                return FakeResponse{200, QJsonDocument(QJsonObject{{"link", QString(srv->baseUrl() + "/dl/x.srt")}, {"remaining", 5}})
                                             .toJson(QJsonDocument::Compact)};
            if (r.target == "/dl/x.srt")
                return FakeResponse{200, "1\n00:00:01,000 --> 00:00:02,000\nhi\n", "text/plain"};
            return FakeResponse{404, "{}"};
        });
        srv = &server;
        OpenSubtitlesClient client("KEY", "me", "pw");
        client.setApiBase(server.baseUrl() + "/api/v1");
        QByteArray content;
        QString error;
        bool done = false;
        client.download(22, [&](const QByteArray &c, const QString &e) {
            content = c;
            error = e;
            done = true;
        });
        QVERIFY(testutil::waitUntil([&] { return done; }));
        QVERIFY2(error.isEmpty(), qPrintable(error));
        QVERIFY(content.startsWith("1\n"));
        QStringList last;
        for (const auto &r : server.requests)
            last << QString::fromUtf8(r.target.split('/').last());
        QCOMPARE(last, (QStringList{"login", "download", "x.srt"}));
        QCOMPARE(QJsonDocument::fromJson(server.requests[0].body).object(),
                 (QJsonObject{{"username", "me"}, {"password", "pw"}}));
        QCOMPARE(server.requests[1].headers.value("authorization"), QByteArray("Bearer TOK"));
        QCOMPARE(QJsonDocument::fromJson(server.requests[1].body).object(), (QJsonObject{{"file_id", 22}}));
        QCOMPARE(server.requests[1].headers.value("content-type"), QByteArray("application/json"));
        QVERIFY(!server.requests[2].headers.contains("api-key"));   // 임시 링크에는 키를 보내지 않음
        QCOMPARE(client.token(), QString("TOK"));
    }

    void httpErrorsBecomeReadable()
    {
        FakeHttpServer server([](const FakeRequest &) { return FakeResponse{406, R"({"message": "quota exceeded"})"}; });
        OpenSubtitlesClient client("KEY");
        client.setApiBase(server.baseUrl() + "/api/v1");
        QString error;
        bool done = false;
        client.download(1, [&](const QByteArray &, const QString &e) {
            error = e;
            done = true;
        });
        QVERIFY(testutil::waitUntil([&] { return done; }));
        QCOMPARE(error, QString("HTTP 406 quota exceeded"));

        // 연결 실패
        quint16 port;
        {
            QTcpServer tmp;
            tmp.listen(QHostAddress::LocalHost, 0);
            port = tmp.serverPort();
        }
        client.setApiBase(QStringLiteral("http://127.0.0.1:%1/api/v1").arg(port));
        done = false;
        client.download(1, [&](const QByteArray &, const QString &e) {
            error = e;
            done = true;
        });
        QVERIFY(testutil::waitUntil([&] { return done; }));
        QVERIFY2(error.startsWith(QStringLiteral("연결 실패")), qPrintable(error));

        OpenSubtitlesClient noKey("");
        done = false;
        noKey.download(1, [&](const QByteArray &, const QString &e) {
            error = e;
            done = true;
        });
        QVERIFY(testutil::waitUntil([&] { return done; }));
        QCOMPARE(error, QStringLiteral("API 키가 없습니다"));
    }

    void credentialsFileIsPrivate()
    {
        QVERIFY(credentialsFile().startsWith(m_home));   // 실제 ~/.config를 건드리지 않음
        const QString path = m_home + "/cfg/os.json";
        QVERIFY(saveCredentials({{"api_key", "K"}, {"username", ""}, {"password", "p"}}, path));
        struct stat st {};
        QCOMPARE(::stat(QFile::encodeName(path).constData(), &st), 0);
        QCOMPARE(int(st.st_mode & 0777), 0600);
        QCOMPARE(loadCredentials(path), (QMap<QString, QString>{{"api_key", "K"}, {"password", "p"}}));
        qputenv("JVP_OPENSUBTITLES_KEY", "ENV");
        QCOMPARE(loadCredentials(path).value("api_key"), QString("ENV"));
        qunsetenv("JVP_OPENSUBTITLES_KEY");
    }

    void savePath()
    {
        QCOMPARE(subtitleSavePath("/v/movie.mkv", "ko", "x.ASS"), QString("/v/movie.ko.ass"));
        QCOMPARE(subtitleSavePath("/v/movie.mkv", "pt-BR", "x.zip"), QString("/v/movie.pt-br.srt"));
        QCOMPARE(subtitleSavePath("/v/a.b/movie", "", ""), QString("/v/a.b/movie.sub.srt"));
    }

    void urlEncodeMatchesQuotePlus()
    {
        QCOMPARE(urlEncode({{"query", "Movie 2019"}, {"languages", "en,ko"}, {"x", "a+b/c~"}}),
                 QByteArray("query=Movie+2019&languages=en%2Cko&x=a%2Bb%2Fc~"));
    }
};

QTEST_GUILESS_MAIN(TestOpenSubtitles)
#include "test_opensubtitles.moc"
