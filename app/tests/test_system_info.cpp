// 시스템 유틸리티: LAN 주소, Jetson 하드웨어 상태 (가짜 sysfs + 실제 장치)
#include "SystemInfo.h"

#include <QDir>
#include <QFile>
#include <QHostAddress>
#include <QTemporaryDir>
#include <QtTest>

using namespace jvp;

class TestSystemInfo : public QObject {
    Q_OBJECT

    static void write(const QString &path, const QByteArray &data)
    {
        QDir().mkpath(QFileInfo(path).absolutePath());
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(data);
    }

private Q_SLOTS:
    void localIp()
    {
        const QString ip = SystemInfo::localIp();
        QVERIFY(!ip.isEmpty());
        QHostAddress addr;
        QVERIFY(addr.setAddress(ip));
        QCOMPARE(addr.protocol(), QAbstractSocket::IPv4Protocol);
    }

    void statsFromFakeSysfs()
    {
        QTemporaryDir root;
        const QString tz = root.path() + "/sys/devices/virtual/thermal/";
        write(tz + "thermal_zone0/type", "cpu-thermal\n");
        write(tz + "thermal_zone0/temp", "50000\n");
        write(tz + "thermal_zone1/type", "gpu-thermal\n");
        write(tz + "thermal_zone1/temp", "42500\n");
        write(tz + "thermal_zone2/type", "CPU-extra\n");
        write(tz + "thermal_zone2/temp", "60000\n");
        write(tz + "thermal_zone3/type", "cv0-thermal\n");   // 온도 파일 없음 → 건너뜀
        write(root.path() + "/sys/devices/platform/gpu.0/load", "345\n");   // ‰ → 34.5%
        write(root.path() + "/proc/meminfo",
              "MemTotal:        8000000 kB\nMemFree:          100000 kB\nMemAvailable:    2000000 kB\n");

        const QVariantMap s = SystemInfo::hwStats(root.path());
        QCOMPARE(s.value("cpu_temp").toDouble(), 55.0);
        QCOMPARE(s.value("gpu_temp").toDouble(), 42.5);
        QCOMPARE(s.value("gpu_load").toDouble(), 34.5);
        QCOMPARE(s.value("ram_percent").toDouble(), 75.0);
        QVERIFY(qAbs(s.value("ram_total_gb").toDouble() - 8000000.0 * 1024 / (1024.0 * 1024 * 1024)) < 1e-9);
        QVERIFY(qAbs(s.value("ram_used_gb").toDouble() - 6000000.0 * 1024 / (1024.0 * 1024 * 1024)) < 1e-9);

        QTemporaryDir empty;
        QVERIFY(SystemInfo::hwStats(empty.path()).isEmpty());   // 파일이 없으면 키도 없음
    }

    void realDeviceStats()
    {
        const QVariantMap s = SystemInfo::hwStats();
        if (QFile::exists("/proc/meminfo")) {
            QVERIFY(s.contains("ram_total_gb") && s.contains("ram_used_gb") && s.contains("ram_percent"));
            QVERIFY(s.value("ram_total_gb").toDouble() > 0.1);
        }
        if (QFile::exists("/sys/devices/platform/gpu.0/load"))
            QVERIFY(s.contains("gpu_load"));
        QDir thermal("/sys/devices/virtual/thermal");
        for (const QString &zone : thermal.entryList({"thermal_zone*"}, QDir::Dirs)) {
            QFile type(thermal.filePath(zone + "/type"));
            if (type.open(QIODevice::ReadOnly) && type.readAll().contains("cpu")) {
                QFile temp(thermal.filePath(zone + "/temp"));
                if (temp.open(QIODevice::ReadOnly) && !temp.readAll().isEmpty())
                    QVERIFY(s.contains("cpu_temp"));
            }
        }
    }

    void openFileLocationRejectsMissing()
    {
        QVERIFY(!SystemInfo::openFileLocation(QString()));
        QVERIFY(!SystemInfo::openFileLocation("/nonexistent-dir-jvp/also-missing/file.mkv"));
    }
};

QTEST_GUILESS_MAIN(TestSystemInfo)
#include "test_system_info.moc"
