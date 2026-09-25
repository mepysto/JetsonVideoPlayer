"""시청 경험: 화면 회전, 야간 모드(음량 평준화), 수면 타이머, 다음 영상 자동 재생 카운트다운"""
import logging
import os
import time

from gi.repository import GLib, Gst, Gtk

from ..settings import settings

log = logging.getLogger(__name__)

# (gtkglsink rotate-method 값, 표시 이름)
ROTATIONS = [
    ("identity", "원래대로"),
    ("90r", "시계 방향 90°"),
    ("180", "180°"),
    ("90l", "반시계 방향 90°"),
    ("horiz", "좌우 반전"),
    ("vert", "상하 반전"),
]
SLEEP_CHOICES = [(0, "끄기"), (15, "15분 후"), (30, "30분 후"), (60, "60분 후"), (-1, "현재 영상이 끝나면")]
SLEEP_FADE_SEC = 20
AUTOPLAY_COUNTDOWN_SEC = 5

# 야간 모드: 큰 소리는 압축하고(ratio), 전체를 끌어올려(makeup gain) 작은 대사를 잘 들리게 합니다.
NIGHT_THRESHOLD = 0.12
NIGHT_RATIO = 0.25
NIGHT_GAIN = 2.2


class ViewingMixin:
    # ---- 화면 회전 --------------------------------------------------------
    def set_video_rotation(self, method):
        self.video_rotation = method
        sink = getattr(self, "gtk_sink", None)
        if sink is not None and sink.find_property("rotate-method"):
            sink.set_property("rotate-method", method)
        name = dict(ROTATIONS).get(method, method)
        self.show_osd(f"🔄 화면 회전: {name}")
        self._update_overlay_video_size()

    def cycle_video_rotation(self):
        methods = [m for m, _ in ROTATIONS]
        cur = getattr(self, "video_rotation", "identity")
        self.set_video_rotation(methods[(methods.index(cur) + 1) % len(methods)] if cur in methods else "90r")

    def is_rotated_quarter(self):
        return getattr(self, "video_rotation", "identity") in ("90r", "90l")

    # ---- 야간 모드 ----------------------------------------------------------
    def build_night_mode_elements(self):
        """오디오 bin에 넣을 (압축기, 보정 볼륨) 요소를 만듭니다. 꺼져 있으면 효과 없음 설정."""
        dyn = Gst.ElementFactory.make("audiodynamic", "night_dynamic")
        gain = Gst.ElementFactory.make("volume", "night_gain")
        if not dyn or not gain:
            return None, None
        dyn.set_property("characteristics", "soft-knee")
        dyn.set_property("mode", "compressor")
        self.night_elements = (dyn, gain)
        self._apply_night_mode()
        return dyn, gain

    def _apply_night_mode(self):
        dyn, gain = getattr(self, "night_elements", (None, None))
        if not dyn:
            return
        on = settings.get("night_mode")
        dyn.set_property("threshold", NIGHT_THRESHOLD if on else 1.0)
        dyn.set_property("ratio", NIGHT_RATIO if on else 1.0)
        gain.set_property("volume", NIGHT_GAIN if on else 1.0)

    def toggle_night_mode(self):
        settings.set("night_mode", not settings.get("night_mode"))
        self._apply_night_mode()
        self.show_osd("🌙 야간 모드 ON — 큰 소리는 줄이고 대사는 키웁니다" if settings.get("night_mode") else "🌙 야간 모드 OFF")

    # ---- 수면 타이머 --------------------------------------------------------
    def set_sleep_timer(self, minutes):
        """minutes: 0=끄기, -1=현재 영상이 끝나면, 그 외 분 단위"""
        self._cancel_sleep_fade()
        self.sleep_minutes = minutes
        self.sleep_deadline = time.monotonic() + minutes * 60 if minutes > 0 else None
        if getattr(self, "sleep_timer_id", None) is None and minutes > 0:
            self.sleep_timer_id = GLib.timeout_add_seconds(1, self._on_sleep_tick)
        label = dict(SLEEP_CHOICES).get(minutes, f"{minutes}분 후")
        self.show_osd("⏾ 수면 타이머 끔" if minutes == 0 else f"⏾ 수면 타이머: {label} 정지")

    def cycle_sleep_timer(self):
        order = [m for m, _ in SLEEP_CHOICES]
        cur = getattr(self, "sleep_minutes", 0)
        self.set_sleep_timer(order[(order.index(cur) + 1) % len(order)] if cur in order else 0)

    def sleep_remaining_sec(self):
        deadline = getattr(self, "sleep_deadline", None)
        return max(0, int(deadline - time.monotonic())) if deadline else None

    def _on_sleep_tick(self):
        remaining = self.sleep_remaining_sec()
        if remaining is None:
            self.sleep_timer_id = None
            return False
        if remaining in (60, 30):
            self.show_osd(f"⏾ {remaining}초 후 재생을 멈춥니다 (H: 타이머 변경)", duration_sec=3.0)
        if remaining <= SLEEP_FADE_SEC and not getattr(self, "sleep_fading", False):
            self._start_sleep_fade()
        if remaining <= 0:
            self.sleep_timer_id = None
            self._sleep_now()
            return False
        return True

    def _start_sleep_fade(self):
        """남은 시간 동안 볼륨을 서서히 줄입니다 (설정된 볼륨 값은 바꾸지 않음)."""
        self.sleep_fading = True
        self.sleep_fade_base = self.volume_scale.get_value() / 100.0

    def _cancel_sleep_fade(self):
        if getattr(self, "sleep_fading", False):
            self.sleep_fading = False
            if self.pipeline and not self.is_muted:
                self.pipeline.set_property("volume", self.volume_scale.get_value() / 100.0)

    def apply_sleep_fade(self):
        """[update_playback_ui에서 호출] 페이드 중이면 파이프라인 볼륨을 남은 시간 비율로 낮춥니다."""
        if not getattr(self, "sleep_fading", False) or not self.pipeline or self.is_muted:
            return
        remaining = self.sleep_remaining_sec()
        if remaining is None:
            return
        self.pipeline.set_property("volume", self.sleep_fade_base * max(0.0, remaining / SLEEP_FADE_SEC))

    def _sleep_now(self):
        self.sleep_minutes = 0
        self.sleep_deadline = None
        if self.is_playing:
            self.toggle_play_pause()
        self._cancel_sleep_fade()
        self.show_osd("⏾ 수면 타이머: 재생을 멈췄습니다. 편안한 밤 되세요.", duration_sec=5.0)
        log.info("⏾ [수면 타이머] 재생 정지")

    def sleep_after_this_video(self):
        """EOS 시 호출: '현재 영상이 끝나면' 모드면 다음 영상으로 넘어가지 않고 멈춥니다."""
        if getattr(self, "sleep_minutes", 0) == -1:
            self.sleep_minutes = 0
            self._sleep_now()
            return True
        return False

    # ---- 다음 영상 자동 재생 카운트다운 ----------------------------------------
    def build_autoplay_overlay(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.get_style_context().add_class("autoplay-card")
        box.set_halign(Gtk.Align.END)
        box.set_valign(Gtk.Align.END)
        box.set_margin_end(24)
        box.set_margin_bottom(24)
        self.autoplay_title = Gtk.Label(xalign=0)
        self.autoplay_title.set_ellipsize(3)
        self.autoplay_title.set_max_width_chars(36)
        self.autoplay_title.get_style_context().add_class("autoplay-title")
        self.autoplay_status = Gtk.Label(xalign=0)
        self.autoplay_status.get_style_context().add_class("muted")
        self.autoplay_bar = Gtk.ProgressBar()
        self.autoplay_bar.get_style_context().add_class("resume-progress")
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        now_btn = Gtk.Button(label="▶ 지금 재생")
        now_btn.get_style_context().add_class("primary")
        now_btn.connect("clicked", lambda _b: self._finish_autoplay(run=True))
        cancel_btn = Gtk.Button(label="취소")
        cancel_btn.connect("clicked", lambda _b: self._finish_autoplay(run=False))
        buttons.pack_start(now_btn, False, False, 0)
        buttons.pack_start(cancel_btn, False, False, 0)
        for w in (self.autoplay_title, self.autoplay_status, self.autoplay_bar, buttons):
            box.pack_start(w, False, False, 0)
        box.set_no_show_all(True)
        self.autoplay_box = box
        return box

    def start_autoplay_countdown(self, next_path, action):
        """다음 영상 안내 카드를 띄우고 AUTOPLAY_COUNTDOWN_SEC초 후 action()을 실행합니다."""
        if not settings.get("autoplay_countdown") or not getattr(self, "autoplay_box", None):
            action()
            return
        self._cancel_autoplay_timer()
        self.autoplay_action = action
        self.autoplay_started = time.monotonic()
        self.autoplay_title.set_text(f"다음: {os.path.basename(next_path)}")
        self.autoplay_box.set_no_show_all(False)
        self.autoplay_box.show_all()
        self.autoplay_box.set_no_show_all(True)
        self._update_autoplay()
        self.autoplay_timer_id = GLib.timeout_add(100, self._update_autoplay)

    def _update_autoplay(self):
        elapsed = time.monotonic() - getattr(self, "autoplay_started", 0)
        left = max(0.0, AUTOPLAY_COUNTDOWN_SEC - elapsed)
        self.autoplay_status.set_text(f"{left:.0f}초 후 자동 재생")
        self.autoplay_bar.set_fraction(min(1.0, elapsed / AUTOPLAY_COUNTDOWN_SEC))
        if left <= 0:
            self.autoplay_timer_id = None
            self._finish_autoplay(run=True)
            return False
        return True

    def _cancel_autoplay_timer(self):
        if getattr(self, "autoplay_timer_id", None):
            GLib.source_remove(self.autoplay_timer_id)
            self.autoplay_timer_id = None

    def _finish_autoplay(self, run):
        self._cancel_autoplay_timer()
        if getattr(self, "autoplay_box", None):
            self.autoplay_box.hide()
        action, self.autoplay_action = getattr(self, "autoplay_action", None), None
        if run and action:
            action()
        elif not run:
            self.show_osd("⏹ 자동 재생을 취소했습니다.")

    def cancel_autoplay_countdown(self):
        """사용자가 직접 다른 조작(다음/이전/목록 선택)을 하면 카운트다운을 조용히 닫습니다."""
        if getattr(self, "autoplay_action", None):
            self._cancel_autoplay_timer()
            self.autoplay_action = None
            if getattr(self, "autoplay_box", None):
                self.autoplay_box.hide()

    # ---- ⋯ 메뉴 항목 ------------------------------------------------------
    def viewing_setting_entries(self):
        rot = getattr(self, "video_rotation", "identity")
        sleep = getattr(self, "sleep_minutes", 0)
        remaining = self.sleep_remaining_sec()
        sleep_label = "⏾ 수면 타이머 (H)" + (f" — {remaining // 60}분 {remaining % 60}초 남음" if remaining else
                                            (" — 영상 끝나면" if sleep == -1 else ""))
        return [
            ("check", "🌙 야간 모드: 대사 크게·폭음 작게 (E)", settings.get("night_mode"), self.toggle_night_mode),
            ("submenu", sleep_label, [(label, (lambda m=m: self.set_sleep_timer(m)), m == sleep) for m, label in SLEEP_CHOICES]),
            ("submenu", "🔄 화면 회전 (V)", [(label, (lambda m=m: self.set_video_rotation(m)), m == rot) for m, label in ROTATIONS]),
            ("check", "⏭ 다음 영상 5초 카운트다운", settings.get("autoplay_countdown"),
             lambda: settings.set("autoplay_countdown", not settings.get("autoplay_countdown"))),
        ]
