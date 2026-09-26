// 장면 전환 검출(tests/test_scenes.py 이식)과 썸네일 캐시·정밀 장면 분석 작업.
#include "Paths.h"
#include "Scenes.h"
#include "Thumbnails.h"
#include "media_test_util.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QImage>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTest>

#include <random>

using namespace jvp;
using namespace jvp::scenes;

namespace {
constexpr qint64 S = 1000000000LL;

std::vector<Signature> sceneSigs(std::initializer_list<float> levels, int perScene = 10, double noise = 2.0,
                                 unsigned seed = 0)
{
    std::mt19937 rng(seed);
    std::normal_distribution<float> nd(0.f, float(noise));
    std::vector<Signature> sigs;
    for (float level : levels)
        for (int k = 0; k < perScene; ++k) {
            Signature s(kSignatureLen);
            for (float &v : s)
                v = level + nd(rng);
            sigs.push_back(s);
        }
    return sigs;
}

QList<qint64> seq(int n, qint64 step)
{
    QList<qint64> out;
    for (int i = 0; i < n; ++i)
        out.append(i * step);
    return out;
}
} // namespace

class TestScenesThumbnails : public QObject {
    Q_OBJECT
    QString m_home;
    QString m_video;

private slots:
    void initTestCase()
    {
        m_home = testutil::isolateHome();
        QVERIFY(paths::thumbRoot().startsWith(m_home));   // 실제 캐시를 건드리지 않음
    }

    // ---- scenes.py ----
    void detectsHardCuts()
    {
        auto sigs = sceneSigs({30, 200, 90, 160});
        const auto positions = seq(int(sigs.size()), 10 * S);
        const auto found = detectSceneChanges(sigs, positions, qint64(sigs.size()) * 10 * S);
        QCOMPARE(found, (QList<qint64>{100 * S, 200 * S, 300 * S}));
    }

    void noCutsInStaticVideo()
    {
        auto sigs = sceneSigs({100}, 40);
        QVERIFY(detectSceneChanges(sigs, seq(40, S), 40 * S).isEmpty());
    }

    void minGapAndShortInput()
    {
        std::vector<Signature> two(2, Signature(kSignatureLen, 0.f));
        QVERIFY(detectSceneChanges(two, {0, S}, 2 * S).isEmpty());
        // 2초와 3초의 전환은 최소 간격(1.2초)보다 가까우므로 하나만 남깁니다.
        auto sigs = sceneSigs({30}, 2);
        for (auto &s : sceneSigs({200}, 1))
            sigs.push_back(s);
        for (auto &s : sceneSigs({30}, 3))
            sigs.push_back(s);
        const auto found = detectSceneChanges(sigs, seq(6, S), 6 * S, 6.0, 0.2);
        QCOMPARE(found.size(), 1);
        QVERIFY(found[0] == 2 * S || found[0] == 3 * S);
    }

    void imageSignatureShapeAndValues()
    {
        const int w = 32, h = 18;
        std::vector<uchar> rgba(size_t(w) * h * 4, 0);
        for (int y = 0; y < h; ++y)
            for (int x = 0; x < w / 2; ++x)
                rgba[(size_t(y) * w + x) * 4] = 255;   // 왼쪽 절반 빨강
        const auto sig = imageSignature(rgba.data(), w, h);
        QCOMPARE(int(sig.size()), 9 * 16 * 3);
        QCOMPARE(sig[0], 255.f);                 // [0,0,R]
        QCOMPARE(sig[15 * 3], 0.f);              // [0,15,R]
    }

    // ---- thumbnails.py ----
    void sampleCountRule()
    {
        QCOMPARE(thumbnailSampleCount(30 * S), 20);
        QCOMPARE(thumbnailSampleCount(600 * S), 60);
        QCOMPARE(thumbnailSampleCount(7200 * S), 120);
    }

    void nearestThumbnailRule()
    {
        ThumbnailIndex idx;
        idx.positions = {0, 10 * S, 20 * S};
        idx.files = {"000.jpg", "001.jpg", "002.jpg"};
        QCOMPARE(nearestThumbnail(idx, 4 * S), 0);
        QCOMPARE(nearestThumbnail(idx, 6 * S), 1);        // 다음 것이 더 가까움
        QCOMPARE(nearestThumbnail(idx, 1 * S, true), 1);  // 그 시각 이후의 첫 썸네일
        QCOMPARE(nearestThumbnail(idx, 10 * S, true), 1);
        QCOMPARE(nearestThumbnail(idx, 99 * S), 2);
        QCOMPARE(nearestThumbnail(idx, -5), 0);
        QCOMPARE(nearestThumbnail(ThumbnailIndex(), 0), -1);
    }

