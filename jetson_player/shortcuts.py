"""키보드 단축키 정의 테이블.

키 처리(on_key_press), 도움말 대화상자(F1), README 단축키 표가 모두 이 테이블 하나에서 만들어집니다.
표는 위에서부터 차례로 검사하며 처음 일치하는 항목이 실행됩니다.

`python3 -m jetson_player.shortcuts` 를 실행하면 README용 마크다운 표를 출력합니다.
"""
from collections import namedtuple

# mods 조건:
#   "plain"  : Shift/Ctrl 없이      "shift" : Shift (Ctrl 없이)      "ctrl" : Ctrl (Shift 없이)
#   "ctrl_shift": Ctrl+Shift        "noctrl": Ctrl 없이 (Shift 무관)   "any" : 조건 없음
Shortcut = namedtuple("Shortcut", "keys mods action args help_key help_desc category")


def _sc(keys, mods, action, args=(), help_key=None, help_desc=None, category=None):
    return Shortcut(frozenset(keys), mods, action, tuple(args), help_key, help_desc, category)


PLAYBACK = "재생 및 탐색"
MARKS = "구간 반복 & 북마크 & 캡처"
SCREEN = "화면 및 오디오"
SUBS = "자막"
GENERAL = "파일 및 일반"
EXTRA = "부가 기능"

CATEGORY_ORDER = [PLAYBACK, MARKS, SCREEN, SUBS, EXTRA, GENERAL]

