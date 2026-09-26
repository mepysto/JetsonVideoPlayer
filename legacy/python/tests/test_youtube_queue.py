import threading
import time

import pytest

from jetson_player import youtube


class FakeGLib:
    @staticmethod
    def idle_add(fn, *args):
        fn(*args)


class FakeYDL:
    """extract_info가 테스트에서 release 될 때까지 진행률 훅을 반복 호출하며 기다리는 가짜 yt-dlp"""
    gates = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        gate = FakeYDL.gates.setdefault(url, threading.Event())
        while not gate.wait(0.01):
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "total_bytes": 100, "downloaded_bytes": 50,
                      "speed": 2048, "eta": 5, "info_dict": {"title": url}})
        vid = url[-11:]
        return {"title": f"title-{vid}", "id": vid, "ext": "mp4"}

    def prepare_filename(self, info):
        return f"/tmp/{info['title']} [{info['id']}].mp4"


@pytest.fixture
def mgr(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube, "GLib", FakeGLib)
    monkeypatch.setattr(youtube, "HAS_YT_DLP", True)
    monkeypatch.setattr(youtube, "yt_dlp", type("M", (), {"YoutubeDL": FakeYDL}), raising=False)
    FakeYDL.gates = {}
    return youtube.YouTubeManager(download_dir=str(tmp_path))


def wait_until(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


URL_A = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
URL_B = "https://www.youtube.com/watch?v=BBBBBBBBBBB"


def test_queue_cancel_and_advance(mgr):
    events = []
    cb = dict(on_finish=lambda p, t: events.append(("finish", t)), on_error=lambda e: events.append(("error", e)))
    assert mgr.download_async(URL_A, **cb) == ("started", 0)
    assert mgr.download_async(URL_A, **cb) == ("downloading", 0)
    assert mgr.download_async(URL_B, **cb) == ("queued", 1)
    assert mgr.download_async(URL_B, **cb) == ("queued", 1)          # 중복 추가 안 함
    assert [q["url"] for q in mgr.get_status()["queue"]] == [URL_B]

    assert mgr.cancel_current() is True
    assert wait_until(lambda: ("error", youtube.YouTubeManager.CANCELLED_MESSAGE) in events)
    # 취소 후 대기열의 다음 작업이 자동 시작
    assert wait_until(lambda: mgr.get_status()["url"] == URL_B and mgr.get_status()["active"])
    FakeYDL.gates.setdefault(URL_B, threading.Event()).set()
    assert wait_until(lambda: ("finish", "title-BBBBBBBBBBB") in events)
    assert wait_until(lambda: not mgr.get_status()["active"])
    assert mgr.get_status()["queue"] == []


def test_cancel_pending(mgr):
    mgr.download_async(URL_A)
    mgr.download_async(URL_B)
    assert mgr.cancel_pending(URL_B) is True
    assert mgr.get_status()["queue"] == []
    mgr.cancel_current()
    assert wait_until(lambda: not mgr.get_status()["active"])


def test_cached_file_short_circuits(mgr, tmp_path):
    cached = tmp_path / "Old Video [AAAAAAAAAAA].mp4"
    cached.write_bytes(b"x" * (600 * 1024))
    done = []
    assert mgr.download_async(URL_A, on_finish=lambda p, t: done.append((p, t)))[0] == "cached"
    assert done == [(str(cached), "Old Video")]


def test_format_for_quality():
    assert "height<=720" in youtube.youtube_format_for_quality("720p")
    assert youtube.youtube_format_for_quality("audio").startswith("bestaudio")
    best = youtube.youtube_format_for_quality("best")
    assert best.startswith("bestvideo[vcodec^=avc1]") and "av01" in best
