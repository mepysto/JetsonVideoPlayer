"""C++ 앱 전체를 실제로 띄워 웹 리모컨 HTTP API로 조작하고 결과를 확인하는 종단 간(e2e) 테스트.

실행: pytest app/tests/e2e -v   (JVP_BIN으로 실행 파일 지정, 기본 app/build/src/jetson-player)
화면(DISPLAY)이 필요합니다. 없으면 건너뜁니다. 사용자 설정을 건드리지 않도록 HOME을 임시 폴더로 바꿉니다.
"""
import http.client
import json
import os
import re
import shutil
import shlex
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BIN = Path(os.environ.get("JVP_BIN", ROOT / "app" / "build" / "src" / "jetson-player"))
PIN = "4242"

pytestmark = [
    pytest.mark.skipif(not BIN.exists(), reason=f"실행 파일 없음: {BIN}"),
    pytest.mark.skipif(not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"), reason="화면 없음"),
    pytest.mark.skipif(shutil.which("gst-launch-1.0") is None, reason="gst-launch-1.0 없음"),
]


# ---- 테스트 자료 ---------------------------------------------------------------------

def make_clip(path, seconds=8, pattern="smpte"):
    """x264 + AAC mp4 (소프트웨어 인코더라 어느 기기에서나 만들 수 있음)"""
    frames = seconds * 25
    cmd = (f"-q -e videotestsrc pattern={pattern} num-buffers={frames} ! "
           f"video/x-raw,width=320,height=240,framerate=25/1 ! x264enc speed-preset=ultrafast ! h264parse ! "
           f"mp4mux name=m ! filesink location={shlex.quote(str(path))} "
           f"audiotestsrc num-buffers={seconds * 44100 // 1024} wave=sine ! audioconvert ! avenc_aac ! m.")
    # 셸을 거치지 않고 인자 목록으로 실행 (경로의 특수 문자가 명령으로 해석되지 않게)
    subprocess.run(["gst-launch-1.0", *shlex.split(cmd)], check=True, timeout=120)


SRT_EP1 = """1
00:00:01,000 --> 00:00:03,000
안녕하세요 첫 번째 영상입니다

2
00:00:04,000 --> 00:00:06,000
The weather is lovely today
"""


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    make_clip(d / "ep1.mp4", 8, "smpte")
    make_clip(d / "ep2.mp4", 8, "ball")
    (d / "ep1.ko.srt").write_text(SRT_EP1, encoding="utf-8")
    return d


# ---- 앱 실행 / HTTP --------------------------------------------------------------------

class Player:
    def __init__(self, home, target, extra=()):
        self.home = Path(home)
        cfg = self.home / ".config" / "jetson_video_player"
        cfg.mkdir(parents=True, exist_ok=True)
        settings = cfg / "settings.json"
        data = json.loads(settings.read_text()) if settings.exists() else {}
        data.update(remote_pin=PIN, autoplay_countdown=False, loudness_normalize=False)
        settings.write_text(json.dumps(data))
        env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                   QT_LOGGING_RULES="jvp.*.info=true")
        self.log = open(self.home / "player.out", "w")
        self.proc = subprocess.Popen([str(BIN), str(target), *extra], env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.port = self._wait_port()
        self.cookie = self._login()

    def _wait_port(self, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = (self.home / "player.out").read_text(errors="replace")
            m = re.search(r"스마트폰 접속 주소: http://[\d.]+:(\d+)", text)
            if m:
                return int(m.group(1))
            if self.proc.poll() is not None:
                raise RuntimeError(f"앱이 종료됨 (코드 {self.proc.returncode}):\n{text}")
            time.sleep(0.2)
        raise TimeoutError("웹 리모컨 주소가 로그에 나오지 않았습니다")

    def request(self, method, path, body=None, cookie=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if cookie and getattr(self, "cookie", None):
            headers["Cookie"] = self.cookie
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def _login(self):
        r, _ = self.request("POST", "/api/login", {"pin": PIN}, cookie=False)
        assert r.status == 200
        return r.getheader("Set-Cookie").split(";")[0]

    def status(self):
        r, body = self.request("GET", "/api/status")
        assert r.status == 200
        return json.loads(body)

    def cmd(self, action, **kw):
        r, _ = self.request("POST", "/api/cmd", dict(action=action, **kw))
        assert r.status == 200, r.status

    def wait(self, pred, timeout=10, what="조건"):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.status()
            if pred(last):
                return last
            time.sleep(0.2)
        raise AssertionError(f"{what} 시간 초과. 마지막 상태: {json.dumps(last, ensure_ascii=False)[:800]}")

    def quit(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.log.close()
        return self.proc.returncode

    def output(self):
        return (self.home / "player.out").read_text(errors="replace")


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def player(home, media):
    p = Player(home, media)
    yield p
    p.quit()


# ---- 시나리오 ---------------------------------------------------------------------------

def test_starts_playing_folder_with_subtitle(player):
    s = player.wait(lambda s: s["is_playing"] and s["duration_sec"] > 0, what="재생 시작")
    assert s["title"] == "ep1.mp4"
    assert s["total_videos"] == 2 and s["current_index"] == 0
    assert 7 <= s["duration_sec"] <= 9
    assert [t["label"] for t in s["subtitle_tracks"]] and s["subtitle_tracks"][0]["active"]
    p0 = s["position_sec"]
    player.wait(lambda s: s["position_sec"] > p0 + 0.8, what="위치 진행")


def test_pause_seek_speed_volume(player):
    player.wait(lambda s: s["is_playing"] and s["duration_sec"] > 0, what="재생 시작")
    player.cmd("play_pause")
    player.wait(lambda s: not s["is_playing"], what="일시정지")
    player.cmd("seek_abs", sec=5)
    player.wait(lambda s: abs(s["position_sec"] - 5) < 0.6, what="탐색")
    player.cmd("play_pause")
    player.cmd("speed", val=1.5)
    player.cmd("volume", val=150)
    s = player.wait(lambda s: s["speed"] == 1.5 and s["volume"] == 150 and s["is_playing"], what="속도·볼륨")
    player.cmd("mute")
    player.wait(lambda s: s["is_muted"], what="음소거")
    player.cmd("speed_reset")
    player.wait(lambda s: s["speed"] == 1.0, what="속도 초기화")


def test_next_prev_and_play_index(player):
    player.wait(lambda s: s["duration_sec"] > 0, what="재생 시작")
    player.cmd("next")
    player.wait(lambda s: s["current_index"] == 1 and s["title"] == "ep2.mp4" and s["is_playing"], what="다음 영상")
    player.cmd("prev")
    player.wait(lambda s: s["current_index"] == 0, what="이전 영상")
    player.cmd("play_index", index=1)
    player.wait(lambda s: s["current_index"] == 1, what="목록에서 선택")


def test_end_of_video_advances_to_next(player):
    player.wait(lambda s: s["duration_sec"] > 0, what="재생 시작")
    player.cmd("seek_abs", sec=7)
    player.wait(lambda s: s["current_index"] == 1 and s["is_playing"], timeout=15, what="끝나면 다음 영상")


def test_subtitle_bookmark_ab_and_marks(player):
    player.wait(lambda s: s["duration_sec"] > 0, what="재생 시작")
    player.cmd("sub_toggle_track", index=0)
    player.wait(lambda s: not s["subtitle_tracks"][0]["active"], what="자막 끄기")
    player.cmd("sub_sync", delta=500)
    player.wait(lambda s: s["subtitle_offset_ms"] == 500, what="자막 싱크")
    player.cmd("bookmark_add")
    player.wait(lambda s: len(s["bookmarks"]) == 1, what="북마크")
    player.cmd("seek_abs", sec=1)
    time.sleep(0.5)
    player.cmd("ab_a")
    player.cmd("seek_abs", sec=3)
    time.sleep(0.5)
    player.cmd("ab_b")
    s = player.wait(lambda s: s["ab"]["active"], what="A-B 반복")
    assert s["ab"]["a"] < s["ab"]["b"]
    # 구간 안에서 반복: B를 지나도 A로 돌아와야 함
    time.sleep(3)
    assert player.status()["position_sec"] < 3.6
    player.cmd("ab_clear")
    player.wait(lambda s: not s["ab"]["active"], what="A-B 해제")


def test_viewing_settings(player):
    player.wait(lambda s: s["duration_sec"] > 0, what="재생 시작")
    player.cmd("night")
    player.cmd("rotate")
    player.cmd("eq", val="dialogue")
    player.cmd("sleep", minutes=15)
    s = player.wait(lambda s: s["night_mode"] and s["rotation"] == "90r" and s["eq_preset"] == "dialogue"
                    and s["sleep"]["minutes"] == 15, what="시청 설정")
    assert 14 * 60 < s["sleep"]["remaining"] <= 15 * 60
    player.cmd("repeat")
    player.wait(lambda s: s["repeat_mode"] == "one", what="반복 모드")


def test_dialogue_search_and_play_at(player):
    player.wait(lambda s: s["duration_sec"] > 0, what="재생 시작")
    deadline = time.time() + 10
    while True:
        r, body = player.request("GET", "/api/search?q=weather")
        data = json.loads(body)
        if data["results"] or time.time() > deadline:
            break
        time.sleep(0.3)
    assert data["results"], data
    hit = data["results"][0]
    assert hit["name"] == "ep1.mp4" and abs(hit["sec"] - 4.0) < 0.01
    player.cmd("next")
    player.wait(lambda s: s["current_index"] == 1, what="다른 영상으로")
    player.cmd("play_at", index=hit["index"], sec=hit["sec"])
    player.wait(lambda s: s["current_index"] == 0 and 3.0 <= s["position_sec"] <= 5.0, what="대사 위치로 이동")


def test_playlist_groups_and_sse(player):
    player.wait(lambda s: s["duration_sec"] > 0, what="재생 시작")
    s = player.status()
    items = [it for g in s["playlist_groups"] for it in g["items"]]
    assert [it["name"] for it in items] == ["ep1.mp4", "ep2.mp4"] and items[0]["active"]
    c = http.client.HTTPConnection("127.0.0.1", player.port, timeout=10)
    c.request("GET", "/api/events", headers={"Cookie": player.cookie})
    r = c.getresponse()
    assert r.status == 200 and r.getheader("Content-Type").startswith("text/event-stream")
    got = b""
    deadline = time.time() + 5
    while b"event: playlist" not in got and time.time() < deadline:
        got += r.fp.read1(4096)
    c.close()
    assert b"event: status" in got and b"event: playlist" in got


def test_resume_position_after_restart(home, media):
    p = Player(home, media / "ep1.mp4")
    p.wait(lambda s: s["duration_sec"] > 0, what="재생 시작")
    p.cmd("seek_abs", sec=5)
    p.wait(lambda s: s["position_sec"] >= 5, what="탐색")
    p.cmd("play_pause")
    time.sleep(0.5)
    assert p.quit() == 0
    p2 = Player(home, media / "ep1.mp4")
    try:
        s = p2.wait(lambda s: s["duration_sec"] > 0 and s["position_sec"] >= 4.5, what="이어보기")
        assert s["position_sec"] < 7
        assert "이어보기" in p2.output()
    finally:
        p2.quit()


def test_bad_path_exits_with_error(home):
    env = dict(os.environ, HOME=str(home))
    r = subprocess.run([str(BIN), "/nonexistent/file.mp4"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "재생할 수 있는 영상이 없습니다" in r.stderr


def test_mpris_play_pause(player):
    if shutil.which("gdbus") is None:
        pytest.skip("gdbus 없음")
    player.wait(lambda s: s["is_playing"] and s["duration_sec"] > 0, what="재생 시작")
    r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.mpris.MediaPlayer2.jetson_player",
                        "--object-path", "/org/mpris/MediaPlayer2", "--method",
                        "org.mpris.MediaPlayer2.Player.PlayPause"], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        pytest.skip(f"MPRIS 이름을 쓸 수 없음 (다른 플레이어 실행 중?): {r.stderr.strip()}")
    player.wait(lambda s: not s["is_playing"], what="MPRIS 일시정지")


# ---- AI 자막 · 번역 (whisper.cpp / NLLB가 설치된 기기에서만) ----------------------------------

REAL_DATA = Path.home() / ".local" / "share" / "jetson_video_player"


@pytest.fixture
def ai_home(home):
    whisper = REAL_DATA / "whisper.cpp"
    sample = whisper / "samples" / "jfk.wav"
    if not sample.exists() or not list((whisper / "models").glob("ggml-*.bin")):
        pytest.skip("whisper.cpp 또는 모델 없음 (scripts/setup_whisper.sh)")
    data = home / ".local" / "share" / "jetson_video_player"
    data.mkdir(parents=True)
    for name in ("whisper.cpp", "nllb"):
        if (REAL_DATA / name).exists():
            (data / name).symlink_to(REAL_DATA / name)
    return home


def test_ai_subtitles_then_translation(ai_home, tmp_path):
    speech = tmp_path / "speech" / "jfk.mkv"
    speech.parent.mkdir()
    wav = REAL_DATA / "whisper.cpp" / "samples" / "jfk.wav"
    subprocess.run(["gst-launch-1.0", "-q", "-e", "videotestsrc", "num-buffers=275", "!",
                    "video/x-raw,width=320,height=240,framerate=25/1", "!", "x264enc", "speed-preset=ultrafast", "!",
                    "h264parse", "!", "matroskamux", "name=m", "!", "filesink", f"location={speech}",
                    "filesrc", f"location={wav}", "!", "wavparse", "!", "audioconvert", "!", "vorbisenc", "!", "m."],
                   check=True, timeout=120)
    p = Player(ai_home, speech)
    try:
        p.wait(lambda s: s["duration_sec"] > 0 and s["ai"]["available"], what="재생 시작")
        p.cmd("play_pause")   # 인식이 끝날 때까지 멈춰 두어도 됩니다
        p.cmd("ai_subtitles")
        s = p.wait(lambda s: not s["ai"]["running"] and any(t["label"].startswith("🤖 AI") and "(" in t["label"]
                                                           and "생성 중" not in t["label"] for t in s["subtitle_tracks"]),
                   timeout=120, what="AI 자막 완성")
        assert "fellow Americans" in p.output() or any("영어" in t["label"] for t in s["subtitle_tracks"])
        srt = list((speech.parent).glob("*.srt"))
        assert srt and "country" in srt[0].read_text()
        if not s["translate"]["available"]:
            pytest.skip("번역 엔진 없음")
        p.cmd("translate")
        s = p.wait(lambda s: not s["translate"]["running"] and any(t["label"].startswith("🌐") and "번역 중" not in t["label"]
                                                                  for t in s["subtitle_tracks"]),
                   timeout=180, what="번역 완성")
        ko = [f for f in speech.parent.glob("*.srt") if ".ko." in f.name]
        assert ko and any("가" <= ch <= "힣" for ch in ko[0].read_text()), "한국어 번역 파일"
    finally:
        p.quit()
