// MediaProbe: 디코딩 없이 코덱·크로마·깊이를 읽는지 (NVDEC가 못 푸는 형식 포함)
#include "MediaProbe.h"
#include "PlayerEngine.h"
#include "Storage.h"

#include <QProcess>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtTest>

using namespace jvp;

class TestMediaProbe : public QObject {
    Q_OBJECT
    QTemporaryDir m_home;

    // gst-launch로 짧은 테스트 영상을 만듭니다 (없으면 건너뜀)
    QString make(const QString &name, const QString &pipelineTail)
    {
        const QString path = m_home.filePath(name);
        const QString launch = QStandardPaths::findExecutable("gst-launch-1.0");
        if (launch.isEmpty())
            return {};
        QProcess p;
        p.start(launch, QProcess::splitCommand(
                            QStringLiteral("-q videotestsrc num-buffers=10 ! video/x-raw,width=320,height=240 ! %1 location=%2")
                                .arg(pipelineTail, path)));
        p.waitForFinished(60000);
        return QFileInfo(path).size() > 0 ? path : QString();
    }

private slots:
    void initTestCase()
    {
        qputenv("HOME", m_home.path().toUtf8());
        qputenv("XDG_CONFIG_HOME", m_home.filePath(".config").toUtf8());
        PlayerEngine::initGStreamer();   // 실제 앱처럼 NVDEC 우선순위를 올린 상태에서
    }

    void vp8Webm()
    {
        const QString f = make("a.webm", "vp8enc ! webmmux ! filesink");
        if (f.isEmpty())
            QSKIP("vp8enc 없음");
        const auto info = probe::videoCodec(f);
        QVERIFY(info.has_value());
        QCOMPARE(info->codec, QStringLiteral("vp8"));
        QCOMPARE(info->pixFmt, QStringLiteral("yuv420p"));
        const auto hw = probe::checkHwSupport(f);
        QVERIFY(hw.supported.has_value());
    }

    void h264Mp4WithAudio()
    {
        if (!QStandardPaths::findExecutable("gst-launch-1.0").isEmpty()) {
            const QString path = m_home.filePath("b.mp4");
            QProcess p;
            p.start("gst-launch-1.0", QProcess::splitCommand(QStringLiteral(
                "-q -e videotestsrc num-buffers=10 ! x264enc ! h264parse ! mp4mux name=m ! filesink location=%1 "
                "audiotestsrc num-buffers=10 ! avenc_aac ! m.").arg(path)));
            p.waitForFinished(60000);
            if (QFileInfo(path).size() == 0)
                QSKIP("x264enc/avenc_aac 없음");
            const auto info = probe::videoCodec(path);
            QVERIFY(info.has_value());
            QCOMPARE(info->codec, QStringLiteral("h264"));
            QCOMPARE(probe::audioCodec(path), QStringLiteral("audio/mpeg"));
        }
    }

    void notAMediaFile()
    {
        const QString path = m_home.filePath("x.mp4");
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(QByteArray(4096, 'x'));
        f.close();
        QVERIFY(!probe::videoCodec(path).has_value());
        QVERIFY(!probe::checkHwSupport(path).supported.has_value());
    }

    // 개발 장비에 있는 HEVC 4:4:4 12비트 파일 (NVDEC 미지원 → 디스커버러는 실패하던 경우)
    void hevc444FromEnv()
    {
        const QString f = qEnvironmentVariable("JVP_TEST_HEVC444");
        if (f.isEmpty() || !QFileInfo::exists(f))
            QSKIP("JVP_TEST_HEVC444 미설정");
        const auto info = probe::videoCodec(f);
        QVERIFY(info.has_value());
        QCOMPARE(info->codec, QStringLiteral("hevc"));
        QCOMPARE(info->pixFmt, QStringLiteral("yuv444p12le"));
        QCOMPARE(probe::checkHwSupport(f).supported, std::optional<bool>(false));
    }
};

QTEST_GUILESS_MAIN(TestMediaProbe)
#include "test_media_probe.moc"
