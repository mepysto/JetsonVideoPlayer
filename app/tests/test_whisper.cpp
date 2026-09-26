// AI 자막(whisper.cpp): tests/test_ai_whisper.py 이식 + 실제 whisper-cli 통합 테스트(설치되어 있을 때만).
#include "Paths.h"
#include "Whisper.h"
#include "media_test_util.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QProcess>
#include <QRegularExpression>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTest>

using namespace jvp;
using namespace jvp::ai;

namespace {
Segments parseSrt(const QString &text)
{
    static const QRegularExpression re(
        QStringLiteral(R"((\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)\n(.*?)(?:\n\n|\n?$))"),
        QRegularExpression::DotMatchesEverythingOption);
    Segments out;
    auto ms = [](const QRegularExpressionMatch &m, int i) {
        return ((m.captured(i).toLongLong() * 60 + m.captured(i + 1).toLongLong()) * 60 + m.captured(i + 2).toLongLong()) * 1000
               + m.captured(i + 3).toLongLong();
    };
    auto it = re.globalMatch(text);
    while (it.hasNext()) {
        const auto m = it.next();
        out.append({ms(m, 1), ms(m, 5), m.captured(9).trimmed()});
    }
    return out;
}

void touch(const QString &path, const QByteArray &data = {})
{
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write(data);
}
} // namespace

class TestWhisper : public QObject {
    Q_OBJECT
    QString m_home;
    QString m_realWhisper;

private slots:
    void initTestCase()
    {
        m_home = testutil::isolateHome();
        // 실제 설치(통합 테스트용)는 HOME을 바꾸기 전의 위치에서 찾습니다.
        m_realWhisper = qEnvironmentVariable("JVP_WHISPER_DIR");
        if (m_realWhisper.isEmpty())
            m_realWhisper = testutil::realHome() + "/.local/share/jetson_video_player/whisper.cpp";
        qunsetenv("JVP_WHISPER_DIR");
    }

    void parseLines()
    {
        QCOMPARE(parseWhisperLine("[00:00:01.000 --> 00:00:04.500]   Hello there"), (Segment{1000, 4500, "Hello there"}));
        QCOMPARE(parseWhisperLine(QStringLiteral("[01:02:03.25 --> 01:02:04.000]  안녕")),
                 (Segment{3723250, 3724000, QStringLiteral("안녕")}));
        QVERIFY(!parseWhisperLine("[00:00:01.000 --> 00:00:02.000]   [BLANK_AUDIO]"));
        QVERIFY(!parseWhisperLine("[00:00:01.000 --> 00:00:02.000]   [Music]"));
        QVERIFY(!parseWhisperLine("whisper_init_from_file: loading model"));
        QVERIFY(!parseWhisperLine("[00:00:02.000 --> 00:00:02.000]   zero length"));
        QCOMPARE(parseDetectedLanguage("whisper_full_with_state: auto-detected language: en (p = 0.97)"), QString("en"));
    }

    void planPassesStartsAtCurrentPosition()
    {
        const qint64 minute = 60000;
        auto passes = planPasses(20 * minute, 10 * minute);
        QCOMPARE(passes.first(), (QPair<qint64, qint64>{10 * minute, minute}));   // 현재 위치의 짧은 첫 구간
        auto covered = passes;
        std::sort(covered.begin(), covered.end());
        qint64 pos = 0;
        for (const auto &p : covered) {   // 빈틈/중복 없이 전체를 덮음
            QCOMPARE(p.first, pos);
            pos += p.second;
        }
        QCOMPARE(pos, 20 * minute);
        QCOMPARE(planPasses(10 * minute, 10000).first().first, 0);   // 30초 이내면 처음부터
    }

    void formatSrtRoundtrip()
    {
        const QString srt = formatSrt({{3000, 4000, QStringLiteral("둘")}, {0, 1500, QStringLiteral("하나")}});
        QVERIFY(srt.startsWith("1\n00:00:00,000 --> 00:00:01,500\n"));
        QCOMPARE(parseSrt(srt), (Segments{{0, 1500, QStringLiteral("하나")}, {3000, 4000, QStringLiteral("둘")}}));
        QVERIFY(formatSrt({{3723004, 3724000, "x"}}).contains("01:02:03,004 --> 01:02:04,000"));
    }

    void aiSubtitlePathNextToVideo()
    {
        const QString video = m_home + "/movie.mkv";
        touch(video);
        QCOMPARE(aiSubtitlePath(video, "ko"), m_home + "/movie.ai.ko.srt");
        QVERIFY(aiSubtitlePath(video, "ko", true).endsWith("movie.ai.en.srt"));
        QCOMPARE(aiSubtitlePath(video, ""), m_home + "/movie.ai.auto.srt");
        QCOMPARE(fileStem("/x/.hidden"), QString(".hidden"));
        QCOMPARE(fileStem("/x/a.b.mkv"), QString("a.b"));
    }

