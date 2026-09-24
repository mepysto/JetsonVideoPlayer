import json

from jetson_player.settings import DEFAULTS, Settings
from jetson_player.storage import NS_PER_SECOND, ResumeCache

S = NS_PER_SECOND


def test_resume_progress_and_completion(tmp_path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"")
    rc = ResumeCache(path=str(tmp_path / "resume.json"))
    rc.set(str(video), 3 * S, 100 * S)          # 5초 미만은 저장하지 않음
    assert rc.get(str(video)) == (0, 0)
    rc.set(str(video), 40 * S, 100 * S)
    assert rc.get(str(video)) == (40 * S, 100 * S)
    ratio, watched = rc.get_progress(str(video))
    assert abs(ratio - 0.4) < 1e-9 and watched is False
    assert rc.recent_in_progress() == [(str(video), 40 * S, 100 * S)]

    rc.set(str(video), 97 * S, 100 * S)         # 95% 이후 → 시청 완료
    assert rc.get(str(video)) == (0, 100 * S)
    assert rc.get_progress(str(video)) == (None, True)
    assert rc.recent_in_progress() == []

    rc.set(str(video), 10 * S, 100 * S)         # 다시 보기 시작해도 완료 표시는 유지
    assert rc.get_progress(str(video))[1] is True

    rc.save()
    reloaded = ResumeCache(path=str(tmp_path / "resume.json"))
    assert reloaded.get(str(video)) == (10 * S, 100 * S)


def test_recent_in_progress_skips_missing_files(tmp_path):
    rc = ResumeCache(path=str(tmp_path / "resume.json"))
    rc.set(str(tmp_path / "gone.mp4"), 30 * S, 100 * S)
    assert rc.recent_in_progress() == []


def test_settings_roundtrip_and_validation(tmp_path):
    path = tmp_path / "settings.json"
    st = Settings(path=str(path))
    assert st.get("volume") == DEFAULTS["volume"]
    assert st.save() is False                    # 변경 없으면 쓰지 않음
    st.update(volume=250, repeat_mode="one", subtitle_font_scale=1.2)
    assert st.get("volume") == 200               # 범위 제한
    assert st.save() is True
    again = Settings(path=str(path))
    assert again.get("repeat_mode") == "one" and again.get("subtitle_font_scale") == 1.2


def test_settings_ignores_corrupt_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"volume": "loud", "repeat_mode": "bogus", "muted": 1, "unknown": 5}))
    st = Settings(path=str(path))
    assert st.get("volume") == DEFAULTS["volume"]
    assert st.get("repeat_mode") == DEFAULTS["repeat_mode"]
    assert st.get("muted") is DEFAULTS["muted"]


def test_settings_survives_garbage_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert Settings(path=str(path)).get("volume") == DEFAULTS["volume"]


def test_sort_video_paths(tmp_path):
    import os
    from jetson_player.library import sort_video_paths
    a, b, c = (tmp_path / n for n in ("a.mp4", "b.mp4", "c.mp4"))
    a.write_bytes(b"x" * 10); b.write_bytes(b"x" * 30); c.write_bytes(b"x" * 20)
    os.utime(a, (1000, 3000)); os.utime(b, (1000, 1000)); os.utime(c, (1000, 2000))
    paths = [str(c), str(a), str(b)]
    names = lambda ps: [os.path.basename(p) for p in ps]
    assert names(sort_video_paths(paths, "name")) == ["a.mp4", "b.mp4", "c.mp4"]
    assert names(sort_video_paths(paths, "mtime")) == ["a.mp4", "c.mp4", "b.mp4"]
    assert names(sort_video_paths(paths, "size")) == ["b.mp4", "c.mp4", "a.mp4"]
    assert names(sort_video_paths(paths + [str(tmp_path / "gone.mp4")], "size"))[-1] == "gone.mp4"
