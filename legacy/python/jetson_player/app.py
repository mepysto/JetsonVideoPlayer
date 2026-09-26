"""명령줄 진입점"""
import logging
import signal
import sys

from gi.repository import GLib, Gst, Gtk

from .log import LOG_FILE, setup_logging
from .ui.window import JetsonSignageFlexiblePlayer

log = logging.getLogger(__name__)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print("사용법: jetson-player [동영상파일 또는 디렉토리 경로]")
        print("       jetson-player                 (대기 화면으로 단독 실행)")
        print("\n옵션:")
        print("  -h, --help    도움말 및 사용법 안내 출력")
        print("\n환경 변수:")
        print("  JVP_LOG_LEVEL=DEBUG   자세한 로그 (기본 INFO)")
        print(f"\n로그 파일: {LOG_FILE}")
        sys.exit(0)

    setup_logging()
    Gst.init(None)
    Gtk.init(None)

    user_input = sys.argv[1] if len(sys.argv) >= 2 else None
    win = JetsonSignageFlexiblePlayer(user_input)
    win.show_all()

    # Ctrl+C / kill / 터미널 종료 시에도 정상 종료 경로(설정·이어보기 저장, 파이프라인 해제)를 탑니다.
    def on_signal(signum):
        log.info(f"⏹ 종료 신호 수신 ({signal.Signals(signum).name})")
        win.on_destroy(win)
        return GLib.SOURCE_REMOVE

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, on_signal, sig)

    Gtk.main()
