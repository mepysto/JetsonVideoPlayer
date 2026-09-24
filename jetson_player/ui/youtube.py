"""YouTube 다운로드/재생 UI와 로딩 오버레이"""
import time

from gi.repository import GLib, Gdk, Gtk

from ..youtube import extract_youtube_url, youtube_mgr


class YouTubeMixin:
    def show_yt_loading(self, title="YouTube 영상 준비 중...", status="⚡ 버퍼링 준비 중..."):
        """비디오 영역 상단에 YouTube 로딩 및 버퍼링 오버레이를 표시합니다."""
        if getattr(self, "placeholder_box", None):
            self.placeholder_box.hide()
        if getattr(self, "yt_loading_box", None):
            self.yt_loading_title.set_markup(f"<span font='13' weight='bold' color='#e9ff5b'>{GLib.markup_escape_text(title)}</span>")
            self.yt_loading_status.set_markup(f"<span font='11' color='#8f98a8'>{GLib.markup_escape_text(status)}</span>")
            self.yt_loading_progress.set_fraction(0.0)
            if getattr(self, "yt_spinner", None):
                self.yt_spinner.start()
            self.yt_loading_box.set_no_show_all(False)
            self.yt_loading_box.show_all()
            self.yt_loading_box.set_no_show_all(True)

    def update_yt_loading(self, pct, speed_str="", eta_str="", title=None):
        """YouTube 버퍼링 진행률, 속도 및 잔여 시간을 실시간 갱신합니다."""
        if getattr(self, "yt_loading_box", None) and self.yt_loading_box.get_visible():
            if title and title != "YouTube Video":
                self.yt_loading_title.set_markup(f"<span font='13' weight='bold' color='#e9ff5b'>{GLib.markup_escape_text(title)}</span>")
            speed_info = f" ({speed_str}, 남은시간 {eta_str})" if speed_str else ""
            self.yt_loading_status.set_markup(f"<span font='11' color='#8f98a8'>⚡ 초고속 버퍼링 {pct:.0f}%{speed_info}</span>")
            self.yt_loading_progress.set_fraction(max(0.0, min(1.0, pct / 100.0)))

    def hide_yt_loading(self):
        """YouTube 로딩 오버레이를 숨깁니다."""
        if getattr(self, "yt_loading_box", None):
            if getattr(self, "yt_spinner", None):
                self.yt_spinner.stop()
            self.yt_loading_box.hide()

    def _restore_empty_or_loading_state(self):
        self.hide_yt_loading()
        if not self.playlist and getattr(self, "placeholder_box", None):
            self.placeholder_box.set_no_show_all(False)
            self.placeholder_box.show_all()
            self.placeholder_box.set_no_show_all(True)
        return False

    def start_youtube_download(self, url, quality="best"):
        """유튜브 영상을 비동기로 다운로드하고 진행률을 표시하며, 완료 시 재생목록에 추가 및 자동 재생합니다."""
        norm_url = extract_youtube_url(url)
        if not norm_url:
            self.show_osd("⚠️ 올바른 유튜브 링크가 아닙니다.", duration_sec=2.0)
            return

        # 1. 이미 다운로드 보관 중인 영상이 있으면 0초 즉시 재생
        existing = youtube_mgr.find_existing_video(norm_url)
        if existing:
            print(f"⚡ [YouTube 다운로드] 이미 보관된 영상 발견: {existing}")
            self.show_osd("⚡ 이미 저장된 유튜브 영상입니다. 즉시 재생합니다!", duration_sec=2.0)
            if getattr(self, "placeholder_box", None):
                self.placeholder_box.hide()
            self.hide_yt_loading()
            if existing not in self.playlist:
                self.playlist.append(existing)
                self.populate_playlist_tree()
                self.refresh_playlist_ui()
                new_idx = len(self.playlist) - 1
                self.play_index_direct(new_idx)
            else:
                idx = self.playlist.index(existing)
                self.play_index_direct(idx)
            return

        q_desc = "최고 화질" if quality == "best" else quality
        if not self.playlist:
            self.show_yt_loading(title="YouTube 영상 다운로드 중...", status=f"⬇️ {q_desc} 다운로드 준비 중...")
        self.show_osd("⬇️ [유튜브] 다운로드 준비 중...", duration_sec=1.5)
        if getattr(self, "yt_btn", None):
            self.yt_btn.set_label("⏳ 다운로드 중...")
        print(f"⬇️ [YouTube 다운로드 시작] {norm_url} (품질: {quality})")

        last_osd_time = [0]

        def _on_progress(pct, speed_str, eta_str, title):
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label(f"⬇️ {pct:.0f}%")
            now = time.time()
            if now - last_osd_time[0] >= 0.8 or pct >= 99.0:
                last_osd_time[0] = now
                self.show_osd(f"⬇️ {pct:.0f}% ({speed_str}, 남은시간 {eta_str})", duration_sec=1.2)
            if not self.playlist or (getattr(self, "yt_loading_box", None) and self.yt_loading_box.get_visible()):
                self.update_yt_loading(pct, speed_str, eta_str, title)

        def _on_finish(final_filepath, title):
            print(f"🎉 [YouTube 다운로드 완료] {final_filepath}")
            self.hide_yt_loading()
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label("✅ 완료")
                GLib.timeout_add(2500, lambda: self.yt_btn.set_label("▶️ 유튜브") if getattr(self, "yt_btn", None) else False)
            self.show_osd(f"🎉 다운로드 완료: {title[:25]}", duration_sec=3.0)
            
            # 재생목록에 추가하고 사이드바 트리 갱신 및 즉시 하드웨어 가속 재생
            if final_filepath not in self.playlist:
                self.playlist.append(final_filepath)
                self.populate_playlist_tree()
                self.refresh_playlist_ui()
                new_idx = len(self.playlist) - 1
                self.play_index_direct(new_idx)
            else:
                idx = self.playlist.index(final_filepath)
                self.play_index_direct(idx)

        def _on_error(err):
            print(f"❌ [YouTube 다운로드 실패] {err}")
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label("❌ 실패")
                GLib.timeout_add(3000, lambda: self.yt_btn.set_label("▶️ 유튜브") if getattr(self, "yt_btn", None) else False)
            self.show_osd(f"❌ 다운로드 실패: {err[:40]}", duration_sec=4.0)
            if getattr(self, "yt_loading_box", None) and self.yt_loading_box.get_visible():
                self.yt_spinner.stop()
                self.yt_loading_title.set_markup("<span font='13' weight='bold' color='#ff6b6b'>다운로드 실패</span>")
                self.yt_loading_status.set_markup(f"<span font='11' color='#dce2ec'>{GLib.markup_escape_text(err[:50])}</span>")
                GLib.timeout_add(3500, self._restore_empty_or_loading_state)

        youtube_mgr.download_async(
            norm_url,
            quality=quality,
            on_progress=_on_progress,
            on_finish=_on_finish,
            on_error=_on_error
        )

    def start_youtube_stream(self, url, quality="best"):
        """유튜브 영상을 초고속 버퍼링 다운로드 후 Jetson HW 가속으로 끊김 없이 즉시 최고 화질로 재생합니다."""
        norm_url = extract_youtube_url(url)
        if not norm_url:
            self.show_osd("⚠️ 올바른 유튜브 링크가 아닙니다.", duration_sec=2.0)
            return

        # 1. 이미 다운로드되어 있는 영상인지 먼저 확인 (0.01초 즉시 재생)
        existing = youtube_mgr.find_existing_video(norm_url)
        if existing:
            print(f"⚡ [YouTube 즉시 재생] 이미 저장된 영상 발견: {existing}")
            self.show_osd("⚡ 보관된 유튜브 영상을 즉시 재생합니다!", duration_sec=2.0)
            if getattr(self, "placeholder_box", None):
                self.placeholder_box.hide()
            self.hide_yt_loading()
            if existing not in self.playlist:
                self.playlist.append(existing)
                self.populate_playlist_tree()
                self.refresh_playlist_ui()
                new_idx = len(self.playlist) - 1
                self.play_index_direct(new_idx)
            else:
                idx = self.playlist.index(existing)
                self.play_index_direct(idx)
            return

        # 2. 신규 영상 버퍼링 및 로딩 화면 활성화
        q_desc = "최고 화질" if quality == "best" else quality
        self.show_yt_loading(title="YouTube 영상 연결 중...", status=f"⚡ {q_desc} 초고속 버퍼링 준비 중...")
        self.show_osd(f"⚡ [유튜브] {q_desc} 빠른 버퍼링 후 즉시 재생합니다...", duration_sec=2.5)
        print(f"🎬 [YouTube 빠른 재생 버퍼링 시작] {norm_url} (품질: {quality})")
        if getattr(self, "yt_btn", None):
            self.yt_btn.set_label("⏳ 버퍼링...")

        last_osd_time = [0]

        def _on_progress(pct, speed_str, eta_str, title):
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label(f"⚡ {pct:.0f}%")
            now = time.time()
            if now - last_osd_time[0] >= 0.8 or pct >= 99.0:
                last_osd_time[0] = now
                self.show_osd(f"⚡ 버퍼링 {pct:.0f}% ({speed_str}, 남은시간 {eta_str})", duration_sec=1.2)
            self.update_yt_loading(pct, speed_str, eta_str, title)

        def _on_finish(final_filepath, title):
            print(f"▶️ [YouTube 쾌속 재생 시작] {final_filepath}")
            self.hide_yt_loading()
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label("✅ 재생 중")
                GLib.timeout_add(2500, lambda: self.yt_btn.set_label("▶️ 유튜브") if getattr(self, "yt_btn", None) else False)
            self.show_osd(f"▶️ 재생: {title[:25]}", duration_sec=3.0)
            
            if final_filepath not in self.playlist:
                self.playlist.append(final_filepath)
                self.populate_playlist_tree()
                self.refresh_playlist_ui()
                new_idx = len(self.playlist) - 1
                self.play_index_direct(new_idx)
            else:
                idx = self.playlist.index(final_filepath)
                self.play_index_direct(idx)

        def _on_error(err):
            print(f"❌ [YouTube 빠른 재생 실패] {err}")
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label("❌ 실패")
                GLib.timeout_add(3000, lambda: self.yt_btn.set_label("▶️ 유튜브") if getattr(self, "yt_btn", None) else False)
            self.show_osd(f"❌ 빠른 재생 실패: {err[:40]}", duration_sec=4.0)
            if getattr(self, "yt_loading_box", None):
                self.yt_spinner.stop()
                self.yt_loading_title.set_markup("<span font='13' weight='bold' color='#ff6b6b'>재생 실패</span>")
                self.yt_loading_status.set_markup(f"<span font='11' color='#dce2ec'>{GLib.markup_escape_text(err[:50])}</span>")
                GLib.timeout_add(3500, self._restore_empty_or_loading_state)

        # YouTube 직접 스트리밍 시 HTTP 403 차단 및 저화질 문제를 완벽 방지하기 위해 선택된 최고 화질로 고속 버퍼링 후 자동 재생 연결
        youtube_mgr.download_async(
            norm_url,
            quality=quality,
            on_progress=_on_progress,
            on_finish=_on_finish,
            on_error=_on_error
        )

    def show_youtube_popover(self, parent_widget=None):
        """유튜브 URL 입력, 화질 선택, 다운로드 및 스트리밍을 위한 팝오버 창을 표시합니다."""
        parent = parent_widget or getattr(self, "topbar", None) or self.play_button
        pop = Gtk.Popover(relative_to=parent)
        pop.set_position(Gtk.PositionType.BOTTOM)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        box.set_size_request(350, -1)

        title = Gtk.Label(label="▶️ 유튜브 영상 재생 & 다운로드", xalign=0)
        title.get_style_context().add_class("popover-title")
        box.pack_start(title, False, False, 0)

        # URL 입력창
        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("https://www.youtube.com/watch?v=...")
        url_entry.set_width_chars(32)

        # 클립보드에 유튜브 주소가 있으면 자동 채움
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip_text = clipboard.wait_for_text()
        if clip_text:
            yt_url = extract_youtube_url(clip_text)
            if yt_url:
                url_entry.set_text(yt_url)

        box.pack_start(url_entry, False, False, 2)

        # 화질 선택
        q_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        q_lbl = Gtk.Label(label="품질:")
        q_lbl.get_style_context().add_class("muted")
        q_combo = Gtk.ComboBoxText()
        q_combo.append("best", "최고 화질 (1080p Full HD / H.264 HW 가속)")
        q_combo.append("1080p", "1080p Full HD (H.264 NVDEC)")
        q_combo.append("720p", "720p HD (초고속)")
        q_combo.append("audio", "오디오만 (M4A)")
        q_combo.set_active_id("best")
        q_row.pack_start(q_lbl, False, False, 0)
        q_row.pack_start(q_combo, True, True, 0)
        box.pack_start(q_row, False, False, 2)

        # 액션 버튼 열
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        dl_btn = Gtk.Button(label="⬇️ 다운로드 & 재생")
        dl_btn.get_style_context().add_class("primary")
        dl_btn.set_tooltip_text("최고 화질로 다운로드하여 Jetson nvv4l2decoder HW 가속으로 완벽 재생 (오프라인 보관)")

        def on_dl_clicked(_b):
            target_url = url_entry.get_text().strip()
            if not target_url:
                self.show_osd("⚠️ 유튜브 링크를 입력하세요.", duration_sec=2.0)
                return
            q = q_combo.get_active_id() or "best"
            pop.popdown()
            self.start_youtube_download(target_url, quality=q)

        dl_btn.connect("clicked", on_dl_clicked)
        btn_box.pack_start(dl_btn, True, True, 0)

        stream_btn = Gtk.Button(label="⚡ 바로 재생")
        stream_btn.set_tooltip_text("최고 화질 초고속 버퍼링 후 즉시 HW 가속으로 끊김 없이 재생")

        def on_stream_clicked(_b):
            target_url = url_entry.get_text().strip()
            if not target_url:
                self.show_osd("⚠️ 유튜브 링크를 입력하세요.", duration_sec=2.0)
                return
            q = q_combo.get_active_id() or "best"
            pop.popdown()
            self.start_youtube_stream(target_url, quality=q)

        stream_btn.connect("clicked", on_stream_clicked)
        btn_box.pack_start(stream_btn, True, True, 0)

        url_entry.connect("activate", on_dl_clicked)

        box.pack_start(btn_box, False, False, 4)

        box.show_all()
        pop.add(box)
        pop.popup()
