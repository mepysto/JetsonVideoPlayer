#pragma once
// HDR(PQ/HLG) → SDR 톤매핑의 CPU 참조 구현 — VideoItem.cpp 셰이더와 같은 계산을 테스트에서 검증하기 위한 것.
// (파이썬 jetson_player/media/hdr.py의 reference(), pq_to_nits, hlg_to_nits, tonemap 이식)

#include <array>

namespace jvp::hdr {

using Vec3 = std::array<double, 3>;
using Mat3 = std::array<Vec3, 3>;   // 행 우선

constexpr double kSdrWhiteNits = 203.0;   // BT.2408: HDR 안의 SDR 기준 백색
constexpr double kKnee = 0.75;            // 이 밝기(SDR 백색 대비)까지는 그대로, 위로는 부드럽게 1.0에 수렴
constexpr double kDisplayGamma = 2.2;
constexpr double kHlgPeakNits = 1000.0;

enum class Transfer { Pq, Hlg };

const Vec3 &luma2020();
const Mat3 &bt2020To709();
const Mat3 &matrixFix();                  // BT.709 행렬로 만든 RGB → BT.2020 행렬로 다시 만든 R'G'B'

Vec3 mul(const Mat3 &m, const Vec3 &v);
double pqToNits(double e);                // PQ 부호값(0~1) → nit
Vec3 pqToNits(const Vec3 &e);
Vec3 hlgToNits(const Vec3 &rgb);          // OOTF(시스템 감마 1.2) 포함
double tonemap(double x);                 // SDR 백색 대비 밝기 → 0~1
// 셰이더와 같은 과정: 입력/출력 모두 0~1 R'G'B'
Vec3 reference(const Vec3 &rgb, Transfer kind, bool fixMatrix);

} // namespace jvp::hdr
