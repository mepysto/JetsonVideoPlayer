"""AI 자막 생성: whisper.cpp(CUDA)로 영상 음성을 인식해 자막을 만듭니다.

설치: ./scripts/setup_whisper.sh   (기본 설치 위치 ~/.local/share/jetson_video_player/whisper.cpp)

동작
  1) GStreamer로 음성을 16kHz 모노 WAV로 추출 (ffmpeg 불필요)
  2) whisper-cli 실행 — 지금 보고 있는 위치부터 먼저 인식한 뒤 앞부분을 이어서 인식
  3) 인식된 문장을 즉시 콜백으로 전달 (화면에 실시간 표시), 끝나면 영상 옆에 .ai.<언어>.srt 저장
"""
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from gi.repository import GLib, Gst

from ..subtitles.parse import AI_SUBTITLE_CACHE_DIR, cached_ai_subtitle_stem

log = logging.getLogger(__name__)

WHISPER_HOME = os.environ.get("JVP_WHISPER_DIR", os.path.expanduser("~/.local/share/jetson_video_player/whisper.cpp"))
SEGMENT_RE = re.compile(r"^\[(\d+):(\d+):(\d+)\.(\d+)\s*-->\s*(\d+):(\d+):(\d+)\.(\d+)\]\s*(.*)$")
LANG_RE = re.compile(r"auto-detected language:\s*([a-z]{2,3})")
LANGUAGE_NAMES = {"ko": "한국어", "en": "영어", "ja": "일본어", "zh": "중국어", "es": "스페인어", "fr": "프랑스어", "de": "독일어", "ru": "러시아어"}


def find_whisper_binary():
    candidates = [os.environ.get("JVP_WHISPER_BIN"), os.path.join(WHISPER_HOME, "build", "bin", "whisper-cli"), shutil.which("whisper-cli")]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


# 알려진 모델 설명 (Orin Nano 8GB, 60초 음성 실측)
MODEL_NOTES = {
    "small-q5_1": "기본 — 60초 음성 4.6초, 메모리 약 1.0GB",
    "large-v3-turbo-q5_0": "더 정확 — 60초 음성 6.4초, 메모리 약 1.4GB",
}
MODEL_FILE_RE = re.compile(r"^ggml-(.+)\.bin$")


def list_whisper_models():
    """설치된 모델 이름 목록 (whisper.cpp 저장소의 테스트용 더미 모델 제외)"""
    try:
        names = [m.group(1) for f in os.listdir(os.path.join(WHISPER_HOME, "models"))
                 if (m := MODEL_FILE_RE.match(f))]
    except OSError:
        return []
    return sorted(names)


def find_whisper_model(model_name="small-q5_1"):
    """설정된 모델을 우선 찾고, 없으면 설치된 아무 모델이나 사용합니다."""
    model_dir = os.path.join(WHISPER_HOME, "models")
    preferred = os.path.join(model_dir, f"ggml-{model_name}.bin")
    if os.path.isfile(preferred):
        return preferred
    try:
        found = sorted(f for f in os.listdir(model_dir) if f.startswith("ggml-") and f.endswith(".bin"))
    except OSError:
        found = []
    return os.path.join(model_dir, found[0]) if found else None


def whisper_available(model_name="small-q5_1"):
    return find_whisper_binary() is not None and find_whisper_model(model_name) is not None


def _ms(h, m, s, frac):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0")[:3])


def parse_whisper_line(line):
    """'[00:00:01.000 --> 00:00:04.500]   text' → (1000, 4500, 'text') 또는 None"""
    m = SEGMENT_RE.match(line.strip())
    if not m:
        return None
    g = m.groups()
    text = g[8].strip()
    if not text or text in ("[BLANK_AUDIO]", "[Music]", "[음악]") or (text.startswith("[") and text.endswith("]")):
        return None
    start, end = _ms(*g[0:4]), _ms(*g[4:8])
    return (start, end, text) if end > start else None


def plan_passes(duration_ms, start_ms, first_chunk_ms=60_000, chunk_ms=300_000):
    """인식 순서: 현재 위치 → 끝, 그다음 처음 → 현재 위치.

    첫 구간은 짧게(빠른 첫 자막), 이후는 길게 나눠 모델 재로딩 횟수를 줄입니다.
    반환: [(offset_ms, length_ms), ...]
    """
    start_ms = max(0, min(start_ms, duration_ms))
    if start_ms < 30_000:
        start_ms = 0
    passes = []
    for a, b in ((start_ms, duration_ms), (0, start_ms)):
        pos = a
        while pos < b:
            size = first_chunk_ms if not passes else chunk_ms
            length = min(size, b - pos)
            passes.append((pos, length))
            pos += length
    return passes


def format_srt(events):
    def ts(ms):
        h, rem = divmod(ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms_ = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms_:03d}"
    lines = []
    for n, (start, end, text) in enumerate(sorted(events), 1):
        lines += [str(n), f"{ts(start)} --> {ts(end)}", text, ""]
    return "\n".join(lines)