    void readOnlyFolderSavesToCacheWithFolderHash()
    {
        QStringList results;
        for (const char *show : {"showA", "showB"}) {
            const QString folder = m_home + "/" + show;
            QDir().mkpath(folder);
            touch(folder + "/ep1.mkv", "x");
            QFile::setPermissions(folder, QFileDevice::ReadOwner | QFileDevice::ExeOwner);   // 쓰기 불가
            results << aiSubtitlePath(folder + "/ep1.mkv", "ko");
            QFile::setPermissions(folder, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);
        }
        if (::geteuid() == 0)
            QSKIP("root는 권한 검사를 무시합니다");
        QCOMPARE(QFileInfo(results[0]).absolutePath(), paths::aiSubtitleCacheDir());
        QVERIFY(results[0] != results[1]);   // 같은 이름의 다른 폴더 영상과 섞이지 않음
        const QString hash = QString::fromLatin1(
            QCryptographicHash::hash((m_home + "/showA").toUtf8(), QCryptographicHash::Sha1).toHex().left(8));
        QCOMPARE(QFileInfo(results[0]).fileName(), "ep1." + hash + ".ai.ko.srt");
        QCOMPARE(aiSubtitlePathFor(m_home + "/showA/ep1.mkv", "ko", false, false), results[0]);

        // 파이썬 cached_ai_subtitle_stem과 같은 이름인지 직접 비교
        const QString py = QStandardPaths::findExecutable("python3");
        if (!py.isEmpty()) {
            QProcess p;
            p.start(py, {"-c", "import hashlib,os,sys;v=sys.argv[1];s=os.path.splitext(os.path.basename(v))[0];"
                               "f=os.path.dirname(os.path.abspath(v));print(f'{s}.{hashlib.sha1(f.encode()).hexdigest()[:8]}')",
                         m_home + QStringLiteral("/showA/../showA/ep1.mkv")});
            QVERIFY(p.waitForFinished(10000));
            QCOMPARE(cachedAiSubtitleStem(m_home + "/showA/../showA/ep1.mkv"), QString::fromUtf8(p.readAllStandardOutput()).trimmed());
        }
    }

    void listModelsIgnoresTestFixtures()
    {
        const QString dir = m_home + "/wh";
        QDir().mkpath(dir + "/models");
        for (const char *n : {"ggml-small-q5_1.bin", "ggml-large-v3-turbo-q5_0.bin", "for-tests-ggml-tiny.bin",
                              "ggml-x.bin.part", "README.md"})
            touch(dir + "/models/" + n);
        qputenv("JVP_WHISPER_DIR", dir.toUtf8());
        QCOMPARE(listWhisperModels(), (QStringList{"large-v3-turbo-q5_0", "small-q5_1"}));
        QVERIFY(findWhisperModel("large-v3-turbo-q5_0").endsWith("ggml-large-v3-turbo-q5_0.bin"));
        QVERIFY(findWhisperModel("medium").endsWith(".bin"));   // 없는 모델이면 설치된 것 사용
        QVERIFY(findWhisperBinary().isEmpty() || !findWhisperBinary().startsWith(dir));
        qunsetenv("JVP_WHISPER_DIR");
        QVERIFY(listWhisperModels().isEmpty());                 // 임시 HOME에는 설치 없음
    }

    void missingInstallReportsError()
    {
        qputenv("JVP_WHISPER_DIR", QByteArray("/nonexistent"));
        qputenv("JVP_WHISPER_BIN", QByteArray("/nonexistent/whisper-cli"));
        const QString savedPath = qEnvironmentVariable("PATH");
        qputenv("PATH", QByteArray("/nonexistent"));
        AiSubtitleJob job(m_home + "/movie.mkv", 1000);
        QSignalSpy done(&job, &AiSubtitleJob::done);
        job.start();
        QVERIFY(done.wait(5000));
        QVERIFY(done.first().at(2).toString().contains("whisper.cpp"));
        qputenv("PATH", savedPath.toUtf8());
        qunsetenv("JVP_WHISPER_DIR");
        qunsetenv("JVP_WHISPER_BIN");
    }

