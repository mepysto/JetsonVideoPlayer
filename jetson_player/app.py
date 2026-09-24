"""명령줄 진입점"""
import sys

from gi.repository import Gst, Gtk

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
    Gtk.main()
