// YouTube: URL 정규화(tests/test_youtube_url.py)와 다운로드 대기열(tests/test_youtube_queue.py) 이식.
// 네트워크에 나가지 않습니다: 가짜 실행기(주입)와 yt-dlp 흉내 스크립트만 씁니다.
#include "YouTube.h"
#include "media_test_util.h"

#include <QDir>
#include <QFile>
#include <QSet>
#include <QSignalSpy>
#include <QTest>
#include <QTimer>

using namespace jvp::youtube;

namespace {
const QString VID = "dQw4w9WgXcQ";
const QString CANON = "https://www.youtube.com/watch?v=" + VID;
const QString URL_A = "https://www.youtube.com/watch?v=AAAAAAAAAAA";
const QString URL_B = "https://www.youtube.com/watch?v=BBBBBBBBBBB";

// release 될 때까지 진행률 줄을 반복해서 내보내는 가짜 yt-dlp
class FakeRunner : public DownloadRunner {
public:
    static QSet<QString> &released()
    {
        static QSet<QString> s;
        return s;
    }
    static QList<QStringList> &argLog()
    {
        static QList<QStringList> l;
        return l;
    }
    void start(const QString &, const QStringList &args) override
    {
        argLog().append(args);
        m_url = args.last();
        connect(&m_timer, &QTimer::timeout, this, [this] {
            if (released().contains(m_url)) {
                m_timer.stop();
                const QString vid = m_url.right(11);
                emit lineReceived("[jvp-progress] finished|100|100|NA|2048|0|" + m_url);
                emit lineReceived("[jvp-file] /tmp/title-" + vid + " [" + vid + "].mp4");
                emit lineReceived("[jvp-title] title-" + vid);
                emit finished(0, false);
                return;
            }
            emit lineReceived("[jvp-progress] downloading|50|100|NA|2048|5|" + m_url);
        });
        m_timer.start(10);
    }
    void kill() override
    {
        m_timer.stop();
        QTimer::singleShot(0, this, [this] { emit finished(9, true); });
    }

private:
    QString m_url;
    QTimer m_timer;
};

struct Events {
    QList<QPair<QString, QString>> list;   // ("finish", title) / ("error", message)
    bool has(const QString &k, const QString &v) const { return list.contains({k, v}); }
};

void track(YouTubeManager &m, Events &ev)
{
    QObject::connect(&m, &YouTubeManager::finished, [&ev](const QString &, const QString &, const QString &t) {
        ev.list.append({"finish", t});
    });
    QObject::connect(&m, &YouTubeManager::failed, [&ev](const QString &, const QString &e) { ev.list.append({"error", e}); });
}
} // namespace

class TestYouTube : public QObject {
    Q_OBJECT
    QString m_home;
    int m_n = 0;

    std::unique_ptr<YouTubeManager> makeManager()
    {
        const QString dir = m_home + QStringLiteral("/yt%1").arg(++m_n);
        auto m = std::make_unique<YouTubeManager>(dir);
        m->setProgram("fake-yt-dlp");
        m->setRunnerFactory([] { return new FakeRunner(); });
        FakeRunner::released().clear();
        FakeRunner::argLog().clear();
        return m;
    }

private slots:
    void initTestCase() { m_home = testutil::isolateHome(); }

    // ---- test_youtube_url.py ----
    void extractNormalizes_data()
    {
        QTest::addColumn<QString>("raw");
        QTest::newRow("watch") << "https://www.youtube.com/watch?v=" + VID;
        QTest::newRow("mix") << "https://www.youtube.com/watch?v=" + VID + "&list=RD" + VID + "&start_radio=1";
        QTest::newRow("short") << "https://youtu.be/" + VID + "?t=30";
        QTest::newRow("mobile") << "https://m.youtube.com/watch?v=" + VID;
        QTest::newRow("shorts") << "https://www.youtube.com/shorts/" + VID;
        QTest::newRow("embed") << "https://www.youtube.com/embed/" + VID;
        QTest::newRow("noscheme") << "youtube.com/watch?v=" + VID;
        QTest::newRow("in-text") << QStringLiteral("여기 링크: https://youtu.be/%1 보세요").arg(VID);
    }
    void extractNormalizes()
    {
        QFETCH(QString, raw);
        QCOMPARE(extractYoutubeUrl(raw), CANON);
    }

    void extractRejects()
    {
        for (const QString &raw : {QString(), QString(""), QString("https://example.com/video.mp4"), QString("just text")})
            QVERIFY2(extractYoutubeUrl(raw).isNull(), qPrintable(raw));
    }

