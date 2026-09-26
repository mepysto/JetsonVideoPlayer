"""AI 자막 번역: 자막 트랙을 다른 언어(기본 한국어)로 번역합니다.

번역 엔진
  - local  : Meta NLLB-200 (600M, CTranslate2 int8, CPU) — 오프라인 번역 전용 모델
             설치: ./scripts/setup_translator.sh   (모델 라이선스: CC-BY-NC 4.0, 비상업적 이용)
  - claude : Claude API (claude-opus-5) — anthropic 패키지와 API 인증 정보가 있을 때만 사용
  - auto   : local이 설치되어 있으면 local, 아니면 claude

음성 인식 자막은 문장 중간에서 줄이 끊기므로 먼저 실제 문장 단위로 다시 나눈 뒤 번역합니다.
지금 보고 있는 위치 근처부터 번역하고, 끝나면 <영상>.ai.<언어>.srt 로 저장합니다.

(범용 소형 LLM(Qwen2.5 1.5B/3B, llama.cpp)도 시험했지만 이 기기에서 줄 대응이 어긋나고 다른 문자가
 섞이는 등 자막 번역 품질이 부족해 번역 전용 모델을 사용합니다.)
"""
import importlib.util
import json
import os
import sys
import threading

from gi.repository import GLib

NLLB_HOME = os.environ.get("JVP_NLLB_DIR", os.path.expanduser("~/.local/share/jetson_video_player/nllb"))
# NLLB 언어 코드
NLLB_CODES = {"ko": "kor_Hang", "en": "eng_Latn", "ja": "jpn_Jpan", "zh": "zho_Hans",
              "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "ru": "rus_Cyrl"}
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


SENTENCE_END = (".", "?", "!", "。", "？", "！", "…", '"', "”")


def resegment_sentences(events, max_chars=120, max_gap_ms=1500):
    """음성 인식 자막은 문장 중간에서 줄이 끊기므로, 번역 전에 실제 문장 단위로 다시 나눕니다.

    각 줄의 단어에 글자 위치 비율로 시각을 배분한 뒤, 문장 끝(. ? ! 등), 긴 공백, 글자 수 한도에서 끊습니다.
    반환: [(start_ms, end_ms, sentence), ...]
    """
    words = []  # (start_ms, end_ms, word)
    for start, end, text in sorted(events):
        tokens = text.split()
        total = sum(len(t) + 1 for t in tokens) or 1
        pos = 0
        for tok in tokens:
            w_start = start + (end - start) * pos // total
            pos += len(tok) + 1
            words.append((w_start, start + (end - start) * pos // total, tok))

    sentences, cur = [], []

    def flush():
        if cur:
            sentences.append((cur[0][0], max(cur[-1][1], cur[0][0] + 800), " ".join(w for _s, _e, w in cur)))
            cur.clear()

    for word in words:
        if cur and (word[0] - cur[-1][1] > max_gap_ms or sum(len(w) + 1 for _s, _e, w in cur) + len(word[2]) > max_chars):
            flush()
        cur.append(word)
        if word[2].endswith(SENTENCE_END):
            flush()
    flush()
    return sentences


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


def plan_batches(events, position_ms, size=BATCH_SIZE, first_size=6):
    """[(시작 인덱스, 끝 인덱스), ...] — 현재 위치부터 끝까지, 그다음 앞부분 순서.

    첫 묶음은 작게(first_size) 잡아 번역된 자막이 화면에 빨리 나타나게 합니다.
    """
    n = len(events)
    start = next((i for i, ev in enumerate(events) if ev[1] >= position_ms), 0)
    batches = []
    for lo, hi in ((start, n), (0, start)):
        i = lo
        while i < hi:
            step = first_size if not batches else size
            batches.append((i, min(i + step, hi)))
            i += step
    return batches


# ---- 번역 엔진 ---------------------------------------------------------------
def nllb_paths():
    """(파이썬 라이브러리 폴더, 모델 폴더) — setup_translator.sh 가 설치한 위치"""
    return os.path.join(NLLB_HOME, "pylib"), os.path.join(NLLB_HOME, "model")


def local_available():
    pylib, model = nllb_paths()
    return (os.path.isdir(os.path.join(pylib, "ctranslate2")) and os.path.isfile(os.path.join(model, "model.bin"))
            and os.path.isfile(os.path.join(model, "sentencepiece.bpe.model")))


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


class NllbBackend:
    """NLLB-200 번역 전용 모델 (CTranslate2, CPU int8). 입력 한 줄 → 출력 한 줄이라 줄 대응이 어긋나지 않습니다."""

    def __init__(self, threads=4):
        self.threads = threads
        self.translator = None
        self.sp = None

    def start(self, cancelled):
        pylib, model = nllb_paths()
        if not local_available():
            raise RuntimeError("번역 엔진이 설치되어 있지 않습니다. ./scripts/setup_translator.sh 를 실행하세요.")
        if pylib not in sys.path:
            sys.path.append(pylib)   # 시스템 파이썬 패키지(numpy 등)를 건드리지 않는 전용 설치 폴더
        import ctranslate2
        import sentencepiece
        self.translator = ctranslate2.Translator(model, device="cpu", compute_type="int8", intra_threads=self.threads)
        self.sp = sentencepiece.SentencePieceProcessor(model_file=os.path.join(model, "sentencepiece.bpe.model"))

    def translate(self, lines, context, target, source="en"):
        src, tgt = NLLB_CODES.get(source, "eng_Latn"), NLLB_CODES[target]
        tokens = [self.sp.encode(line, out_type=str) + ["</s>", src] for line in lines]
        results = self.translator.translate_batch(tokens, target_prefix=[[tgt]] * len(lines), beam_size=2, max_batch_size=16)
        out = []
        for r in results:
            text = self.sp.decode(r.hypotheses[0][1:]).replace("⁇", "")
            out.append(" ".join(text.split()))
        return out

    def stop(self):
        # 모델 메모리(약 1.2GB)를 바로 돌려줍니다.
        self.translator = None
        self.sp = None


class ClaudeBackend:
    """Claude API 번역 (구조화 출력으로 줄 수 보장, 거절 시 서버 측 대체 모델로 재시도)."""

    def __init__(self, client=None):
        self.client = client

    def start(self, cancelled):
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic()

    def translate(self, lines, context, target, source="en"):
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
    return NllbBackend() if name == "local" else ClaudeBackend()


# ---- 번역 작업 ---------------------------------------------------------------
class TranslationJob:
    """콜백(모두 메인 스레드): on_segments([(start, end, text)]), on_status(text, fraction), on_done(events, error)"""

    def __init__(self, events, target="ko", backend=None, position_ms=0, on_segments=None, on_status=None, on_done=None,
                 source="en", resegment=True, save_path=None):
        self.events = resegment_sentences(events) if resegment else sorted(events)
        self.source = source
        self.save_path = save_path   # 끝까지 번역되면 작업 스레드에서 바로 SRT로 저장 (앱을 곧바로 닫아도 유지)
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
        result = self.backend.translate(lines, context, self.target, self.source)
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
        if not error and result and self.save_path:
            try:
                from .whisper import format_srt
                with open(self.save_path, "w", encoding="utf-8") as f:
                    f.write(format_srt(result))
            except OSError as e:
                error = f"저장 실패: {e}"
        self._emit(self.on_done, result, error)
