"""재생목록 폴더 감시: 영상이 추가·삭제되면 재생을 멈추지 않고 재생목록을 갱신합니다 (F5: 수동 새로고침)."""
import logging
import os
import threading

from gi.repository import Gio, GLib

from ..library import VIDEO_EXTS, merge_rescanned, prefer_h265_versions, scan_video_files, sort_video_paths
from ..network import is_gvfs_path
from ..settings import settings

log = logging.getLogger(__name__)

MAX_WATCHED_DIRS = 300       # 넘으면 주기적 재검사로 대체 (inotify 감시 수 한도 보호)
RESCAN_DEBOUNCE_MS = 2000    # 복사 중인 파일은 변경 알림이 계속 오므로, 조용해진 뒤 한 번만 다시 읽음
POLL_INTERVAL_SEC = 60       # 네트워크 폴더 등 감시할 수 없는 경우


def _watched_dirs(root, limit):
    dirs = []
    for current, subdirs, _files in os.walk(root, followlinks=True):
        subdirs[:] = sorted(d for d in subdirs if d != "unsupported_originals" and not d.startswith("."))
        dirs.append(current)
        if len(dirs) > limit:
            return None
    return dirs


class FolderWatchMixin:
    def start_folder_watch(self):
        """현재 재생목록 폴더(input_path)를 감시합니다. 폴더가 아니면(단일 파일·파일 목록) 감시하지 않습니다."""
        self.stop_folder_watch()
        root = self.input_path
        if not self._playlist_is_folder():
            return
        dirs = None if is_gvfs_path(root) else _watched_dirs(root, MAX_WATCHED_DIRS)
        if dirs is None:
            # 네트워크 폴더는 변경 알림이 오지 않고, 하위 폴더가 아주 많으면 감시 수 한도에 걸립니다.
            self._watch_poll_id = GLib.timeout_add_seconds(POLL_INTERVAL_SEC, self._on_watch_poll)
            log.debug(f"📂 폴더 감시: {POLL_INTERVAL_SEC}초마다 다시 읽기 ({root})")
            return
        monitors = []
        for d in dirs:
            try:
                mon = Gio.File.new_for_path(d).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            except GLib.Error as e:
                log.debug(f"폴더 감시 실패 ({d}): {e.message}")
                continue
            mon.connect("changed", self._on_watched_dir_changed)
            monitors.append(mon)
        self._folder_monitors = monitors
        log.debug(f"📂 폴더 감시: {len(monitors)}개 폴더 ({root})")

    def _playlist_is_folder(self):
        """폴더를 열어 만든 재생목록인지 (단일 파일·직접 고른 파일 목록·M3U는 아님)"""
        root = self.input_path
        return bool(root) and os.path.isdir(root) and not self.is_single_file_mode \
            and not getattr(self, "playlist_from_files", False)

    def stop_folder_watch(self):
        for mon in getattr(self, "_folder_monitors", []):
            mon.cancel()
        self._folder_monitors = []
        for name in ("_watch_poll_id", "_rescan_timer_id"):
            timer_id = getattr(self, name, None)
            if timer_id:
                GLib.source_remove(timer_id)
            setattr(self, name, None)

    def _on_watched_dir_changed(self, _monitor, gfile, other, event):
        relevant = (Gio.FileMonitorEvent.CREATED, Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_IN,
                    Gio.FileMonitorEvent.MOVED_OUT, Gio.FileMonitorEvent.RENAMED, Gio.FileMonitorEvent.CHANGED,
                    Gio.FileMonitorEvent.CHANGES_DONE_HINT)
        if event not in relevant:
            return
        names = [f.get_basename() or "" for f in (gfile, other) if f is not None]
        is_video = any(os.path.splitext(n)[1].lower() in VIDEO_EXTS for n in names)
        is_dir_change = event != Gio.FileMonitorEvent.CHANGED and any("." not in n for n in names)
        if is_video or is_dir_change:
            self._schedule_rescan()

    def _schedule_rescan(self):
        if getattr(self, "_rescan_timer_id", None):
            GLib.source_remove(self._rescan_timer_id)
        self._rescan_timer_id = GLib.timeout_add(RESCAN_DEBOUNCE_MS, self._on_rescan_timer)

    def _on_rescan_timer(self):
        self._rescan_timer_id = None
        self.rescan_playlist(quiet=True)
        return False

    def _on_watch_poll(self):
        self.rescan_playlist(quiet=True)
        return True

    def rescan_playlist(self, quiet=False):
        """재생목록 폴더를 다시 읽어 추가·삭제된 영상을 반영합니다 (재생은 계속됩니다)."""
        root = self.input_path
        if not self._playlist_is_folder():
            if not quiet:
                self.show_osd("ℹ️ 폴더로 연 재생목록만 새로고침할 수 있습니다.")
            return
        if getattr(self, "_rescan_running", False):
            return
        self._rescan_running = True

        def work():
            try:
                scanned = prefer_h265_versions(scan_video_files(root))
            except OSError as e:
                log.warning(f"⚠️ 재생목록 새로고침 실패 ({root}): {e}")
                scanned = None
            GLib.idle_add(self._apply_rescan, root, scanned, quiet)

        threading.Thread(target=work, daemon=True, name="playlist-rescan").start()

    def _apply_rescan(self, root, scanned, quiet):
        self._rescan_running = False
        if scanned is None or root != self.input_path:
            return False
        current = self.playlist[self.current_index] if 0 <= self.current_index < len(self.playlist) else None
        new, added, removed = merge_rescanned(self.playlist, root, scanned, current)
        if not added and not removed:
            if not quiet:
                self.show_osd("🔄 재생목록이 최신 상태입니다.")
            return False
        self.playlist = sort_video_paths(new, settings.get("playlist_sort"))
        if current in self.playlist:
            self.current_index = self.playlist.index(current)
        self.play_queue = [p for p in self.play_queue if p in self.playlist]
        self.populate_playlist_tree()
        self.refresh_playlist_ui()
        parts = ([f"+{len(added)}"] if added else []) + ([f"-{len(removed)}"] if removed else [])
        self.show_osd(f"🔄 재생목록 갱신 ({' / '.join(parts)}): 총 {len(self.playlist)}개", duration_sec=2.5)
        log.info(f"🔄 [재생목록 갱신] 추가 {len(added)}, 제거 {len(removed)} → {len(self.playlist)}개")
        if any(os.path.isdir(os.path.dirname(p)) for p in added):
            # 새 하위 폴더가 생겼을 수 있으므로 감시 대상을 다시 잡습니다.
            if not is_gvfs_path(root):
                self.start_folder_watch()
        return False
