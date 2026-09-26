import ast
import glob
import os

import pytest

from jetson_player.shortcuts import SHORTCUTS, find_shortcut, help_rows, markdown_tables, mods_match

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_STATES = [(s, c) for s in (False, True) for c in (False, True)]


@pytest.mark.parametrize("key,shift,ctrl,action,args", [
    ("s", False, True, "capture_screenshot", ()),
    ("s", False, False, "toggle_subtitles", ()),
    ("O", True, True, "open_folder_dialog", ()),
    ("o", False, True, "open_file_dialog", ()),
    ("b", False, False, "add_bookmark", ()),
    ("Right", True, False, "seek_relative", (30,)),
    ("Right", False, False, "seek_relative", (10,)),
    ("Right", False, True, "frame_step", (1,)),
    ("Up", False, False, "step_playback_rate", (0.25,)),
    ("Up", True, False, "step_volume", (5,)),        # README에 있었지만 구현되지 않았던 조합
    ("A", True, False, "cycle_audio_track", ()),
    ("a", False, False, "step_playback_rate", (-0.25,)),
    ("braceleft", True, False, "set_ab_repeat_a", ()),
    ("bracketleft", False, False, "adjust_subtitle_scale", (-0.1,)),
    ("period", True, False, "step_playback_rate", (0.25,)),
    ("period", False, False, "adjust_subtitle_sync", (100,)),
    ("R", True, False, "cycle_repeat_mode", ()),
    ("r", False, False, "reset_playback_rate", ()),
    ("Escape", False, False, "handle_escape", ()),
])
def test_key_mapping(key, shift, ctrl, action, args):
    sc = find_shortcut(key, shift, ctrl)
    assert sc is not None and sc.action == action and sc.args == args


def test_unknown_key():
    assert find_shortcut("F12", False, False) is None


def test_no_fully_shadowed_rows():
    """앞 항목에 완전히 가려져 절대 실행될 수 없는 항목이 없어야 합니다."""
    for i, sc in enumerate(SHORTCUTS):
        for key in sc.keys:
            reachable = any(
                mods_match(sc.mods, s, c) and find_shortcut(key, s, c) is sc for s, c in MOD_STATES
            )
            assert reachable, f"{key} ({sc.mods}) → {sc.action} 는 앞 항목에 가려집니다"


def _window_methods():
    names = set()
    for path in glob.glob(os.path.join(ROOT, "jetson_player", "ui", "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.update(n.name for n in node.body if isinstance(n, ast.FunctionDef))
    return names


def test_all_actions_implemented():
    missing = sorted({sc.action for sc in SHORTCUTS} - _window_methods())
    assert not missing, f"단축키 동작 미구현: {missing}"


def test_help_and_markdown():
    rows = help_rows()
    assert any(key == "Ctrl + S" for _, key, _ in rows)
    md = markdown_tables()
    assert "| `Ctrl + S` |" in md and "### 자막" in md
