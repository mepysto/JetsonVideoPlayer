#pragma once
// 재생 전에 파일을 살펴보는 도구: NVDEC 하드웨어 디코딩 가능 여부, 오디오 형식, HDMI 패스스루 가능 형식.
// filesrc ! parsebin 으로 스트림 caps만 읽습니다 (디코딩하지 않음 — NVDEC 미지원 형식에서도 동작).

#include <QSet>
#include <QString>
#include <optional>

namespace jvp::probe {

struct VideoCodecInfo {
    QString codec;     // ffprobe 식 이름 (hevc, h264, vp9, av1 ...)
    QString pixFmt;    // yuv420p, yuv420p10le ...
    QString profile;
};

// 첫 비디오 스트림 정보 (영상 스트림이 없으면 codec이 빈 문자열, 읽지 못하면 nullopt)
std::optional<VideoCodecInfo> videoCodec(const QString &path, int timeoutSec = 3);

// NVDEC로 디코딩할 수 있는지 (결과는 hwCache에 저장). 판별할 수 없으면 nullopt → 하드웨어부터 시도
struct HwSupport {
    std::optional<bool> supported;
    QString reason;
};
HwSupport checkHwSupport(const QString &path);

// 첫 오디오 스트림의 형식 (예: "audio/x-ac3"), 없거나 모르면 빈 문자열
QString audioCodec(const QString &path, int timeoutSec = 3);

// 원음 그대로 보낼 수 있는 압축 형식 (사운드 서버의 HDMI 패스스루 설정이 켜져 있을 때만 나타남)
const QSet<QString> &passthroughCaps();   // audio/x-ac3, audio/x-eac3, audio/x-dts
QSet<QString> sinkPassthroughFormats(const char *factory = "pulsesink");

} // namespace jvp::probe
