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
    assert batches[0] == (20, 40) and sorted(batches) == [(0, 20), (20, 40), (40, 50)]
    assert plan_batches(events, 0, 20)[0] == (0, 20)


class FakeBackend:
    def __init__(self, fail_sizes=()):
        self.calls, self.fail_sizes, self.stopped = [], set(fail_sizes), False

    def start(self, cancelled):
        pass

    def translate(self, lines, context, target):
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
    done = run_job(TranslationJob(ev(45), "ko", backend, position_ms=30_000, on_segments=got.extend))
    assert done["error"] is None and backend.stopped
    assert [t for _s, _e, t in done["events"]] == [f"ko:line {i}" for i in range(45)]
    assert got[0][2] == "ko:line 20"                                   # 현재 위치 묶음부터


def test_job_splits_batch_when_count_mismatch():
    backend = FakeBackend(fail_sizes={20, 10})                         # 20줄·10줄 묶음은 실패 → 5줄로 나눠 성공
    done = run_job(TranslationJob(ev(20), "ko", backend))
    assert len(done["events"]) == 20 and set(backend.calls) == {20, 10, 5}


def test_job_keeps_original_when_single_line_fails():
    backend = FakeBackend(fail_sizes={2, 1})
    done = run_job(TranslationJob(ev(2), "ko", backend))
    assert [t for _s, _e, t in done["events"]] == ["line 0", "line 1"]


def test_job_cancel():
    class Slow(FakeBackend):
        def translate(self, lines, context, target):
            time.sleep(0.2)
            return super().translate(lines, context, target)
    job = TranslationJob(ev(200), "ko", Slow())
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
