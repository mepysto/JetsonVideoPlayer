"""재생목록 전체 자막에서 대사를 찾아 해당 장면으로 이동하기 위한 색인 (GTK 비의존)

색인은 영상별 자막 파일의 (경로, 수정 시각)으로 캐시하므로, 재생목록이 바뀌어도 바뀐 영상만 다시 읽습니다.
build()는 백그라운드 스레드에서, search()는 어느 스레드에서든(리모컨 HTTP 스레드 포함) 부를 수 있습니다.
"""
import os
import re
import threading
from collections import namedtuple

from .parse import find_all_matching_subtitles, get_subtitle_label, parse_subtitle_file_events

SearchHit = namedtuple("SearchHit", "video start_ms text label")

_SPACES = re.compile(r"\s+")


def normalize(text):
    """대소문자·줄바꿈·연속 공백을 무시하고 비교하기 위한 형태"""
    return _SPACES.sub(" ", text).strip().casefold()


def _file_signature(paths):
    sig = []
    for p in paths:
        try:
            sig.append((p, os.stat(p).st_mtime_ns))
        except OSError:
            pass
    return tuple(sig)


class DialogueIndex:
    def __init__(self, find_subtitles=find_all_matching_subtitles, parse=parse_subtitle_file_events):
        self._find_subtitles = find_subtitles
        self._parse = parse
        self._lock = threading.Lock()
        self._videos = []          # 재생목록 순서
        self._entries = {}         # video → (signature, [(start_ms, norm, text, label)])

    def build(self, videos, cancelled=lambda: False):
        """videos(재생목록)의 자막을 읽어 색인합니다. 바뀌지 않은 영상은 다시 읽지 않습니다."""
        videos = list(videos)
        with self._lock:
            self._videos = videos
            known = dict(self._entries)
        fresh = {}
        for video in videos:
            if cancelled():
                return False
            sig = _file_signature(self._find_subtitles(video))
            cached = known.get(video)
            if cached and cached[0] == sig:
                fresh[video] = cached
                continue
            lines = []
            for sub_path, _mtime in sig:
                label = get_subtitle_label(sub_path)
                for start_ms, _end_ms, text in self._parse(sub_path):
                    if text.strip():
                        lines.append((start_ms, normalize(text), text.strip(), label))
            lines.sort(key=lambda row: row[0])
            fresh[video] = (sig, lines)
        with self._lock:
            if self._videos is videos:
                self._entries = fresh
        return True

    def invalidate(self, video):
        """이 영상의 자막이 새로 생겼거나 바뀌었을 때 (다음 build에서 다시 읽음)"""
        with self._lock:
            self._entries.pop(video, None)

    def search(self, query, limit=200, first_video=None):
        """query가 들어 있는 대사 목록. first_video(지금 보는 영상)의 결과를 먼저, 이후 재생목록 순서."""
        needle = normalize(query)
        if not needle:
            return []
        with self._lock:
            order = list(self._videos)
            entries = dict(self._entries)
        if first_video in entries:
            order = [first_video] + [v for v in order if v != first_video]
        hits = []
        for video in order:
            entry = entries.get(video)
            if not entry:
                continue
            for start_ms, norm, text, label in entry[1]:
                if needle in norm:
                    hits.append(SearchHit(video, start_ms, text, label))
                    if len(hits) >= limit:
                        return hits
        return hits

    def line_count(self):
        with self._lock:
            return sum(len(e[1]) for e in self._entries.values())
