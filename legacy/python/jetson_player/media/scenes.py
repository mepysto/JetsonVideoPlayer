"""썸네일 시그니처(축소 이미지)로 장면 전환 지점을 찾습니다 (챕터가 없는 영상의 자동 챕터)."""
import numpy as np

SIGNATURE_SIZE = (16, 9)  # (가로, 세로) 블록 수


def image_signature(rgba, width, height):
    """RGBA 바이트 → 16x9 블록 평균 RGB (float32 배열, 길이 16*9*3)"""
    arr = np.frombuffer(rgba, dtype=np.uint8)[: width * height * 4].reshape(height, width, 4)[:, :, :3].astype(np.float32)
    bw, bh = SIGNATURE_SIZE
    ys = np.linspace(0, height, bh + 1, dtype=int)
    xs = np.linspace(0, width, bw + 1, dtype=int)
    blocks = np.empty((bh, bw, 3), dtype=np.float32)
    for j in range(bh):
        for i in range(bw):
            blocks[j, i] = arr[ys[j]:ys[j + 1], xs[i]:xs[i + 1]].mean(axis=(0, 1))
    return blocks.reshape(-1)


def detect_scene_changes(signatures, positions, duration, sensitivity=6.0, min_gap_ratio=0.03, max_scenes=30):
    """연속 시그니처 간 차이가 평소보다 크게 튀는 지점을 장면 전환으로 봅니다.

    signatures: 시간순 시그니처 목록, positions: 각 시그니처의 시각(ns), duration: 전체 길이(ns)
    반환: 장면 시작 시각 목록 (ns, 0 제외, 시간순)
    """
    if len(signatures) < 3 or duration <= 0:
        return []
    sig = np.stack([np.asarray(s, dtype=np.float32) for s in signatures])
    diffs = np.abs(np.diff(sig, axis=0)).mean(axis=1)          # 경계 i: positions[i] → positions[i+1]
    return scene_changes_from_diffs(diffs, positions[1:], duration, sensitivity,
                                    min_gap_ns=duration * min_gap_ratio, max_scenes=max_scenes)


def scene_changes_from_diffs(diffs, positions, duration, sensitivity=6.0, min_gap_ns=0, max_scenes=30):
    """프레임 간 차이값(diffs[i] = positions[i] 시점 직전 대비 변화량)에서 장면 전환 시각을 고릅니다."""
    diffs = np.asarray(diffs, dtype=np.float32)
    if len(diffs) < 2 or duration <= 0:
        return []
    # 장면 전환 값 자체가 평균/표준편차를 부풀리지 않도록 중앙값과 MAD(중앙값 절대 편차)로 기준을 잡습니다.
    median = float(np.median(diffs))
    mad = float(np.median(np.abs(diffs - median))) * 1.4826
    threshold = max(12.0, median + sensitivity * max(mad, 1.0))
    candidates = [i for i in np.argsort(-diffs) if diffs[i] >= threshold]

    chosen = []
    for i in candidates:
        pos = positions[i]
        if pos <= min_gap_ns or pos >= duration - min_gap_ns:
            continue
        if all(abs(pos - c) >= min_gap_ns for c in chosen):
            chosen.append(pos)
        if len(chosen) >= max_scenes:
            break
    return sorted(chosen)