    void extractVideoId()
    {
        for (const QString &raw : {"https://youtu.be/" + VID, "https://www.youtube.com/watch?v=" + VID + "&list=PL123",
                                   "https://www.youtube.com/live/" + VID})
            QCOMPARE(extractYoutubeVideoId(raw), VID);
    }

    void isYoutube()
    {
        QVERIFY(isYoutubeUrl("https://youtu.be/" + VID));
        QVERIFY(!isYoutubeUrl("/home/user/video.mp4"));
        QVERIFY(!isYoutubeUrl(QString()));
    }

    void formatForQualityRule()
    {
        QVERIFY(formatForQuality("720p").contains("height<=720"));
        QVERIFY(formatForQuality("audio").startsWith("bestaudio"));
        const QString best = formatForQuality("best");
        QVERIFY(best.startsWith("bestvideo[vcodec^=avc1]") && best.contains("av01"));
        QCOMPARE(formatSpeed(2048), QString("2 KB/s"));
        QCOMPARE(formatSpeed(3 * 1024 * 1024 + 100000), QString("3.1 MB/s"));
        QCOMPARE(formatSpeed(10), QString("10 B/s"));
        QCOMPARE(formatEta(5), QString("5초"));
        QCOMPARE(formatEta(125), QString("2분 5초"));
    }

    // ---- test_youtube_queue.py ----
    void queueCancelAndAdvance()
    {
        auto mgr = makeManager();
        Events ev;
        track(*mgr, ev);
        QCOMPARE(mgr->downloadAsync(URL_A), (QPair<QString, int>{"started", 0}));
        QCOMPARE(mgr->downloadAsync(URL_A), (QPair<QString, int>{"downloading", 0}));
        QCOMPARE(mgr->downloadAsync(URL_B), (QPair<QString, int>{"queued", 1}));
        QCOMPARE(mgr->downloadAsync(URL_B), (QPair<QString, int>{"queued", 1}));   // 중복 추가 안 함
        const QVariantList queue = mgr->status().value("queue").toList();
        QCOMPARE(queue.size(), 1);
        QCOMPARE(queue.first().toMap().value("url").toString(), URL_B);
        QCOMPARE(queue.first().toMap().value("quality").toString(), QString("best"));

        // 진행률이 상태에 반영됨
        QVERIFY(testutil::waitUntil([&] { return mgr->status().value("percent").toDouble() == 50.0; }));
        const auto st = mgr->status();
        QCOMPARE(st.value("title").toString(), URL_A);
        QCOMPARE(st.value("speed").toString(), QString("2 KB/s"));
        QCOMPARE(st.value("eta").toString(), QString("5초"));

        QVERIFY(mgr->cancelCurrent());
        QVERIFY(testutil::waitUntil([&] { return ev.has("error", YouTubeManager::kCancelledMessage); }));
        // 취소 후 대기열의 다음 작업이 자동 시작
        QVERIFY(testutil::waitUntil([&] {
            return mgr->status().value("url").toString() == URL_B && mgr->status().value("active").toBool();
        }));
        FakeRunner::released().insert(URL_B);
        QVERIFY(testutil::waitUntil([&] { return ev.has("finish", "title-BBBBBBBBBBB"); }));
        QVERIFY(testutil::waitUntil([&] { return !mgr->status().value("active").toBool(); }));
        QVERIFY(mgr->status().value("queue").toList().isEmpty());
        QVERIFY(mgr->status().value("completed").toBool());
        QCOMPARE(mgr->status().value("percent").toDouble(), 100.0);
        QCOMPARE(mgr->status().value("filepath").toString(), QString("/tmp/title-BBBBBBBBBBB [BBBBBBBBBBB].mp4"));
    }

    void cancelPending()
    {
        auto mgr = makeManager();
        mgr->downloadAsync(URL_A);
        mgr->downloadAsync(URL_B);
        QVERIFY(mgr->cancelPending(URL_B));
        QVERIFY(!mgr->cancelPending(URL_B));
        QVERIFY(mgr->status().value("queue").toList().isEmpty());
        mgr->cancelCurrent();
        QVERIFY(testutil::waitUntil([&] { return !mgr->status().value("active").toBool(); }));
        QCOMPARE(mgr->status().value("error").toString(), YouTubeManager::kCancelledMessage);
        QVERIFY(!mgr->cancelCurrent());
    }

    void cachedFileShortCircuits()
    {
        auto mgr = makeManager();
        const QString cached = mgr->downloadDir() + "/Old Video [AAAAAAAAAAA].mp4";
        QFile f(cached);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(QByteArray(600 * 1024, 'x'));
        f.close();
        QSignalSpy done(mgr.get(), &YouTubeManager::finished);
        QCOMPARE(mgr->downloadAsync(URL_A).first, QString("cached"));
        QVERIFY(done.wait(1000));
        QCOMPARE(done.first().at(1).toString(), cached);
        QCOMPARE(done.first().at(2).toString(), QString("Old Video"));
        QCOMPARE(mgr->findExistingVideo("AAAAAAAAAAA"), cached);   // ID로도 찾음
        QVERIFY(FakeRunner::argLog().isEmpty());
    }

