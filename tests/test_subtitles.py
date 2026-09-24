import os


def test_srt_time_to_ms(jp):
    assert jp.srt_time_to_ms("00:01:23,456") == 83456
    assert jp.srt_time_to_ms("01:00:00.5") == 3600500
    assert jp.srt_time_to_ms("02:03.100") == 123100
    assert jp.srt_time_to_ms("garbage") == 0


def test_ms_to_srt_time_roundtrip(jp):
    for ms in (0, 999, 83456, 3723004):
        assert jp.srt_time_to_ms(jp.ms_to_srt_time(ms)) == ms


def test_parse_srt(jp):
    content = "1\n00:00:01,000 --> 00:00:02,500\n<i>Hello</i>\nWorld\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n"
    assert jp.parse_srt_or_vtt_to_events(content) == [
        (1000, 2500, "Hello\nWorld"),
        (3000, 4000, "Bye"),
    ]


def test_parse_vtt(jp):
    content = "WEBVTT\n\n00:01.000 --> 00:02.000\nHi\n"
    assert jp.parse_srt_or_vtt_to_events(content) == [(1000, 2000, "Hi")]


def test_parse_smi(jp):
    content = (
        "<SAMI><BODY>"
        "<SYNC Start=1000><P>안녕<br>하세요</P>"
        "<SYNC Start=3000><P>&nbsp;</P>"
        "<SYNC Start=5000><P>끝</P>"
        "</BODY></SAMI>"
    )
    events = jp.parse_smi_to_events(content)
    assert events[0] == (1000, 3000, "안녕\n하세요")
    assert events[-1][0] == 5000 and events[-1][2] == "끝"


def test_parse_ass(jp):
    content = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\b1}Hello\\NWorld, again\n"
    )
    assert jp.parse_ass_to_events(content) == [(1000, 2500, "Hello\nWorld, again")]


def test_subtitle_label_and_color(jp):
    assert "한국어" in jp.get_subtitle_label("/x/movie.ko.srt")
    assert "영어" in jp.get_subtitle_label("/x/movie.en.srt")
    assert jp.get_subtitle_color("/x/movie.ko.srt") == jp.LANGUAGE_COLORS["ko"]
    assert jp.get_subtitle_color("/x/movie.srt", 1) == jp.FALLBACK_PALETTE[1]



def test_find_all_matching_subtitles(jp, tmp_path):
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"")
    for name in ("Movie.en.srt", "Movie.ko.srt", "Other.srt", "Movie.smi"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    found = [os.path.basename(p) for p in jp.find_all_matching_subtitles(str(video))]
    assert "Other.srt" not in found
    assert found[0] == "Movie.ko.srt"
    assert set(found) == {"Movie.en.srt", "Movie.ko.srt", "Movie.smi"}


def test_scan_video_files(jp, tmp_path):
    (tmp_path / "b.mp4").write_bytes(b"")
    (tmp_path / "A.MKV").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x")
    (tmp_path / ".hidden.mp4").write_bytes(b"")
    sub = tmp_path / "season1"
    sub.mkdir()
    (sub / "ep1.webm").write_bytes(b"")
    backup = tmp_path / "unsupported_originals"
    backup.mkdir()
    (backup / "old.avi").write_bytes(b"")
    found = [os.path.relpath(p, tmp_path) for p in jp.scan_video_files(str(tmp_path))]
    assert found == ["A.MKV", "b.mp4", os.path.join("season1", "ep1.webm")]


def test_scan_video_files_empty(jp, tmp_path):
    assert jp.scan_video_files(str(tmp_path)) == []


def test_atomic_write_json(jp, tmp_path):
    import json
    target = tmp_path / "sub" / "data.json"
    jp.atomic_write_json(str(target), {"한글": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"한글": 1}
    assert not (tmp_path / "sub" / "data.json.tmp").exists()
