"""음량 측정: BS.1770 기준 신호로 필터 부호·게이팅을 검증합니다."""
import math

import gi
import numpy as np
import pytest

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from jetson_player.media.loudness import (RATE, LoudnessMeter, db_to_linear, gain_for, measure_file)  # noqa: E402


def sine(amplitude, seconds=5.0, freq=997.0):
    t = np.arange(int(RATE * seconds)) / RATE
    mono = (amplitude * np.sin(2 * math.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1).ravel()


def test_gain_limits():
    assert gain_for(-23.0) == pytest.approx(7.0)
    assert gain_for(-40.0) == 12.0 and gain_for(5.0) == -12.0 and gain_for(None) == 0.0
    assert db_to_linear(-6.0206) == pytest.approx(0.5, abs=1e-4)


def test_silence_has_no_loudness():
    m = LoudnessMeter()
    m.feed(np.zeros(RATE * 4, dtype=np.float32))
    assert m.integrated() is None


def test_meter_gates_quiet_parts():
    """앞 절반 -20dBFS 사인, 뒤 절반 무음 → 무음은 게이트로 빠져 -20 부근 (필터 전 기준 근사)"""
    m = LoudnessMeter()
    m.feed(np.concatenate([sine(0.1, 3.0), np.zeros(RATE * 3 * 2, dtype=np.float32)]))
    assert m.integrated() == pytest.approx(-0.691 + 10 * math.log10(2 * 0.1 ** 2 / 2), abs=0.3)


@pytest.fixture
def tone_file(tmp_path):
    Gst.init(None)
    if not all(Gst.ElementFactory.find(n) for n in ("audiotestsrc", "wavenc", "audioiirfilter")):
        pytest.skip("GStreamer 요소 없음")
    path = tmp_path / "tone.wav"
    p = Gst.parse_launch(f"audiotestsrc wave=sine freq=997 volume=0.5 num-buffers=240 samplesperbuffer=1000 "
                         f"! audio/x-raw,rate=48000,channels=2,format=S16LE ! wavenc ! filesink location={path}")
    p.set_state(Gst.State.PLAYING)
    p.get_bus().timed_pop_filtered(20 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    p.set_state(Gst.State.NULL)
    return path


def test_measure_file_matches_bs1770_reference(tone_file):
    """997Hz 사인 두 채널 진폭 0.5 → BS.1770: 0 LUFS(진폭 1) - 6.02dB ≈ -6.0 LUFS"""
    lufs = measure_file(str(tone_file))
    assert lufs == pytest.approx(-6.02, abs=0.3)