    void missingYtDlpIsError()
    {
        auto mgr = makeManager();
        mgr->setProgram(QString());
        QSignalSpy failed(mgr.get(), &YouTubeManager::failed);
        QCOMPARE(mgr->downloadAsync(URL_A).first, QString("error"));
        QVERIFY(failed.wait(1000));
    }

    void argumentsMatchPythonOptions()
    {
        auto mgr = makeManager();
        const QStringList args = mgr->buildArguments(URL_A, "720p");
        auto after = [&](const QString &flag) { return args.value(args.indexOf(flag) + 1); };
        QCOMPARE(after("-f"), formatForQuality("720p"));
        QCOMPARE(after("-o"), mgr->downloadDir() + "/%(title)s [%(id)s].%(ext)s");
        QCOMPARE(after("--merge-output-format"), QString("mp4"));
        QCOMPARE(after("--concurrent-fragments"), QString("4"));
        QVERIFY(args.contains("--no-playlist") && args.contains("--force-overwrites") && args.contains("--newline"));
        QVERIFY(after("--remote-components").startsWith("ejs:"));
        QCOMPARE(args.last(), URL_A);
        QCOMPARE(args.value(args.size() - 2), QString("--"));
        const auto js = jsRuntime();
        if (!js.first.isEmpty())
            QCOMPARE(after("--js-runtimes"), js.first + ":" + js.second);
    }

    void realProcessRunnerWithFakeScript()
    {
        // 실제 ProcessRunner(QProcess)로 yt-dlp 흉내 스크립트를 실행해 출력 해석·취소·부분 파일 정리를 확인
        const QString dir = m_home + "/ytproc";
        QDir().mkpath(dir);
        const QString script = dir + "/fake-yt-dlp.sh";
        QFile f(script);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("#!/bin/sh\n"
                "out=\"\"; for a in \"$@\"; do case \"$prev\" in -o) out=\"$a\";; esac; prev=\"$a\"; url=\"$a\"; done\n"
                "d=$(dirname \"$out\"); vid=${url##*=}\n"
                "case \"$url\" in *SLOWSLOWSLO*) : > \"$d/Slow [$vid].mp4.part\"; echo '[jvp-progress] downloading|10|100|NA|10|9|Slow'; sleep 30;; esac\n"
                "echo '[jvp-progress] downloading|25|100|NA|2000000|3|Fake Title'\n"
                "head -c 600000 /dev/zero > \"$d/Fake Title [$vid].mp4\"\n"
                "echo '[jvp-progress] finished|100|100|NA|NA|NA|Fake Title'\n"
                "echo \"[jvp-file] $d/Fake Title [$vid].mp4\"\n"
                "echo '[jvp-title] Fake Title'\n");
        f.close();
        QFile::setPermissions(script, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);

        YouTubeManager mgr(dir + "/dl");
        mgr.setProgram(script);
        QSignalSpy progress(&mgr, &YouTubeManager::progress), done(&mgr, &YouTubeManager::finished),
            failed(&mgr, &YouTubeManager::failed);
        QCOMPARE(mgr.downloadAsync(URL_A).first, QString("started"));
        QVERIFY(done.wait(10000));
        QCOMPARE(done.first().at(1).toString(), mgr.downloadDir() + "/Fake Title [AAAAAAAAAAA].mp4");
        QCOMPARE(done.first().at(2).toString(), QString("Fake Title"));
        QVERIFY(progress.count() >= 1);
        QCOMPARE(progress.first().at(1).toDouble(), 25.0);
        QCOMPARE(progress.first().at(2).toString(), QString("1.9 MB/s"));

        const QString slow = "https://www.youtube.com/watch?v=SLOWSLOWSLO";
        QCOMPARE(mgr.downloadAsync(slow).first, QString("started"));
        QVERIFY(testutil::waitUntil([&] { return QFile::exists(mgr.downloadDir() + "/Slow [SLOWSLOWSLO].mp4.part"); }));
        QVERIFY(mgr.cancelCurrent());
        QVERIFY(failed.wait(5000));
        QCOMPARE(failed.first().at(1).toString(), YouTubeManager::kCancelledMessage);
        QVERIFY(!QFile::exists(mgr.downloadDir() + "/Slow [SLOWSLOWSLO].mp4.part"));   // 부분 파일 정리
    }
};

QTEST_GUILESS_MAIN(TestYouTube)
#include "test_youtube.moc"
