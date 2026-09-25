"""음량 평준화: 영상의 통합 음량(ITU-R BS.1770 / EBU R128, LUFS)을 측정해 목표 음량에 맞출 이득을 계산합니다.

측정은 GStreamer로 오디오만 디코딩해(48kHz 스테레오 float) K-가중 필터(audioiirfilter)를 거친 뒤
numpy로 400ms 블록 게이팅을 계산합니다. 이 Jetson의 ffmpeg에는 AAC/AC3 디코더가 없어 GStreamer를 씁니다.
"""
import logging
import math
import os
import threading
import warnings

import numpy as np
from gi.repository import GObject, Gst

log = logging.getLogger(__name__)

RATE = 48000
TARGET_LUFS = -16.0
MAX_BOOST_DB = 12.0
MAX_CUT_DB = 12.0

# BS.1770 K-가중 필터 (48kHz): 고역 선반 필터 × 고역 통과 필터 — 두 2차 필터를 곱한 4차 필터로 한 번에 적용
_SHELF_B = (1.53512485958697, -2.69169618940638, 1.19839281085285)
_SHELF_A = (1.0, -1.69065929318241, 0.73248077421585)
_HPF_B = (1.0, -2.0, 1.0)
_HPF_A = (1.0, -1.99004745483398, 0.99007225036621)
K_WEIGHT_B = tuple(np.convolve(_SHELF_B, _HPF_B))
K_WEIGHT_A = tuple(np.convolve(_SHELF_A, _HPF_A))

BLOCK_SEC = 0.4          # 400ms 블록, 75% 겹침 → 100ms 단위로 합을 모아 둡니다
STEP = int(RATE * 0.1)
ABSOLUTE_GATE = -70.0
RELATIVE_GATE = -10.0


class LoudnessMeter:
    """K-가중된 스테레오 샘플을 받아 통합 음량(LUFS)을 계산합니다 (채널 가중치 L=R=1)."""

    def __init__(self):
        self._pending = np.zeros((0, 2), dtype=np.float64)
        self._steps = []   # 100ms마다 채널 합산 제곱합

    def feed(self, interleaved):
        frames = np.asarray(interleaved, dtype=np.float64).reshape(-1, 2)
        data = np.concatenate([self._pending, frames]) if len(self._pending) else frames
        n = len(data) // STEP
        if n:
            chunk = data[: n * STEP].reshape(n, STEP, 2)
            self._steps.extend((chunk ** 2).sum(axis=(1, 2)).tolist())
        self._pending = data[n * STEP:]

    def integrated(self):
        """통합 음량 (LUFS). 소리가 거의 없으면 None"""
        steps = np.asarray(self._steps)
        if len(steps) < 4:
            return None
        blocks = (steps[:-3] + steps[1:-2] + steps[2:-1] + steps[3:]) / (RATE * BLOCK_SEC)
        with np.errstate(divide="ignore"):
            loud = -0.691 + 10 * np.log10(blocks)
        gated = blocks[loud > ABSOLUTE_GATE]
        if not len(gated):
            return None
        relative = -0.691 + 10 * math.log10(gated.mean()) + RELATIVE_GATE
        final = gated[(-0.691 + 10 * np.log10(gated)) > relative]
        if not len(final):
            return None
        return -0.691 + 10 * math.log10(final.mean())


def gain_for(lufs, target=TARGET_LUFS):
    """목표 음량에 맞추는 이득 (dB, ±12dB 제한). 측정값이 없으면 0"""
    if lufs is None:
        return 0.0
    return max(-MAX_CUT_DB, min(MAX_BOOST_DB, target - lufs))


def db_to_linear(db):
    return 10 ** (db / 20.0)


def _value_array(values):
    """audioiirfilter의 계수 속성(GValueArray). PyGObject는 리스트를 바로 변환하지 못합니다."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        arr = GObject.ValueArray.new(len(values))
        for x in values:
            v = GObject.Value()
            v.init(GObject.TYPE_DOUBLE)
            v.set_double(float(x))
            arr.append(v)
    return arr


def build_meter_pipeline(uri):
    """영상 파일의 첫 오디오 → 48kHz 스테레오 float → K-가중 → appsink"""
    pipeline = Gst.Pipeline.new("loudness")
    src = Gst.ElementFactory.make("uridecodebin", None)
    src.set_property("uri", uri)
    src.set_property("caps", Gst.Caps.from_string("audio/x-raw"))
    conv = Gst.ElementFactory.make("audioconvert", None)
    resample = Gst.ElementFactory.make("audioresample", None)
    caps = Gst.ElementFactory.make("capsfilter", None)
    caps.set_property("caps", Gst.Caps.from_string(f"audio/x-raw,format=F32LE,layout=interleaved,rate={RATE},channels=2"))
    kweight = Gst.ElementFactory.make("audioiirfilter", None)
    kweight.set_property("b", _value_array(K_WEIGHT_B))
    kweight.set_property("a", _value_array(K_WEIGHT_A))
    sink = Gst.ElementFactory.make("appsink", None)
    sink.set_property("sync", False)
    sink.set_property("max-buffers", 32)
    for el in (src, conv, resample, caps, kweight, sink):
        pipeline.add(el)
    conv.link(resample)
    resample.link(caps)
    caps.link(kweight)
    kweight.link(sink)

    def on_pad(_src, pad):
        pad_caps = pad.get_current_caps() or pad.query_caps(None)
        if pad_caps and pad_caps.get_structure(0).get_name().startswith("audio/"):
            target = conv.get_static_pad("sink")
            if not target.is_linked():
                pad.link(target)

    src.connect("pad-added", on_pad)
    return pipeline, sink


def measure_file(path, cancelled=lambda: False, timeout_sec=900):
    """파일 전체의 통합 음량(LUFS). 오디오가 없거나 실패하면 None"""
    pipeline, sink = build_meter_pipeline(Gst.filename_to_uri(os.path.abspath(path)))
    meter = LoudnessMeter()
    bus = pipeline.get_bus()
    pipeline.set_state(Gst.State.PLAYING)
    result = None
    try:
        waited = 0.0
        while not cancelled():
            sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
            if sample is not None:
                buf = sample.get_buffer()
                ok, info = buf.map(Gst.MapFlags.READ)
                if ok:
                    meter.feed(np.frombuffer(info.data, dtype=np.float32).copy())
                    buf.unmap(info)
                continue
            msg = bus.pop_filtered(Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if msg is not None:
                if msg.type == Gst.MessageType.ERROR:
                    log.debug(f"음량 측정 실패 ({os.path.basename(path)}): {msg.parse_error()[0].message}")
                    return None
                result = meter.integrated()
                break
            if sink.get_property("eos"):
                result = meter.integrated()
                break
            waited += 0.2
            if waited > timeout_sec:
                break
    finally:
        pipeline.set_state(Gst.State.NULL)
    return result


class LoudnessJob:
    """백그라운드 음량 측정 (낮은 우선순위 스레드). on_done(lufs)는 작업 스레드에서 호출됩니다."""

    def __init__(self, path, on_done):
        self.path = path
        self.on_done = on_done
        self.cancelled = False
        self.thread = threading.Thread(target=self._run, daemon=True, name="loudness")

    def start(self):
        self.thread.start()
        return self

    def cancel(self):
        self.cancelled = True

    def _run(self):
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 15)   # 재생을 방해하지 않게
        except (AttributeError, OSError):
            pass
        lufs = measure_file(self.path, cancelled=lambda: self.cancelled)
        if not self.cancelled:
            self.on_done(lufs)
