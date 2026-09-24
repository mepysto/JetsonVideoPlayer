"""하단/전체화면 컨트롤, OSD, 진행바, 커서, 전체화면 전환"""

from gi.repository import GLib, Gdk, Gst, Gtk

from ..storage import resume_cache


class ControlsMixin:
    def show_osd(self, text, timeout_ms=1200, duration_sec=None):
        """화면 상단 중앙에 설정 변경 상태(속도, 탐색 등)를 알려주는 OSD 박스를 표시합니다."""
        if duration_sec is not None:
            try:
                timeout_ms = max(400, int(float(duration_sec) * 1000))
            except Exception:
                pass
        if not getattr(self, "osd_box", None) or not getattr(self, "osd_label", None):
            return
        if getattr(self, "_restoring_settings", False):
            return
        self.osd_label.set_text(text)
        self.osd_box.show_all()
        if getattr(self, "osd_timer_id", None):
            try:
                GLib.source_remove(self.osd_timer_id)
            except Exception:
                pass
        self.osd_timer_id = GLib.timeout_add(timeout_ms, self._hide_osd)

    def _hide_osd(self):
        if getattr(self, "osd_box", None):
            self.osd_box.hide()
        self.osd_timer_id = None
        return False

    def update_speed_button_ui(self):
        """재생 속도 버튼 텍스트를 현재 배속에 맞게 갱신합니다."""
        rate_str = f"{self.playback_rate:.2f}x" if (self.playback_rate * 10) % 1 != 0 else f"{self.playback_rate:.1f}x"
        if rate_str.endswith(".0x") and self.playback_rate == 1.0:
            rate_str = "1.0x"
        if getattr(self, "speed_button", None):
            self.speed_button.set_label(f"⚡ {rate_str}")
        if getattr(self, "fs_speed_button", None):
            self.fs_speed_button.set_label(f"⚡ {rate_str}")

    def build_speed_popover(self, parent_btn):
        """재생 속도 선택 팝오버 메뉴를 구성합니다."""
        if getattr(self, "speed_popover", None):
            try:
                self.speed_popover.destroy()
            except Exception:
                pass
            self.speed_popover = None

        self.speed_popover = Gtk.Popover(relative_to=parent_btn)
        self.speed_popover.set_position(Gtk.PositionType.TOP)
        self.speed_popover.set_border_width(12)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        title = Gtk.Label(label="⚡ 재생 속도 조절", xalign=0)
        title.get_style_context().add_class("popover-title")
        container.pack_start(title, False, False, 2)

        # 프리셋 속도 버튼 목록
        presets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        presets_box.get_style_context().add_class("sub-btn-row")
        for spd in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
            btn = Gtk.Button(label=f"{spd}x")
            if abs(self.playback_rate - spd) < 0.01:
                btn.get_style_context().add_class("primary")
            btn.connect("clicked", lambda _b, s=spd: (self.set_playback_rate(s), self.speed_popover.popdown()))
            presets_box.pack_start(btn, True, True, 0)
        container.pack_start(presets_box, False, False, 2)

        # 미세 조절 바
        step_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        step_box.get_style_context().add_class("sub-btn-row")

        dec_btn = Gtk.Button(label="˗ 느리게 (-0.25x)")
        dec_btn.connect("clicked", lambda _b: self.step_playback_rate(-0.25))
        step_box.pack_start(dec_btn, True, True, 0)

        reset_btn = Gtk.Button(label="1.0x (기본)")
        reset_btn.connect("clicked", lambda _b: (self.reset_playback_rate(), self.speed_popover.popdown()))
        step_box.pack_start(reset_btn, True, True, 0)

        inc_btn = Gtk.Button(label="˖ 빠르게 (+0.25x)")
        inc_btn.connect("clicked", lambda _b: self.step_playback_rate(0.25))
        step_box.pack_start(inc_btn, True, True, 0)

        container.pack_start(step_box, False, False, 2)

        hint = Gtk.Label(label="단축키: Up/Down 또는 d/a (속도 조절), r (1.0x 복원)", xalign=0)
        hint.get_style_context().add_class("muted")
        container.pack_start(hint, False, False, 2)

        container.show_all()
        self.speed_popover.add(container)

        def on_pop_closed(_pop):
            self.is_popover_open = False
        self.speed_popover.connect("closed", on_pop_closed)

    def on_speed_button_clicked(self, widget):
        self.build_speed_popover(widget)
        self.is_popover_open = True

    def on_video_scroll_event(self, widget, event):
        """
        비디오 화면 영역 내에서만 마우스 휠 스크롤 시 10초 앞/뒤로 Seek 이동합니다.
        플레이리스트 사이드바나 컨트롤바 등의 스크롤과 완전히 물리적으로 격리됩니다.
        """
        if getattr(self, "is_mouse_over_fs_controls", False) or getattr(self, "is_popover_open", False):
            return False

        if event.direction == Gdk.ScrollDirection.UP:
            self.seek_relative(10)
            return True
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.seek_relative(-10)
            return True
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            if event.delta_y < -0.1:
                self.seek_relative(10)
                return True
            elif event.delta_y > 0.1:
                self.seek_relative(-10)
                return True
        return False

    def on_video_button_press(self, widget, event):
        """
        비디오 화면 영역 클릭 처리:
        - 좌클릭 싱글: 재생 / 일시정지 (250ms 디바운스로 더블클릭과 분리)
        - 좌클릭 더블: 영상 전체화면 전환 토글
        - 우클릭: 빠른 조작 컨텍스트 메뉴 표시
        """
        if getattr(self, "is_mouse_over_fs_controls", False) or getattr(self, "is_popover_open", False):
            return False

        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            if self.click_timer_id is not None:
                try:
                    GLib.source_remove(self.click_timer_id)
                except Exception:
                    pass
                self.click_timer_id = None
            self.toggle_fullscreen()
            return True

        elif event.type == Gdk.EventType.BUTTON_PRESS:
            if event.button == 1:
                if self.click_timer_id is not None:
                    try:
                        GLib.source_remove(self.click_timer_id)
                    except Exception:
                        pass
                self.click_timer_id = GLib.timeout_add(250, self._handle_single_click)
                return True
            elif event.button == 3:
                self.show_context_menu(event)
                return True

        return False

    def _handle_single_click(self):
        self.click_timer_id = None
        self.toggle_play_pause()
        return False

    def on_scale_change_value(self, scale, scroll_type, value):
        """슬라이더 드래그 중 실시간으로 위치 라벨을 업데이트합니다."""
        if self.is_seeking and self.duration_ns > 0:
            target = int(self.duration_ns * value / 100)
            self.position_label.set_text(self.format_time(target))
            if getattr(self, "fs_position_label", None):
                self.fs_position_label.set_text(self.format_time(target))
        return False

    def build_fs_controls(self):
        """전체화면(Fullscreen) 모드 전용 플로팅 컨트롤 바 위젯을 생성합니다."""
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.get_style_context().add_class("fs-controls")

        # 타임라인
        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.fs_position_label = Gtk.Label(label="00:00")
        self.fs_position_label.get_style_context().add_class("muted")

        self.fs_progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.fs_progress_scale.set_draw_value(False)
        self.fs_progress_scale.set_hexpand(True)
        self.fs_progress_scale.connect("button-press-event", self.on_seek_start)
        self.fs_progress_scale.connect("button-release-event", self.on_fs_seek_end)
        self.fs_progress_scale.connect("change-value", self.on_scale_change_value)

        self.fs_duration_label = Gtk.Label(label="00:00")
        self.fs_duration_label.get_style_context().add_class("muted")

        timeline.pack_start(self.fs_position_label, False, False, 0)
        timeline.pack_start(self.fs_progress_scale, True, True, 0)
        timeline.pack_start(self.fs_duration_label, False, False, 0)
        panel.pack_start(timeline, False, False, 0)

        # 액션 버튼 열
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        prev_btn = Gtk.Button(label="⏮")
        prev_btn.set_tooltip_text("이전 영상 (P)")
        prev_btn.connect("clicked", lambda _b: self.play_prev_video())

        rewind_btn = Gtk.Button(label="↶ 10")
        rewind_btn.set_tooltip_text("10초 뒤로 (←)")
        rewind_btn.connect("clicked", lambda _b: self.seek_relative(-10))

        self.fs_play_button = Gtk.Button(label="Ⅱ")
        self.fs_play_button.get_style_context().add_class("primary")
        self.fs_play_button.set_tooltip_text("재생/일시정지 (Space)")
        self.fs_play_button.connect("clicked", lambda _b: self.toggle_play_pause())

        forward_btn = Gtk.Button(label="10 ↷")
        forward_btn.set_tooltip_text("10초 앞으로 (→)")
        forward_btn.connect("clicked", lambda _b: self.seek_relative(10))

        next_btn = Gtk.Button(label="⏭")
        next_btn.set_tooltip_text("다음 영상 (N)")
        next_btn.connect("clicked", lambda _b: self.play_next_video())

        for b in (prev_btn, rewind_btn, self.fs_play_button, forward_btn, next_btn):
            actions.pack_start(b, False, False, 0)

        # 속도 조절
        fs_speed_down = Gtk.Button(label="˗")
        fs_speed_down.set_tooltip_text("재생 속도 감소 (단축키: Down 또는 a)")
        fs_speed_down.connect("clicked", lambda _b: self.step_playback_rate(-0.25))

        self.fs_speed_button = Gtk.Button(label="1.0x")
        self.fs_speed_button.get_style_context().add_class("speed-btn")
        self.fs_speed_button.set_tooltip_text("재생 속도 조절 (단축키: Up/Down 또는 d/a, r: 1.0x)")
        self.fs_speed_button.connect("clicked", self.on_speed_button_clicked)

        fs_speed_up = Gtk.Button(label="˖")
        fs_speed_up.set_tooltip_text("재생 속도 증가 (단축키: Up 또는 d)")
        fs_speed_up.connect("clicked", lambda _b: self.step_playback_rate(0.25))

        actions.pack_start(fs_speed_down, False, False, 0)
        actions.pack_start(self.fs_speed_button, False, False, 0)
        actions.pack_start(fs_speed_up, False, False, 0)

        spacer = Gtk.Box()
        actions.pack_start(spacer, True, True, 0)

        # 볼륨 및 음소거
        self.fs_mute_btn = Gtk.Button(label="◖)))")
        self.fs_mute_btn.set_tooltip_text("음소거 (M)")
        self.fs_mute_btn.connect("clicked", lambda _b: self.toggle_mute())
        actions.pack_start(self.fs_mute_btn, False, False, 2)

        self.fs_volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 1)
        self.fs_volume_scale.set_size_request(90, -1)
        self.fs_volume_scale.set_draw_value(False)
        self.fs_volume_scale.set_value(100)
        self.fs_volume_scale.connect("value-changed", self.on_fs_volume_changed)
        actions.pack_start(self.fs_volume_scale, False, False, 0)

        # 창 모드로 복귀
        fs_toggle_btn = Gtk.Button(label="⧉")
        fs_toggle_btn.set_tooltip_text("창 모드로 복귀 (F / Esc)")
        fs_toggle_btn.connect("clicked", lambda _b: self.toggle_fullscreen())
        actions.pack_end(fs_toggle_btn, False, False, 0)

        # 자막
        self.fs_sub_button = Gtk.Button(label="💬 자막")
        self.fs_sub_button.set_tooltip_text("자막 켜기/끄기 (S)")
        self.fs_sub_button.connect("clicked", self.on_sub_button_clicked)
        actions.pack_end(self.fs_sub_button, False, False, 2)

        # 북마크
        fs_bm_btn = Gtk.Button(label="🔖 북마크")
        fs_bm_btn.set_tooltip_text("북마크 목록 보기 / 추가 (B)")
        fs_bm_btn.connect("clicked", lambda b: self.show_bookmarks_popover(b))
        actions.pack_end(fs_bm_btn, False, False, 2)

        # 무손실 스크린샷 캡처
        fs_cap_btn = Gtk.Button(label="📸 캡처")
        fs_cap_btn.set_tooltip_text("현재 프레임 무손실 스크린샷 저장 (Ctrl+S / C)")
        fs_cap_btn.connect("clicked", lambda _b: self.capture_screenshot())
        actions.pack_end(fs_cap_btn, False, False, 2)

        panel.pack_start(actions, False, False, 0)

        panel.connect("enter-notify-event", self._on_fs_controls_enter)
        panel.connect("leave-notify-event", self._on_fs_controls_leave)

        return panel

    def _on_fs_controls_enter(self, widget, event):
        self.is_mouse_over_fs_controls = True
        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        return False

    def _on_fs_controls_leave(self, widget, event):
        self.is_mouse_over_fs_controls = False
        if self.is_video_only:
            if getattr(self, "cursor_hide_timer_id", None):
                try:
                    GLib.source_remove(self.cursor_hide_timer_id)
                except Exception:
                    pass
            self.cursor_hide_timer_id = GLib.timeout_add(2500, self._on_hide_timer_tick)
        return False

    def on_fs_seek_end(self, scale, _event):
        if self.pipeline and self.duration_ns > 0:
            target = int(self.duration_ns * scale.get_value() / 100)
            self.last_known_pos_ns = target
            self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                Gst.SeekType.SET,
                target,
                Gst.SeekType.NONE,
                -1
            )
            self.show_osd(f"⏱️ {self.format_time(target)} / {self.format_time(self.duration_ns)}")
        self.is_seeking = False
        return False

    def on_fs_volume_changed(self, scale):
        val = scale.get_value()
        if self.is_muted and val > 0:
            self.is_muted = False
            if getattr(self, "mute_btn", None):
                self.mute_btn.set_label("◖)))")
            if getattr(self, "fs_mute_btn", None):
                self.fs_mute_btn.set_label("◖)))")
        if hasattr(self, "volume_scale") and abs(self.volume_scale.get_value() - val) > 0.5:
            self.volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)
        boost_str = " (부스트)" if val > 100 else ""
        self.show_osd(f"🔊 볼륨: {int(val)}%{boost_str}")
    @staticmethod
    def format_time(nanoseconds):
        total_seconds = max(0, int(nanoseconds / Gst.SECOND))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def update_playback_ui(self):
        if not self.pipeline:
            return True
        position_ok, position = self.pipeline.query_position(Gst.Format.TIME)
        if position_ok and position > 0:
            self.last_known_pos_ns = position

            # A-B 구간 반복 루프 검사
            if getattr(self, "is_ab_repeat_active", False) and self.ab_repeat_a is not None and self.ab_repeat_b is not None:
                if position >= self.ab_repeat_b:
                    self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, self.ab_repeat_a)
                    return True

            # 5초 이상 재생 시 이어보기 캐시 갱신
            if self.playlist and 0 <= self.current_index < len(self.playlist):
                resume_cache.set(self.playlist[self.current_index], position, self.duration_ns)

        pos_sec = int(position / Gst.SECOND) if position_ok else -1

        if position_ok and pos_sec != self.last_ui_pos_sec:
            self.last_ui_pos_sec = pos_sec
            time_str = self.format_time(position)

            # 1) 일반 모드 컨트롤 UI 갱신
            if not self.is_video_only:
                self.position_label.set_text(time_str)
                if self.duration_ns == 0:
                    duration_ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
                    if duration_ok and duration > 0:
                        self.duration_ns = duration
                        self.duration_label.set_text(self.format_time(duration))
                if self.duration_ns > 0 and not self.is_seeking:
                    self.progress_scale.set_value(min(100, position * 100 / self.duration_ns))

            # 2) 전체화면 플로팅 컨트롤 UI 갱신
            if getattr(self, "fs_position_label", None):
                self.fs_position_label.set_text(time_str)
            if getattr(self, "fs_duration_label", None):
                if self.duration_ns > 0:
                    self.fs_duration_label.set_text(self.format_time(self.duration_ns))
            if getattr(self, "fs_progress_scale", None) and self.duration_ns > 0 and not self.is_seeking:
                self.fs_progress_scale.set_value(min(100, position * 100 / self.duration_ns))

        # 미디어 HUD 갱신
        if getattr(self, "is_hud_visible", False) and self.stats_ticks % 4 == 0:
            self.update_hud_info()

        self.stats_ticks += 1
        if self.video_sink and self.stats_ticks % 20 == 0 and self.video_sink.find_property("stats"):
            stats = self.video_sink.get_property("stats")
            if stats:
                rendered = stats.get_value("rendered") or 0
                dropped = stats.get_value("dropped") or 0
                if dropped > self.last_dropped_frames:
                    print(f"📊 [렌더링 통계] rendered={rendered}, dropped={dropped}")
                self.last_dropped_frames = dropped
        return True

    def on_seek_start(self, scale, event):
        self.is_seeking = True
        if event.button == 1:
            alloc = scale.get_allocation()
            if alloc.width > 0:
                click_ratio = max(0.0, min(1.0, event.x / alloc.width))
                scale.set_value(click_ratio * 100)
                if self.duration_ns > 0:
                    target = int(self.duration_ns * click_ratio)
                    self.position_label.set_text(self.format_time(target))
                    if getattr(self, "fs_position_label", None):
                        self.fs_position_label.set_text(self.format_time(target))
        return False

    def on_seek_end(self, scale, _event):
        if self.pipeline and self.duration_ns > 0:
            target = int(self.duration_ns * scale.get_value() / 100)
            self.last_known_pos_ns = target
            self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                Gst.SeekType.SET,
                target,
                Gst.SeekType.NONE,
                -1
            )
            self.show_osd(f"⏱️ {self.format_time(target)} / {self.format_time(self.duration_ns)}")
        self.is_seeking = False
        return False

    def on_volume_changed(self, scale):
        val = scale.get_value()
        if self.is_muted and val > 0:
            self.is_muted = False
            if getattr(self, "mute_btn", None):
                self.mute_btn.set_label("◖)))")
            if getattr(self, "fs_mute_btn", None):
                self.fs_mute_btn.set_label("◖)))")
        if hasattr(self, "fs_volume_scale") and abs(self.fs_volume_scale.get_value() - val) > 0.5:
            self.fs_volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)
        self.show_osd(f"🔊 볼륨: {int(val)}%")

    def hide_cursor(self):
        """마우스 커서를 투명(숨김) 커서로 설정합니다."""
        self.cursor_hide_timer_id = None
        gdk_win = self.get_window()
        if gdk_win:
            display = gdk_win.get_display()
            blank_cursor = None
            try:
                blank_cursor = Gdk.Cursor.new_from_name(display, "none")
            except Exception:
                pass
            if not blank_cursor:
                blank_cursor = Gdk.Cursor.new_for_display(display, Gdk.CursorType.BLANK_CURSOR)
            gdk_win.set_cursor(blank_cursor)
            self.is_cursor_hidden = True
        return False

    def show_cursor(self):
        """마우스 커서를 기본 포인터로 복원합니다."""
        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.set_cursor(None)
        self.is_cursor_hidden = False

    def on_mouse_motion(self, widget, event):
        """마우스 움직임 감지 시 커서를 표시하고 전체화면일 때 컨트롤 바를 띄운 후 2.5초 후 자동 숨김 타이머를 재설정합니다."""
        if self.is_video_only:
            if self.is_cursor_hidden:
                self.show_cursor()
            if getattr(self, "fs_controls_box", None) and not self.is_fs_controls_visible:
                self.fs_controls_box.show_all()
                self.is_fs_controls_visible = True

            if getattr(self, "cursor_hide_timer_id", None):
                try:
                    GLib.source_remove(self.cursor_hide_timer_id)
                except Exception:
                    pass
            self.cursor_hide_timer_id = GLib.timeout_add(2500, self._on_hide_timer_tick)
        return False

    def _on_hide_timer_tick(self):
        """2.5초 동안 마우스 조작이 없을 때 전체화면 컨트롤 바와 커서를 숨깁니다."""
        if self.is_video_only:
            if getattr(self, "is_mouse_over_fs_controls", False) or getattr(self, "is_popover_open", False):
                return True
            if getattr(self, "fs_controls_box", None) and self.is_fs_controls_visible:
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.hide_cursor()
        self.cursor_hide_timer_id = None
        return False

    def on_window_button_press(self, widget, event):
        """더블클릭 시 전체화면 전환 및 마우스 조작 감지"""
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.toggle_fullscreen()
            return True
        if self.is_video_only:
            self.on_mouse_motion(widget, event)
        return False

    def toggle_fullscreen(self):
        """상단바, 재생목록, 컨트롤을 숨긴 영상 전용 전체화면을 전환합니다."""
        if not self.is_video_only:
            self.sidebar_was_visible = self.sidebar.get_visible()
            self.topbar.hide()
            self.sidebar.hide()
            self.controls.hide()
            if getattr(self, "fs_controls_box", None):
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.fullscreen()
            self.set_decorated(False)
            self.set_keep_above(True)
            self.is_fullscreen = True
            self.is_video_only = True
            self.fullscreen_button.set_label("⧉")
            # 전체화면 전환 시 마우스 커서 즉시 숨김
            self.hide_cursor()
            self.show_osd("🖥️ 전체화면 (영상 전용)")
            print("🖥️ 영상 전용 전체화면 (마우스 조작 시 컨트롤 표시)")
        else:
            self.unfullscreen()
            self.set_decorated(True)
            self.set_keep_above(self.is_keep_above)
            self.topbar.show()
            self.controls.show()
            if self.sidebar_was_visible:
                self.sidebar.show()
                if self.main_paned:
                    alloc_w = self.main_paned.get_allocation().width
                    if alloc_w > 0:
                        self.main_paned.set_position(max(200, alloc_w - self.sidebar_width))
            if getattr(self, "fs_controls_box", None):
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.is_fullscreen = False
            self.is_video_only = False
            self.fullscreen_button.set_label("⛶")
            # 일반 모드 복귀 시 마우스 커서 복원
            self.show_cursor()
            self.show_osd("🖥️ 창 모드 복귀")
            print("🖥️ 플레이어 창 모드 복귀")
