"""영상 위에 외부/AI 자막을 직접 그리는 오버레이 위젯 (Pango + Cairo).

GStreamer의 suburi/textoverlay 대신 이 위젯을 쓰면 트랙 선택, 싱크, 크기 변경이
파이프라인 재구축 없이 즉시 반영되고, 생성 중인 AI 자막도 실시간으로 표시할 수 있습니다.
"""
from gi.repository import GLib, Gtk, Pango, PangoCairo

from ..subtitles.timeline import active_lines

FONT_FAMILY = "Noto Sans CJK KR, Noto Sans CJK TC, Noto Sans CJK SC, Noto Sans CJK JP, Sans"
TICK_MS = 40


def _hex_to_rgb(color):
    try:
        c = color.lstrip("#")
        return int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0
    except (ValueError, IndexError):
        return 1.0, 1.0, 1.0


class SubtitleOverlay(Gtk.DrawingArea):
    def __init__(self, position_provider):
        """position_provider(): 현재 재생 위치(ms) 또는 None"""
        super().__init__()
        self.position_provider = position_provider
        self.tracks = []
        self.offset_ms = 0
        self.font_scale = 1.0
        self.enabled = True
        self.video_size = None       # (width, height) — 레터박스 계산용 (픽셀 종횡비 반영)
        self._lines = []
        self._timer_id = None
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)
        self.connect("draw", self._on_draw)

    # ---- 상태 설정 -------------------------------------------------------
    def set_tracks(self, tracks):
        self.tracks = list(tracks)
        self._sync_timer()
        self.refresh(force=True)

    def set_offset(self, offset_ms):
        self.offset_ms = offset_ms
        self.refresh(force=True)

    def set_font_scale(self, scale):
        self.font_scale = scale
        self.queue_draw()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._sync_timer()
        self.refresh(force=True)

    def set_video_size(self, width, height):
        self.video_size = (width, height) if width and height else None
        self.queue_draw()

    def clear(self):
        self.tracks = []
        self.video_size = None
        self._sync_timer()
        self.refresh(force=True)

    # ---- 갱신 -----------------------------------------------------------
    def _sync_timer(self):
        active = self.enabled and bool(self.tracks)
        if active and self._timer_id is None:
            self._timer_id = GLib.timeout_add(TICK_MS, self._on_tick)
        elif not active and self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def _on_tick(self):
        self.refresh()
        return True

    def refresh(self, force=False):
        lines = []
        if self.enabled and self.tracks:
            pos = self.position_provider()
            if pos is not None:
                lines = active_lines(self.tracks, pos, self.offset_ms)
        if force or lines != self._lines:
            self._lines = lines
            self.queue_draw()

    def current_lines(self):
        return list(self._lines)

    # ---- 그리기 ---------------------------------------------------------
    def _video_rect(self, width, height):
        """위젯 안에서 실제 영상이 그려지는 영역 (종횡비 유지 레터박스)"""
        if not self.video_size:
            return 0, 0, width, height
        vw, vh = self.video_size
        scale = min(width / vw, height / vh)
        w, h = vw * scale, vh * scale
        return (width - w) / 2, (height - h) / 2, w, h

    def _on_draw(self, widget, cr):
        if not self._lines:
            return False
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        vx, vy, vw, vh = self._video_rect(width, height)

        n_tracks = max(1, len(self.tracks))
        factor = 0.052 if n_tracks == 1 else (0.042 if n_tracks == 2 else 0.035)
        font_px = max(12, int(vh * factor * self.font_scale))

        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription.from_string(f"{FONT_FAMILY} Bold")
        desc.set_absolute_size(font_px * Pango.SCALE)
        layout.set_font_description(desc)
        layout.set_alignment(Pango.Alignment.CENTER)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_width(int(vw * 0.92 * Pango.SCALE))

        # 아래 줄부터 위로 쌓아 올립니다.
        rendered = []
        for text, color in self._lines:
            layout.set_text(text, -1)
            _ink, logical = layout.get_pixel_extents()
            rendered.append((text, color, logical.height))
        line_gap = font_px * 0.12
        y = vy + vh - vh * 0.06
        outline = max(2.0, font_px * 0.14)
        for text, color, line_h in reversed(rendered):
            y -= line_h
            layout.set_text(text, -1)
            cr.move_to(vx + vw * 0.04, y)
            PangoCairo.layout_path(cr, layout)
            cr.set_source_rgba(0, 0, 0, 0.92)
            cr.set_line_width(outline)
            cr.set_line_join(1)  # ROUND
            cr.stroke_preserve()
            r, g, b = _hex_to_rgb(color)
            cr.set_source_rgb(r, g, b)
            cr.fill()
            y -= line_gap
        return False
