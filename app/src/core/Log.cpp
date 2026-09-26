#include "Log.h"

#include "Paths.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QMutex>
#include <QMutexLocker>

#include <cstdio>

namespace jvp::log {

namespace {

struct State {
    QMutex mutex;
    QFile file;
    QString path;
    QString level = QStringLiteral("INFO");
    bool installed = false;
    QtMessageHandler previous = nullptr;
};

State &state()
{
    static State s;
    return s;
}

const char *levelName(QtMsgType type)
{
    switch (type) {
    case QtDebugMsg:
        return "DEBUG";
    case QtInfoMsg:
        return "INFO";
    case QtWarningMsg:
        return "WARNING";
    case QtCriticalMsg:
        return "ERROR";
    case QtFatalMsg:
        return "CRITICAL";
    }
    return "INFO";
}

// [잠금 보유] RotatingFileHandler와 같이: 이번 기록으로 한도를 넘으면 .1 → .2 … 로 밀어내고 새 파일
void rollover(State &s)
{
    s.file.close();
    for (int i = kBackups - 1; i >= 1; --i) {
        const QString src = QStringLiteral("%1.%2").arg(s.path).arg(i);
        const QString dst = QStringLiteral("%1.%2").arg(s.path).arg(i + 1);
        if (QFile::exists(src)) {
            QFile::remove(dst);
            QFile::rename(src, dst);
        }
    }
    const QString first = s.path + QStringLiteral(".1");
    QFile::remove(first);
    QFile::rename(s.path, first);
    s.file.setFileName(s.path);
    // 다시 열지 못하면 파일 기록만 빠지고 stderr 출력은 계속됩니다
    (void)s.file.open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text);
}

void handler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    State &s = state();
    // 터미널에는 메시지만 (파이썬 버전과 같은 모양)
    const QByteArray line = msg.toUtf8() + '\n';
    std::fwrite(line.constData(), 1, size_t(line.size()), stderr);
    std::fflush(stderr);

    QMutexLocker lock(&s.mutex);
    if (!s.file.isOpen())
        return;
    const QString category = context.category ? QString::fromUtf8(context.category) : QStringLiteral("default");
    const QByteArray record = QStringLiteral("%1 %2 %3: %4\n")
                                  .arg(QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-dd HH:mm:ss,zzz")),
                                       QStringLiteral("%1").arg(QLatin1String(levelName(type)), -7), category, msg)
                                  .toUtf8();
    if (s.file.size() + record.size() >= kMaxBytes && s.file.size() > 0)
        rollover(s);
    if (s.file.isOpen()) {
        s.file.write(record);
        s.file.flush();
    }
}

int levelValue(const QString &name)
{
    if (name == QLatin1String("DEBUG"))
        return 10;
    if (name == QLatin1String("INFO"))
        return 20;
    if (name == QLatin1String("WARNING") || name == QLatin1String("WARN"))
        return 30;
    if (name == QLatin1String("ERROR"))
        return 40;
    if (name == QLatin1String("CRITICAL") || name == QLatin1String("FATAL"))
        return 50;
    return -1;
}

} // namespace

QString defaultLogFile() { return paths::cacheDir() + QStringLiteral("/player.log"); }

QString setupLogging(const QString &levelIn, const QString &logFile)
{
    QString name = (levelIn.isEmpty() ? qEnvironmentVariable("JVP_LOG_LEVEL") : levelIn).trimmed().toUpper();
    if (name.isEmpty())
        name = QStringLiteral("INFO");
    int value = levelValue(name);
    if (value < 0) {
        name = QStringLiteral("INFO");
        value = 20;
    }
    if (name == QLatin1String("WARN"))
        name = QStringLiteral("WARNING");
    if (name == QLatin1String("FATAL"))
        name = QStringLiteral("CRITICAL");

    // 수준은 분류(category) 필터 규칙으로: 걸러진 메시지는 문자열을 만들지도 않습니다.
    // QT_LOGGING_RULES 환경 변수가 이 규칙보다 우선하므로 특정 분류만 더 자세히 볼 수도 있습니다.
    QStringList rules;
    if (value <= 10)
        rules << QStringLiteral("jvp.*.debug=true");
    else
        rules << QStringLiteral("*.debug=false");
    if (value > 20)
        rules << QStringLiteral("*.info=false");
    if (value > 30)
        rules << QStringLiteral("*.warning=false");
    QLoggingCategory::setFilterRules(rules.join(QLatin1Char('\n')));

    State &s = state();
    QString openError;
    {
        QMutexLocker lock(&s.mutex);
        s.level = name;
        s.file.close();
        s.path.clear();
        if (!logFile.isEmpty()) {
            QDir().mkpath(QFileInfo(logFile).absolutePath());
            s.file.setFileName(logFile);
            if (s.file.open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text))
                s.path = logFile;
            else
                openError = s.file.errorString();
        }
        if (!s.installed) {
            s.previous = qInstallMessageHandler(handler);
            s.installed = true;
        }
    }
    if (!openError.isEmpty())
        qWarning().noquote() << QStringLiteral("⚠️ 로그 파일을 열 수 없어 터미널에만 기록합니다 (%1): %2").arg(logFile, openError);
    return name;
}

void shutdownLogging()
{
    State &s = state();
    QMutexLocker lock(&s.mutex);
    if (s.installed) {
        qInstallMessageHandler(s.previous);
        s.installed = false;
        s.previous = nullptr;
    }
    s.file.close();
    s.path.clear();
    QLoggingCategory::setFilterRules(QString());
}

QString logFilePath()
{
    State &s = state();
    QMutexLocker lock(&s.mutex);
    return s.path;
}

QString currentLevel()
{
    State &s = state();
    QMutexLocker lock(&s.mutex);
    return s.level;
}

} // namespace jvp::log
