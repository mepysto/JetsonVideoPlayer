"""대사 검색 (Ctrl+F): 재생목록 전체 자막에서 대사를 찾아 그 장면으로 이동합니다."""
import logging
import os
import threading

from gi.repository import GLib, Gdk, Gst, Gtk

from ..subtitles.search import DialogueIndex, normalize

log = logging.getLogger(__name__)

SEARCH_DEBOUNCE_MS = 150
MAX_RESULTS = 200


def _format_ms(ms):
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _highlight(text, query):
    """검색어 부분을 굵게 표시한 Pango 마크업 (대소문자 무시, 공백은 원문 그대로)"""
    one_line = " ".join(text.split())
    pos = one_line.casefold().find(normalize(query))
    if pos < 0:
        return GLib.markup_escape_text(one_line)
    end = pos + len(normalize(query))
    esc = GLib.markup_escape_text
    return f"{esc(one_line[:pos])}<b><span foreground='#e9ff5b'>{esc(one_line[pos:end])}</span></b>{esc(one_line[end:])}"


class DialogueSearchMixin:
    # ---- 색인 ----------------------------------------------------------------
    def refresh_dialogue_index(self, on_ready=None):
        """현재 재생목록으로 색인을 (백그라운드에서) 갱신합니다. 바뀐 자막만 다시 읽습니다."""
        if not hasattr(self, "dialogue_index"):
            self.dialogue_index = DialogueIndex()
        if on_ready:
            self._dialogue_index_waiters = getattr(self, "_dialogue_index_waiters", []) + [on_ready]
        if getattr(self, "_dialogue_index_thread", None):
            self._dialogue_index_again = True
            return
        videos = [p for p in self.playlist if not p.startswith(("http://", "https://"))]

        def work():
            try:
                self.dialogue_index.build(videos, cancelled=lambda: getattr(self, "is_destroyed", False))
            except Exception:
                log.warning("⚠️ 대사 색인 실패", exc_info=True)
            GLib.idle_add(self._on_dialogue_index_built)

        self._dialogue_index_again = False
        self._dialogue_index_thread = threading.Thread(target=work, daemon=True, name="dialogue-index")
        self._dialogue_index_thread.start()

    def _on_dialogue_index_built(self):
        self._dialogue_index_thread = None
        if getattr(self, "_dialogue_index_again", False):
            self.refresh_dialogue_index()
            return False
        waiters, self._dialogue_index_waiters = getattr(self, "_dialogue_index_waiters", []), []
        for cb in waiters:
            cb()
        return False

    def search_dialogue(self, query, limit=MAX_RESULTS):
        """[아무 스레드] 색인에서 대사 검색. 지금 보는 영상의 결과가 먼저 옵니다."""
        index = getattr(self, "dialogue_index", None)
        if index is None:
            return []
        current = self.playlist[self.current_index] if self.playlist and 0 <= self.current_index < len(self.playlist) else None
        return index.search(query, limit=limit, first_video=current)

    def jump_to_dialogue(self, video, start_ms):
        """대사 위치로 이동: 같은 영상이면 탐색, 다른 영상이면 그 위치부터 재생 (대사 0.5초 전부터)"""
        target_ns = max(0, start_ms - 500) * Gst.MSECOND
        current = self.playlist[self.current_index] if self.playlist and 0 <= self.current_index < len(self.playlist) else None
        if video == current and self.pipeline:
            self.seek_to(target_ns, "accurate")
            if not self.is_playing:
                self.toggle_play_pause()
        elif video in self.playlist:
            self.current_index = self.playlist.index(video)
            self.play_current_video(open_at_ns=target_ns)
            self.refresh_playlist_ui()
        else:
            self.show_osd("⚠️ 재생목록에 없는 영상입니다.")
            return
        self.show_osd(f"🔎 {os.path.basename(video)[:40]} · {_format_ms(start_ms)}")

    # ---- 검색 창 --------------------------------------------------------------
    def show_dialogue_search(self):
        if not self.playlist:
            self.show_osd("ℹ️ 재생목록이 비어 있습니다.")
            return
        dialog = getattr(self, "_search_dialog", None)
        if dialog is not None:
            dialog.present()
            self._search_entry.grab_focus()
            self.refresh_dialogue_index(self._run_dialogue_search)
            return

        dialog = Gtk.Window(title="대사 검색")
        dialog.set_transient_for(self)
        dialog.set_destroy_with_parent(True)
        dialog.set_default_size(620, 520)
        dialog.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.connect("destroy", lambda _w: setattr(self, "_search_dialog", None))
        dialog.connect("key-press-event", self._on_search_dialog_key)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        dialog.add(box)

        entry = Gtk.SearchEntry()
        entry.set_placeholder_text("대사 검색 (재생목록 전체 자막)")
        entry.connect("search-changed", lambda _e: self._schedule_dialogue_search())
        entry.connect("activate", lambda _e: self._activate_first_search_result())
        box.pack_start(entry, False, False, 0)

        status = Gtk.Label(xalign=0)
        status.get_style_context().add_class("muted")
        box.pack_start(status, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        results = Gtk.ListBox()
        results.set_selection_mode(Gtk.SelectionMode.BROWSE)
        results.set_activate_on_single_click(True)
        results.connect("row-activated", self._on_search_row_activated)
        scrolled.add(results)
        box.pack_start(scrolled, True, True, 0)

        self._search_dialog, self._search_entry = dialog, entry
        self._search_status, self._search_results = status, results
        dialog.show_all()
        status.set_text("🔎 자막 색인 중...")
        self.refresh_dialogue_index(self._run_dialogue_search)

    def _on_search_dialog_key(self, widget, event):
        name = Gdk.keyval_name(event.keyval)
        if name == "Escape":
            widget.destroy()
            return True
        if name == "Down" and self._search_entry.has_focus():
            row = self._search_results.get_row_at_index(0)
            if row:
                self._search_results.select_row(row)
                row.grab_focus()
            return True
        return False

    def _schedule_dialogue_search(self):
        if getattr(self, "_search_timer_id", None):
            GLib.source_remove(self._search_timer_id)
        self._search_timer_id = GLib.timeout_add(SEARCH_DEBOUNCE_MS, self._run_dialogue_search)

    def _run_dialogue_search(self):
        self._search_timer_id = None
        if getattr(self, "_search_dialog", None) is None:
            return False
        query = self._search_entry.get_text()
        for child in self._search_results.get_children():
            self._search_results.remove(child)
        index = getattr(self, "dialogue_index", None)
        n_lines = index.line_count() if index else 0
        if not normalize(query):
            self._search_status.set_text(f"영상 {len(self.playlist)}개 · 대사 {n_lines}줄 색인됨" if n_lines
                                         else "자막이 있는 영상이 없습니다.")
            return False
        hits = self.search_dialogue(query)
        more = "+" if len(hits) >= MAX_RESULTS else ""
        self._search_status.set_text(f"{len(hits)}{more}개 찾음" if hits else "찾은 대사가 없습니다.")
        current = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
        for hit in hits:
            row = Gtk.ListBoxRow()
            row.hit = hit
            label = Gtk.Label(xalign=0)
            label.set_line_wrap(True)
            name = GLib.markup_escape_text(os.path.basename(hit.video))
            here = " · <span foreground='#e9ff5b'>지금 영상</span>" if hit.video == current else ""
            label.set_markup(f"<small><b>{_format_ms(hit.start_ms)}</b>  {name}{here}</small>\n{_highlight(hit.text, query)}")
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_tooltip_text(hit.label)
            row.add(label)
            self._search_results.add(row)
        self._search_results.show_all()
        return False

    def _activate_first_search_result(self):
        row = self._search_results.get_row_at_index(0)
        if row:
            self._on_search_row_activated(self._search_results, row)

    def _on_search_row_activated(self, _listbox, row):
        hit = getattr(row, "hit", None)
        if hit:
            self.jump_to_dialogue(hit.video, hit.start_ms)

