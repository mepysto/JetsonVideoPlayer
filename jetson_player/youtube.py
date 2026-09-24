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


def youtube_format_for_quality(quality):
    """화질 선택값을 yt-dlp 포맷 문자열로 변환합니다.

    Jetson NVDEC(nvv4l2decoder) 하드웨어 가속을 보장하고 화면 미출력(AV1 DPB 결함)을 막기 위해
    H.264(avc1)를 최우선으로 선택하며, AV1(av01)은 배제합니다.
    """
    if quality in ("1080p", "720p"):
        h = quality[:-1]
        return (
            f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio/"
            f"bestvideo[height<={h}][vcodec!*='av01'][vcodec!*='av1']+bestaudio[ext=m4a]/"
            f"best[height<={h}][vcodec^=avc1]/"
            f"best[height<={h}][vcodec!*='av01']/"
            f"best[height<={h}]"
        )
    if quality == "audio":
        return "bestaudio[ext=m4a]/bestaudio"
    # "best": H.264 최고 화질 우선, 없으면 AV1을 제외한 최고 화질
    return (
        "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/"
        "bestvideo[vcodec^=avc1]+bestaudio/"
        "bestvideo[vcodec!*='av01'][vcodec!*='av1']+bestaudio[ext=m4a]/"
        "bestvideo[vcodec!*='av01'][vcodec!*='av1']+bestaudio/"
        "best[vcodec^=avc1]/"
        "best[vcodec!*='av01']/"
        "best"
    )


def _format_speed(speed):
    if speed > 1024 * 1024:
        return f"{speed / (1024 * 1024):.1f} MB/s"
    if speed > 1024:
        return f"{speed / 1024:.0f} KB/s"
    return f"{speed:.0f} B/s"


def _format_eta(eta):
    return f"{eta}초" if eta < 60 else f"{eta // 60}분 {eta % 60}초"


class DownloadCancelled(Exception):
    """사용자가 진행 중인 다운로드를 취소했습니다."""


