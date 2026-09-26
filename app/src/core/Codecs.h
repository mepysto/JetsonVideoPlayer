#pragma once
// Jetson Orin NVDEC(nvv4l2decoder)가 디코딩할 수 있는 영상 형식 판별 (파이썬 media/codecs.py 이식).
// 재생 전에 판별해 두면, 하드웨어 디코더가 첫 프레임에서 실패한 뒤 소프트웨어로 다시 시작하는 끊김 없이
// 처음부터 알맞은 경로를 고를 수 있습니다.

#include <QString>

namespace jvp::codecs {

struct ChromaDepth {
    QString chroma;   // "420" / "422" / "444", 모르면 null QString
    int depth = 8;    // 비트 깊이
    bool operator==(const ChromaDepth &o) const { return chroma == o.chroma && depth == o.depth; }
};
// ffprobe pix_fmt 이름 → 샘플링과 비트 깊이
ChromaDepth chromaAndDepth(const QString &pixFmt);

// avc/avc1 → h264, h265/hvc1/hev1 → hevc, av01 → av1 (소문자)
QString canonicalCodec(const QString &codec);
// 코덱별 NVDEC 최대 비트 깊이 (미지원 코덱은 0)
int nvdecMaxBits(const QString &codec);

struct NvdecDecision {
    bool supported = false;
    QString reason;   // 사용자에게 보일 한국어 설명
};
// 형식 정보가 부족하면 코덱(과 프로파일 이름)만으로 판단합니다
NvdecDecision nvdecSupports(const QString &codec, const QString &pixFmt, const QString &profile = QString());

} // namespace jvp::codecs
