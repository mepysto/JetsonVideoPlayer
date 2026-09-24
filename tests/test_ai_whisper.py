import os

from jetson_player.ai.whisper import ai_subtitle_path, format_srt, parse_whisper_line, plan_passes
from jetson_player.subtitles.parse import parse_srt_or_vtt_to_events


def test_parse_whisper_line():
    assert parse_whisper_line("[00:00:01.000 --> 00:00:04.500]   Hello there") == (1000, 4500, "Hello there")
    assert parse_whisper_line("[01:02:03.25 --> 01:02:04.000]  안녕") == (3723250, 3724000, "안녕")
    assert parse_whisper_line("[00:00:01.000 --> 00:00:02.000]   [BLANK_AUDIO]") is None
    assert parse_whisper_line("[00:00:01.000 --> 00:00:02.000]   [Music]") is None
    assert parse_whisper_line("whisper_init_from_file: loading model") is None


def test_plan_passes_starts_at_current_position():
    minute = 60_000
    passes = plan_passes(20 * minute, 10 * minute)
    assert passes[0] == (10 * minute, minute)                 # 현재 위치의 짧은 첫 구간
    covered = sorted(passes)
    pos = 0
    for offset, length in covered:                            # 빈틈/중복 없이 전체를 덮음
        assert offset == pos
        pos += length
    assert pos == 20 * minute
    assert plan_passes(10 * minute, 10_000)[0][0] == 0         # 30초 이내면 처음부터


def test_format_srt_roundtrip():
    events = [(3000, 4000, "둘"), (0, 1500, "하나")]
    parsed = parse_srt_or_vtt_to_events(format_srt(events))
    assert parsed == [(0, 1500, "하나"), (3000, 4000, "둘")]


def test_ai_subtitle_path(tmp_path):
    video = tmp_path / "movie.mkv"
    video.write_bytes(b"")
    assert ai_subtitle_path(str(video), "ko") == os.path.join(str(tmp_path), "movie.ai.ko.srt")
    assert ai_subtitle_path(str(video), "ko", translate=True).endswith("movie.ai.en.srt")
