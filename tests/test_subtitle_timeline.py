from jetson_player.subtitles.timeline import SubtitleTrack, active_lines, short_badge


def test_active_at_and_boundaries():
    tr = SubtitleTrack("🇰🇷 한국어 (a.ko.srt)", "#FFFFFF", [(1000, 2000, "하나"), (2000, 3000, "둘"), (5000, 9000, "셋")])
    assert tr.active_at(999) == []
    assert tr.active_at(1000) == ["하나"]
    assert tr.active_at(1999) == ["하나"]
    assert tr.active_at(2000) == ["둘"]          # 끝 시각은 포함하지 않음
    assert tr.active_at(4000) == []
    assert tr.active_at(8999) == ["셋"]


def test_overlapping_and_long_events():
    tr = SubtitleTrack("x", "#fff", [(0, 60000, "긴 제목"), (1000, 2000, "대사")])
    assert tr.active_at(1500) == ["긴 제목", "대사"]
    assert tr.active_at(30000) == ["긴 제목"]


def test_add_events_incrementally_out_of_order():
    tr = SubtitleTrack("🤖 AI", "#B388FF")
    tr.add_events([(5000, 6000, "나중")])
    tr.add_events([(1000, 2000, "먼저"), (3000, 3000, "길이0 무시"), (4000, 4500, "   ")])
    assert len(tr) == 2
    assert tr.active_at(1500) == ["먼저"] and tr.active_at(5500) == ["나중"]


def test_next_change_after():
    tr = SubtitleTrack("x", "#fff", [(1000, 2000, "a"), (5000, 6000, "b")])
    assert tr.next_change_after(0) == 1000
    assert tr.next_change_after(1500) == 2000
    assert tr.next_change_after(2500) == 5000
    assert tr.next_change_after(7000) is None


def test_active_lines_multi_track_badges_and_offset():
    ko = SubtitleTrack("🇰🇷 한국어 (a.ko.srt)", "#FFFFFF", [(1000, 2000, "안녕\n하세요")])
    en = SubtitleTrack("🇺🇸 영어 (a.en.srt)", "#FFE066", [(1000, 2000, "Hello")])
    assert active_lines([ko], 1500) == [("안녕", "#FFFFFF"), ("하세요", "#FFFFFF")]
    assert active_lines([ko, en], 1500) == [("[KR] 안녕", "#FFFFFF"), ("하세요", "#FFFFFF"), ("[EN] Hello", "#FFE066")]
    # 오프셋 +500ms: 자막이 0.5초 늦게 표시
    assert active_lines([ko], 1200, offset_ms=500) == []
    assert active_lines([ko], 1600, offset_ms=500) != []


def test_short_badge():
    assert short_badge("🇯🇵 일본어 (x.ja.srt)") == "[JP] "
    assert short_badge("🤖 AI 자막 (auto)") == "[AI] "
    assert short_badge("📄 x.srt") == ""
