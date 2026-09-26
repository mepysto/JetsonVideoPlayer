import os
import time

from jetson_player.subtitles.search import DialogueIndex, normalize


def srt(path, *lines):
    blocks = []
    for n, (start_s, text) in enumerate(lines, 1):
        blocks.append(f"{n}\n00:00:{start_s:02d},000 --> 00:00:{start_s + 1:02d},000\n{text}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")


def make_library(tmp_path):
    for name in ("a.mkv", "b.mkv"):
        (tmp_path / name).write_bytes(b"x")
    srt(tmp_path / "a.ko.srt", (1, "안녕하세요 여러분"), (5, "오늘은\n날씨가 좋네요"))
    srt(tmp_path / "b.en.srt", (2, "Hello  World"), (9, "Good WEATHER today"))
    return [str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv")]


def test_normalize_ignores_case_and_whitespace():
    assert normalize("  Hello\n  World ") == "hello world"


def test_search_across_playlist(tmp_path):
    videos = make_library(tmp_path)
    index = DialogueIndex()
    assert index.build(videos)
    hits = index.search("날씨가 좋")
    assert [(os.path.basename(h.video), h.start_ms) for h in hits] == [("a.mkv", 5000)]
    assert "오늘은" in hits[0].text and "한국어" in hits[0].label
    assert [h.start_ms for h in index.search("hello world")] == [2000]
    assert index.search("   ") == []


def test_current_video_results_come_first(tmp_path):
    videos = make_library(tmp_path)
    srt(tmp_path / "a.ko.srt", (1, "weather report"))
    index = DialogueIndex()
    index.build(videos)
    assert [os.path.basename(h.video) for h in index.search("weather")] == ["a.mkv", "b.mkv"]
    assert [os.path.basename(h.video) for h in index.search("weather", first_video=videos[1])] == ["b.mkv", "a.mkv"]


def test_rebuild_rereads_only_changed_subtitles(tmp_path):
    videos = make_library(tmp_path)
    parsed = []
    from jetson_player.subtitles.parse import parse_subtitle_file_events

    def counting_parse(path):
        parsed.append(os.path.basename(path))
        return parse_subtitle_file_events(path)

    index = DialogueIndex(parse=counting_parse)
    index.build(videos)
    assert sorted(parsed) == ["a.ko.srt", "b.en.srt"]
    parsed.clear()
    index.build(videos)
    assert parsed == []
    time.sleep(0.01)
    srt(tmp_path / "b.ai.ko.srt", (3, "새 AI 대사"))
    index.build(videos)
    assert sorted(parsed) == ["b.ai.ko.srt", "b.en.srt"]
    assert [h.start_ms for h in index.search("새 ai")] == [3000]


def test_limit(tmp_path):
    (tmp_path / "a.mkv").write_bytes(b"x")
    srt(tmp_path / "a.srt", *[(i, "la") for i in range(10)])
    index = DialogueIndex()
    index.build([str(tmp_path / "a.mkv")])
    assert len(index.search("la", limit=3)) == 3
