import pytest

from jetson_player.subtitles.ass import (anchor_point, ass_time_to_ms, events_as_plain, legacy_alignment,
                                         parse_ass, parse_color)

SCRIPT = r"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,40,40,50,1
Style: Sign,Arial,48,&H0000FFFF,&H000000FF,&H00202020,&H00000000,-1,1,0,0,100,100,0,0,3,2,0,8,10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.50,0:00:04.00,Default,,0,0,0,,Hello {\b1}bold{\b0} and {\i1\c&H0000FF&}red italic{\r}\Nsecond line
Dialogue: 1,0:00:02.00,0:00:05.00,Sign,,0,0,0,,{\an7\pos(100,200)}Top sign
Dialogue: 0,0:00:03.00,0:00:03.50,Default,,0,0,0,,{\p1}m 0 0 l 100 0 100 100{\p0}
Dialogue: 0,0:00:06.00,0:00:07.00,*Default,,0,0,0,,{\fs80\bord5\3c&HFF0000&\an9}Big{\fad(200,200)} right
"""


def test_parse_script_info_and_styles():
    s = parse_ass(SCRIPT)
    assert s.play_res == (1920, 1080)
    d, sign = s.styles["Default"], s.styles["Sign"]
    assert d.font == "Noto Sans" and d.size == 64 and d.alignment == 2 and d.margin_v == 50
    assert d.back_color == pytest.approx((0, 0, 0, 1 - 0x80 / 255))
    assert sign.bold and sign.italic and sign.border_style == 3 and sign.alignment == 8
    assert sign.primary == (1.0, 1.0, 0.0, 1.0)   # &H0000FFFF → 노랑 (BGR)


def test_override_runs():
    ev = parse_ass(SCRIPT).events[0]
    assert ev.start == 1500 and ev.end == 4000
    texts = [(r.text, r.bold, r.italic, r.color[:3]) for r in ev.runs]
    assert texts == [("Hello ", False, False, (1, 1, 1)), ("bold", True, False, (1, 1, 1)),
                     (" and ", False, False, (1, 1, 1)), ("red italic", False, True, (1, 0, 0)),
                     ("\nsecond line", False, False, (1, 1, 1))]
    assert ev.plain_text == "Hello bold and red italic\nsecond line"


def test_position_alignment_and_drawings():
    s = parse_ass(SCRIPT)
    sign = s.events[1]
    assert sign.alignment == 7 and sign.pos == (100, 200) and sign.layer == 1
    assert anchor_point(sign, s.play_res) == (100, 200, 0.0, 0.0)
    assert len(s.events) == 3                     # 그리기(\p1)만 있는 대사는 제외
    big = s.events[2]
    assert big.alignment == 9 and big.outline == 5 and big.outline_color[:3] == (0, 0, 1)
    assert big.runs[0].size == 80 and big.plain_text == "Big right"
    assert big.style.name == "Default"            # *Default → Default


def test_anchor_from_margins():
    s = parse_ass(SCRIPT)
    ev = s.events[0]                              # 아래 가운데, 여백 40/40/50
    assert anchor_point(ev, s.play_res) == (960, 1030, 0.5, 1.0)


def test_active_at_orders_by_layer():
    s = parse_ass(SCRIPT)
    assert [e.plain_text.split()[0] for e in s.active_at(2500)] == ["Hello", "Top"]
    assert s.active_at(4500)[0].plain_text == "Top sign"
    assert s.active_at(10_000) == []


def test_plain_events_for_search():
    assert events_as_plain(parse_ass(SCRIPT))[1] == (2000, 5000, "Top sign")


@pytest.mark.parametrize("value, expected", [
    ("&H00FFFFFF", (1, 1, 1, 1)), ("&HFF000000", (0, 0, 0, 0)), ("&H0000FF&", (1, 0, 0, 1)), ("junk", None)])
def test_parse_color(value, expected):
    assert parse_color(value, None) == (pytest.approx(expected) if expected else None)


def test_legacy_ssa():
    ssa = """[Script Info]\nPlayResY: 480\n[V4 Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding
Style: Default,Arial,24,16777215,65535,65535,-2147483640,-1,0,1,2,0,6,30,30,10,0,0
[Events]
Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: Marked=0,0:00:00.00,0:00:02.00,Default,,0000,0000,0000,,{\\a1}Old style
"""
    s = parse_ass(ssa)
    assert s.play_res == (640, 480)
    assert s.styles["Default"].alignment == 8      # SSA 6(위 가운데) → 8
    assert s.events[0].alignment == 1 and legacy_alignment(10) == 5
    assert ass_time_to_ms("1:02:03.45") == 3723450


def test_load_ass_script_from_file(tmp_path):
    from jetson_player.subtitles.parse import load_ass_script, parse_subtitle_file_events
    f = tmp_path / "x.ass"
    f.write_text(SCRIPT, encoding="utf-8")
    script = load_ass_script(str(f))
    assert script is not None and script.play_res == (1920, 1080) and len(script.events) == 3
    assert parse_subtitle_file_events(str(f))[0][2].startswith("Hello bold")
    assert load_ass_script(str(tmp_path / "x.srt")) is None


def test_matroska_blocks_and_dedupe():
    from jetson_player.subtitles.ass import AssScript, matroska_block_to_event
    s = parse_ass(SCRIPT)
    live = AssScript(play_res=s.play_res, styles=s.styles)
    ev = matroska_block_to_event("7,0,Sign,,0,0,0,,{\\an5}Center", s.styles, 1000, 2000)
    assert ev.order == 7 and ev.style.name == "Sign" and ev.alignment == 5 and (ev.start, ev.end) == (1000, 2000)
    live.add_events([ev])
    live.add_events([matroska_block_to_event("7,0,Sign,,0,0,0,,{\\an5}Center", s.styles, 1000, 2000)])
    assert len(live.active_at(1500)) == 1


def test_tag_arguments_that_start_with_letters():
    """\\fnComic Sans, \\rSign처럼 인자가 영문자로 시작해도 태그 이름과 구분합니다."""
    s = parse_ass(r"""[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, Bold
Style: Default,Arial,40,&H00FFFFFF,0
Style: Sign,Impact,60,&H0000FFFF,-1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{\fnComic Sans}Hello {\rSign}World {\r\fscx120\blur2\b1}bold
""")
    runs = [(r.text, r.font, r.size, r.bold) for r in s.events[0].runs]
    assert runs == [("Hello ", "Comic Sans", 40.0, False), ("World ", "Impact", 60.0, True), ("bold", "Arial", 40.0, True)]