SHORTCUTS = [
    # 파일 / 캡처 / 북마크 (Ctrl 조합 우선)
    _sc({"s", "S"}, "ctrl", "capture_screenshot", help_key="Ctrl + S", help_desc="현재 프레임 원본 무손실 스크린샷 저장", category=MARKS),
    _sc({"o", "O"}, "ctrl_shift", "open_folder_dialog", help_key="Ctrl + Shift + O", help_desc="동영상 폴더 열기", category=GENERAL),
    _sc({"o", "O"}, "ctrl", "open_file_dialog", help_key="Ctrl + O", help_desc="동영상 파일 열기", category=GENERAL),
    _sc({"b", "B"}, "ctrl", "show_bookmarks_popover", help_key="Ctrl + B", help_desc="북마크 목록 (클릭 시 점프 / 삭제)", category=MARKS),
    _sc({"b", "B"}, "plain", "add_bookmark", help_key="B", help_desc="현재 위치 북마크 추가", category=MARKS),

    # 종료 / 전체화면 해제
    _sc({"Escape"}, "any", "handle_escape", help_key="Esc", help_desc="전체화면 해제 (일반 창에서는 종료)", category=GENERAL),
    _sc({"q", "Q"}, "noctrl", "quit_player", help_key="Q", help_desc="플레이어 종료", category=GENERAL),

    # 재생 및 탐색
    _sc({"space"}, "any", "toggle_play_pause", help_key="Space / 마우스 좌클릭", help_desc="재생 / 일시정지", category=PLAYBACK),
    _sc({"Right"}, "shift", "seek_relative", (30,), help_key="Shift + Left / Right", help_desc="30초 뒤로 / 앞으로", category=PLAYBACK),
    _sc({"Left"}, "shift", "seek_relative", (-30,)),
    _sc({"Right"}, "ctrl", "frame_step", (1,), help_key="Ctrl + Left / Right", help_desc="한 프레임 뒤로 / 앞으로 (일시정지 상태)", category=PLAYBACK),
    _sc({"Left"}, "ctrl", "frame_step", (-1,)),
    _sc({"Right"}, "any", "seek_relative", (10,), help_key="Left / Right", help_desc="10초 뒤로 / 앞으로", category=PLAYBACK),
    _sc({"Left"}, "any", "seek_relative", (-10,)),
    _sc({"l", "L"}, "noctrl", "seek_relative", (10,), help_key="J / L", help_desc="10초 뒤로 / 앞으로 (YouTube 스타일)", category=PLAYBACK),
    _sc({"j", "J"}, "noctrl", "seek_relative", (-10,)),
    _sc({"n", "N"}, "noctrl", "play_next_video", help_key="P / N", help_desc="이전 영상 / 다음 영상 (대기열 우선)", category=PLAYBACK),
    _sc({"p", "P"}, "noctrl", "play_prev_video"),

    # 볼륨 (Shift+Up/Down은 속도보다 먼저 검사)
    _sc({"Up"}, "shift", "step_volume", (5,), help_key="0 / 9 (또는 Shift + Up / Down)", help_desc="볼륨 5% 올리기 / 내리기 (최대 200% 부스트)", category=SCREEN),
    _sc({"Down"}, "shift", "step_volume", (-5,)),
    _sc({"0", "parenright"}, "noctrl", "step_volume", (5,)),
    _sc({"9", "parenleft"}, "noctrl", "step_volume", (-5,)),
    _sc({"m", "M"}, "noctrl", "toggle_mute", help_key="M", help_desc="음소거 켜기 / 끄기", category=SCREEN),

    # 재생 속도
    _sc({"Up", "d", "D"}, "plain", "step_playback_rate", (0.25,), help_key="Up / Down 또는 D / A", help_desc="재생 속도 +0.25x / -0.25x", category=PLAYBACK),
    _sc({"Down", "a", "A"}, "plain", "step_playback_rate", (-0.25,)),
    _sc({"greater", "period"}, "shift", "step_playback_rate", (0.25,), help_key="> / <", help_desc="재생 속도 빠르게 / 느리게", category=PLAYBACK),
    _sc({"less", "comma"}, "shift", "step_playback_rate", (-0.25,)),
    _sc({"r", "R"}, "shift", "cycle_repeat_mode", help_key="Shift + R", help_desc="재생 모드 순환 (전체반복 → 한곡반복 → 순차정지 → 셔플)", category=PLAYBACK),
    _sc({"r", "R"}, "ctrl", "cycle_repeat_mode"),
    _sc({"r", "R"}, "plain", "reset_playback_rate", help_key="R", help_desc="재생 속도 1.0x 복원", category=PLAYBACK),

    # 오디오 트랙 / AV 싱크
    _sc({"a", "A"}, "shift", "cycle_audio_track", help_key="Shift + A", help_desc="오디오(음성) 트랙 전환", category=SCREEN),
    _sc({"z", "Z"}, "shift", "adjust_av_sync", (-50,), help_key="Shift + Z / X", help_desc="오디오(AV) 싱크 50ms 앞당김 / 늦춤", category=SCREEN),
    _sc({"x", "X"}, "shift", "adjust_av_sync", (50,)),
    _sc({"c", "C"}, "shift", "reset_av_sync", help_key="Shift + C", help_desc="오디오(AV) 싱크 0ms 초기화", category=SCREEN),

    # 구간 반복
    _sc({"bracketleft", "braceleft"}, "shift", "set_ab_repeat_a", help_key="Shift + [ / ]", help_desc="A-B 구간 반복 시작점(A) / 끝점(B) 설정", category=MARKS),
    _sc({"bracketright", "braceright"}, "shift", "set_ab_repeat_b"),
    _sc({"backslash", "bar"}, "any", "clear_ab_repeat", help_key="\\ (백슬래시)", help_desc="A-B 구간 반복 해제", category=MARKS),

    # 자막
    _sc({"s", "S"}, "plain", "toggle_subtitles", help_key="S", help_desc="자막 켜기 / 끄기 (내장 자막 포함)", category=SUBS),
    _sc({"c", "C"}, "plain", "show_subtitle_popover", help_key="C", help_desc="자막 선택 및 크기/싱크 설정 창", category=SUBS),
    _sc({"bracketleft"}, "plain", "adjust_subtitle_scale", (-0.1,), help_key="[ / ]", help_desc="자막 크기 -10% / +10%", category=SUBS),
    _sc({"bracketright"}, "plain", "adjust_subtitle_scale", (0.1,)),
    _sc({"z", "Z"}, "plain", "adjust_subtitle_sync", (-500,), help_key="Z / X", help_desc="자막 싱크 -0.5초 / +0.5초", category=SUBS),
    _sc({"x", "X"}, "plain", "adjust_subtitle_sync", (500,)),
    _sc({"comma"}, "plain", "adjust_subtitle_sync", (-100,), help_key=", / .", help_desc="자막 싱크 -0.1초 / +0.1초", category=SUBS),
    _sc({"period"}, "plain", "adjust_subtitle_sync", (100,)),
    _sc({"g", "G"}, "plain", "start_ai_subtitles", help_key="G", help_desc="🤖 AI 자막 생성 (Whisper, 음성 인식)", category=SUBS),

    # 화면
    _sc({"f", "F"}, "noctrl", "toggle_fullscreen", help_key="F / 마우스 더블클릭", help_desc="영상 전용 전체화면", category=SCREEN),
    _sc({"t", "T"}, "noctrl", "toggle_keep_above", help_key="T", help_desc="항상 위에 표시", category=SCREEN),
    _sc({"i", "I"}, "noctrl", "toggle_hud", help_key="I", help_desc="Jetson 하드웨어 & 미디어 정보 HUD", category=SCREEN),
    _sc({"v", "V"}, "plain", "cycle_video_rotation", help_key="V", help_desc="화면 회전 (90° 단위 / 좌우·상하 반전)", category=SCREEN),
    _sc({"e", "E"}, "plain", "toggle_night_mode", help_key="E", help_desc="🌙 야간 모드 (큰 소리 줄이고 작은 대사 키우기)", category=SCREEN),

    # 부가 기능
    _sc({"h", "H"}, "plain", "cycle_sleep_timer", help_key="H", help_desc="⏾ 수면 타이머 (15 → 30 → 60분 → 영상 끝 → 끄기)", category=EXTRA),
    _sc({"k", "K"}, "plain", "show_chapters_menu", help_key="K", help_desc="챕터 / 장면 목록", category=EXTRA),

    _sc({"F1", "question"}, "any", "show_help_dialog", help_key="F1 또는 ?", help_desc="단축키 도움말", category=GENERAL),
]

