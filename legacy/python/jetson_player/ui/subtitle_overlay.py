"""영상 위에 외부/AI 자막을 직접 그리는 오버레이 위젯 (Pango + Cairo).

GStreamer의 suburi/textoverlay 대신 이 위젯을 쓰면 트랙 선택, 싱크, 크기 변경이
파이프라인 재구축 없이 즉시 반영되고, 생성 중인 AI 자막도 실시간으로 표시할 수 있습니다.
"""
from gi.repository import GLib, Gtk, Pango, PangoCairo

from ..subtitles.ass import anchor_point
from ..subtitles.timeline import active_ass_events, active_lines

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
        self._ass = []               # [(AssScript, AssEvent)] — ASS 원래 스타일로 그릴 대사
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
        lines, ass = [], []
        if self.enabled and self.tracks:
            pos = self.position_provider()
            if pos is not None:
                lines = active_lines(self.tracks, pos, self.offset_ms)
                ass = active_ass_events(self.tracks, pos, self.offset_ms)
        if force or lines != self._lines or [id(e) for _s, e in ass] != [id(e) for _s, e in self._ass]:
            self._lines = lines
            self._ass = ass
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
        if not self._lines and not self._ass:
            return False
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        vx, vy, vw, vh = self._video_rect(width, height)
        if self._ass:
            self._draw_ass(cr, (vx, vy, vw, vh))
        if not self._lines:
            return False

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

    # ---- ASS 원래 스타일 ---------------------------------------------------
    def _draw_ass(self, cr, video_rect):
        """ASS 대사를 스크립트 좌표(PlayRes)에서 영상 영역으로 옮겨 원래 글꼴·색·위치로 그립니다."""
        vx, vy, vw, vh = video_rect
        stacked = {}   # 정렬 위치별로 이미 쓴 높이 (\pos 없는 대사가 겹치지 않게 쌓음)
        for script, ev in self._ass:
            px, py = script.play_res
            sx, sy = vw / px, vh / py
            layout = PangoCairo.create_layout(cr)
            layout.set_markup(_ass_markup(ev, sy * self.font_scale), -1)
            col = (ev.alignment - 1) % 3
            layout.set_alignment((Pango.Alignment.LEFT, Pango.Alignment.CENTER, Pango.Alignment.RIGHT)[col])
            ax, ay, h_align, v_align = anchor_point(ev, script.play_res)
            if ev.pos is None:
                # 여백 사이 상자 안에서 줄바꿈하고 정렬합니다.
                box_w = max(1.0, (px - ev.margin_l - ev.margin_r) * sx)
                layout.set_width(int(box_w * Pango.SCALE))
                layout.set_wrap(Pango.WrapMode.WORD_CHAR)
                _ink, logical = layout.get_pixel_extents()
                x = vx + ev.margin_l * sx
                row = (ev.alignment - 1) // 3
                used = stacked.get(ev.alignment, 0.0)
                y = vy + ay * sy - v_align * logical.height + (-used if row == 0 else used if row == 2 else 0)
                stacked[ev.alignment] = used + logical.height
            else:
                _ink, logical = layout.get_pixel_extents()
                x = vx + ax * sx - h_align * logical.width - logical.x
                y = vy + ay * sy - v_align * logical.height
            self._paint_ass_layout(cr, layout, ev, x, y, sy, logical)

    def _paint_ass_layout(self, cr, layout, ev, x, y, sy, logical):
        outline = max(0.0, ev.outline * sy * self.font_scale)
        shadow = max(0.0, ev.shadow * sy * self.font_scale)
        cr.save()
        if ev.style.border_style == 3:
            # 불투명 상자: 외곽선 색으로 글자 뒤를 채움
            pad = max(outline, 2.0)
            r, g, b, a = ev.outline_color
            cr.set_source_rgba(r, g, b, a)
            cr.rectangle(x + logical.x - pad, y + logical.y - pad, logical.width + 2 * pad, logical.height + 2 * pad)
            cr.fill()
        else:
            if shadow > 0:
                r, g, b, a = ev.back_color
                cr.move_to(x + shadow, y + shadow)
                PangoCairo.layout_path(cr, layout)
                cr.set_source_rgba(r, g, b, a)
                if outline > 0:
                    cr.set_line_width(outline * 2)
                    cr.set_line_join(1)
                    cr.stroke_preserve()
                cr.fill()
                cr.new_path()
            if outline > 0:
                r, g, b, a = ev.outline_color
                cr.move_to(x, y)
                PangoCairo.layout_path(cr, layout)
                cr.set_source_rgba(r, g, b, a)
                cr.set_line_width(outline * 2)
                cr.set_line_join(1)
                cr.stroke()
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)   # 글자 색은 마크업(런별 색·투명도)으로
        cr.restore()


def _ass_markup(event, scale):
    """AssEvent의 런들을 Pango 마크업으로 (글꼴 크기는 화면 픽셀로 환산)"""
    parts = []
    for run in event.runs:
        r, g, b, a = run.color
        size_px = max(6.0, run.size * scale)
        attrs = [f"font_family='{GLib.markup_escape_text(run.font or 'Sans')}, {FONT_FAMILY}'",
                 f"size='{int(size_px * 0.85 * Pango.SCALE * 72 / 96)}'",
                 f"foreground='#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'",
                 f"fgalpha='{max(1, int(round(a * 100)))}%'"]
        if run.bold:
            attrs.append("weight='bold'")
        if run.italic:
            attrs.append("style='italic'")
        if run.underline:
            attrs.append("underline='single'")
        if run.strikeout:
            attrs.append("strikethrough='true'")
        parts.append(f"<span {' '.join(attrs)}>{GLib.markup_escape_text(run.text)}</span>")
    return "".join(parts)

