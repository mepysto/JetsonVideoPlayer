"""외부/내장 자막 선택, 크기·싱크 조절"""
import os
from urllib.request import pathname2url

from gi.repository import GLib, Gst, Gtk

from ..subtitles.merge import generate_merged_subtitle_file


class SubtitlesMixin:
    def get_current_subtitle_font_desc(self):
        """
        한국어(KR), 중국어 번체/대만어(TC), 간체(SC), 일본어(JP), 영문 알파벳을
        한 글자의 빠짐이나 깨짐 없이 100% 온전하게 렌더링하는 CJK 통합 폰트 디스크립터를 반환합니다.
        """
        active_indices = getattr(self, "active_subtitle_indices", set())
        
        num_tracks = len(active_indices) if active_indices else 1
        if num_tracks <= 1:
            base_pt = 22
        elif num_tracks == 2:
            base_pt = 17
        else:
            base_pt = 14
        final_pt = max(10, min(36, int(base_pt * getattr(self, "subtitle_font_scale", 1.0))))
        
        # Noto Sans CJK TC는 대만 번체 한자(13,053자)와 한글(11,172자), 영문, 기호를 단일 폰트 내에 100% 내장하고 있어
        # 한국어 단독, 중국어 단독, 한국어+중국어+영어 다중 자막 어떤 조합에서도 폰트 폴백 결함 없이 완벽히 렌더링됩니다.
        font_stack = "Noto Sans CJK TC, Noto Sans CJK KR, Noto Sans CJK SC, Noto Sans CJK JP, Sans"
        return f"{font_stack} Bold {final_pt}"

    def build_subtitle_popover(self, parent_btn=None):
        """다중 자막 선택, 크기 조절 및 싱크 조절 팝오버(Popover) 창을 구성합니다."""
        target_btn = parent_btn or (self.fs_sub_button if self.is_video_only and getattr(self, "fs_sub_button", None) else self.sub_button)
        self.sub_popover = Gtk.Popover(relative_to=target_btn)
        self.sub_popover.set_position(Gtk.PositionType.TOP)
        self.sub_popover.set_border_width(12)
        
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # 헤더
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="💬 자막 선택 & 설정", xalign=0)
        title.get_style_context().add_class("popover-title")
        header.pack_start(title, True, True, 0)
        container.pack_start(header, False, False, 2)
        
        hint = Gtk.Label(label="다중 자막 선택 시 언어별 뱃지와 함께 동시에 표시됩니다.", xalign=0)
        hint.get_style_context().add_class("muted")
        container.pack_start(hint, False, False, 0)
        
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        container.pack_start(sep1, False, False, 2)

        # 🗚 자막 크기 조절 바
        size_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        size_bar.get_style_context().add_class("sub-btn-row")
        
        size_lbl = Gtk.Label(label="🗚 크기:")
        size_lbl.get_style_context().add_class("muted")
        size_bar.pack_start(size_lbl, False, False, 0)
        
        dec_btn = Gtk.Button(label="작게 (-)")
        dec_btn.set_tooltip_text("자막 크기 축소 (단축키: [ )")
        dec_btn.connect("clicked", lambda _b: self.adjust_subtitle_scale(-0.1))
        size_bar.pack_start(dec_btn, True, True, 0)
        
        pct_str = f"{int(self.subtitle_font_scale * 100)}%"
        self.scale_label = Gtk.Label(label=pct_str)
        self.scale_label.set_width_chars(5)
        size_bar.pack_start(self.scale_label, False, False, 2)
        
        inc_btn = Gtk.Button(label="크게 (+)")
        inc_btn.set_tooltip_text("자막 크기 확대 (단축키: ] )")
        inc_btn.connect("clicked", lambda _b: self.adjust_subtitle_scale(0.1))
        size_bar.pack_start(inc_btn, True, True, 0)
        
        reset_size_btn = Gtk.Button(label="100%")
        reset_size_btn.set_tooltip_text("기본 크기(100%)로 복원")
        reset_size_btn.connect("clicked", self.reset_subtitle_scale)
        size_bar.pack_start(reset_size_btn, False, False, 0)
        
        container.pack_start(size_bar, False, False, 2)

        # ⏱️ 자막 싱크(Sync) 조절 바
        sync_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sync_bar.get_style_context().add_class("sub-btn-row")
        
        sync_lbl = Gtk.Label(label="⏱️ 싱크:")
        sync_lbl.get_style_context().add_class("muted")
        sync_bar.pack_start(sync_lbl, False, False, 0)
        
        fast_btn = Gtk.Button(label="-0.5s")
        fast_btn.set_tooltip_text("자막 0.5초 빠르게 (단축키: Z, ,: -0.1s)")
        fast_btn.connect("clicked", lambda _b: self.adjust_subtitle_sync(-500))
        sync_bar.pack_start(fast_btn, True, True, 0)
        
        sync_str = f"{self.subtitle_offset_ms / 1000:+.1f}s"
        self.sync_label = Gtk.Label(label=sync_str)
        self.sync_label.set_width_chars(6)
        sync_bar.pack_start(self.sync_label, False, False, 2)
        
        slow_btn = Gtk.Button(label="+0.5s")
        slow_btn.set_tooltip_text("자막 0.5초 느리게 (단축키: X, .: +0.1s)")
        slow_btn.connect("clicked", lambda _b: self.adjust_subtitle_sync(500))
        sync_bar.pack_start(slow_btn, True, True, 0)
        
        reset_sync_btn = Gtk.Button(label="0.0s")
        reset_sync_btn.set_tooltip_text("자막 싱크 기본값(0.0초)으로 복원")
        reset_sync_btn.connect("clicked", self.reset_subtitle_sync)
        sync_bar.pack_start(reset_sync_btn, False, False, 0)
        
        container.pack_start(sync_bar, False, False, 2)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        container.pack_start(sep2, False, False, 2)

        # 자막 체크박스 리스트
        self.sub_checkboxes = []
        for idx, sub in enumerate(self.available_subtitles):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            
            # 색상 표시 원형 인디케이터
            color_box = Gtk.DrawingArea()
            color_box.set_size_request(12, 12)
            c_hex = sub['color']
            def draw_color_dot(widget, cr, col_hex):
                try:
                    r = int(col_hex[1:3], 16) / 255.0
                    g = int(col_hex[3:5], 16) / 255.0
                    b = int(col_hex[5:7], 16) / 255.0
                    cr.set_source_rgb(r, g, b)
                    cr.arc(6, 6, 5, 0, 2 * 3.14159)
                    cr.fill()
                except Exception:
                    pass
            color_box.connect("draw", draw_color_dot, c_hex)
            row.pack_start(color_box, False, False, 2)
            
            chk = Gtk.CheckButton(label=sub['label'])
            chk.set_active(idx in self.active_subtitle_indices)
            chk.connect("toggled", self.on_subtitle_checkbox_toggled, idx)
            row.pack_start(chk, True, True, 0)
            
            self.sub_checkboxes.append(chk)
            container.pack_start(row, False, False, 2)
            
        # 전체 선택 / 전체 해제 버튼
        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_bar.get_style_context().add_class("sub-btn-row")
        select_all_btn = Gtk.Button(label="모두 선택")
        select_all_btn.connect("clicked", self.on_select_all_subtitles)
        deselect_all_btn = Gtk.Button(label="모두 해제")
        deselect_all_btn.connect("clicked", self.on_deselect_all_subtitles)
        btn_bar.pack_start(select_all_btn, True, True, 0)
        btn_bar.pack_start(deselect_all_btn, True, True, 0)
        container.pack_start(btn_bar, False, False, 4)
        
        container.show_all()
        self.sub_popover.add(container)

        def on_sub_pop_closed(_pop):
            self.is_popover_open = False
        self.sub_popover.connect("closed", on_sub_pop_closed)

    def adjust_subtitle_scale(self, delta):
        """자막 크기를 delta만큼 확대/축소하고 즉시 화면에 반영합니다."""
        new_scale = round(max(0.6, min(1.6, self.subtitle_font_scale + delta)), 2)
        if new_scale != self.subtitle_font_scale:
            self.subtitle_font_scale = new_scale
            pct = int(self.subtitle_font_scale * 100)
            print(f"🗚 [자막 크기 조절] {pct}%")
            self.show_osd(f"🗚 자막 크기: {pct}%")
            if getattr(self, "scale_label", None):
                self.scale_label.set_text(f"{pct}%")
            if getattr(self, "subtitle_overlay_element", None):
                try:
                    self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
                except Exception:
                    pass
            self.schedule_subtitles_reload()

    def reset_subtitle_scale(self, _btn=None):
        """자막 크기를 기본값(100%)으로 복원합니다."""
        if self.subtitle_font_scale != 1.0:
            self.subtitle_font_scale = 1.0
            print("🗚 [자막 크기 조절] 100% (기본값)")
            self.show_osd("🗚 자막 크기: 100%")
            if getattr(self, "scale_label", None):
                self.scale_label.set_text("100%")
            if getattr(self, "subtitle_overlay_element", None):
                try:
                    self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
                except Exception:
                    pass
            self.schedule_subtitles_reload()

    def adjust_subtitle_sync(self, delta_ms):
        """자막 싱크를 delta_ms만큼 앞당기거나 늦추고 실시간 OSD 반영 후 디바운스로 적용합니다."""
        self.subtitle_offset_ms += delta_ms
        sec_str = f"{self.subtitle_offset_ms / 1000:+.1f}s"
        print(f"⏱️ [자막 싱크 조절] {sec_str}")
        self.show_osd(f"⏱️ 자막 싱크: {sec_str}")
        if getattr(self, "sync_label", None):
            self.sync_label.set_text(sec_str)
        self.schedule_subtitles_reload()

    def reset_subtitle_sync(self, _btn=None):
        """자막 싱크를 기본값(0.0초)으로 복원합니다."""
        if self.subtitle_offset_ms != 0:
            self.subtitle_offset_ms = 0
            print("⏱️ [자막 싱크 조절] 0.0s (기본값)")
            self.show_osd("⏱️ 자막 싱크: 0.0s")
            if getattr(self, "sync_label", None):
                self.sync_label.set_text("0.0s")
            self.schedule_subtitles_reload()

    def show_subtitle_popover(self, parent_btn=None):
        """자막 선택 팝오버를 열거나 닫습니다."""
        if not self.available_subtitles:
            print("ℹ️ 현재 영상에 사용 가능한 자막이 없습니다.")
            return
        if self.sub_popover:
            self.sub_popover.destroy()
            self.sub_popover = None
        self.build_subtitle_popover(parent_btn=parent_btn)
        self.is_popover_open = True
        self.sub_popover.show_all()
        self.sub_popover.popup()

    def _detect_embedded_subtitles(self):
        """외부 자막이 없을 때 컨테이너 내장 자막 트랙 수를 감지하고 표시 여부를 적용합니다."""
        if not self.pipeline or self.available_subtitles:
            return
        try:
            n_text = self.pipeline.get_property("n-text")
        except Exception:
            return
        if n_text != self.n_embedded_text:
            self.n_embedded_text = n_text
            if n_text > 0:
                print(f"💬 [내장 자막 감지] {n_text}개 트랙")
        if self.n_embedded_text > 0:
            self._apply_embedded_subs_visibility()
        self.update_subtitle_button_ui()

    def _apply_embedded_subs_visibility(self):
        for ov in self.subtitle_overlays:
            try:
                if ov.find_property("silent"):
                    ov.set_property("silent", not self.embedded_subs_enabled)
            except Exception:
                pass

    def _embedded_track_label(self, idx):
        """내장 자막 트랙의 언어 태그를 읽어 표시용 이름을 만듭니다."""
        lang = ""
        try:
            tags = self.pipeline.emit("get-text-tags", idx) if self.pipeline else None
            if tags:
                ok, val = tags.get_string(Gst.TAG_LANGUAGE_CODE)
                if ok and val:
                    lang = f" ({val})"
        except Exception:
            pass
        return f"내장 자막 {idx + 1}/{self.n_embedded_text}{lang}"

    def toggle_embedded_subtitles(self):
        self.embedded_subs_enabled = not self.embedded_subs_enabled
        self._apply_embedded_subs_visibility()
        cur = self.pipeline.get_property("current-text") if self.pipeline else 0
        name = self._embedded_track_label(max(0, cur))
        self.show_osd(f"💬 {name} {'ON' if self.embedded_subs_enabled else 'OFF'}")
        self.update_subtitle_button_ui()

    def cycle_embedded_subtitles(self):
        """내장 자막 트랙 순환: 트랙1 → 트랙2 → … → 끄기 → 트랙1"""
        if not self.pipeline or self.n_embedded_text <= 0:
            return
        if not self.embedded_subs_enabled:
            self.embedded_subs_enabled = True
            self.pipeline.set_property("current-text", 0)
            nxt = 0
        else:
            cur = max(0, self.pipeline.get_property("current-text"))
            nxt = cur + 1
            if nxt >= self.n_embedded_text:
                self.embedded_subs_enabled = False
            else:
                self.pipeline.set_property("current-text", nxt)
        self._apply_embedded_subs_visibility()
        if self.embedded_subs_enabled:
            self.show_osd(f"💬 {self._embedded_track_label(nxt)}")
        else:
            self.show_osd("💬 내장 자막 OFF")
        self.update_subtitle_button_ui()

    def on_sub_button_clicked(self, widget):
        """자막 버튼 클릭 시 단일 자막은 토글, 다중 자막은 팝오버 메뉴를 표시합니다."""
        if not self.available_subtitles:
            if self.n_embedded_text > 1:
                self.cycle_embedded_subtitles()
            elif self.n_embedded_text == 1:
                self.toggle_embedded_subtitles()
            return
        if len(self.available_subtitles) == 1:
            self.toggle_subtitles()
        else:
            self.show_subtitle_popover(parent_btn=widget)

    def on_subtitle_checkbox_toggled(self, chk_button, track_idx):
        """자막 체크박스 토글 시 실시간으로 활성 자막 목록을 갱신하고 화면에 안전하게 반영합니다."""
        if getattr(self, "is_updating_sub_checkboxes", False):
            return
            
        if chk_button.get_active():
            self.active_subtitle_indices.add(track_idx)
            self.subtitles_enabled = True
        else:
            self.active_subtitle_indices.discard(track_idx)
            if not self.active_subtitle_indices:
                self.subtitles_enabled = False
        self.schedule_subtitles_reload()

    def on_select_all_subtitles(self, _btn):
        """모든 자막 체크 활성화 (일괄 락 적용으로 프로그램 충돌 및 중복 리로드 차단)"""
        self.is_updating_sub_checkboxes = True
        try:
            self.active_subtitle_indices = set(range(len(self.available_subtitles)))
            self.subtitles_enabled = bool(self.active_subtitle_indices)
            for chk in getattr(self, "sub_checkboxes", []):
                chk.set_active(True)
        finally:
            self.is_updating_sub_checkboxes = False
        self.schedule_subtitles_reload()

    def on_deselect_all_subtitles(self, _btn):
        """모든 자막 체크 해제 (일괄 락 적용으로 프로그램 충돌 및 중복 리로드 차단)"""
        self.is_updating_sub_checkboxes = True
        try:
            self.active_subtitle_indices.clear()
            self.subtitles_enabled = False
            for chk in getattr(self, "sub_checkboxes", []):
                chk.set_active(False)
        finally:
            self.is_updating_sub_checkboxes = False
        self.schedule_subtitles_reload()

    def schedule_subtitles_reload(self):
        """빠른 조작이나 연타 시 파이프라인 중복 파괴를 막기 위해 150ms 디바운스로 안전하게 재로드합니다."""
        if getattr(self, "sub_reload_timer_id", None):
            try:
                GLib.source_remove(self.sub_reload_timer_id)
            except Exception:
                pass
            self.sub_reload_timer_id = None
        self.sub_reload_timer_id = GLib.timeout_add(150, self._deferred_reload_subtitles)

    def _deferred_reload_subtitles(self):
        self.sub_reload_timer_id = None
        self.reload_and_apply_subtitles()
        return False

    def reload_and_apply_subtitles(self):
        """선택된 다중 자막 트랙들을 실시간 병합하여 GStreamer 파이프라인에 즉시 반영합니다."""
        if not self.pipeline:
            return
            
        video_path = self.playlist[self.current_index]
        active_tracks = []
        for idx in sorted(list(self.active_subtitle_indices)):
            if 0 <= idx < len(self.available_subtitles):
                sub = self.available_subtitles[idx]
                active_tracks.append((sub['label'], sub['color'], sub['events']))
                
        if active_tracks and self.subtitles_enabled:
            merged_file = generate_merged_subtitle_file(
                active_tracks, video_path,
                font_scale=self.subtitle_font_scale,
                offset_ms=self.subtitle_offset_ms
            )
            new_suburi = f"file://{pathname2url(os.path.abspath(merged_file))}" if merged_file else None
        else:
            new_suburi = None
            
        # GStreamer playbin은 실행 중 suburi 변경 시 내부 파서를 다시 읽지 않으므로,
        # 자막 스트림이 변경된 경우 현재 재생 위치(초 단위)를 100% 보존하여 즉시 매끄럽게 재로드합니다.
        if new_suburi != getattr(self, "current_suburi", None):
            pos_ns = 0
            if self.pipeline:
                success, q_pos = self.pipeline.query_position(Gst.Format.TIME)
                if success and q_pos > 0:
                    pos_ns = q_pos
                elif getattr(self, "last_known_pos_ns", 0) > 0:
                    pos_ns = self.last_known_pos_ns
            self.play_current_video(start_position_ns=pos_ns)
        else:
            if not self.subtitles_enabled or not active_tracks:
                self.pipeline.set_property("current-text", -1)
            else:
                self.pipeline.set_property("current-text", 0)
                
        if getattr(self, "subtitle_overlay_element", None):
            try:
                self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
            except Exception:
                pass

        self.update_subtitle_button_ui()

    def update_subtitle_button_ui(self):
        """자막 버튼 레이블 및 활성화 상태 갱신 (일반 컨트롤 및 전체화면 컨트롤)"""
        btns = [b for b in [getattr(self, "sub_button", None), getattr(self, "fs_sub_button", None)] if b is not None]
        if not btns:
            return
            
        total = len(self.available_subtitles)
        if total == 0 and self.n_embedded_text > 0:
            state = "ON" if self.embedded_subs_enabled else "OFF"
            count = f" ({self.n_embedded_text})" if self.n_embedded_text > 1 else ""
            tip = "내장 자막 켜기/끄기 (S)" if self.n_embedded_text == 1 else "클릭: 내장 자막 트랙 순환 / S: 켜기·끄기"
            for b in btns:
                b.set_label(f"💬 내장{count} {state}")
                b.set_sensitive(True)
                b.set_tooltip_text(tip)
        elif total == 0:
            for b in btns:
                b.set_label("💬 자막 없음")
                b.set_sensitive(False)
                b.set_tooltip_text("자막 없음")
        elif total == 1:
            lbl = "💬 자막 ON" if (self.subtitles_enabled and self.active_subtitle_indices) else "💬 자막 OFF"
            for b in btns:
                b.set_label(lbl)
                b.set_sensitive(True)
                b.set_tooltip_text("자막 켜기/끄기 (S)")
        else:
            active_cnt = len(self.active_subtitle_indices) if self.subtitles_enabled else 0
            lbl = f"💬 자막 ({active_cnt}/{total})"
            for b in btns:
                b.set_label(lbl)
                b.set_sensitive(True)
                b.set_tooltip_text(f"다중 자막 선택 메뉴 (S: 토글, C: 설정 창) - {total}개 사용 가능")

    def toggle_subtitles(self):
        """자막 켜기/끄기 상태를 토글합니다."""
        if not self.available_subtitles:
            if self.n_embedded_text > 0:
                self.toggle_embedded_subtitles()
            else:
                print("ℹ️ 현재 영상에 로드된 자막이 없습니다.")
            return

        self.subtitles_enabled = not self.subtitles_enabled
        if self.subtitles_enabled and not self.active_subtitle_indices:
            self.active_subtitle_indices = set(range(len(self.available_subtitles)))

        status_str = "ON" if self.subtitles_enabled else "OFF"
        self.show_osd(f"💬 자막 {status_str}")
        self.reload_and_apply_subtitles()
