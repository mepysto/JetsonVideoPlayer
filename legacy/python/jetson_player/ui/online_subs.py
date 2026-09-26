"""온라인 자막 찾기 (OpenSubtitles.com): 검색 → 골라서 받기 → 바로 켜기"""
import logging
import os
import threading

from gi.repository import GLib, Gtk

from ..settings import settings
from ..subtitles.opensubtitles import (OpenSubtitlesClient, OpenSubtitlesError, load_credentials, query_from_filename,
                                       save_credentials, subtitle_save_path)
from ..subtitles.parse import AI_SUBTITLE_CACHE_DIR, cached_ai_subtitle_stem

log = logging.getLogger(__name__)

CONSUMERS_URL = "https://www.opensubtitles.com/consumers"


def _unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem}.{n}{ext}"):
        n += 1
    return f"{stem}.{n}{ext}"


class OnlineSubtitlesMixin:
    def show_online_subtitle_search(self):
        video = self.playlist[self.current_index] if self.playlist and 0 <= self.current_index < len(self.playlist) else None
        if not video or video.startswith(("http://", "https://")) or not os.path.isfile(video):
            self.show_osd("ℹ️ 로컬 영상을 재생 중일 때 찾을 수 있습니다.")
            return
        creds = load_credentials()
        if not creds.get("api_key"):
            if not self.show_opensubtitles_account_dialog():
                return
            creds = load_credentials()
        self._open_search_dialog(video, creds)

    # ---- 계정 -----------------------------------------------------------------
    def show_opensubtitles_account_dialog(self):
        """API 키(필수)와 계정(선택)을 입력받아 저장합니다. 저장했으면 True"""
        creds = load_credentials()
        dialog = Gtk.Dialog(title="OpenSubtitles 설정", transient_for=self, modal=True, destroy_with_parent=True)
        dialog.add_buttons("취소", Gtk.ResponseType.CANCEL, "저장", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(14)
        info = Gtk.Label(xalign=0)
        info.set_line_wrap(True)
        info.set_markup("OpenSubtitles.com의 무료 <b>API 키</b>가 필요합니다.\n"
                        f"<a href='{CONSUMERS_URL}'>{CONSUMERS_URL}</a> 에서 발급받으세요.\n"
                        "<small>계정을 넣으면 하루 다운로드 한도가 늘어납니다 (선택). "
                        "정보는 ~/.config/jetson_video_player/opensubtitles.json 에 본인만 읽을 수 있게 저장됩니다.</small>")
        box.pack_start(info, False, False, 0)
        grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        entries = {}
        for row, (key, label, secret) in enumerate((("api_key", "API 키", False), ("username", "아이디 (선택)", False),
                                                     ("password", "비밀번호 (선택)", True))):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            entry = Gtk.Entry(text=creds.get(key, ""), hexpand=True)
            entry.set_visibility(not secret)
            entry.set_activates_default(True)
            grid.attach(entry, 1, row, 1, 1)
            entries[key] = entry
        box.pack_start(grid, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        values = {k: e.get_text().strip() for k, e in entries.items()}
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not values["api_key"]:
            return False
        try:
            save_credentials(values)
        except OSError as e:
            self.show_osd(f"❌ 저장 실패: {e}", duration_sec=3.0)
            return False
        return True

    # ---- 검색 창 ---------------------------------------------------------------
    def _open_search_dialog(self, video, creds):
        dialog = Gtk.Dialog(title="온라인 자막 찾기 (OpenSubtitles)", transient_for=self, destroy_with_parent=True)
        dialog.set_default_size(640, 460)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        row = Gtk.Box(spacing=6)
        query = Gtk.Entry(text=query_from_filename(video), hexpand=True)
        langs = Gtk.Entry(text=settings.get("opensubtitles_languages"), width_chars=8)
        langs.set_tooltip_text("언어 코드 (쉼표로 구분): ko, en, ja, zh-cn ...")
        search_btn = Gtk.Button(label="🔎 검색")
        account_btn = Gtk.Button(label="⚙️")
        account_btn.set_tooltip_text("API 키 / 계정 설정")
        for w, expand in ((query, True), (langs, False), (search_btn, False), (account_btn, False)):
            row.pack_start(w, expand, expand, 0)
        box.pack_start(row, False, False, 0)

        status = Gtk.Label(xalign=0)
        status.get_style_context().add_class("muted")
        box.pack_start(status, False, False, 0)

        scrolled = Gtk.ScrolledWindow(vexpand=True)
        results = Gtk.ListBox()
        results.set_activate_on_single_click(False)
        scrolled.add(results)
        box.pack_start(scrolled, True, True, 0)
        hint = Gtk.Label(label="두 번 누르면(또는 Enter) 받아서 바로 켭니다. ✓ = 이 영상 파일과 정확히 맞는 자막", xalign=0)
        hint.get_style_context().add_class("muted")
        box.pack_start(hint, False, False, 0)

        state = {"busy": False}

        def set_busy(text):
            state["busy"] = bool(text)
            status.set_text(text or "")
            search_btn.set_sensitive(not text)

        def show_results(found, error):
            set_busy(None)
            for child in results.get_children():
                results.remove(child)
            if error:
                status.set_text(f"❌ {error}")
                return
            status.set_text(f"{len(found)}개 찾음" if found else "찾은 자막이 없습니다. 검색어를 바꿔 보세요.")
            for r in found:
                item = Gtk.ListBoxRow()
                item.result = r
                label = Gtk.Label(xalign=0)
                label.set_line_wrap(True)
                mark = "✓ " if r.hash_match else ""
                label.set_markup(f"<b>{mark}[{GLib.markup_escape_text(r.language)}]</b> "
                                 f"{GLib.markup_escape_text(r.release or r.file_name)}\n"
                                 f"<small>{GLib.markup_escape_text(r.title)} · 다운로드 {r.downloads:,}회</small>")
                label.set_margin_top(4)
                label.set_margin_bottom(4)
                item.add(label)
                results.add(item)
            results.show_all()

        def client():
            c = load_credentials()
            return OpenSubtitlesClient(c.get("api_key"), c.get("username"), c.get("password"))

        def do_search(*_args):
            if state["busy"]:
                return
            languages = tuple(x.strip().lower() for x in langs.get_text().split(",") if x.strip()) or ("ko", "en")
            settings.set("opensubtitles_languages", ",".join(languages))
            text = query.get_text().strip()
            set_busy("🔎 검색 중...")

            def work():
                try:
                    found, error = client().search(video, languages, query=text or None), None
                except OpenSubtitlesError as e:
                    found, error = [], str(e)
                GLib.idle_add(lambda: (show_results(found, error), False)[1])

            threading.Thread(target=work, daemon=True, name="opensubtitles").start()

        def do_download(_listbox, item):
            r = getattr(item, "result", None)
            if r is None or state["busy"]:
                return
            set_busy(f"⬇️ 받는 중: {r.release or r.file_name}")

            def work():
                try:
                    content, error = client().download(r.file_id), None
                except OpenSubtitlesError as e:
                    content, error = None, str(e)
                GLib.idle_add(lambda: (self._on_online_subtitle_downloaded(video, r, content, error, dialog, set_busy),
                                       False)[1])

            threading.Thread(target=work, daemon=True, name="opensubtitles").start()

        search_btn.connect("clicked", do_search)
        query.connect("activate", do_search)
        results.connect("row-activated", do_download)
        account_btn.connect("clicked", lambda _b: self.show_opensubtitles_account_dialog())
        dialog.connect("response", lambda d, _r: d.destroy())
        dialog.show_all()
        if creds.get("api_key"):
            do_search()

    def _on_online_subtitle_downloaded(self, video, result, content, error, dialog, set_busy):
        set_busy(None)
        if error or not content:
            self.show_osd(f"❌ 자막 받기 실패: {(error or '빈 파일')[:60]}", duration_sec=4.0)
            return
        path = subtitle_save_path(video, result.language, result.file_name)
        if not os.access(os.path.dirname(path) or ".", os.W_OK):
            # 영상 폴더에 쓸 수 없으면 캐시 폴더에 (다음 재생에서도 자동으로 불러옴)
            os.makedirs(AI_SUBTITLE_CACHE_DIR, exist_ok=True)
            path = os.path.join(AI_SUBTITLE_CACHE_DIR, cached_ai_subtitle_stem(video) + path[len(os.path.splitext(video)[0]):])
        path = _unique_path(path)
        try:
            with open(path, "wb") as f:
                f.write(content)
        except OSError as e:
            self.show_osd(f"❌ 저장 실패: {e}", duration_sec=4.0)
            return
        log.info(f"🔎 [온라인 자막] {result.release or result.file_name} → {path}")
        current = self.playlist[self.current_index] if self.playlist else None
        if current == video and self.add_external_subtitle(path):
            dialog.destroy()
