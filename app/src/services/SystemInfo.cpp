#include "SystemInfo.h"

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QProcess>
#include <QUrl>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

Q_LOGGING_CATEGORY(lcSystem, "jvp.system")

namespace jvp {

namespace {
QByteArray readSmallFile(const QString &path, bool *ok)
{
    QFile f(path);
    *ok = f.open(QIODevice::ReadOnly);
    return *ok ? f.readAll().trimmed() : QByteArray();
}
} // namespace

bool SystemInfo::openFileLocation(const QString &filePath)
{
    if (filePath.isEmpty())
        return false;
    QString target = QFileInfo(filePath).absoluteFilePath();
    QString folder;
    const QFileInfo info(target);
    if (!info.exists()) {
        folder = info.absolutePath();
        if (!QFileInfo::exists(folder))
            return false;
        target = folder;
    } else {
        folder = info.isDir() ? target : info.absolutePath();
    }

    // 1. FileManager1.ShowItems — 폴더를 열고 파일에 포커스 (Nautilus, Dolphin 등)
    if (QFileInfo(target).isFile()) {
        QDBusConnection bus = QDBusConnection::sessionBus();
        if (bus.isConnected()) {
            QDBusMessage msg = QDBusMessage::createMethodCall(
                QStringLiteral("org.freedesktop.FileManager1"), QStringLiteral("/org/freedesktop/FileManager1"),
                QStringLiteral("org.freedesktop.FileManager1"), QStringLiteral("ShowItems"));
            msg << QStringList{QUrl::fromLocalFile(target).toString(QUrl::FullyEncoded)} << QString();
            const QDBusMessage reply = bus.call(msg, QDBus::Block, 2000);
            if (reply.type() == QDBusMessage::ReplyMessage)
                return true;
            qCDebug(lcSystem) << "FileManager1.ShowItems 실패:" << reply.errorMessage();
        }
    }
    // 2. xdg-open, 3. gio open — 실행 파일이 없을 때만 다음으로
    if (QProcess::startDetached(QStringLiteral("xdg-open"), {folder}))
        return true;
    if (QProcess::startDetached(QStringLiteral("gio"), {QStringLiteral("open"), folder}))
        return true;
    qCWarning(lcSystem) << "⚠️ 파일 위치를 열 수 없습니다:" << folder;
    return false;
}

QVariantMap SystemInfo::hwStats(const QString &sysRoot)
{
    const QString root = sysRoot.isEmpty() ? QString() : QDir::cleanPath(sysRoot);
    QVariantMap stats;

    // SoC 온도: thermal_zone*의 type에 cpu/gpu가 들어간 것들의 평균
    QList<double> cpuTemps, gpuTemps;
    const QDir thermal(root + QStringLiteral("/sys/devices/virtual/thermal"));
    for (const QString &zone : thermal.entryList({QStringLiteral("thermal_zone*")}, QDir::Dirs | QDir::NoDotAndDotDot)) {
        bool okType = false, okTemp = false;
        const QString type = QString::fromUtf8(readSmallFile(thermal.filePath(zone + QStringLiteral("/type")), &okType)).toLower();
        const QByteArray raw = readSmallFile(thermal.filePath(zone + QStringLiteral("/temp")), &okTemp);
        bool okNum = false;
        const double value = raw.toDouble(&okNum) / 1000.0;
        if (!okType || !okTemp || !okNum)
            continue;   // cv*-thermal처럼 읽을 수 없는 존은 건너뜀
        if (type.contains(QLatin1String("cpu")))
            cpuTemps.append(value);
        else if (type.contains(QLatin1String("gpu")))
            gpuTemps.append(value);
    }
    auto mean = [](const QList<double> &v) {
        double s = 0;
        for (double x : v)
            s += x;
        return s / v.size();
    };
    if (!cpuTemps.isEmpty())
        stats.insert(QStringLiteral("cpu_temp"), mean(cpuTemps));
    if (!gpuTemps.isEmpty())
        stats.insert(QStringLiteral("gpu_temp"), mean(gpuTemps));

    // GPU 부하: 0~1000(‰) 또는 0~100(%) 값. 파이썬 버전의 경로 + Orin(JetPack 6)의 17000000.gpu
    static const char *const gpuLoadPaths[] = {
        "/sys/devices/platform/gpu.0/load",
        "/sys/devices/gpu.0/load",
        "/sys/devices/platform/17000000.ga10b/load",
        "/sys/devices/platform/17000000.gv11b/load",
        "/sys/devices/platform/17000000.gpu/load",
    };
    for (const char *p : gpuLoadPaths) {
        const QString path = root + QLatin1String(p);
        if (!QFileInfo::exists(path))
            continue;
        bool ok = false;
        const double raw = readSmallFile(path, &ok).toDouble(&ok);
        if (!ok)
            continue;
        stats.insert(QStringLiteral("gpu_load"), raw > 100 ? raw / 10.0 : raw);
        break;
    }

    QFile meminfo(root + QStringLiteral("/proc/meminfo"));
    if (meminfo.open(QIODevice::ReadOnly)) {
        qint64 total = 0, avail = 0;
        for (const QByteArray &line : meminfo.readAll().split('\n')) {
            const QList<QByteArray> parts = line.simplified().split(' ');
            if (parts.size() < 2)
                continue;
            if (parts[0] == "MemTotal:")
                total = parts[1].toLongLong() * 1024;
            else if (parts[0] == "MemAvailable:")
                avail = parts[1].toLongLong() * 1024;
        }
        if (total > 0) {
            const double gib = 1024.0 * 1024.0 * 1024.0;
            const qint64 used = total - avail;
            stats.insert(QStringLiteral("ram_used_gb"), used / gib);
            stats.insert(QStringLiteral("ram_total_gb"), total / gib);
            stats.insert(QStringLiteral("ram_percent"), 100.0 * used / total);
        }
    }
    return stats;
}

QString SystemInfo::localIp()
{
    // UDP 소켓을 사설 주소로 "연결"만 해 보면 커널이 고른 출발 주소를 알 수 있습니다 (패킷은 나가지 않음).
    QString ip = QStringLiteral("127.0.0.1");
    const int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0)
        return ip;
    sockaddr_in dst{};
    dst.sin_family = AF_INET;
    dst.sin_port = htons(1);
    ::inet_pton(AF_INET, "10.255.255.255", &dst.sin_addr);
    if (::connect(fd, reinterpret_cast<sockaddr *>(&dst), sizeof dst) == 0) {
        sockaddr_in local{};
        socklen_t len = sizeof local;
        char buf[INET_ADDRSTRLEN] = {};
        if (::getsockname(fd, reinterpret_cast<sockaddr *>(&local), &len) == 0
            && ::inet_ntop(AF_INET, &local.sin_addr, buf, sizeof buf))
            ip = QString::fromLatin1(buf);
    }
    ::close(fd);
    if (ip == QLatin1String("0.0.0.0"))
        ip = QStringLiteral("127.0.0.1");
    return ip;
}

} // namespace jvp
