#pragma once
// 파일 관리자 연동, Jetson 하드웨어 상태, 네트워크 주소 등 시스템 유틸리티

#include <QString>
#include <QVariantMap>

namespace jvp {

class SystemInfo {
public:
    // 파일이 있는 폴더를 기본 파일 관리자로 열고 그 파일을 선택합니다.
    // 1) D-Bus org.freedesktop.FileManager1.ShowItems  2) xdg-open 폴더  3) gio open 폴더
    static bool openFileLocation(const QString &filePath);

    // Jetson 상태. 읽을 수 있는 값만 들어 있습니다 (키: cpu_temp, gpu_temp (°C), gpu_load (%),
    // ram_used_gb, ram_total_gb, ram_percent). sysRoot는 테스트용 가짜 루트 (기본 "/").
    static QVariantMap hwStats(const QString &sysRoot = QString());

    // 스마트폰 접속용 LAN IPv4 주소 (못 찾으면 "127.0.0.1")
    static QString localIp();
};

} // namespace jvp
