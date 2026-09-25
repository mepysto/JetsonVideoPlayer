"""A-B 반복, 북마크, 스크린샷, AV 싱크, HUD, 도움말, 컨텍스트 메뉴"""
import datetime
import logging
import os

from gi.repository import GLib, Gdk, Gst, Gtk

from ..shortcuts import help_rows
from ..storage import bookmark_cache
from ..system import get_jetson_hw_stats

log = logging.getLogger(__name__)


class FeaturesMixin:
    def set_ab_repeat_a(self):
        """현재 재생 위치를 A-B 구간 반복의 시작점(A)으로 설정합니다."""
        if not self.pipeline:
            return
        success, pos = self.pipeline.query_position(Gst.Format.TIME)
        if success and pos >= 0:
            self.ab_repeat_a = pos
            self.is_ab_repeat_active = False
            if getattr(self, "ab_badge", None):
                self.ab_badge.hide()
            t_str = self.format_time(pos)
            self.show_osd(f"🔁 구간 반복 [A] 설정: {t_str}")
            log.info(f"🔁 [구간 반복] A 지점 설정: {t_str}")
            self.refresh_timeline_marks()

    def set_ab_repeat_b(self):
        """현재 재생 위치를 A-B 구간 반복의 종료점(B)으로 설정하고 루프를 활성화합니다."""
        if not self.pipeline:
            return
        success, pos = self.pipeline.query_position(Gst.Format.TIME)
        if not success or pos < 0:
            return

        if self.ab_repeat_a is None:
            self.ab_repeat_a = 0

        if pos <= self.ab_repeat_a:
            self.show_osd("⚠️ B 지점은 A 지점보다 뒤여야 합니다.")
            return

        self.ab_repeat_b = pos
        self.is_ab_repeat_active = True
        a_str = self.format_time(self.ab_repeat_a)
        b_str = self.format_time(self.ab_repeat_b)
        if getattr(self, "ab_badge", None):
            self.ab_badge.set_label(f"🔁 {a_str} ~ {b_str} ✕")
            self.ab_badge.show()
        self.show_osd(f"🔁 [A-B] 구간 반복 활성화: {a_str} ~ {b_str}")
        log.info(f"🔁 [구간 반복] 활성화: {a_str} ~ {b_str}")
        self.refresh_timeline_marks()

    def clear_ab_repeat(self):
        """A-B 구간 반복을 해제합니다."""
        if self.ab_repeat_a is not None or self.ab_repeat_b is not None or self.is_ab_repeat_active:
            self.ab_repeat_a = None
            self.ab_repeat_b = None
            self.is_ab_repeat_active = False
            if getattr(self, "ab_badge", None):
                self.ab_badge.hide()
            self.show_osd("🔁 A-B 구간 반복 해제")
            log.info("🔁 [구간 반복] 해제")
            self.refresh_timeline_marks()

    def add_bookmark(self):
        """현재 재생 위치를 북마크에 추가합니다."""
        if not self.pipeline or not self.playlist or not (0 <= self.current_index < len(self.playlist)):
            return
        success, pos = self.pipeline.query_position(Gst.Format.TIME)
        if not success or pos < 0:
            return
        cur_path = self.playlist[self.current_index]
        ok, res = bookmark_cache.add(cur_path, pos)
        if ok:
            self.show_osd(f"🔖 북마크 추가: {res}")
            log.info(f"🔖 [북마크 추가] {os.path.basename(cur_path)} @ {res}")
            self.refresh_timeline_marks()
        else:
            self.show_osd(f"🔖 {res}")

    def show_bookmarks_popover(self, parent_widget=None):
        """현재 영상의 북마크 목록을 표시하고 클릭 시 즉시 점프하는 팝오버를 표시합니다."""
        if not self.playlist or not (0 <= self.current_index < len(self.playlist)):
            self.show_osd("재생 중인 영상이 없습니다.")
            return

        parent = parent_widget or getattr(self, "topbar", None) or self.play_button
        cur_path = self.playlist[self.current_index]
        bookmarks = bookmark_cache.get(cur_path)

        pop = Gtk.Popover(relative_to=parent)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(label="🔖 북마크 목록", xalign=0)
        title.get_style_context().add_class("popover-title")
        box.pack_start(title, False, False, 2)

        if not bookmarks:
            empty = Gtk.Label(label="등록된 북마크가 없습니다. (단축키 'B'로 추가)", xalign=0)
            empty.get_style_context().add_class("muted")
            box.pack_start(empty, False, False, 6)
        else:
            scroll = Gtk.ScrolledWindow()
            scroll.set_min_content_height(140)
            scroll.set_min_content_width(220)
            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            for idx, bm in enumerate(bookmarks):
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                b_jump = Gtk.Button(label=f"▶ {bm['label']}")
                b_jump.get_style_context().add_class("tree-tool-btn")
                b_jump.connect("clicked", lambda _b, p=bm['position_ns']: (self.seek_direct(p), pop.popdown()))
                row.pack_start(b_jump, True, True, 0)

                b_del = Gtk.Button(label="✕")
                b_del.get_style_context().add_class("tree-tool-btn")
                b_del.connect("clicked", lambda _b, i=idx: (bookmark_cache.remove(cur_path, i), self.refresh_timeline_marks(), pop.popdown(), self.show_bookmarks_popover(parent)))
                row.pack_start(b_del, False, False, 0)

                list_box.pack_start(row, False, False, 0)
            scroll.add(list_box)
            box.pack_start(scroll, True, True, 0)

        b_add = Gtk.Button(label="➕ 현재 위치 북마크 추가 (B)")
        b_add.get_style_context().add_class("primary")
        b_add.connect("clicked", lambda _b: (self.add_bookmark(), pop.popdown()))
        box.pack_start(b_add, False, False, 4)

        box.show_all()
        pop.add(box)
        pop.popup()

    def capture_screenshot(self):
        """현재 재생 중인 프레임을 무손실 PNG 이미지로 캡처하여 저장합니다."""
        if not self.pipeline:
            self.show_osd("캡처할 재생 영상이 없습니다.")
            return

        pic_dir = os.path.expanduser("~/Pictures/JetsonVideoPlayer")
        os.makedirs(pic_dir, exist_ok=True)
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Screenshot_{now_str}.png"
        filepath = os.path.join(pic_dir, filename)

        saved = False
        try:
            caps = Gst.Caps.from_string("image/png")
            sample = self.pipeline.emit("convert-sample", caps)
            if sample:
                buf = sample.get_buffer()
                succ, map_info = buf.map(Gst.MapFlags.READ)
                if succ:
                    with open(filepath, "wb") as f:
                        f.write(map_info.data)
                    buf.unmap(map_info)
                    saved = True
        except Exception:
            pass

        if not saved:
            try:
                win = self.video_widget.get_window()
                if win:
                    w = self.video_widget.get_allocated_width()
                    h = self.video_widget.get_allocated_height()
                    pixbuf = Gdk.pixbuf_get_from_window(win, 0, 0, w, h)
                    if pixbuf:
                        pixbuf.savev(filepath, "png", [], [])
                        saved = True
            except Exception:
                pass

        if saved:
            self.show_osd(f"📸 스크린샷 저장 완료: {filename}", timeout_ms=2000)
            log.info(f"📸 [스크린샷 캡처] 저장 완료: {filepath}")
        else:
            self.show_osd("⚠️ 스크린샷 캡처 실패")

    def adjust_av_sync(self, delta_ms):
        """오디오와 비디오 간의 싱크 오프셋을 미세 조절합니다 (단위: ms)."""
        self.av_sync_offset_ms += delta_ms
        offset_ns = self.av_sync_offset_ms * 1_000_000

        if getattr(self, "current_asink", None) and self.current_asink.find_property("ts-offset"):
            self.current_asink.set_property("ts-offset", offset_ns)

        sign = "+" if self.av_sync_offset_ms > 0 else ""
        self.show_osd(f"🔊 AV 싱크: {sign}{self.av_sync_offset_ms}ms")
        log.debug(f"🔊 [AV 싱크] 오프셋: {sign}{self.av_sync_offset_ms}ms")

    def reset_av_sync(self):
        """오디오 싱크 오프셋을 0ms(기본값)으로 복원합니다."""
        self.av_sync_offset_ms = 0
        if getattr(self, "current_asink", None) and self.current_asink.find_property("ts-offset"):
            self.current_asink.set_property("ts-offset", 0)
        self.show_osd("🔊 AV 싱크 초기화: 0ms")
        log.debug("🔊 [AV 싱크] 0ms 초기화 완료")

    def toggle_hud(self):
        """미디어 정보 및 실시간 통계 HUD 오버레이를 토글합니다."""
        if not getattr(self, "hud_box", None):
            return
        self.is_hud_visible = not self.is_hud_visible
        if self.is_hud_visible:
            self.update_hud_info()
            self.hud_box.show_all()
        else:
            self.hud_box.hide()

    def update_hud_info(self):
        """현재 비디오의 해상도, 디코더, FPS, 드롭 프레임 정보를 갱신합니다."""
        if not self.is_hud_visible or not getattr(self, "hud_label", None):
            return
        video_path = self.playlist[self.current_index] if (self.playlist and 0 <= self.current_index < len(self.playlist)) else "없음"
        fname = os.path.basename(video_path)
        
        # 시도했다가 버려진 디코더가 아니라, 실제로 영상이 흐르는(협상 완료된) 디코더를 표시합니다.
        active = self.active_video_decoder()
        decoders = active or "감지 중..."
        hw_str = "⚡ NVDEC 하드웨어 가속" if active and "nvv4l2" in active else ("💻 소프트웨어 디코딩" if active else "")
        
        pos_str = self.format_time(self.last_known_pos_ns)
        dur_str = self.format_time(self.duration_ns) if self.duration_ns > 0 else "00:00"
        
        dropped = self.last_dropped_frames
        sub_info = f"{len(self.active_subtitle_indices)}/{len(self.available_subtitles)}개 활성" if self.available_subtitles else "없음"
        
        text = (
            f"<b>[Jetson 미디어 및 시스템 모니터링]</b>\n"
            f"📁 <b>파일:</b> {GLib.markup_escape_text(fname)}\n"
            f"🚀 <b>디코더:</b> {GLib.markup_escape_text(decoders)} ({hw_str})\n"
            f"⏱️ <b>재생:</b> {pos_str} / {dur_str} (속도: {self.playback_rate:.2f}x)\n"
            f"📊 <b>드롭 프레임:</b> {dropped}\n"
            f"💬 <b>자막:</b> {sub_info}\n"
            f"🎵 <b>오디오:</b> 트랙 {self.current_audio_track + 1}/{max(1, self.n_audio_tracks)}"
        )

        hw = get_jetson_hw_stats()
        if "cpu_temp" in hw or "gpu_temp" in hw:
            c_str = f"CPU {hw['cpu_temp']:.1f}°C" if "cpu_temp" in hw else ""
            g_str = f"GPU {hw['gpu_temp']:.1f}°C" if "gpu_temp" in hw else ""
            text += f"\n🌡️ <b>SoC 온도:</b> {c_str}  {g_str}".rstrip()
        if "gpu_load" in hw:
            text += f"\n⚡ <b>GPU 로드:</b> {hw['gpu_load']:.1f}%"
        if "ram_used_gb" in hw:
            text += f"\n💾 <b>시스템 RAM:</b> {hw['ram_used_gb']:.1f}GB / {hw['ram_total_gb']:.1f}GB ({hw['ram_percent']:.0f}%)"
        if self.remote_url:
            text += f"\n📱 <b>웹 리모컨:</b> {self.remote_url}"

        self.hud_label.set_markup(text)

    def toggle_keep_above(self):
        """창을 항상 위에 표시할지 여부를 토글합니다."""
        self.is_keep_above = not self.is_keep_above
        self.set_keep_above(self.is_keep_above)
        status = "ON" if self.is_keep_above else "OFF"
        self.show_osd(f"📌 항상 위에 표시: {status}")

    def show_help_dialog(self):
        """단축키 가이드 다이얼로그를 표시합니다 (jetson_player/shortcuts.py 테이블에서 생성)."""
        dialog = Gtk.Dialog(
            title="단축키 안내",
            parent=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT
        )
        dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        dialog.set_default_size(560, 620)

        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)

        title = Gtk.Label(label="⌨️ Jetson Video Player 단축키 안내")
        title.get_style_context().add_class("section-title")
        box.pack_start(title, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(8)

        row = 0
        current = None
        for category, key, desc in help_rows():
            if category != current:
                current = category
                header = Gtk.Label(xalign=0)
                header.set_markup(f"<b>{GLib.markup_escape_text(category)}</b>")
                header.get_style_context().add_class("popover-title")
                header.set_margin_top(6 if row else 0)
                grid.attach(header, 0, row, 2, 1)
                row += 1
            k_lbl = Gtk.Label(label=key, xalign=0)
            k_lbl.get_style_context().add_class("primary")
            d_lbl = Gtk.Label(label=desc, xalign=0)
            d_lbl.set_line_wrap(True)
            grid.attach(k_lbl, 0, row, 1, 1)
            grid.attach(d_lbl, 1, row, 1, 1)
            row += 1

        scrolled.add(grid)
        box.pack_start(scrolled, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def show_context_menu(self, event):
        """비디오 영역 우클릭 시 빠른 조작을 위한 컨텍스트 메뉴를 띄웁니다."""
        menu = Gtk.Menu()

        play_label = "⏸ 일시정지 (Space)" if self.is_playing else "▶ 재생 (Space)"
        item_play = Gtk.MenuItem(label=play_label)
        item_play.connect("activate", lambda _w: self.toggle_play_pause())
        menu.append(item_play)

        item_prev = Gtk.MenuItem(label="⏮ 이전 영상 (P)")
        item_prev.connect("activate", lambda _w: self.play_prev_video())
        menu.append(item_prev)

        item_next = Gtk.MenuItem(label="⏭ 다음 영상 (N)")
        item_next.connect("activate", lambda _w: self.play_next_video())
        menu.append(item_next)

        menu.append(Gtk.SeparatorMenuItem())

        # 재생 속도 서브메뉴
        speed_menu_item = Gtk.MenuItem(label=f"⚡ 재생 속도 ({self.playback_rate:.2f}x)")
        speed_sub = Gtk.Menu()
        for rate in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
            r_item = Gtk.MenuItem(label=f"{rate}x")
            r_item.connect("activate", lambda _w, r=rate: self.set_playback_rate(r))
            speed_sub.append(r_item)
        speed_menu_item.set_submenu(speed_sub)
        menu.append(speed_menu_item)

        # 자막 메뉴
        sub_cnt = len(self.active_subtitle_indices) if self.subtitles_enabled else 0
        total_sub = len(self.available_subtitles)
        sub_menu_item = Gtk.MenuItem(label=f"💬 자막 ({sub_cnt}/{total_sub})")
        sub_sub = Gtk.Menu()
        toggle_sub = Gtk.MenuItem(label="자막 켜기/끄기 (S)")
        toggle_sub.connect("activate", lambda _w: self.toggle_subtitles())
        sub_sub.append(toggle_sub)
        pop_sub = Gtk.MenuItem(label="자막 설정 창 열기 (C)")
        pop_sub.connect("activate", lambda _w: self.show_subtitle_popover())
        sub_sub.append(pop_sub)
        sub_menu_item.set_submenu(sub_sub)
        menu.append(sub_menu_item)

        # 오디오 트랙 메뉴
        if self.n_audio_tracks > 1:
            audio_menu_item = Gtk.MenuItem(label=f"🎵 오디오 트랙 ({self.current_audio_track + 1}/{self.n_audio_tracks})")
            audio_sub = Gtk.Menu()
            for a_idx in range(self.n_audio_tracks):
                a_item = Gtk.MenuItem(label=f"오디오 트랙 {a_idx + 1}")
                a_item.connect("activate", lambda _w, idx=a_idx: self.set_audio_track(idx))
                audio_sub.append(a_item)
            audio_menu_item.set_submenu(audio_sub)
            menu.append(audio_menu_item)

        # 재생 모드 서브메뉴
        mode_names = {"all": "전체 반복", "one": "1곡 반복", "none": "순차 후 정지", "shuffle": "셔플 무작위"}
        mode_menu_item = Gtk.MenuItem(label=f"🔁 재생 모드: {mode_names.get(self.repeat_mode, self.repeat_mode)}")
        mode_sub = Gtk.Menu()
        for m_key, m_name in [("all", "전체 반복"), ("one", "1곡 반복"), ("none", "순차 후 정지"), ("shuffle", "셔플 무작위")]:
            m_item = Gtk.MenuItem(label=m_name)
            m_item.connect("activate", lambda _w, mk=m_key: self.set_repeat_mode(mk))
            mode_sub.append(m_item)
        mode_menu_item.set_submenu(mode_sub)
        menu.append(mode_menu_item)

        # A-B 구간 반복 서브메뉴
        ab_status = " (활성)" if self.is_ab_repeat_active else ""
        ab_menu_item = Gtk.MenuItem(label=f"🔁 구간 반복 (A-B){ab_status}")
        ab_sub = Gtk.Menu()
        ab_a = Gtk.MenuItem(label="A 지점 설정 (Shift+[)")
        ab_a.connect("activate", lambda _w: self.set_ab_repeat_a())
        ab_sub.append(ab_a)
        ab_b = Gtk.MenuItem(label="B 지점 설정 (Shift+])")
        ab_b.connect("activate", lambda _w: self.set_ab_repeat_b())
        ab_sub.append(ab_b)
        ab_clear = Gtk.MenuItem(label="구간 반복 해제 (\\)")
        ab_clear.connect("activate", lambda _w: self.clear_ab_repeat())
        ab_sub.append(ab_clear)
        ab_menu_item.set_submenu(ab_sub)
        menu.append(ab_menu_item)

        # 오디오/비디오 (AV) 싱크 서브메뉴
        av_sign = "+" if self.av_sync_offset_ms > 0 else ""
        av_menu_item = Gtk.MenuItem(label=f"🔊 AV 싱크 ({av_sign}{self.av_sync_offset_ms}ms)")
        av_sub = Gtk.Menu()
        av_m50 = Gtk.MenuItem(label="오디오 50ms 앞당김 (Shift+Z)")
        av_m50.connect("activate", lambda _w: self.adjust_av_sync(-50))
        av_sub.append(av_m50)
        av_p50 = Gtk.MenuItem(label="오디오 50ms 늦춤 (Shift+X)")
        av_p50.connect("activate", lambda _w: self.adjust_av_sync(50))
        av_sub.append(av_p50)
        av_rst = Gtk.MenuItem(label="AV 싱크 초기화 (Shift+C)")
        av_rst.connect("activate", lambda _w: self.reset_av_sync())
        av_sub.append(av_rst)
        av_menu_item.set_submenu(av_sub)
        menu.append(av_menu_item)

        menu.append(Gtk.SeparatorMenuItem())

        # 스크린샷 캡처
        item_snap = Gtk.MenuItem(label="📸 스크린샷 캡처 (Ctrl+S)")
        item_snap.connect("activate", lambda _w: self.capture_screenshot())
        menu.append(item_snap)

        # 북마크
        item_bm_add = Gtk.MenuItem(label="🔖 북마크 추가 (B)")
        item_bm_add.connect("activate", lambda _w: self.add_bookmark())
        menu.append(item_bm_add)

        item_bm_list = Gtk.MenuItem(label="📑 북마크 목록 (Ctrl+B)")
        item_bm_list.connect("activate", lambda _w: self.show_bookmarks_popover())
        menu.append(item_bm_list)

        # 스마트폰 웹 리모컨
        item_remote = Gtk.MenuItem(label="📱 스마트폰 웹 리모컨 안내...")
        item_remote.connect("activate", lambda _w: self.show_remote_popover(self.topbar))
        menu.append(item_remote)

        menu.append(Gtk.SeparatorMenuItem())

        # 항상 위 토글
        item_ontop = Gtk.CheckMenuItem(label="📌 항상 위에 표시 (T)")
        item_ontop.set_active(self.is_keep_above)
        item_ontop.connect("toggled", lambda _w: self.toggle_keep_above())
        menu.append(item_ontop)

        # 전체화면 토글
        item_fs = Gtk.MenuItem(label="⛶ 전체화면 (F)")
        item_fs.connect("activate", lambda _w: self.toggle_fullscreen())
        menu.append(item_fs)

        # 미디어 정보
        item_info = Gtk.MenuItem(label="ℹ️ 미디어 정보 (I)")
        item_info.connect("activate", lambda _w: self.toggle_hud())
        menu.append(item_info)

        # 단축키 안내
        item_help = Gtk.MenuItem(label="❓ 단축키 안내 (F1)")
        item_help.connect("activate", lambda _w: self.show_help_dialog())
        menu.append(item_help)

        menu.show_all()
        menu.popup_at_pointer(event)
