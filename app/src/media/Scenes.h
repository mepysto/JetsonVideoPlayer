#pragma once
// 썸네일 시그니처(축소 이미지)로 장면 전환 지점을 찾습니다 (챕터가 없는 영상의 자동 챕터).
// (파이썬 jetson_player/media/scenes.py 이식)

#include <QList>
#include <QtGlobal>

#include <vector>

namespace jvp::scenes {

constexpr int kSignatureW = 16, kSignatureH = 9;   // 블록 수
constexpr int kSignatureLen = kSignatureW * kSignatureH * 3;

using Signature = std::vector<float>;   // 16×9 블록 평균 RGB (길이 432)

// RGBA 바이트(행 간격 = width*4) → 16x9 블록 평균 RGB
Signature imageSignature(const uchar *rgba, int width, int height);

// 연속 시그니처 간 차이가 평소보다 크게 튀는 지점을 장면 전환으로 봅니다.
// positions: 각 시그니처의 시각(ns), duration: 전체 길이(ns). 반환: 장면 시작 시각(ns, 0 제외, 시간순)
QList<qint64> detectSceneChanges(const std::vector<Signature> &signatures, const QList<qint64> &positions,
                                 qint64 duration, double sensitivity = 6.0, double minGapRatio = 0.03,
                                 int maxScenes = 30);

// 프레임 간 차이값(diffs[i] = positions[i] 시점 직전 대비 변화량)에서 장면 전환 시각을 고릅니다.
QList<qint64> sceneChangesFromDiffs(const std::vector<float> &diffs, const QList<qint64> &positions, qint64 duration,
                                    double sensitivity = 6.0, double minGapNs = 0, int maxScenes = 30);

} // namespace jvp::scenes
