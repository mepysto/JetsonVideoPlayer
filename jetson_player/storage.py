"""이어보기/북마크/최근 기록/HW 적합성 캐시의 JSON 영구 저장소"""
import json
import logging
import os
import threading
import time

log = logging.getLogger(__name__)


NS_PER_SECOND = 1_000_000_000

def atomic_write_json(path, data):
    """임시 파일에 먼저 쓴 뒤 교체하여, 저장 도중 전원이 꺼져도 기존 JSON이 손상되지 않게 합니다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


CACHE_DIR = os.path.expanduser("~/.cache/jetson_video_player")


class JsonStore:
    """JSON 파일 하나를 메모리에 올려 두고, 바뀐 경우에만 원자적으로 저장하는 저장소의 공통 부분.

    하위 클래스는 self.data 를 self.lock 안에서 읽고 쓰며, 바꾼 뒤 self.is_dirty = True 로 표시합니다.
    파일이 없거나 손상됐으면 빈 값(default_factory())으로 시작합니다.
    """

    def __init__(self, path, default_factory):
        self.path = path
        self.default_factory = default_factory
        self.lock = threading.Lock()
        self.is_dirty = False
        self.data = default_factory()
        self._load()

    def _valid(self, data):
        """불러온 값을 검증해 사용할 값을 반환합니다 (형식이 틀리면 None → 빈 값)."""
        return data if isinstance(data, type(self.default_factory())) else None

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = self._valid(json.load(f))
        except (OSError, ValueError):
            loaded = None
        self.data = loaded if loaded is not None else self.default_factory()

    def _before_save(self):
        """[lock 보유] 저장 직전 정리 (하위 클래스에서 필요 시 재정의)"""

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                self._before_save()
                atomic_write_json(self.path, self.data)
                self.is_dirty = False
            except (OSError, TypeError, ValueError) as e:
                log.warning(f"⚠️ 저장 실패 ({os.path.basename(self.path)}): {e}")


CACHE_FILE = os.path.join(CACHE_DIR, "hw_cache.json")
HW_CACHE_VERSION = 2   # v2: 실제 NVDEC 능력 기준 판정 (v1의 AV1/VP9 '미지원' 판정은 무시하고 다시 검사)


def _file_signature(file_path):
    try:
        st = os.stat(file_path)
        return st.st_mtime, st.st_size
    except OSError:
        return None


class HWSupportCache(JsonStore):
    """영상 파일별 NVDEC 지원 판정 결과 캐시 (파일 크기/수정 시각이 같을 때만 재사용)."""

    def __init__(self, path=None):
        super().__init__(path or CACHE_FILE, dict)

    def get(self, file_path):
        sig = _file_signature(file_path)
        if sig is None:
            return None
        with self.lock:
            entry = self.data.get(file_path)
            if entry and entry.get("v") == HW_CACHE_VERSION and (entry.get("mtime"), entry.get("size")) == sig:
                return entry.get("supported", False), entry.get("reason", "")
        return None

    def set(self, file_path, supported, reason):
        mtime, size = _file_signature(file_path) or (0, 0)
        with self.lock:
            self.data[file_path] = {"mtime": mtime, "size": size, "supported": supported,
                                    "reason": reason, "v": HW_CACHE_VERSION}
            self.is_dirty = True


hw_cache = HWSupportCache()


RESUME_FILE = os.path.join(CACHE_DIR, "resume_cache.json")


class ResumeCache(JsonStore):
    """영상의 마지막 재생 위치(이어보기)와 끝까지 시청했는지(watched)를 기억합니다.

    항목 형식: {"position_ns", "duration_ns", "updated_at", "watched"}
    position_ns가 0이면 진행 중인 위치가 없다는 뜻입니다 (끝까지 본 영상).
    """
    MAX_ENTRIES = 200
    MIN_POSITION_NS = 5 * NS_PER_SECOND
    COMPLETE_RATIO = 0.95

    def __init__(self, path=None):
        super().__init__(path or RESUME_FILE, dict)

    def _before_save(self):
        # 최대 개수 유지 (가장 오래된 항목부터 정리)
        if len(self.data) > self.MAX_ENTRIES:
            keep = sorted(self.data, key=lambda k: self.data[k].get("updated_at", 0))[-self.MAX_ENTRIES:]
            self.data = {k: self.data[k] for k in keep}

    def _valid(self, data):
        return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else None

    def get(self, file_path):
        """이어서 재생할 위치를 반환합니다: (position_ns, duration_ns). 없으면 (0, 0)."""
        with self.lock:
            entry = self.data.get(file_path)
            if entry:
                return entry.get("position_ns", 0), entry.get("duration_ns", 0)
        return 0, 0

    def get_progress(self, file_path):
        """재생목록 표시용 진행 정보: (진행률 0~1 또는 None, 끝까지 본 적 있는지)"""
        with self.lock:
            entry = self.data.get(file_path)
            if not entry:
                return None, False
            pos, dur = entry.get("position_ns", 0), entry.get("duration_ns", 0)
            ratio = (pos / dur) if (pos > 0 and dur > 0) else None
            return ratio, bool(entry.get("watched", False))

    def set(self, file_path, position_ns, duration_ns):
        # 5초 이상 재생되었고, 영상 끝 95% 이전인 경우에만 위치 저장 (이후는 시청 완료 처리)
        if position_ns < self.MIN_POSITION_NS:
            return
        if duration_ns > 0 and position_ns > duration_ns * self.COMPLETE_RATIO:
            self.mark_completed(file_path, duration_ns)
            return

        with self.lock:
            prev = self.data.get(file_path, {})
            self.data[file_path] = {
                "position_ns": position_ns,
                "duration_ns": duration_ns,
                "updated_at": time.time(),
                "watched": prev.get("watched", False),
            }
            self.is_dirty = True

    def mark_completed(self, file_path, duration_ns=0):
        """끝까지 시청: 이어보기 위치는 지우고 시청 완료 표시는 남깁니다."""
        with self.lock:
            prev = self.data.get(file_path, {})
            if prev.get("watched") and prev.get("position_ns", 0) == 0:
                return
            self.data[file_path] = {
                "position_ns": 0,
                "duration_ns": duration_ns or prev.get("duration_ns", 0),
                "updated_at": time.time(),
                "watched": True,
            }
            self.is_dirty = True

    def clear(self, file_path):
        with self.lock:
            if file_path in self.data:
                self.data.pop(file_path, None)
                self.is_dirty = True

    def recent_in_progress(self, limit=5):
        """이어볼 수 있는(진행 중인) 최근 영상 목록: [(path, position_ns, duration_ns), ...]"""
        with self.lock:
            items = [(k, v) for k, v in self.data.items() if v.get("position_ns", 0) > 0]
        items.sort(key=lambda kv: kv[1].get("updated_at", 0), reverse=True)
        result = []
        for path, entry in items:
            if os.path.isfile(path):
                result.append((path, entry["position_ns"], entry.get("duration_ns", 0)))
            if len(result) >= limit:
                break
        return result


resume_cache = ResumeCache()


BOOKMARKS_FILE = os.path.join(CACHE_DIR, "bookmarks.json")


class BookmarkCache(JsonStore):
    """영상 파일별 북마크 목록 {경로: [{"position_ns", "label", "created_at"}, ...]}"""

    def __init__(self, path=None):
        super().__init__(path or BOOKMARKS_FILE, dict)

    def get(self, file_path):
        with self.lock:
            return list(self.data.get(file_path, []))

    def add(self, file_path, position_ns, label=None):
        if not file_path:
            return False, "재생 중인 영상이 없습니다."
        if not label:
            m, s = divmod(int(position_ns / NS_PER_SECOND), 60)
            h, m = divmod(m, 60)
            label = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        with self.lock:
            entries = self.data.setdefault(file_path, [])
            if any(abs(item.get("position_ns", 0) - position_ns) < NS_PER_SECOND for item in entries):
                return False, "이미 등록된 북마크 지점입니다."
            entries.append({"position_ns": position_ns, "label": label, "created_at": time.time()})
            entries.sort(key=lambda x: x.get("position_ns", 0))
            self.is_dirty = True
        return True, label

    def remove(self, file_path, index):
        with self.lock:
            entries = self.data.get(file_path, [])
            if 0 <= index < len(entries):
                entries.pop(index)
                self.is_dirty = True
                return True
        return False


bookmark_cache = BookmarkCache()


HISTORY_FILE = os.path.join(CACHE_DIR, "history.json")
HISTORY_LIMIT = 15


class HistoryCache(JsonStore):
    """최근 재생한 파일/폴더 목록 (최신순, 최대 HISTORY_LIMIT개)"""

    def __init__(self, path=None):
        super().__init__(path or HISTORY_FILE, list)

    def add(self, path):
        if not path or not os.path.exists(path):
            return
        abs_path = os.path.abspath(path)
        entry = {"path": abs_path, "title": os.path.basename(abs_path) or abs_path,
                 "is_dir": os.path.isdir(abs_path), "timestamp": time.time()}
        with self.lock:
            self.data = [entry] + [h for h in self.data if isinstance(h, dict) and h.get("path") != abs_path]
            del self.data[HISTORY_LIMIT:]
            self.is_dirty = True

    def get_all(self):
        with self.lock:
            return list(self.data)


history_cache = HistoryCache()
