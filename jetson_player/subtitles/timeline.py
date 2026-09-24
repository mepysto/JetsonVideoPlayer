"""자막 트랙의 시간 조회: 재생 위치(ms)에 표시할 대사를 빠르게 찾습니다.

플레이어는 이 결과를 화면 위 오버레이에 직접 그리므로, 싱크/크기/트랙 선택이 바뀌어도
GStreamer 파이프라인을 다시 만들 필요가 없습니다. AI 자막처럼 이벤트가 계속 추가되는 트랙도 지원합니다.
"""
import bisect
import threading

SHORT_BADGES = [
    ("한국어", "[KR] "),
    ("영어", "[EN] "),
    ("중국어", "[TW] "),
    ("대만", "[TW] "),
    ("zh-tw", "[TW] "),
    ("일본어", "[JP] "),
    ("스페인어", "[ES] "),
    ("프랑스어", "[FR] "),
    ("독일어", "[DE] "),
    ("AI", "[AI] "),
]


def short_badge(label):
    """자막 레이블에서 짧은 언어 뱃지([KR], [EN] 등)를 추출합니다."""
    lower = label.lower()
    for key, badge in SHORT_BADGES:
        if key.lower() in lower:
            return badge
    return ""


class SubtitleTrack:
    """시작 시각으로 정렬된 자막 이벤트 [(start_ms, end_ms, text), ...] 목록"""

    def __init__(self, label, color, events=()):
        self.label = label
        self.color = color
        self._lock = threading.Lock()
        self.events = []
        self.starts = []
        self.max_duration = 0
        self.add_events(events)

    def add_events(self, events):
        """이벤트를 추가합니다 (AI 자막 생성처럼 백그라운드에서 조금씩 추가되어도 안전)."""
        events = [(int(s), int(e), t) for s, e, t in events if e > s and t and not t.isspace()]
        if not events:
            return
        with self._lock:
            self.events.extend(events)
            self.events.sort(key=lambda ev: (ev[0], ev[1]))
            self.starts = [ev[0] for ev in self.events]
            self.max_duration = max(self.max_duration, max(e - s for s, e, _ in events))

    def __len__(self):
        return len(self.events)

    def active_at(self, t_ms):
        """t_ms 시점에 표시 중인 대사 목록 (시작 순)"""
        with self._lock:
            idx = bisect.bisect_right(self.starts, t_ms)
            found = []
            i = idx - 1
            while i >= 0 and self.starts[i] >= t_ms - self.max_duration:
                start, end, text = self.events[i]
                if start <= t_ms < end:
                    found.append(text)
                i -= 1
        found.reverse()
        return found

    def next_change_after(self, t_ms):
        """t_ms 이후 처음으로 표시 내용이 바뀔 수 있는 시각 (없으면 None) — 다시 그릴 시점 계산용"""
        with self._lock:
            idx = bisect.bisect_right(self.starts, t_ms)
            candidates = []
            if idx < len(self.starts):
                candidates.append(self.starts[idx])
            i = idx - 1
            while i >= 0 and self.starts[i] >= t_ms - self.max_duration:
                end = self.events[i][1]
                if end > t_ms:
                    candidates.append(end)
                i -= 1
        return min(candidates) if candidates else None


def active_lines(tracks, position_ms, offset_ms=0):
    """여러 트랙에서 지금 표시할 줄 목록 [(text, color), ...].

    offset_ms > 0 이면 자막이 늦게(뒤로) 표시됩니다. 트랙이 둘 이상이면 언어 뱃지를 붙입니다.
    """
    t = position_ms - offset_ms
    multi = len(tracks) > 1
    lines = []
    for track in tracks:
        badge = short_badge(track.label) if multi else ""
        for text in track.active_at(t):
            parts = [p.strip() for p in text.splitlines() if p.strip()]
            for n, part in enumerate(parts):
                lines.append(((badge if n == 0 else "") + part, track.color or "#FFFFFF"))
    return lines
