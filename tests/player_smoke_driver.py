"""플레이어 창을 실제로 띄워 시나리오를 돌리고 결과를 JSON 한 줄로 출력합니다.

test_player_smoke.py가 격리된 HOME·가상 디스플레이에서 하위 프로세스로 실행합니다.
사용법: python3 player_smoke_driver.py <영상 폴더>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# jetson_player를 먼저 불러와 gi 라이브러리 버전(Gtk 3.0 등)을 고정합니다.
from jetson_player.ui.window import JetsonSignageFlexiblePlayer  # noqa: E402
from gi.repository import GLib, Gst, Gtk  # noqa: E402

TIMEOUT_SEC = 40


def main(folder):
    Gst.init(None)
    Gtk.init(None)
    win = JetsonSignageFlexiblePlayer(folder)
    win.show_all()
    result = {"steps": []}
    steps = []

    def playing_file():
        if not win.pipeline:
            return None
        _, state, _ = win.pipeline.get_state(0)
        if state != Gst.State.PLAYING:
            return None
        return os.path.basename(win.playlist[win.current_index])

    def subtitle_texts():
        return sorted(ev[2] for sub in win.available_subtitles for ev in sub["events"])

    def position_ns():
        ok, pos = win.pipeline.query_position(Gst.Format.TIME) if win.pipeline else (False, 0)
        return pos if ok else -1

    # 각 단계: (이름, 준비 조건, 실행) — 조건이 참이 될 때까지 기다렸다가 실행합니다.
    def record_first():
        result["first"] = {"file": playing_file(), "subs": subtitle_texts()}
        win.play_next_video()

    def record_second():
        result["second"] = {"file": playing_file(), "subs": subtitle_texts()}
        win.set_playback_rate(2.0)

    def seek_after_rate():
        win.seek_direct(int(0.3 * Gst.SECOND))

    def mark_position():
        started["measure_at"] = (GLib.get_monotonic_time(), position_ns())

    def record_rate():
        t0, p0 = started["measure_at"]
        wall_ns = (GLib.get_monotonic_time() - t0) * 1000
        result["measured_rate"] = round((position_ns() - p0) / wall_ns, 2)
        result["ui_rate"] = win.playback_rate

    started = {}
    steps += [
        ("first", lambda: playing_file() == "a.mkv" and win.available_subtitles, record_first),
        ("second", lambda: playing_file() == "b.mkv" and win.available_subtitles, record_second),
        ("rate", lambda: playing_file() == "b.mkv", seek_after_rate),
        ("seeked", lambda: playing_file() and 0.3 * Gst.SECOND <= position_ns() < 0.8 * Gst.SECOND, mark_position),
        ("measure", lambda: GLib.get_monotonic_time() - started["measure_at"][0] > 600_000, record_rate),
    ]

    def tick():
        if not steps:
            finish()
            return False
        name, ready, action = steps[0]
        started.setdefault(name, GLib.get_monotonic_time())
        if ready():
            steps.pop(0)
            result["steps"].append(name)
            action()
        elif GLib.get_monotonic_time() - started[name] > TIMEOUT_SEC * 1_000_000:
            result["timeout"] = name
            finish()
            return False
        return True

    def finish():
        win.on_destroy(win)   # 설정·기록 저장 후 Gtk.main_quit()

    GLib.timeout_add(100, tick)
    Gtk.main()
    print("RESULT " + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