    void extractAudioSkipsVideoDecoding()
    {
        // 영상은 디코딩하지 않으므로 NVDEC가 못 여는 HEVC 4:4:4 12비트 영상에서도 음성을 추출합니다.
        if (!testutil::hasElements({"x265enc", "h265parse", "matroskamux", "vorbisenc", "wavenc"}))
            QSKIP("GStreamer 요소 없음");
        const QString video = m_home + "/h444a.mkv";
        QString err;
        QVERIFY2(testutil::runPipeline(
                     QStringLiteral("videotestsrc num-buffers=10 ! video/x-raw,width=320,height=180,framerate=5/1,"
                                    "format=Y444_12LE ! x265enc ! h265parse ! matroskamux name=m ! filesink location=\"%1\" "
                                    "audiotestsrc num-buffers=40 samplesperbuffer=2205 ! audioconvert ! vorbisenc ! m.")
                         .arg(video),
                     60, &err),
                 qPrintable(err));
        const QString wav = m_home + "/x.wav";
        QCOMPARE(extractAudioWav(video, wav), QString());
        QVERIFY(QFileInfo(wav).size() > 16000 * 2 * 1.5);   // 약 2초 × 16kHz × 16bit

        const QString silent = m_home + "/silent.mkv";
        QVERIFY(testutil::makeTestVideo(silent, 1, 25, false, 160, 120));
        QCOMPARE(extractAudioWav(silent, m_home + "/y.wav"), QStringLiteral("영상에 음성 트랙이 없습니다."));
        QVERIFY(extractAudioWav(m_home + "/missing.mkv", m_home + "/z.wav").startsWith(QStringLiteral("음성 추출 실패")));
    }

    void transcribesRealSpeech()
    {
        // whisper.cpp 저장소의 JFK 연설 샘플(11초)을 영상(VP8+Vorbis MKV)으로 만든 뒤 전체 과정을 돌립니다.
        qputenv("JVP_WHISPER_DIR", m_realWhisper.toUtf8());
        const QString sample = m_realWhisper + "/samples/jfk.wav";
        if (!whisperAvailable() || !QFile::exists(sample)) {
            qunsetenv("JVP_WHISPER_DIR");
            QSKIP("whisper.cpp 또는 샘플이 설치되어 있지 않습니다");
        }
        const QString video = m_home + "/jfk.mkv";
        QString err;
        QVERIFY2(testutil::runPipeline(
                     QStringLiteral("filesrc location=\"%1\" ! wavparse ! audioconvert ! audioresample ! vorbisenc ! "
                                    "matroskamux name=m ! filesink location=\"%2\" videotestsrc num-buffers=55 ! "
                                    "video/x-raw,width=160,height=90,framerate=5/1 ! vp8enc deadline=1 ! m.")
                         .arg(sample, video),
                     30, &err),
                 qPrintable(err));

        AiSubtitleJob job(video, 11000, 0, "auto", false, "small-q5_1");
        QSignalSpy segs(&job, &AiSubtitleJob::segments), status(&job, &AiSubtitleJob::status),
            done(&job, &AiSubtitleJob::done);
        QElapsedTimer t;
        t.start();
        job.start();
        QVERIFY(done.wait(60000));
        const auto args = done.first();
        qInfo("whisper: %.1f s, language=%s, error='%s', srt=%s", t.elapsed() / 1000.0,
              qPrintable(args.at(1).toString()), qPrintable(args.at(2).toString()), qPrintable(args.at(0).toString()));
        QVERIFY2(args.at(2).toString().isEmpty(), qPrintable(args.at(2).toString()));
        QCOMPARE(args.at(0).toString(), m_home + "/jfk.ai.en.srt");
        QCOMPARE(args.at(1).toString(), QString("en"));
        QCOMPARE(job.detectedLanguage(), QString("en"));
        QVERIFY(segs.count() >= 1);
        QVERIFY(status.count() >= 2);
        QFile f(args.at(0).toString());
        QVERIFY(f.open(QIODevice::ReadOnly));
        const QString srt = QString::fromUtf8(f.readAll());
        const auto parsed = parseSrt(srt);
        QVERIFY(!parsed.isEmpty());
        qInfo("%s", qPrintable(srt.left(300)));
        QVERIFY(srt.contains("country", Qt::CaseInsensitive));
        qunsetenv("JVP_WHISPER_DIR");
    }

    void cancelStopsWhisper()
    {
        qputenv("JVP_WHISPER_DIR", m_realWhisper.toUtf8());
        const QString video = m_home + "/jfk.mkv";
        if (!whisperAvailable() || !QFile::exists(video)) {
            qunsetenv("JVP_WHISPER_DIR");
            QSKIP("whisper.cpp 없음");
        }
        AiSubtitleJob job(video, 11000);
        QSignalSpy done(&job, &AiSubtitleJob::done);
        job.start();
        QTest::qWait(300);
        job.cancel();
        QVERIFY(done.wait(15000));
        QCOMPARE(done.first().at(2).toString(), QStringLiteral("취소됨"));
        QVERIFY(done.first().at(0).toString().isEmpty());
        qunsetenv("JVP_WHISPER_DIR");
    }
};

QTEST_GUILESS_MAIN(TestWhisper)
#include "test_whisper.moc"