class YouTubeManager:
    """YouTube 영상 다운로드를 대기열로 관리합니다 (한 번에 하나씩 순서대로, 취소 가능).

    콜백(on_progress/on_finish/on_error)은 항상 GTK 메인 스레드에서 호출됩니다 (GLib.idle_add).
    """
    CANCELLED_MESSAGE = "사용자가 다운로드를 취소했습니다."

    def __init__(self, download_dir=None):
        self.download_dir = download_dir or os.path.expanduser("~/Videos/YouTube")
        try:
            os.makedirs(self.download_dir, exist_ok=True)
        except Exception:
            pass
        self.current_download = {
            "active": False,
            "title": "",
            "url": "",
            "percent": 0.0,
            "speed": "",
            "eta": "",
            "filepath": None,
            "error": None,
            "completed": False,
        }
        self.pending = []           # 대기 중인 작업 목록 [{url, quality, callbacks...}]
        self._cancel_requested = False
        self.lock = threading.Lock()

    def get_status(self):
        with self.lock:
            status = dict(self.current_download)
            status["queue"] = [{"url": job["url"], "quality": job["quality"]} for job in self.pending]
            return status

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

    @staticmethod
    def _title_from_filename(path):
        title = os.path.splitext(os.path.basename(path))[0]
        if "[" in title and title.endswith("]"):
            title = title[:title.rfind("[")].strip()
        return title

    def download_async(self, url, quality="best", on_progress=None, on_finish=None, on_error=None):
        """다운로드를 요청합니다. 이미 받은 영상이면 즉시 완료, 다른 다운로드가 진행 중이면 대기열에 넣습니다.

        반환값: ("cached" | "started" | "downloading" | "queued" | "error", 대기 순번)
        """
        if not HAS_YT_DLP:
            if on_error:
                GLib.idle_add(lambda: on_error("yt-dlp 모듈이 설치되어 있지 않습니다."))
            return "error", 0

        # 1. 이미 다운로드 보관 중인 파일이 있으면 다운로드를 즉시 생략하고 캐시 파일 반환
        existing = self.find_existing_video(url)
        if existing:
            title = self._title_from_filename(existing)
            if on_finish:
                GLib.idle_add(lambda: on_finish(existing, title))
            return "cached", 0

        job = {"url": url, "quality": quality, "on_progress": on_progress, "on_finish": on_finish, "on_error": on_error}
        with self.lock:
            if self.current_download["active"]:
                if self.current_download["url"] == url:
                    return "downloading", 0          # 같은 영상을 이미 받는 중
                if all(j["url"] != url for j in self.pending):
                    self.pending.append(job)
                position = next(i + 1 for i, j in enumerate(self.pending) if j["url"] == url)
                return "queued", position
            self._begin(job)
        return "started", 0

    def cancel_current(self):
        """진행 중인 다운로드를 취소합니다 (다음 progress 콜백에서 중단)."""
        with self.lock:
            if self.current_download["active"]:
                self._cancel_requested = True
                return True
        return False

    def cancel_pending(self, url):
        with self.lock:
            before = len(self.pending)
            self.pending = [j for j in self.pending if j["url"] != url]
            return len(self.pending) != before

    def _begin(self, job):
        """[lock 보유 상태에서 호출] 작업을 시작합니다."""
        self._cancel_requested = False
        self.current_download.update({
            "active": True, "title": "정보 확인 중...", "url": job["url"], "percent": 0.0,
            "speed": "", "eta": "", "filepath": None, "error": None, "completed": False,
        })
        threading.Thread(target=self._worker, args=(job,), daemon=True).start()

    def _start_next(self):
        with self.lock:
            while self.pending:
                job = self.pending.pop(0)
                existing = self.find_existing_video(job["url"])
                if existing:
                    title = self._title_from_filename(existing)
                    if job["on_finish"]:
                        GLib.idle_add(lambda cb=job["on_finish"], p=existing, t=title: cb(p, t))
                    continue
                self._begin(job)
                return

    def _cleanup_partial_files(self, url):
        vid = extract_youtube_video_id(url)
        if not vid:
            return
        try:
            for fname in os.listdir(self.download_dir):
                if f"[{vid}]" in fname and (".part" in fname or ".ytdl" in fname or re.search(r"\.f\d+\.", fname)):
                    try:
                        os.unlink(os.path.join(self.download_dir, fname))
                    except OSError:
                        pass
        except OSError:
            pass

    def _worker(self, job):
        url, quality = job["url"], job["quality"]
        on_progress, on_finish, on_error = job["on_progress"], job["on_finish"], job["on_error"]

        def _hook(d):
            if self._cancel_requested:
                raise DownloadCancelled(self.CANCELLED_MESSAGE)
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                pct = (downloaded / total * 100.0) if total > 0 else 0.0
                speed_str = _format_speed(d.get('speed') or 0)
                eta_str = _format_eta(d.get('eta') or 0)
                title = d.get('info_dict', {}).get('title', 'YouTube Video')
                with self.lock:
                    self.current_download.update({"title": title, "percent": pct, "speed": speed_str, "eta": eta_str})
                if on_progress:
                    GLib.idle_add(lambda: on_progress(pct, speed_str, eta_str, title))
            elif d['status'] == 'finished':
                with self.lock:
                    self.current_download["filepath"] = d.get('filename', '')

        ydl_opts = {
            'format': youtube_format_for_quality(quality),
            'outtmpl': os.path.join(self.download_dir, "%(title)s [%(id)s].%(ext)s"),
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
                self.current_download.update({"active": False, "percent": 100.0, "filepath": final_filename, "completed": True})
            if on_finish:
                GLib.idle_add(lambda: on_finish(final_filename, title))
        except Exception as e:
            cancelled = self._cancel_requested or isinstance(e, DownloadCancelled) or self.CANCELLED_MESSAGE in str(e)
            err_msg = self.CANCELLED_MESSAGE if cancelled else str(e)
            if cancelled:
                self._cleanup_partial_files(url)
            with self.lock:
                self.current_download.update({"active": False, "error": err_msg})
            if on_error:
                GLib.idle_add(lambda: on_error(err_msg))
        finally:
            self._cancel_requested = False
            self._start_next()


youtube_mgr = YouTubeManager()
