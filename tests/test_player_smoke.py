"""플레이어 창 전체를 띄우는 스모크 테스트 (가상 디스플레이 Xvfb, 격리된 HOME)

과거 회귀: 다음 영상으로 넘어가도 이전 영상의 자막이 남음(552c974), 탐색 후 배속이 1.0으로 초기화됨.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player_smoke_driver.py")


@pytest.fixture
def smoke_result(media_dir, tmp_path):
    if not shutil.which("xvfb-run"):
        pytest.skip("xvfb-run 없음")
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               JVP_VIDEO_SINK="gtk", JVP_LOG_LEVEL="INFO")
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"):
        env.pop(key, None)
    folder = tmp_path / "media"   # 시나리오가 파일을 추가·삭제하므로 복사본에서 실행
    shutil.copytree(media_dir, folder)
    proc = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", sys.executable, DRIVER, str(folder)],
                          env=env, capture_output=True, text=True, timeout=120)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, f"드라이버 실패 (exit {proc.returncode}):\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    return json.loads(line[len("RESULT "):])


def test_player_plays_folder_and_switches_subtitles(smoke_result):
    r = smoke_result
    assert "timeout" not in r, r
    assert r["first"] == {"file": "a.mkv", "subs": ["AAA line"]}
    assert r["second"] == {"file": "b.mkv", "subs": ["BBB line"]}
    assert 1.5 <= r["measured_rate"] <= 2.5   # 탐색 후에도 2배속 유지
    assert r["ui_rate"] == pytest.approx(2.0)
    assert r["search_rows"] == [["a.mkv", 0]]
    assert r["after_search"] == {"file": "a.mkv", "subs": ["AAA line"]}
    # 폴더 감시: 재생을 멈추지 않고 재생목록 갱신
    assert r["after_add"] == {"playlist": ["a.mkv", "b.mkv", "c.mkv"], "file": "a.mkv"}
    assert r["after_remove"] == {"playlist": ["a.mkv", "c.mkv"], "file": "a.mkv"}
