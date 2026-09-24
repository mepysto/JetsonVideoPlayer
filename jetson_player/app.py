"""명령줄 진입점"""
import signal
import sys

from gi.repository import GLib, Gst, Gtk

from .ui.window import JetsonSignageFlexiblePlayer


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help"):
        print("사용법: jetson-player [동영상파일 또는 디렉토리 경로]")
        print("       jetson-player                 (대기 화면으로 단독 실행)")
        print("\n옵션:")
        print("  -h, --help    도움말 및 사용법 안내 출력")
        sys.exit(0)

    Gst.init(None)
    Gtk.init(None)

    user_input = sys.argv[1] if len(sys.argv) >= 2 else None
    win = JetsonSignageFlexiblePlayer(user_input)
    win.show_all()

    # Ctrl+C / kill / 터미널 종료 시에도 정상 종료 경로(설정·이어보기 저장, 파이프라인 해제)를 탑니다.
    def on_signal(signum):
        print(f"\n⏹ 종료 신호 수신 ({signal.Signals(signum).name})")
        win.on_destroy(win)
        return GLib.SOURCE_REMOVE

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, on_signal, sig)

    Gtk.main()
