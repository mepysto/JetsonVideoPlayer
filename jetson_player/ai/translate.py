"""AI 자막 번역: 자막 트랙을 다른 언어(기본 한국어)로 번역합니다.

번역 엔진
  - local  : llama.cpp(CUDA) + Qwen2.5 — 오프라인, 설치: ./scripts/setup_translator.sh
  - claude : Claude API (claude-opus-5) — anthropic 패키지와 API 인증 정보가 있을 때만 사용
  - auto   : local이 설치되어 있으면 local, 아니면 claude

동작: 대사를 20줄 단위로 묶어 번역합니다(앞뒤 문맥 포함, 결과 줄 수를 JSON 스키마로 강제).
      지금 보고 있는 위치 근처부터 번역하고, 끝나면 <영상>.ai.<언어>.srt 로 저장합니다.
"""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from gi.repository import GLib

LLAMA_HOME = os.environ.get("JVP_LLAMA_DIR", os.path.expanduser("~/.local/share/jetson_video_player/llama.cpp"))
TARGET_LANGUAGES = {"ko": "Korean (한국어)", "en": "English", "ja": "Japanese (日本語)", "zh": "Simplified Chinese (简体中文)"}
BATCH_SIZE = 20
CONTEXT_LINES = 3
CLAUDE_MODEL = "claude-opus-5"

SYSTEM_PROMPT = (
    "You translate video subtitles. Translate each numbered line into {target}. "
    "Keep each translation short enough to read as a subtitle, keep names consistent, and keep the tone of speech. "
    "Lines under 'context' are for understanding only and must not be translated. "
    "Return exactly one translation per numbered line, in the same order."
)


def translation_schema(count):
    return {
        "type": "object",
        "properties": {
            "translations": {"type": "array", "items": {"type": "string"}, "minItems": count, "maxItems": count},
        },
        "required": ["translations"],
        "additionalProperties": False,
    }


