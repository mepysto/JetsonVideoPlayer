#!/usr/bin/env python3
import sys
import os
import glob
import subprocess
import shutil
import json
import re
import hashlib
import html
import time
import datetime
import threading
import socket
import urllib.parse
import http.server
from urllib.request import pathname2url
from urllib.parse import unquote
import gi

# Deno 및 Node.js 런타임 경로 환경변수 자동 보정 (yt-dlp의 4K/1080p 고화질 디사이퍼링 완벽 지원)
NODE_PATHS = [
    "/home/btree/.deno/bin",
    "/home/btree/.local/bin",
    "/home/btree/.nvm/versions/node/v24.18.1/bin",
    "/usr/bin",
    "/usr/local/bin",
]
for p in NODE_PATHS:
    if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{p}:{os.environ.get('PATH', '')}"

def open_file_location(filepath):
    """지정된 파일이 위치한 폴더를 리눅스 기본 파일 관리자(Nautilus 등)로 열고 포커스합니다."""
    if not filepath:
        return False
    target = os.path.abspath(filepath)
    if not os.path.exists(target):
        folder = os.path.dirname(target)
        if not os.path.exists(folder):
            return False
        target = folder
    else:
        folder = target if os.path.isdir(target) else os.path.dirname(target)

    # 1. dbus FileManager1 ShowItems 시도 (파일 선택 포커스)
    if os.path.isfile(target):
        try:
            res = subprocess.run(
                ["dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                 "--type=method_call", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1.ShowItems",
                 f"array:string:file://{pathname2url(target)}", "string:"],
                capture_output=True, timeout=2
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    # 2. xdg-open 폴더 열기
    try:
        subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        pass

    # 3. gio open 폴더 열기
    try:
        subprocess.Popen(["gio", "open", folder])
        return True
    except Exception:
        pass

    return False

try:
    import yt_dlp
    HAS_YT_DLP = True
except ImportError:
    HAS_YT_DLP = False

YOUTUBE_URL_REGEX = re.compile(
    r'(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|embed/|live/)|youtu\.be/)([a-zA-Z0-9_-]{11})'
)

def is_youtube_url(url):
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return ("youtube.com" in u or "youtu.be" in u) and (
        any(u.startswith(p) for p in ("http://", "https://", "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"))
        or bool(re.search(r'https?://[^\s<>"]*(?:youtube\.com|youtu\.be)[^\s<>"]*', url.strip()))
    )

def extract_youtube_url(text):
    if not text or not isinstance(text, str):
        return None
    t = text.strip()
    m = re.search(r'https?://[^\s<>"]*(?:youtube\.com|youtu\.be)[^\s<>"]*', t)
    candidate = m.group(0) if m else t
    if not is_youtube_url(candidate):
        m2 = re.search(r'(?:v=|\/shorts\/|\/embed\/|\/live\/|youtu\.be\/)([a-zA-Z0-9_-]{11})(?:[&?]|$)', t)
        if m2 and ("youtube" in t.lower() or "youtu.be" in t.lower()):
            return f"https://www.youtube.com/watch?v={m2.group(1)}"
        return None

    if not (candidate.startswith("http://") or candidate.startswith("https://")):
        candidate = "https://" + candidate

    # 믹스(Mix, list=RD...)나 재생목록 파라미터가 섞여 있어도 단일 비디오(v=...)인 경우 깔끔하게 정규화
    try:
        parsed = urllib.parse.urlparse(candidate)
        # 1. watch?v=... 형태인 경우 부가 쿼리(list, start_radio, index 등)를 제거하고 순수 v 파라미터만 추출
        if "youtube.com" in parsed.netloc and parsed.path.startswith("/watch"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                vid = qs["v"][0]
                return f"https://www.youtube.com/watch?v={vid}"
        # 2. youtu.be/VID 형태
        if "youtu.be" in parsed.netloc:
            vid = parsed.path.strip("/").split("?")[0].split("&")[0]
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        # 3. shorts, embed, live 형태
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                vid = parsed.path[len(prefix):].split("/")[0].split("?")[0].split("&")[0]
                if vid:
                    return f"https://www.youtube.com/watch?v={vid}"
    except Exception:
        pass

    return candidate

class YouTubeManager:
    """YouTube 영상 다운로드 및 스트리밍 메타데이터를 비동기로 관리하는 매니저 클래스"""
    def __init__(self, download_dir=None):
        self.download_dir = download_dir or os.path.expanduser("~/Videos/YouTube")
        try:
            os.makedirs(self.download_dir, exist_ok=True)
        except Exception:
            pass
        self.current_download = {
            "active": False,
            "title": "",
            "percent": 0.0,
            "speed": "",
            "eta": "",
            "filepath": None,
            "error": None,
            "completed": False,
        }
        self.lock = threading.Lock()

    def get_status(self):
        with self.lock:
            return dict(self.current_download)

    def download_async(self, url, quality="best", on_progress=None, on_finish=None, on_error=None):
        """백그라운드 스레드에서 유튜브 영상을 다운로드하고 진행률을 콜백합니다."""
        if not HAS_YT_DLP:
            if on_error:
                GLib.idle_add(lambda: on_error("yt-dlp 모듈이 설치되어 있지 않습니다."))
            return

        def _worker():
            with self.lock:
                self.current_download["active"] = True
                self.current_download["title"] = "정보 확인 중..."
                self.current_download["percent"] = 0.0
                self.current_download["speed"] = ""
                self.current_download["eta"] = ""
                self.current_download["filepath"] = None
                self.current_download["error"] = None
                self.current_download["completed"] = False

            def _hook(d):
                if d['status'] == 'downloading':
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes') or 0
                    pct = (downloaded / total * 100.0) if total > 0 else 0.0
                    
                    speed = d.get('speed') or 0
                    if speed > 1024 * 1024:
                        speed_str = f"{speed / (1024 * 1024):.1f} MB/s"
                    elif speed > 1024:
                        speed_str = f"{speed / 1024:.0f} KB/s"
                    else:
                        speed_str = f"{speed:.0f} B/s"

                    eta = d.get('eta') or 0
                    eta_str = f"{eta}초" if eta < 60 else f"{eta // 60}분 {eta % 60}초"

                    title = d.get('info_dict', {}).get('title', 'YouTube Video')
                    with self.lock:
                        self.current_download["title"] = title
                        self.current_download["percent"] = pct
                        self.current_download["speed"] = speed_str
                        self.current_download["eta"] = eta_str

                    if on_progress:
                        GLib.idle_add(lambda: on_progress(pct, speed_str, eta_str, title))

                elif d['status'] == 'finished':
                    filename = d.get('filename', '')
                    with self.lock:
                        self.current_download["percent"] = 100.0
                        self.current_download["filepath"] = filename

            # 최고 화질(1080p Full HD / 720p 등) 및 고음질 오디오 스트림 결합 (mp4 출력)
            # Jetson NVDEC(nvv4l2decoder) 하드웨어 가속을 100% 보장하고 화면 미출력(AV1 DPB 결함)을 원천 차단하기 위해
            # H.264(avc1)를 최우선으로 선택하며, AV1(av01)은 엄격히 배제합니다.
            if quality == "1080p":
                fmt = (
                    "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]/"
                    "bestvideo[height<=1080][vcodec^=avc1]+bestaudio/"
                    "bestvideo[height<=1080][vcodec!*='av01'][vcodec!*='av1']+bestaudio[ext=m4a]/"
                    "best[height<=1080][vcodec^=avc1]/"
                    "best[height<=1080][vcodec!*='av01']/"
                    "best[height<=1080]"
                )
            elif quality == "720p":
                fmt = (
                    "bestvideo[height<=720][vcodec^=avc1]+bestaudio[ext=m4a]/"
                    "bestvideo[height<=720][vcodec^=avc1]+bestaudio/"
                    "bestvideo[height<=720][vcodec!*='av01'][vcodec!*='av1']+bestaudio[ext=m4a]/"
                    "best[height<=720][vcodec^=avc1]/"
                    "best[height<=720][vcodec!*='av01']/"
                    "best[height<=720]"
                )
            elif quality == "audio":
                fmt = "bestaudio[ext=m4a]/bestaudio"
            else: # "best" (최고 화질: 1080p H.264 Full HD 최우선, 또는 AV1 제외 최고화질)
                fmt = (
                    "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/"
                    "bestvideo[vcodec^=avc1]+bestaudio/"
                    "bestvideo[vcodec!*='av01'][vcodec!*='av1']+bestaudio[ext=m4a]/"
                    "bestvideo[vcodec!*='av01'][vcodec!*='av1']+bestaudio/"
                    "best[vcodec^=avc1]/"
                    "best[vcodec!*='av01']/"
                    "best"
                )

            out_tmpl = os.path.join(self.download_dir, "%(title)s [%(id)s].%(ext)s")
            ydl_opts = {
                'format': fmt,
                'outtmpl': out_tmpl,
                'progress_hooks': [_hook],
                'quiet': True,
                'no_warnings': True,
                'merge_output_format': 'mp4',
                'noplaylist': True,
                'overwrites': True,
                'remote_components': ['ejs:github'],
            }

            deno_bin = "/home/btree/.deno/bin/deno"
            node_bin = "/home/btree/.nvm/versions/node/v24.18.1/bin/node"
            if os.path.exists(deno_bin):
                ydl_opts['js_runtimes'] = {'deno': {'path': deno_bin}}
            elif os.path.exists(node_bin):
                ydl_opts['js_runtimes'] = {'node': {'path': node_bin}}

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    final_filename = ydl.prepare_filename(info)
                    base, _ = os.path.splitext(final_filename)
                    if os.path.exists(f"{base}.mp4"):
                        final_filename = f"{base}.mp4"
                    title = info.get('title', 'YouTube Video')

                with self.lock:
                    self.current_download["active"] = False
                    self.current_download["percent"] = 100.0
                    self.current_download["filepath"] = final_filename
                    self.current_download["completed"] = True

                if on_finish:
                    GLib.idle_add(lambda: on_finish(final_filename, title))
            except Exception as e:
                err_msg = str(e)
                with self.lock:
                    self.current_download["active"] = False
                    self.current_download["error"] = err_msg
                if on_error:
                    GLib.idle_add(lambda: on_error(err_msg))

        threading.Thread(target=_worker, daemon=True).start()

    def extract_stream_async(self, url, on_success=None, on_error=None):
        """즉시 스트리밍을 위한 비디오 URL 및 메타데이터 추출 (H.264 최우선)"""
        if not HAS_YT_DLP:
            if on_error:
                GLib.idle_add(lambda: on_error("yt-dlp 모듈이 설치되어 있지 않습니다."))
            return

        def _worker():
            fmt = "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/best[vcodec^=avc1]/best[ext=mp4]/best"
            ydl_opts = {
                'format': fmt,
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'noplaylist': True,
                'remote_components': ['ejs:github'],
            }
            deno_bin = "/home/btree/.deno/bin/deno"
            node_bin = "/home/btree/.nvm/versions/node/v24.18.1/bin/node"
            if os.path.exists(deno_bin):
                ydl_opts['js_runtimes'] = {'deno': {'path': deno_bin}}
            elif os.path.exists(node_bin):
                ydl_opts['js_runtimes'] = {'node': {'path': node_bin}}

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    stream_url = info.get('url')
                    title = info.get('title', 'YouTube Stream')
                    duration = info.get('duration', 0)
                if stream_url:
                    if on_success:
                        GLib.idle_add(lambda: on_success(stream_url, title, duration))
                else:
                    if on_error:
                        GLib.idle_add(lambda: on_error("스트림 URL을 추출할 수 없습니다."))
            except Exception as e:
                if on_error:
                    GLib.idle_add(lambda: on_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

youtube_mgr = YouTubeManager()

# 환경 변수 자동 설정 (cannot open display 에러 방지)
if "DISPLAY" not in os.environ:
    if os.path.exists("/tmp/.X11-unix/X1"):
        os.environ["DISPLAY"] = ":1"
    else:
        os.environ["DISPLAY"] = ":0"
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

# 필요한 GStreamer 및 GTK 컴포넌트 로드
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GstPbutils', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkX11', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gst, Gtk, Gdk, GstVideo, GstPbutils, GLib, GdkX11, Pango, GdkPixbuf

def enable_x11_compositor_bypass(gdk_window):
    """
    GNOME Mutter 윈도우 컴포지터의 중간 재합성으로 인한 프레임 지터를 차단하기 위해
    X11 _NET_WM_BYPASS_COMPOSITOR 힌트를 지정하여 Direct GPU 스캔아웃을 활성화합니다.
    """
    try:
        xid = None
        if hasattr(gdk_window, "get_xid"):
            xid = gdk_window.get_xid()
        elif hasattr(GdkX11, "X11Window") and hasattr(GdkX11.X11Window, "get_xid"):
            xid = GdkX11.X11Window.get_xid(gdk_window)
        if xid:
            subprocess.run(
                ["xprop", "-id", str(xid), "-f", "_NET_WM_BYPASS_COMPOSITOR", "32c", "-set", "_NET_WM_BYPASS_COMPOSITOR", "1"],
                capture_output=True, check=False
            )
    except Exception:
        pass

def optimize_gstreamer_ranks():
    """
    Jetson 하드웨어 디코더(nvv4l2decoder)를 H.264/H.265 및 AV1 코덱에 우선 할당하여 
    4K 60fps 단일 영상 재생 시 CPU 병목으로 인한 화면 끊김(Stuttering)을 완벽히 방지합니다.
    JetPack 드라이버 에러(NvBufSurfTransform -1)가 발생하는 VP9 10-bit HDR 영상만 SW 디코더(vp9dec)로 우회합니다.
    """
    registry = Gst.Registry.get()
    
    # 1. Jetson 하드웨어 디코더 존재 여부 감지
    hw_decoder = registry.find_feature("nvv4l2decoder", Gst.ElementFactory.__gtype__)
    
    if hw_decoder:
        # Jetson 하드웨어 디코더 및 변환기 우위 설정 (PRIMARY + 1000)
        hw_elements = ["nvv4l2decoder", "nvvidconv"]
        for name in hw_elements:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 1000)
        
        # AV1/H264/H265/VP9 스트림 파서 랭크 상향 (프레임 경계 추출 보장)
        parsers = ["av1parse", "h264parse", "h265parse", "vp9parse"]
        for name in parsers:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 1500)

        # 소프트웨어 디코더는 기본 rank를 유지합니다. 하드웨어를 우선하되 특정
        # 프로파일/드라이버 오류에서는 GStreamer가 안전하게 fallback할 수 있어야 합니다.

        # CPU 소프트웨어 비디오 변환기/스케일러 랭크 유지 (Standard Format Conversion 허용)
        for name in ["videoconvert", "videoscale"]:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY)

        print("⚡ [하드웨어 가속 60 FPS 최적화] nvv4l2decoder HW 가속 및 60 FPS 전용 파이프라인 무결 적용 완료.")
    else:
        print("ℹ️ [소프트웨어 디코딩] Jetson HW 디코더(nvv4l2decoder)가 감지되지 않아 기본 디코더를 유지합니다.")

CACHE_DIR = os.path.expanduser("~/.cache/jetson_video_player")
CACHE_FILE = os.path.join(CACHE_DIR, "hw_cache.json")

