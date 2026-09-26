// log.py 이식 검증 (tests/test_log.py 대응)
#include "Log.h"

#include <QFile>
#include <QLoggingCategory>
#include <QRegularExpression>
#include <QTemporaryDir>
#include <QTest>

#include <cstdio>
#include <fcntl.h>
#include <unistd.h>

Q_LOGGING_CATEGORY(lcTest, "jvp.test")

namespace {
QString readAll(const QString &path)
{
    QFile f(path);
    return f.open(QIODevice::ReadOnly) ? QString::fromUtf8(f.readAll()) : QString();
}

// 표준 오류를 잠시 파일로 돌려 터미널 출력 확인
class StderrCapture {
public:
    explicit StderrCapture(const QString &path)
    {
        std::fflush(stderr);
        m_saved = ::dup(2);
        const int fd = ::open(QFile::encodeName(path).constData(), O_WRONLY | O_CREAT | O_TRUNC, 0600);
        ::dup2(fd, 2);
        ::close(fd);
    }
    ~StderrCapture()
    {
        std::fflush(stderr);
        ::dup2(m_saved, 2);
        ::close(m_saved);
    }

private:
    int m_saved = -1;
};
} // namespace

class TestLog : public QObject {
    Q_OBJECT
    QTemporaryDir m_dir;

private slots:
    void cleanup() { jvp::log::shutdownLogging(); }

    void writesFileAndConsole()
    {
        const QString logFile = m_dir.filePath("sub/player.log");
        QCOMPARE(jvp::log::setupLogging("DEBUG", logFile), QString("DEBUG"));
        QCOMPARE(jvp::log::logFilePath(), logFile);
        const QString errFile = m_dir.filePath("stderr.txt");
        {
            StderrCapture cap(errFile);
            qCWarning(lcTest) << "⚠️ 테스트 경고";
            qCDebug(lcTest) << "디버그 보임";
        }
        const QString text = readAll(logFile);
        QVERIFY2(text.contains("⚠️ 테스트 경고"), qPrintable(text));
        QVERIFY(text.contains("WARNING jvp.test: "));
        QVERIFY(text.contains("DEBUG   jvp.test: "));
        QVERIFY(QRegularExpression("^\\d{4}-\\d\\d-\\d\\d \\d\\d:\\d\\d:\\d\\d,\\d{3} WARNING").match(text).hasMatch());
        const QString err = readAll(errFile);
        QVERIFY(err.contains("⚠️ 테스트 경고\n"));
        QVERIFY(!err.contains("jvp.test"));   // 터미널에는 메시지만
    }

    void levelFiltersDebug()
    {
        const QString logFile = m_dir.filePath("level.log");
        QCOMPARE(jvp::log::setupLogging("info", logFile), QString("INFO"));
        {
            StderrCapture cap(m_dir.filePath("e2.txt"));
            qCDebug(lcTest) << "숨김";
            qCInfo(lcTest) << "정보";
        }
        const QString text = readAll(logFile);
        QVERIFY(!text.contains("숨김"));
        QVERIFY(text.contains("INFO    jvp.test: 정보"));

        QCOMPARE(jvp::log::setupLogging("WARNING", logFile), QString("WARNING"));
        {
            StderrCapture cap(m_dir.filePath("e3.txt"));
            qCInfo(lcTest) << "정보2";
        }
        QVERIFY(!readAll(logFile).contains("정보2"));
    }

    void unknownLevelFallsBackToInfo()
    {
        QCOMPARE(jvp::log::setupLogging("LOUD", QString()), QString("INFO"));
        QCOMPARE(jvp::log::currentLevel(), QString("INFO"));
        QVERIFY(jvp::log::logFilePath().isEmpty());
        qputenv("JVP_LOG_LEVEL", "error");
        QCOMPARE(jvp::log::setupLogging(QString(), QString()), QString("ERROR"));
        qunsetenv("JVP_LOG_LEVEL");
    }

    void rotates()
    {
        const QString logFile = m_dir.filePath("rot/player.log");
        jvp::log::setupLogging("INFO", logFile);
        const QString chunk(2000, QChar('x'));
        {
            StderrCapture cap(m_dir.filePath("e4.txt"));
            for (int i = 0; i < 2600; ++i)   // 약 5 MB → 1 MB씩 회전, 백업은 3개까지
                qCWarning(lcTest).noquote() << chunk;
        }
        QVERIFY(QFile::exists(logFile + ".1"));
        QVERIFY(QFile::exists(logFile + ".3"));
        QVERIFY(!QFile::exists(logFile + ".4"));
        QVERIFY(QFile(logFile).size() < jvp::log::kMaxBytes);
        QVERIFY(QFile(logFile + ".1").size() <= jvp::log::kMaxBytes);
    }

    void unwritableFileFallsBackToConsole()
    {
        const QString blocker = m_dir.filePath("blocker");
        QFile f(blocker);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.close();
        StderrCapture cap(m_dir.filePath("e5.txt"));
        QCOMPARE(jvp::log::setupLogging("INFO", blocker + "/player.log"), QString("INFO"));
        QVERIFY(jvp::log::logFilePath().isEmpty());
    }
};

QTEST_GUILESS_MAIN(TestLog)
#include "test_log.moc"