    void cacheDirMatchesPythonHashing()
    {
        const QString f = m_home + QStringLiteral("/한글 이름.mkv");
        QFile file(f);
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write("abc");
        file.close();
        const QString py = QStandardPaths::findExecutable("python3");
        if (py.isEmpty())
            QSKIP("python3 없음");
        QProcess p;
        p.start(py, {"-c", "import hashlib,os,sys;p=sys.argv[1];st=os.stat(p);"
                           "k=f'{os.path.abspath(p)}|{st.st_size}|{int(st.st_mtime)}';"
                           "print(os.path.join(os.path.expanduser('~/.cache/jetson_video_player/thumbs'),"
                           "hashlib.sha1(k.encode()).hexdigest()[:20]))",
                     f});
        QVERIFY(p.waitForFinished(10000));
        QCOMPARE(thumbnailCacheDir(f), QString::fromUtf8(p.readAllStandardOutput()).trimmed());
    }

    void readsPythonIndexFormat()
    {
        const QString f = m_home + QStringLiteral("/py.mkv");
        QFile file(f);
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write("x");
        file.close();
        const QString dir = thumbnailCacheDir(f);
        QVERIFY(QDir().mkpath(dir));
        QFile idx(dir + "/index.json");
        QVERIFY(idx.open(QIODevice::WriteOnly));
        // 파이썬 json.dump(indent=2) 출력 그대로
        idx.write("{\n  \"version\": 1,\n  \"complete\": true,\n  \"duration\": 30000000000,\n"
                  "  \"positions\": [\n    750000000,\n    2250000000\n  ],\n  \"files\": [\n    \"000.jpg\",\n"
                  "    \"001.jpg\"\n  ],\n  \"scenes\": [\n    2250000000\n  ],\n  \"scenes_precise\": [10000000000]\n}");
        idx.close();
        const auto loaded = loadThumbnailIndex(f);
        QVERIFY(loaded.has_value());
        QCOMPARE(loaded->dir, dir);
        QCOMPARE(loaded->positions, (QList<qint64>{750000000LL, 2250000000LL}));
        QCOMPARE(loaded->scenes, (QList<qint64>{2250000000LL}));
        QVERIFY(loaded->scenesPrecise.has_value() && loaded->scenesPrecise->value(0) == 10 * S);
        QCOMPARE(loaded->filePath(1), dir + "/001.jpg");

        ThumbnailJob job(f);   // 캐시가 있으면 스레드 없이 done
        QSignalSpy spy(&job, &ThumbnailJob::done);
        job.start();
        QVERIFY(!job.isRunning());
        QVERIFY(spy.wait(1000));
        QCOMPARE(spy.first().first().value<ThumbnailIndex>().files.size(), 2);
    }

    void generatesThumbnailsAndScenes()
    {
        // 검정 10초 → 흰색 10초 → 빨강 10초 (5fps, 모든 프레임이 키프레임)
        if (!testutil::hasElements({"videotestsrc", "vp8enc", "matroskamux", "concat"}))
            QSKIP("GStreamer 요소 없음");
        m_video = m_home + QStringLiteral("/scenes.mkv");
        const QString seg = QStringLiteral("videotestsrc pattern=%1 num-buffers=50 ! video/x-raw,width=320,height=180,framerate=5/1 ! c. ");
        QString err;
        QVERIFY2(testutil::runPipeline(QStringLiteral("concat name=c ! videoconvert ! vp8enc deadline=1 keyframe-max-dist=1 ! "
                                                      "matroskamux ! filesink location=\"%1\" ").arg(m_video)
                                           + seg.arg("black") + seg.arg("white") + seg.arg("red"),
                                       60, &err),
                 qPrintable(err));

        ThumbnailJob job(m_video);
        QSignalSpy done(&job, &ThumbnailJob::done), progress(&job, &ThumbnailJob::progress),
            failed(&job, &ThumbnailJob::failed);
        job.start();
        QVERIFY(done.wait(60000));
        QCOMPARE(failed.count(), 0);
        QVERIFY(progress.count() >= 1);
        const auto idx = done.first().first().value<ThumbnailIndex>();
        qInfo("thumbnails: %d, duration %.2fs, scenes %s", int(idx.files.size()), idx.duration / 1e9,
              qPrintable([&] { QStringList s; for (auto x : idx.scenes) s << QString::number(x / 1e9, 'f', 2); return s.join(','); }()));
        QVERIFY(idx.files.size() >= 18 && idx.files.size() <= 20);
        QVERIFY(std::is_sorted(idx.positions.begin(), idx.positions.end()));
        QCOMPARE(idx.dir, thumbnailCacheDir(m_video));
        const QImage first(idx.filePath(0));
        QCOMPARE(first.width(), kThumbWidth);
        QCOMPARE(first.height(), 90);
        QCOMPARE(idx.scenes.size(), 2);
        QVERIFY(std::llabs(idx.scenes[0] - 10 * S) < 2 * S);
        QVERIFY(std::llabs(idx.scenes[1] - 20 * S) < 2 * S);

        QFile f(idx.dir + "/index.json");
        QVERIFY(f.open(QIODevice::ReadOnly));
        const QJsonObject o = QJsonDocument::fromJson(f.readAll()).object();
        QCOMPARE(o.value("version").toInt(), 1);
        QVERIFY(o.value("complete").toBool());
        QCOMPARE(o.value("positions").toArray().size(), idx.files.size());
        QVERIFY(loadThumbnailIndex(m_video).has_value());
    }