# 도움말에만 표시되는 마우스 조작
MOUSE_HELP = [
    ("마우스 휠 위 / 아래", "비디오 영역에서 10초 앞으로 / 뒤로", PLAYBACK),
    ("진행바에 마우스 올리기", "해당 시각 미리보기 (썸네일)", PLAYBACK),
    ("마우스 우클릭", "빠른 조작 메뉴", GENERAL),
]


def mods_match(mods, shift, ctrl):
    if mods == "any":
        return True
    if mods == "plain":
        return not shift and not ctrl
    if mods == "shift":
        return shift and not ctrl
    if mods == "ctrl":
        return ctrl and not shift
    if mods == "ctrl_shift":
        return ctrl and shift
    if mods == "noctrl":
        return not ctrl
    raise ValueError(mods)


def find_shortcut(keyname, shift, ctrl):
    """눌린 키에 해당하는 첫 번째 단축키 항목을 반환합니다 (없으면 None)."""
    for sc in SHORTCUTS:
        if keyname in sc.keys and mods_match(sc.mods, shift, ctrl):
            return sc
    return None


def help_rows():
    """카테고리 순서대로 정렬된 (카테고리, 키, 설명) 목록"""
    rows = [(sc.category, sc.help_key, sc.help_desc) for sc in SHORTCUTS if sc.help_key]
    rows += [(cat, key, desc) for key, desc, cat in MOUSE_HELP]
    return sorted(rows, key=lambda r: CATEGORY_ORDER.index(r[0]))


def markdown_tables():
    out = []
    current = None
    for cat, key, desc in help_rows():
        if cat != current:
            current = cat
            out.append(f"\n### {cat}\n| 조작 | 기능 |\n| --- | --- |")
        keys = key if ("마우스" in key or "진행바" in key) else f"`{key}`"
        out.append(f"| {keys} | {desc} |")
    return "\n".join(out).strip() + "\n"


if __name__ == "__main__":
    print(markdown_tables())
