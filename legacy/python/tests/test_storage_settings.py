import json
import os

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


def test_bookmarks(tmp_path):
    from jetson_player.storage import BookmarkCache
    path = str(tmp_path / "bm.json")
    bc = BookmarkCache(path=path)
    assert bc.add("/v.mp4", 65 * S) == (True, "01:05")
    assert bc.add("/v.mp4", int(65.5 * S))[0] is False          # 1초 이내 중복
    assert bc.add("/v.mp4", 3725 * S) == (True, "01:02:05")
    assert bc.add("/v.mp4", 10 * S, label="intro") == (True, "intro")
    assert [b["label"] for b in bc.get("/v.mp4")] == ["intro", "01:05", "01:02:05"]   # 시간순
    assert bc.remove("/v.mp4", 0) and not bc.remove("/v.mp4", 9)
    assert bc.add("", 0)[0] is False
    bc.save()
    assert [b["label"] for b in BookmarkCache(path=path).get("/v.mp4")] == ["01:05", "01:02:05"]


def test_history_order_dedupe_limit(tmp_path):
    from jetson_player.storage import HISTORY_LIMIT, HistoryCache
    hc = HistoryCache(path=str(tmp_path / "h.json"))
    files = []
    for i in range(HISTORY_LIMIT + 3):
        f = tmp_path / f"v{i}.mp4"
        f.write_bytes(b"")
        files.append(str(f))
        hc.add(str(f))
    hc.add(files[5])                                          # 다시 보면 맨 앞으로
    items = hc.get_all()
    assert len(items) == HISTORY_LIMIT and items[0]["path"] == files[5]
    assert len({i["path"] for i in items}) == HISTORY_LIMIT
    hc.add(str(tmp_path / "missing.mp4"))                     # 없는 파일은 무시
    assert hc.get_all()[0]["path"] == files[5]


def test_hw_cache_invalidates_on_change_and_version(tmp_path):
    import json
    from jetson_player.storage import HWSupportCache
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    path = str(tmp_path / "hw.json")
    hc = HWSupportCache(path=path)
    hc.set(str(video), True, "ok")
    assert hc.get(str(video)) == (True, "ok")
    video.write_bytes(b"xx")                                  # 파일이 바뀌면 다시 검사
    assert hc.get(str(video)) is None
    hc.set(str(video), False, "no")
    hc.save()
    data = json.load(open(path))
    data[str(video)]["v"] = 1                                 # 이전 버전 판정은 무시
    json.dump(data, open(path, "w"))
    assert HWSupportCache(path=path).get(str(video)) is None


def test_stores_survive_wrong_json_types(tmp_path):
    from jetson_player.storage import BookmarkCache, HistoryCache
    (tmp_path / "bm.json").write_text("[1, 2]")
    (tmp_path / "h.json").write_text('{"a": 1}')
    assert BookmarkCache(path=str(tmp_path / "bm.json")).get("/x") == []
    assert HistoryCache(path=str(tmp_path / "h.json")).get_all() == []


def test_prefer_h265_versions(tmp_path):
    from jetson_player.library import prefer_h265_versions
    for n in ("a.mkv", "a_h265.mp4", "b.mkv"):
        (tmp_path / n).write_bytes(b"x")
    paths = [str(tmp_path / n) for n in ("a.mkv", "a_h265.mp4", "b.mkv", "gone.mkv")]
    assert [os.path.basename(p) for p in prefer_h265_versions(paths)] == ["a_h265.mp4", "b.mkv"]


def test_merge_rescanned_keeps_outside_items_and_current():
    from jetson_player.library import merge_rescanned
    playlist = ["/v/a.mkv", "/v/b.mkv", "/yt/clip.mp4", "/v/sub/c.mkv"]
    new, added, removed = merge_rescanned(playlist, "/v", ["/v/a.mkv", "/v/sub/c.mkv", "/v/d.mkv"], current="/v/b.mkv")
    assert set(new) == {"/v/a.mkv", "/v/sub/c.mkv", "/v/d.mkv", "/yt/clip.mp4", "/v/b.mkv"}   # b는 재생 중이라 유지
    assert added == ["/v/d.mkv"] and removed == []
    new, added, removed = merge_rescanned(playlist, "/v", ["/v/a.mkv"], current="/v/a.mkv")
    assert removed == ["/v/b.mkv", "/v/sub/c.mkv"] and "/yt/clip.mp4" in new
    assert merge_rescanned(["/vv/x.mkv"], "/v", [])[0] == ["/vv/x.mkv"]   # /vv는 /v 폴더 밖
