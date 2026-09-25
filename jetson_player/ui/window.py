"""메인 플레이어 창: 상태 초기화, 키보드 단축키, 종료 처리 (기능은 mixin 모듈에 분리)"""
import logging
import os
import sys
import threading

from gi.repository import GLib, Gdk, Gst, Gtk

from ..mpris import start_mpris
from ..settings import settings
from ..shortcuts import find_shortcut
from ..media.gst_setup import build_hw_video_output, enable_x11_compositor_bypass, optimize_gstreamer_ranks
from ..storage import bookmark_cache, history_cache, hw_cache, resume_cache
from ..library import is_playlist_file
from ..youtube import is_youtube_url
from .remote import RemoteMixin
from .youtube import YouTubeMixin
from .features import FeaturesMixin
from .library import LibraryMixin
from .playlist import PlaylistPanelMixin
from .controls import ControlsMixin
from .layout import LayoutMixin
from .playback import PlaybackMixin
from .subtitles import SubtitlesMixin
from .menu import MenuMixin
from .timeline import TimelineMixin
from .ai import AiSubtitlesMixin
from .viewing import ViewingMixin
from .state import ControlStateMixin
from .search import DialogueSearchMixin
from .network import NetworkMixin
from .watch import FolderWatchMixin
from .mini import MiniPlayerMixin

log = logging.getLogger(__name__)


