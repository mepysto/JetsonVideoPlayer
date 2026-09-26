"""OpenSubtitles.com REST API (v1)로 자막 검색·다운로드 (GTK 비의존, urllib만 사용)

API 키는 https://www.opensubtitles.com/consumers 에서 무료로 발급받습니다.
키만 있어도 검색·소량 다운로드가 되고, 계정(아이디/비밀번호)을 넣으면 하루 다운로드 한도가 늘어납니다.
자격 정보는 ~/.config/jetson_video_player/opensubtitles.json (권한 600) 또는 JVP_OPENSUBTITLES_KEY 환경 변수.
"""
import json
import logging
import os
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from ..settings import CONFIG_DIR

log = logging.getLogger(__name__)

API_BASE = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "JetsonVideoPlayer v1.0"
CREDENTIALS_FILE = os.path.join(CONFIG_DIR, "opensubtitles.json")
TIMEOUT_SEC = 15
HASH_CHUNK = 64 * 1024


class OpenSubtitlesError(Exception):
    pass


@dataclass
class SubtitleResult:
    file_id: int
    language: str
    release: str
    file_name: str
    downloads: int
    hash_match: bool
    title: str


# ---- 영상 식별 -----------------------------------------------------------------

def moviehash(path):
    """OpenSubtitles 해시: 파일 크기 + 앞/뒤 64KB를 64비트 정수로 더한 값 (16자리 16진수)"""
    size = os.path.getsize(path)
    if size < HASH_CHUNK * 2:
        raise OpenSubtitlesError("파일이 너무 작습니다")
    total = size
    with open(path, "rb") as f:
        for offset in (0, size - HASH_CHUNK):
            f.seek(offset)
            chunk = f.read(HASH_CHUNK)
            total += sum(struct.unpack(f"<{HASH_CHUNK // 8}Q", chunk))
    return f"{total & 0xFFFFFFFFFFFFFFFF:016x}"


def query_from_filename(path):
    """검색어: 파일 이름에서 화질·코덱·그룹 태그를 떼어 냅니다 (Movie.Name.2019.1080p.x265-GRP → Movie Name 2019)"""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", stem)
    stem = re.sub(r"[._]+", " ", stem)
    stem = re.split(r"\b(?:480p|720p|1080p|2160p|4k|x264|x265|h264|h265|hevc|web-?dl|webrip|bluray|brrip|hdtv|aac|ddp?5|remux)\b",
                    stem, flags=re.IGNORECASE)[0]
    return re.sub(r"\s+", " ", stem).strip(" -")


# ---- 자격 정보 -------------------------------------------------------------------

def load_credentials(path=CREDENTIALS_FILE):
    """{"api_key", "username", "password", "token"} — 환경 변수 키가 있으면 우선합니다."""
    creds = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            creds = {k: v for k, v in data.items() if isinstance(v, str)}
    except (OSError, ValueError):
        pass
    if os.environ.get("JVP_OPENSUBTITLES_KEY"):
        creds["api_key"] = os.environ["JVP_OPENSUBTITLES_KEY"]
    return creds


def save_credentials(creds, path=CREDENTIALS_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in creds.items() if v}, f, ensure_ascii=False, indent=2)
    os.replace(path + ".tmp", path)


# ---- API ---------------------------------------------------------------------------

class OpenSubtitlesClient:
    def __init__(self, api_key, username=None, password=None, token=None, opener=None):
        if not api_key:
            raise OpenSubtitlesError("API 키가 없습니다")
        self.api_key = api_key
        self.username, self.password, self.token = username, password, token
        self._open = opener or urllib.request.urlopen

    def _request(self, method, path, params=None, body=None, auth=False):
        url = API_BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = {"Api-Key": self.api_key, "User-Agent": USER_AGENT, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._open(req, timeout=TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("message", "")
            except (ValueError, AttributeError, OSError):
                pass
            raise OpenSubtitlesError(f"HTTP {e.code} {detail}".strip()) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise OpenSubtitlesError(f"연결 실패: {e}") from e

    def login(self):
        """계정이 있으면 토큰을 받아 둡니다 (다운로드 한도 증가). 반환: 토큰 또는 None"""
        if not (self.username and self.password):
            return None
        data = self._request("POST", "/login", body={"username": self.username, "password": self.password})
        self.token = data.get("token")
        return self.token

    def search(self, video_path, languages=("ko", "en"), query=None):
        """해시가 맞는 자막을 먼저, 이후 다운로드 수 순서로 정렬한 결과"""
        params = {"languages": ",".join(sorted(languages))}
        try:
            params["moviehash"] = moviehash(video_path)
        except (OSError, OpenSubtitlesError):
            pass
        params["query"] = query or query_from_filename(video_path)
        data = self._request("GET", "/subtitles", params=dict(sorted(params.items())))
        return parse_search_results(data)

    def download(self, file_id):
        """자막 파일 내용(bytes). 먼저 /download로 임시 링크를 받습니다."""
        if self.username and self.password and not self.token:
            self.login()
        data = self._request("POST", "/download", body={"file_id": int(file_id)}, auth=True)
        link = data.get("link")
        if not link:
            raise OpenSubtitlesError(data.get("message") or "다운로드 링크를 받지 못했습니다")
        req = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
        try:
            with self._open(req, timeout=TIMEOUT_SEC) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise OpenSubtitlesError(f"다운로드 실패: {e}") from e


def parse_search_results(data):
    results = []
    for item in (data or {}).get("data", []):
        attrs = item.get("attributes") or {}
        files = attrs.get("files") or []
        if not files or not files[0].get("file_id"):
            continue
        details = attrs.get("feature_details") or {}
        title = details.get("title") or details.get("movie_name") or ""
        if details.get("year"):
            title = f"{title} ({details['year']})"
        results.append(SubtitleResult(
            file_id=int(files[0]["file_id"]), language=attrs.get("language") or "?",
            release=attrs.get("release") or files[0].get("file_name") or "", file_name=files[0].get("file_name") or "",
            downloads=int(attrs.get("download_count") or 0), hash_match=bool(attrs.get("moviehash_match")),
            title=title))
    results.sort(key=lambda r: (not r.hash_match, -r.downloads))
    return results


def subtitle_save_path(video_path, language, content_name=""):
    """영상 옆 <영상 이름>.<언어>.<확장자> (쓸 수 없으면 None — 호출하는 쪽이 캐시 폴더로)"""
    ext = os.path.splitext(content_name)[1].lower()
    if ext not in (".srt", ".ass", ".ssa", ".vtt", ".smi", ".sub"):
        ext = ".srt"
    stem = os.path.splitext(video_path)[0]
    lang = re.sub(r"[^a-z-]", "", (language or "").lower())[:5] or "sub"
    return f"{stem}.{lang}{ext}"
