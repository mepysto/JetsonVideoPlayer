"""메인 창 위젯 트리 구성"""
import os

from gi.repository import Gdk, Gtk, Pango

from ..storage import resume_cache
from .subtitle_overlay import SubtitleOverlay


STYLE_CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")


class LayoutMixin:
    def build_ui(self):
        """Jetson EGL 출력과 충돌하지 않는 네이티브 GTK 플레이어 UI를 구성합니다."""
        provider = Gtk.CssProvider()
        provider.load_from_path(STYLE_CSS_PATH)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        def make_topbar_sep():
            sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
            sep.get_style_context().add_class("topbar-sep")
            return sep

        self.topbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.topbar.get_style_context().add_class("topbar")
        self.topbar.set_border_width(6)
        
        brand = Gtk.Label(label="JETSON VIDEO PLAYER")
        brand.get_style_context().add_class("brand")
        self.topbar.pack_start(brand, False, False, 4)
        self.topbar.pack_start(make_topbar_sep(), False, False, 2)

        # 상단 빠른 조작 툴바 - 그룹 1: 파일 / 폴더 / 최근 열기
        open_file_btn = Gtk.Button(label="📂 파일")
        open_file_btn.set_tooltip_text("동영상 파일 열기 (Ctrl+O)")
        open_file_btn.connect("clicked", lambda _b: self.open_file_dialog())
        self.topbar.pack_start(open_file_btn, False, False, 0)

        open_dir_btn = Gtk.Button(label="📁 폴더")
        open_dir_btn.set_tooltip_text("동영상 폴더 열기 (Ctrl+Shift+O)")
        open_dir_btn.connect("clicked", lambda _b: self.open_folder_dialog())
        self.topbar.pack_start(open_dir_btn, False, False, 0)

        recent_btn = Gtk.Button(label="🕒 최근")
        recent_btn.set_tooltip_text("최근 재생한 영상/폴더 열기")
        recent_btn.connect("clicked", lambda _b: self.show_history_popover(recent_btn))
        self.topbar.pack_start(recent_btn, False, False, 0)

        self.yt_btn = Gtk.Button(label="▶️ 유튜브")
        self.yt_btn.set_tooltip_text("유튜브 영상 다운로드 / 바로 재생")
        self.yt_btn.connect("clicked", lambda _b: self.show_youtube_popover(self.yt_btn))
        self.topbar.pack_start(self.yt_btn, False, False, 0)

        self.topbar.pack_start(make_topbar_sep(), False, False, 2)

        # 그룹 2: 재생 모드 (자주 쓰지 않는 기능은 우측 ⋯ 메뉴로 정리)
        self.repeat_btn = Gtk.Button(label="🔁")
        self.repeat_btn.set_tooltip_text("재생 모드 (전체반복/1곡반복/정지/셔플) (Shift+R)")
        self.repeat_btn.connect("clicked", lambda _b: self.cycle_repeat_mode())
        self.topbar.pack_start(self.repeat_btn, False, False, 0)

        self.topbar.pack_start(make_topbar_sep(), False, False, 2)

        self.now_playing_label = Gtk.Label(xalign=0)
        self.now_playing_label.set_ellipsize(3)
        self.now_playing_label.get_style_context().add_class("now-playing")
        self.topbar.pack_start(self.now_playing_label, True, True, 8)

        self.more_button = Gtk.Button(label="⋯")
        self.more_button.get_style_context().add_class("more-btn")
        self.more_button.set_tooltip_text("더 보기: 북마크, 캡처, 리모컨, HUD, AI 자막, 수면 타이머, 화면 설정, 도움말")
        self.more_button.connect("clicked", lambda b: self.show_more_menu(b))

        playlist_toggle = Gtk.Button(label="☷  재생목록")
        playlist_toggle.set_tooltip_text("재생목록 열기/닫기")
        playlist_toggle.connect("clicked", self.on_playlist_toggle)
        self.topbar.pack_end(playlist_toggle, False, False, 0)
        self.topbar.pack_end(self.more_button, False, False, 0)

        close_button = Gtk.Button(label="✕")
        close_button.set_tooltip_text("종료 (Q / Esc)")
        close_button.connect("clicked", self.on_destroy)
        self.topbar.pack_end(close_button, False, False, 0)
        root.pack_start(self.topbar, False, False, 0)

        self.main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)

        # 비디오 위젯 및 오버레이(OSD, 전체화면 플로팅 컨트롤) 컨테이너
        self.video_container = Gtk.Overlay()

        # 비디오 이벤트 박스 (마우스 휠 Scroll Seek 및 화면 클릭 격리)
        self.video_event_box = Gtk.EventBox()
        self.video_event_box.set_visible_window(False)
        self.video_event_box.add_events(
            Gdk.EventMask.SCROLL_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.video_event_box.connect("scroll-event", self.on_video_scroll_event)
        self.video_event_box.connect("button-press-event", self.on_video_button_press)
        self.video_event_box.add(self.video_widget)
        self.video_container.add(self.video_event_box)

        # 외부/AI 자막 오버레이 (클릭은 아래 영상 영역으로 통과)
        self.subtitle_overlay = SubtitleOverlay(self._subtitle_position_ms)
        self.video_container.add_overlay(self.subtitle_overlay)
        self.video_container.set_overlay_pass_through(self.subtitle_overlay, True)

        # 0) 플레이스홀더 (빈 화면 안내)
        self.placeholder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.placeholder_box.set_halign(Gtk.Align.CENTER)
        self.placeholder_box.set_valign(Gtk.Align.CENTER)
        ph_icon = Gtk.Label()
        ph_icon.set_markup("<span font='54'>🎬</span>")
        ph_title = Gtk.Label()
        ph_title.set_markup("<span font='16' weight='bold' color='#dce2ec'>재생할 동영상 또는 폴더를 드래그 앤 드롭하세요</span>")
        ph_sub = Gtk.Label(label="상단의 빠른 조작 바 또는 아래 버튼으로 즉시 선택할 수 있습니다 (단축키: Ctrl+O)")
        ph_sub.get_style_context().add_class("muted")

        ph_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ph_btn_box.set_halign(Gtk.Align.CENTER)

        ph_open_file = Gtk.Button(label="📂 동영상 파일 열기")
        ph_open_file.get_style_context().add_class("ph-btn-primary")
        ph_open_file.connect("clicked", lambda _b: self.open_file_dialog())

        ph_open_dir = Gtk.Button(label="📁 폴더 열기")
        ph_open_dir.get_style_context().add_class("ph-btn-sub")
        ph_open_dir.connect("clicked", lambda _b: self.open_folder_dialog())

        ph_open_yt = Gtk.Button(label="▶️ 유튜브 영상 재생")
        ph_open_yt.get_style_context().add_class("ph-btn-sub")
        ph_open_yt.connect("clicked", lambda _b: self.show_youtube_popover(ph_open_yt))

        ph_btn_box.pack_start(ph_open_file, False, False, 0)
        ph_btn_box.pack_start(ph_open_dir, False, False, 0)
        ph_btn_box.pack_start(ph_open_yt, False, False, 0)

        self.placeholder_box.pack_start(ph_icon, False, False, 0)
        self.placeholder_box.pack_start(ph_title, False, False, 0)
        self.placeholder_box.pack_start(ph_sub, False, False, 0)
        self.placeholder_box.pack_start(ph_btn_box, False, False, 4)

        # 이어보기 카드 (최근 시청 중이던 영상)
        self.resume_cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.resume_cards_box.set_margin_top(10)
        self.placeholder_box.pack_start(self.resume_cards_box, False, False, 0)
        self.placeholder_box.set_no_show_all(True)
        self.video_container.add_overlay(self.placeholder_box)

        # 0-1) YouTube 영상 고속 버퍼링 및 로딩 오버레이 (화면 중앙)
        self.yt_loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.yt_loading_box.get_style_context().add_class("yt-overlay-box")
        self.yt_loading_box.set_halign(Gtk.Align.CENTER)
        self.yt_loading_box.set_valign(Gtk.Align.CENTER)
        self.yt_loading_box.set_size_request(420, -1)

        yt_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        yt_header_box.set_halign(Gtk.Align.CENTER)
        self.yt_spinner = Gtk.Spinner()
        self.yt_spinner.set_size_request(24, 24)
        yt_icon_lbl = Gtk.Label()
        yt_icon_lbl.set_markup("<span font='22'>📺</span>")
        yt_badge_lbl = Gtk.Label()
        yt_badge_lbl.set_markup("<span font='14' weight='bold' color='#ff4e4e'>YouTube</span> <span font='14' weight='bold' color='#ffffff'>다운로드</span>")
        yt_header_box.pack_start(yt_icon_lbl, False, False, 0)
        yt_header_box.pack_start(yt_badge_lbl, False, False, 0)
        yt_header_box.pack_start(self.yt_spinner, False, False, 4)

        self.yt_loading_title = Gtk.Label()
        self.yt_loading_title.set_markup("<span font='13' weight='bold' color='#e9ff5b'>영상 정보를 불러오는 중...</span>")
        self.yt_loading_title.set_line_wrap(True)
        self.yt_loading_title.set_max_width_chars(38)
        self.yt_loading_title.set_justify(Gtk.Justification.CENTER)

        self.yt_loading_progress = Gtk.ProgressBar()
        self.yt_loading_progress.set_fraction(0.0)
        self.yt_loading_progress.get_style_context().add_class("yt-progress")

        self.yt_loading_status = Gtk.Label()
        self.yt_loading_status.set_markup("<span font='11' color='#8f98a8'>⬇️ 다운로드 준비 중...</span>")

        self.yt_loading_box.pack_start(yt_header_box, False, False, 0)
        self.yt_loading_box.pack_start(self.yt_loading_title, False, False, 2)
        self.yt_loading_box.pack_start(self.yt_loading_progress, False, False, 4)
        self.yt_loading_box.pack_start(self.yt_loading_status, False, False, 0)
        self.yt_loading_box.set_no_show_all(True)
        self.video_container.add_overlay(self.yt_loading_box)

        # 1) OSD 라벨 오버레이 (화면 상단 중앙)
        self.osd_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.osd_box.get_style_context().add_class("osd-box")
        self.osd_box.set_halign(Gtk.Align.CENTER)
        self.osd_box.set_valign(Gtk.Align.START)
        self.osd_label = Gtk.Label()
        self.osd_label.get_style_context().add_class("osd-text")
        self.osd_box.add(self.osd_label)
        self.osd_box.set_no_show_all(True)
        self.video_container.add_overlay(self.osd_box)

        # 2) 미디어 정보 및 실시간 하드웨어 HUD 오버레이 (화면 좌측 상단)
        self.hud_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.hud_box.get_style_context().add_class("hud-box")
        self.hud_box.set_halign(Gtk.Align.START)
        self.hud_box.set_valign(Gtk.Align.START)
        self.hud_box.set_margin_start(16)
        self.hud_box.set_margin_top(16)
        self.hud_label = Gtk.Label(xalign=0)
        self.hud_label.get_style_context().add_class("hud-text")
        self.hud_box.add(self.hud_label)
        self.hud_box.set_no_show_all(True)
        self.video_container.add_overlay(self.hud_box)

        # 2-1) 다음 영상 자동 재생 카운트다운 카드 (우측 하단)
        self.video_container.add_overlay(self.build_autoplay_overlay())

        # 3) 전체화면 플로팅 컨트롤 바 오버레이 (화면 하단)
        self.fs_controls_box = self.build_fs_controls()
        self.fs_controls_box.set_halign(Gtk.Align.FILL)
        self.fs_controls_box.set_valign(Gtk.Align.END)
        self.fs_controls_box.set_no_show_all(True)
        self.video_container.add_overlay(self.fs_controls_box)

        self.main_paned.pack1(self.video_container, resize=True, shrink=False)
        self.sidebar = self.build_playlist_panel()
        self.main_paned.pack2(self.sidebar, resize=True, shrink=False)
        self.main_paned.connect("notify::position", self.on_paned_notify_position)
        self.main_paned.connect("size-allocate", self.on_paned_size_allocate)
        root.pack_start(self.main_paned, True, True, 0)

        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.controls.get_style_context().add_class("controls")
        self.controls.set_border_width(10)

        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.position_label = Gtk.Label(label="00:00")
        self.position_label.get_style_context().add_class("muted")
        self.progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.progress_scale.set_draw_value(False)
        self.progress_scale.set_hexpand(True)
        self.progress_scale.connect("button-press-event", self.on_seek_start)
        self.progress_scale.connect("button-release-event", self.on_seek_end)
        self.progress_scale.connect("change-value", self.on_scale_change_value)
        self.setup_timeline_interactions(self.progress_scale)

        # A-B 구간 반복 상시 시각 배지
        self.ab_badge = Gtk.Button(label="")
        self.ab_badge.get_style_context().add_class("ab-badge")
        self.ab_badge.set_tooltip_text("A-B 구간 반복 활성화 중 (클릭 시 즉시 해제)")
        self.ab_badge.connect("clicked", lambda _b: self.clear_ab_repeat())
        self.ab_badge.set_no_show_all(True)
        self.ab_badge.hide()

        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.get_style_context().add_class("muted")
        timeline.pack_start(self.position_label, False, False, 0)
        timeline.pack_start(self.progress_scale, True, True, 0)
        timeline.pack_start(self.ab_badge, False, False, 4)
        timeline.pack_start(self.make_time_toggle(self.duration_label), False, False, 0)
        self.controls.pack_start(timeline, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        prev_button = Gtk.Button(label="⏮")
        prev_button.set_tooltip_text("이전 영상 (P)")
        prev_button.connect("clicked", lambda _button: self.play_prev_video())
        self.play_button = Gtk.Button(label="Ⅱ")
        self.play_button.get_style_context().add_class("primary")
        self.play_button.set_tooltip_text("재생/일시정지 (Space)")
        self.play_button.connect("clicked", lambda _button: self.toggle_play_pause())
        next_button = Gtk.Button(label="⏭")
        next_button.set_tooltip_text("다음 영상 (N)")
        next_button.connect("clicked", lambda _button: self.play_next_video())
        rewind_button = Gtk.Button(label="↶ 10")
        rewind_button.set_tooltip_text("10초 뒤로 (←)")
        rewind_button.connect("clicked", lambda _button: self.seek_relative(-10))
        forward_button = Gtk.Button(label="10 ↷")
        forward_button.set_tooltip_text("10초 앞으로 (→)")
        forward_button.connect("clicked", lambda _button: self.seek_relative(10))
        for button in (prev_button, rewind_button, self.play_button, forward_button, next_button):
            actions.pack_start(button, False, False, 0)

        # 속도 조절 버튼 ([-] 1.0x [+])
        speed_down_btn = Gtk.Button(label="˗")
        speed_down_btn.set_tooltip_text("재생 속도 감소 (단축키: Down 또는 a)")
        speed_down_btn.connect("clicked", lambda _b: self.step_playback_rate(-0.25))
        actions.pack_start(speed_down_btn, False, False, 0)

        self.speed_button = Gtk.Button(label="1.0x")
        self.speed_button.get_style_context().add_class("speed-btn")
        self.speed_button.set_tooltip_text("재생 속도 설정 (단축키: Up/Down 또는 d/a, r: 1.0x)")
        self.speed_button.connect("clicked", self.on_speed_button_clicked)
        actions.pack_start(self.speed_button, False, False, 0)

        speed_up_btn = Gtk.Button(label="˖")
        speed_up_btn.set_tooltip_text("재생 속도 증가 (단축키: Up 또는 d)")
        speed_up_btn.connect("clicked", lambda _b: self.step_playback_rate(0.25))
        actions.pack_start(speed_up_btn, False, False, 0)

        spacer = Gtk.Box()
        actions.pack_start(spacer, True, True, 0)

        # 볼륨 및 음소거 버튼
        self.mute_btn = Gtk.Button(label="◖)))")
        self.mute_btn.set_tooltip_text("음소거 켜기/끄기 (M)")
        self.mute_btn.connect("clicked", lambda _b: self.toggle_mute())
        actions.pack_start(self.mute_btn, False, False, 2)

        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 200, 1)
        self.volume_scale.set_size_request(110, -1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_value(100)
        self.volume_scale.connect("value-changed", self._on_volume_scale_changed)
        actions.pack_start(self.volume_scale, False, False, 0)

        self.fullscreen_button = Gtk.Button(label="⛶")
        self.fullscreen_button.set_tooltip_text("영상만 전체화면 (F)")
        self.fullscreen_button.connect("clicked", lambda _button: self.toggle_fullscreen())
        actions.pack_end(self.fullscreen_button, False, False, 0)

        self.sub_button = Gtk.Button(label="💬 자막")
        self.sub_button.set_tooltip_text("자막 켜기/끄기 (S)")
        self.sub_button.connect("clicked", self.on_sub_button_clicked)
        actions.pack_end(self.sub_button, False, False, 4)

        self.controls.pack_start(actions, False, False, 0)
        root.pack_end(self.controls, False, False, 0)

        if not self.playlist and not getattr(self, "initial_yt_url", None):
            self.show_placeholder()

        self.refresh_playlist_ui()

    def show_placeholder(self):
        """대기 화면(열기 버튼 + 이어보기 카드)을 표시합니다."""
        if not getattr(self, "placeholder_box", None):
            return
        self.refresh_resume_cards()
        self.placeholder_box.set_no_show_all(False)
        self.placeholder_box.show_all()
        self.placeholder_box.set_no_show_all(True)

    def refresh_resume_cards(self):
        """최근 시청 중이던 영상을 진행률과 함께 카드로 표시합니다. 클릭하면 이어서 재생합니다."""
        box = getattr(self, "resume_cards_box", None)
        if box is None:
            return
        for child in box.get_children():
            box.remove(child)
        recent = resume_cache.recent_in_progress(limit=4)
        if not recent:
            return
        header = Gtk.Label(label="⏱️ 이어보기", xalign=0)
        header.get_style_context().add_class("resume-header")
        box.pack_start(header, False, False, 0)
        for path, pos_ns, dur_ns in recent:
            btn = Gtk.Button()
            btn.get_style_context().add_class("resume-card")
            btn.set_tooltip_text(path)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            title = Gtk.Label(label=os.path.basename(path), xalign=0)
            title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            title.set_max_width_chars(48)
            title.get_style_context().add_class("resume-title")
            inner.pack_start(title, False, False, 0)
            bar = Gtk.ProgressBar()
            bar.get_style_context().add_class("resume-progress")
            bar.set_fraction(max(0.0, min(1.0, pos_ns / dur_ns)) if dur_ns > 0 else 0.0)
            inner.pack_start(bar, False, False, 0)
            folder = os.path.basename(os.path.dirname(path))
            dur_str = f" / {self.format_time(dur_ns)}" if dur_ns > 0 else ""
            meta = Gtk.Label(label=f"{self.format_time(pos_ns)}{dur_str}  ·  📁 {folder}", xalign=0)
            meta.get_style_context().add_class("muted")
            inner.pack_start(meta, False, False, 0)
            btn.add(inner)
            btn.connect("clicked", lambda _b, p=path: self.load_path(p))
            box.pack_start(btn, False, False, 0)
