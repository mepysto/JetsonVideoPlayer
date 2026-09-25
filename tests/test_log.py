import logging

from jetson_player.log import setup_logging


def test_setup_logging_writes_file_and_console(tmp_path, capsys):
    log_file = tmp_path / "sub" / "player.log"
    root = setup_logging("DEBUG", str(log_file))
    try:
        logging.getLogger("jetson_player.test").warning("⚠️ 테스트 경고")
        for h in root.handlers:
            h.flush()
        assert "⚠️ 테스트 경고" in log_file.read_text(encoding="utf-8")
        assert "WARNING" in log_file.read_text(encoding="utf-8")
        assert "⚠️ 테스트 경고" in capsys.readouterr().err
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()


def test_unknown_level_falls_back_to_info(tmp_path):
    root = setup_logging("LOUD", None)
    try:
        assert root.level == logging.INFO
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
