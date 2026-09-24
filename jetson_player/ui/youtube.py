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
            self.yt_loading_status.set_markup(f"<span font='11' color='#8f98a8'>⬇️ 받는 중 {pct:.0f}%{speed_info}</span>")
            self.yt_loading_progress.set_fraction(max(0.0, min(1.0, pct / 100.0)))

    def hide_yt_loading(self):
        """YouTube 로딩 오버레이를 숨깁니다."""
        if getattr(self, "yt_loading_box", None):
            if getattr(self, "yt_spinner", None):
                self.yt_spinner.stop()
            self.yt_loading_box.hide()

    def _restore_empty_or_loading_state(self):
        self.hide_yt_loading()
        if not self.playlist:
            self.show_placeholder()
        return False

    def _add_and_play_youtube_file(self, path, play_now=True):
        """다운로드된 파일을 재생목록에 넣고, play_now면 즉시 재생 / 아니면 "다음에 재생" 대기열에 넣습니다."""
        if getattr(self, "placeholder_box", None):
            self.placeholder_box.hide()
        if path not in self.playlist:
            self.playlist.append(path)
            self.populate_playlist_tree()
            self.refresh_playlist_ui()
        if play_now:
            self.play_index_direct(self.playlist.index(path))
        else:
            self.queue_next(path)

    def _reset_yt_button_later(self, delay_ms):
        def reset():
            if getattr(self, "yt_btn", None) and not youtube_mgr.get_status()["active"]:
                self.yt_btn.set_label("▶️ 유튜브")
            return False
        GLib.timeout_add(delay_ms, reset)

    def start_youtube(self, url, quality="best"):
        """YouTube 영상을 H.264 최고 화질로 받아 Jetson HW 가속으로 재생합니다.

        이미 받은 영상은 즉시 재생하고, 다른 다운로드가 진행 중이면 대기열에 넣었다가
        완료되면 "다음에 재생" 대기열에 추가합니다 (보던 영상을 끊지 않음).
        """
        norm_url = extract_youtube_url(url)
        if not norm_url:
            self.show_osd("⚠️ 올바른 유튜브 링크가 아닙니다.", duration_sec=2.0)
            return

        existing = youtube_mgr.find_existing_video(norm_url)
        if existing:
            print(f"⚡ [YouTube] 이미 받은 영상을 바로 재생합니다: {existing}")
            self.show_osd("⚡ 이미 받은 유튜브 영상입니다. 바로 재생합니다!", duration_sec=2.0)
            self.hide_yt_loading()
            self._add_and_play_youtube_file(existing)
            return

        # 재생 중인 영상이 없을 때만 전체 로딩 화면을 띄우고, 완료 시 바로 재생합니다.
        nothing_playing = not self.playlist or self.pipeline is None
        q_desc = {"best": "최고 화질", "audio": "오디오"}.get(quality, quality)
        last_osd_time = [0]

        def _on_progress(pct, speed_str, eta_str, title):
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label(f"⬇️ {pct:.0f}%")
            now = time.time()
            if now - last_osd_time[0] >= 0.8 or pct >= 99.0:
                last_osd_time[0] = now
                if not nothing_playing:
                    self.show_osd(f"⬇️ {pct:.0f}% ({speed_str}, 남은시간 {eta_str})", duration_sec=1.2)
            self.update_yt_loading(pct, speed_str, eta_str, title)

        def _on_finish(final_filepath, title):
            print(f"🎉 [YouTube 다운로드 완료] {final_filepath}")
            self.hide_yt_loading()
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label("✅ 완료")
                self._reset_yt_button_later(2500)
            play_now = nothing_playing or self.pipeline is None
            if play_now:
                self.show_osd(f"▶️ 재생: {title[:30]}", duration_sec=3.0)
            else:
                self.show_osd(f"🎉 다운로드 완료 → 다음에 재생: {title[:25]}", duration_sec=3.5)
            self._add_and_play_youtube_file(final_filepath, play_now=play_now)

        def _on_error(err):
            cancelled = err == youtube_mgr.CANCELLED_MESSAGE
            print(f"{'⏹' if cancelled else '❌'} [YouTube] {err}")
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label("⏹ 취소됨" if cancelled else "❌ 실패")
                self._reset_yt_button_later(3000)
            self.show_osd("⏹ 다운로드를 취소했습니다." if cancelled else f"❌ 다운로드 실패: {err[:40]}", duration_sec=3.0)
            if getattr(self, "yt_loading_box", None) and self.yt_loading_box.get_visible():
                self.yt_spinner.stop()
                head = "다운로드 취소" if cancelled else "다운로드 실패"
                self.yt_loading_title.set_markup(f"<span font='13' weight='bold' color='#ff6b6b'>{head}</span>")
                self.yt_loading_status.set_markup(f"<span font='11' color='#dce2ec'>{GLib.markup_escape_text(err[:60])}</span>")
                GLib.timeout_add(2500 if cancelled else 3500, self._restore_empty_or_loading_state)

        result, position = youtube_mgr.download_async(
            norm_url, quality=quality, on_progress=_on_progress, on_finish=_on_finish, on_error=_on_error
        )
        if result == "started":
            print(f"⬇️ [YouTube 다운로드 시작] {norm_url} (품질: {quality})")
            if nothing_playing:
                self.show_yt_loading(title="YouTube 영상 받는 중...", status=f"⬇️ {q_desc} 다운로드 준비 중...")
            else:
                self.show_osd(f"⬇️ [유튜브] {q_desc} 다운로드를 시작합니다.", duration_sec=1.5)
            if getattr(self, "yt_btn", None):
                self.yt_btn.set_label("⏳ 준비 중...")
        elif result == "queued":
            nothing_playing = False  # 대기열 작업은 완료 후 "다음에 재생"으로 추가
            self.show_osd(f"🕒 다운로드 대기열 {position}번째로 추가했습니다.", duration_sec=2.5)
        elif result == "downloading":
            self.show_osd("⬇️ 이미 받고 있는 영상입니다.", duration_sec=2.0)

    # 원격 리모컨/이전 코드 호환: 두 동작 모두 "받아서 재생"입니다.
    def start_youtube_download(self, url, quality="best"):
        self.start_youtube(url, quality)

    def start_youtube_stream(self, url, quality="best"):
        self.start_youtube(url, quality)

    def _build_youtube_downloads_section(self, pop):
        """팝오버 하단: 진행 중인 다운로드(취소)와 대기열(삭제) 목록"""
        status = youtube_mgr.get_status()
        if not status["active"] and not status["queue"]:
            return None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(Gtk.Separator(), False, False, 2)
        if status["active"]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lbl = Gtk.Label(label=f"⬇️ {status['percent']:.0f}%  {status['title'][:34]}", xalign=0)
            lbl.set_ellipsize(3)
            row.pack_start(lbl, True, True, 0)
            cancel = Gtk.Button(label="취소")
            cancel.get_style_context().add_class("tree-tool-btn")
            cancel.connect("clicked", lambda _b: (youtube_mgr.cancel_current(), pop.popdown()))
            row.pack_start(cancel, False, False, 0)
            box.pack_start(row, False, False, 0)
        for i, job in enumerate(status["queue"], 1):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lbl = Gtk.Label(label=f"🕒 {i}. {job['url'].split('v=')[-1]} ({job['quality']})", xalign=0)
            lbl.get_style_context().add_class("muted")
            row.pack_start(lbl, True, True, 0)
            rm = Gtk.Button(label="✕")
            rm.get_style_context().add_class("tree-tool-btn")
            rm.connect("clicked", lambda _b, u=job["url"]: (youtube_mgr.cancel_pending(u), pop.popdown()))
            row.pack_start(rm, False, False, 0)
            box.pack_start(row, False, False, 0)
        return box

    def show_youtube_popover(self, parent_widget=None):
        """유튜브 URL 입력, 화질 선택, 다운로드 상태/대기열을 보여주는 팝오버를 표시합니다."""
        parent = parent_widget or getattr(self, "topbar", None) or self.play_button
        pop = Gtk.Popover(relative_to=parent)
        pop.set_position(Gtk.PositionType.BOTTOM)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        box.set_size_request(350, -1)

        title = Gtk.Label(label="▶️ 유튜브 영상 받아서 재생", xalign=0)
        title.get_style_context().add_class("popover-title")
        box.pack_start(title, False, False, 0)

        hint = Gtk.Label(label="H.264로 받아 ~/Videos/YouTube 에 보관하고 HW 가속으로 재생합니다.", xalign=0)
        hint.get_style_context().add_class("muted")
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)

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

        q_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        q_lbl = Gtk.Label(label="품질:")
        q_lbl.get_style_context().add_class("muted")
        q_combo = Gtk.ComboBoxText()
        q_combo.append("best", "최고 화질 (H.264 HW 가속)")
        q_combo.append("1080p", "1080p Full HD (H.264)")
        q_combo.append("720p", "720p HD (빠른 다운로드)")
        q_combo.append("audio", "오디오만 (M4A)")
        q_combo.set_active_id("best")
        q_row.pack_start(q_lbl, False, False, 0)
        q_row.pack_start(q_combo, True, True, 0)
        box.pack_start(q_row, False, False, 2)

        go_btn = Gtk.Button(label="⬇️ 받아서 재생")
        go_btn.get_style_context().add_class("primary")
        go_btn.set_tooltip_text("다른 영상을 받는 중이면 대기열에 추가되고, 완료 후 '다음에 재생'으로 들어갑니다.")

        def on_go(_b):
            target_url = url_entry.get_text().strip()
            if not target_url:
                self.show_osd("⚠️ 유튜브 링크를 입력하세요.", duration_sec=2.0)
                return
            pop.popdown()
            self.start_youtube(target_url, quality=q_combo.get_active_id() or "best")

        go_btn.connect("clicked", on_go)
        url_entry.connect("activate", on_go)
        box.pack_start(go_btn, False, False, 4)

        downloads = self._build_youtube_downloads_section(pop)
        if downloads:
            box.pack_start(downloads, False, False, 0)

        box.show_all()
        pop.add(box)
        pop.popup()
