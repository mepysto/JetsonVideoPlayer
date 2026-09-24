"""스마트폰 웹 리모컨: HTTP 서버, 상태 스냅샷, 원격 명령 처리"""
import http.server
import os
import threading

from gi.repository import GLib, Gdk, Gst, Gtk

from ..remote.server import JetsonWebRemoteHandler
from ..system import get_local_ip
from ..youtube import youtube_mgr


class RemoteMixin:
    def start_web_remote_server(self):
        """스마트폰 접속용 웹 리모컨 백그라운드 HTTP 서버를 구동합니다."""
        JetsonWebRemoteHandler.player = self
        local_ip = get_local_ip()
        for port in [8888, 8889, 8890, 8080]:
            try:
                server = http.server.ThreadingHTTPServer(("0.0.0.0", port), JetsonWebRemoteHandler)
                self.web_server = server
                self.web_port = port
                self.remote_url = f"http://{local_ip}:{port}"
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                self.web_server_thread = thread
                print(f"📱 [웹 리모컨 서버 활성화] 스마트폰 접속 주소: {self.remote_url}")
                break
            except Exception:
                continue

    def stop_web_remote_server(self):
        """웹 리모컨 서버를 안전하게 종료합니다."""
        if self.web_server:
            try:
                self.web_server.shutdown()
                self.web_server.server_close()
            except Exception:
                pass
            self.web_server = None

    def get_remote_status(self):
        """웹 리모컨 클라이언트에게 현재 재생 상태를 반환합니다.
        HTTP 스레드에서 호출되므로 메인 루프가 만든 스냅샷만 읽습니다 (GTK/GStreamer 직접 접근 금지)."""
        with self._remote_status_lock:
            status = dict(self._remote_status)
        status["yt_download"] = youtube_mgr.get_status()
        return status

    def _refresh_remote_status(self):
        """[메인 스레드] 웹 리모컨용 재생 상태 스냅샷을 주기적으로 갱신합니다."""
        if self.is_destroyed:
            return False
        try:
            status = self._build_remote_status()
        except Exception as e:
            print(f"⚠️ 리모컨 상태 갱신 실패: {e}")
            return True
        with self._remote_status_lock:
            self._remote_status = status
        return True

    def _build_remote_playlist_groups(self):
        """폴더별 그룹화된 재생목록을 생성합니다 (재생목록/현재 항목이 바뀔 때만 재계산)."""
        cache_key = (tuple(self.playlist), self.current_index, self.input_path)
        if self._remote_groups_cache is not None and self._remote_groups_cache[0] == cache_key:
            return self._remote_groups_cache[1]

        abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None
        groups_map = {}
        for idx, fpath in enumerate(self.playlist):
            if abs_root:
                dir_path = os.path.dirname(fpath)
                rel = os.path.relpath(dir_path, abs_root)
                folder_name = "📁 루트 폴더" if rel == "." else f"📁 {rel}"
            else:
                dir_name = os.path.basename(os.path.dirname(fpath))
                folder_name = f"📁 {dir_name}" if dir_name else "📁 동영상 목록"

            if folder_name not in groups_map:
                groups_map[folder_name] = []

            groups_map[folder_name].append({
                "index": idx,
                "name": os.path.basename(fpath),
                "active": idx == self.current_index
            })

        playlist_groups = []
        for folder_name, items in groups_map.items():
            playlist_groups.append({
                "folder": folder_name,
                "has_active": any(it["active"] for it in items),
                "count": len(items),
                "items": items
            })
        self._remote_groups_cache = (cache_key, playlist_groups)
        return playlist_groups

    def _build_remote_status(self):
        pos_sec = 0
        dur_sec = 0
        if self.pipeline:
            try:
                succ, p = self.pipeline.query_position(Gst.Format.TIME)
                if succ and p > 0:
                    pos_sec = p / Gst.SECOND
                succ, d = self.pipeline.query_duration(Gst.Format.TIME)
                if succ and d > 0:
                    dur_sec = d / Gst.SECOND
            except Exception:
                pass

        cur_title = ""
        if self.playlist and 0 <= self.current_index < len(self.playlist):
            cur_title = os.path.basename(self.playlist[self.current_index])

        playlist_groups = self._build_remote_playlist_groups()

        vol = int(self.volume_scale.get_value()) if getattr(self, "volume_scale", None) else 100

        return {
            "title": cur_title,
            "is_playing": self.is_playing,
            "position_sec": pos_sec,
            "duration_sec": dur_sec,
            "volume": vol,
            "is_muted": self.is_muted,
            "speed": self.playback_rate,
            "subtitles_enabled": self.subtitles_enabled,
            "is_fullscreen": self.is_fullscreen,
            "repeat_mode": self.repeat_mode,
            "playlist_groups": playlist_groups,
            "total_videos": len(self.playlist),
        }

    def handle_remote_command(self, action, val=None, index=None, delta=None, percent=None, url=None, quality=None):
        """웹 리모컨에서 수신한 명령을 GTK 메인 스레드에 위임하여 안전하게 실행합니다."""
        if action == "play_pause":
            GLib.idle_add(self.toggle_play_pause)
        elif action == "next":
            GLib.idle_add(self.play_next_video)
        elif action == "prev":
            GLib.idle_add(self.play_prev_video)
        elif action == "mute":
            GLib.idle_add(self.toggle_mute)
        elif action == "fullscreen":
            GLib.idle_add(self.toggle_fullscreen)
        elif action == "subtitles":
            GLib.idle_add(self.toggle_subtitles)
        elif action == "repeat":
            GLib.idle_add(self.cycle_repeat_mode)
        elif action == "screenshot":
            GLib.idle_add(self.capture_screenshot)
        elif action == "speed" and val is not None:
            try:
                s = float(val)
                GLib.idle_add(lambda: self.set_playback_rate(s))
            except Exception:
                pass
        elif action == "speed_step" and delta is not None:
            try:
                d = float(delta)
                GLib.idle_add(lambda: self.step_playback_rate(d))
            except Exception:
                pass
        elif action == "speed_reset":
            GLib.idle_add(self.reset_playback_rate)
        elif action == "seek" and delta is not None:
            try:
                d = float(delta) * Gst.SECOND
                GLib.idle_add(lambda: self.seek_relative(d))
            except Exception:
                pass
        elif action == "seek_to" and percent is not None:
            try:
                pct = float(percent)
                GLib.idle_add(lambda: self.seek_to_percent(pct))
            except Exception:
                pass
        elif action == "volume" and val is not None:
            try:
                v = float(val)
                GLib.idle_add(lambda: self.set_volume(v))
            except Exception:
                pass
        elif action == "play_index" and index is not None:
            try:
                idx = int(index)
                GLib.idle_add(lambda: self.play_index_direct(idx))
            except Exception:
                pass
        elif action == "ab_a":
            GLib.idle_add(self.set_ab_repeat_a)
        elif action == "ab_b":
            GLib.idle_add(self.set_ab_repeat_b)
        elif action == "ab_clear":
            GLib.idle_add(self.clear_ab_repeat)
        elif action == "bookmark_add":
            GLib.idle_add(self.add_bookmark)
        elif action == "audio_cycle":
            GLib.idle_add(self.cycle_audio_track)
        elif action == "yt_download" and url:
            GLib.idle_add(lambda: self.start_youtube_download(url, quality or "best"))
        elif action == "yt_stream" and url:
            GLib.idle_add(lambda: self.start_youtube_stream(url, quality=quality or "best"))
        elif action == "open_location":
            try:
                idx = int(index) if index is not None else None
            except (TypeError, ValueError):
                idx = None
            GLib.idle_add(lambda: self.open_selected_or_current_location_by_index(idx))

    def show_remote_popover(self, parent_btn):
        """스마트폰 접속을 위한 웹 리모컨 안내 팝오버를 표시합니다."""
        pop = Gtk.Popover(relative_to=parent_btn)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_border_width(12)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        title = Gtk.Label(label="📱 스마트폰 웹 리모컨", xalign=0)
        title.get_style_context().add_class("popover-title")
        box.pack_start(title, False, False, 0)

        desc = Gtk.Label(label="같은 Wi-Fi에 연결된 스마트폰 브라우저에서\n아래 주소로 접속하면 바로 조작할 수 있습니다:", xalign=0)
        desc.get_style_context().add_class("muted")
        box.pack_start(desc, False, False, 2)

        url_entry = Gtk.Entry()
        url_entry.set_text(self.remote_url or "http://127.0.0.1:8888")
        url_entry.set_editable(False)
        box.pack_start(url_entry, False, False, 4)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        copy_btn = Gtk.Button(label="📋 주소 복사")
        copy_btn.get_style_context().add_class("primary")
        def on_copy(_b):
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(self.remote_url, -1)
            self.show_osd("📋 리모컨 주소가 복사되었습니다!")
            pop.popdown()
        copy_btn.connect("clicked", on_copy)
        btn_row.pack_start(copy_btn, True, True, 0)

        box.pack_start(btn_row, False, False, 4)

        box.show_all()
        pop.add(box)
        pop.popup()
