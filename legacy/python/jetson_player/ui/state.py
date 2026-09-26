"""재생/음소거/볼륨 상태를 한곳에서 관리하고, 일반 컨트롤과 전체화면 컨트롤을 함께 갱신합니다.

self.is_playing / self.is_muted 에 값을 넣기만 하면 두 컨트롤의 버튼 표시가 자동으로 맞춰집니다.
볼륨은 어느 슬라이더(일반/전체화면)를 움직이든 _on_volume_scale_changed 하나에서 처리합니다.
"""
PLAY_LABELS = {True: "Ⅱ", False: "▶"}
MUTE_LABELS = {True: "🔇", False: "◖)))"}


class ControlStateMixin:
    # ---- 재생 상태 ---------------------------------------------------------
    @property
    def is_playing(self):
        return getattr(self, "_is_playing", False)

    @is_playing.setter
    def is_playing(self, value):
        self._is_playing = bool(value)
        for btn in (getattr(self, "play_button", None), getattr(self, "fs_play_button", None)):
            if btn is not None:
                btn.set_label(PLAY_LABELS[self._is_playing])

    # ---- 음소거 ------------------------------------------------------------
    @property
    def is_muted(self):
        return getattr(self, "_is_muted", False)

    @is_muted.setter
    def is_muted(self, value):
        self._is_muted = bool(value)
        for btn in (getattr(self, "mute_btn", None), getattr(self, "fs_mute_btn", None)):
            if btn is not None:
                btn.set_label(MUTE_LABELS[self._is_muted])

    def toggle_mute(self):
        """음소거 상태를 토글합니다 (해제 시 음소거 전 볼륨으로 복원)."""
        if not self.is_muted:
            self.pre_mute_volume = self.volume_scale.get_value()
            self.is_muted = True
            self.volume_scale.set_value(0)
            self.show_osd("🔇 음소거")
        else:
            self.is_muted = False
            restore = self.pre_mute_volume if self.pre_mute_volume > 0 else 50
            if abs(self.volume_scale.get_value() - restore) < 0.5:
                self._on_volume_scale_changed(self.volume_scale)
            else:
                self.volume_scale.set_value(restore)

    # ---- 볼륨 --------------------------------------------------------------
    def set_volume(self, val):
        """볼륨(0~200%)을 설정합니다. 슬라이더 변경 핸들러가 파이프라인·표시를 처리합니다."""
        val = max(0, min(200, val))
        if abs(self.volume_scale.get_value() - val) < 0.5:
            self._on_volume_scale_changed(self.volume_scale)
        else:
            self.volume_scale.set_value(val)

    def _on_volume_scale_changed(self, scale):
        """[일반/전체화면 볼륨 슬라이더 공용] 다른 슬라이더 동기화, 음소거 해제, 파이프라인 반영, OSD"""
        if getattr(self, "_syncing_volume", False):
            return
        val = scale.get_value()
        self._syncing_volume = True
        try:
            for other in (getattr(self, "volume_scale", None), getattr(self, "fs_volume_scale", None)):
                if other is not None and other is not scale and abs(other.get_value() - val) > 0.5:
                    other.set_value(val)
        finally:
            self._syncing_volume = False
        if self.is_muted and val > 0:
            self.is_muted = False
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)
        if not self.is_muted:
            self.show_osd(f"🔊 볼륨: {int(val)}%" + (" (부스트)" if val > 100 else ""))
