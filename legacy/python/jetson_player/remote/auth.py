"""웹 리모컨 접속 인증: 4자리 PIN으로 로그인하면 기기별 토큰(쿠키)을 발급합니다.

- PIN은 설정 파일에 저장되어 재시작해도 유지되며, 팝오버에서 새로 만들 수 있습니다.
- 토큰은 해시로만 저장합니다 (~/.config/jetson_video_player/remote_tokens.json).
- 같은 IP에서 PIN을 연속으로 틀리면 잠시 로그인을 막습니다.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from ..storage import atomic_write_json

MAX_TOKENS = 20
MAX_FAILURES = 8
LOCK_SECONDS = 300


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_pin():
    return f"{secrets.randbelow(10000):04d}"


class RemoteAuth:
    def __init__(self, pin, token_file, now=time.monotonic):
        self.pin = pin
        self.token_file = token_file
        self.now = now
        self.lock = threading.Lock()
        self.failures = {}          # ip → (실패 횟수, 첫 실패 시각)
        self.token_hashes = self._load()

    def _load(self):
        try:
            with open(self.token_file, encoding="utf-8") as f:
                data = json.load(f)
            return [h for h in data if isinstance(h, str)][-MAX_TOKENS:]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self):
        try:
            atomic_write_json(self.token_file, self.token_hashes)
        except OSError:
            pass

    def is_locked(self, ip):
        with self.lock:
            count, first = self.failures.get(ip, (0, 0))
            if count >= MAX_FAILURES and self.now() - first < LOCK_SECONDS:
                return True
            if count and self.now() - first >= LOCK_SECONDS:
                self.failures.pop(ip, None)
            return False

    def login(self, ip, pin):
        """PIN이 맞으면 새 토큰 문자열, 틀리면 None, 잠금 중이면 'locked'"""
        if self.is_locked(ip):
            return "locked"
        if not isinstance(pin, str) or not hmac.compare_digest(pin.strip(), self.pin):
            with self.lock:
                count, first = self.failures.get(ip, (0, self.now()))
                self.failures[ip] = (count + 1, first)
            return None
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.failures.pop(ip, None)
            self.token_hashes = (self.token_hashes + [_hash(token)])[-MAX_TOKENS:]
            self._save()
        return token

    def is_valid(self, token):
        if not token:
            return False
        h = _hash(token)
        with self.lock:
            return any(hmac.compare_digest(h, known) for known in self.token_hashes)

    def reset(self, new_pin):
        """PIN을 바꾸고 기존에 로그인한 모든 기기를 로그아웃시킵니다."""
        with self.lock:
            self.pin = new_pin
            self.token_hashes = []
            self.failures.clear()
            self._save()


def default_token_file():
    from ..settings import CONFIG_DIR
    return os.path.join(CONFIG_DIR, "remote_tokens.json")
