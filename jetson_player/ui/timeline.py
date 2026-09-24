"""진행바(타임라인): 마우스 hover 미리보기(시각 + 썸네일), 남은 시간 표시 전환, 북마크/구간/챕터 눈금"""
from gi.repository import Gdk, Gtk

from ..settings import settings
from ..storage import bookmark_cache


class TimelineMixin:
    # ---- hover 미리보기 ---------------------------------------------------
    def setup_timeline_interactions(self, scale):
        """진행바에 hover 미리보기 팝오버를 연결합니다 (일반/전체화면 진행바 공용)."""
        scale.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        scale.connect("motion-notify-event", self.on_timeline_motion)
        scale.connect("leave-notify-event", self.on_timeline_leave)

        pop = Gtk.Popover(relative_to=scale)
        pop.set_modal(False)
        pop.set_position(Gtk.PositionType.TOP)
        pop.set_transitions_enabled(False)
        pop.get_style_context().add_class("timeline-preview")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        image = Gtk.Image()
        image.set_no_show_all(True)
        label = Gtk.Label()
        label.get_style_context().add_class("timeline-preview-time")
        box.pack_start(image, False, False, 0)
        box.pack_start(label, False, False, 0)
        pop.add(box)
        box.show_all()
        scale.timeline_preview = (pop, image, label)

    @staticmethod
    def _scale_ratio_at(scale, x):
        alloc = scale.get_allocation()
        if alloc.width <= 0:
            return None
        return max(0.0, min(1.0, x / alloc.width))

    def on_timeline_motion(self, scale, event):
        preview = getattr(scale, "timeline_preview", None)
        if not preview or self.duration_ns <= 0:
            return False
        pop, image, label = preview
        ratio = self._scale_ratio_at(scale, event.x)
        if ratio is None:
            return False
        target_ns = int(self.duration_ns * ratio)
        text = self.format_time(target_ns)
        chapter = self.chapter_title_at(target_ns) if hasattr(self, "chapter_title_at") else None
        if chapter:
            text = f"{text}  ·  {chapter}"
        label.set_text(text)

        pixbuf = self.get_thumbnail_at(target_ns) if hasattr(self, "get_thumbnail_at") else None
        if pixbuf is not None:
            image.set_from_pixbuf(pixbuf)
            image.show()
        else:
            image.hide()

        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(event.x), 0, 1, 1
        pop.set_pointing_to(rect)
        if not pop.get_visible():
            pop.show()
        return False

    def on_timeline_leave(self, scale, _event):
        preview = getattr(scale, "timeline_preview", None)
        if preview:
            preview[0].hide()
        return False

    def hide_timeline_previews(self):
        for scale in (getattr(self, "progress_scale", None), getattr(self, "fs_progress_scale", None)):
            preview = getattr(scale, "timeline_preview", None) if scale else None
            if preview:
                preview[0].hide()

    # ---- 남은 시간 / 전체 시간 전환 ----------------------------------------
    def make_time_toggle(self, label):
        """시간 라벨을 클릭하면 전체 길이와 남은 시간 표시를 전환하도록 감쌉니다."""
        box = Gtk.EventBox()
        box.add(label)
        box.set_tooltip_text("클릭: 전체 길이 / 남은 시간 표시 전환")
        box.connect("button-press-event", lambda _w, _e: (self.toggle_time_display(), True)[1])
        return box

    def toggle_time_display(self):
        settings.set("time_display_remaining", not settings.get("time_display_remaining"))
        self.update_duration_labels(self.last_known_pos_ns)

    def update_duration_labels(self, position_ns):
        if self.duration_ns <= 0:
            return
        if settings.get("time_display_remaining"):
            text = "-" + self.format_time(max(0, self.duration_ns - position_ns))
        else:
            text = self.format_time(self.duration_ns)
        for lbl in (getattr(self, "duration_label", None), getattr(self, "fs_duration_label", None)):
            if lbl:
                lbl.set_text(text)

    # ---- 눈금: 북마크 / A-B 구간 / 챕터 -------------------------------------
    def refresh_timeline_marks(self):
        """진행바에 북마크(▾), A-B 구간, 챕터 위치를 눈금으로 표시합니다."""
        scales = [s for s in (getattr(self, "progress_scale", None), getattr(self, "fs_progress_scale", None)) if s]
        for scale in scales:
            scale.clear_marks()
        if self.duration_ns <= 0 or not self.playlist or not (0 <= self.current_index < len(self.playlist)):
            return
        positions = []
        for bm in bookmark_cache.get(self.playlist[self.current_index]):
            positions.append(bm.get("position_ns", 0))
        for chapter_ns, _title in getattr(self, "chapters", []):
            if chapter_ns > 0:
                positions.append(chapter_ns)
        if self.ab_repeat_a is not None:
            positions.append(self.ab_repeat_a)
        if self.ab_repeat_b is not None:
            positions.append(self.ab_repeat_b)
        for scale in scales:
            for pos in positions:
                scale.add_mark(min(100.0, pos * 100.0 / self.duration_ns), Gtk.PositionType.TOP, None)
