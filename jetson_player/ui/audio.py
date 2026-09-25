"""오디오 효과: 음량 평준화(영상마다 다른 음량 맞추기)와 EQ 프리셋"""
import logging
import os

from gi.repository import GLib, Gst

from ..media.loudness import LoudnessJob, db_to_linear, gain_for
from ..settings import settings
from ..storage import loudness_cache

log = logging.getLogger(__name__)

# equalizer-10bands 대역: 29, 59, 119, 237, 474, 947, 1889, 3770, 7523, 15011 Hz (dB)
EQ_PRESETS = {
    "flat": ("기본", [0] * 10),
    "dialogue": ("대사 강조", [-6, -5, -3, -1, 1, 3, 4, 3, 0, -2]),
    "bass": ("저음 강화", [6, 5, 4, 2, 0, 0, 0, 0, 0, 0]),
    "treble": ("고음 강화", [0, 0, 0, 0, 0, 1, 2, 4, 5, 6]),
    "quiet": ("작은 볼륨 청취", [-8, -6, -3, 0, 1, 2, 2, 1, 0, -2]),
}
RAMP_STEPS = 10
RAMP_MS = 100


class AudioEffectsMixin:
    def build_audio_effect_elements(self):
        """오디오 bin에 넣을 효과 요소 목록 (EQ → 야간 모드 → 음량 평준화 → 리미터). 없는 요소는 빠집니다."""
        eq = Gst.ElementFactory.make("equalizer-10bands", "eq")
        night_dyn, night_gain = self.build_night_mode_elements()
        loud = Gst.ElementFactory.make("volume", "loudness_gain")
        limiter = Gst.ElementFactory.make("rglimiter", "limiter")   # 이득을 올려도 찢어지는 소리 방지
        self.eq_element, self.loudness_element = eq, loud
        # 같은 영상에서 파이프라인만 다시 만든 경우(HW 경로 실패 등)에도 맞춰 둔 이득을 유지합니다.
        target = getattr(self, "_loudness_target_db", 0.0)
        self._loudness_current_db = target
        if loud is not None:
            loud.set_property("volume", db_to_linear(target))
        self._apply_eq_preset()
        return [eq, night_dyn, night_gain, loud, limiter]

    # ---- EQ ------------------------------------------------------------------
    def _apply_eq_preset(self):
        eq = getattr(self, "eq_element", None)
        if eq is None:
            return
        _name, gains = EQ_PRESETS.get(settings.get("eq_preset"), EQ_PRESETS["flat"])
        for i, g in enumerate(gains):
            eq.set_property(f"band{i}", float(g))

    def set_eq_preset(self, key):
        if key not in EQ_PRESETS:
            return
        settings.set("eq_preset", key)
        self._apply_eq_preset()
        self.show_osd(f"🎚️ EQ: {EQ_PRESETS[key][0]}")

    # ---- 음량 평준화 -------------------------------------------------------------
    def start_loudness_for(self, path):
        """재생을 시작한 영상의 음량을 (측정해 둔 값이 없으면 백그라운드에서 측정해) 맞춥니다."""
        job = getattr(self, "loudness_job", None)
        if job:
            job.cancel()
        self.loudness_job = None
        self._loudness_path = path
        self._loudness_lufs = None
        self._set_loudness_gain(0.0, ramp=False)
        if not settings.get("loudness_normalize") or not path or path.startswith(("http://", "https://")) \
                or not os.path.isfile(path):
            return
        known, lufs = loudness_cache.lookup(path)
        if known:
            self._apply_measured_loudness(path, lufs)
            return

        def done(value):
            loudness_cache.store(path, value)
            GLib.idle_add(lambda: (self._apply_measured_loudness(path, value), False)[1])

        self.loudness_job = LoudnessJob(path, done).start()

    def _apply_measured_loudness(self, path, lufs):
        if path != getattr(self, "_loudness_path", None) or not settings.get("loudness_normalize"):
            return
        gain = gain_for(lufs)
        self._loudness_lufs = lufs
        log.info(f"🔊 [음량 평준화] {os.path.basename(path)}: "
                 f"{'오디오 없음' if lufs is None else f'{lufs:.1f} LUFS → {gain:+.1f} dB'}")
        self._set_loudness_gain(gain, ramp=True)

    def _set_loudness_gain(self, target_db, ramp=True):
        """이득을 바꿉니다. ramp: 1초에 걸쳐 서서히 (갑자기 커지거나 작아지지 않게)"""
        self._loudness_target_db = target_db
        el = getattr(self, "loudness_element", None)
        timer = getattr(self, "_loudness_ramp_id", None)
        if timer:
            GLib.source_remove(timer)
            self._loudness_ramp_id = None
        if el is None:
            return
        start_db = getattr(self, "_loudness_current_db", 0.0)
        if not ramp or abs(target_db - start_db) < 0.05:
            self._loudness_current_db = target_db
            el.set_property("volume", db_to_linear(target_db))
            return
        steps = iter(range(1, RAMP_STEPS + 1))

        def tick():
            n = next(steps, None)
            if n is None or getattr(self, "loudness_element", None) is not el:
                self._loudness_ramp_id = None
                return False
            db = start_db + (target_db - start_db) * n / RAMP_STEPS
            self._loudness_current_db = db
            el.set_property("volume", db_to_linear(db))
            return True

        self._loudness_ramp_id = GLib.timeout_add(RAMP_MS, tick)

    def toggle_loudness_normalize(self):
        on = not settings.get("loudness_normalize")
        settings.set("loudness_normalize", on)
        if on:
            self.start_loudness_for(self.playlist[self.current_index] if self.playlist else None)
        else:
            self._set_loudness_gain(0.0)
        self.show_osd("🔊 음량 평준화 ON" if on else "🔊 음량 평준화 OFF")

    def audio_setting_entries(self):
        lufs = getattr(self, "_loudness_lufs", None)
        detail = f" — {lufs:.0f} LUFS → {getattr(self, '_loudness_current_db', 0.0):+.0f}dB" \
            if settings.get("loudness_normalize") and lufs is not None else ""
        preset = settings.get("eq_preset")
        return [
            ("check", f"🔊 음량 평준화 (영상마다 음량 맞추기){detail}", settings.get("loudness_normalize"),
             self.toggle_loudness_normalize),
            ("submenu", f"🎚️ EQ: {EQ_PRESETS.get(preset, EQ_PRESETS['flat'])[0]}",
             [(name, (lambda k=k: self.set_eq_preset(k)), k == preset) for k, (name, _g) in EQ_PRESETS.items()]),
        ]