def build_user_message(lines, context):
    parts = []
    if context:
        parts.append("context:\n" + "\n".join(f"- {c}" for c in context))
    parts.append("lines:\n" + "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines)))
    parts.append(f'Return JSON: {{"translations": [{len(lines)} strings]}}')
    return "\n\n".join(parts)


def parse_translations(text, expected):
    """모델 응답 JSON에서 번역 목록을 꺼냅니다. 개수가 다르면 None."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        items = json.loads(text[start:end]).get("translations")
    except (ValueError, AttributeError):
        return None
    if not isinstance(items, list) or len(items) != expected or not all(isinstance(t, str) for t in items):
        return None
    return [t.strip() for t in items]


def plan_batches(events, position_ms, size=BATCH_SIZE):
    """[(시작 인덱스, 끝 인덱스), ...] — 현재 위치가 포함된 묶음부터, 그 뒤, 그다음 앞부분 순서."""
    batches = [(i, min(i + size, len(events))) for i in range(0, len(events), size)]
    current = next((n for n, (a, b) in enumerate(batches) if events[b - 1][1] >= position_ms), 0)
    return batches[current:] + batches[:current]


# ---- 번역 엔진 ---------------------------------------------------------------
def find_llama_server():
    for c in (os.environ.get("JVP_LLAMA_SERVER"), os.path.join(LLAMA_HOME, "build", "bin", "llama-server"), shutil.which("llama-server")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def find_llama_model():
    model_dir = os.path.join(LLAMA_HOME, "models")
    try:
        models = sorted(f for f in os.listdir(model_dir) if f.endswith(".gguf"))
    except OSError:
        return None
    return os.path.join(model_dir, models[0]) if models else None


def local_available():
    return find_llama_server() is not None and find_llama_model() is not None


def claude_available():
    """anthropic 패키지와 인증 정보(API 키 또는 `ant auth login` 프로필)가 있는지"""
    if importlib.util.find_spec("anthropic") is None:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.path.isdir(os.path.expanduser("~/.config/anthropic")))


def resolve_backend(preference):
    """설정값(auto/local/claude) → 실제 사용할 엔진 이름 또는 None"""
    if preference in ("local", "auto") and local_available():
        return "local"
    if preference in ("claude", "auto") and claude_available():
        return "claude"
    return None


class LlamaCppBackend:
    """llama-server를 필요할 때만 띄워 번역하고, 작업이 끝나면 종료해 메모리를 돌려줍니다."""

    def __init__(self):
        self.proc = None
        self.port = None

    def start(self, cancelled):
        server, model = find_llama_server(), find_llama_model()
        if not server or not model:
            raise RuntimeError("번역 엔진이 설치되어 있지 않습니다. ./scripts/setup_translator.sh 를 실행하세요.")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.proc = subprocess.Popen(
            [server, "-m", model, "--host", "127.0.0.1", "--port", str(self.port), "-ngl", "99", "-c", "4096", "--no-webui"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 120
        while time.time() < deadline:
            if cancelled() or self.proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError("번역 엔진을 시작하지 못했습니다.")

    def translate(self, lines, context, target):
        body = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.format(target=TARGET_LANGUAGES[target])},
                {"role": "user", "content": build_user_message(lines, context)},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
            "response_format": {"type": "json_schema", "schema": translation_schema(len(lines))},
        }
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/v1/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            reply = json.loads(r.read().decode("utf-8"))
        return parse_translations(reply["choices"][0]["message"]["content"], len(lines))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class ClaudeBackend:
    """Claude API 번역 (구조화 출력으로 줄 수 보장, 거절 시 서버 측 대체 모델로 재시도)."""

    def __init__(self, client=None):
        self.client = client

    def start(self, cancelled):
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic()

    def translate(self, lines, context, target):
        response = self.client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT.format(target=TARGET_LANGUAGES[target]),
            messages=[{"role": "user", "content": build_user_message(lines, context)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": translation_schema(len(lines))}},
        )
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        return parse_translations(text, len(lines))

    def stop(self):
        pass


def make_backend(name):
    return LlamaCppBackend() if name == "local" else ClaudeBackend()


# ---- 번역 작업 ---------------------------------------------------------------
class TranslationJob:
    """콜백(모두 메인 스레드): on_segments([(start, end, text)]), on_status(text, fraction), on_done(events, error)"""

    def __init__(self, events, target="ko", backend=None, position_ms=0, on_segments=None, on_status=None, on_done=None):
        self.events = sorted(events)
        self.target = target
        self.backend = backend
        self.position_ms = position_ms
        self.on_segments = on_segments
        self.on_status = on_status
        self.on_done = on_done
        self.cancelled = False
        self.translated = {}
        self.thread = threading.Thread(target=self._run, daemon=True, name="ai-translate")

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancelled = True

    def is_running(self):
        return self.thread.is_alive()

    def _emit(self, fn, *args):
        if fn:
            GLib.idle_add(lambda: (fn(*args), False)[1])

    def _translate_range(self, a, b):
        """묶음 번역. 줄 수가 맞지 않으면 반으로 나눠 재시도하고, 한 줄도 실패하면 원문을 둡니다."""
        lines = [text.replace("\n", " ") for _s, _e, text in self.events[a:b]]
        context = [text.replace("\n", " ") for _s, _e, text in self.events[max(0, a - CONTEXT_LINES):a]]
        result = self.backend.translate(lines, context, self.target)
        if result is not None:
            return result
        if b - a == 1:
            return lines
        mid = (a + b) // 2
        return self._translate_range(a, mid) + self._translate_range(mid, b)

    def _run(self):
        error = None
        try:
            if not self.events:
                raise RuntimeError("번역할 자막이 없습니다.")
            self._emit(self.on_status, "🌐 번역 엔진 준비 중...", 0.0)
            self.backend.start(lambda: self.cancelled)
            total = len(self.events)
            for a, b in plan_batches(self.events, self.position_ms):
                if self.cancelled:
                    break
                translations = self._translate_range(a, b)
                batch = []
                for i, (start, end, _src), text in zip(range(a, b), self.events[a:b], translations):
                    if text:
                        self.translated[i] = (start, end, text)
                        batch.append((start, end, text))
                self._emit(self.on_segments, batch)
                frac = len(self.translated) / total
                self._emit(self.on_status, f"🌐 자막 번역 중 {frac * 100:.0f}%", frac)
        except Exception as e:
            error = str(e)
        finally:
            try:
                self.backend.stop()
            except Exception:
                pass
        if self.cancelled:
            error = "취소됨"
        result = [self.translated[i] for i in sorted(self.translated)]
        self._emit(self.on_done, result, error)
