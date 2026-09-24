import numpy as np

from jetson_player.media.scenes import detect_scene_changes, image_signature

S = 1_000_000_000


def _scene_sigs(levels, per_scene=10, noise=2.0, seed=0):
    rng = np.random.default_rng(seed)
    sigs = []
    for level in levels:
        for _ in range(per_scene):
            sigs.append(np.full(16 * 9 * 3, level, dtype=np.float32) + rng.normal(0, noise, 16 * 9 * 3))
    return sigs


def test_detects_hard_cuts():
    sigs = _scene_sigs([30, 200, 90, 160])
    positions = [i * 10 * S for i in range(len(sigs))]
    scenes = detect_scene_changes(sigs, positions, duration=len(sigs) * 10 * S)
    assert scenes == [100 * S, 200 * S, 300 * S]


def test_no_cuts_in_static_video():
    sigs = _scene_sigs([100], per_scene=40)
    assert detect_scene_changes(sigs, [i * S for i in range(40)], duration=40 * S) == []


def test_min_gap_and_short_input():
    assert detect_scene_changes([np.zeros(432)] * 2, [0, S], duration=2 * S) == []
    # 2초와 3초의 전환은 최소 간격(1.2초)보다 가까우므로 하나만 남깁니다.
    sigs = _scene_sigs([30], per_scene=2) + _scene_sigs([200], per_scene=1) + _scene_sigs([30], per_scene=3)
    scenes = detect_scene_changes(sigs, [i * S for i in range(6)], duration=6 * S, min_gap_ratio=0.2)
    assert len(scenes) == 1 and scenes[0] in (2 * S, 3 * S)


def test_image_signature_shape_and_values():
    w, h = 32, 18
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, : w // 2, 0] = 255          # 왼쪽 절반 빨강
    sig = image_signature(rgba.tobytes(), w, h).reshape(9, 16, 3)
    assert sig.shape == (9, 16, 3)
    assert sig[0, 0, 0] == 255 and sig[0, 15, 0] == 0