    void preciseSceneAnalysis()
    {
        if (m_video.isEmpty() || !QFile::exists(m_video))
            QSKIP("테스트 영상 없음");
        SceneAnalysisJob job(m_video);
        QSignalSpy done(&job, &SceneAnalysisJob::done);
        job.start();
        QVERIFY(done.wait(60000));
        const auto args = done.first();
        QVERIFY(args.at(1).toBool());
        const auto found = args.at(0).value<QList<qint64>>();
        qInfo("precise scenes: %s", qPrintable([&] { QStringList s; for (auto x : found) s << QString::number(x / 1e9, 'f', 3); return s.join(','); }()));
        QCOMPARE(found.size(), 2);
        QVERIFY(std::llabs(found[0] - 10 * S) <= S / 5);   // 프레임 단위 (5fps)
        QVERIFY(std::llabs(found[1] - 20 * S) <= S / 5);
        const auto idx = loadThumbnailIndex(m_video);
        QVERIFY(idx && idx->scenesPrecise && *idx->scenesPrecise == found);   // index.json에 저장됨
    }

    void nvdecUnsupportedFormatFallsBackToSoftware()
    {
        // HEVC main-444-12: NVDEC가 열지 못합니다 ("unsupported pixel format"). 길이·크기는 parsebin으로 읽고,
        // 디코딩은 소프트웨어(avdec_h265)로 넘어가야 합니다.
        if (!testutil::hasElements({"x265enc", "h265parse", "mp4mux", "avdec_h265"}))
            QSKIP("x265enc/avdec_h265 없음");
        const QString path = m_home + QStringLiteral("/h444.mp4");
        QString err;
        QVERIFY2(testutil::runPipeline(QStringLiteral("videotestsrc num-buffers=50 ! video/x-raw,width=320,height=180,"
                                                      "framerate=5/1,format=Y444_12LE ! x265enc key-int-max=5 ! h265parse ! "
                                                      "mp4mux ! filesink location=\"%1\"").arg(path),
                                       60, &err),
                 qPrintable(err));
        ThumbnailJob job(path);
        QSignalSpy done(&job, &ThumbnailJob::done), failed(&job, &ThumbnailJob::failed);
        job.start();
        QVERIFY(testutil::waitUntil([&] { return done.count() || failed.count(); }, 60000));
        QVERIFY2(failed.isEmpty(), failed.isEmpty() ? "" : qPrintable(failed.first().first().toString()));
        const auto idx = done.first().first().value<ThumbnailIndex>();
        qInfo("HEVC 4:4:4 12-bit: %d thumbnails, duration %.2fs", int(idx.files.size()), idx.duration / 1e9);
        QVERIFY(std::llabs(idx.duration - 10 * S) < S / 2);
        QVERIFY(idx.files.size() >= 8);   // 키프레임 1초 간격 → 20개 지점 중 같은 키프레임은 한 번만
        QCOMPARE(QImage(idx.filePath(0)).size(), QSize(kThumbWidth, 90));

        SceneAnalysisJob sa(path);
        QSignalSpy saDone(&sa, &SceneAnalysisJob::done);
        sa.start();
        QVERIFY(saDone.wait(60000));
        QVERIFY(saDone.first().at(1).toBool());
    }

    void cancelStopsJobs()
    {
        if (m_video.isEmpty() || !QFile::exists(m_video))
            QSKIP("테스트 영상 없음");
        QDir(thumbnailCacheDir(m_video)).removeRecursively();
        auto *job = new ThumbnailJob(m_video);
        QSignalSpy done(job, &ThumbnailJob::done);
        job->start();
        QTest::qWait(100);
        job->cancel();
        QVERIFY(testutil::waitUntil([&] { return !job->isRunning(); }, 10000));
        QTest::qWait(50);
        QCOMPARE(done.count(), 0);
        QVERIFY(!loadThumbnailIndex(m_video).has_value());
        delete job;

        SceneAnalysisJob sa(m_video);
        QSignalSpy saDone(&sa, &SceneAnalysisJob::done);
        sa.start();
        sa.cancel();
        QVERIFY(saDone.wait(10000));
        QVERIFY(!saDone.first().at(1).toBool());
    }
};

QTEST_MAIN(TestScenesThumbnails)
#include "test_scenes_thumbnails.moc"
