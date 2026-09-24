"""이어보기/북마크/최근 기록/HW 적합성 캐시의 JSON 영구 저장소"""
import json
import os
import threading
import time


NS_PER_SECOND = 1_000_000_000

def atomic_write_json(path, data):
    """임시 파일에 먼저 쓴 뒤 교체하여, 저장 도중 전원이 꺼져도 기존 JSON이 손상되지 않게 합니다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


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
        except Exception:
            self.cache = {}

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                atomic_write_json(CACHE_FILE, self.cache)
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
    """영상의 마지막 재생 위치(이어보기)와 끝까지 시청했는지(watched)를 기억합니다.

    항목 형식: {"position_ns", "duration_ns", "updated_at", "watched"}
    position_ns가 0이면 진행 중인 위치가 없다는 뜻입니다 (끝까지 본 영상).
    """
    MAX_ENTRIES = 200
    MIN_POSITION_NS = 5 * NS_PER_SECOND
    COMPLETE_RATIO = 0.95

    def __init__(self, path=None):
        self.path = path or RESUME_FILE
        self.lock = threading.Lock()
        self.cache = {}
        self.is_dirty = False
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.cache = {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
        except Exception:
            self.cache = {}

    def save(self):
        with self.lock:
            if not self.is_dirty:
                return
            try:
                # 최대 개수 유지 (가장 오래된 항목부터 정리)
                if len(self.cache) > self.MAX_ENTRIES:
                    keep = sorted(self.cache, key=lambda k: self.cache[k].get("updated_at", 0))[-self.MAX_ENTRIES:]
                    self.cache = {k: self.cache[k] for k in keep}
                atomic_write_json(self.path, self.cache)
                self.is_dirty = False
            except Exception:
                pass

    def get(self, file_path):
        """이어서 재생할 위치를 반환합니다: (position_ns, duration_ns). 없으면 (0, 0)."""
        with self.lock:
            entry = self.cache.get(file_path)
            if entry:
                return entry.get("position_ns", 0), entry.get("duration_ns", 0)
        return 0, 0

    def get_progress(self, file_path):
        """재생목록 표시용 진행 정보: (진행률 0~1 또는 None, 끝까지 본 적 있는지)"""
        with self.lock:
            entry = self.cache.get(file_path)
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
            prev = self.cache.get(file_path, {})
            self.cache[file_path] = {
                "position_ns": position_ns,
                "duration_ns": duration_ns,
                "updated_at": time.time(),
                "watched": prev.get("watched", False),
            }
            self.is_dirty = True

    def mark_completed(self, file_path, duration_ns=0):
        """끝까지 시청: 이어보기 위치는 지우고 시청 완료 표시는 남깁니다."""
        with self.lock:
            prev = self.cache.get(file_path, {})
            if prev.get("watched") and prev.get("position_ns", 0) == 0:
                return
            self.cache[file_path] = {
                "position_ns": 0,
                "duration_ns": duration_ns or prev.get("duration_ns", 0),
                "updated_at": time.time(),
                "watched": True,
            }
            self.is_dirty = True

    def clear(self, file_path):
        with self.lock:
            if file_path in self.cache:
                self.cache.pop(file_path, None)
                self.is_dirty = True

    def recent_in_progress(self, limit=5):
        """이어볼 수 있는(진행 중인) 최근 영상 목록: [(path, position_ns, duration_ns), ...]"""
        with self.lock:
            items = [(k, v) for k, v in self.cache.items() if v.get("position_ns", 0) > 0]
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
                atomic_write_json(BOOKMARKS_FILE, self.cache)
                self.is_dirty = False
            except Exception:
                pass

    def get(self, file_path):
        with self.lock:
            return list(self.cache.get(file_path, []))

    def add(self, file_path, position_ns, label=None):
        if not file_path:
            return False, "재생 중인 영상이 없습니다."
        sec = int(position_ns / NS_PER_SECOND)
        if not label:
            m, s = divmod(sec, 60)
            h, m = divmod(m, 60)
            label = f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        with self.lock:
            entries = self.cache.setdefault(file_path, [])
            for item in entries:
                if abs(item.get("position_ns", 0) - position_ns) < NS_PER_SECOND:
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
                atomic_write_json(HISTORY_FILE, self.history)
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
