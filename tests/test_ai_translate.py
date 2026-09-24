import time
from types import SimpleNamespace

import pytest

from jetson_player.ai import translate
from jetson_player.ai.translate import ClaudeBackend, TranslationJob, parse_translations, plan_batches


class FakeGLib:
    @staticmethod
    def idle_add(fn, *args):
        fn(*args)


@pytest.fixture(autouse=True)
def sync_glib(monkeypatch):
    monkeypatch.setattr(translate, "GLib", FakeGLib)


def ev(n, step=1000):
    return [(i * step, i * step + 900, f"line {i}") for i in range(n)]


def test_parse_translations():
    assert parse_translations('{"translations": ["가", "나"]}', 2) == ["가", "나"]
    assert parse_translations('설명... {"translations": ["가"]} 끝', 1) == ["가"]     # 앞뒤 잡음 허용
    assert parse_translations('{"translations": ["가"]}', 2) is None                   # 개수 불일치
    assert parse_translations("not json", 1) is None


def test_plan_batches_starts_near_position():
    events = ev(50)
    batches = plan_batches(events, position_ms=25_500, size=20)
    assert batches[0] == (25, 31)                                   # 현재 위치의 작은 첫 묶음
    covered = sorted(i for a, b in batches for i in range(a, b))
    assert covered == list(range(50))                               # 빠짐·중복 없음
    assert plan_batches(events, 0, 20)[:2] == [(0, 6), (6, 26)]


class FakeBackend:
    def __init__(self, fail_sizes=()):
        self.calls, self.fail_sizes, self.stopped = [], set(fail_sizes), False

    def start(self, cancelled):
        pass

    def translate(self, lines, context, target, source="en"):
        self.calls.append(len(lines))
        if len(lines) in self.fail_sizes:
            return None
        return [f"{target}:{l}" for l in lines]

    def stop(self):
        self.stopped = True


def run_job(job):
    done = {}
    job.on_done = lambda events, error: done.update(events=events, error=error)
    job.start()
    job.thread.join(5)
    return done


def test_job_translates_all_lines_in_order():
    backend = FakeBackend()
    got = []
    done = run_job(TranslationJob(ev(45), "ko", backend, position_ms=30_000, on_segments=got.extend, resegment=False))
    assert done["error"] is None and backend.stopped
    assert [t for _s, _e, t in done["events"]] == [f"ko:line {i}" for i in range(45)]
    assert got[0][2] == "ko:line 30"                                   # 30초에 표시 중인 대사(30.0~30.9초)부터


def test_job_splits_batch_when_count_mismatch():
    backend = FakeBackend(fail_sizes={14, 7})                          # 14줄·7줄 묶음은 실패 → 3·4줄로 나눠 성공
    done = run_job(TranslationJob(ev(20), "ko", backend, resegment=False))   # 묶음: 6줄, 14줄
    assert len(done["events"]) == 20 and set(backend.calls) == {6, 14, 7, 3, 4}


def test_job_keeps_original_when_single_line_fails():
    backend = FakeBackend(fail_sizes={2, 1})
    done = run_job(TranslationJob(ev(2), "ko", backend, resegment=False))
    assert [t for _s, _e, t in done["events"]] == ["line 0", "line 1"]


def test_job_cancel():
    class Slow(FakeBackend):
        def translate(self, lines, context, target, source="en"):
            time.sleep(0.2)
            return super().translate(lines, context, target, source)
    job = TranslationJob(ev(200), "ko", Slow(), resegment=False)
    done = {}
    job.on_done = lambda events, error: done.update(events=events, error=error)
    job.start()
    time.sleep(0.05)
    job.cancel()
    job.thread.join(5)
    assert done["error"] == "취소됨" and len(done["events"]) < 200


