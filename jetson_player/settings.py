"""사용자 설정(볼륨, 자막 크기, 반복 모드, 창/사이드바 크기 등)의 영구 저장"""
import copy
import json
import logging
import os
import threading

from .storage import atomic_write_json

log = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "jetson_video_player")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "volume": 100,
    "muted": False,
    "subtitle_font_scale": 1.0,
    "repeat_mode": "all",
    "sidebar_width": 360,
    "sidebar_visible": True,
    "window_width": 1280,
    "window_height": 720,
    "window_maximized": False,
    "hud_visible": False,
    "embedded_subs_enabled": True,
    "subtitle_ass_styles": True,   # ASS/SSA 자막을 원래 글꼴·색·위치로 그림 (끄면 통일된 자막 모양)
    "time_display_remaining": False,
    "playlist_sort": "name",
    "autoplay_countdown": True,
    "night_mode": False,
    "loudness_normalize": True,   # 영상마다 다른 음량을 비슷하게 (EBU R128 측정)
    "eq_preset": "flat",
    "opensubtitles_languages": "ko,en",
    "audio_passthrough": False,
    "hdr_tonemap": True,
    "remote_pin": "",
    "remote_lan_only": True,
    "mini_width": 480,
    "mini_x": -1,               # -1: 화면 오른쪽 아래
    "mini_y": -1,
    "network_locations": [],   # [{"uri": "smb://…", "path": "/run/user/…/gvfs/…", "name": …}]
    "whisper_model": "small-q5_1",
    "whisper_language": "auto",
    "whisper_translate": False,
    "youtube_auto_ai_subtitles": False,
    "translate_target": "ko",
    "translate_backend": "auto",
    "whisper_auto_translate": False,
}

REPEAT_MODES = ("all", "one", "none", "shuffle")
PLAYLIST_SORTS = ("name", "mtime", "size")


def _validate(key, value):
    """저장 파일이 손상되었거나 이전 버전 값이어도 안전한 값만 받아들입니다."""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return default
        limits = {
            "volume": (0, 200),
            "subtitle_font_scale": (0.6, 1.6),
            "sidebar_width": (200, 2000),
            "window_width": (480, 10000),
            "window_height": (320, 10000),
            "mini_width": (240, 1280),
            "mini_x": (-1, 20000),
            "mini_y": (-1, 20000),
        }
        lo, hi = limits.get(key, (float("-inf"), float("inf")))
        value = max(lo, min(hi, value))
        return type(default)(value)
    if isinstance(default, list):
        return copy.deepcopy(value) if isinstance(value, list) else copy.deepcopy(default)
    if isinstance(default, str):
        if not isinstance(value, str):
            return default
        choices = {"repeat_mode": REPEAT_MODES, "playlist_sort": PLAYLIST_SORTS,
                   "translate_target": ("ko", "en", "ja", "zh"), "translate_backend": ("auto", "local", "claude"),
                   "eq_preset": ("flat", "dialogue", "bass", "treble", "quiet")}.get(key)
        if choices and value not in choices:
            return default
        return value
    return default


class Settings:
    """JSON 파일 기반 설정 저장소. 값이 바뀐 경우에만 디스크에 씁니다."""

    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self.lock = threading.Lock()
        self.values = copy.deepcopy(DEFAULTS)
        self._saved = None
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            for key in DEFAULTS:
                if key in data:
                    self.values[key] = _validate(key, data[key])
        self._saved = copy.deepcopy(self.values)

    def get(self, key):
        with self.lock:
            value = self.values[key]
            return copy.deepcopy(value) if isinstance(value, list) else value

    def set(self, key, value):
        if key not in DEFAULTS:
            raise KeyError(key)
        with self.lock:
            self.values[key] = _validate(key, value)

    def update(self, **kwargs):
        for key, value in kwargs.items():
            self.set(key, value)

    def save(self):
        with self.lock:
            if self.values == self._saved:
                return False
            try:
                atomic_write_json(self.path, self.values)
                self._saved = copy.deepcopy(self.values)
                return True
            except OSError as e:
                log.warning(f"⚠️ 설정 저장 실패: {e}")
                return False


settings = Settings()
