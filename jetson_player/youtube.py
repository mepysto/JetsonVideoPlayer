"""YouTube URL 처리와 yt-dlp 기반 다운로드 매니저"""
import os
import re
import shutil
import threading
import urllib.parse

from gi.repository import GLib


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


def extract_youtube_video_id(url):
    """유튜브 링크에서 11자리 고유 비디오 ID를 추출합니다."""
    if not url or not isinstance(url, str):
        return None
    norm = extract_youtube_url(url)
    target = norm or url.strip()
    try:
        parsed = urllib.parse.urlparse(target)
        if "watch" in parsed.path:
            qs = urllib.parse.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return qs["v"][0]
        if "youtu.be" in parsed.netloc:
            vid = parsed.path.strip("/").split("?")[0].split("&")[0]
            if vid and len(vid) == 11:
                return vid
        for prefix in ("/shorts/", "/embed/", "/live/"):
            if parsed.path.startswith(prefix):
                vid = parsed.path[len(prefix):].split("/")[0].split("?")[0].split("&")[0]
                if vid and len(vid) == 11:
                    return vid
    except Exception:
        pass
    m = re.search(r'(?:v=|\/shorts\/|\/embed\/|\/live\/|youtu\.be\/)([a-zA-Z0-9_-]{11})(?:[&?]|$)', target)
    if m:
        return m.group(1)
    return None


def yt_dlp_js_runtimes():
    """yt-dlp의 YouTube 서명 해독용 JS 런타임(Deno 우선, 없으면 Node.js)을 PATH에서 찾습니다."""
    for name in ("deno", "node"):
        path = shutil.which(name)
        if path:
            return {name: {"path": path}}
    return None


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

    def find_existing_video(self, url_or_id):
        """이미 다운로드되어 보관 중인 유튜브 영상 파일이 있는지 검색합니다."""
        if not os.path.exists(self.download_dir):
            return None
        vid = extract_youtube_video_id(url_or_id) if (isinstance(url_or_id, str) and (url_or_id.startswith("http") or "youtube" in url_or_id or "youtu.be" in url_or_id)) else url_or_id
        if not vid:
            return None
        target_pattern = f"[{vid}]."
        try:
            for fname in sorted(os.listdir(self.download_dir)):
                if target_pattern in fname and not fname.endswith(".part"):
                    full_p = os.path.join(self.download_dir, fname)
                    if os.path.isfile(full_p) and os.path.getsize(full_p) > 512 * 1024:
                        return full_p
        except Exception:
            pass
        return None

    def download_async(self, url, quality="best", on_progress=None, on_finish=None, on_error=None):
        """백그라운드 스레드에서 유튜브 영상을 다운로드하고 진행률을 콜백합니다."""
        if not HAS_YT_DLP:
            if on_error:
                GLib.idle_add(lambda: on_error("yt-dlp 모듈이 설치되어 있지 않습니다."))
            return

        # 1. 이미 다운로드 보관 중인 파일이 있으면 다운로드를 즉시 생략하고 캐시 파일 반환
        existing = self.find_existing_video(url)
        if existing:
            base = os.path.basename(existing)
            title = os.path.splitext(base)[0]
            if "[" in title and title.endswith("]"):
                title = title[:title.rfind("[")].strip()
            with self.lock:
                self.current_download["active"] = False
                self.current_download["percent"] = 100.0
                self.current_download["filepath"] = existing
                self.current_download["completed"] = True
                self.current_download["title"] = title
            if on_finish:
                GLib.idle_add(lambda: on_finish(existing, title))
            return

        with self.lock:
            if self.current_download["active"]:
                if on_error:
                    GLib.idle_add(lambda: on_error("이미 다른 유튜브 다운로드가 진행 중입니다."))
                return
            self.current_download["active"] = True

        def _worker():
            with self.lock:
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
                'concurrent_fragment_downloads': 4,
                'remote_components': ['ejs:github'],
            }

            js_runtimes = yt_dlp_js_runtimes()
            if js_runtimes:
                ydl_opts['js_runtimes'] = js_runtimes

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
            js_runtimes = yt_dlp_js_runtimes()
            if js_runtimes:
                ydl_opts['js_runtimes'] = js_runtimes

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
                # except 블록이 끝나면 e가 삭제되므로, 나중에 실행되는 콜백에는 메시지를 미리 담아 둡니다.
                err_msg = str(e)
                if on_error:
                    GLib.idle_add(lambda: on_error(err_msg))

        threading.Thread(target=_worker, daemon=True).start()


youtube_mgr = YouTubeManager()
