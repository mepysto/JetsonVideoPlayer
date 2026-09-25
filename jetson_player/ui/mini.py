"""미니 플레이어 (W): 테두리 없는 작은 창을 항상 위에 띄워 다른 작업을 하면서 봅니다.

드래그: 창 이동 · 더블클릭 / W / Esc: 원래 창으로 · 휠: 볼륨 · Ctrl+휠: 크기
마우스를 올리면 전체화면과 같은 떠 있는 컨트롤이 나타납니다 (is_video_only 경로 재사용).
"""
import logging

from gi.repository import Gdk, GLib, Gtk

from ..settings import settings

log = logging.getLogger(__name__)

MINI_MARGIN = 24
MINI_MIN_WIDTH = 240
MINI_MAX_WIDTH = 1280
NORMAL_MIN_VIDEO_SIZE = (640, 480)


def mini_height(width, video_size):
    """영상 비율에 맞춘 미니 창 높이 (영상 크기를 모르면 16:9)"""
    vw, vh = video_size if video_size and all(video_size) else (16, 9)
    return max(90, int(round(width * vh / vw)))


class MiniPlayerMixin:
    def toggle_mini_player(self):
        if getattr(self, "is_mini", False):
            self.exit_mini_player()
        else:
            self.enter_mini_player()

    def enter_mini_player(self):
        if self.is_fullscreen:
            self.toggle_fullscreen()
        self._mini_restore = {
            "size": self.get_size(), "position": self.get_position(),
            "maximized": getattr(self, "is_maximized", False), "sidebar": self.sidebar.get_visible(),
        }
        if self._mini_restore["maximized"]:
            self.unmaximize()
        self.is_mini = True
        self.sidebar_was_visible = self._mini_restore["sidebar"]
        self.topbar.hide()
        self.sidebar.hide()
        self.controls.hide()
        self.is_video_only = True        # 마우스를 올리면 떠 있는 컨트롤 표시 (미니용 작은 컨트롤)
        if getattr(self, "fs_controls_box", None):
            self.fs_controls_box.hide()
        self.is_fs_controls_visible = False
        self.set_decorated(False)
        self.set_keep_above(True)
        self.video_widget.set_size_request(160, 90)
        self._apply_mini_geometry(settings.get("mini_width"))
        self.show_osd("🗗 미니 플레이어 — 드래그: 이동 · 휠: 볼륨 · Ctrl+휠: 크기 · 더블클릭: 원래대로", duration_sec=3.0)
        log.debug("🗗 미니 플레이어")

    def _apply_mini_geometry(self, width, keep_position=False):
        width = int(max(MINI_MIN_WIDTH, min(MINI_MAX_WIDTH, width)))
        height = mini_height(width, getattr(self, "video_resolution", None))
        x, y = settings.get("mini_x"), settings.get("mini_y")
        if keep_position:
            x, y = self.get_position()
        elif x < 0 or y < 0:
            area = self._workarea()
            x = area.x + area.width - width - MINI_MARGIN
            y = area.y + area.height - height - MINI_MARGIN
        self.set_position(Gtk.WindowPosition.NONE)   # 시작 시 지정한 CENTER가 크기 변경 때 다시 가운데로 옮기지 않도록
        self.resize(width, height)
        self.move(x, y)
        # 창 관리자가 크기 변경을 먼저 처리한 뒤 위치를 한 번 더 맞춥니다.
        GLib.timeout_add(150, lambda: (self.move(x, y) if getattr(self, "is_mini", False) else None, False)[1])
        self._mini_width = width

    def _workarea(self):
        display = Gdk.Display.get_default()
        gdk_win = self.get_window()
        monitor = display.get_monitor_at_window(gdk_win) if gdk_win else display.get_primary_monitor()
        return (monitor or display.get_monitor(0)).get_workarea()

    def exit_mini_player(self):
        if not getattr(self, "is_mini", False):
            return
        x, y = self.get_position()
        settings.set("mini_x", x)
        settings.set("mini_y", y)
        settings.set("mini_width", getattr(self, "_mini_width", settings.get("mini_width")))
        self.is_mini = False
        self.is_video_only = False
        for box in (getattr(self, "fs_controls_box", None), getattr(self, "mini_controls_box", None)):
            if box is not None:
                box.hide()
        self.is_fs_controls_visible = False
        self.show_cursor()
        self.video_widget.set_size_request(*NORMAL_MIN_VIDEO_SIZE)
        self.set_decorated(True)
        self.set_keep_above(self.is_keep_above)
        self.topbar.show()
        self.controls.show()
        restore = getattr(self, "_mini_restore", None) or {}
        if restore.get("sidebar", True):
            self.sidebar.show()
        if restore.get("size"):
            self.resize(*restore["size"])
        if restore.get("position"):
            self.move(*restore["position"])
        if restore.get("maximized"):
            self.maximize()
        self.show_osd("🗖 원래 창으로")

    def ensure_mini_controls(self):
        """미니 창 아래쪽에 뜨는 작은 컨트롤 (이전 · 재생/일시정지 · 다음 · 원래 창)"""
        box = getattr(self, "mini_controls_box", None)
        if box is not None:
            return box
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.get_style_context().add_class("fs-controls")
        box.get_style_context().add_class("mini-controls")
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.END)
        for label, tip, callback in (("⏮", "이전 영상", self.play_prev_video),
                                     ("⏯", "재생 / 일시정지", self.toggle_play_pause),
                                     ("⏭", "다음 영상", self.play_next_video),
                                     ("🗖", "원래 창으로 (W)", self.exit_mini_player)):
            btn = Gtk.Button(label=label)
            btn.set_tooltip_text(tip)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.connect("clicked", lambda _b, cb=callback: cb())
            box.pack_start(btn, False, False, 0)
        box.connect("enter-notify-event", self._on_fs_controls_enter)
        box.connect("leave-notify-event", self._on_fs_controls_leave)
        box.set_no_show_all(True)
        self.video_container.add_overlay(box)
        self.mini_controls_box = box
        return box

    def handle_mini_button_press(self, event):
        """미니 모드의 영상 클릭: 드래그로 창 이동, 더블클릭으로 복귀. 처리했으면 True."""
        if not getattr(self, "is_mini", False) or event.button != 1:
            return False
        if event.type == Gdk.EventType._2BUTTON_PRESS:
            self.exit_mini_player()
            return True
        if event.type == Gdk.EventType.BUTTON_PRESS:
            # 창 관리자에 맡기는 begin_move_drag 대신 직접 옮깁니다 (창 관리자에 따라 끌기가 불안정).
            x, y = self.get_position()
            self._mini_drag = (event.x_root - x, event.y_root - y)
            return True
        return False

    def mini_drag_motion(self, event):
        """드래그 중이면 창을 옮기고 True"""
        drag = getattr(self, "_mini_drag", None)
        if not drag or not getattr(self, "is_mini", False):
            return False
        self.move(int(event.x_root - drag[0]), int(event.y_root - drag[1]))
        return True

    def end_mini_drag(self):
        self._mini_drag = None

    def handle_mini_scroll(self, event):
        """미니 모드의 휠: 볼륨, Ctrl+휠: 창 크기. 처리했으면 True."""
        if not getattr(self, "is_mini", False):
            return False
        up = event.direction == Gdk.ScrollDirection.UP or (
            event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y < -0.1)
        down = event.direction == Gdk.ScrollDirection.DOWN or (
            event.direction == Gdk.ScrollDirection.SMOOTH and event.delta_y > 0.1)
        if not (up or down):
            return False
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            self._apply_mini_geometry(getattr(self, "_mini_width", 480) * (1.1 if up else 1 / 1.1), keep_position=True)
        else:
            self.step_volume(5 if up else -5)
            self.show_osd(f"🔊 {int(self.volume_scale.get_value())}%", timeout_ms=700)
        return True
