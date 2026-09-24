import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def jp():
    """GTK를 import하지 않는 순수 모듈들의 공개 이름을 하나의 네임스페이스로 묶어 제공합니다."""
    from jetson_player import library, storage, youtube
    from jetson_player.subtitles import parse, timeline

    ns = types.SimpleNamespace()
    for module in (parse, timeline, youtube, library, storage):
        for name in dir(module):
            if not name.startswith("_"):
                setattr(ns, name, getattr(module, name))
    return ns
