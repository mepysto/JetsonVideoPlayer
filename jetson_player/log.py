"""로그 설정: 터미널(기존과 같은 이모지 메시지) + 회전 로그 파일

임포트만으로는 아무 것도 하지 않습니다. app.main()이 시작할 때 setup_logging()을 부릅니다.
JVP_LOG_LEVEL=DEBUG 로 자세한 로그(키 조작, 탐색 등)를 볼 수 있습니다.
"""
import logging
import logging.handlers
import os

from .storage import CACHE_DIR

LOG_FILE = os.path.join(CACHE_DIR, "player.log")
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 3


def setup_logging(level=None, log_file=LOG_FILE):
    """루트 로거에 터미널·파일 핸들러를 붙입니다. 파일을 만들 수 없으면 터미널만 씁니다."""
    level_name = (level or os.environ.get("JVP_LOG_LEVEL") or "INFO").upper()
    level_value = getattr(logging, level_name, None)
    if not isinstance(level_value, int):
        level_value = logging.INFO

    root = logging.getLogger()
    root.setLevel(level_value)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
            root.addHandler(file_handler)
        except OSError as e:
            root.warning(f"⚠️ 로그 파일을 열 수 없어 터미널에만 기록합니다 ({log_file}): {e}")
    return root
