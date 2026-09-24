"""스마트폰 웹 리모컨: HTTP 서버, PIN/QR 접속, 상태 방송(SSE), 원격 명령 처리"""
import http.server
import os
import threading

from gi.repository import GLib, Gdk, Gst, Gtk

from ..ai.whisper import whisper_available
from ..media.thumbnails import load_thumbnail_index, thumbnail_cache_dir
from ..remote.auth import RemoteAuth, default_token_file, generate_pin
from ..remote.events import EventBroker
from ..remote.server import JetsonWebRemoteHandler
from ..settings import settings
from ..storage import bookmark_cache, resume_cache
from ..system import get_local_ip
from ..vendor.qrcodegen import QrCode
from ..youtube import youtube_mgr


def _to_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class RemoteMixin:
    # ---- 서버 -----------------------------------------------------------
    def start_web_remote_server(self):
        """스마트폰 접속용 웹 리모컨 백그라운드 HTTP 서버를 구동합니다."""
        pin = settings.get("remote_pin")
        if not (isinstance(pin, str) and len(pin) == 4 and pin.isdigit()):
            pin = generate_pin()
            settings.set("remote_pin", pin)
            settings.save()
        self.remote_auth = RemoteAuth(pin, default_token_file())
        self.remote_broker = EventBroker()
        JetsonWebRemoteHandler.player = self
        JetsonWebRemoteHandler.auth = self.remote_auth
        JetsonWebRemoteHandler.broker = self.remote_broker

        local_ip = get_local_ip()
        for port in [8888, 8889, 8890, 8080]:
            try:
                server = http.server.ThreadingHTTPServer(("0.0.0.0", port), JetsonWebRemoteHandler)
                server.daemon_threads = True   # SSE 연결이 남아 있어도 종료를 막지 않음
                self.web_server = server
                self.web_port = port
                self.remote_url = f"http://{local_ip}:{port}"
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                self.web_server_thread = thread
                print(f"📱 [웹 리모컨 서버 활성화] 스마트폰 접속 주소: {self.remote_url}  (PIN {pin})")
                break
            except Exception:
                continue

    def stop_web_remote_server(self):
        """웹 리모컨 서버를 안전하게 종료합니다."""
        if getattr(self, "remote_broker", None):
            self.remote_broker.close()
        if self.web_server:
            try:
                self.web_server.shutdown()
                self.web_server.server_close()
            except Exception:
                pass
            self.web_server = None

    def remote_login_url(self):
        return f"{self.remote_url}/?pin={self.remote_auth.pin}" if getattr(self, "remote_auth", None) else self.remote_url

    def regenerate_remote_pin(self):
        """새 PIN을 만들고 기존에 연결된 기기를 모두 로그아웃시킵니다."""
        pin = generate_pin()
        settings.set("remote_pin", pin)
        settings.save()
        self.remote_auth.reset(pin)
        self.show_osd(f"🔐 새 리모컨 PIN: {pin} (기존 연결 해제)", duration_sec=3.0)

    # ---- 상태 스냅샷 / 방송 (메인 스레드) ----------------------------------------
    def get_remote_status(self):
        """[HTTP 스레드] 메인 루프가 만든 스냅샷만 읽습니다 (GTK/GStreamer 직접 접근 금지)."""
        with self._remote_status_lock:
            status = dict(self._remote_status)
        status["yt_download"] = youtube_mgr.get_status()
        return status

    def _refresh_remote_status(self):
        """[메인 스레드] 상태 스냅샷을 갱신하고 변경분을 SSE로 방송합니다 (500ms 주기)."""
        if self.is_destroyed:
            return False
        try:
            status = self._build_remote_status()
            groups = self._build_remote_playlist_groups()
            thumbs = self._remote_thumbs_payload()
        except Exception as e:
            print(f"⚠️ 리모컨 상태 갱신 실패: {e}")
            return True
        status["yt_download"] = youtube_mgr.get_status()
        with self._remote_status_lock:
            self._remote_status = dict(status, playlist_groups=groups)
            self._remote_thumb_files = (thumbs, list((getattr(self, "thumb_index", None) or {}).get("files", [])),
                                        (getattr(self, "thumb_index", None) or {}).get("dir"))
        if getattr(self, "mpris", None):
            try:
                self.mpris.update()
            except Exception as e:
                print(f"⚠️ MPRIS 갱신 실패: {e}")
        broker = getattr(self, "remote_broker", None)
        if broker:
            broker.publish("status", status)
            broker.publish("playlist", groups)
            broker.publish("thumbs", thumbs)
        return True

    def _remote_thumbs_payload(self):
        index = getattr(self, "thumb_index", None) or {}
        positions = [round(p / Gst.SECOND, 2) for p in index.get("positions", [])]
        return {"positions": positions, "video": self.current_index}

    def remote_thumbnail_path(self, i):
        """[HTTP 스레드] 현재 영상의 i번째 썸네일 파일 경로"""
        with self._remote_status_lock:
            _payload, files, folder = getattr(self, "_remote_thumb_files", ({}, [], None))
        if folder and i is not None and 0 <= i < len(files):
            return os.path.join(folder, files[i])
        return None

    def remote_playlist_thumbnail_path(self, playlist_index):
        """[HTTP 스레드] 재생목록 항목의 대표 썸네일 (캐시가 있을 때만)"""
        with self._remote_status_lock:
            paths = self._remote_playlist_paths
        if playlist_index is None or not (0 <= playlist_index < len(paths)):
            return None
        index = load_thumbnail_index(paths[playlist_index])
        if not index or not index.get("files"):
            return None
        return os.path.join(index["dir"], index["files"][min(len(index["files"]) - 1, len(index["files"]) // 5)])

    def _build_remote_playlist_groups(self):
        """폴더별 그룹화된 재생목록 (재생목록/현재 항목이 바뀔 때만 재계산)"""
        cache_key = (tuple(self.playlist), self.current_index, self.input_path)
        if self._remote_groups_cache is not None and self._remote_groups_cache[0] == cache_key:
            return self._remote_groups_cache[1]

        abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None
        groups_map = {}
        for idx, fpath in enumerate(self.playlist):
            if abs_root:
                rel = os.path.relpath(os.path.dirname(fpath), abs_root)
                folder_name = "📁 루트 폴더" if rel == "." else f"📁 {rel}"
            else:
                dir_name = os.path.basename(os.path.dirname(fpath))
                folder_name = f"📁 {dir_name}" if dir_name else "📁 동영상 목록"
            has_thumb = os.path.exists(os.path.join(thumbnail_cache_dir(fpath), "index.json"))
            groups_map.setdefault(folder_name, []).append({
                "index": idx,
                "name": os.path.basename(fpath),
                "active": idx == self.current_index,
                "watched": resume_cache.get_progress(fpath)[1],
                "thumb": os.path.basename(thumbnail_cache_dir(fpath))[:8] if has_thumb else "",
            })

        playlist_groups = [
            {"folder": name, "has_active": any(it["active"] for it in items), "count": len(items), "items": items}
            for name, items in groups_map.items()
        ]
        self._remote_groups_cache = (cache_key, playlist_groups)
        with self._remote_status_lock:
            self._remote_playlist_paths = list(self.playlist)
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

        has_current = bool(self.playlist) and 0 <= self.current_index < len(self.playlist)
        cur_path = self.playlist[self.current_index] if has_current else None
        vol = int(self.volume_scale.get_value()) if getattr(self, "volume_scale", None) else 100
        ai_job = getattr(self, "ai_job", None)
        ai_status = getattr(self, "ai_status", None)
        chapter = self.chapter_title_at(int(pos_sec * Gst.SECOND)) if self.chapters else None

        return {
            "title": os.path.basename(cur_path) if cur_path else "",
            "is_playing": self.is_playing,
            "position_sec": round(pos_sec, 2),
            "duration_sec": round(dur_sec, 2),
            "volume": vol,
            "is_muted": self.is_muted,
            "speed": self.playback_rate,
            "subtitles_enabled": self.subtitles_enabled,
            "subtitle_offset_ms": self.subtitle_offset_ms,
            "subtitle_tracks": [
                {"index": i, "label": sub["label"], "color": sub["color"],
                 "active": self.subtitles_enabled and i in self.active_subtitle_indices}
                for i, sub in enumerate(self.available_subtitles)
            ],
            "embedded_subtitles": self.n_embedded_text,
            "is_fullscreen": self.is_fullscreen,
            "repeat_mode": self.repeat_mode,
            "total_videos": len(self.playlist),
            "current_index": self.current_index,
            "chapter": chapter,
            "chapters": [{"sec": round(p / Gst.SECOND, 2), "title": t} for p, t in self.chapters],
            "bookmarks": [{"sec": round(b.get("position_ns", 0) / Gst.SECOND, 2), "label": b.get("label", "")}
                          for b in (bookmark_cache.get(cur_path) if cur_path else [])],
            "ab": {"a": self.ab_repeat_a / Gst.SECOND if self.ab_repeat_a is not None else None,
                   "b": self.ab_repeat_b / Gst.SECOND if self.ab_repeat_b is not None else None,
                   "active": self.is_ab_repeat_active},
            "audio": {"current": self.current_audio_track + 1, "total": self.n_audio_tracks},
            "ai": {"running": bool(ai_job and ai_job.is_running()), "text": ai_status[0] if ai_status else "",
                   "fraction": ai_status[1] if ai_status else 0.0,
                   "available": whisper_available(settings.get("whisper_model"))},
            "sleep": {"minutes": self.sleep_minutes, "remaining": self.sleep_remaining_sec()},
            "night_mode": settings.get("night_mode"),
            "rotation": self.video_rotation,
        }

    # ---- 원격 명령 (HTTP 스레드 → 메인 스레드로 위임) ---------------------------------
    def handle_remote_command(self, action, val=None, index=None, delta=None, percent=None, url=None, quality=None,
                              sec=None, minutes=None):
        """웹 리모컨에서 수신한 명령을 GTK 메인 스레드에서 실행합니다."""
        def run(fn, *args):
            GLib.idle_add(lambda: (fn(*args), False)[1])

        simple = {
            "play_pause": self.toggle_play_pause, "next": self.play_next_video, "prev": self.play_prev_video,
            "mute": self.toggle_mute, "fullscreen": self.toggle_fullscreen, "subtitles": self.toggle_subtitles,
            "repeat": self.cycle_repeat_mode, "screenshot": self.capture_screenshot, "speed_reset": self.reset_playback_rate,
            "ab_a": self.set_ab_repeat_a, "ab_b": self.set_ab_repeat_b, "ab_clear": self.clear_ab_repeat,
            "bookmark_add": self.add_bookmark, "audio_cycle": self.cycle_audio_track,
            "sub_sync_reset": self.reset_subtitle_sync, "ai_subtitles": self.start_ai_subtitles,
            "night": self.toggle_night_mode, "rotate": self.cycle_video_rotation,
            "yt_cancel": youtube_mgr.cancel_current,
        }
        if action in simple:
            run(simple[action])
        elif action == "speed" and _to_float(val) is not None:
            run(self.set_playback_rate, _to_float(val))
        elif action == "speed_step" and _to_float(delta) is not None:
            run(self.step_playback_rate, _to_float(delta))
        elif action == "seek" and _to_float(delta) is not None:
            run(self.seek_relative, _to_float(delta))
        elif action == "seek_to" and _to_float(percent) is not None:
            run(self.seek_to_percent, _to_float(percent))
        elif action == "seek_abs" and _to_float(sec) is not None:
            run(self.seek_direct, int(max(0.0, _to_float(sec)) * Gst.SECOND))
        elif action == "volume" and _to_float(val) is not None:
            run(self.set_volume, _to_float(val))
        elif action == "play_index" and _to_int(index) is not None:
            run(self.play_index_direct, _to_int(index))
        elif action == "queue_next" and _to_int(index) is not None:
            i = _to_int(index)
            run(lambda: self.queue_next(self.playlist[i]) if 0 <= i < len(self.playlist) else None)
        elif action == "sub_toggle_track" and _to_int(index) is not None:
            run(self.toggle_subtitle_track, _to_int(index))
        elif action == "sub_sync" and _to_int(delta) is not None:
            run(self.adjust_subtitle_sync, _to_int(delta))
        elif action == "sleep" and _to_int(minutes) is not None:
            run(self.set_sleep_timer, _to_int(minutes))
        elif action in ("yt", "yt_download", "yt_stream") and url:
            run(self.start_youtube, str(url), str(quality or "best"))
        elif action == "yt_remove" and url:
            run(youtube_mgr.cancel_pending, str(url))
        elif action == "open_location":
            run(self.open_selected_or_current_location_by_index, _to_int(index))

    def seek_to_percent(self, pct):
        if not self.pipeline:
            return
        success, duration = self.pipeline.query_duration(Gst.Format.TIME)
        if success and duration > 0:
            self.seek_direct(int(duration * (max(0.0, min(100.0, pct)) / 100.0)))

    def toggle_subtitle_track(self, idx):
        """리모컨에서 자막 트랙 하나를 켜고 끕니다."""
        if not (0 <= idx < len(self.available_subtitles)):
            return
        if idx in self.active_subtitle_indices and self.subtitles_enabled:
            self.active_subtitle_indices.discard(idx)
        else:
            self.active_subtitle_indices.add(idx)
        self.subtitles_enabled = bool(self.active_subtitle_indices)
        self.reload_and_apply_subtitles()
        self.show_osd(f"💬 {self.available_subtitles[idx]['label'][:30]} {'ON' if idx in self.active_subtitle_indices else 'OFF'}")

    # ---- 접속 안내 팝오버 (QR 코드 + PIN) ------------------------------------------
    def _qr_drawing_area(self, text, size=196):
        qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
        area = Gtk.DrawingArea()
        area.set_size_request(size, size)

        def draw(_w, cr):
            border = 3
            n = qr.get_size() + border * 2
            scale = size / n
            cr.set_source_rgb(1, 1, 1)
            cr.paint()
            cr.set_source_rgb(0, 0, 0)
            for y in range(qr.get_size()):
                for x in range(qr.get_size()):
                    if qr.get_module(x, y):
                        cr.rectangle((x + border) * scale, (y + border) * scale, scale + 0.3, scale + 0.3)
            cr.fill()
            return False
        area.connect("draw", draw)
        return area

    def show_remote_popover(self, parent_btn):
        """스마트폰 접속 안내: QR 코드(찍으면 바로 로그인), 주소, PIN"""
        pop = Gtk.Popover(relative_to=parent_btn)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_border_width(14)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        title = Gtk.Label(label="📱 스마트폰 웹 리모컨", xalign=0)
        title.get_style_context().add_class("popover-title")
        box.pack_start(title, False, False, 0)

        desc = Gtk.Label(label="같은 Wi-Fi의 스마트폰 카메라로 QR 코드를 찍으면\n바로 연결됩니다.", xalign=0)
        desc.get_style_context().add_class("muted")
        box.pack_start(desc, False, False, 0)

        if getattr(self, "remote_auth", None) and self.remote_url:
            qr_holder = Gtk.Box()
            qr_holder.set_halign(Gtk.Align.CENTER)
            qr_holder.pack_start(self._qr_drawing_area(self.remote_login_url()), False, False, 0)
            box.pack_start(qr_holder, False, False, 6)

            pin_lbl = Gtk.Label()
            pin_lbl.set_markup(f"<span font_family='monospace' size='xx-large' weight='bold' color='#e9ff5b'>PIN  {self.remote_auth.pin}</span>")
            box.pack_start(pin_lbl, False, False, 2)

        url_entry = Gtk.Entry()
        url_entry.set_text(self.remote_url or "리모컨 서버를 시작하지 못했습니다")
        url_entry.set_editable(False)
        box.pack_start(url_entry, False, False, 2)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        copy_btn = Gtk.Button(label="📋 주소 복사")
        copy_btn.get_style_context().add_class("primary")

        def on_copy(_b):
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.remote_url, -1)
            self.show_osd("📋 리모컨 주소가 복사되었습니다!")
            pop.popdown()
        copy_btn.connect("clicked", on_copy)
        btn_row.pack_start(copy_btn, True, True, 0)

        if getattr(self, "remote_auth", None):
            regen_btn = Gtk.Button(label="🔐 새 PIN")
            regen_btn.set_tooltip_text("새 PIN을 만들고 기존에 연결된 기기를 모두 로그아웃시킵니다")
            regen_btn.connect("clicked", lambda _b: (pop.popdown(), self.regenerate_remote_pin(), self.show_remote_popover(parent_btn)))
            btn_row.pack_start(regen_btn, False, False, 0)
        box.pack_start(btn_row, False, False, 4)

        box.show_all()
        pop.add(box)
        pop.popup()