class HWSupportCache:
    """비디오 파일별 하드웨어 적합성 ffprobe 분석 결과를 디스크에 영구 캐시하여 시작 지연을 방지합니다."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.is_dirty = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception as e:
            self.cache = {}

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
                self.is_dirty = False
            except Exception:
                pass

    def get(self, file_path):
        try:
            st = os.stat(file_path)
            mtime = st.st_mtime
            size = st.st_size
        except Exception:
            return None

        with self.lock:
            entry = self.cache.get(file_path)
            if entry and entry.get("mtime") == mtime and entry.get("size") == size:
                return entry.get("supported", False), entry.get("reason", "")
        return None

    def set(self, file_path, supported, reason):
        try:
            st = os.stat(file_path)
            mtime = st.st_mtime
            size = st.st_size
        except Exception:
            mtime = 0
            size = 0

        with self.lock:
            self.cache[file_path] = {
                "mtime": mtime,
                "size": size,
                "supported": supported,
                "reason": reason
            }
            self.is_dirty = True

hw_cache = HWSupportCache()

RESUME_FILE = os.path.join(CACHE_DIR, "resume_cache.json")

class ResumeCache:
    """영상의 마지막 재생 위치를 기억하여 다음 실행 시 이어보기를 지원합니다."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.is_dirty = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(RESUME_FILE):
                with open(RESUME_FILE, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(RESUME_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
                self.is_dirty = False
            except Exception:
                pass

    def get(self, file_path):
        with self.lock:
            entry = self.cache.get(file_path)
            if entry and isinstance(entry, dict):
                return entry.get("position_ns", 0), entry.get("duration_ns", 0)
        return 0, 0

    def set(self, file_path, position_ns, duration_ns):
        # 5초 이상 재생되었고, 영상 끝 95% 이전인 경우에만 저장
        if position_ns < 5 * Gst.SECOND:
            return
        if duration_ns > 0 and position_ns > duration_ns * 0.95:
            self.clear(file_path)
            return

        with self.lock:
            self.cache[file_path] = {
                "position_ns": position_ns,
                "duration_ns": duration_ns,
                "updated_at": time.time()
            }
            # 최대 200개 유지
            if len(self.cache) > 200:
                oldest = sorted(self.cache.keys(), key=lambda k: self.cache[k].get("updated_at", 0))[0]
                self.cache.pop(oldest, None)
            self.is_dirty = True

    def clear(self, file_path):
        with self.lock:
            if file_path in self.cache:
                self.cache.pop(file_path, None)
                self.is_dirty = True

resume_cache = ResumeCache()

BOOKMARKS_FILE = os.path.join(CACHE_DIR, "bookmarks.json")

class BookmarkCache:
    """비디오 파일별 북마크 타임스탬프를 관리하고 영구 저장합니다."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.is_dirty = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(BOOKMARKS_FILE):
                with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                    self.cache = json.load(f)
        except Exception:
            self.cache = {}

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(BOOKMARKS_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
                self.is_dirty = False
            except Exception:
                pass

    def get(self, file_path):
        with self.lock:
            return list(self.cache.get(file_path, []))

    def add(self, file_path, position_ns, label=None):
        if not file_path:
            return False, "재생 중인 영상이 없습니다."
        sec = int(position_ns / Gst.SECOND)
        if not label:
            m, s = divmod(sec, 60)
            h, m = divmod(m, 60)
            label = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        with self.lock:
            entries = self.cache.setdefault(file_path, [])
            for item in entries:
                if abs(item.get("position_ns", 0) - position_ns) < Gst.SECOND:
                    return False, "이미 등록된 북마크 지점입니다."
            entries.append({
                "position_ns": position_ns,
                "label": label,
                "created_at": time.time()
            })
            entries.sort(key=lambda x: x.get("position_ns", 0))
            self.is_dirty = True
        return True, label

    def remove(self, file_path, index):
        with self.lock:
            entries = self.cache.get(file_path, [])
            if 0 <= index < len(entries):
                entries.pop(index)
                self.is_dirty = True
                return True
        return False

bookmark_cache = BookmarkCache()

HISTORY_FILE = os.path.join(CACHE_DIR, "history.json")

class HistoryCache:
    """최근 재생한 파일 및 디렉토리 목록을 관리합니다."""
    def __init__(self):
        self.lock = threading.Lock()
        self.history = []
        self.is_dirty = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
        except Exception:
            self.history = []

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.history, f, ensure_ascii=False, indent=2)
                self.is_dirty = False
            except Exception:
                pass

    def add(self, path):
        if not path or not os.path.exists(path):
            return
        abs_path = os.path.abspath(path)
        is_dir = os.path.isdir(abs_path)
        title = os.path.basename(abs_path) or abs_path
        with self.lock:
            self.history = [h for h in self.history if h.get("path") != abs_path]
            self.history.insert(0, {
                "path": abs_path,
                "title": title,
                "is_dir": is_dir,
                "timestamp": time.time()
            })
            self.history = self.history[:15]
            self.is_dirty = True

    def get_all(self):
        with self.lock:
            return list(self.history)

history_cache = HistoryCache()

def get_jetson_hw_stats():
    """Jetson 하드웨어(SoC 온도, GPU 로드, RAM 사용량) 상태를 안전하게 파싱합니다."""
    stats = {}
    try:
        cpu_temps = []
        gpu_temps = []
        for tz in glob.glob("/sys/devices/virtual/thermal/thermal_zone*"):
            type_file = os.path.join(tz, "type")
            temp_file = os.path.join(tz, "temp")
            if os.path.exists(type_file) and os.path.exists(temp_file):
                try:
                    with open(type_file, "r") as f:
                        ztype = f.read().strip().lower()
                    with open(temp_file, "r") as f:
                        temp_val = float(f.read().strip()) / 1000.0
                    if "cpu" in ztype:
                        cpu_temps.append(temp_val)
                    elif "gpu" in ztype:
                        gpu_temps.append(temp_val)
                except Exception:
                    continue
        if cpu_temps:
            stats["cpu_temp"] = sum(cpu_temps) / len(cpu_temps)
        if gpu_temps:
            stats["gpu_temp"] = sum(gpu_temps) / len(gpu_temps)
    except Exception:
        pass

    gpu_load_paths = [
        "/sys/devices/platform/gpu.0/load",
        "/sys/devices/gpu.0/load",
        "/sys/devices/platform/17000000.ga10b/load",
        "/sys/devices/platform/17000000.gv11b/load"
    ]
    for p in gpu_load_paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    raw = float(f.read().strip())
                    stats["gpu_load"] = raw / 10.0 if raw > 100 else raw
                break
            except Exception:
                continue

    try:
        mem_total = 0
        mem_avail = 0
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) * 1024
        if mem_total > 0:
            mem_used = mem_total - mem_avail
            stats["ram_used_gb"] = mem_used / (1024 ** 3)
            stats["ram_total_gb"] = mem_total / (1024 ** 3)
            stats["ram_percent"] = (mem_used / mem_total) * 100.0
    except Exception:
        pass

    return stats

def get_local_ip():
    """스마트폰 접속을 위한 현재 머신의 로컬 네트워크 IPv4 주소를 감지합니다."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

REMOTE_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="theme-color" content="#0c1017">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Jetson Player Remote</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; -webkit-user-select: none; }
  body { background: #0c1017; color: #f0f4fc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; flex-direction: column; align-items: center; min-height: 100vh; padding: 14px; }
  .container { width: 100%; max-width: 480px; display: flex; flex-direction: column; gap: 12px; }
  .header { display: flex; justify-content: space-between; align-items: center; padding: 4px 2px; }
  .title { font-size: 16px; font-weight: 800; color: #e9ff5b; letter-spacing: 1px; }
  .badge { background: #1f2937; color: #9ca3af; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
  .badge.online { background: #064e3b; color: #34d399; }
  .card { background: #141a24; border: 1px solid #232c3d; border-radius: 16px; padding: 16px; display: flex; flex-direction: column; gap: 12px; box-shadow: 0 4px 14px rgba(0,0,0,0.3); }
  .card-title-row { display: flex; justify-content: space-between; align-items: center; }
  .card-title { font-size: 14px; font-weight: 700; color: #cbd5e1; }
  .now-playing-title { font-size: 15px; font-weight: 700; color: #ffffff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .time-row { display: flex; justify-content: space-between; font-size: 12px; color: #9ca3af; font-family: monospace; }
  input[type=range] { width: 100%; height: 6px; border-radius: 3px; -webkit-appearance: none; background: #2a3447; outline: none; }
  input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%; background: #e9ff5b; cursor: pointer; }
  .btn-row { display: flex; justify-content: space-around; align-items: center; gap: 8px; }
  button { background: #1c2433; color: #f0f4fc; border: 1px solid #2d3748; border-radius: 12px; padding: 10px 14px; font-size: 15px; font-weight: 700; cursor: pointer; transition: background 0.1s, transform 0.1s; display: flex; align-items: center; justify-content: center; }
  button:active { background: #2d3748; transform: scale(0.96); }
  button.primary { background: #e9ff5b; color: #0c1017; border-color: #e9ff5b; width: 60px; height: 60px; border-radius: 30px; font-size: 24px; }
  button.primary:active { background: #f2ff91; }
  .vol-row { display: flex; align-items: center; gap: 12px; }
  .vol-label { font-size: 13px; font-weight: 700; color: #e9ff5b; min-width: 60px; text-align: right; }
  
  /* 속도 조절 UI */
  .speed-badge { background: #232d3f; color: #e9ff5b; padding: 3px 8px; border-radius: 6px; font-size: 13px; font-weight: 800; font-family: monospace; }
  .speed-presets { display: flex; gap: 6px; justify-content: space-between; }
  .speed-presets button { flex: 1; padding: 8px 2px; font-size: 12px; border-radius: 8px; }
  .speed-presets button.active-speed { background: #e9ff5b; color: #0c1017; font-weight: bold; border-color: #e9ff5b; }
  .speed-steps { display: flex; gap: 6px; }
  .speed-steps button { flex: 1; padding: 8px 6px; font-size: 12px; border-radius: 8px; }

  .grid-actions { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .grid-actions button { font-size: 13px; padding: 10px; border-radius: 10px; }
  
  /* 폴더 아코디언 재생목록 */
  .playlist-card { max-height: 380px; overflow-y: auto; padding: 14px; }
  .search-input { width: 100%; background: #161c28; color: #f0f4fc; border: 1px solid #2a3447; border-radius: 8px; padding: 8px 12px; font-size: 13px; outline: none; margin-bottom: 10px; }
  .search-input:focus { border-color: #e9ff5b; }
  .folder-group { margin-bottom: 8px; border: 1px solid #232c3d; border-radius: 10px; overflow: hidden; background: #0f141d; }
  .folder-header { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: #19202c; cursor: pointer; font-size: 13px; font-weight: 700; color: #cbd5e1; }
  .folder-header:active { background: #222c3e; }
  .folder-header.has-active { color: #e9ff5b; border-left: 3px solid #e9ff5b; }
  .folder-items { display: none; flex-direction: column; }
  .folder-items.open { display: flex; }
  .playlist-item { padding: 9px 12px 9px 24px; font-size: 12px; color: #94a3b8; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-top: 1px solid #161c28; }
  .playlist-item:active { background: #1c2432; }
  .playlist-item.active { background: #222b3a; color: #e9ff5b; font-weight: bold; border-left: 3px solid #e9ff5b; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="title">⚡ JETSON REMOTE</div>
    <div id="statusBadge" class="badge">연결 중...</div>
  </div>

  <!-- 현재 재생 카드 -->
  <div class="card">
    <div id="trackTitle" class="now-playing-title">재생 중인 영상 없음</div>
    <div class="time-row">
      <span id="curTime">00:00</span>
      <span id="durTime">00:00</span>
    </div>
    <input type="range" id="progressBar" min="0" max="100" value="0" step="0.1">
    
    <div class="btn-row">
      <button onclick="cmd('prev')">⏮</button>
      <button onclick="cmd('seek', {delta: -10})">⏪ 10s</button>
      <button id="playBtn" class="primary" onclick="cmd('play_pause')">▶</button>
      <button onclick="cmd('seek', {delta: 10})">10s ⏩</button>
      <button onclick="cmd('next')">⏭</button>
    </div>
  </div>

  <!-- 재생 속도 조절 카드 -->
  <div class="card">
    <div class="card-title-row">
      <span class="card-title">⚡ 재생 속도 조절</span>
      <span id="speedVal" class="speed-badge">1.0x</span>
    </div>
    <div class="speed-presets">
      <button onclick="cmd('speed', {val: 0.5})" id="sp_05">0.5x</button>
      <button onclick="cmd('speed', {val: 0.75})" id="sp_075">0.75x</button>
      <button onclick="cmd('speed', {val: 1.0})" id="sp_10">1.0x</button>
      <button onclick="cmd('speed', {val: 1.25})" id="sp_125">1.25x</button>
      <button onclick="cmd('speed', {val: 1.5})" id="sp_15">1.5x</button>
      <button onclick="cmd('speed', {val: 2.0})" id="sp_20">2.0x</button>
    </div>
    <div class="speed-steps">
      <button onclick="cmd('speed_step', {delta: -0.25})">˗ 느리게 (-0.25x)</button>
      <button onclick="cmd('speed_reset')" style="flex: 0.8;">1.0x 기본</button>
      <button onclick="cmd('speed_step', {delta: 0.25})">˖ 빠르게 (+0.25x)</button>
    </div>
  </div>

  <!-- 볼륨 및 기본 액션 카드 -->
  <div class="card">
    <div class="vol-row">
      <button onclick="cmd('mute')" id="muteBtn" style="padding: 8px 12px; font-size: 18px;">🔊</button>
      <input type="range" id="volBar" min="0" max="200" value="100" step="1">
      <span id="volVal" class="vol-label">100%</span>
    </div>
    <div class="grid-actions">
      <button onclick="cmd('fullscreen')">📺 전체화면 토글</button>
      <button onclick="cmd('subtitles')">💬 자막 토글</button>
      <button onclick="cmd('repeat')">🔁 <span id="repeatModeText">반복 모드</span></button>
      <button onclick="cmd('screenshot')">📸 스크린샷 캡처</button>
    </div>
  </div>

  <!-- 고급 조작 카드 (A-B 구간반복 / 북마크 / 오디오 트랙) -->
  <div class="card">
    <div class="card-title-row">
      <span class="card-title">🎛️ 구간반복 & 북마크 & 오디오</span>
    </div>
    <div style="display: flex; gap: 6px;">
      <button onclick="cmd('ab_a')" style="flex:1; font-size:12px; padding:9px 4px;">🔁 [A] 시작</button>
      <button onclick="cmd('ab_b')" style="flex:1; font-size:12px; padding:9px 4px;">🔁 [B] 끝</button>
      <button onclick="cmd('ab_clear')" style="flex:0.8; font-size:12px; padding:9px 4px;">반복 해제</button>
    </div>
    <div class="grid-actions">
      <button onclick="cmd('bookmark_add')">🔖 북마크 추가</button>
      <button onclick="cmd('audio_cycle')">🎵 오디오 트랙 전환</button>
      <button onclick="cmd('open_location')" style="grid-column: span 2;">📂 파일 위치 열기 (파일 브라우저)</button>
    </div>
  </div>

  <!-- 유튜브 영상 재생 및 다운로드 카드 -->
  <div class="card">
    <div class="card-title-row">
      <span class="card-title">📺 유튜브 (YouTube) 무선 전송</span>
    </div>
    <div style="display: flex; gap: 6px; margin-bottom: 8px;">
      <input type="url" id="ytUrlInput" class="search-input" style="margin-bottom:0; flex:1;" placeholder="유튜브 링크 붙여넣기 (Ctrl+V)...">
    </div>
    <div style="display: flex; gap: 6px; margin-bottom: 8px; align-items: center;">
      <span style="font-size: 12px; color: #94a3b8; min-width: 36px;">화질:</span>
      <select id="ytQualitySelect" style="flex: 1; background: #161c28; color: #f0f4fc; border: 1px solid #2a3447; border-radius: 8px; padding: 7px 10px; font-size: 12px; outline: none;">
        <option value="best" selected>최고 화질 (1080p Full HD / HW 가속)</option>
        <option value="1080p">1080p Full HD (H.264)</option>
        <option value="720p">720p HD (초고속)</option>
        <option value="audio">오디오만 (M4A)</option>
      </select>
    </div>
    <div style="display: flex; gap: 6px;">
      <button onclick="submitYt('download')" class="primary" style="flex:1.2; font-size:12px; padding:10px 6px; font-weight:bold; border-radius:8px; width:auto; height:auto;">⬇️ 다운로드 & 재생</button>
      <button onclick="submitYt('stream')" style="flex:1; font-size:12px; padding:10px 6px; border-radius:8px;">🎬 바로 보기</button>
    </div>
    <div id="ytProgressBox" style="display:none; margin-top:10px; background:#141a24; padding:8px 10px; border-radius:8px; border:1px solid #293548;">
      <div style="display:flex; justify-content:space-between; font-size:11px; color:#e9ff5b; font-weight:700; margin-bottom:4px;">
        <span id="ytProgTitle" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:200px;">다운로드 중...</span>
        <span id="ytProgPct">0%</span>
      </div>
      <div style="width:100%; height:6px; background:#222c3d; border-radius:3px; overflow:hidden;">
        <div id="ytProgBar" style="width:0%; height:100%; background:#e9ff5b; transition:width 0.2s;"></div>
      </div>
      <div style="display:flex; justify-content:space-between; font-size:10px; color:#94a3b8; margin-top:4px;">
        <span id="ytProgSpeed">-- MB/s</span>
        <span id="ytProgEta">남은 시간 --</span>
      </div>
    </div>
  </div>

  <!-- 폴더별 정리된 재생목록 카드 (검색창 포함) -->
  <div class="card playlist-card">
    <div class="card-title-row" style="margin-bottom: 6px;">
      <span class="card-title">📂 폴더별 재생목록</span>
      <span id="playlistTotalCount" style="font-size: 12px; color: #94a3b8;"></span>
    </div>
    <input type="search" id="playlistSearch" class="search-input" placeholder="🔍 영상 제목 검색..." oninput="onSearch(this.value)">
    <div id="playlistContainer"></div>
  </div>
</div>

<script>
let isSeeking = false;
let isVolDragging = false;
const progress = document.getElementById('progressBar');
const volBar = document.getElementById('volBar');
let openFolders = new Set();
let autoOpenedActiveFolder = false;
let currentPlaylistGroups = [];
let lastPlaylistDataHash = "";
let searchQuery = "";

progress.addEventListener('input', () => { isSeeking = true; });
progress.addEventListener('change', () => {
  cmd('seek_to', { percent: progress.value });
  isSeeking = false;
});

volBar.addEventListener('input', () => {
  isVolDragging = true;
  updateVolLabel(volBar.value);
});
volBar.addEventListener('change', () => {
  cmd('volume', { val: volBar.value });
  isVolDragging = false;
});

function updateVolLabel(val) {
  const lbl = document.getElementById('volVal');
  if (!lbl) return;
  if (val > 100) {
    lbl.innerText = val + '% (부스트)';
    lbl.style.color = '#ff9800';
  } else {
    lbl.innerText = val + '%';
    lbl.style.color = '#e9ff5b';
  }
}

function cmd(action, params={}) {
  if (navigator.vibrate) navigator.vibrate(15);
  let q = new URLSearchParams({ action, ...params });
  fetch('/api/cmd?' + q.toString()).catch(() => {});
}

function fmtTime(sec) {
  sec = Math.floor(sec || 0);
  let m = Math.floor(sec / 60);
  let s = sec % 60;
  let h = Math.floor(m / 60);
  m = m % 60;
  if (h > 0) return `${h}:${m<10?'0':''}${m}:${s<10?'0':''}${s}`;
  return `${m<10?'0':''}${m}:${s<10?'0':''}${s}`;
}

function submitYt(mode) {
  const inp = document.getElementById('ytUrlInput');
  const url = (inp ? inp.value : '').trim();
  if (!url) {
    alert('유튜브 링크를 입력하세요.');
    return;
  }
  const qSelect = document.getElementById('ytQualitySelect');
  const q = qSelect ? qSelect.value : 'best';
  const pBox = document.getElementById('ytProgressBox');
  if (pBox) {
    pBox.style.display = 'block';
    pBox.removeAttribute('data-keep');
  }
  if (mode === 'download') {
    cmd('yt_download', { url: url, quality: q });
    document.getElementById('ytProgTitle').innerText = '⬇️ 최고 화질 다운로드 준비 중...';
  } else {
    cmd('yt_stream', { url: url, quality: q });
    document.getElementById('ytProgTitle').innerText = '⚡ 최고 화질 빠른 재생 버퍼링 중...';
  }
  inp.value = '';
}

function escapeHtml(str) {
  return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function toggleFolderById(idx) {
  const itemsEl = document.getElementById('fitems_' + idx);
  const arrowEl = document.getElementById('farrow_' + idx);
  if (itemsEl) {
    const isOpen = itemsEl.classList.toggle('open');
    if (arrowEl) arrowEl.innerText = isOpen ? '▼' : '▶';
    const folder = itemsEl.getAttribute('data-folder');
    if (isOpen) openFolders.add(folder);
    else openFolders.delete(folder);
  }
}

function onSearch(query) {
  searchQuery = (query || "").trim().toLowerCase();
  renderPlaylistGroups(currentPlaylistGroups);
}

function renderPlaylistGroups(groups) {
  currentPlaylistGroups = groups;
  const container = document.getElementById('playlistContainer');
  if (!groups || groups.length === 0) {
    container.innerHTML = '<div style="font-size:12px; color:#64748b; padding:8px;">재생목록이 비어 있습니다.</div>';
    return;
  }

  // 활성 항목이 있는 폴더 최초 자동 열기
  if (!autoOpenedActiveFolder) {
    groups.forEach(g => {
      if (g.has_active) {
        openFolders.add(g.folder);
        autoOpenedActiveFolder = true;
      }
    });
  }

  let html = '';
  let matchCount = 0;

  groups.forEach((g, idx) => {
    // 검색어 필터링
    let visibleItems = g.items;
    if (searchQuery) {
      visibleItems = g.items.filter(it => it.name.toLowerCase().includes(searchQuery));
    }
    if (visibleItems.length === 0) return;

    matchCount += visibleItems.length;
    // 검색 중일 때는 검색 결과가 있는 폴더 자동 펼침
    const isOpen = searchQuery ? true : openFolders.has(g.folder);
    const arrow = isOpen ? '▼' : '▶';
    const activeCls = g.has_active ? ' has-active' : '';
    const openCls = isOpen ? ' open' : '';

    html += '<div class="folder-group">';
    html += `  <div class="folder-header${activeCls}" onclick="toggleFolderById(${idx})">`;
    html += `    <span>${escapeHtml(g.folder)} <small style="opacity:0.75; font-size:11px;">(${visibleItems.length}개)</small></span>`;
    html += `    <span id="farrow_${idx}" style="font-size: 11px; opacity:0.8;">${arrow}</span>`;
    html += '  </div>';
    html += `  <div class="folder-items${openCls}" id="fitems_${idx}" data-folder="${escapeHtml(g.folder)}">`;
    visibleItems.forEach(it => {
      const itActive = it.active ? ' active' : '';
      html += `    <div class="playlist-item${itActive}" onclick="cmd('play_index', {index: ${it.index}})">`;
      html += `      ${it.index + 1}. ${escapeHtml(it.name)}`;
      html += '    </div>';
    });
    html += '  </div>';
    html += '</div>';
  });

  if (searchQuery && matchCount === 0) {
    html = '<div style="font-size:12px; color:#64748b; padding:12px; text-align:center;">검색 결과가 없습니다.</div>';
  }

  container.innerHTML = html;
}

function updateStatus() {
  fetch('/api/status')
    .then(r => r.json())
    .then(data => {
      document.getElementById('statusBadge').innerText = '연결됨';
      document.getElementById('statusBadge').className = 'badge online';
      document.getElementById('trackTitle').innerText = data.title || '대기 화면';
      document.getElementById('curTime').innerText = fmtTime(data.position_sec);
      document.getElementById('durTime').innerText = fmtTime(data.duration_sec);
      document.getElementById('playBtn').innerText = data.is_playing ? 'Ⅱ' : '▶';
      document.getElementById('muteBtn').innerText = data.is_muted ? '🔇' : '🔊';

      if (!isSeeking && data.duration_sec > 0) {
        progress.value = (data.position_sec / data.duration_sec) * 100;
      }
      if (!isVolDragging) {
        volBar.value = data.volume;
        updateVolLabel(data.volume);
      }

      // 속도 UI 갱신
      const curSpeed = data.speed || 1.0;
      document.getElementById('speedVal').innerText = curSpeed.toFixed(2) + 'x';
      ['05', '075', '10', '125', '15', '20'].forEach(id => {
        const el = document.getElementById('sp_' + id);
        if (el) el.className = '';
      });
      if (Math.abs(curSpeed - 0.5) < 0.02) document.getElementById('sp_05').className = 'active-speed';
      else if (Math.abs(curSpeed - 0.75) < 0.02) document.getElementById('sp_075').className = 'active-speed';
      else if (Math.abs(curSpeed - 1.0) < 0.02) document.getElementById('sp_10').className = 'active-speed';
      else if (Math.abs(curSpeed - 1.25) < 0.02) document.getElementById('sp_125').className = 'active-speed';
      else if (Math.abs(curSpeed - 1.5) < 0.02) document.getElementById('sp_15').className = 'active-speed';
      else if (Math.abs(curSpeed - 2.0) < 0.02) document.getElementById('sp_20').className = 'active-speed';

      let repeatLabel = '전체반복';
      if (data.repeat_mode === 'repeat_one') repeatLabel = '한곡반복';
      else if (data.repeat_mode === 'stop_after_finish') repeatLabel = '순차정지';
      else if (data.repeat_mode === 'shuffle') repeatLabel = '무작위';
      document.getElementById('repeatModeText').innerText = repeatLabel;

      if (data.total_videos !== undefined) {
        document.getElementById('playlistTotalCount').innerText = `총 ${data.total_videos}개`;
      }

      // 유튜브 다운로드 상태 실시간 갱신
      const pBox = document.getElementById('ytProgressBox');
      if (data.yt_download && data.yt_download.active) {
        if (pBox) pBox.style.display = 'block';
        document.getElementById('ytProgTitle').innerText = data.yt_download.title || '다운로드 중...';
        document.getElementById('ytProgPct').innerText = (data.yt_download.percent || 0).toFixed(1) + '%';
        document.getElementById('ytProgBar').style.width = (data.yt_download.percent || 0) + '%';
        document.getElementById('ytProgSpeed').innerText = data.yt_download.speed || '';
        document.getElementById('ytProgEta').innerText = data.yt_download.eta ? '남은 시간: ' + data.yt_download.eta : '';
      } else if (data.yt_download && data.yt_download.completed) {
        if (pBox && !pBox.getAttribute('data-keep')) {
          document.getElementById('ytProgTitle').innerText = '🎉 다운로드 완료! 자동 재생 중...';
          document.getElementById('ytProgPct').innerText = '100%';
          document.getElementById('ytProgBar').style.width = '100%';
          document.getElementById('ytProgSpeed').innerText = '';
          document.getElementById('ytProgEta').innerText = '';
          pBox.setAttribute('data-keep', '1');
          setTimeout(() => {
            pBox.style.display = 'none';
            pBox.removeAttribute('data-keep');
          }, 3000);
        }
      } else {
        if (pBox && !pBox.getAttribute('data-keep')) {
          pBox.style.display = 'none';
        }
      }

      // 폴더 그룹 데이터 변경 감지 (DOM 리렌더링 최적화: 변경 시에만 업데이트하여 터치 튐 방지)
      if (data.playlist_groups) {
        const dataHash = JSON.stringify(data.playlist_groups);
        if (dataHash !== lastPlaylistDataHash) {
          lastPlaylistDataHash = dataHash;
          data.playlist_groups.forEach(g => {
            if (g.has_active && !openFolders.has(g.folder)) {
              openFolders.add(g.folder);
            }
          });
          renderPlaylistGroups(data.playlist_groups);
        }
      }
    })
    .catch(() => {
      document.getElementById('statusBadge').innerText = '오프라인';
      document.getElementById('statusBadge').className = 'badge';
    });
}
setInterval(updateStatus, 1000);
updateStatus();
</script>
</body>
</html>
"""

class JetsonWebRemoteHandler(http.server.BaseHTTPRequestHandler):
    player = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(REMOTE_HTML.encode("utf-8"))
        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            status = self.player.get_remote_status() if self.player else {}
            self.wfile.write(json.dumps(status).encode("utf-8"))
        elif path == "/api/cmd":
            action = query.get("action", [""])[0]
            val = query.get("val", [None])[0]
            index = query.get("index", [None])[0]
            delta = query.get("delta", [None])[0]
            percent = query.get("percent", [None])[0]
            url = query.get("url", [None])[0]
            quality = query.get("quality", ["best"])[0]

            if self.player:
                self.player.handle_remote_command(action, val=val, index=index, delta=delta, percent=percent, url=url, quality=quality)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()


LANGUAGE_COLORS = {
    'ko': '#FFFFFF',  # 🇰🇷 한국어: 화이트 (메인 기본)
    'en': '#FFE066',  # 🇺🇸 영어: 레몬 옐로우 (화사하고 뛰어난 가독성)
    'zh': '#64D2FF',  # 🇨🇳 중국어: 시안/스카이블루 (시원하고 직관적)
    'ja': '#69F0AE',  # 🇯🇵 일본어: 네온 민트 (눈에 편안한 그린)
    'es': '#FF80AB',  # 🇪🇸 스페인어: 소프트 핑크
    'fr': '#FFB74D',  # 🇫🇷 프랑스어: 앰버 오렌지
    'de': '#D1C4E9',  # 🇩🇪 독일어: 소프트 라벤더
    'ru': '#FF8A80',  # 🇷🇺 러시아어: 코랄 레드
}

FALLBACK_PALETTE = ["#B388FF", "#80CBC4", "#FFF59D", "#FFAB91", "#CE93D8", "#80DEEA"]

def get_subtitle_color(file_path, index=0):
    """자막 파일의 언어 태그를 분석하여 언어별 최적 고대비 고유 색상을 반환합니다."""
    stem = os.path.basename(file_path).lower()
    if any(k in stem for k in ['.ko', '.kor', '.kr', '_ko', '_kor', '_kr', '.korean', '한국어', '한글']):
        return LANGUAGE_COLORS['ko']
    elif any(k in stem for k in ['.en', '.eng', '_en', '_eng', '.english', '영어', '영문']):
        return LANGUAGE_COLORS['en']
    elif any(k in stem for k in ['.zh', '.chi', '.zho', '_zh', '_chi', '.chinese', '중국어', '중문', '.cmn', 'zh-tw', 'zh-cn']):
        return LANGUAGE_COLORS['zh']
    elif any(k in stem for k in ['.ja', '.jpn', '.jp', '_ja', '_jpn', '.japanese', '일본어', '일어']):
        return LANGUAGE_COLORS['ja']
    elif any(k in stem for k in ['.es', '.spa', '_es', '_spa', '.spanish', '스페인어']):
        return LANGUAGE_COLORS['es']
    elif any(k in stem for k in ['.fr', '.fre', '.fra', '_fr', '_fre', '.french', '프랑스어']):
        return LANGUAGE_COLORS['fr']
    elif any(k in stem for k in ['.de', '.ger', '.deu', '_de', '_ger', '.german', '독일어']):
        return LANGUAGE_COLORS['de']
    elif any(k in stem for k in ['.ru', '.rus', '_ru', '_rus', '.russian', '러시아어']):
        return LANGUAGE_COLORS['ru']
    
    return FALLBACK_PALETTE[index % len(FALLBACK_PALETTE)]

def ms_to_srt_time(ms):
    """밀리초(ms)를 SRT 타임코드(HH:MM:SS,mmm) 포맷으로 변환합니다."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    ms %= 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"

def srt_time_to_ms(time_str):
    """00:01:23,456 또는 00:01:23.456 형태의 타임코드를 밀리초(ms)로 변환합니다."""
    time_str = time_str.strip().replace(',', '.')
    parts = time_str.split(':')
    try:
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            s_parts = parts[2].split('.')
            s = int(s_parts[0])
            ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
            return (h * 3600 + m * 60 + s) * 1000 + ms
        elif len(parts) == 2:
            m = int(parts[0])
            s_parts = parts[1].split('.')
            s = int(s_parts[0])
            ms = int(s_parts[1].ljust(3, '0')[:3]) if len(s_parts) > 1 else 0
            return (m * 60 + s) * 1000 + ms
    except Exception:
        pass
    return 0

def read_subtitle_text(file_path):
    """다양한 인코딩(UTF-8, CP949, EUC-KR 등)을 자동 감지하여 자막 텍스트를 로드합니다."""
    encodings = ['utf-8-sig', 'utf-8', 'cp949', 'euc-kr', 'utf-16', 'latin-1']
    for enc in encodings:
        try:
            with open(file_path, 'r', encoding=enc) as f:
                content = f.read()
                return content, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(file_path, 'r', encoding='latin-1', errors='replace') as f:
        return f.read(), 'latin-1'

def parse_smi_to_events(content):
    """SAMI (.smi) 텍스트를 [(start_ms, end_ms, text), ...] 목록으로 파싱합니다."""
    sync_pattern = re.compile(r'<sync\s+start\s*=\s*["\']?(\d+)["\']?[^>]*>(.*?)(?=<sync|$)', re.IGNORECASE | re.DOTALL)
    tag_cleaner = re.compile(r'<[^>]+>')
    raw_entries = []
    for match in sync_pattern.finditer(content):
        start_ms = int(match.group(1))
        body = match.group(2)
        body = re.sub(r'<br\s*/?>', '\n', body, flags=re.IGNORECASE)
        clean = tag_cleaner.sub('', body)
        clean = clean.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
        clean = "\n".join([line.strip() for line in clean.splitlines() if line.strip()])
        raw_entries.append((start_ms, clean))
    
    events = []
    for i in range(len(raw_entries)):
        start_ms, text = raw_entries[i]
        if not text or text == '&nbsp;' or text.isspace():
            continue
        if i + 1 < len(raw_entries):
            end_ms = raw_entries[i+1][0]
            if end_ms - start_ms > 7000:
                end_ms = start_ms + 4000
        else:
            end_ms = start_ms + 4000
        if end_ms <= start_ms:
            end_ms = start_ms + 1000
        events.append((start_ms, end_ms, text))
    return events

def parse_srt_or_vtt_to_events(content):
    """SRT / WebVTT 텍스트를 [(start_ms, end_ms, text), ...] 목록으로 파싱합니다."""
    time_pat = re.compile(r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})')
    tag_cleaner = re.compile(r'<[^>]+>')
    blocks = re.split(r'\n\s*\n', content.strip())
    events = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_match = None
        text_lines = []
        for line in lines:
            m = time_pat.search(line)
            if m:
                time_match = m
            elif time_match:
                clean = tag_cleaner.sub('', line)
                if clean:
                    text_lines.append(clean)
        if time_match and text_lines:
            start_ms = srt_time_to_ms(time_match.group(1))
            end_ms = srt_time_to_ms(time_match.group(2))
            text = "\n".join(text_lines)
            if end_ms > start_ms:
                events.append((start_ms, end_ms, text))
    return events

def parse_ass_to_events(content):
    """ASS / SSA 자막 텍스트를 [(start_ms, end_ms, text), ...] 목록으로 파싱합니다."""
    tag_cleaner = re.compile(r'\{.*?\}')
    events = []
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) >= 10:
            start_ms = srt_time_to_ms(parts[1])
            end_ms = srt_time_to_ms(parts[2])
            raw_text = parts[9]
            clean = tag_cleaner.sub('', raw_text)
            clean = clean.replace('\\N', '\n').replace('\\n', '\n').strip()
            if clean and end_ms > start_ms:
                events.append((start_ms, end_ms, clean))
    return events

def parse_subtitle_file_events(file_path):
    """자막 파일의 인코딩을 자동 감지하고 포맷에 맞게 파싱하여 타임라인 이벤트 목록을 반환합니다."""
    try:
        content, _enc = read_subtitle_text(file_path)
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.smi':
            return parse_smi_to_events(content)
        elif ext in ['.ass', '.ssa']:
            return parse_ass_to_events(content)
        else:
            return parse_srt_or_vtt_to_events(content)
    except Exception as e:
        print(f"⚠️ 자막 파싱 실패 ({file_path}): {e}")
        return []

def get_subtitle_label(file_path):
    """자막 파일명에서 언어 태그를 감지하여 사람이 읽기 쉬운 레이블을 생성합니다."""
    base = os.path.basename(file_path)
    stem, _ext = os.path.splitext(base)
    stem_lower = stem.lower()
    
    # 한국어
    if any(k in stem_lower for k in ['.ko', '.kor', '.kr', '_ko', '_kor', '_kr', '.korean', '한국어', '한글']):
        return f"🇰🇷 한국어 ({base})"
    # 영어
    elif any(k in stem_lower for k in ['.en', '.eng', '_en', '_eng', '.english', '영어', '영문']):
        return f"🇺🇸 영어 ({base})"
    # 일본어
    elif any(k in stem_lower for k in ['.ja', '.jpn', '.jp', '_ja', '_jpn', '.japanese', '일본어', '일어']):
        return f"🇯🇵 일본어 ({base})"
    # 중국어
    elif any(k in stem_lower for k in ['.zh', '.chi', '.zho', '_zh', '_chi', '.chinese', '중국어', '중문', '.cmn']):
        return f"🇨🇳 중국어 ({base})"
    # 스페인어
    elif any(k in stem_lower for k in ['.es', '.spa', '_es', '_spa', '.spanish', '스페인어']):
        return f"🇪🇸 스페인어 ({base})"
    # 프랑스어
    elif any(k in stem_lower for k in ['.fr', '.fre', '.fra', '_fr', '_fre', '.french', '프랑스어']):
        return f"🇫🇷 프랑스어 ({base})"
    # 독일어
    elif any(k in stem_lower for k in ['.de', '.ger', '.deu', '_de', '_ger', '.german', '독일어']):
        return f"🇩🇪 독일어 ({base})"
    
    return f"📄 {base}"

def find_all_matching_subtitles(video_path):
    """동영상 파일과 관련된 모든 자막 파일(.srt, .smi, .vtt, .ass, .ssa, .sub) 목록을 탐색하여 반환합니다."""
    dir_name = os.path.dirname(os.path.abspath(video_path))
    base_name = os.path.basename(video_path)
    stem, _ = os.path.splitext(base_name)
    stem_lower = stem.lower()
    sub_exts = ['.srt', '.smi', '.vtt', '.ass', '.ssa', '.sub']
    
    found_files = []
    seen = set()
    
    # 1. 동일한 파일명 (대소문자 무관)
    for ext in sub_exts:
        for c_ext in [ext, ext.upper()]:
            cand = os.path.join(dir_name, stem + c_ext)
            if os.path.isfile(cand) and cand not in seen:
                seen.add(cand)
                found_files.append(cand)
                
    # 2. 언어 태그 및 확장자 매칭
    try:
        for fname in os.listdir(dir_name):
            cand_path = os.path.join(dir_name, fname)
            if not os.path.isfile(cand_path) or cand_path in seen:
                continue
            f_lower = fname.lower()
            if any(f_lower.endswith(ext) for ext in sub_exts):
                if f_lower.startswith(stem_lower) or stem_lower in f_lower:
                    seen.add(cand_path)
                    found_files.append(cand_path)
    except Exception:
        pass
        
    # 만약 위 규칙으로 찾은 자막이 없고 디렉토리에 자막 파일이 있다면 모두 포함
    if not found_files:
        try:
            for fname in os.listdir(dir_name):
                cand_path = os.path.join(dir_name, fname)
                if os.path.isfile(cand_path) and any(fname.lower().endswith(ext) for ext in sub_exts):
                    if cand_path not in seen:
                        seen.add(cand_path)
                        found_files.append(cand_path)
        except Exception:
            pass

    # 한국어, 영어 순서가 앞으로 오도록 스마트 정렬
    def sort_key(path):
        lbl = get_subtitle_label(path)
        if "한국어" in lbl:
            return (0, path)
        if "영어" in lbl:
            return (1, path)
        if "일본어" in lbl:
            return (2, path)
        return (3, path)

    found_files.sort(key=sort_key)
    return found_files

def get_subtitle_short_badge(label):
    """자막 레이블에서 직관적인 언어 뱃지([KR], [TW], [EN], [JP] 등)를 추출합니다."""
    if "한국어" in label:
        return "[KR] "
    elif "영어" in label:
        return "[EN] "
    elif "중국어" in label or "대만" in label or "zh-TW" in label or "zh-tw" in label:
        return "[TW] "
    elif "일본어" in label:
        return "[JP] "
    elif "스페인어" in label:
        return "[ES] "
    elif "프랑스어" in label:
        return "[FR] "
    elif "독일어" in label:
        return "[DE] "
    return ""

def merge_subtitle_tracks(tracks, font_scale=1.0, offset_ms=0):
    """
    여러 자막 트랙 [(label, color, events), ...]의 타임라인을 정밀 분할하고
    언어별 고유 색상(<font color="...">) 및 싱크 오프셋을 적용하여 SAMI(.smi) 포맷 문자열로 병합합니다.
    GStreamer subparse는 SAMI 포맷의 <font color="..."> 태그를 완벽한 Pango markup(<span foreground="...">)으로
    변환하여 화면에 줄별 고유 색상으로 선명하게 렌더링합니다.
    """
    if not tracks:
        return ""
        
    time_points = set()
    offset_tracks = []
    for label, color, events in tracks:
        shifted_events = []
        for start_ms, end_ms, text in events:
            s = max(0, start_ms + offset_ms)
            e = max(s + 50, end_ms + offset_ms)
            shifted_events.append((s, e, text))
            time_points.add(s)
            time_points.add(e)
        offset_tracks.append((label, color, shifted_events))
            
    sorted_times = sorted(list(time_points))
    if len(sorted_times) < 2:
        return ""
        
    smi_blocks = []
    is_multi = len(offset_tracks) > 1
    
    for i in range(len(sorted_times) - 1):
        t_start = sorted_times[i]
        t_end = sorted_times[i + 1]
        if t_end <= t_start:
            continue
            
        active_lines = []
        for label, color, events in offset_tracks:
            for ev_start, ev_end, text in events:
                if ev_start <= t_start and ev_end >= t_end:
                    if text and not text.isspace():
                        badge = get_subtitle_short_badge(label) if is_multi else ""
                        c = color if color else "#FFFFFF"
                        lines = [line.strip() for line in text.splitlines() if line.strip()]
                        if lines:
                            escaped_first = html.escape(f"{badge}{lines[0]}")
                            styled_lines = [f'<font color="{c}">{escaped_first}</font>']
                            for extra_line in lines[1:]:
                                styled_lines.append(f'<font color="{c}">{html.escape(extra_line)}</font>')
                            active_lines.append("<br>".join(styled_lines))
                    break
                    
        if active_lines:
            combined_text = "<br>".join(active_lines)
            smi_blocks.append((t_start, t_end, combined_text))
            
    # 인접 동일 텍스트 블록 병합 및 80ms 미만 극미세 구간 스무딩 최적화
    smoothed = []
    for start, end, text in smi_blocks:
        if not text or text.isspace():
            continue
        if end - start < 80:
            if smoothed and smoothed[-1][2] == text:
                smoothed[-1] = (smoothed[-1][0], end, text)
                continue
            elif end - start < 40:
                continue
        if smoothed and smoothed[-1][1] == start and smoothed[-1][2] == text:
            smoothed[-1] = (smoothed[-1][0], end, text)
        else:
            smoothed.append((start, end, text))
            
    # SAMI 표준 문서 생성
    out = [
        '<SAMI>',
        '<HEAD>',
        '<TITLE>Jetson Multi Subtitles</TITLE>',
        '<STYLE TYPE="text/css"><!-- P { font-family: sans-serif; text-align: center; } .KRCC { Name: Korean; lang: ko-KR; } --></STYLE>',
        '</HEAD>',
        '<BODY>'
    ]
    
    for idx, (start, end, text) in enumerate(smoothed):
        out.append(f'<SYNC Start={start}><P Class=KRCC>{text}</SYNC>')
        next_start = smoothed[idx + 1][0] if idx + 1 < len(smoothed) else end + 1000
        # 다음 대사와의 간격이 200ms 이상일 때만 공백 자막을 삽입하여 subparse 큐 지연 및 싱크 왜곡 방지
        if next_start - end >= 200:
            out.append(f'<SYNC Start={end}><P Class=KRCC>&nbsp;</SYNC>')
            
    out.append('</BODY>')
    out.append('</SAMI>')
    
    return "\n".join(out)

def generate_merged_subtitle_file(active_tracks, video_path, font_scale=1.0, offset_ms=0):
    """
    선택된 자막 트랙들을 언어별 고유 색상이 적용된 SAMI(.smi) 파일로 생성하고 그 경로를 반환합니다.
    """
    if not active_tracks:
        return None
        
    cache_dir = "/tmp/jetson_subtitles"
    os.makedirs(cache_dir, exist_ok=True)
    
    track_ids = "_".join([t[0] for t in active_tracks])
    h = hashlib.md5((video_path + track_ids + f"_{font_scale:.2f}_{offset_ms}").encode('utf-8')).hexdigest()[:14]
    target_file = os.path.join(cache_dir, f"merged_sub_{h}.smi")
    
    smi_content = merge_subtitle_tracks(active_tracks, font_scale=font_scale, offset_ms=offset_ms)
    if not smi_content:
        return None
        
    with open(target_file, 'w', encoding='utf-8') as f:
        f.write(smi_content)
        
    return target_file

class JetsonSignageFlexiblePlayer(Gtk.Window):
    def __init__(self, input_path):
        super().__init__(title="Jetson Video Player")
        
        # [필수] 하드웨어 가속 랭크 최적화 보장
        optimize_gstreamer_ranks()

        # 1. 플레이어 창 설정 (일반 데스크탑 창 모드로 시작, F 키로 전체화면 전환)
        self.set_decorated(True)
        self.set_default_size(1280, 720)
        self.set_position(Gtk.WindowPosition.CENTER)
        
        # 이벤트 연결 (종료, 키보드 및 마우스 감지)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key_press)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("motion-notify-event", self.on_mouse_motion)
        self.connect("button-press-event", self.on_window_button_press)

        # 드래그 앤 드롭 지원 (동영상, 폴더, 자막 파일)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.on_drag_data_received)

        # 2. 입력 경로 타입(폴더 vs 파일)을 분석하여 재생 목록 구성
        self.input_path = input_path
        self.playlist = []
        self.current_index = 0
        self.is_single_file_mode = False
        self.xid = None
        if self.input_path:
            if is_youtube_url(self.input_path):
                yt_arg = self.input_path
                self.input_path = None
                GLib.idle_add(lambda: self.start_youtube_download(yt_arg, quality="best"))
            else:
                self.build_playlist()

        # UI/재생 상태
        self.is_playing = False
        self.is_fullscreen = False
        self.is_video_only = False
        self.is_keep_above = False
        self.sidebar_was_visible = True
        self.main_paned = None
        self.sidebar_width = 360
        self.is_adjusting_paned = False
        self.is_wrap_enabled = False
        self.r_text = None
        self.wrap_button = None
        self.is_destroyed = False
        self._bg_checker_started = False
        self.is_seeking = False
        self.duration_ns = 0
        self.tree_store = None
        self.playlist_treeview = None
        self.playlist_tree_iters = {}
        self.decoder_names = set()
        self.video_sink = None
        self.stats_ticks = 0
        self.last_dropped_frames = 0
        self.last_ui_pos_sec = -1
        self.retry_counts = {}
        self.max_retries = 2

        # 마우스 커서 숨김 제어 상태
        self.cursor_hide_timer_id = None
        self.is_cursor_hidden = False

        # 재생 속도(Playback Speed/Rate) 상태 변수
        self.playback_rate = 1.0
        self.rate_applied_on_preroll = False
        self.speed_button = None
        self.speed_popover = None
        self.fs_speed_button = None

        # 볼륨 및 음소거 상태
        self.is_muted = False
        self.pre_mute_volume = 100
        self.mute_btn = None
        self.fs_mute_btn = None

        # 재생 모드 (all: 전체 반복, one: 1곡 반복, none: 순차 후 정지, shuffle: 셔플 무작위)
        self.repeat_mode = "all"
        self.repeat_btn = None

        # 마우스 단일/더블 클릭 제어 타이머
        self.click_timer_id = None

        # 오디오 트랙 상태
        self.current_audio_track = 0
        self.n_audio_tracks = 0

        # 미디어 정보 HUD 및 빈 화면 안내
        self.hud_box = None
        self.hud_label = None
        self.is_hud_visible = False
        self.placeholder_box = None

        # A-B 구간 반복 상태
        self.ab_repeat_a = None
        self.ab_repeat_b = None
        self.is_ab_repeat_active = False
        self.ab_badge = None

        # 오디오/비디오(AV) 싱크 미세 조절 상태
        self.av_sync_offset_ms = 0
        self.current_asink = None

        # 스마트폰 웹 리모컨 서버 상태
        self.web_server = None
        self.web_server_thread = None
        self.web_port = 8888
        self.remote_url = ""

        # 검색 필터 텍스트
        self.search_text = ""
        self.search_entry = None

        # 전체화면 플로팅 컨트롤 바 및 OSD 상태 변수
        self.fs_controls_box = None
        self.is_fs_controls_visible = False
        self.is_mouse_over_fs_controls = False
        self.is_popover_open = False
        self.osd_box = None
        self.osd_label = None
        self.osd_timer_id = None
        self.fs_progress_scale = None
        self.fs_position_label = None
        self.fs_duration_label = None
        self.fs_play_button = None
        self.fs_sub_button = None
        self.fs_volume_scale = None

        # 다중 자막(Subtitle) 상태 변수 초기화
        self.subtitles_enabled = True
        self.has_subtitles = False
        self.single_sub_mode = True  # 기본 1개(한국어 우선)만 활성화 (화면 가림 방지)
        self.available_subtitles = []  # list of dicts: {'path', 'label', 'color', 'events'}
        self.active_subtitle_indices = set()  # set of int indices
        self.current_suburi = None
        self.pending_seek_ns = 0
        self.last_known_pos_ns = 0  # 자막 전환 시 0초 튕김 방지용 백업 위치
        self.is_updating_sub_checkboxes = False  # 모두 선택/해제 일괄 변경 락
        self.sub_reload_timer_id = None  # 자막 리로드 디바운스 타이머
        self.subtitle_font_scale = 1.0  # 자막 크기 스케일 (0.6 ~ 1.6)
        self.subtitle_offset_ms = 0  # 자막 싱크 오프셋 (ms 단위, 음수: 빠르게, 양수: 느리게)
        self.scale_label = None
        self.sync_label = None
        self.sub_popover = None

        # 3. 비디오가 임베딩될 GtkGLSink 네이티브 OpenGL 위젯 생성 (Totem 공식 아키텍처)
        self.gtk_sink = Gst.ElementFactory.make("gtkglsink", "gtk_sink")
        if self.gtk_sink:
            self.video_sink_bin = Gst.ElementFactory.make("glsinkbin", "glsinkbin")
            self.video_sink_bin.set_property("sink", self.gtk_sink)
            self.video_widget = self.gtk_sink.get_property("widget")
            self.video_sink = self.video_sink_bin
        else:
            self.gtk_sink = Gst.ElementFactory.make("gtksink", "gtk_sink")
            self.video_widget = self.gtk_sink.get_property("widget") if self.gtk_sink else Gtk.DrawingArea()
            self.video_sink = self.gtk_sink

        self.video_widget.set_hexpand(True)
        self.video_widget.set_vexpand(True)
        self.video_widget.set_size_request(640, 480)
        self.video_widget.connect("realize", self.on_realize)

        self.build_ui()

        # 4. GStreamer 핵심 파이프라인 변수 초기화
        self.pipeline = None
        self.bus = None

        # 재생 위치와 UI 상태 갱신 (250ms 주기로 매끄러운 진행바 보장)
        self.position_timer_id = GLib.timeout_add(250, self.update_playback_ui)

        # 스마트폰 웹 리모컨 서버 자동 기동
        self.start_web_remote_server()

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
        """웹 리모컨 클라이언트에게 현재 재생 상태를 반환합니다."""
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

        # 폴더별 그룹화된 재생목록 생성
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
            "yt_download": youtube_mgr.get_status()
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
            idx = int(index) if index is not None else None
            GLib.idle_add(lambda: self.open_selected_or_current_location_by_index(idx))

    def seek_to_percent(self, pct):
        if not self.pipeline:
            return
        success, duration = self.pipeline.query_duration(Gst.Format.TIME)
        if success and duration > 0:
            target = int(duration * (pct / 100.0))
            self.last_known_pos_ns = target
            self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target)

    def play_index_direct(self, idx):
        if self.playlist and 0 <= idx < len(self.playlist):
            self.current_index = idx
            self.play_current_video()

    def set_volume(self, val):
        val = max(0, min(200, val))
        if getattr(self, "volume_scale", None):
            self.volume_scale.set_value(val)
        if getattr(self, "fs_volume_scale", None):
            self.fs_volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)
        boost_str = " (부스트)" if val > 100 else ""
        self.show_osd(f"🔊 볼륨: {int(val)}%{boost_str}")

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

    def start_youtube_download(self, url, quality="best"):
        """유튜브 영상을 비동기로 다운로드하고 진행률을 표시하며, 완료 시 재생목록에 추가 및 자동 재생합니다."""
        norm_url = extract_youtube_url(url)
        if not norm_url:
            self.show_osd("⚠️ 올바른 유튜브 링크가 아닙니다.", duration_sec=2.0)
            return

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

        def _on_finish(final_filepath, title):
            print(f"🎉 [YouTube 다운로드 완료] {final_filepath}")
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

        q_desc = "최고 화질" if quality == "best" else quality
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

        def _on_finish(final_filepath, title):
            print(f"▶️ [YouTube 쾌속 재생 시작] {final_filepath}")
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
            print(f"🔁 [구간 반복] A 지점 설정: {t_str}")

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
        print(f"🔁 [구간 반복] 활성화: {a_str} ~ {b_str}")

    def clear_ab_repeat(self):
        """A-B 구간 반복을 해제합니다."""
        if self.ab_repeat_a is not None or self.ab_repeat_b is not None or self.is_ab_repeat_active:
            self.ab_repeat_a = None
            self.ab_repeat_b = None
            self.is_ab_repeat_active = False
            if getattr(self, "ab_badge", None):
                self.ab_badge.hide()
            self.show_osd("🔁 A-B 구간 반복 해제")
            print("🔁 [구간 반복] 해제")

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
            print(f"🔖 [북마크 추가] {os.path.basename(cur_path)} @ {res}")
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
                b_del.connect("clicked", lambda _b, i=idx: (bookmark_cache.remove(cur_path, i), pop.popdown(), self.show_bookmarks_popover(parent)))
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

    def show_history_popover(self, parent_widget=None):
        """최근 재생한 파일 및 폴더 목록을 표시하는 팝오버를 표시합니다."""
        parent = parent_widget or getattr(self, "topbar", None)
        history = history_cache.get_all()

        pop = Gtk.Popover(relative_to=parent)
        pop.set_position(Gtk.PositionType.BOTTOM)
        pop.set_border_width(10)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(label="🕒 최근 재생 항목", xalign=0)
        title.get_style_context().add_class("popover-title")
        box.pack_start(title, False, False, 2)

        if not history:
            empty = Gtk.Label(label="최근 재생 기록이 없습니다.", xalign=0)
            empty.get_style_context().add_class("muted")
            box.pack_start(empty, False, False, 6)
        else:
            scroll = Gtk.ScrolledWindow()
            scroll.set_min_content_height(160)
            scroll.set_min_content_width(280)
            list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            for item in history:
                icon = "📁 " if item.get("is_dir") else "🎬 "
                btn = Gtk.Button(label=f"{icon}{item['title']}")
                btn.set_tooltip_text(item['path'])
                btn.get_style_context().add_class("tree-tool-btn")
                btn.connect("clicked", lambda _b, p=item['path']: (pop.popdown(), self.load_target_path(p)))
                list_box.pack_start(btn, False, False, 0)
            scroll.add(list_box)
            box.pack_start(scroll, True, True, 0)

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
            print(f"📸 [스크린샷 캡처] 저장 완료: {filepath}")
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
        print(f"🔊 [AV 싱크] 오프셋: {sign}{self.av_sync_offset_ms}ms")

    def reset_av_sync(self):
        """오디오 싱크 오프셋을 0ms(기본값)으로 복원합니다."""
        self.av_sync_offset_ms = 0
        if getattr(self, "current_asink", None) and self.current_asink.find_property("ts-offset"):
            self.current_asink.set_property("ts-offset", 0)
        self.show_osd("🔊 AV 싱크 초기화: 0ms")
        print("🔊 [AV 싱크] 0ms 초기화 완료")

    def seek_direct(self, target_ns):
        """지정된 나노초 위치로 즉각 Seek합니다."""
        if self.pipeline and target_ns >= 0:
            self.last_known_pos_ns = target_ns
            self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target_ns)

    def load_target_path(self, path):
        """파일 또는 폴더 경로를 로드하여 즉시 재생합니다."""
        if not path or not os.path.exists(path):
            self.show_osd("경로가 존재하지 않습니다.")
            return
        if os.path.isfile(path):
            self.playlist = [os.path.abspath(path)]
            self.current_index = 0
            self.populate_playlist_tree()
            self.play_current_video()
        elif os.path.isdir(path):
            files = self.find_video_files(path)
            if files:
                self.playlist = files
                self.current_index = 0
                self.populate_playlist_tree()
                self.play_current_video()
            else:
                self.show_osd("폴더 내에 동영상이 없습니다.")

    def show_osd(self, text, timeout_ms=1200, duration_sec=None):
        """화면 상단 중앙에 설정 변경 상태(속도, 탐색 등)를 알려주는 OSD 박스를 표시합니다."""
        if duration_sec is not None:
            try:
                timeout_ms = max(400, int(float(duration_sec) * 1000))
            except Exception:
                pass
        if not getattr(self, "osd_box", None) or not getattr(self, "osd_label", None):
            return
        self.osd_label.set_text(text)
        self.osd_box.show_all()
        if getattr(self, "osd_timer_id", None):
            try:
                GLib.source_remove(self.osd_timer_id)
            except Exception:
                pass
        self.osd_timer_id = GLib.timeout_add(timeout_ms, self._hide_osd)

    def _hide_osd(self):
        if getattr(self, "osd_box", None):
            self.osd_box.hide()
        self.osd_timer_id = None
        return False

    def set_playback_rate(self, new_rate):
        """GStreamer 파이프라인에 재생 속도(Playback Rate)를 적용합니다."""
        new_rate = round(max(0.25, min(3.0, new_rate)), 2)
        self.playback_rate = new_rate
        self.rate_applied_on_preroll = True

        if self.pipeline:
            pos = self.last_known_pos_ns
            success, q_pos = self.pipeline.query_position(Gst.Format.TIME)
            if success and q_pos > 0:
                pos = q_pos
                self.last_known_pos_ns = q_pos

            flags = Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT
            res = self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                flags,
                Gst.SeekType.SET,
                pos,
                Gst.SeekType.NONE,
                -1
            )
            if not res:
                print(f"⚠️ 재생 속도 {new_rate:.2f}x 설정 실패")
            else:
                print(f"⚡ [재생 속도 변경] {new_rate:.2f}x (현재 위치: {self.format_time(pos)})")

        self.update_speed_button_ui()
        self.show_osd(f"⚡ 속도: {self.playback_rate:.2f}x")

    def step_playback_rate(self, delta):
        """현재 재생 속도에서 delta만큼 속도를 증감합니다."""
        new_rate = self.playback_rate + delta
        self.set_playback_rate(new_rate)

    def reset_playback_rate(self):
        """재생 속도를 1.0x (기본값)으로 복원합니다."""
        self.set_playback_rate(1.0)

    def update_speed_button_ui(self):
        """재생 속도 버튼 텍스트를 현재 배속에 맞게 갱신합니다."""
        rate_str = f"{self.playback_rate:.2f}x" if (self.playback_rate * 10) % 1 != 0 else f"{self.playback_rate:.1f}x"
        if rate_str.endswith(".0x") and self.playback_rate == 1.0:
            rate_str = "1.0x"
        if getattr(self, "speed_button", None):
            self.speed_button.set_label(f"⚡ {rate_str}")
        if getattr(self, "fs_speed_button", None):
            self.fs_speed_button.set_label(f"⚡ {rate_str}")

    def build_speed_popover(self, parent_btn):
        """재생 속도 선택 팝오버 메뉴를 구성합니다."""
        if getattr(self, "speed_popover", None):
            try:
                self.speed_popover.destroy()
            except Exception:
                pass
            self.speed_popover = None

        self.speed_popover = Gtk.Popover(relative_to=parent_btn)
        self.speed_popover.set_position(Gtk.PositionType.TOP)
        self.speed_popover.set_border_width(12)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        title = Gtk.Label(label="⚡ 재생 속도 조절", xalign=0)
        title.get_style_context().add_class("popover-title")
        container.pack_start(title, False, False, 2)

        # 프리셋 속도 버튼 목록
        presets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        presets_box.get_style_context().add_class("sub-btn-row")
        for spd in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]:
            btn = Gtk.Button(label=f"{spd}x")
            if abs(self.playback_rate - spd) < 0.01:
                btn.get_style_context().add_class("primary")
            btn.connect("clicked", lambda _b, s=spd: (self.set_playback_rate(s), self.speed_popover.popdown()))
            presets_box.pack_start(btn, True, True, 0)
        container.pack_start(presets_box, False, False, 2)

        # 미세 조절 바
        step_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        step_box.get_style_context().add_class("sub-btn-row")

        dec_btn = Gtk.Button(label="˗ 느리게 (-0.25x)")
        dec_btn.connect("clicked", lambda _b: self.step_playback_rate(-0.25))
        step_box.pack_start(dec_btn, True, True, 0)

        reset_btn = Gtk.Button(label="1.0x (기본)")
        reset_btn.connect("clicked", lambda _b: (self.reset_playback_rate(), self.speed_popover.popdown()))
        step_box.pack_start(reset_btn, True, True, 0)

        inc_btn = Gtk.Button(label="˖ 빠르게 (+0.25x)")
        inc_btn.connect("clicked", lambda _b: self.step_playback_rate(0.25))
        step_box.pack_start(inc_btn, True, True, 0)

        container.pack_start(step_box, False, False, 2)

        hint = Gtk.Label(label="단축키: Up/Down 또는 d/a (속도 조절), r (1.0x 복원)", xalign=0)
        hint.get_style_context().add_class("muted")
        container.pack_start(hint, False, False, 2)

        container.show_all()
        self.speed_popover.add(container)

        def on_pop_closed(_pop):
            self.is_popover_open = False
        self.speed_popover.connect("closed", on_pop_closed)

    def on_speed_button_clicked(self, widget):
        self.build_speed_popover(widget)
        self.is_popover_open = True
    def on_video_scroll_event(self, widget, event):
        """
        비디오 화면 영역 내에서만 마우스 휠 스크롤 시 10초 앞/뒤로 Seek 이동합니다.
        플레이리스트 사이드바나 컨트롤바 등의 스크롤과 완전히 물리적으로 격리됩니다.
        """
        if getattr(self, "is_mouse_over_fs_controls", False) or getattr(self, "is_popover_open", False):
            return False

        if event.direction == Gdk.ScrollDirection.UP:
            self.seek_relative(10)
            return True
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.seek_relative(-10)
            return True
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            if event.delta_y < -0.1:
                self.seek_relative(10)
                return True
            elif event.delta_y > 0.1:
                self.seek_relative(-10)
                return True
        return False

    def on_video_button_press(self, widget, event):
        """
        비디오 화면 영역 클릭 처리:
        - 좌클릭 싱글: 재생 / 일시정지 (250ms 디바운스로 더블클릭과 분리)
        - 좌클릭 더블: 영상 전체화면 전환 토글
        - 우클릭: 빠른 조작 컨텍스트 메뉴 표시
        """
        if getattr(self, "is_mouse_over_fs_controls", False) or getattr(self, "is_popover_open", False):
            return False

        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            if self.click_timer_id is not None:
                try:
                    GLib.source_remove(self.click_timer_id)
                except Exception:
                    pass
                self.click_timer_id = None
            self.toggle_fullscreen()
            return True

        elif event.type == Gdk.EventType.BUTTON_PRESS:
            if event.button == 1:
                if self.click_timer_id is not None:
                    try:
                        GLib.source_remove(self.click_timer_id)
                    except Exception:
                        pass
                self.click_timer_id = GLib.timeout_add(250, self._handle_single_click)
                return True
            elif event.button == 3:
                self.show_context_menu(event)
                return True

        return False

    def _handle_single_click(self):
        self.click_timer_id = None
        self.toggle_play_pause()
        return False

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

    def toggle_mute(self):
        """음소거 상태를 토글합니다."""
        self.is_muted = not self.is_muted
        if self.is_muted:
            if hasattr(self, "volume_scale"):
                self.pre_mute_volume = self.volume_scale.get_value()
                self.volume_scale.set_value(0)
            if getattr(self, "fs_volume_scale", None):
                self.fs_volume_scale.set_value(0)
            if self.pipeline:
                self.pipeline.set_property("volume", 0.0)
            self.show_osd("🔇 음소거")
            lbl = "🔇"
        else:
            restore_val = self.pre_mute_volume if self.pre_mute_volume > 0 else 50
            if hasattr(self, "volume_scale"):
                self.volume_scale.set_value(restore_val)
            if getattr(self, "fs_volume_scale", None):
                self.fs_volume_scale.set_value(restore_val)
            if self.pipeline:
                self.pipeline.set_property("volume", restore_val / 100.0)
            self.show_osd(f"🔊 볼륨: {int(restore_val)}%")
            lbl = "◖)))"
        if getattr(self, "mute_btn", None):
            self.mute_btn.set_label(lbl)
        if getattr(self, "fs_mute_btn", None):
            self.fs_mute_btn.set_label(lbl)

    def cycle_repeat_mode(self):
        """재생 모드를 순환 전환합니다 (전체 반복 -> 1곡 반복 -> 순차 후 정지 -> 셔플)."""
        modes = ["all", "one", "none", "shuffle"]
        cur_idx = modes.index(self.repeat_mode) if self.repeat_mode in modes else 0
        new_mode = modes[(cur_idx + 1) % len(modes)]
        self.set_repeat_mode(new_mode)

    def set_repeat_mode(self, mode):
        self.repeat_mode = mode
        icons = {
            "all": ("🔁 전체 반복", "🔁"),
            "one": ("🔂 1곡 반복", "🔂"),
            "none": ("➡️ 순차 재생 후 정지", "➡️"),
            "shuffle": ("🔀 셔플 무작위 재생", "🔀")
        }
        name, icon = icons.get(mode, ("🔁 전체 반복", "🔁"))
        self.show_osd(name)
        if getattr(self, "repeat_btn", None):
            self.repeat_btn.set_label(icon)
            self.repeat_btn.set_tooltip_text(f"재생 모드: {name}")

    def cycle_audio_track(self):
        """오디오 트랙을 순환 변경합니다."""
        if not self.pipeline:
            return
        try:
            n_audio = self.pipeline.get_property("n-audio")
            self.n_audio_tracks = n_audio
            if n_audio <= 1:
                self.show_osd("🎵 오디오 트랙: 단일 트랙")
                return
            cur = self.pipeline.get_property("current-audio")
            next_track = (cur + 1) % n_audio
            self.set_audio_track(next_track)
        except Exception:
            pass

    def set_audio_track(self, track_idx):
        if not self.pipeline:
            return
        try:
            self.pipeline.set_property("current-audio", track_idx)
            self.current_audio_track = track_idx
            self.show_osd(f"🎵 오디오 트랙 {track_idx + 1}/{max(1, self.n_audio_tracks)}")
            print(f"🎵 [오디오 트랙 변경] 트랙 {track_idx + 1}/{max(1, self.n_audio_tracks)}")
        except Exception as e:
            print(f"⚠️ 오디오 트랙 변경 실패: {e}")

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
        
        decoders = ", ".join(self.decoder_names) if self.decoder_names else "감지 중..."
        hw_str = "⚡ NVDEC 하드웨어 가속" if "nvv4l2" in decoders.lower() else "💻 소프트웨어 디코딩"
        
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

    def open_file_dialog(self):
        """파일 선택 다이얼로그를 띄워 새 동영상을 선택 및 재생합니다."""
        dialog = Gtk.FileChooserDialog(
            title="동영상 파일 열기",
            parent=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        dialog.set_select_multiple(True)

        filter_video = Gtk.FileFilter()
        filter_video.set_name("동영상 파일")
        for ext in ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.webm", "*.ts", "*.m4v"]:
            filter_video.add_pattern(ext)
            filter_video.add_pattern(ext.upper())
        dialog.add_filter(filter_video)

        filter_all = Gtk.FileFilter()
        filter_all.set_name("모든 파일")
        filter_all.add_pattern("*")
        dialog.add_filter(filter_all)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filenames = dialog.get_filenames()
            dialog.destroy()
            if filenames:
                self.load_files(filenames)
        else:
            dialog.destroy()

    def open_folder_dialog(self):
        """폴더 선택 다이얼로그를 띄워 폴더 내 영상들을 재생목록으로 구성합니다."""
        dialog = Gtk.FileChooserDialog(
            title="동영상 폴더 열기",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK
        )
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            folder = dialog.get_filename()
            dialog.destroy()
            if folder:
                self.load_path(folder)
        else:
            dialog.destroy()

    def load_path(self, input_path):
        """새로운 파일 또는 폴더 경로를 로드하여 즉시 재생을 시작합니다."""
        self.input_path = input_path
        self.build_playlist()
        self.populate_playlist_tree()
        self.refresh_playlist_ui()
        if self.playlist:
            self.current_index = 0
            if getattr(self, "placeholder_box", None):
                self.placeholder_box.hide()
            self.play_current_video()

    def load_files(self, files):
        """다중 파일 목록을 재생목록에 추가하고 재생을 시작합니다."""
        if not files:
            return
        video_exts = {'.webm', '.mp4', '.mkv', '.mov', '.avi', '.ts', '.m4v'}
        valid_files = [f for f in files if os.path.splitext(f)[1].lower() in video_exts]
        if not valid_files:
            return
        self.playlist = sorted(valid_files)
        self.input_path = os.path.dirname(valid_files[0]) if len(valid_files) > 1 else valid_files[0]
        self.current_index = 0
        self.is_single_file_mode = (len(valid_files) == 1)
        self.populate_playlist_tree()
        self.refresh_playlist_ui()
        if getattr(self, "placeholder_box", None):
            self.placeholder_box.hide()
        self.play_current_video()

    def on_drag_data_received(self, widget, context, x, y, data, info, time):
        """파일 탐색기에서 드롭된 파일/폴더를 처리합니다."""
        uris = data.get_uris()
        if not uris:
            context.finish(False, False, time)
            return

        paths = []
        for uri in uris:
            if uri.startswith("file://"):
                p = unquote(uri[7:])
                if os.path.exists(p):
                    paths.append(p)

        if not paths:
            context.finish(False, False, time)
            return

        first = paths[0]
        sub_exts = {'.srt', '.smi', '.vtt', '.ass', '.ssa', '.sub'}
        ext = os.path.splitext(first)[1].lower()

        # 자막 파일이 드롭된 경우: 현재 재생 영상에 자막 추가 적용
        if ext in sub_exts:
            evs = parse_subtitle_file_events(first)
            if evs:
                idx = len(self.available_subtitles)
                color = get_subtitle_color(first, idx)
                lbl = get_subtitle_label(first)
                self.available_subtitles.append({
                    'path': first,
                    'label': lbl,
                    'color': color,
                    'events': evs
                })
                self.active_subtitle_indices.add(idx)
                self.has_subtitles = True
                self.subtitles_enabled = True
                self.schedule_subtitles_reload()
                self.show_osd(f"💬 자막 추가됨: {lbl}")
                print(f"💬 드래그로 자막 추가: {first}")
            context.finish(True, False, time)
            return

        # 디렉토리가 드롭된 경우
        if os.path.isdir(first):
            self.load_path(first)
            context.finish(True, False, time)
            return

        # 동영상 파일들이 드롭된 경우
        video_exts = {'.webm', '.mp4', '.mkv', '.mov', '.avi', '.ts', '.m4v'}
        video_files = [p for p in paths if os.path.splitext(p)[1].lower() in video_exts]
        if video_files:
            self.load_files(video_files)
            context.finish(True, False, time)
            return

        context.finish(False, False, time)

    def show_help_dialog(self):
        """단축키 가이드 다이얼로그를 표시합니다."""
        dialog = Gtk.Dialog(
            title="단축키 안내",
            parent=self,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT
        )
        dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        dialog.set_default_size(520, 560)

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

        shortcuts = [
            ("Space / 마우스 좌클릭", "재생 / 일시정지"),
            ("Left / Right (J / L)", "10초 뒤로 / 앞으로 (Shift 조합 시 30초)"),
            ("마우스 휠 위 / 아래", "비디오 영역 10초 앞으로 / 뒤로 Seek"),
            ("Up / Down 또는 D / A", "재생 속도 증가 / 감소 (+0.25x / -0.25x)"),
            ("R", "재생 속도 1.0x 기본값 복원"),
            ("Shift+Up / Down 또는 0 / 9", "볼륨 5% 올리기 / 내리기"),
            ("M", "음소거 (Mute) 켜기 / 끄기"),
            ("P / N", "이전 / 다음 영상"),
            ("F / 마우스 더블클릭", "영상 전용 전체화면 토글"),
            ("T", "항상 위에 표시 (Always on Top) 토글"),
            ("S", "자막 전체 켜기 / 끄기"),
            ("C", "다중 자막 선택 및 크기/싱크 조절 창 열기"),
            ("[ / ]", "자막 크기 축소 / 확대 (-10% / +10%)"),
            ("Z / X", "자막 싱크 앞당김 / 늦춤 (-0.5s / +0.5s)"),
            (", / .", "자막 싱크 미세 조절 (-0.1s / +0.1s)"),
            ("Shift+A", "오디오 트랙 변경 (다중 음성 지원 영상)"),
            ("Shift+Z / Shift+X", "오디오(AV) 싱크 50ms 앞당김 / 늦춤"),
            ("Shift+C", "오디오(AV) 싱크 0ms 초기화"),
            ("Shift+[ / Shift+]", "A-B 구간 반복 시작점(A) / 끝점(B) 설정"),
            ("\\ (백슬래시)", "A-B 구간 반복 해제"),
            ("Ctrl+S", "현재 프레임 무손실 스크린샷 캡처"),
            ("B / Ctrl+B", "현재 위치 북마크 추가 / 북마크 목록 보기"),
            ("Shift+R", "재생 모드 순환 (전체반복/1곡반복/정지/셔플)"),
            ("I", "미디어 정보 및 실시간 하드웨어 통계 HUD"),
            ("Ctrl+O / Ctrl+Shift+O", "파일 열기 / 폴더 열기"),
            ("마우스 우클릭", "빠른 메뉴 (컨텍스트 메뉴)"),
            ("F1 또는 ?", "단축키 도움말 (현재 창)"),
            ("Esc", "전체화면 해제 (일반 창에서는 종료)"),
            ("Q", "프로그램 종료"),
        ]

        for row, (key, desc) in enumerate(shortcuts):
            k_lbl = Gtk.Label(label=key, xalign=0)
            k_lbl.get_style_context().add_class("primary")
            d_lbl = Gtk.Label(label=desc, xalign=0)
            grid.attach(k_lbl, 0, row, 1, 1)
            grid.attach(d_lbl, 1, row, 1, 1)

        scrolled.add(grid)
        box.pack_start(scrolled, True, True, 0)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def on_scale_change_value(self, scale, scroll_type, value):
        """슬라이더 드래그 중 실시간으로 위치 라벨을 업데이트합니다."""
        if self.is_seeking and self.duration_ns > 0:
            target = int(self.duration_ns * value / 100)
            self.position_label.set_text(self.format_time(target))
            if getattr(self, "fs_position_label", None):
                self.fs_position_label.set_text(self.format_time(target))
        return False

    def build_fs_controls(self):
        """전체화면(Fullscreen) 모드 전용 플로팅 컨트롤 바 위젯을 생성합니다."""
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        panel.get_style_context().add_class("fs-controls")

        # 타임라인
        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.fs_position_label = Gtk.Label(label="00:00")
        self.fs_position_label.get_style_context().add_class("muted")

        self.fs_progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.fs_progress_scale.set_draw_value(False)
        self.fs_progress_scale.set_hexpand(True)
        self.fs_progress_scale.connect("button-press-event", self.on_seek_start)
        self.fs_progress_scale.connect("button-release-event", self.on_fs_seek_end)
        self.fs_progress_scale.connect("change-value", self.on_scale_change_value)

        self.fs_duration_label = Gtk.Label(label="00:00")
        self.fs_duration_label.get_style_context().add_class("muted")

        timeline.pack_start(self.fs_position_label, False, False, 0)
        timeline.pack_start(self.fs_progress_scale, True, True, 0)
        timeline.pack_start(self.fs_duration_label, False, False, 0)
        panel.pack_start(timeline, False, False, 0)

        # 액션 버튼 열
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        prev_btn = Gtk.Button(label="⏮")
        prev_btn.set_tooltip_text("이전 영상 (P)")
        prev_btn.connect("clicked", lambda _b: self.play_prev_video())

        rewind_btn = Gtk.Button(label="↶ 10")
        rewind_btn.set_tooltip_text("10초 뒤로 (←)")
        rewind_btn.connect("clicked", lambda _b: self.seek_relative(-10))

        self.fs_play_button = Gtk.Button(label="Ⅱ")
        self.fs_play_button.get_style_context().add_class("primary")
        self.fs_play_button.set_tooltip_text("재생/일시정지 (Space)")
        self.fs_play_button.connect("clicked", lambda _b: self.toggle_play_pause())

        forward_btn = Gtk.Button(label="10 ↷")
        forward_btn.set_tooltip_text("10초 앞으로 (→)")
        forward_btn.connect("clicked", lambda _b: self.seek_relative(10))

        next_btn = Gtk.Button(label="⏭")
        next_btn.set_tooltip_text("다음 영상 (N)")
        next_btn.connect("clicked", lambda _b: self.play_next_video())

        for b in (prev_btn, rewind_btn, self.fs_play_button, forward_btn, next_btn):
            actions.pack_start(b, False, False, 0)

        # 속도 조절
        fs_speed_down = Gtk.Button(label="˗")
        fs_speed_down.set_tooltip_text("재생 속도 감소 (단축키: Down 또는 a)")
        fs_speed_down.connect("clicked", lambda _b: self.step_playback_rate(-0.25))

        self.fs_speed_button = Gtk.Button(label="1.0x")
        self.fs_speed_button.get_style_context().add_class("speed-btn")
        self.fs_speed_button.set_tooltip_text("재생 속도 조절 (단축키: Up/Down 또는 d/a, r: 1.0x)")
        self.fs_speed_button.connect("clicked", self.on_speed_button_clicked)

        fs_speed_up = Gtk.Button(label="˖")
        fs_speed_up.set_tooltip_text("재생 속도 증가 (단축키: Up 또는 d)")
        fs_speed_up.connect("clicked", lambda _b: self.step_playback_rate(0.25))

        actions.pack_start(fs_speed_down, False, False, 0)
        actions.pack_start(self.fs_speed_button, False, False, 0)
        actions.pack_start(fs_speed_up, False, False, 0)

        spacer = Gtk.Box()
        actions.pack_start(spacer, True, True, 0)

        # 볼륨 및 음소거
        self.fs_mute_btn = Gtk.Button(label="◖)))")
        self.fs_mute_btn.set_tooltip_text("음소거 (M)")
        self.fs_mute_btn.connect("clicked", lambda _b: self.toggle_mute())
        actions.pack_start(self.fs_mute_btn, False, False, 2)

        self.fs_volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 1)
        self.fs_volume_scale.set_size_request(90, -1)
        self.fs_volume_scale.set_draw_value(False)
        self.fs_volume_scale.set_value(100)
        self.fs_volume_scale.connect("value-changed", self.on_fs_volume_changed)
        actions.pack_start(self.fs_volume_scale, False, False, 0)

        # 창 모드로 복귀
        fs_toggle_btn = Gtk.Button(label="⧉")
        fs_toggle_btn.set_tooltip_text("창 모드로 복귀 (F / Esc)")
        fs_toggle_btn.connect("clicked", lambda _b: self.toggle_fullscreen())
        actions.pack_end(fs_toggle_btn, False, False, 0)

        # 자막
        self.fs_sub_button = Gtk.Button(label="💬 자막")
        self.fs_sub_button.set_tooltip_text("자막 켜기/끄기 (S)")
        self.fs_sub_button.connect("clicked", self.on_sub_button_clicked)
        actions.pack_end(self.fs_sub_button, False, False, 2)

        # 북마크
        fs_bm_btn = Gtk.Button(label="🔖 북마크")
        fs_bm_btn.set_tooltip_text("북마크 목록 보기 / 추가 (B)")
        fs_bm_btn.connect("clicked", lambda b: self.show_bookmarks_popover(b))
        actions.pack_end(fs_bm_btn, False, False, 2)

        # 무손실 스크린샷 캡처
        fs_cap_btn = Gtk.Button(label="📸 캡처")
        fs_cap_btn.set_tooltip_text("현재 프레임 무손실 스크린샷 저장 (Ctrl+S / C)")
        fs_cap_btn.connect("clicked", lambda _b: self.capture_screenshot())
        actions.pack_end(fs_cap_btn, False, False, 2)

        panel.pack_start(actions, False, False, 0)

        panel.connect("enter-notify-event", self._on_fs_controls_enter)
        panel.connect("leave-notify-event", self._on_fs_controls_leave)

        return panel

    def _on_fs_controls_enter(self, widget, event):
        self.is_mouse_over_fs_controls = True
        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        return False

    def _on_fs_controls_leave(self, widget, event):
        self.is_mouse_over_fs_controls = False
        if self.is_video_only:
            if getattr(self, "cursor_hide_timer_id", None):
                try:
                    GLib.source_remove(self.cursor_hide_timer_id)
                except Exception:
                    pass
            self.cursor_hide_timer_id = GLib.timeout_add(2500, self._on_hide_timer_tick)
        return False

    def on_fs_seek_end(self, scale, _event):
        if self.pipeline and self.duration_ns > 0:
            target = int(self.duration_ns * scale.get_value() / 100)
            self.last_known_pos_ns = target
            self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                Gst.SeekType.SET,
                target,
                Gst.SeekType.NONE,
                -1
            )
            self.show_osd(f"⏱️ {self.format_time(target)} / {self.format_time(self.duration_ns)}")
        self.is_seeking = False
        return False

    def on_fs_volume_changed(self, scale):
        val = scale.get_value()
        if self.is_muted and val > 0:
            self.is_muted = False
            if getattr(self, "mute_btn", None):
                self.mute_btn.set_label("◖)))")
            if getattr(self, "fs_mute_btn", None):
                self.fs_mute_btn.set_label("◖)))")
        if hasattr(self, "volume_scale") and abs(self.volume_scale.get_value() - val) > 0.5:
            self.volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)
        boost_str = " (부스트)" if val > 100 else ""
        self.show_osd(f"🔊 볼륨: {int(val)}%{boost_str}")

    def build_ui(self):
        """Jetson EGL 출력과 충돌하지 않는 네이티브 GTK 플레이어 UI를 구성합니다."""
        css = b"""
        window { background: #090b10; color: #f4f6fb; }
        .topbar, .controls { background: #11151d; }
        .topbar { border-bottom: 1px solid #252b36; }
        .topbar button { padding: 4px 8px; font-size: 12px; }
        separator.topbar-sep { background-color: #252b36; min-width: 1px; margin: 4px 3px; }
        .controls { border-top: 1px solid #252b36; }
        .brand { font-size: 15px; font-weight: 800; color: #ffffff; letter-spacing: 1px; }
        .muted { color: #8f98a8; font-size: 12px; }
        .now-playing { color: #dce2ec; font-size: 13px; font-weight: 500; }
        button { background: transparent; color: #dce2ec; border: 0; border-radius: 7px; padding: 6px 10px; font-size: 13px; }
        button:hover { background: #252b36; color: #ffffff; }
        .primary { background: #e9ff5b; color: #111318; border-radius: 20px; min-width: 28px; min-height: 28px; }
        .primary:hover { background: #f2ff91; color: #111318; }
        .ab-badge { background: #2e1065; color: #e9ff5b; border: 1px solid #7c3aed; border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: bold; }
        .ab-badge:hover { background: #4c1d95; color: #ffffff; }
        .ph-btn-primary { background: #e9ff5b; color: #111318; font-size: 13px; font-weight: 700; padding: 9px 18px; border-radius: 8px; }
        .ph-btn-primary:hover { background: #f2ff91; }
        .ph-btn-sub { background: #1c222e; color: #f0f4fc; font-size: 13px; font-weight: 600; padding: 9px 18px; border-radius: 8px; border: 1px solid #333d4e; }
        .ph-btn-sub:hover { background: #283244; color: #ffffff; }
        .sidebar { background: #0e1117; border-left: 1px solid #252b36; }
        .section-title { font-size: 15px; font-weight: 700; color: #ffffff; }
        .playlist-row { border-radius: 8px; padding: 7px; }
        .playlist-row:hover { background: #1a1f29; }
        .playlist-row-active { background: #242b35; border-left: 3px solid #e9ff5b; }
        .track-number { color: #70798a; font-size: 12px; }
        .track-title { color: #dce2ec; font-size: 13px; }
        scale trough { background: #303744; min-height: 4px; border-radius: 3px; }
        scale highlight { background: #e9ff5b; border-radius: 3px; }
        scale slider { background: #ffffff; min-width: 13px; min-height: 13px; border-radius: 7px; }
        popover { background: #131822; border: 1px solid #2a3240; border-radius: 9px; color: #f4f6fb; padding: 6px; }
        .popover-title { font-size: 13px; font-weight: 700; color: #e9ff5b; margin-bottom: 4px; }
        .sub-btn-row button { background: #1c222e; border-radius: 5px; padding: 4px 8px; font-size: 11px; }
        .sub-btn-row button:hover { background: #2a3344; }
        checkbutton { color: #dce2ec; font-size: 12px; }
        checkbutton:hover { color: #ffffff; }
        .fs-controls { background: rgba(17, 21, 29, 0.92); border: 1px solid #303744; border-radius: 12px; padding: 8px 14px; margin: 12px; }
        .osd-box { background: rgba(14, 17, 23, 0.90); border: 1px solid #3b4455; border-radius: 9px; padding: 10px 24px; margin-top: 25px; }
        .osd-text { font-size: 19px; font-weight: 800; color: #e9ff5b; }
        .hud-box { background: rgba(10, 14, 22, 0.92); border: 1px solid #3b4455; border-radius: 10px; padding: 14px 18px; margin: 16px; }
        .hud-text { font-family: monospace; font-size: 13px; color: #e9ff5b; }
        .speed-btn { font-weight: 700; color: #e9ff5b; min-width: 48px; }
        .speed-btn:hover { background: #252b36; }
        entry { background-color: #161b24; color: #dce2ec; border: 1px solid #2a3344; border-radius: 6px; padding: 5px 8px; font-size: 12px; }
        entry:focus { border-color: #e9ff5b; }
        treeview {
            background-color: #0e1117;
            color: #dce2ec;
            border: none;
            font-size: 13px;
        }
        treeview:selected {
            background-color: #242b35;
            color: #ffffff;
        }
        treeview:hover {
            background-color: #161b24;
        }
        treeview.view {
            background-color: #0e1117;
            color: #dce2ec;
        }
        treeview.view:selected {
            background-color: #242b35;
            color: #ffffff;
        }
        .tree-tool-btn {
            background: #1a202c;
            border-radius: 5px;
            padding: 3px 8px;
            font-size: 11px;
            color: #a0aec0;
        }
        .tree-tool-btn:hover {
            background: #2d3748;
            color: #ffffff;
        }
        .tree-tool-btn.active {
            background: #e9ff5b;
            color: #111318;
            font-weight: bold;
        }
        .tree-tool-btn.active:hover {
            background: #f2ff91;
            color: #111318;
        }
        paned > separator {
            background-color: #252b36;
            min-width: 5px;
            margin: 0;
        }
        paned > separator:hover {
            background-color: #e9ff5b;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        def make_topbar_sep():
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            sep.get_style_context().add_class("topbar-sep")
            return sep

        self.topbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.topbar.get_style_context().add_class("topbar")
        self.topbar.set_border_width(6)
        
        brand = Gtk.Label(label="JETSON VIDEO PLAYER")
        brand.get_style_context().add_class("brand")
        self.topbar.pack_start(brand, False, False, 4)
        self.topbar.pack_start(make_topbar_sep(), False, False, 2)

        # 상단 빠른 조작 툴바 - 그룹 1: 파일 / 폴더 / 최근 열기
        open_file_btn = Gtk.Button(label="📂 파일")
        open_file_btn.set_tooltip_text("동영상 파일 열기 (Ctrl+O)")
        open_file_btn.connect("clicked", lambda _b: self.open_file_dialog())
        self.topbar.pack_start(open_file_btn, False, False, 0)

        open_dir_btn = Gtk.Button(label="📁 폴더")
        open_dir_btn.set_tooltip_text("동영상 폴더 열기 (Ctrl+Shift+O)")
        open_dir_btn.connect("clicked", lambda _b: self.open_folder_dialog())
        self.topbar.pack_start(open_dir_btn, False, False, 0)

        recent_btn = Gtk.Button(label="🕒 최근")
        recent_btn.set_tooltip_text("최근 재생한 영상/폴더 열기")
        recent_btn.connect("clicked", lambda _b: self.show_history_popover(recent_btn))
        self.topbar.pack_start(recent_btn, False, False, 0)

        self.yt_btn = Gtk.Button(label="▶️ 유튜브")
        self.yt_btn.set_tooltip_text("유튜브 영상 다운로드 / 바로 재생")
        self.yt_btn.connect("clicked", lambda _b: self.show_youtube_popover(self.yt_btn))
        self.topbar.pack_start(self.yt_btn, False, False, 0)

        self.topbar.pack_start(make_topbar_sep(), False, False, 2)

        # 그룹 2: 북마크 / 무손실 캡처 / 스마트폰 리모컨
        bookmark_btn = Gtk.Button(label="🔖 북마크")
        bookmark_btn.set_tooltip_text("현재 영상 북마크 목록 보기 (Ctrl+B) / 추가 (B)")
        bookmark_btn.connect("clicked", lambda _b: self.show_bookmarks_popover(bookmark_btn))
        self.topbar.pack_start(bookmark_btn, False, False, 0)

        screenshot_btn = Gtk.Button(label="📸 캡처")
        screenshot_btn.set_tooltip_text("현재 프레임 무손실 스크린샷 저장 (Ctrl+S)")
        screenshot_btn.connect("clicked", lambda _b: self.capture_screenshot())
        self.topbar.pack_start(screenshot_btn, False, False, 0)

        remote_btn = Gtk.Button(label="📱 리모컨")
        remote_btn.set_tooltip_text("스마트폰 웹 리모컨 접속 안내")
        remote_btn.connect("clicked", lambda _b: self.show_remote_popover(remote_btn))
        self.topbar.pack_start(remote_btn, False, False, 0)

        self.topbar.pack_start(make_topbar_sep(), False, False, 2)

        # 그룹 3: 재생 모드 / 미디어 HUD / 도움말
        self.repeat_btn = Gtk.Button(label="🔁")
        self.repeat_btn.set_tooltip_text("재생 모드 (전체반복/1곡반복/정지/셔플) (Shift+R)")
        self.repeat_btn.connect("clicked", lambda _b: self.cycle_repeat_mode())
        self.topbar.pack_start(self.repeat_btn, False, False, 0)

        hud_toggle_btn = Gtk.Button(label="ℹ️")
        hud_toggle_btn.set_tooltip_text("미디어 정보 및 하드웨어 모니터링 HUD (I)")
        hud_toggle_btn.connect("clicked", lambda _b: self.toggle_hud())
        self.topbar.pack_start(hud_toggle_btn, False, False, 0)

        help_btn = Gtk.Button(label="❓")
        help_btn.set_tooltip_text("단축키 안내 (F1)")
        help_btn.connect("clicked", lambda _b: self.show_help_dialog())
        self.topbar.pack_start(help_btn, False, False, 0)

        self.topbar.pack_start(make_topbar_sep(), False, False, 2)

        self.now_playing_label = Gtk.Label(xalign=0)
        self.now_playing_label.set_ellipsize(3)
        self.now_playing_label.get_style_context().add_class("now-playing")
        self.topbar.pack_start(self.now_playing_label, True, True, 8)

        playlist_toggle = Gtk.Button(label="☷  재생목록")
        playlist_toggle.set_tooltip_text("재생목록 열기/닫기")
        playlist_toggle.connect("clicked", self.on_playlist_toggle)
        self.topbar.pack_end(playlist_toggle, False, False, 0)

        close_button = Gtk.Button(label="✕")
        close_button.set_tooltip_text("종료 (Q / Esc)")
        close_button.connect("clicked", self.on_destroy)
        self.topbar.pack_end(close_button, False, False, 0)
        root.pack_start(self.topbar, False, False, 0)

        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)

        # 비디오 위젯 및 오버레이(OSD, 전체화면 플로팅 컨트롤) 컨테이너
        self.video_container = Gtk.Overlay()

        # 비디오 이벤트 박스 (마우스 휠 Scroll Seek 및 화면 클릭 격리)
        self.video_event_box = Gtk.EventBox()
        self.video_event_box.set_visible_window(False)
        self.video_event_box.add_events(
            Gdk.EventMask.SCROLL_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.video_event_box.connect("scroll-event", self.on_video_scroll_event)
        self.video_event_box.connect("button-press-event", self.on_video_button_press)
        self.video_event_box.add(self.video_widget)
        self.video_container.add(self.video_event_box)

        # 0) 플레이스홀더 (빈 화면 안내)
        self.placeholder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.placeholder_box.set_halign(Gtk.Align.CENTER)
        self.placeholder_box.set_valign(Gtk.Align.CENTER)
        ph_icon = Gtk.Label()
        ph_icon.set_markup("<span font='54'>🎬</span>")
        ph_title = Gtk.Label()
        ph_title.set_markup("<span font='16' weight='bold' color='#dce2ec'>재생할 동영상 또는 폴더를 드래그 앤 드롭하세요</span>")
        ph_sub = Gtk.Label(label="상단의 빠른 조작 바 또는 아래 버튼으로 즉시 선택할 수 있습니다 (단축키: Ctrl+O)")
        ph_sub.get_style_context().add_class("muted")

        ph_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ph_btn_box.set_halign(Gtk.Align.CENTER)

        ph_open_file = Gtk.Button(label="📂 동영상 파일 열기")
        ph_open_file.get_style_context().add_class("ph-btn-primary")
        ph_open_file.connect("clicked", lambda _b: self.open_file_dialog())

        ph_open_dir = Gtk.Button(label="📁 폴더 열기")
        ph_open_dir.get_style_context().add_class("ph-btn-sub")
        ph_open_dir.connect("clicked", lambda _b: self.open_folder_dialog())

        ph_open_yt = Gtk.Button(label="▶️ 유튜브 영상 재생")
        ph_open_yt.get_style_context().add_class("ph-btn-sub")
        ph_open_yt.connect("clicked", lambda _b: self.show_youtube_popover(ph_open_yt))

        ph_btn_box.pack_start(ph_open_file, False, False, 0)
        ph_btn_box.pack_start(ph_open_dir, False, False, 0)
        ph_btn_box.pack_start(ph_open_yt, False, False, 0)

        self.placeholder_box.pack_start(ph_icon, False, False, 0)
        self.placeholder_box.pack_start(ph_title, False, False, 0)
        self.placeholder_box.pack_start(ph_sub, False, False, 0)
        self.placeholder_box.pack_start(ph_btn_box, False, False, 4)
        self.placeholder_box.set_no_show_all(True)
        self.video_container.add_overlay(self.placeholder_box)

        # 1) OSD 라벨 오버레이 (화면 상단 중앙)
        self.osd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.osd_box.get_style_context().add_class("osd-box")
        self.osd_box.set_halign(Gtk.Align.CENTER)
        self.osd_box.set_valign(Gtk.Align.START)
        self.osd_label = Gtk.Label()
        self.osd_label.get_style_context().add_class("osd-text")
        self.osd_box.add(self.osd_label)
        self.osd_box.set_no_show_all(True)
        self.video_container.add_overlay(self.osd_box)

        # 2) 미디어 정보 및 실시간 하드웨어 HUD 오버레이 (화면 좌측 상단)
        self.hud_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.hud_box.get_style_context().add_class("hud-box")
        self.hud_box.set_halign(Gtk.Align.START)
        self.hud_box.set_valign(Gtk.Align.START)
        self.hud_box.set_margin_start(16)
        self.hud_box.set_margin_top(16)
        self.hud_label = Gtk.Label(xalign=0)
        self.hud_label.get_style_context().add_class("hud-text")
        self.hud_box.add(self.hud_label)
        self.hud_box.set_no_show_all(True)
        self.video_container.add_overlay(self.hud_box)

        # 3) 전체화면 플로팅 컨트롤 바 오버레이 (화면 하단)
        self.fs_controls_box = self.build_fs_controls()
        self.fs_controls_box.set_halign(Gtk.Align.FILL)
        self.fs_controls_box.set_valign(Gtk.Align.END)
        self.fs_controls_box.set_no_show_all(True)
        self.video_container.add_overlay(self.fs_controls_box)

        self.main_paned.pack1(self.video_container, resize=True, shrink=False)
        self.sidebar = self.build_playlist_panel()
        self.main_paned.pack2(self.sidebar, resize=True, shrink=False)
        self.main_paned.connect("notify::position", self.on_paned_notify_position)
        self.main_paned.connect("size-allocate", self.on_paned_size_allocate)
        root.pack_start(self.main_paned, True, True, 0)

        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.controls.get_style_context().add_class("controls")
        self.controls.set_border_width(10)

        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.position_label = Gtk.Label(label="00:00")
        self.position_label.get_style_context().add_class("muted")
        self.progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.progress_scale.set_draw_value(False)
        self.progress_scale.set_hexpand(True)
        self.progress_scale.connect("button-press-event", self.on_seek_start)
        self.progress_scale.connect("button-release-event", self.on_seek_end)
        self.progress_scale.connect("change-value", self.on_scale_change_value)

        # A-B 구간 반복 상시 시각 배지
        self.ab_badge = Gtk.Button(label="")
        self.ab_badge.get_style_context().add_class("ab-badge")
        self.ab_badge.set_tooltip_text("A-B 구간 반복 활성화 중 (클릭 시 즉시 해제)")
        self.ab_badge.connect("clicked", lambda _b: self.clear_ab_repeat())
        self.ab_badge.set_no_show_all(True)
        self.ab_badge.hide()

        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.get_style_context().add_class("muted")
        timeline.pack_start(self.position_label, False, False, 0)
        timeline.pack_start(self.progress_scale, True, True, 0)
        timeline.pack_start(self.ab_badge, False, False, 4)
        timeline.pack_start(self.duration_label, False, False, 0)
        self.controls.pack_start(timeline, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        prev_button = Gtk.Button(label="⏮")
        prev_button.set_tooltip_text("이전 영상 (P)")
        prev_button.connect("clicked", lambda _button: self.play_prev_video())
        self.play_button = Gtk.Button(label="Ⅱ")
        self.play_button.get_style_context().add_class("primary")
        self.play_button.set_tooltip_text("재생/일시정지 (Space)")
        self.play_button.connect("clicked", lambda _button: self.toggle_play_pause())
        next_button = Gtk.Button(label="⏭")
        next_button.set_tooltip_text("다음 영상 (N)")
        next_button.connect("clicked", lambda _button: self.play_next_video())
        rewind_button = Gtk.Button(label="↶ 10")
        rewind_button.set_tooltip_text("10초 뒤로 (←)")
        rewind_button.connect("clicked", lambda _button: self.seek_relative(-10))
        forward_button = Gtk.Button(label="10 ↷")
        forward_button.set_tooltip_text("10초 앞으로 (→)")
        forward_button.connect("clicked", lambda _button: self.seek_relative(10))
        for button in (prev_button, rewind_button, self.play_button, forward_button, next_button):
            actions.pack_start(button, False, False, 0)

        # 속도 조절 버튼 ([-] 1.0x [+])
        speed_down_btn = Gtk.Button(label="˗")
        speed_down_btn.set_tooltip_text("재생 속도 감소 (단축키: Down 또는 a)")
        speed_down_btn.connect("clicked", lambda _b: self.step_playback_rate(-0.25))
        actions.pack_start(speed_down_btn, False, False, 0)

        self.speed_button = Gtk.Button(label="1.0x")
        self.speed_button.get_style_context().add_class("speed-btn")
        self.speed_button.set_tooltip_text("재생 속도 설정 (단축키: Up/Down 또는 d/a, r: 1.0x)")
        self.speed_button.connect("clicked", self.on_speed_button_clicked)
        actions.pack_start(self.speed_button, False, False, 0)

        speed_up_btn = Gtk.Button(label="˖")
        speed_up_btn.set_tooltip_text("재생 속도 증가 (단축키: Up 또는 d)")
        speed_up_btn.connect("clicked", lambda _b: self.step_playback_rate(0.25))
        actions.pack_start(speed_up_btn, False, False, 0)

        spacer = Gtk.Box()
        actions.pack_start(spacer, True, True, 0)

        # 볼륨 및 음소거 버튼
        self.mute_btn = Gtk.Button(label="◖)))")
        self.mute_btn.set_tooltip_text("음소거 켜기/끄기 (M)")
        self.mute_btn.connect("clicked", lambda _b: self.toggle_mute())
        actions.pack_start(self.mute_btn, False, False, 2)

        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 1)
        self.volume_scale.set_size_request(110, -1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_value(100)
        self.volume_scale.connect("value-changed", self.on_volume_changed)
        actions.pack_start(self.volume_scale, False, False, 0)

        self.fullscreen_button = Gtk.Button(label="⛶")
        self.fullscreen_button.set_tooltip_text("영상만 전체화면 (F)")
        self.fullscreen_button.connect("clicked", lambda _button: self.toggle_fullscreen())
        actions.pack_end(self.fullscreen_button, False, False, 0)

        self.sub_button = Gtk.Button(label="💬 자막")
        self.sub_button.set_tooltip_text("자막 켜기/끄기 (S)")
        self.sub_button.connect("clicked", self.on_sub_button_clicked)
        actions.pack_end(self.sub_button, False, False, 4)

        self.controls.pack_start(actions, False, False, 0)
        root.pack_end(self.controls, False, False, 0)

        if not self.playlist:
            if getattr(self, "placeholder_box", None):
                self.placeholder_box.show_all()

        self.refresh_playlist_ui()

    def build_playlist_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.get_style_context().add_class("sidebar")
        panel.set_size_request(240, -1)
        panel.set_border_width(12)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="재생목록", xalign=0)
        title.get_style_context().add_class("section-title")
        count = Gtk.Label(label=f"{len(self.playlist)}개 영상", xalign=1)
        count.get_style_context().add_class("muted")
        heading.pack_start(title, True, True, 0)
        heading.pack_end(count, False, False, 0)
        panel.pack_start(heading, False, False, 2)

        # 검색창
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("영상 검색...")
        self.search_entry.connect("search-changed", self.on_search_changed)
        panel.pack_start(self.search_entry, False, False, 2)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        if not self.is_single_file_mode:
            exp_btn = Gtk.Button(label="전체 펼치기")
            exp_btn.get_style_context().add_class("tree-tool-btn")
            exp_btn.set_tooltip_text("모든 폴더 펼치기")
            exp_btn.connect("clicked", lambda _b: self.playlist_treeview.expand_all())
            col_btn = Gtk.Button(label="전체 접기")
            col_btn.get_style_context().add_class("tree-tool-btn")
            col_btn.set_tooltip_text("모든 폴더 접기")
            col_btn.connect("clicked", lambda _b: self.collapse_playlist_tree())
            tools.pack_start(exp_btn, True, True, 0)
            tools.pack_start(col_btn, True, True, 0)

        self.wrap_button = Gtk.Button(label="줄바꿈")
        self.wrap_button.get_style_context().add_class("tree-tool-btn")
        self.wrap_button.set_tooltip_text("긴 파일명 자동 줄바꿈 켜기/끄기")
        self.wrap_button.connect("clicked", self.on_wrap_toggle)

        open_loc_btn = Gtk.Button(label="📂 위치")
        open_loc_btn.get_style_context().add_class("tree-tool-btn")
        open_loc_btn.set_tooltip_text("선택 또는 현재 재생 중인 영상의 폴더 위치를 파일 브라우저로 열기")
        open_loc_btn.connect("clicked", lambda _b: self.open_selected_or_current_location())

        if self.is_single_file_mode:
            tools.pack_start(self.wrap_button, True, True, 0)
            tools.pack_start(open_loc_btn, True, True, 0)
        else:
            tools.pack_start(self.wrap_button, False, False, 0)
            tools.pack_start(open_loc_btn, False, False, 0)
        panel.pack_start(tools, False, False, 2)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self.tree_store = Gtk.TreeStore(str, str, str, int, bool)
        self.playlist_treeview = Gtk.TreeView(model=self.tree_store)
        self.playlist_treeview.set_headers_visible(False)
        self.playlist_treeview.set_activate_on_single_click(True)
        self.playlist_treeview.set_has_tooltip(True)
        self.playlist_treeview.connect("query-tooltip", self.on_tree_query_tooltip)
        self.playlist_treeview.connect("size-allocate", self.on_tree_size_allocate)
        self.playlist_treeview.connect("row-activated", self.on_tree_row_activated)
        self.playlist_treeview.connect("row-expanded", self.on_tree_row_expanded)
        self.playlist_treeview.connect("row-collapsed", self.on_tree_row_collapsed)
        self.playlist_treeview.connect("button-press-event", self.on_tree_button_press)

        col = Gtk.TreeViewColumn("Track")
        r_icon = Gtk.CellRendererText()
        r_icon.set_property("xpad", 4)
        col.pack_start(r_icon, False)
        col.add_attribute(r_icon, "text", 0)

        self.r_text = Gtk.CellRendererText()
        self.r_text.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.r_text.set_property("ypad", 6)
        col.pack_start(self.r_text, True)
        col.add_attribute(self.r_text, "markup", 1)
        self.playlist_treeview.append_column(col)

        self.populate_playlist_tree()

        scroll.add(self.playlist_treeview)
        panel.pack_start(scroll, True, True, 0)
        return panel

    def open_selected_or_current_location(self, target_path=None):
        """선택된 재생목록 항목 또는 현재 재생 중인 영상의 폴더 위치를 파일 브라우저로 엽니다."""
        path_to_open = target_path
        if not path_to_open and self.playlist_treeview:
            sel = self.playlist_treeview.get_selection()
            model, tree_iter = sel.get_selected()
            if tree_iter:
                path_to_open = model.get_value(tree_iter, 2)

        if not path_to_open and self.playlist and 0 <= self.current_index < len(self.playlist):
            path_to_open = self.playlist[self.current_index]

        if not path_to_open:
            yt_dir = os.path.expanduser("~/Videos/YouTube")
            if os.path.exists(yt_dir):
                path_to_open = yt_dir
            else:
                self.show_osd("⚠️ 열 위치가 지정되지 않았습니다.")
                return

        success = open_file_location(path_to_open)
        if success:
            dir_name = path_to_open if os.path.isdir(path_to_open) else os.path.dirname(path_to_open)
            self.show_osd(f"📂 폴더 열기: {os.path.basename(dir_name) or dir_name}", duration_sec=2.0)
            print(f"📂 [파일 위치 열기] {path_to_open}")
        else:
            self.show_osd("⚠️ 파일 브라우저를 열지 못했습니다.")

    def open_selected_or_current_location_by_index(self, idx=None):
        target = None
        if idx is not None and 0 <= idx < len(self.playlist):
            target = self.playlist[idx]
        self.open_selected_or_current_location(target)

    def on_tree_button_press(self, treeview, event):
        """재생목록 항목 우클릭 시 컨텍스트 메뉴(파일 위치 열기, 재생, 경로 복사 등)를 표시합니다."""
        if event.button == 3:  # 마우스 우클릭
            path_info = treeview.get_path_at_pos(int(event.x), int(event.y))
            if path_info:
                tree_path, _col, _cell_x, _cell_y = path_info
                tree_iter = self.tree_store.get_iter(tree_path)
                file_path = self.tree_store.get_value(tree_iter, 2)
                item_idx = self.tree_store.get_value(tree_iter, 3)
                is_dir = self.tree_store.get_value(tree_iter, 4)

                menu = Gtk.Menu()

                # 1. 파일 위치 열기
                loc_item = Gtk.MenuItem(label="📂 파일 위치 열기 (파일 브라우저)")
                loc_item.connect("activate", lambda _m: self.open_selected_or_current_location(file_path))
                menu.append(loc_item)

                if not is_dir and item_idx >= 0:
                    # 2. 지금 재생
                    play_item = Gtk.MenuItem(label="▶️ 지금 재생")
                    play_item.connect("activate", lambda _m: self.play_index_direct(item_idx))
                    menu.append(play_item)

                menu.append(Gtk.SeparatorMenuItem())

                # 3. 전체 경로 복사
                copy_path_item = Gtk.MenuItem(label="📋 전체 경로 복사")
                def on_copy_path(_m):
                    cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                    cb.set_text(file_path, -1)
                    self.show_osd("📋 파일 경로가 복사되었습니다!", duration_sec=1.5)
                copy_path_item.connect("activate", on_copy_path)
                menu.append(copy_path_item)

                # 4. 파일 이름 복사
                copy_name_item = Gtk.MenuItem(label="📋 파일 이름 복사")
                def on_copy_name(_m):
                    cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                    cb.set_text(os.path.basename(file_path), -1)
                    self.show_osd("📋 파일 이름이 복사되었습니다!", duration_sec=1.5)
                copy_name_item.connect("activate", on_copy_name)
                menu.append(copy_name_item)

                menu.show_all()
                menu.popup_at_pointer(event)
                return True
        return False

    def on_search_changed(self, entry):
        self.search_text = entry.get_text().strip().lower()
        self.populate_playlist_tree()

    def on_paned_notify_position(self, paned, _gparam):
        """사용자가 스플리터 핸들을 드래그할 때 사이드바 너비를 기억합니다."""
        if self.is_adjusting_paned or not self.sidebar or not self.sidebar.get_visible():
            return
        pos = paned.get_position()
        alloc_w = paned.get_allocation().width
        if alloc_w > 0 and pos > 0:
            current_s_w = alloc_w - pos
            if current_s_w >= 200:
                self.sidebar_width = current_s_w

    def on_paned_size_allocate(self, paned, allocation):
        """창 크기 조절 시 사이드바의 설정된 너비를 정확히 유지합니다."""
        if not self.sidebar or not self.sidebar.get_visible():
            return
        target_pos = max(200, allocation.width - self.sidebar_width)
        if abs(paned.get_position() - target_pos) > 2:
            self.is_adjusting_paned = True
            paned.set_position(target_pos)
            self.is_adjusting_paned = False

    def on_wrap_toggle(self, _button):
        """재생목록 내 긴 파일명의 자동 줄바꿈을 토글합니다."""
        self.is_wrap_enabled = not self.is_wrap_enabled
        if not self.r_text:
            return
        if self.is_wrap_enabled:
            if self.wrap_button:
                self.wrap_button.get_style_context().add_class("active")
            self.r_text.set_property("wrap-mode", Pango.WrapMode.WORD_CHAR)
            self.r_text.set_property("ellipsize", Pango.EllipsizeMode.NONE)
            self.update_tree_wrap_width()
        else:
            if self.wrap_button:
                self.wrap_button.get_style_context().remove_class("active")
            self.r_text.set_property("ellipsize", Pango.EllipsizeMode.END)
            self.r_text.set_property("wrap-width", -1)
        if self.playlist_treeview:
            self.playlist_treeview.queue_resize()

    def update_tree_wrap_width(self):
        """트리뷰 너비에 맞춰 셀 렌더러의 wrap-width를 자동 계산합니다."""
        if not self.is_wrap_enabled or not self.playlist_treeview or not self.r_text:
            return
        alloc = self.playlist_treeview.get_allocation()
        if alloc.width > 50:
            target_w = max(120, alloc.width - 65)
            if self.r_text.get_property("wrap-width") != target_w:
                self.r_text.set_property("wrap-width", target_w)

    def on_tree_size_allocate(self, _widget, allocation):
        """트리뷰 크기 변경 시 줄바꿈 너비를 실시간 동기화합니다."""
        if self.is_wrap_enabled and self.r_text:
            target_w = max(120, allocation.width - 65)
            if self.r_text.get_property("wrap-width") != target_w:
                self.r_text.set_property("wrap-width", target_w)

    def on_tree_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        """재생목록 항목에 마우스 호버 시 전체 파일명 및 경로를 툴팁으로 표시합니다."""
        res = widget.get_tooltip_context(x, y, keyboard_mode)
        if not res:
            return False
        bool_val, bx, by, model, path, tree_iter = res
        if not bool_val or tree_iter is None:
            return False

        try:
            is_dir = model.get_value(tree_iter, 4)
            full_path = model.get_value(tree_iter, 2)
            idx = model.get_value(tree_iter, 3)

            if is_dir:
                dir_name = os.path.basename(full_path)
                safe_name = GLib.markup_escape_text(dir_name)
                safe_path = GLib.markup_escape_text(full_path)
                tooltip.set_markup(
                    f"📁 <b>{safe_name}</b>\n"
                    f"<span color='#8f98a8' size='smaller'>{safe_path}</span>"
                )
            else:
                file_name = os.path.basename(full_path)
                safe_name = GLib.markup_escape_text(file_name)
                safe_path = GLib.markup_escape_text(full_path)
                num_badge = f"<span color='#e9ff5b' weight='bold'>#{idx + 1}</span> " if idx >= 0 else ""
                tooltip.set_markup(
                    f"🎬 {num_badge}<b>{safe_name}</b>\n"
                    f"<span color='#8f98a8' size='smaller'>{safe_path}</span>"
                )
            widget.set_tooltip_row(tooltip, path)
            return True
        except Exception:
            return False

    def on_playlist_toggle(self, _button):
        is_vis = not self.sidebar.get_visible()
        self.sidebar.set_visible(is_vis)
        if is_vis and self.main_paned:
            alloc_w = self.main_paned.get_allocation().width
            if alloc_w > 0:
                self.main_paned.set_position(max(200, alloc_w - self.sidebar_width))

    def populate_playlist_tree(self):
        """재생목록을 디렉토리 계층 구조의 트리로 구축합니다 (검색 필터 지원)."""
        if not self.tree_store:
            return
        self.tree_store.clear()
        self.playlist_tree_iters.clear()

        if not self.playlist:
            return

        abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None

        filtered_items = []
        for idx, p in enumerate(self.playlist):
            fname = os.path.basename(p)
            if self.search_text and (self.search_text not in fname.lower() and self.search_text not in p.lower()):
                continue
            filtered_items.append((idx, p))

        if not abs_root:
            for idx, p in filtered_items:
                fname = os.path.basename(p)
                safe_name = GLib.markup_escape_text(fname)
                v_iter = self.tree_store.append(
                    None,
                    ["🎬", f"<span>{safe_name}</span>", p, idx, False]
                )
                self.playlist_tree_iters[idx] = v_iter
            return

        # 1. 디렉토리별 하위 영상 파일 수 카운트
        dir_counts = {}
        for idx, p in filtered_items:
            rel_p = os.path.relpath(p, abs_root)
            parts = rel_p.split(os.sep)[:-1]
            for i in range(1, len(parts) + 1):
                d = os.sep.join(parts[:i])
                dir_counts[d] = dir_counts.get(d, 0) + 1

        # 2. 계층형 폴더 및 비디오 노드 추가
        dir_iters = {}
        for idx, p in filtered_items:
            rel_p = os.path.relpath(p, abs_root)
            parts = rel_p.split(os.sep)
            fname = parts[-1]
            dir_parts = parts[:-1]

            cur_p = ""
            parent_iter = None
            for d in dir_parts:
                cur_p = os.path.join(cur_p, d) if cur_p else d
                if cur_p not in dir_iters:
                    cnt = dir_counts.get(cur_p, 0)
                    safe_d = GLib.markup_escape_text(d)
                    lbl = f"<b>{safe_d}</b> <span color='#70798a' size='smaller'>({cnt})</span>"
                    d_iter = self.tree_store.append(
                        parent_iter,
                        ["📁", lbl, cur_p, -1, True]
                    )
                    dir_iters[cur_p] = d_iter
                    parent_iter = d_iter
                else:
                    parent_iter = dir_iters[cur_p]

            safe_name = GLib.markup_escape_text(fname)
            v_iter = self.tree_store.append(
                parent_iter,
                ["🎬", f"<span>{safe_name}</span>", p, idx, False]
            )
            self.playlist_tree_iters[idx] = v_iter

        if self.search_text and self.playlist_treeview:
            self.playlist_treeview.expand_all()

    def on_tree_row_activated(self, treeview, path, _column):
        """트리 항목 클릭 시: 폴더는 펼치기/접기 토글, 비디오 파일은 즉시 재생"""
        model = treeview.get_model()
        tree_iter = model.get_iter(path)
        is_dir = model.get_value(tree_iter, 4)
        if is_dir:
            if treeview.row_expanded(path):
                treeview.collapse_row(path)
            else:
                treeview.expand_row(path, False)
        else:
            idx = model.get_value(tree_iter, 3)
            if idx != self.current_index and 0 <= idx < len(self.playlist):
                self.current_index = idx
                self.play_current_video()

    def on_tree_row_expanded(self, _treeview, tree_iter, _path):
        if self.tree_store and self.tree_store.get_value(tree_iter, 4):
            self.tree_store.set_value(tree_iter, 0, "📂")

    def on_tree_row_collapsed(self, _treeview, tree_iter, _path):
        if self.tree_store and self.tree_store.get_value(tree_iter, 4):
            self.tree_store.set_value(tree_iter, 0, "📁")

    def collapse_playlist_tree(self):
        """전체 폴더를 접되, 현재 재생 중인 영상의 폴더는 열어둡니다."""
        if self.playlist_treeview:
            self.playlist_treeview.collapse_all()
            if 0 <= self.current_index < len(self.playlist):
                cur_iter = self.playlist_tree_iters.get(self.current_index)
                if cur_iter and self.tree_store.iter_is_valid(cur_iter):
                    path = self.tree_store.get_path(cur_iter)
                    self.playlist_treeview.expand_to_path(path)
                    self.playlist_treeview.scroll_to_cell(path, None, True, 0.5, 0.0)

    def refresh_playlist_ui(self):
        if not self.playlist:
            return
        current_path = self.playlist[self.current_index]
        abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None
        if abs_root:
            display_name = os.path.relpath(current_path, abs_root)
        else:
            display_name = os.path.basename(current_path)

        self.now_playing_label.set_text(
            f"재생 중  ·  {display_name}   {self.current_index + 1}/{len(self.playlist)}"
        )
        self.now_playing_label.set_tooltip_text(f"{display_name}\n({current_path})")

        if not self.tree_store or not self.playlist_tree_iters:
            return

        active_iter = None
        for idx, tree_iter in self.playlist_tree_iters.items():
            if not self.tree_store.iter_is_valid(tree_iter):
                continue
            path_val = self.tree_store.get_value(tree_iter, 2)
            fname = os.path.basename(path_val)
            safe_name = GLib.markup_escape_text(fname)

            if idx == self.current_index:
                active_iter = tree_iter
                self.tree_store.set_value(tree_iter, 0, "▶")
                self.tree_store.set_value(
                    tree_iter,
                    1,
                    f"<span color='#e9ff5b' weight='bold'>{safe_name}</span>"
                )
            else:
                self.tree_store.set_value(tree_iter, 0, "🎬")
                self.tree_store.set_value(
                    tree_iter,
                    1,
                    f"<span color='#dce2ec'>{safe_name}</span>"
                )

        if active_iter and self.playlist_treeview:
            tree_path = self.tree_store.get_path(active_iter)
            if tree_path:
                self.playlist_treeview.expand_to_path(tree_path)
                sel = self.playlist_treeview.get_selection()
                sel.select_iter(active_iter)
                GLib.idle_add(lambda: self.playlist_treeview.scroll_to_cell(tree_path, None, True, 0.5, 0.0))

    @staticmethod
    def format_time(nanoseconds):
        total_seconds = max(0, int(nanoseconds / Gst.SECOND))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def update_playback_ui(self):
        if not self.pipeline:
            return True
        position_ok, position = self.pipeline.query_position(Gst.Format.TIME)
        if position_ok and position > 0:
            self.last_known_pos_ns = position

            # A-B 구간 반복 루프 검사
            if getattr(self, "is_ab_repeat_active", False) and self.ab_repeat_a is not None and self.ab_repeat_b is not None:
                if position >= self.ab_repeat_b:
                    self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, self.ab_repeat_a)
                    return True

            # 5초 이상 재생 시 이어보기 캐시 갱신
            if self.playlist and 0 <= self.current_index < len(self.playlist):
                resume_cache.set(self.playlist[self.current_index], position, self.duration_ns)

        pos_sec = int(position / Gst.SECOND) if position_ok else -1

        if position_ok and pos_sec != self.last_ui_pos_sec:
            self.last_ui_pos_sec = pos_sec
            time_str = self.format_time(position)

            # 1) 일반 모드 컨트롤 UI 갱신
            if not self.is_video_only:
                self.position_label.set_text(time_str)
                if self.duration_ns == 0:
                    duration_ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
                    if duration_ok and duration > 0:
                        self.duration_ns = duration
                        self.duration_label.set_text(self.format_time(duration))
                if self.duration_ns > 0 and not self.is_seeking:
                    self.progress_scale.set_value(min(100, position * 100 / self.duration_ns))

            # 2) 전체화면 플로팅 컨트롤 UI 갱신
            if getattr(self, "fs_position_label", None):
                self.fs_position_label.set_text(time_str)
            if getattr(self, "fs_duration_label", None):
                if self.duration_ns > 0:
                    self.fs_duration_label.set_text(self.format_time(self.duration_ns))
            if getattr(self, "fs_progress_scale", None) and self.duration_ns > 0 and not self.is_seeking:
                self.fs_progress_scale.set_value(min(100, position * 100 / self.duration_ns))

        # 미디어 HUD 갱신
        if getattr(self, "is_hud_visible", False) and self.stats_ticks % 4 == 0:
            self.update_hud_info()

        self.stats_ticks += 1
        if self.video_sink and self.stats_ticks % 20 == 0 and self.video_sink.find_property("stats"):
            stats = self.video_sink.get_property("stats")
            if stats:
                rendered = stats.get_value("rendered") or 0
                dropped = stats.get_value("dropped") or 0
                if dropped > self.last_dropped_frames:
                    print(f"📊 [렌더링 통계] rendered={rendered}, dropped={dropped}")
                self.last_dropped_frames = dropped
        return True

    def on_seek_start(self, scale, event):
        self.is_seeking = True
        if event.button == 1:
            alloc = scale.get_allocation()
            if alloc.width > 0:
                click_ratio = max(0.0, min(1.0, event.x / alloc.width))
                scale.set_value(click_ratio * 100)
                if self.duration_ns > 0:
                    target = int(self.duration_ns * click_ratio)
                    self.position_label.set_text(self.format_time(target))
                    if getattr(self, "fs_position_label", None):
                        self.fs_position_label.set_text(self.format_time(target))
        return False

    def on_seek_end(self, scale, _event):
        if self.pipeline and self.duration_ns > 0:
            target = int(self.duration_ns * scale.get_value() / 100)
            self.last_known_pos_ns = target
            self.pipeline.seek(
                self.playback_rate,
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                Gst.SeekType.SET,
                target,
                Gst.SeekType.NONE,
                -1
            )
            self.show_osd(f"⏱️ {self.format_time(target)} / {self.format_time(self.duration_ns)}")
        self.is_seeking = False
        return False

    def on_volume_changed(self, scale):
        val = scale.get_value()
        if self.is_muted and val > 0:
            self.is_muted = False
            if getattr(self, "mute_btn", None):
                self.mute_btn.set_label("◖)))")
            if getattr(self, "fs_mute_btn", None):
                self.fs_mute_btn.set_label("◖)))")
        if hasattr(self, "fs_volume_scale") and abs(self.fs_volume_scale.get_value() - val) > 0.5:
            self.fs_volume_scale.set_value(val)
        if self.pipeline:
            self.pipeline.set_property("volume", val / 100.0)
        self.show_osd(f"🔊 볼륨: {int(val)}%")

    def hide_cursor(self):
        """마우스 커서를 투명(숨김) 커서로 설정합니다."""
        self.cursor_hide_timer_id = None
        gdk_win = self.get_window()
        if gdk_win:
            display = gdk_win.get_display()
            blank_cursor = None
            try:
                blank_cursor = Gdk.Cursor.new_from_name(display, "none")
            except Exception:
                pass
            if not blank_cursor:
                blank_cursor = Gdk.Cursor.new_for_display(display, Gdk.CursorType.BLANK_CURSOR)
            gdk_win.set_cursor(blank_cursor)
            self.is_cursor_hidden = True
        return False

    def show_cursor(self):
        """마우스 커서를 기본 포인터로 복원합니다."""
        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.set_cursor(None)
        self.is_cursor_hidden = False

    def on_mouse_motion(self, widget, event):
        """마우스 움직임 감지 시 커서를 표시하고 전체화면일 때 컨트롤 바를 띄운 후 2.5초 후 자동 숨김 타이머를 재설정합니다."""
        if self.is_video_only:
            if self.is_cursor_hidden:
                self.show_cursor()
            if getattr(self, "fs_controls_box", None) and not self.is_fs_controls_visible:
                self.fs_controls_box.show_all()
                self.is_fs_controls_visible = True

            if getattr(self, "cursor_hide_timer_id", None):
                try:
                    GLib.source_remove(self.cursor_hide_timer_id)
                except Exception:
                    pass
            self.cursor_hide_timer_id = GLib.timeout_add(2500, self._on_hide_timer_tick)
        return False

    def _on_hide_timer_tick(self):
        """2.5초 동안 마우스 조작이 없을 때 전체화면 컨트롤 바와 커서를 숨깁니다."""
        if self.is_video_only:
            if getattr(self, "is_mouse_over_fs_controls", False) or getattr(self, "is_popover_open", False):
                return True
            if getattr(self, "fs_controls_box", None) and self.is_fs_controls_visible:
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.hide_cursor()
        self.cursor_hide_timer_id = None
        return False

    def on_window_button_press(self, widget, event):
        """더블클릭 시 전체화면 전환 및 마우스 조작 감지"""
        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == 1:
            self.toggle_fullscreen()
            return True
        if self.is_video_only:
            self.on_mouse_motion(widget, event)
        return False

    def toggle_fullscreen(self):
        """상단바, 재생목록, 컨트롤을 숨긴 영상 전용 전체화면을 전환합니다."""
        if not self.is_video_only:
            self.sidebar_was_visible = self.sidebar.get_visible()
            self.topbar.hide()
            self.sidebar.hide()
            self.controls.hide()
            if getattr(self, "fs_controls_box", None):
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.fullscreen()
            self.set_decorated(False)
            self.set_keep_above(True)
            self.is_fullscreen = True
            self.is_video_only = True
            self.fullscreen_button.set_label("⧉")
            # 전체화면 전환 시 마우스 커서 즉시 숨김
            self.hide_cursor()
            self.show_osd("🖥️ 전체화면 (영상 전용)")
            print("🖥️ 영상 전용 전체화면 (마우스 조작 시 컨트롤 표시)")
        else:
            self.unfullscreen()
            self.set_decorated(True)
            self.set_keep_above(self.is_keep_above)
            self.topbar.show()
            self.controls.show()
            if self.sidebar_was_visible:
                self.sidebar.show()
                if self.main_paned:
                    alloc_w = self.main_paned.get_allocation().width
                    if alloc_w > 0:
                        self.main_paned.set_position(max(200, alloc_w - self.sidebar_width))
            if getattr(self, "fs_controls_box", None):
                self.fs_controls_box.hide()
                self.is_fs_controls_visible = False
            self.is_fullscreen = False
            self.is_video_only = False
            self.fullscreen_button.set_label("⛶")
            # 일반 모드 복귀 시 마우스 커서 복원
            self.show_cursor()
            self.show_osd("🖥️ 창 모드 복귀")
            print("🖥️ 플레이어 창 모드 복귀")

    def get_current_subtitle_font_desc(self):
        """
        한국어(KR), 중국어 번체/대만어(TC), 간체(SC), 일본어(JP), 영문 알파벳을
        한 글자의 빠짐이나 깨짐 없이 100% 온전하게 렌더링하는 CJK 통합 폰트 디스크립터를 반환합니다.
        """
        active_indices = getattr(self, "active_subtitle_indices", set())
        
        num_tracks = len(active_indices) if active_indices else 1
        if num_tracks <= 1:
            base_pt = 22
        elif num_tracks == 2:
            base_pt = 17
        else:
            base_pt = 14
        final_pt = max(10, min(36, int(base_pt * getattr(self, "subtitle_font_scale", 1.0))))
        
        # Noto Sans CJK TC는 대만 번체 한자(13,053자)와 한글(11,172자), 영문, 기호를 단일 폰트 내에 100% 내장하고 있어
        # 한국어 단독, 중국어 단독, 한국어+중국어+영어 다중 자막 어떤 조합에서도 폰트 폴백 결함 없이 완벽히 렌더링됩니다.
        font_stack = "Noto Sans CJK TC, Noto Sans CJK KR, Noto Sans CJK SC, Noto Sans CJK JP, Sans"
        return f"{font_stack} Bold {final_pt}"

    def on_source_setup(self, playbin, source):
        """네트워크 스트리밍(HTTP/HTTPS) 소스에 User-Agent 및 SSL 설정을 주입합니다."""
        if source.find_property("user-agent"):
            source.set_property("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        if source.find_property("ssl-strict"):
            source.set_property("ssl-strict", False)

    def on_deep_element_added(self, bin_elem, sub_bin, element):
        """
        GStreamer 하위 요소 생성 시 젯슨 HW 디코더(nvv4l2decoder) 및 비디오 싱크(nveglglessink)를 감지하여 
        DPB 프레임 버퍼(num-extra-surfaces=32), disable-dpb low-latency 모드, 동적 메모리 할당, 
        고성능 모드, 프레임 드랍 0 및 화면 왜곡 방지 옵션을 동적 설정합니다.
        """
        factory = element.get_factory()
        fname = factory.get_name() if factory else ""
        ename = element.get_name()
        klass = factory.get_metadata("klass") if factory else ""
        if klass and "Decoder" in klass and "Video" in klass and fname not in self.decoder_names:
            self.decoder_names.add(fname)
            acceleration = "NVDEC 하드웨어" if fname == "nvv4l2decoder" else "소프트웨어 fallback"
            print(f"🎬 [선택된 비디오 디코더] {fname} ({acceleration})")

        if "dav1d" in fname or "dav1d" in ename:
            if element.find_property("max-threads"):
                element.set_property("max-threads", 6)
        if "nvv4l2decoder" in fname or "nvv4l2decoder" in ename:
            # NVDEC 하드웨어 디코더 파라미터 최적화
            if element.find_property("enable-max-performance"):
                element.set_property("enable-max-performance", True)
            if element.find_property("num-extra-surfaces"):
                element.set_property("num-extra-surfaces", 32)
            if element.find_property("qos"):
                element.set_property("qos", False)
            if element.find_property("drop-on-latency"):
                element.set_property("drop-on-latency", False)
            if element.find_property("drop-frame-interval"):
                element.set_property("drop-frame-interval", 0)
            if element.find_property("max-errors"):
                element.set_property("max-errors", -1)

        if "nvvidconv" in fname or "nvvidconv" in ename:
            if element.find_property("output-buffers"):
                element.set_property("output-buffers", 32)
            if element.find_property("interpolation-method"):
                # 최고 품질 보간 알고리즘 (5: Nicest 10-tap) 적용하여 픽셀 선명도 극대화
                element.set_property("interpolation-method", 5)
        if "nveglglessink" in fname or "nveglglessink" in ename:
            if element.find_property("force-aspect-ratio"):
                element.set_property("force-aspect-ratio", True)

        # 자막 렌더링 요소 최적화 (외곽선, Noto Sans CJK 한글/한자 유니버설 폰트, 하단 중앙 정렬, 자동 줄바꿈, 완벽한 A/V 싱크)
        if any(k in fname or k in ename for k in ["textoverlay", "subtitleoverlay", "textrender", "playsink"]):
            if "textoverlay" in fname or "textoverlay" in ename or "subtitleoverlay" in fname or "subtitleoverlay" in ename:
                self.subtitle_overlay_element = element
            if element.find_property("font-desc"):
                element.set_property("font-desc", self.get_current_subtitle_font_desc())
            if element.find_property("subtitle-font-desc"):
                element.set_property("subtitle-font-desc", self.get_current_subtitle_font_desc())
            if element.find_property("valignment"):
                element.set_property("valignment", 1)  # bottom
            if element.find_property("halignment"):
                element.set_property("halignment", 1)  # center
            if element.find_property("line-alignment"):
                element.set_property("line-alignment", 1)  # center
            if element.find_property("wrap-mode"):
                element.set_property("wrap-mode", 2)  # wordchar (화면 폭 초과 시 자동 줄바꿈)
            if element.find_property("draw-outline"):
                element.set_property("draw-outline", True)
            if element.find_property("draw-shadow"):
                element.set_property("draw-shadow", False)
            if element.find_property("outline-color"):
                element.set_property("outline-color", 0xFF000000)
            if element.find_property("color"):
                element.set_property("color", 0xFFFFFFFF)
            if element.find_property("wait-text"):
                # GStreamer A/V 및 자막 타임스탬프 100% 정밀 동기화
                element.set_property("wait-text", True)
            if element.find_property("shaded-background"):
                element.set_property("shaded-background", False)
            if element.find_property("auto-resize"):
                element.set_property("auto-resize", False)
        if "subparse" in fname or "subparse" in ename:
            if element.find_property("subtitle-encoding"):
                element.set_property("subtitle-encoding", "UTF-8")

    def check_video_hw_support(self, file_path):
        """
        ffprobe JSON 정보를 분석하여 Jetson NVDEC 하드웨어 디코더가
        100% 안정적으로 가속 지원하는 포맷(H.265/HEVC 및 H.264 8-bit)인지 판정합니다.
        JetPack 드라이버 상 DPB/버퍼 결함이 발생하는 AV1, VP9 등의 코덱이나
        H.264 10-bit 영상은 미지원으로 분류하여 H.265로 자동 변환하도록 유도합니다.
        영구 캐시(hw_cache)를 우선 조회하여 불필요한 ffprobe 중복 실행을 차단합니다.
        """
        cached = hw_cache.get(file_path)
        if cached is not None:
            return cached

        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,profile,width,height,color_space,color_transfer,color_primaries",
                "-of", "json",
                file_path
            ]
            data = json.loads(subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True))
            if not data.get("streams"):
                res = (False, "비디오 스트림 없음")
                hw_cache.set(file_path, res[0], res[1])
                return res
            stream = data["streams"][0]
            codec = stream.get("codec_name", "").lower()
            pix_fmt = stream.get("pix_fmt", "").lower()
            profile = stream.get("profile", "").lower()

            # 1. H.265 / HEVC -> 8-bit 및 10-bit 모두 Jetson NVDEC 하드웨어 가속 100% 완벽 지원
            if codec in ["hevc", "h265"]:
                bit_depth = "10-bit" if "10" in pix_fmt or "p10" in pix_fmt else "8-bit"
                res = (True, f"HEVC ({codec.upper()}) {bit_depth} NVDEC 지원")
                hw_cache.set(file_path, res[0], res[1])
                return res

            # 2. H.264 / AVC -> 8-bit만 지원 (High 10 / yuv420p10le 등 10-bit는 NVDEC 미지원)
            if codec in ["h264", "avc"]:
                if "10" in pix_fmt or "10" in profile or "p10" in pix_fmt:
                    res = (False, f"H.264 10-bit NVDEC 미지원 ({pix_fmt}/{profile})")
                else:
                    res = (True, "H.264 8-bit NVDEC 지원")
                hw_cache.set(file_path, res[0], res[1])
                return res

            # 3. 그 외 (AV1, VP9, VP8 등) -> JetPack nvv4l2decoder DPB 결함 및 SW 디코딩 병목 방지를 위해 H.265 변환 대상
            res = (False, f"NVDEC 미지원/불안정 코덱 ({codec.upper()})")
            hw_cache.set(file_path, res[0], res[1])
            return res
        except Exception as e:
            # ffprobe 실패 시 GStreamer Discoverer로 안전하게 2차 분석 (cuvid 드라이버 누락 등 방지)
            try:
                uri = f"file://{pathname2url(os.path.abspath(file_path))}"
                disc = GstPbutils.Discoverer.new(3 * Gst.SECOND)
                info = disc.discover_uri(uri)
                v_streams = info.get_video_streams()
                if v_streams:
                    caps_str = v_streams[0].get_caps().to_string().lower()
                    if "video/x-h265" in caps_str or "video/x-hevc" in caps_str:
                        res = (True, "HEVC (H.265) NVDEC 지원")
                    elif "video/x-h264" in caps_str:
                        if "10-bit" in caps_str or "bit-depth-luma=(uint)10" in caps_str:
                            res = (False, "H.264 10-bit NVDEC 미지원")
                        else:
                            res = (True, "H.264 8-bit NVDEC 지원")
                    else:
                        cname = caps_str.split(',')[0].replace('video/x-', '')
                        res = (False, f"NVDEC 미지원 코덱 ({cname.upper()})")
                    hw_cache.set(file_path, res[0], res[1])
                    return res
            except Exception:
                pass
            res = (False, f"코덱 분석 실패 ({e})")
            return res

    def probe_video(self, file_path):
        """변환 품질 결정을 위해 이름 순서에 의존하지 않는 ffprobe 정보를 반환합니다."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,profile,color_space,color_transfer,color_primaries",
            "-of", "json", file_path,
        ]
        data = json.loads(subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True))
        if not data.get("streams"):
            raise ValueError("비디오 스트림이 없습니다")
        return data["streams"][0]

    def auto_convert_to_h265(self, file_path):
        """
        하드웨어 디코딩 미지원 영상을 H.265 (HEVC) MP4 포맷으로 자동 변환하고,
        원래 영상 파일은 'unsupported_originals' 백업 폴더로 안전하게 이동합니다.
        """
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        name_no_ext, _ext = os.path.splitext(base_name)

        # 1. 백업 폴더 생성 (unsupported_originals)
        backup_dir = os.path.join(dir_name, "unsupported_originals")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, base_name)

        # 2. H.265 변환 목표 파일 경로 생성 (.mp4)
        target_mp4_path = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")
        if os.path.exists(target_mp4_path):
            supported, _reason = self.check_video_hw_support(target_mp4_path)
            if supported:
                print(f"ℹ️ 기존 H.265 변환본을 사용합니다: {target_mp4_path}")
                hw_cache.set(file_path, True, "기존 H.265 변환본")
                hw_cache.save()
                return target_mp4_path

        # 3. 비트 심도 검사 (10-bit 소스는 H.265 10-bit 유지)
        _is_supported, reason = self.check_video_hw_support(file_path)
        try:
            stream = self.probe_video(file_path)
        except Exception as error:
            print(f"❌ 변환용 영상 정보 확인 실패: {error}")
            return file_path
        source_pix_fmt = stream.get("pix_fmt", "").lower()
        is_10bit = "10" in source_pix_fmt or "p10" in source_pix_fmt
        pix_fmt = "yuv420p10le" if is_10bit else "yuv420p"
        profile = "main10" if is_10bit else "main"
        temp_output = os.path.join(dir_name, f".{name_no_ext}_h265.part.mp4")

        print(f"\n🔄 [자동 코덱 변환 개시] {base_name}")
        print(f"   - 감지된 사유: {reason}")
        print(f"   - 타겟 코덱: H.265 / HEVC MP4 ({pix_fmt})")
        print(f"   - 백업 이동 경로: {backup_path}")

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
            "-map_metadata", "0", "-map_chapters", "0",
            "-pix_fmt", pix_fmt,
            "-c:v", "libx265",
            "-profile:v", profile,
            "-preset", "fast",
            "-crf", "18",
            "-threads", "6",
            "-c:a", "aac",
            "-b:a", "256k",
            "-c:s", "mov_text",
            "-movflags", "+faststart",
            "-tag:v", "hvc1",
            temp_output
        ]

        try:
            subprocess.run(ffmpeg_cmd, check=True)
            os.replace(temp_output, target_mp4_path)
            hw_cache.set(target_mp4_path, True, f"HEVC 변환 완료 ({pix_fmt})")
            hw_cache.set(file_path, True, "H.265 변환 완료")
            hw_cache.save()
            print(f"✅ [H.265 변환 완료] {os.path.basename(target_mp4_path)}")

            if os.path.exists(file_path) and file_path != target_mp4_path:
                if os.path.exists(backup_path):
                    base, suffix = os.path.splitext(base_name)
                    counter = 1
                    while os.path.exists(backup_path):
                        backup_path = os.path.join(backup_dir, f"{base}_{counter}{suffix}")
                        counter += 1
                shutil.move(file_path, backup_path)
                print(f"📦 [원본 파일 백업 이동 완료] {backup_path}")

            return target_mp4_path
        except Exception as e:
            print(f"❌ [변환 실패] {file_path}: {e}")
            if os.path.exists(temp_output):
                os.unlink(temp_output)
            return file_path

    def build_playlist(self):
        """입력값을 분석하여 재생 목록을 동적으로 구성하고, 하드웨어 미지원 코덱은 H.265로 자동 변환 및 백업합니다."""
        abs_path = os.path.abspath(self.input_path)
        
        raw_playlist = []
        if os.path.isdir(abs_path):
            self.is_single_file_mode = False
            video_exts = {'.webm', '.mp4', '.mkv', '.mov', '.avi', '.ts', '.m4v'}
            try:
                for root, dirs, files in os.walk(abs_path, followlinks=True):
                    # 백업 디렉토리(unsupported_originals) 및 숨김 폴더는 탐색에서 제외
                    dirs[:] = sorted([d for d in dirs if d != "unsupported_originals" and not d.startswith('.')])
                    files.sort()
                    for fname in files:
                        if fname.startswith('.'):
                            continue
                        _stem, ext = os.path.splitext(fname)
                        if ext.lower() in video_exts:
                            full_p = os.path.join(root, fname)
                            if os.path.isfile(full_p):
                                raw_playlist.append(full_p)
            except Exception as e:
                print(f"❌ 디렉토리 읽기 실패 ({abs_path}): {e}")
                sys.exit(1)
            raw_playlist.sort()
            
            if not raw_playlist:
                print(f"❌ 에러: [{self.input_path}] 폴더 내에 재생 가능한 영상 파일이 없습니다.")
                sys.exit(1)

        elif os.path.isfile(abs_path):
            self.is_single_file_mode = True
            raw_playlist.append(abs_path)
        else:
            print(f"❌ 에러: [{self.input_path}] 존재하지 않는 파일이거나 올바르지 않은 경로입니다.")
            sys.exit(1)

        # [초고속 시작 최적화] 시작 시 모든 파일에 대한 무거운 ffprobe 검사를 건너뛰고,
        # 기존 H.265 변환본이 있는 경우에만 빠르게 우선 매핑하여 0.05초 만에 재생목록을 완성합니다.
        # 하드웨어 재생 적합성 검사는 현재 재생할 영상에 대해 On-Demand로 즉시 수행되고,
        # 나머지 영상들은 재생 중 백그라운드 스레드에서 점진적으로 검사/캐싱됩니다.
        self.playlist = []
        processed_set = set()
        raw_set = set(raw_playlist)
        for path in raw_playlist:
            if not os.path.exists(path) or path in processed_set:
                continue

            dir_name = os.path.dirname(path)
            base_name = os.path.basename(path)
            name_no_ext, _ext = os.path.splitext(base_name)

            final_path = path
            # 동일 폴더에 이미 _h265.mp4 변환본이 존재하는 경우 변환본을 채택
            if not name_no_ext.endswith("_h265"):
                target_h265 = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")
                if target_h265 in raw_set or os.path.exists(target_h265):
                    final_path = target_h265
                    processed_set.add(path)

            if final_path not in self.playlist:
                self.playlist.append(final_path)
                processed_set.add(final_path)

        mode_str = "단일 파일 반복 모드" if self.is_single_file_mode else "폴더 순환 모드"
        print(f"📂 [{mode_str}] 총 {len(self.playlist)}개의 영상을 로드했습니다.")
        for idx, path in enumerate(self.playlist):
            disp = os.path.relpath(path, abs_path) if not self.is_single_file_mode else os.path.basename(path)
            print(f"   [{idx}] {disp}")

    def on_realize(self, widget):
        """GTK 창의 리소스가 로드되었을 때 영상 재생을 시작하고 백그라운드 검사기를 가동합니다."""
        if self.pipeline is not None:
            return
        print("🖥️ GUI 창 준비 완료. 영상 재생을 시작합니다.")
        
        top_window = self.get_window()
        if top_window:
            enable_x11_compositor_bypass(top_window)

        self.play_current_video()
        self.start_background_hw_checker()

    def start_background_hw_checker(self):
        """백그라운드에서 재생목록 파일들의 하드웨어 가속 적합성을 점진적으로 검사하고 캐싱합니다."""
        if getattr(self, "_bg_checker_started", False):
            return
        self._bg_checker_started = True
        t = threading.Thread(target=self._background_hw_worker, daemon=True)
        t.start()

    def _background_hw_worker(self):
        # 첫 영상이 시작되고 UI가 완전히 렌더링될 때까지 1.5초 대기
        time.sleep(1.5)
        for idx in range(len(self.playlist)):
            if getattr(self, "is_destroyed", False):
                break
            if idx >= len(self.playlist):
                break
            path = self.playlist[idx]
            if not os.path.exists(path):
                continue

            # 캐시가 이미 존재하면 스킵 (불필요한 작업 방지)
            cached = hw_cache.get(path)
            if cached is None:
                is_supported, _reason = self.check_video_hw_support(path)
                # 동일 폴더에 이미 _h265.mp4가 존재하는 경우 메인 스레드에 경로 교체 요청
                if not is_supported:
                    dir_name = os.path.dirname(path)
                    name_no_ext, _ext = os.path.splitext(os.path.basename(path))
                    target_h265 = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")
                    if os.path.exists(target_h265):
                        GLib.idle_add(self._apply_background_h265_path, idx, target_h265)
                # 현재 영상 재생 성능에 영향을 주지 않도록 파일 간 0.05초 대기
                time.sleep(0.05)

        hw_cache.save()

    def _apply_background_h265_path(self, idx, new_path):
        if 0 <= idx < len(self.playlist) and os.path.exists(new_path):
            self.playlist[idx] = new_path
            self.update_playlist_item_ui(idx, new_path)

    def update_playlist_item_ui(self, idx, new_path):
        """재생목록 항목 경로가 변경(H.265 변환 등)되었을 때 트리뷰 UI를 동기화합니다."""
        if not self.tree_store or idx not in self.playlist_tree_iters:
            return
        tree_iter = self.playlist_tree_iters[idx]
        if self.tree_store.iter_is_valid(tree_iter):
            fname = os.path.basename(new_path)
            safe_name = GLib.markup_escape_text(fname)
            self.tree_store.set_value(tree_iter, 1, f"<span>{safe_name}</span>")
            self.tree_store.set_value(tree_iter, 2, new_path)

    def play_current_video(self, start_position_ns=0):
        """[성능 최적화] 영상 전환 및 다중 자막 변경 시 파이프라인 자원을 완전 세척 후 신규 구축합니다."""
        if not self.playlist or self.current_index < 0 or self.current_index >= len(self.playlist):
            return

        video_path = self.playlist[self.current_index]
        self.rate_applied_on_preroll = False

        # 최근 재생 기록에 추가
        history_cache.add(video_path)

        # 새 영상 시작 시 A-B 구간 반복 리셋
        if start_position_ns == 0:
            self.ab_repeat_a = None
            self.ab_repeat_b = None
            self.is_ab_repeat_active = False
            if getattr(self, "ab_badge", None):
                self.ab_badge.hide()

        # [하드웨어 적합성 검사 (SW Fallback 우선)]
        if os.path.exists(video_path):
            is_supported, reason = self.check_video_hw_support(video_path)
            if not is_supported:
                print(f"ℹ️ [코덱 상태] {os.path.basename(video_path)}: {reason} (소프트웨어 디코딩으로 즉시 재생합니다)")
                if "AV1" in reason.upper():
                    self.show_osd("⚠️ AV1 코덱: Jetson NVDEC 미지원 (H.264/H.265 포맷 권장)", duration_sec=4.0)
        
        if getattr(self, "placeholder_box", None):
            self.placeholder_box.hide()

        if start_position_ns == 0:
            # 이어보기 체크 (이전 시청 위치가 있으면 복원)
            saved_pos_ns, saved_dur_ns = resume_cache.get(video_path)
            if saved_pos_ns > 0:
                start_position_ns = saved_pos_ns
                self.show_osd(f"⏱️ 이어서 재생: {self.format_time(saved_pos_ns)}")
                print(f"⏱️ [이어보기] {self.format_time(saved_pos_ns)} 지점부터 재생합니다.")

            abs_root = os.path.abspath(self.input_path) if (self.input_path and os.path.isdir(self.input_path)) else None
            is_net_stream = video_path.startswith("http://") or video_path.startswith("https://")
            if is_net_stream:
                disp = "▶ YouTube / 온라인 스트림"
            else:
                disp = os.path.relpath(video_path, abs_root) if abs_root else os.path.basename(video_path)
            print(f"\n▶ [{self.current_index + 1}/{len(self.playlist)}] 재생 중: {disp}")
            self.refresh_playlist_ui()
            self.duration_ns = 0
            self.progress_scale.set_value(0)
            self.position_label.set_text("00:00")
            self.duration_label.set_text("00:00")
            if getattr(self, "fs_progress_scale", None):
                self.fs_progress_scale.set_value(0)
            if getattr(self, "fs_position_label", None):
                self.fs_position_label.set_text("00:00")
            if getattr(self, "fs_duration_label", None):
                self.fs_duration_label.set_text("00:00")
            self.decoder_names.clear()
            self.last_dropped_frames = 0
            self.last_ui_pos_sec = -1

            # 신규 영상인 경우 자막 파일 전체 탐색 및 파싱 초기화
            all_sub_files = find_all_matching_subtitles(video_path)
            self.available_subtitles = []
            for idx, s_path in enumerate(all_sub_files):
                evs = parse_subtitle_file_events(s_path)
                if evs:
                    color = get_subtitle_color(s_path, idx)
                    lbl = get_subtitle_label(s_path)
                    self.available_subtitles.append({
                        'path': s_path,
                        'label': lbl,
                        'color': color,
                        'events': evs
                    })

            self.active_subtitle_indices = set()
            if self.available_subtitles:
                if getattr(self, "single_sub_mode", True):
                    # 기본 1개(한국어 우선)만 활성화하여 화면 가림 방지
                    self.active_subtitle_indices = {0}
                    self.has_subtitles = True
                    self.subtitles_enabled = True
                    print(f"💬 [자막 자동 활성화] {self.available_subtitles[0]['label']} (다중 자막 메뉴에서 추가 선택 가능)")
                else:
                    self.active_subtitle_indices = set(range(len(self.available_subtitles)))
                    self.has_subtitles = True
                    self.subtitles_enabled = True
                    print(f"💬 [다중 자막 자동 활성화 ({len(self.available_subtitles)}개)] " + ", ".join([s['label'] for s in self.available_subtitles]))
            else:
                self.has_subtitles = False

        self.pending_seek_ns = start_position_ns
        is_net_stream = video_path.startswith("http://") or video_path.startswith("https://")
        if is_net_stream:
            video_uri = video_path
        else:
            video_uri = f"file://{pathname2url(os.path.abspath(video_path))}"
        
        # [핵심] 기존 파이프라인 및 버스 시그널 감시 완전 해제 후 NULL 처리 (EGL Surface/VIC 락 세척)
        if self.bus is not None:
            try:
                self.bus.remove_signal_watch()
            except Exception:
                pass
            self.bus = None

        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        # 신규 playbin 파이프라인 생성
        self.pipeline = Gst.ElementFactory.make("playbin", "player")

        # 젯슨 HW 디코더 동적 속성 설정을 위한 deep-element-added 시그널 연결
        self.pipeline.connect("deep-element-added", self.on_deep_element_added)
        self.pipeline.connect("source-setup", self.on_source_setup)

        # 0x01 (video) + 0x02 (audio) + 0x04 (text/subtitles) + 0x10 (soft-volume) = 0x00000017
        self.pipeline.set_property("flags", 0x00000017)

        # 활성화된 자막 병합 파일 준비 및 suburi 설정
        active_tracks = []
        for idx in sorted(list(self.active_subtitle_indices)):
            if 0 <= idx < len(self.available_subtitles):
                sub = self.available_subtitles[idx]
                active_tracks.append((sub['label'], sub['color'], sub['events']))

        if active_tracks and self.subtitles_enabled:
            merged_file = generate_merged_subtitle_file(
                active_tracks, video_path,
                font_scale=self.subtitle_font_scale,
                offset_ms=self.subtitle_offset_ms
            )
            if merged_file:
                self.current_suburi = f"file://{pathname2url(os.path.abspath(merged_file))}"
                self.pipeline.set_property("suburi", self.current_suburi)
                if self.pipeline.find_property("subtitle-font-desc"):
                    self.pipeline.set_property("subtitle-font-desc", self.get_current_subtitle_font_desc())
                if self.pipeline.find_property("subtitle-encoding"):
                    self.pipeline.set_property("subtitle-encoding", "UTF-8")
                selected_labels = [t[0] for t in active_tracks]
                sync_info = f" / 싱크 {self.subtitle_offset_ms/1000:+.1f}s" if self.subtitle_offset_ms != 0 else ""
                print(f"💬 [다중 자막 로드 완료 ({len(active_tracks)}개 / 크기 {int(self.subtitle_font_scale*100)}%{sync_info})] " + ", ".join(selected_labels))
            else:
                self.current_suburi = None
        else:
            self.current_suburi = None

        # Totem 공식 네이티브 GTK OpenGL 비디오 싱크 할당 (60Hz V-Sync 완벽 일치 & 4K 1:1 선명도 보장)
        # 배속 재생 시 지연 프레임으로 인한 파이프라인 정체를 방지하기 위해 qos=True 및 max-lateness=50ms 설정
        if self.video_sink:
            if self.video_sink.find_property("sync"):
                self.video_sink.set_property("sync", True)
            if self.video_sink.find_property("qos"):
                self.video_sink.set_property("qos", True)
            if self.video_sink.find_property("max-lateness"):
                self.video_sink.set_property("max-lateness", 50 * Gst.MSECOND)
            self.pipeline.set_property("video-sink", self.video_sink)

        # scaletempo가 포함된 커스텀 오디오 싱크 bin 생성 (배속 재생 시 끊김 및 음정 왜곡 없는 완벽한 사운드 보장)
        audio_bin = Gst.Bin.new("audio_sink_bin")
        aconv = Gst.ElementFactory.make("audioconvert", "aconv")
        scaletempo = Gst.ElementFactory.make("scaletempo", "scaletempo")
        aresample = Gst.ElementFactory.make("audioresample", "aresample")
        asink = Gst.ElementFactory.make("autoaudiosink", "asink")
        if not asink:
            asink = Gst.ElementFactory.make("fakesink", "asink")
        if asink and asink.find_property("sync"):
            asink.set_property("sync", True)
        self.current_asink = asink
        if asink and asink.find_property("ts-offset") and self.av_sync_offset_ms != 0:
            asink.set_property("ts-offset", self.av_sync_offset_ms * 1_000_000)

        if aconv and scaletempo and aresample and asink:
            audio_bin.add(aconv)
            audio_bin.add(scaletempo)
            audio_bin.add(aresample)
            audio_bin.add(asink)
            aconv.link(scaletempo)
            scaletempo.link(aresample)
            aresample.link(asink)

            pad = aconv.get_static_pad("sink")
            ghost_pad = Gst.GhostPad.new("sink", pad)
            ghost_pad.set_active(True)
            audio_bin.add_pad(ghost_pad)
            self.pipeline.set_property("audio-sink", audio_bin)
        elif asink:
            self.pipeline.set_property("audio-sink", asink)

        # 버스 이벤트 연결
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.enable_sync_message_emission()
        self.bus.connect("sync-message::element", self.on_sync_message)
        self.bus.connect("message", self.on_bus_message)

        # URI 속성 갱신 후 플레이 시작
        self.pipeline.set_property("uri", video_uri)
        self.pipeline.set_property("volume", self.volume_scale.get_value() / 100.0)

        if not self.subtitles_enabled or not active_tracks:
            self.pipeline.set_property("current-text", -1)

        self.update_subtitle_button_ui()
        self.update_speed_button_ui()

        # 재생 중간 위치에서 자막을 재로드할 경우, 비디오/오디오/자막 스트림의 완벽한 Preroll을 위해
        # PAUSED 상태로 진입 후 ASYNC_DONE에서 정밀 Seek를 수행하고 PLAYING으로 전환합니다.
        if self.pending_seek_ns > 0:
            self.pipeline.set_state(Gst.State.PAUSED)
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
            
        self.is_playing = True
        self.play_button.set_label("Ⅱ")
        if getattr(self, "fs_play_button", None):
            self.fs_play_button.set_label("Ⅱ")
        
        return False

    def on_sync_message(self, bus, message):
        """VideoOverlay 인터페이스가 필요한 fallback 싱크를 위한 창 핸들 연결"""
        is_prepare_handle = False
        if hasattr(GstVideo, "is_video_overlay_prepare_window_handle_message"):
            is_prepare_handle = GstVideo.is_video_overlay_prepare_window_handle_message(message)
        
        if not is_prepare_handle and message.get_structure():
            is_prepare_handle = (message.get_structure().get_name() == "prepare-window-handle")

        if is_prepare_handle:
            target_window = getattr(self, "video_widget", None)
            gdk_win = target_window.get_window() if target_window else self.get_window()
            if gdk_win:
                xid = None
                if hasattr(gdk_win, "get_xid"):
                    xid = gdk_win.get_xid()
                elif hasattr(GdkX11, "X11Window") and hasattr(GdkX11.X11Window, "get_xid"):
                    xid = GdkX11.X11Window.get_xid(gdk_win)
                if xid:
                    if isinstance(message.src, GstVideo.VideoOverlay) or hasattr(message.src, "set_window_handle"):
                        message.src.set_window_handle(xid)

    def on_bus_message(self, bus, message):
        """재생 완료(EOS) 및 에러 메시지 처리"""
        if message.type == Gst.MessageType.EOS:
            self.retry_counts.pop(self.playlist[self.current_index], None)
            # 재생 완료 시 이어보기 캐시 삭제
            if 0 <= self.current_index < len(self.playlist):
                resume_cache.clear(self.playlist[self.current_index])
                resume_cache.save()

            if self.repeat_mode == "one" or self.is_single_file_mode:
                print("🔄 1곡 반복: 처음부터 다시 재생합니다.")
                GLib.timeout_add(10, self.play_current_video, 0)
            elif self.repeat_mode == "shuffle" and len(self.playlist) > 1:
                import random
                next_idx = self.current_index
                while next_idx == self.current_index:
                    next_idx = random.randint(0, len(self.playlist) - 1)
                self.current_index = next_idx
                GLib.timeout_add(50, self.play_current_video, 0)
            elif self.repeat_mode == "none":
                if self.current_index + 1 < len(self.playlist):
                    self.current_index += 1
                    GLib.timeout_add(50, self.play_current_video, 0)
                else:
                    print("⏹ 모든 영상 재생 완료 (순차 재생 정지).")
                    self.toggle_play_pause()
            else:
                self.play_next_video()
            
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"❌ 재생 중 에러 발생: {err}")
            if debug:
                print(f"   GStreamer: {debug}")
            path = self.playlist[self.current_index]
            retries = self.retry_counts.get(path, 0)
            if retries < self.max_retries:
                self.retry_counts[path] = retries + 1
                print(f"🔄 재생 파이프라인 재시도 ({retries + 1}/{self.max_retries})")
                GLib.timeout_add(250, self.play_current_video)
            elif self.is_single_file_mode:
                print("⏹ 반복 오류로 재생을 중단합니다. 원본과 디코더 로그를 확인하세요.")
                self.pipeline.set_state(Gst.State.PAUSED)
            else:
                print("⏭ 반복 오류 항목을 건너뜁니다.")
                self.play_next_video()

        elif message.type == Gst.MessageType.ASYNC_DONE:
            if getattr(self, "pending_seek_ns", 0) > 0 and self.pipeline:
                seek_ns = self.pending_seek_ns
                self.pending_seek_ns = 0
                self.rate_applied_on_preroll = True
                self.pipeline.seek(
                    self.playback_rate,
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    Gst.SeekType.SET,
                    seek_ns,
                    Gst.SeekType.NONE,
                    -1
                )
                self.pipeline.set_state(Gst.State.PLAYING)
            elif not getattr(self, "rate_applied_on_preroll", False) and getattr(self, "playback_rate", 1.0) != 1.0 and self.pipeline:
                self.rate_applied_on_preroll = True
                self.pipeline.seek(
                    self.playback_rate,
                    Gst.Format.TIME,
                    Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                    Gst.SeekType.SET,
                    0,
                    Gst.SeekType.NONE,
                    -1
                )

        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self.pipeline:
            _old_state, new_state, _pending = message.parse_state_changed()
            self.is_playing = new_state == Gst.State.PLAYING
            lbl = "Ⅱ" if self.is_playing else "▶"
            self.play_button.set_label(lbl)
            if getattr(self, "fs_play_button", None):
                self.fs_play_button.set_label(lbl)

    def seek_relative(self, offset_seconds):
        """현재 재생 위치를 기준으로 지정된 초만큼 앞/뒤로 이동합니다."""
        if not self.pipeline:
            return
            
        success, position = self.pipeline.query_position(Gst.Format.TIME)
        if not success:
            print("⚠️ 현재 재생 위치를 확인할 수 없어 탐색에 실패했습니다.")
            return

        target_ns = position + (offset_seconds * Gst.SECOND)
        if target_ns < 0:
            target_ns = 0
        if self.duration_ns > 0 and target_ns > self.duration_ns:
            target_ns = self.duration_ns

        self.last_known_pos_ns = target_ns
        res = self.pipeline.seek(
            self.playback_rate,
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            Gst.SeekType.SET,
            target_ns,
            Gst.SeekType.NONE,
            -1
        )
        if not res:
            print("⚠️ 탐색 실패로 파이프라인을 재구축합니다.")
            self.play_current_video(start_position_ns=target_ns)
            return

        direction = "앞으로" if offset_seconds > 0 else "뒤로"
        print(f"⏩ {direction} {abs(offset_seconds)}초 이동 (현재 위치: {target_ns / Gst.SECOND:.1f}초)")
        direction_symbol = "⏩ +" if offset_seconds > 0 else "⏪ -"
        cur_str = self.format_time(target_ns)
        dur_str = f" / {self.format_time(self.duration_ns)}" if self.duration_ns > 0 else ""
        self.show_osd(f"{direction_symbol}{abs(offset_seconds)}초 ({cur_str}{dur_str})")

    def toggle_play_pause(self):
        """일시 정지 / 재생 상태를 전환합니다."""
        if not self.pipeline:
            return
            
        if self.is_playing:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.is_playing = False
            self.play_button.set_label("▶")
            if getattr(self, "fs_play_button", None):
                self.fs_play_button.set_label("▶")
            self.show_osd("⏸ 일시 정지")
            print("⏸ 일시 정지")
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
            self.is_playing = True
            self.play_button.set_label("Ⅱ")
            if getattr(self, "fs_play_button", None):
                self.fs_play_button.set_label("Ⅱ")
            self.show_osd("▶ 재생")
            print("▶ 다시 재생")

    def play_next_video(self):
        """다음 영상으로 전환합니다."""
        if not self.playlist:
            return
        if self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video, 0)
        elif self.repeat_mode == "shuffle" and len(self.playlist) > 1:
            import random
            next_idx = self.current_index
            while next_idx == self.current_index:
                next_idx = random.randint(0, len(self.playlist) - 1)
            self.current_index = next_idx
            GLib.timeout_add(50, self.play_current_video, 0)
        else:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            print("⏭ 다음 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video, 0)

    def play_prev_video(self):
        """이전 영상으로 전환합니다."""
        if not self.playlist:
            return
        if self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video, 0)
        elif self.repeat_mode == "shuffle" and len(self.playlist) > 1:
            import random
            prev_idx = self.current_index
            while prev_idx == self.current_index:
                prev_idx = random.randint(0, len(self.playlist) - 1)
            self.current_index = prev_idx
            GLib.timeout_add(50, self.play_current_video, 0)
        else:
            self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
            print("⏮ 이전 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video, 0)

    def build_subtitle_popover(self, parent_btn=None):
        """다중 자막 선택, 크기 조절 및 싱크 조절 팝오버(Popover) 창을 구성합니다."""
        target_btn = parent_btn or (self.fs_sub_button if self.is_video_only and getattr(self, "fs_sub_button", None) else self.sub_button)
        self.sub_popover = Gtk.Popover(relative_to=target_btn)
        self.sub_popover.set_position(Gtk.PositionType.TOP)
        self.sub_popover.set_border_width(12)
        
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # 헤더
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="💬 자막 선택 & 설정", xalign=0)
        title.get_style_context().add_class("popover-title")
        header.pack_start(title, True, True, 0)
        container.pack_start(header, False, False, 2)
        
        hint = Gtk.Label(label="다중 자막 선택 시 언어별 뱃지와 함께 동시에 표시됩니다.", xalign=0)
        hint.get_style_context().add_class("muted")
        container.pack_start(hint, False, False, 0)
        
        sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        container.pack_start(sep1, False, False, 2)

        # 🗚 자막 크기 조절 바
        size_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        size_bar.get_style_context().add_class("sub-btn-row")
        
        size_lbl = Gtk.Label(label="🗚 크기:")
        size_lbl.get_style_context().add_class("muted")
        size_bar.pack_start(size_lbl, False, False, 0)
        
        dec_btn = Gtk.Button(label="작게 (-)")
        dec_btn.set_tooltip_text("자막 크기 축소 (단축키: [ )")
        dec_btn.connect("clicked", lambda _b: self.adjust_subtitle_scale(-0.1))
        size_bar.pack_start(dec_btn, True, True, 0)
        
        pct_str = f"{int(self.subtitle_font_scale * 100)}%"
        self.scale_label = Gtk.Label(label=pct_str)
        self.scale_label.set_width_chars(5)
        size_bar.pack_start(self.scale_label, False, False, 2)
        
        inc_btn = Gtk.Button(label="크게 (+)")
        inc_btn.set_tooltip_text("자막 크기 확대 (단축키: ] )")
        inc_btn.connect("clicked", lambda _b: self.adjust_subtitle_scale(0.1))
        size_bar.pack_start(inc_btn, True, True, 0)
        
        reset_size_btn = Gtk.Button(label="100%")
        reset_size_btn.set_tooltip_text("기본 크기(100%)로 복원")
        reset_size_btn.connect("clicked", self.reset_subtitle_scale)
        size_bar.pack_start(reset_size_btn, False, False, 0)
        
        container.pack_start(size_bar, False, False, 2)

        # ⏱️ 자막 싱크(Sync) 조절 바
        sync_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sync_bar.get_style_context().add_class("sub-btn-row")
        
        sync_lbl = Gtk.Label(label="⏱️ 싱크:")
        sync_lbl.get_style_context().add_class("muted")
        sync_bar.pack_start(sync_lbl, False, False, 0)
        
        fast_btn = Gtk.Button(label="-0.5s")
        fast_btn.set_tooltip_text("자막 0.5초 빠르게 (단축키: Z, ,: -0.1s)")
        fast_btn.connect("clicked", lambda _b: self.adjust_subtitle_sync(-500))
        sync_bar.pack_start(fast_btn, True, True, 0)
        
        sync_str = f"{self.subtitle_offset_ms / 1000:+.1f}s"
        self.sync_label = Gtk.Label(label=sync_str)
        self.sync_label.set_width_chars(6)
        sync_bar.pack_start(self.sync_label, False, False, 2)
        
        slow_btn = Gtk.Button(label="+0.5s")
        slow_btn.set_tooltip_text("자막 0.5초 느리게 (단축키: X, .: +0.1s)")
        slow_btn.connect("clicked", lambda _b: self.adjust_subtitle_sync(500))
        sync_bar.pack_start(slow_btn, True, True, 0)
        
        reset_sync_btn = Gtk.Button(label="0.0s")
        reset_sync_btn.set_tooltip_text("자막 싱크 기본값(0.0초)으로 복원")
        reset_sync_btn.connect("clicked", self.reset_subtitle_sync)
        sync_bar.pack_start(reset_sync_btn, False, False, 0)
        
        container.pack_start(sync_bar, False, False, 2)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        container.pack_start(sep2, False, False, 2)

        # 자막 체크박스 리스트
        self.sub_checkboxes = []
        for idx, sub in enumerate(self.available_subtitles):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            
            # 색상 표시 원형 인디케이터
            color_box = Gtk.DrawingArea()
            color_box.set_size_request(12, 12)
            c_hex = sub['color']
            def draw_color_dot(widget, cr, col_hex):
                try:
                    r = int(col_hex[1:3], 16) / 255.0
                    g = int(col_hex[3:5], 16) / 255.0
                    b = int(col_hex[5:7], 16) / 255.0
                    cr.set_source_rgb(r, g, b)
                    cr.arc(6, 6, 5, 0, 2 * 3.14159)
                    cr.fill()
                except Exception:
                    pass
            color_box.connect("draw", draw_color_dot, c_hex)
            row.pack_start(color_box, False, False, 2)
            
            chk = Gtk.CheckButton(label=sub['label'])
            chk.set_active(idx in self.active_subtitle_indices)
            chk.connect("toggled", self.on_subtitle_checkbox_toggled, idx)
            row.pack_start(chk, True, True, 0)
            
            self.sub_checkboxes.append(chk)
            container.pack_start(row, False, False, 2)
            
        # 전체 선택 / 전체 해제 버튼
        btn_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_bar.get_style_context().add_class("sub-btn-row")
        select_all_btn = Gtk.Button(label="모두 선택")
        select_all_btn.connect("clicked", self.on_select_all_subtitles)
        deselect_all_btn = Gtk.Button(label="모두 해제")
        deselect_all_btn.connect("clicked", self.on_deselect_all_subtitles)
        btn_bar.pack_start(select_all_btn, True, True, 0)
        btn_bar.pack_start(deselect_all_btn, True, True, 0)
        container.pack_start(btn_bar, False, False, 4)
        
        container.show_all()
        self.sub_popover.add(container)

        def on_sub_pop_closed(_pop):
            self.is_popover_open = False
        self.sub_popover.connect("closed", on_sub_pop_closed)

    def adjust_subtitle_scale(self, delta):
        """자막 크기를 delta만큼 확대/축소하고 즉시 화면에 반영합니다."""
        new_scale = round(max(0.6, min(1.6, self.subtitle_font_scale + delta)), 2)
        if new_scale != self.subtitle_font_scale:
            self.subtitle_font_scale = new_scale
            pct = int(self.subtitle_font_scale * 100)
            print(f"🗚 [자막 크기 조절] {pct}%")
            self.show_osd(f"🗚 자막 크기: {pct}%")
            if getattr(self, "scale_label", None):
                self.scale_label.set_text(f"{pct}%")
            if getattr(self, "subtitle_overlay_element", None):
                try:
                    self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
                except Exception:
                    pass
            self.schedule_subtitles_reload()

    def reset_subtitle_scale(self, _btn=None):
        """자막 크기를 기본값(100%)으로 복원합니다."""
        if self.subtitle_font_scale != 1.0:
            self.subtitle_font_scale = 1.0
            print("🗚 [자막 크기 조절] 100% (기본값)")
            self.show_osd("🗚 자막 크기: 100%")
            if getattr(self, "scale_label", None):
                self.scale_label.set_text("100%")
            if getattr(self, "subtitle_overlay_element", None):
                try:
                    self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
                except Exception:
                    pass
            self.schedule_subtitles_reload()

    def adjust_subtitle_sync(self, delta_ms):
        """자막 싱크를 delta_ms만큼 앞당기거나 늦추고 실시간 OSD 반영 후 디바운스로 적용합니다."""
        self.subtitle_offset_ms += delta_ms
        sec_str = f"{self.subtitle_offset_ms / 1000:+.1f}s"
        print(f"⏱️ [자막 싱크 조절] {sec_str}")
        self.show_osd(f"⏱️ 자막 싱크: {sec_str}")
        if getattr(self, "sync_label", None):
            self.sync_label.set_text(sec_str)
        self.schedule_subtitles_reload()

    def reset_subtitle_sync(self, _btn=None):
        """자막 싱크를 기본값(0.0초)으로 복원합니다."""
        if self.subtitle_offset_ms != 0:
            self.subtitle_offset_ms = 0
            print("⏱️ [자막 싱크 조절] 0.0s (기본값)")
            self.show_osd("⏱️ 자막 싱크: 0.0s")
            if getattr(self, "sync_label", None):
                self.sync_label.set_text("0.0s")
            self.schedule_subtitles_reload()

    def show_subtitle_popover(self, parent_btn=None):
        """자막 선택 팝오버를 열거나 닫습니다."""
        if not self.available_subtitles:
            print("ℹ️ 현재 영상에 사용 가능한 자막이 없습니다.")
            return
        if self.sub_popover:
            self.sub_popover.destroy()
            self.sub_popover = None
        self.build_subtitle_popover(parent_btn=parent_btn)
        self.is_popover_open = True
        self.sub_popover.show_all()
        self.sub_popover.popup()

    def on_sub_button_clicked(self, widget):
        """자막 버튼 클릭 시 단일 자막은 토글, 다중 자막은 팝오버 메뉴를 표시합니다."""
        if not self.available_subtitles:
            return
        if len(self.available_subtitles) == 1:
            self.toggle_subtitles()
        else:
            self.show_subtitle_popover(parent_btn=widget)

    def on_subtitle_checkbox_toggled(self, chk_button, track_idx):
        """자막 체크박스 토글 시 실시간으로 활성 자막 목록을 갱신하고 화면에 안전하게 반영합니다."""
        if getattr(self, "is_updating_sub_checkboxes", False):
            return
            
        if chk_button.get_active():
            self.active_subtitle_indices.add(track_idx)
            self.subtitles_enabled = True
        else:
            self.active_subtitle_indices.discard(track_idx)
            if not self.active_subtitle_indices:
                self.subtitles_enabled = False
        self.schedule_subtitles_reload()

    def on_select_all_subtitles(self, _btn):
        """모든 자막 체크 활성화 (일괄 락 적용으로 프로그램 충돌 및 중복 리로드 차단)"""
        self.is_updating_sub_checkboxes = True
        try:
            self.active_subtitle_indices = set(range(len(self.available_subtitles)))
            self.subtitles_enabled = bool(self.active_subtitle_indices)
            for chk in getattr(self, "sub_checkboxes", []):
                chk.set_active(True)
        finally:
            self.is_updating_sub_checkboxes = False
        self.schedule_subtitles_reload()

    def on_deselect_all_subtitles(self, _btn):
        """모든 자막 체크 해제 (일괄 락 적용으로 프로그램 충돌 및 중복 리로드 차단)"""
        self.is_updating_sub_checkboxes = True
        try:
            self.active_subtitle_indices.clear()
            self.subtitles_enabled = False
            for chk in getattr(self, "sub_checkboxes", []):
                chk.set_active(False)
        finally:
            self.is_updating_sub_checkboxes = False
        self.schedule_subtitles_reload()

    def schedule_subtitles_reload(self):
        """빠른 조작이나 연타 시 파이프라인 중복 파괴를 막기 위해 150ms 디바운스로 안전하게 재로드합니다."""
        if getattr(self, "sub_reload_timer_id", None):
            try:
                GLib.source_remove(self.sub_reload_timer_id)
            except Exception:
                pass
            self.sub_reload_timer_id = None
        self.sub_reload_timer_id = GLib.timeout_add(150, self._deferred_reload_subtitles)

    def _deferred_reload_subtitles(self):
        self.sub_reload_timer_id = None
        self.reload_and_apply_subtitles()
        return False

    def reload_and_apply_subtitles(self):
        """선택된 다중 자막 트랙들을 실시간 병합하여 GStreamer 파이프라인에 즉시 반영합니다."""
        if not self.pipeline:
            return
            
        video_path = self.playlist[self.current_index]
        active_tracks = []
        for idx in sorted(list(self.active_subtitle_indices)):
            if 0 <= idx < len(self.available_subtitles):
                sub = self.available_subtitles[idx]
                active_tracks.append((sub['label'], sub['color'], sub['events']))
                
        if active_tracks and self.subtitles_enabled:
            merged_file = generate_merged_subtitle_file(
                active_tracks, video_path,
                font_scale=self.subtitle_font_scale,
                offset_ms=self.subtitle_offset_ms
            )
            new_suburi = f"file://{pathname2url(os.path.abspath(merged_file))}" if merged_file else None
        else:
            new_suburi = None
            
        # GStreamer playbin은 실행 중 suburi 변경 시 내부 파서를 다시 읽지 않으므로,
        # 자막 스트림이 변경된 경우 현재 재생 위치(초 단위)를 100% 보존하여 즉시 매끄럽게 재로드합니다.
        if new_suburi != getattr(self, "current_suburi", None):
            pos_ns = 0
            if self.pipeline:
                success, q_pos = self.pipeline.query_position(Gst.Format.TIME)
                if success and q_pos > 0:
                    pos_ns = q_pos
                elif getattr(self, "last_known_pos_ns", 0) > 0:
                    pos_ns = self.last_known_pos_ns
            self.play_current_video(start_position_ns=pos_ns)
        else:
            if not self.subtitles_enabled or not active_tracks:
                self.pipeline.set_property("current-text", -1)
            else:
                self.pipeline.set_property("current-text", 0)
                
        if getattr(self, "subtitle_overlay_element", None):
            try:
                self.subtitle_overlay_element.set_property("font-desc", self.get_current_subtitle_font_desc())
            except Exception:
                pass

        self.update_subtitle_button_ui()

    def update_subtitle_button_ui(self):
        """자막 버튼 레이블 및 활성화 상태 갱신 (일반 컨트롤 및 전체화면 컨트롤)"""
        btns = [b for b in [getattr(self, "sub_button", None), getattr(self, "fs_sub_button", None)] if b is not None]
        if not btns:
            return
            
        total = len(self.available_subtitles)
        if total == 0:
            for b in btns:
                b.set_label("💬 자막 없음")
                b.set_sensitive(False)
                b.set_tooltip_text("자막 없음")
        elif total == 1:
            lbl = "💬 자막 ON" if (self.subtitles_enabled and self.active_subtitle_indices) else "💬 자막 OFF"
            for b in btns:
                b.set_label(lbl)
                b.set_sensitive(True)
                b.set_tooltip_text("자막 켜기/끄기 (S)")
        else:
            active_cnt = len(self.active_subtitle_indices) if self.subtitles_enabled else 0
            lbl = f"💬 자막 ({active_cnt}/{total})"
            for b in btns:
                b.set_label(lbl)
                b.set_sensitive(True)
                b.set_tooltip_text(f"다중 자막 선택 메뉴 (S: 토글, C: 설정 창) - {total}개 사용 가능")

    def toggle_subtitles(self):
        """자막 켜기/끄기 상태를 토글합니다."""
        if not self.available_subtitles:
            print("ℹ️ 현재 영상에 로드된 자막이 없습니다.")
            return

        self.subtitles_enabled = not self.subtitles_enabled
        if self.subtitles_enabled and not self.active_subtitle_indices:
            self.active_subtitle_indices = set(range(len(self.available_subtitles)))

        status_str = "ON" if self.subtitles_enabled else "OFF"
        self.show_osd(f"💬 자막 {status_str}")
        self.reload_and_apply_subtitles()

    def on_key_press(self, widget, event):
        """키보드 입력 이벤트 제어"""
        keyname = Gdk.keyval_name(event.keyval)
        state = event.state
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)

        # 1. 파일 및 폴더 열기 / 스크린샷 캡처
        if is_ctrl and keyname in ["s", "S"]:
            self.capture_screenshot()
            return True
        elif is_ctrl and keyname in ["o", "O"]:
            if is_shift:
                self.open_folder_dialog()
            else:
                self.open_file_dialog()
            return True
        elif is_ctrl and keyname in ["b", "B"]:
            self.show_bookmarks_popover()
            return True
        elif not is_ctrl and not is_shift and keyname in ["b", "B"]:
            self.add_bookmark()
            return True

        # 2. 종료 및 전체화면 해제
        if keyname == "Escape":
            if self.is_fullscreen or self.is_video_only:
                self.toggle_fullscreen()
                return True
            else:
                print("⏹ 프로그램 종료.")
                self.on_destroy(widget)
                return True
        elif keyname in ["q", "Q"]:
            print("⏹ 프로그램 종료.")
            self.on_destroy(widget)
            return True

        # 3. 재생 및 탐색
        elif keyname == "space":
            self.toggle_play_pause()
            return True
        elif keyname == "Right":
            delta = 30 if is_shift else 10
            self.seek_relative(delta)
            return True
        elif keyname == "Left":
            delta = -30 if is_shift else -10
            self.seek_relative(delta)
            return True
        elif keyname in ["l", "L"]:
            self.seek_relative(10)
            return True
        elif keyname in ["j", "J"]:
            self.seek_relative(-10)
            return True

        # 4. 볼륨 조절 및 음소거 (최대 200% 부스트 지원)
        elif keyname in ["m", "M"]:
            self.toggle_mute()
            return True
        elif keyname in ["0", "parenright"]:
            cur_vol = self.volume_scale.get_value()
            self.volume_scale.set_value(min(200, cur_vol + 5))
            return True
        elif keyname in ["9", "parenleft"]:
            cur_vol = self.volume_scale.get_value()
            self.volume_scale.set_value(max(0, cur_vol - 5))
            return True

        # 5. 영상 재생 속도 제어
        elif (not is_shift and keyname in ["Up", "d", "D"]) or (is_shift and keyname in ["greater", "period"]):
            self.step_playback_rate(0.25)
            return True
        elif (not is_shift and keyname in ["Down", "a", "A"]) or (is_shift and keyname in ["less", "comma"]):
            self.step_playback_rate(-0.25)
            return True
        elif keyname in ["r", "R"]:
            if is_shift or is_ctrl:
                self.cycle_repeat_mode()
            else:
                self.reset_playback_rate()
            return True

        # 6. 영상 전환
        elif keyname in ["n", "N"]:
            self.play_next_video()
            return True
        elif keyname in ["p", "P"]:
            self.play_prev_video()
            return True

        # 7. 오디오 트랙 및 AV 싱크 제어
        elif is_shift and keyname in ["A", "a"]:
            self.cycle_audio_track()
            return True
        elif is_shift and keyname in ["z", "Z"]:
            self.adjust_av_sync(-50)
            return True
        elif is_shift and keyname in ["x", "X"]:
            self.adjust_av_sync(50)
            return True
        elif is_shift and keyname in ["c", "C"]:
            self.reset_av_sync()
            return True

        # 8. 구간 반복 (A-B Repeat)
        elif is_shift and keyname in ["[", "braceleft"]:
            self.set_ab_repeat_a()
            return True
        elif is_shift and keyname in ["]", "braceright"]:
            self.set_ab_repeat_b()
            return True
        elif keyname in ["backslash", "bar"] or (is_shift and keyname in ["backslash", "bar"]):
            self.clear_ab_repeat()
            return True

        # 9. 자막 제어 (자막 크기 및 자막 싱크)
        elif not is_shift and not is_ctrl and keyname in ["s", "S"]:
            self.toggle_subtitles()
            return True
        elif not is_shift and not is_ctrl and keyname in ["c", "C"]:
            self.show_subtitle_popover()
            return True
        elif not is_shift and keyname in ["[", "bracketleft"]:
            self.adjust_subtitle_scale(-0.1)
            return True
        elif not is_shift and keyname in ["]", "bracketright"]:
            self.adjust_subtitle_scale(0.1)
            return True
        elif not is_shift and keyname in ["z", "Z"]:
            self.adjust_subtitle_sync(-500)
            return True
        elif not is_shift and keyname in ["x", "X"]:
            self.adjust_subtitle_sync(500)
            return True
        elif not is_shift and keyname in [",", "comma"]:
            self.adjust_subtitle_sync(-100)
            return True
        elif not is_shift and keyname in [".", "period"]:
            self.adjust_subtitle_sync(100)
            return True

        # 10. 화면 및 HUD 모드
        elif keyname in ["f", "F"]:
            self.toggle_fullscreen()
            return True
        elif keyname in ["t", "T"]:
            self.toggle_keep_above()
            return True
        elif keyname in ["i", "I"]:
            self.toggle_hud()
            return True
        elif keyname in ["F1", "question"]:
            self.show_help_dialog()
            return True

        return False

    def on_destroy(self, widget):
        self.is_destroyed = True
        try:
            self.stop_web_remote_server()
            hw_cache.save()
            resume_cache.save()
            bookmark_cache.save()
            history_cache.save()
        except Exception:
            pass
        except Exception:
            pass

        if getattr(self, "click_timer_id", None):
            try:
                GLib.source_remove(self.click_timer_id)
            except Exception:
                pass
            self.click_timer_id = None

        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        self.show_cursor()

        if getattr(self, "osd_timer_id", None):
            try:
                GLib.source_remove(self.osd_timer_id)
            except Exception:
                pass
            self.osd_timer_id = None

        if getattr(self, "sub_reload_timer_id", None):
            try:
                GLib.source_remove(self.sub_reload_timer_id)
            except Exception:
                pass
            self.sub_reload_timer_id = None

        if getattr(self, "position_timer_id", None):
            try:
                GLib.source_remove(self.position_timer_id)
            except Exception:
                pass
            self.position_timer_id = None
        if self.bus is not None:
            try:
                self.bus.remove_signal_watch()
            except Exception:
                pass
            self.bus = None
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        if Gtk.main_level() > 0:
            Gtk.main_quit()

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print("사용법: jetson-player [동영상파일 또는 디렉토리 경로]")
        print("       jetson-player                 (대기 화면으로 단독 실행)")
        print("\n옵션:")
        print("  -h, --help    도움말 및 사용법 안내 출력")
        sys.exit(0)

    Gst.init(None)
    Gtk.init(None)

    user_input = sys.argv[1] if len(sys.argv) >= 2 else None
    win = JetsonSignageFlexiblePlayer(user_input)
    win.show_all()
    Gtk.main()
