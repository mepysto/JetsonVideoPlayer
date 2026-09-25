"""네트워크 폴더(SMB/NFS 등): GVfs로 마운트하고 gvfs-fuse 로컬 경로로 재생합니다.

마운트한 공유는 /run/user/<uid>/gvfs/smb-share:server=…,share=…/ 아래 일반 파일처럼 보이므로
썸네일·AI 자막·이어보기 등 기존 기능을 그대로 쓸 수 있습니다. 주소와 로컬 경로의 대응은
settings["network_locations"]에 저장해 두고, 재부팅 뒤 이어보기를 누르면 다시 마운트합니다.
"""
import logging
import os
import urllib.parse

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

NETWORK_SCHEMES = ("smb", "nfs", "sftp", "ftp", "ftps", "dav", "davs", "afp")
MAX_LOCATIONS = 10


def gvfs_root():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "gvfs")


def is_gvfs_path(path):
    return bool(path) and os.path.abspath(path).startswith(gvfs_root() + os.sep)


def is_network_uri(text):
    scheme = urllib.parse.urlsplit((text or "").strip()).scheme.lower()
    return scheme in NETWORK_SCHEMES


def normalize_uri(text):
    """사용자가 입력한 주소 정리: \\\\서버\\공유 (Windows 표기) → smb://서버/공유, 끝의 / 제거"""
    text = (text or "").strip()
    if text.startswith("\\\\"):
        text = "smb://" + text.lstrip("\\").replace("\\", "/")
    if "://" in text:
        scheme, rest = text.split("://", 1)
        text = f"{scheme.lower()}://{rest.rstrip('/')}"
    return text


def display_name(uri):
    """목록에 보일 짧은 이름: 서버/공유/폴더"""
    parts = urllib.parse.urlsplit(uri)
    path = urllib.parse.unquote(parts.path).strip("/")
    return f"{parts.hostname or ''}/{path}".rstrip("/") or uri


def clean_locations(value):
    """설정 파일의 network_locations를 검증: [{"uri", "path", "name"}] (최대 MAX_LOCATIONS개)"""
    if not isinstance(value, list):
        return []
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            continue
        uri, path = item.get("uri"), item.get("path")
        if not (isinstance(uri, str) and isinstance(path, str) and is_network_uri(uri)) or uri in seen:
            continue
        seen.add(uri)
        name = item.get("name") if isinstance(item.get("name"), str) else display_name(uri)
        result.append({"uri": uri, "path": path, "name": name})
    return result[:MAX_LOCATIONS]


def remember_location(locations, uri, path):
    """최근 사용한 위치를 맨 앞으로 (같은 주소는 한 번만)"""
    entry = {"uri": uri, "path": os.path.abspath(path), "name": display_name(uri)}
    return [entry] + [loc for loc in clean_locations(locations) if loc["uri"] != uri][:MAX_LOCATIONS - 1]


def uri_for_path(locations, path):
    """로컬 gvfs 경로를 저장된 위치의 네트워크 주소로 되돌립니다 (재마운트용). 모르면 None."""
    path = os.path.abspath(path)
    best = None
    for loc in clean_locations(locations):
        root = loc["path"]
        if path == root or path.startswith(root.rstrip(os.sep) + os.sep):
            if best is None or len(root) > len(best["path"]):
                best = loc
    if best is None:
        return None
    rel = os.path.relpath(path, best["path"])
    if rel == ".":
        return best["uri"]
    return best["uri"].rstrip("/") + "/" + "/".join(urllib.parse.quote(p) for p in rel.split(os.sep))


def mount_uri(uri, mount_operation, on_done):
    """uri를 마운트하고 on_done(local_path, error_message)를 메인 루프에서 호출합니다.

    이미 마운트되어 있으면 바로 경로를 돌려줍니다. 인증이 필요하면 mount_operation(Gtk.MountOperation)이 창을 띄웁니다.
    """
    gfile = Gio.File.new_for_uri(uri)

    def resolve():
        path = gfile.get_path()
        if path and os.path.exists(path):
            on_done(path, None)
        else:
            on_done(None, "로컬 경로로 열 수 없습니다 (gvfs-fuse 패키지가 필요합니다)")

    def finished(_source, result):
        try:
            gfile.mount_enclosing_volume_finish(result)
        except GLib.Error as e:
            if not e.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                log.warning(f"⚠️ 네트워크 폴더 연결 실패 ({uri}): {e.message}")
                on_done(None, e.message)
                return
        resolve()

    gfile.mount_enclosing_volume(Gio.MountMountFlags.NONE, mount_operation, None, finished)