def test_claude_backend_request_shape_and_refusal():
    sent = {}

    class Messages:
        def create(self, **kwargs):
            sent.update(kwargs)
            text = '{"translations": ["안녕", "잘 가"]}'
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])

    client = SimpleNamespace(beta=SimpleNamespace(messages=Messages()))
    backend = ClaudeBackend(client=client)
    backend.start(lambda: False)
    assert backend.translate(["hi", "bye"], ["context"], "ko") == ["안녕", "잘 가"]
    assert sent["model"] == "claude-opus-5" and sent["fallbacks"] == "default"
    assert sent["betas"] == ["server-side-fallback-2026-07-01"]
    schema = sent["output_config"]["format"]["schema"]["properties"]["translations"]
    assert schema["minItems"] == schema["maxItems"] == 2

    Messages.create = lambda self, **kw: SimpleNamespace(stop_reason="refusal", content=[])
    assert backend.translate(["x"], [], "ko") is None


def test_local_available_requires_library_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(translate, "NLLB_HOME", str(tmp_path))
    assert translate.local_available() is False
    (tmp_path / "pylib" / "ctranslate2").mkdir(parents=True)
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "model.bin").write_bytes(b"")
    assert translate.local_available() is False                    # 토크나이저 모델 없음
    (tmp_path / "model" / "sentencepiece.bpe.model").write_bytes(b"")
    assert translate.local_available() is True


def test_job_resegments_and_passes_source_language():
    seen = {}

    class Rec(FakeBackend):
        def translate(self, lines, context, target, source="en"):
            seen.setdefault("source", source)
            seen.setdefault("lines", []).extend(lines)
            return super().translate(lines, context, target, source)
    events = [(0, 4000, "from a long rest. So let's begin in a seated"), (4000, 6000, "position.")]
    done = run_job(TranslationJob(events, "ko", Rec(), source="ja"))
    assert seen["source"] == "ja"
    assert seen["lines"] == ["from a long rest.", "So let's begin in a seated position."]
    assert len(done["events"]) == 2



def test_resegment_sentences_splits_mid_line():
    from jetson_player.ai.translate import resegment_sentences
    events = [
        (0, 4000, "from a long rest. So let's begin in a seated"),   # 문장이 줄 중간에서 끝남
        (4000, 6000, "position. Ready?"),
        (9000, 10000, "After a pause"),                               # 1.5초 넘게 비면 끊기
    ]
    out = resegment_sentences(events)
    assert [t for _s, _e, t in out] == ["from a long rest.", "So let's begin in a seated position.", "Ready?", "After a pause"]
    assert out[0][0] == 0 and 0 < out[0][1] < 4000                   # 줄 중간 시각으로 배분
    assert out[1][0] < 4000 < out[1][1]                               # 두 줄에 걸친 문장
    assert out[3][0] == 9000


def test_resegment_sentences_limits_length_and_keeps_words():
    from jetson_player.ai.translate import resegment_sentences
    events = [(i * 1000, i * 1000 + 1000, "word " * 5) for i in range(20)]
    out = resegment_sentences(events, max_chars=60)
    assert all(len(t) <= 60 for _s, _e, t in out)
    assert sum(len(t.split()) for _s, _e, t in out) == 100


def test_job_saves_srt_in_worker(tmp_path):
    from jetson_player.subtitles.parse import parse_srt_or_vtt_to_events
    out = tmp_path / "movie.ai.ko.srt"
    done = run_job(TranslationJob(ev(3), "ko", FakeBackend(), resegment=False, save_path=str(out)))
    assert done["error"] is None
    assert [t for _s, _e, t in parse_srt_or_vtt_to_events(out.read_text(encoding="utf-8"))] == ["ko:line 0", "ko:line 1", "ko:line 2"]


def test_job_does_not_save_when_cancelled(tmp_path):
    out = tmp_path / "x.srt"
    job = TranslationJob(ev(3), "ko", FakeBackend(), resegment=False, save_path=str(out))
    job.cancel()
    run_job(job)
    assert not out.exists()
