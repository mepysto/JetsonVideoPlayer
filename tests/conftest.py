import importlib.util
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def jp():
    """jetson_player.py를 모듈로 로드합니다 (GUI는 초기화하지 않음)."""
    spec = importlib.util.spec_from_file_location("jetson_player", os.path.join(ROOT, "jetson_player.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