def ai_subtitle_path(video_path, language, translate=False):
    """영상 옆 저장 경로 (쓰기 불가 폴더면 캐시 폴더)"""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    lang = "en" if translate else (language or "auto")
    folder = os.path.dirname(os.path.abspath(video_path))
    if os.access(folder, os.W_OK):
        return os.path.join(folder, f"{stem}.ai.{lang}.srt")
    os.makedirs(AI_SUBTITLE_CACHE_DIR, exist_ok=True)
    return os.path.join(AI_SUBTITLE_CACHE_DIR, f"{cached_ai_subtitle_stem(video_path)}.ai.{lang}.srt")


def extract_audio_wav(video_path, wav_path, cancelled=lambda: False):
    """GStreamer로 음성을 16kHz 모노 16bit WAV로 추출합니다. 음성 트랙이 없으면 예외."""
    pipeline = Gst.parse_launch(
        "filesrc name=src ! decodebin name=dec "
        "dec. ! queue ! audioconvert ! audioresample ! audio/x-raw,rate=16000,channels=1,format=S16LE ! wavenc ! filesink name=out"
    )
    pipeline.get_by_name("src").set_property("location", video_path)
    pipeline.get_by_name("out").set_property("location", wav_path)
    bus = pipeline.get_bus()
    pipeline.set_state(Gst.State.PLAYING)
    try:
        while True:
            if cancelled():
                raise InterruptedError("취소됨")
            msg = bus.timed_pop_filtered(200 * Gst.MSECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            if msg is None:
                continue
            if msg.type == Gst.MessageType.ERROR:
                raise RuntimeError(f"음성 추출 실패: {msg.parse_error()[0].message}")
            break
    finally:
        pipeline.set_state(Gst.State.NULL)
    if not os.path.exists(wav_path) or os.path.getsize(wav_path) <= 44:
        raise RuntimeError("영상에 음성 트랙이 없습니다.")


class AiSubtitleJob:
    """백그라운드 AI 자막 생성 작업.

    콜백(모두 메인 스레드): on_segments([(start, end, text)]), on_status(text, fraction), on_done(srt_path, language, error)
    """

    def __init__(self, video_path, duration_ms, start_ms=0, language="auto", translate=False, model_name="small-q5_1",
                 on_segments=None, on_status=None, on_done=None):
        self.video_path = video_path
        self.duration_ms = duration_ms
        self.start_ms = start_ms
        self.language = language
        self.translate = translate
        self.model_name = model_name
        self.on_segments = on_segments
        self.on_status = on_status
        self.on_done = on_done
        self.cancelled = False
        self.detected_language = None
        self.events = []
        self.processed_ms = 0
        self._proc = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="ai-subtitles")

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancelled = True
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()

    def is_running(self):
        return self.thread.is_alive()

    def _emit(self, fn, *args):
        if fn:
            GLib.idle_add(lambda: (fn(*args), False)[1])

    def _run(self):
        error, srt_path = None, None
        workdir = tempfile.mkdtemp(prefix="jvp_ai_")
        try:
            binary, model = find_whisper_binary(), find_whisper_model(self.model_name)
            if not binary or not model:
                raise RuntimeError("whisper.cpp가 설치되어 있지 않습니다. ./scripts/setup_whisper.sh 를 실행하세요.")
            self._emit(self.on_status, "🎧 음성 추출 중...", 0.0)
            wav = os.path.join(workdir, "audio.wav")
            extract_audio_wav(self.video_path, wav, cancelled=lambda: self.cancelled)

            started = time.time()
            for offset, length in plan_passes(self.duration_ms, self.start_ms):
                if self.cancelled:
                    break
                self._transcribe(binary, model, wav, offset, length)
                self.processed_ms += length
                frac = self.processed_ms / self.duration_ms if self.duration_ms else 0
                self._emit(self.on_status, f"🤖 AI 자막 생성 중 {frac * 100:.0f}%", frac)
            if self.cancelled:
                raise InterruptedError("취소됨")
            if not self.events:
                raise RuntimeError("인식된 대사가 없습니다.")
            lang = "en" if self.translate else (self.detected_language or self.language)
            srt_path = ai_subtitle_path(self.video_path, lang, self.translate)
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(format_srt(self.events))
            log.info(f"🤖 [AI 자막] {len(self.events)}문장, {time.time() - started:.1f}초 → {srt_path}")
        except InterruptedError:
            error = "취소됨"
        except Exception as e:
            error = str(e)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        self._emit(self.on_done, srt_path, self.detected_language, error)

    def _transcribe(self, binary, model, wav, offset_ms, length_ms):
        lang = self.detected_language or self.language or "auto"
        cmd = [binary, "-m", model, "-f", wav, "-l", lang, "-ot", str(offset_ms), "-d", str(length_ms), "-t", "4"]
        if self.translate:
            cmd.append("-tr")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

        def read_stderr(stream):
            for line in stream:
                m = LANG_RE.search(line)
                if m and not self.detected_language:
                    self.detected_language = m.group(1)
        err_thread = threading.Thread(target=read_stderr, args=(self._proc.stderr,), daemon=True)
        err_thread.start()
        batch = []
        last_flush = time.time()
        for line in self._proc.stdout:
            seg = parse_whisper_line(line)
            if seg:
                batch.append(seg)
            if batch and (time.time() - last_flush > 0.5):
                self._flush(batch)
                batch, last_flush = [], time.time()
        self._proc.wait()
        err_thread.join(timeout=1)
        if batch:
            self._flush(batch)

    def _flush(self, batch):
        self.events.extend(batch)
        self._emit(self.on_segments, list(batch))