class JetsonSignageFlexiblePlayer(
    ControlStateMixin,
    RemoteMixin,
    YouTubeMixin,
    FeaturesMixin,
    LibraryMixin,
    PlaylistPanelMixin,
    ControlsMixin,
    LayoutMixin,
    PlaybackMixin,
    SubtitlesMixin,
    MenuMixin,
    TimelineMixin,
    AiSubtitlesMixin,
    ViewingMixin,
    DialogueSearchMixin,
    NetworkMixin,
    FolderWatchMixin,
    MiniPlayerMixin,
    Gtk.Window,
):
    """Jetson 영상 플레이어 메인 창. 기능별 메서드는 각 mixin 모듈에 있고, 공유 상태는 __init__에서 초기화합니다."""

    def __init__(self, input_path=None):
        super().__init__(title="Jetson Video Player")
        
        # [필수] 하드웨어 가속 랭크 최적화 보장
        optimize_gstreamer_ranks()

        # 1. 플레이어 창 설정 (일반 데스크탑 창 모드로 시작, F 키로 전체화면 전환)
        self.set_decorated(True)
        self.set_default_size(settings.get("window_width"), settings.get("window_height"))
        self.set_position(Gtk.WindowPosition.CENTER)
        
        # 이벤트 연결 (종료, 키보드 및 마우스 감지)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key_press)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.connect("motion-notify-event", self.on_mouse_motion)
        self.connect("button-press-event", self.on_window_button_press)
        # 진행바 밖에서 버튼을 놓아도 드래그 상태가 남지 않도록 창 전체에서 한 번 더 받습니다.
        self.connect("button-release-event", self.on_window_button_release)

        # 드래그 앤 드롭 지원 (동영상, 폴더, 자막 파일)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.on_drag_data_received)

        # 2. 입력 경로 타입(폴더 vs 파일 vs 유튜브 링크)을 분석하여 재생 목록 구성
        self.input_path = input_path
        self.playlist = []
        self.current_index = 0
        self.is_single_file_mode = False
        self.xid = None
        self.initial_yt_url = None
        if self.input_path:
            if is_youtube_url(self.input_path):
                self.initial_yt_url = self.input_path
                self.input_path = None
            elif not self.build_playlist():
                sys.exit(1)

        # UI/재생 상태
        self.is_playing = False
        self.is_fullscreen = False
        self.is_video_only = False
        self.is_mini = False
        self.is_keep_above = False
        self.sidebar_was_visible = True
        self.main_paned = None
        self.sidebar_width = settings.get("sidebar_width")
        self.is_adjusting_paned = False
        self.is_wrap_enabled = False
        self.r_text = None
        self.wrap_button = None
        self.is_destroyed = False
        self._bg_checker_started = False
        self.is_seeking = False
        self._seek_scale = None
        self.duration_ns = 0
        self.tree_store = None
        self.playlist_treeview = None
        self.playlist_tree_iters = {}
        self.decoder_names = set()
        self.video_sink = None
        self.stats_ticks = 0
        self.last_dropped_frames = 0
        self.last_ui_pos_sec = -1
        self.retry_counts = {}
        self.max_retries = 2

        # 마우스 커서 숨김 제어 상태
        self.cursor_hide_timer_id = None
        self.is_cursor_hidden = False

        # 재생 속도(Playback Speed/Rate) 상태 변수
        self.playback_rate = 1.0
        self.rate_applied_on_preroll = False
        self.speed_button = None
        self.speed_popover = None
        self.fs_speed_button = None

        # 볼륨 및 음소거 상태
        self.is_muted = False
        self.pre_mute_volume = 100
        self.mute_btn = None
        self.fs_mute_btn = None

        # 재생 모드 (all: 전체 반복, one: 1곡 반복, none: 순차 후 정지, shuffle: 셔플 무작위)
        self.repeat_mode = settings.get("repeat_mode")
        self.repeat_btn = None

        # 마우스 단일/더블 클릭 제어 타이머
        self.click_timer_id = None

        # 오디오 트랙 상태
        self.current_audio_track = 0
        self.n_audio_tracks = 0

        # 미디어 정보 HUD 및 빈 화면 안내
        self.hud_box = None
        self.hud_label = None
        self.is_hud_visible = False
        self.placeholder_box = None

        # YouTube 영상 버퍼링/스트리밍 오버레이 위젯 상태
        self.yt_loading_box = None
        self.yt_spinner = None
        self.yt_loading_title = None
        self.yt_loading_progress = None
        self.yt_loading_status = None

        # A-B 구간 반복 상태
        self.ab_repeat_a = None
        self.ab_repeat_b = None
        self.is_ab_repeat_active = False
        self.ab_badge = None

        # 오디오/비디오(AV) 싱크 미세 조절 상태
        self.av_sync_offset_ms = 0
        self.current_asink = None

        # 스마트폰 웹 리모컨 서버 상태
        self.web_server = None
        self.web_server_thread = None
        self.web_port = 8888
        self.remote_url = ""
        self._remote_status_lock = threading.Lock()
        self._remote_status = {}
        self._remote_groups_cache = None
        self._remote_playlist_paths = []           # HTTP 스레드용 재생목록 사본
        self._remote_thumb_files = ({}, [], None)   # HTTP 스레드용 현재 영상 썸네일 목록
        self.remote_auth = None
        self.remote_broker = None
        self.mpris = None

        # 검색 필터 텍스트
        self.search_text = ""
        # "다음에 재생" 대기열 (파일 경로 목록, 정렬/목록 변경에도 유지)
        self.play_queue = []
        self.search_entry = None

        # 전체화면 플로팅 컨트롤 바 및 OSD 상태 변수
        self.fs_controls_box = None
        self.is_fs_controls_visible = False
        self.is_mouse_over_fs_controls = False
        self.is_popover_open = False
        self.osd_box = None
        self.osd_label = None
        self.osd_timer_id = None
        self.fs_progress_scale = None
        self.fs_position_label = None
        self.fs_duration_label = None
        self.fs_play_button = None
        self.fs_sub_button = None
        self.fs_volume_scale = None

        # 다중 자막(Subtitle) 상태 변수 초기화
        self.subtitles_enabled = True
        self.has_subtitles = False
        self.single_sub_mode = True  # 기본 1개(한국어 우선)만 활성화 (화면 가림 방지)
        self.available_subtitles = []  # list of dicts: {'path', 'label', 'color', 'events'}
        self.active_subtitle_indices = set()  # set of int indices
        self.pending_seek_ns = 0
        self.last_known_pos_ns = 0  # 자막 전환 시 0초 튕김 방지용 백업 위치
        self.is_updating_sub_checkboxes = False  # 모두 선택/해제 일괄 변경 락
        self.subtitle_font_scale = settings.get("subtitle_font_scale")  # 자막 크기 스케일 (0.6 ~ 1.6)
        self.subtitle_offset_ms = 0  # 자막 싱크 오프셋 (ms 단위, 음수: 빠르게, 양수: 느리게)
        self.scale_label = None
        self.sync_label = None
        self.sub_popover = None
        # 컨테이너 내장 자막(MKV 등) 상태: 외부 자막이 없을 때 playbin이 자동 표시하는 트랙
        self.n_embedded_text = 0
        self.embedded_subs_enabled = settings.get("embedded_subs_enabled")
        self.subtitle_overlays = []  # 현재 파이프라인의 textoverlay/subtitleoverlay (silent 토글용)
        self.embedded_track = None  # 내장 자막 텍스트 (appsink로 수신, 오버레이로 표시)
        self.ai_job = None     # AI 자막 생성 작업 (whisper.cpp)
        # 시청 경험: 화면 회전 / 수면 타이머 / 자동 재생 카운트다운 / 야간 모드 요소
        self.video_rotation = "identity"
        self.sleep_minutes = 0
        self.sleep_deadline = None
        self.sleep_timer_id = None
        self.sleep_fading = False
        self.autoplay_action = None
        self.autoplay_timer_id = None
        self.night_elements = (None, None)
        self.ai_status = None  # (상태 문구, 진행률)
        self.translate_job = None    # 자막 번역 작업
        self.translate_status = None
        self.auto_ai_paths = set()  # 재생되면 AI 자막을 자동 생성할 영상 (YouTube 다운로드)

        # 3. 비디오가 임베딩될 GtkGLSink 네이티브 OpenGL 위젯 생성 (Totem 공식 아키텍처)
        # JVP_VIDEO_SINK=gtk: OpenGL 없이 gtksink 사용 (가상 디스플레이 테스트, GL 문제 진단용)
        use_gl = os.environ.get("JVP_VIDEO_SINK", "gl") != "gtk"
        self.gtk_sink = Gst.ElementFactory.make("gtkglsink", "gtk_sink") if use_gl else None
        if self.gtk_sink:
            self.video_sink_bin = Gst.ElementFactory.make("glsinkbin", "glsinkbin")
            self.video_sink_bin.set_property("sink", self.gtk_sink)
            self.video_widget = self.gtk_sink.get_property("widget")
            self.video_sink = self.video_sink_bin
        else:
            self.gtk_sink = Gst.ElementFactory.make("gtksink", "gtk_sink")
            self.video_widget = self.gtk_sink.get_property("widget") if self.gtk_sink else Gtk.DrawingArea()
            self.video_sink = self.gtk_sink
        # playbin에 연결할 최종 영상 출력 (NVDEC 하드웨어 디코딩 유지를 위한 nvvidconv 포함)
        self.video_output = build_hw_video_output(self.video_sink)
        self.using_hw_video_output = False
        self.hw_decode_expected = None  # 현재 영상의 NVDEC 지원 여부 (None: 판별 불가)
        self.hw_output_disabled = set()  # HW 출력 경로가 실패한 파일 (호환 경로로 재생)

        self.video_widget.set_hexpand(True)
        self.video_widget.set_vexpand(True)
        self.video_widget.set_size_request(640, 480)
        self.video_widget.connect("realize", self.on_realize)

        # 4. GStreamer 핵심 파이프라인 변수 초기화 (UI 생성/설정 복원 중 핸들러가 참조하므로 먼저 정의)
        self.pipeline = None
        self.bus = None

        # 설정 복원 중에는 OSD 알림을 띄우지 않습니다.
        self._restoring_settings = True
        self.is_maximized = False
        self.connect("window-state-event", self._on_window_state_event)

        self.build_ui()
        self._apply_saved_settings()
        # 정렬 버튼 표시 (M3U 재생목록은 파일에 적힌 순서를 유지)
        self.apply_playlist_sort(resort=not is_playlist_file(self.input_path or ""))

        # 재생 위치와 UI 상태 갱신 (250ms 주기로 매끄러운 진행바 보장)
        self.position_timer_id = GLib.timeout_add(250, self.update_playback_ui)
        # 웹 리모컨 상태 스냅샷 갱신 (HTTP 스레드는 이 스냅샷만 읽음)
        self._refresh_remote_status()
        self.remote_status_timer_id = GLib.timeout_add(500, self._refresh_remote_status)
        # 이어보기/북마크/기록을 10초마다 디스크에 저장 (비정상 종료 시 유실 방지)
        self.cache_flush_timer_id = GLib.timeout_add_seconds(10, self._flush_caches)

        # 스마트폰 웹 리모컨 서버 자동 기동
        self.start_web_remote_server()
        # 키보드 미디어 키 / 시스템 미디어 컨트롤 (MPRIS2)
        self.mpris = start_mpris(self)

        # CLI 인자로 유튜브 링크가 입력된 경우 바로 받아서 재생
        if self.initial_yt_url:
            init_url = self.initial_yt_url
            GLib.idle_add(lambda: self.start_youtube_stream(init_url, quality="best"))

    def _flush_caches(self):
        if self.is_destroyed:
            return False
        for cache in (resume_cache, bookmark_cache, history_cache):
            cache.save()
        self._capture_settings()
        settings.save()
        return True

    def _apply_saved_settings(self):
        """저장된 사용자 설정을 UI와 재생 상태에 적용합니다 (build_ui 이후 호출)."""
        self.volume_scale.set_value(settings.get("volume"))
        if settings.get("muted"):
            self.toggle_mute()
        self.set_repeat_mode(self.repeat_mode)
        if not settings.get("sidebar_visible"):
            self.sidebar.set_visible(False)
        if settings.get("window_maximized"):
            self.maximize()
        if settings.get("hud_visible"):
            GLib.idle_add(lambda: (self.toggle_hud() if not self.is_hud_visible else None, False)[1])
        GLib.idle_add(self._finish_restoring_settings)

    def _finish_restoring_settings(self):
        self._restoring_settings = False
        return False

    def _on_window_state_event(self, _widget, event):
        self.is_maximized = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
        return False

    def _capture_settings(self):
        """현재 UI/재생 상태를 설정 객체에 기록합니다 (저장은 settings.save())."""
        volume = self.pre_mute_volume if self.is_muted else self.volume_scale.get_value()
        sidebar_visible = self.sidebar_was_visible if self.is_video_only else self.sidebar.get_visible()
        values = dict(
            volume=volume,
            muted=self.is_muted,
            subtitle_font_scale=self.subtitle_font_scale,
            repeat_mode=self.repeat_mode,
            sidebar_width=self.sidebar_width,
            sidebar_visible=sidebar_visible,
            hud_visible=self.is_hud_visible,
            embedded_subs_enabled=self.embedded_subs_enabled,
        )
        if not self.is_video_only and not self.is_maximized:
            width, height = self.get_size()
            values.update(window_width=width, window_height=height)
        if not self.is_video_only:
            values["window_maximized"] = self.is_maximized
        settings.update(**values)

    def on_realize(self, widget):
        """GTK 창의 리소스가 로드되었을 때 영상 재생을 시작하고 백그라운드 검사기를 가동합니다."""
        if self.pipeline is not None:
            return
        log.info("🖥️ GUI 창 준비 완료. 영상 재생을 시작합니다.")
        
        top_window = self.get_window()
        if top_window:
            enable_x11_compositor_bypass(top_window)

        if self.playlist:
            self.play_current_video()
            self.start_folder_watch()
        self.start_background_hw_checker()

    def on_key_press(self, widget, event):
        """키보드 입력: 단축키 테이블(jetson_player/shortcuts.py)에서 찾아 실행합니다."""
        keyname = Gdk.keyval_name(event.keyval)
        state = event.state

        # 검색창/URL 입력창에 입력 중일 때는 단축키가 글자를 가로채지 않도록 입력창에 그대로 전달합니다.
        # (Esc도 입력창의 기본 동작(검색어 지우기)에 맡겨 앱이 종료되지 않게 합니다.)
        if isinstance(self.get_focus(), Gtk.Entry):
            return False

        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shortcut = find_shortcut(keyname, is_shift, is_ctrl)
        if shortcut is None:
            return False
        handler = getattr(self, shortcut.action, None)
        if handler is None:
            return False
        handler(*shortcut.args)
        return True

    def handle_escape(self):
        """Esc: 전체화면이면 창 모드로, 아니면 종료합니다."""
        if getattr(self, "is_mini", False):
            self.exit_mini_player()
        elif self.is_fullscreen or self.is_video_only:
            self.toggle_fullscreen()
        else:
            self.quit_player()

    def quit_player(self):
        log.info("⏹ 프로그램 종료.")
        self.on_destroy(self)

    def on_destroy(self, widget):
        self.is_destroyed = True
        self.stop_folder_watch()
        for job_name in ("thumb_job", "scene_job", "ai_job", "translate_job"):
            job = getattr(self, job_name, None)
            if job:
                job.cancel()
        try:
            self.stop_web_remote_server()
            hw_cache.save()
            resume_cache.save()
            bookmark_cache.save()
            history_cache.save()
            self._capture_settings()
            settings.save()
        except Exception as e:
            log.warning(f"⚠️ 종료 시 저장 실패: {e}")

        for timer_name in ("sleep_timer_id", "autoplay_timer_id"):
            timer_id = getattr(self, timer_name, None)
            if timer_id:
                GLib.source_remove(timer_id)
                setattr(self, timer_name, None)

        if getattr(self, "cache_flush_timer_id", None):
            try:
                GLib.source_remove(self.cache_flush_timer_id)
            except Exception:
                pass
            self.cache_flush_timer_id = None

        if getattr(self, "remote_status_timer_id", None):
            try:
                GLib.source_remove(self.remote_status_timer_id)
            except Exception:
                pass
            self.remote_status_timer_id = None

        if getattr(self, "click_timer_id", None):
            try:
                GLib.source_remove(self.click_timer_id)
            except Exception:
                pass
            self.click_timer_id = None

        if getattr(self, "cursor_hide_timer_id", None):
            try:
                GLib.source_remove(self.cursor_hide_timer_id)
            except Exception:
                pass
            self.cursor_hide_timer_id = None
        self.show_cursor()

        if getattr(self, "osd_timer_id", None):
            try:
                GLib.source_remove(self.osd_timer_id)
            except Exception:
                pass
            self.osd_timer_id = None


        if getattr(self, "position_timer_id", None):
            try:
                GLib.source_remove(self.position_timer_id)
            except Exception:
                pass
            self.position_timer_id = None
        if self.bus is not None:
            try:
                self.bus.remove_signal_watch()
            except Exception:
                pass
            self.bus = None
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        if Gtk.main_level() > 0:
            Gtk.main_quit()
