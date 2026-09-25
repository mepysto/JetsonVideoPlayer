"""네트워크 폴더(SMB/NFS) 열기: 주소 입력·최근 위치·재연결, 백그라운드 폴더 읽기"""
import logging
import os
import threading

from gi.repository import GLib, Gtk

from ..library import scan_video_files
from ..network import (clean_locations, display_name, is_network_uri, mount_uri, normalize_uri,
                       remember_location, uri_for_path)
from ..settings import settings

log = logging.getLogger(__name__)


class NetworkMixin:
    def show_network_dialog(self):
        """네트워크 폴더 주소를 입력하거나 최근 위치를 골라 엽니다."""
        dialog = Gtk.Dialog(title="네트워크 폴더 열기", transient_for=self, modal=True, destroy_with_parent=True)
        dialog.add_buttons("취소", Gtk.ResponseType.CANCEL, "연결", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_default_size(460, -1)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(14)

        hint = Gtk.Label(xalign=0)
        hint.set_markup("NAS·공유 폴더 주소를 입력하세요.\n"
                        "<small>예: <tt>smb://192.168.0.10/video/드라마</tt>  ·  <tt>nfs://nas/export/movies</tt>  ·  "
                        "<tt>\\\\\\\\NAS\\\\video</tt></small>")
        box.pack_start(hint, False, False, 0)

        entry = Gtk.Entry()
        entry.set_placeholder_text("smb://서버/공유/폴더")
        entry.set_activates_default(True)
        locations = clean_locations(settings.get("network_locations"))
        if locations:
            entry.set_text(locations[0]["uri"])
        box.pack_start(entry, False, False, 0)

        if locations:
            recent_title = Gtk.Label(label="최근 위치", xalign=0)
            recent_title.get_style_context().add_class("muted")
            box.pack_start(recent_title, False, False, 4)
            for loc in locations:
                btn = Gtk.Button(label=f"🌐 {loc['name']}")
                btn.set_tooltip_text(loc["uri"])
                btn.get_style_context().add_class("tree-tool-btn")
                btn.connect("clicked", lambda _b, u=loc["uri"]: (dialog.response(Gtk.ResponseType.CANCEL),
                                                                 self.open_network_uri(u)))
                box.pack_start(btn, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        uri = normalize_uri(entry.get_text())
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not uri:
            return
        if not is_network_uri(uri):
            if os.path.isdir(uri):
                self.load_path(uri)
            else:
                self.show_osd("⚠️ smb:// 또는 nfs:// 로 시작하는 주소를 입력하세요.", duration_sec=3.0)
            return
        self.open_network_uri(uri)

    def open_network_uri(self, uri, then=None):
        """네트워크 주소를 연결(마운트)하고 폴더를 엽니다. then(local_path)가 있으면 대신 그것을 호출합니다."""
        self.show_osd(f"🌐 연결 중: {display_name(uri)}", duration_sec=10.0)

        def done(path, error):
            if error:
                self.show_osd(f"❌ 연결 실패: {error[:60]}", duration_sec=4.0)
                return
            settings.set("network_locations", remember_location(settings.get("network_locations"), uri, path))
            settings.save()
            log.info(f"🌐 [네트워크 폴더] {uri} → {path}")
            (then or self.load_path)(path)

        mount_uri(uri, Gtk.MountOperation(parent=self), done)

    def reconnect_network_path(self, path):
        """연결이 끊긴 gvfs 경로(재부팅 후 이어보기 등)를 다시 마운트해 엽니다."""
        uri = uri_for_path(settings.get("network_locations"), path)
        if not uri:
            self.show_osd("⚠️ 네트워크 폴더가 연결되어 있지 않습니다. ⋯ → 🌐 네트워크 폴더 열기", duration_sec=4.0)
            return
        self.open_network_uri(uri, then=lambda _mounted: self.load_path(path) if os.path.exists(path)
                              else self.show_osd("⚠️ 네트워크 폴더에서 파일을 찾을 수 없습니다.", duration_sec=3.0))

    def is_known_network_path(self, path):
        return uri_for_path(settings.get("network_locations"), path) is not None

    def _scan_network_folder_then_load(self, folder):
        """네트워크 폴더의 영상 목록을 백그라운드에서 읽고 load_path를 이어서 진행합니다 (UI 멈춤 방지)."""
        self.show_osd(f"📂 네트워크 폴더 읽는 중: {os.path.basename(folder)}", duration_sec=30.0)

        def work():
            try:
                files = scan_video_files(folder)
            except OSError as e:
                message = f"❌ 폴더를 읽을 수 없습니다: {e}"
                GLib.idle_add(lambda: (self.show_osd(message, duration_sec=4.0), False)[1])
                return
            GLib.idle_add(lambda: (self.load_path(folder, scanned=files), False)[1])

        threading.Thread(target=work, daemon=True, name="network-scan").start()
