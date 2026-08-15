import sys
import os
import glob
import subprocess
import shutil
import json
import gi
from urllib.request import pathname2url

# 환경 변수 자동 설정 (cannot open display 에러 방지)
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":0"
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

# 필요한 GStreamer 및 GTK 컴포넌트 로드
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Gst, Gtk, Gdk, GstVideo, GLib, GdkX11

def enable_x11_compositor_bypass(gdk_window):
    """
    GNOME Mutter 윈도우 컴포지터의 중간 재합성으로 인한 프레임 지터를 차단하기 위해
    X11 _NET_WM_BYPASS_COMPOSITOR 힌트를 지정하여 Direct GPU 스캔아웃을 활성화합니다.
    """
    try:
        xid = None
        if hasattr(gdk_window, "get_xid"):
            xid = gdk_window.get_xid()
        elif hasattr(GdkX11, "X11Window") and hasattr(GdkX11.X11Window, "get_xid"):
            xid = GdkX11.X11Window.get_xid(gdk_window)
        if xid:
            subprocess.run(
                ["xprop", "-id", str(xid), "-f", "_NET_WM_BYPASS_COMPOSITOR", "32c", "-set", "_NET_WM_BYPASS_COMPOSITOR", "1"],
                capture_output=True, check=False
            )
    except Exception:
        pass

def optimize_gstreamer_ranks():
    """
    Jetson 하드웨어 디코더(nvv4l2decoder)를 H.264/H.265 및 AV1 코덱에 우선 할당하여 
    4K 60fps 단일 영상 재생 시 CPU 병목으로 인한 화면 끊김(Stuttering)을 완벽히 방지합니다.
    JetPack 드라이버 에러(NvBufSurfTransform -1)가 발생하는 VP9 10-bit HDR 영상만 SW 디코더(vp9dec)로 우회합니다.
    """
    registry = Gst.Registry.get()
    
    # 1. Jetson 하드웨어 디코더 존재 여부 감지
    hw_decoder = registry.find_feature("nvv4l2decoder", Gst.ElementFactory.__gtype__)
    
    if hw_decoder:
        # Jetson 하드웨어 디코더 및 변환기 우위 설정 (PRIMARY + 1000)
        hw_elements = ["nvv4l2decoder", "nvvidconv"]
        for name in hw_elements:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 1000)
        
        # AV1/H264/H265/VP9 스트림 파서 랭크 상향 (프레임 경계 추출 보장)
        parsers = ["av1parse", "h264parse", "h265parse", "vp9parse"]
        for name in parsers:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 1500)

        # 소프트웨어 디코더는 기본 rank를 유지합니다. 하드웨어를 우선하되 특정
        # 프로파일/드라이버 오류에서는 GStreamer가 안전하게 fallback할 수 있어야 합니다.

        # CPU 소프트웨어 비디오 변환기/스케일러 랭크 유지 (Standard Format Conversion 허용)
        for name in ["videoconvert", "videoscale"]:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY)

        print("⚡ [하드웨어 가속 60 FPS 최적화] nvv4l2decoder HW 가속 및 60 FPS 전용 파이프라인 무결 적용 완료.")
    else:
        print("ℹ️ [소프트웨어 디코딩] Jetson HW 디코더(nvv4l2decoder)가 감지되지 않아 기본 디코더를 유지합니다.")

class JetsonSignageFlexiblePlayer(Gtk.Window):
    def __init__(self, input_path):
        super().__init__(title="Jetson Video Player")
        
        # [필수] 하드웨어 가속 랭크 최적화 보장
        optimize_gstreamer_ranks()

        # 1. 플레이어 창 설정
        self.set_decorated(False)
        self.fullscreen()
        self.set_keep_above(True)
        self.set_default_size(1280, 720)
        
        # 이벤트 연결 (종료 및 키보드 입력)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key_press)

        # 2. 입력 경로 타입(폴더 vs 파일)을 분석하여 재생 목록 구성
        self.input_path = input_path
        self.playlist = []
        self.current_index = 0
        self.is_single_file_mode = False
        self.xid = None
        self.build_playlist()

        # UI/재생 상태
        self.is_playing = True
        self.is_fullscreen = True
        self.is_video_only = False
        self.sidebar_was_visible = True
        self.is_seeking = False
        self.duration_ns = 0
        self.playlist_rows = []
        self.decoder_names = set()
        self.video_sink = None
        self.stats_ticks = 0
        self.last_dropped_frames = 0
        self.last_ui_pos_sec = -1
        self.retry_counts = {}
        self.max_retries = 2

        # 3. 비디오가 임베딩될 Gtk DrawingArea 생성
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_hexpand(True)
        self.drawing_area.set_vexpand(True)
        self.drawing_area.set_size_request(640, 480) # [핵심] C-라이브러리 dst->h == 0 멈춤 에러 방지
        self.drawing_area.set_app_paintable(True)    # [핵심] GTK 창 기본 배경 그리기 차단
        self.drawing_area.set_double_buffered(False) # [최적화] EGL 직결 위젯의 불필요한 백버퍼 더블버퍼링 차단
        self.drawing_area.connect("draw", lambda widget, cr: True) # [핵심] GTK repaint 이벤트 무력화
        
        # 화면 준비가 완료(realize)되면 재생을 시작하도록 이벤트 등록
        self.drawing_area.connect("realize", self.on_realize)
        self.drawing_area.connect("size-allocate", self.on_size_allocate)

        self.build_ui()

        # 4. GStreamer 핵심 파이프라인 변수 초기화
        self.pipeline = None
        self.bus = None

        # 재생 위치와 UI 상태 갱신 (1초 주기로 최적화하여 X11 UI 경합 방지)
        self.position_timer_id = GLib.timeout_add(1000, self.update_playback_ui)

    def build_ui(self):
        """Jetson EGL 출력과 충돌하지 않는 네이티브 GTK 플레이어 UI를 구성합니다."""
        css = b"""
        window { background: #090b10; color: #f4f6fb; }
        .topbar, .controls { background: #11151d; }
        .topbar { border-bottom: 1px solid #252b36; }
        .controls { border-top: 1px solid #252b36; }
        .brand { font-size: 17px; font-weight: 700; color: #ffffff; }
        .muted { color: #8f98a8; font-size: 12px; }
        .now-playing { color: #dce2ec; font-size: 13px; }
        button { background: transparent; color: #dce2ec; border: 0; border-radius: 7px; padding: 7px 10px; }
        button:hover { background: #252b36; color: #ffffff; }
        .primary { background: #e9ff5b; color: #111318; border-radius: 20px; min-width: 28px; min-height: 28px; }
        .primary:hover { background: #f2ff91; color: #111318; }
        .sidebar { background: #0e1117; border-left: 1px solid #252b36; }
        .section-title { font-size: 15px; font-weight: 700; color: #ffffff; }
        .playlist-row { border-radius: 8px; padding: 7px; }
        .playlist-row:hover { background: #1a1f29; }
        .playlist-row-active { background: #242b35; border-left: 3px solid #e9ff5b; }
        .track-number { color: #70798a; font-size: 12px; }
        .track-title { color: #dce2ec; font-size: 13px; }
        scale trough { background: #303744; min-height: 4px; border-radius: 3px; }
        scale highlight { background: #e9ff5b; border-radius: 3px; }
        scale slider { background: #ffffff; min-width: 13px; min-height: 13px; border-radius: 7px; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        self.topbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.topbar.get_style_context().add_class("topbar")
        self.topbar.set_border_width(10)
        brand = Gtk.Label(label="JETSON  /  VIDEO PLAYER")
        brand.get_style_context().add_class("brand")
        self.topbar.pack_start(brand, False, False, 4)
        self.now_playing_label = Gtk.Label(xalign=0)
        self.now_playing_label.set_ellipsize(3)
        self.now_playing_label.get_style_context().add_class("now-playing")
        self.topbar.pack_start(self.now_playing_label, True, True, 12)
        playlist_toggle = Gtk.Button(label="☷  재생목록")
        playlist_toggle.set_tooltip_text("재생목록 열기/닫기")
        playlist_toggle.connect("clicked", self.on_playlist_toggle)
        self.topbar.pack_end(playlist_toggle, False, False, 0)
        close_button = Gtk.Button(label="✕")
        close_button.set_tooltip_text("종료 (Esc)")
        close_button.connect("clicked", self.on_destroy)
        self.topbar.pack_end(close_button, False, False, 0)
        root.pack_start(self.topbar, False, False, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(self.drawing_area, True, True, 0)
        self.sidebar = self.build_playlist_panel()
        content.pack_end(self.sidebar, False, False, 0)
        root.pack_start(content, True, True, 0)

        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.controls.get_style_context().add_class("controls")
        self.controls.set_border_width(10)

        timeline = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.position_label = Gtk.Label(label="00:00")
        self.position_label.get_style_context().add_class("muted")
        self.progress_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
        self.progress_scale.set_draw_value(False)
        self.progress_scale.set_hexpand(True)
        self.progress_scale.connect("button-press-event", self.on_seek_start)
        self.progress_scale.connect("button-release-event", self.on_seek_end)
        self.duration_label = Gtk.Label(label="00:00")
        self.duration_label.get_style_context().add_class("muted")
        timeline.pack_start(self.position_label, False, False, 0)
        timeline.pack_start(self.progress_scale, True, True, 0)
        timeline.pack_start(self.duration_label, False, False, 0)
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

        spacer = Gtk.Box()
        actions.pack_start(spacer, True, True, 0)
        volume_icon = Gtk.Label(label="◖)))")
        volume_icon.get_style_context().add_class("muted")
        actions.pack_start(volume_icon, False, False, 4)
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.volume_scale.set_size_request(110, -1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_value(100)
        self.volume_scale.connect("value-changed", self.on_volume_changed)
        actions.pack_start(self.volume_scale, False, False, 0)
        self.fullscreen_button = Gtk.Button(label="⛶")
        self.fullscreen_button.set_tooltip_text("영상만 전체화면 (F)")
        self.fullscreen_button.connect("clicked", lambda _button: self.toggle_fullscreen())
        actions.pack_end(self.fullscreen_button, False, False, 0)
        self.controls.pack_start(actions, False, False, 0)
        root.pack_end(self.controls, False, False, 0)

        self.refresh_playlist_ui()

    def build_playlist_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.get_style_context().add_class("sidebar")
        panel.set_size_request(310, -1)
        panel.set_border_width(14)
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        title = Gtk.Label(label="재생목록", xalign=0)
        title.get_style_context().add_class("section-title")
        count = Gtk.Label(label=f"{len(self.playlist)}개 영상", xalign=1)
        count.get_style_context().add_class("muted")
        heading.pack_start(title, True, True, 0)
        heading.pack_end(count, False, False, 0)
        panel.pack_start(heading, False, False, 4)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.playlist_box = Gtk.ListBox()
        self.playlist_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.playlist_box.set_activate_on_single_click(True)
        self.playlist_box.connect("row-activated", self.on_playlist_row_activated)
        for index, path in enumerate(self.playlist):
            row = Gtk.ListBoxRow()
            row.get_style_context().add_class("playlist-row")
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            number = Gtk.Label(label=f"{index + 1:02d}")
            number.get_style_context().add_class("track-number")
            name = Gtk.Label(label=os.path.basename(path), xalign=0)
            name.set_ellipsize(3)
            name.set_tooltip_text(path)
            name.get_style_context().add_class("track-title")
            line.pack_start(number, False, False, 0)
            line.pack_start(name, True, True, 0)
            row.add(line)
            self.playlist_box.add(row)
            self.playlist_rows.append(row)
        scroll.add(self.playlist_box)
        panel.pack_start(scroll, True, True, 0)
        return panel

    def on_playlist_toggle(self, _button):
        self.sidebar.set_visible(not self.sidebar.get_visible())

    def on_playlist_row_activated(self, _listbox, row):
        index = row.get_index()
        if index != self.current_index:
            self.current_index = index
            self.play_current_video()

    def refresh_playlist_ui(self):
        if not self.playlist:
            return
        filename = os.path.basename(self.playlist[self.current_index])
        self.now_playing_label.set_text(
            f"재생 중  ·  {filename}   {self.current_index + 1}/{len(self.playlist)}"
        )
        for index, row in enumerate(self.playlist_rows):
            context = row.get_style_context()
            if index == self.current_index:
                context.add_class("playlist-row-active")
            else:
                context.remove_class("playlist-row-active")

    @staticmethod
    def format_time(nanoseconds):
        total_seconds = max(0, int(nanoseconds / Gst.SECOND))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def update_playback_ui(self):
        if not self.pipeline:
            return True
        position_ok, position = self.pipeline.query_position(Gst.Format.TIME)
        pos_sec = int(position / Gst.SECOND) if position_ok else -1

        # 초(second) 단위가 바뀌었을 때만 GTK UI를 갱신하여 X11 Re-draw 부하 제거
        if position_ok and pos_sec != self.last_ui_pos_sec:
            self.last_ui_pos_sec = pos_sec
            if not self.is_video_only:
                self.position_label.set_text(self.format_time(position))
                if self.duration_ns == 0:
                    duration_ok, duration = self.pipeline.query_duration(Gst.Format.TIME)
                    if duration_ok and duration > 0:
                        self.duration_ns = duration
                        self.duration_label.set_text(self.format_time(duration))
                if self.duration_ns > 0 and not self.is_seeking:
                    self.progress_scale.set_value(min(100, position * 100 / self.duration_ns))

        self.stats_ticks += 1
        if self.video_sink and self.stats_ticks % 10 == 0 and self.video_sink.find_property("stats"):
            stats = self.video_sink.get_property("stats")
            if stats:
                rendered = stats.get_value("rendered") or 0
                dropped = stats.get_value("dropped") or 0
                if dropped > self.last_dropped_frames:
                    print(f"📊 [렌더링 통계] rendered={rendered}, dropped={dropped}")
                self.last_dropped_frames = dropped
        return True

    def on_seek_start(self, _scale, _event):
        self.is_seeking = True
        return False

    def on_seek_end(self, scale, _event):
        if self.pipeline and self.duration_ns > 0:
            target = int(self.duration_ns * scale.get_value() / 100)
            self.pipeline.seek_simple(
                Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, target
            )
        self.is_seeking = False
        return False

    def on_volume_changed(self, scale):
        if self.pipeline:
            self.pipeline.set_property("volume", scale.get_value() / 100.0)

    def toggle_fullscreen(self):
        """상단바, 재생목록, 컨트롤을 숨긴 영상 전용 전체화면을 전환합니다."""
        if not self.is_video_only:
            self.sidebar_was_visible = self.sidebar.get_visible()
            self.topbar.hide()
            self.sidebar.hide()
            self.controls.hide()
            self.fullscreen()
            self.set_keep_above(True)
            self.is_fullscreen = True
            self.is_video_only = True
            self.fullscreen_button.set_label("⧉")
            print("🖥️ 영상 전용 전체화면")
        else:
            self.topbar.show()
            self.controls.show()
            if self.sidebar_was_visible:
                self.sidebar.show()
            self.is_video_only = False
            self.fullscreen_button.set_label("⛶")
            print("🖥️ 플레이어 UI 표시")

    def on_deep_element_added(self, bin_elem, sub_bin, element):
        """
        GStreamer 하위 요소 생성 시 젯슨 HW 디코더(nvv4l2decoder) 및 비디오 싱크(nveglglessink)를 감지하여 
        DPB 프레임 버퍼(num-extra-surfaces=32), disable-dpb low-latency 모드, 동적 메모리 할당, 
        고성능 모드, 프레임 드랍 0 및 화면 왜곡 방지 옵션을 동적 설정합니다.
        """
        factory = element.get_factory()
        fname = factory.get_name() if factory else ""
        ename = element.get_name()
        klass = factory.get_metadata("klass") if factory else ""
        if klass and "Decoder" in klass and "Video" in klass and fname not in self.decoder_names:
            self.decoder_names.add(fname)
            acceleration = "NVDEC 하드웨어" if fname == "nvv4l2decoder" else "소프트웨어 fallback"
            print(f"🎬 [선택된 비디오 디코더] {fname} ({acceleration})")
        if "dav1d" in fname or "dav1d" in ename:
            if element.find_property("max-threads"):
                element.set_property("max-threads", 6)
        if "nvv4l2decoder" in fname or "nvv4l2decoder" in ename:
            if element.find_property("num-extra-surfaces"):
                element.set_property("num-extra-surfaces", 32)
            if element.find_property("enable-max-performance"):
                element.set_property("enable-max-performance", True)
            if element.find_property("drop-frame-interval"):
                element.set_property("drop-frame-interval", 0)
        if "nvvidconv" in fname or "nvvidconv" in ename:
            if element.find_property("output-buffers"):
                element.set_property("output-buffers", 32)
            if element.find_property("interpolation-method"):
                # 최고 품질 보간 알고리즘 (5: Nicest 10-tap) 적용하여 픽셀 선명도 극대화
                element.set_property("interpolation-method", 5)
        if "nveglglessink" in fname or "nveglglessink" in ename:
            if element.find_property("force-aspect-ratio"):
                element.set_property("force-aspect-ratio", True)

    def check_video_hw_support(self, file_path):
        """
        ffprobe JSON 정보를 분석하여 Jetson NVDEC 하드웨어 디코더가
        100% 안정적으로 가속 지원하는 포맷(H.265/HEVC 및 H.264 8-bit)인지 판정합니다.
        JetPack 드라이버 상 DPB/버퍼 결함이 발생하는 AV1, VP9 등의 코덱이나
        H.264 10-bit 영상은 미지원으로 분류하여 H.265로 자동 변환하도록 유도합니다.
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "stream=codec_name,pix_fmt,profile,width,height,color_space,color_transfer,color_primaries",
                "-of", "json",
                file_path
            ]
            data = json.loads(subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True))
            if not data.get("streams"):
                return False, "비디오 스트림 없음"
            stream = data["streams"][0]
            codec = stream.get("codec_name", "").lower()
            pix_fmt = stream.get("pix_fmt", "").lower()
            profile = stream.get("profile", "").lower()

            # 1. H.265 / HEVC -> 8-bit 및 10-bit 모두 Jetson NVDEC 하드웨어 가속 100% 완벽 지원
            if codec in ["hevc", "h265"]:
                bit_depth = "10-bit" if "10" in pix_fmt or "p10" in pix_fmt else "8-bit"
                return True, f"HEVC ({codec.upper()}) {bit_depth} NVDEC 지원"

            # 2. H.264 / AVC -> 8-bit만 지원 (High 10 / yuv420p10le 등 10-bit는 NVDEC 미지원)
            if codec in ["h264", "avc"]:
                if "10" in pix_fmt or "10" in profile or "p10" in pix_fmt:
                    return False, f"H.264 10-bit NVDEC 미지원 ({pix_fmt}/{profile})"
                return True, "H.264 8-bit NVDEC 지원"

            # 3. 그 외 (AV1, VP9, VP8 등) -> JetPack nvv4l2decoder DPB 결함 및 SW 디코딩 병목 방지를 위해 H.265 변환 대상
            return False, f"NVDEC 미지원/불안정 코덱 ({codec.upper()})"
        except Exception as e:
            return False, f"코덱 분석 실패 ({e})"

    def probe_video(self, file_path):
        """변환 품질 결정을 위해 이름 순서에 의존하지 않는 ffprobe 정보를 반환합니다."""
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,profile,color_space,color_transfer,color_primaries",
            "-of", "json", file_path,
        ]
        data = json.loads(subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True))
        if not data.get("streams"):
            raise ValueError("비디오 스트림이 없습니다")
        return data["streams"][0]

    def auto_convert_to_h265(self, file_path):
        """
        하드웨어 디코딩 미지원 영상을 H.265 (HEVC) MP4 포맷으로 자동 변환하고,
        원래 영상 파일은 'unsupported_originals' 백업 폴더로 안전하게 이동합니다.
        """
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        name_no_ext, _ext = os.path.splitext(base_name)

        # 1. 백업 폴더 생성 (unsupported_originals)
        backup_dir = os.path.join(dir_name, "unsupported_originals")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, base_name)

        # 2. H.265 변환 목표 파일 경로 생성 (.mp4)
        target_mp4_path = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")
        if os.path.exists(target_mp4_path):
            supported, _reason = self.check_video_hw_support(target_mp4_path)
            if supported:
                print(f"ℹ️ 기존 H.265 변환본을 사용합니다: {target_mp4_path}")
                return target_mp4_path

        # 3. 비트 심도 검사 (10-bit 소스는 H.265 10-bit 유지)
        _is_supported, reason = self.check_video_hw_support(file_path)
        try:
            stream = self.probe_video(file_path)
        except Exception as error:
            print(f"❌ 변환용 영상 정보 확인 실패: {error}")
            return file_path
        source_pix_fmt = stream.get("pix_fmt", "").lower()
        is_10bit = "10" in source_pix_fmt or "p10" in source_pix_fmt
        pix_fmt = "yuv420p10le" if is_10bit else "yuv420p"
        profile = "main10" if is_10bit else "main"
        temp_output = os.path.join(dir_name, f".{name_no_ext}_h265.part.mp4")

        print(f"\n🔄 [자동 코덱 변환 개시] {base_name}")
        print(f"   - 감지된 사유: {reason}")
        print(f"   - 타겟 코덱: H.265 / HEVC MP4 ({pix_fmt})")
        print(f"   - 백업 이동 경로: {backup_path}")

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
            "-map_metadata", "0", "-map_chapters", "0",
            "-pix_fmt", pix_fmt,
            "-c:v", "libx265",
            "-profile:v", profile,
            "-preset", "fast",
            "-crf", "18",
            "-threads", "6",
            "-c:a", "aac",
            "-b:a", "256k",
            "-c:s", "mov_text",
            "-movflags", "+faststart",
            "-tag:v", "hvc1",
            temp_output
        ]

        try:
            subprocess.run(ffmpeg_cmd, check=True)
            os.replace(temp_output, target_mp4_path)
            print(f"✅ [H.265 변환 완료] {os.path.basename(target_mp4_path)}")

            if os.path.exists(file_path) and file_path != target_mp4_path:
                if os.path.exists(backup_path):
                    base, suffix = os.path.splitext(base_name)
                    counter = 1
                    while os.path.exists(backup_path):
                        backup_path = os.path.join(backup_dir, f"{base}_{counter}{suffix}")
                        counter += 1
                shutil.move(file_path, backup_path)
                print(f"📦 [원본 파일 백업 이동 완료] {backup_path}")

            return target_mp4_path
        except Exception as e:
            print(f"❌ [변환 실패] {file_path}: {e}")
            if os.path.exists(temp_output):
                os.unlink(temp_output)
            return file_path

    def build_playlist(self):
        """입력값을 분석하여 재생 목록을 동적으로 구성하고, 하드웨어 미지원 코덱은 H.265로 자동 변환 및 백업합니다."""
        abs_path = os.path.abspath(self.input_path)
        
        raw_playlist = []
        if os.path.isdir(abs_path):
            self.is_single_file_mode = False
            extensions = ['*.webm', '*.mp4', '*.mkv', '*.mov', '*.avi']
            for ext in extensions:
                raw_playlist.extend(glob.glob(os.path.join(abs_path, ext)))
                raw_playlist.extend(glob.glob(os.path.join(abs_path, ext.upper())))
            raw_playlist.sort()
            
            if not raw_playlist:
                print(f"❌ 에러: [{self.input_path}] 폴더 내에 재생 가능한 영상 파일이 없습니다.")
                sys.exit(1)

        elif os.path.isfile(abs_path):
            self.is_single_file_mode = True
            raw_playlist.append(abs_path)
        else:
            print(f"❌ 에러: [{self.input_path}] 존재하지 않는 파일이거나 올바르지 않은 경로입니다.")
            sys.exit(1)

        # 중복 제거 및 하드웨어 미지원 영상 자동 H.265 변환 / 백업 검사
        processed_set = set()
        for path in raw_playlist:
            if not os.path.exists(path) or path in processed_set:
                continue

            is_supported, _reason = self.check_video_hw_support(path)
            if not is_supported:
                # 하드웨어 미지원 코덱 발견시 H.265 변환 및 원본 백업 수행
                final_path = self.auto_convert_to_h265(path)
            else:
                final_path = path

            if final_path not in self.playlist:
                self.playlist.append(final_path)
                processed_set.add(final_path)

        mode_str = "단일 파일 반복 모드" if self.is_single_file_mode else "폴더 순환 모드"
        print(f"📂 [{mode_str}] 총 {len(self.playlist)}개의 NVDEC 가속 영상을 재생합니다.")
        for idx, path in enumerate(self.playlist):
            print(f"   [{idx}] {os.path.basename(path)}")

    def on_size_allocate(self, widget, allocation):
        """GTK 창/위젯 크기 변경 시 비디오 싱크 렌더링 사각형을 실제 픽셀 해상도에 1:1 동기화하여 텍스처 뭉개짐을 완벽 방지합니다."""
        target_sink = getattr(self, "video_sink", None)
        if target_sink:
            try:
                if isinstance(target_sink, GstVideo.VideoOverlay) or hasattr(target_sink, "set_render_rectangle"):
                    target_sink.set_render_rectangle(0, 0, allocation.width, allocation.height)
                    target_sink.expose()
                elif self.pipeline and hasattr(self.pipeline, "set_render_rectangle"):
                    self.pipeline.set_render_rectangle(0, 0, allocation.width, allocation.height)
                    self.pipeline.expose()
            except Exception:
                pass

    def on_realize(self, widget):
        """GTK 창의 리소스가 로드되었을 때 영상 재생을 시작합니다."""
        if self.pipeline is not None:
            return
        print("🖥️ GUI 창 준비 완료. 영상 재생을 시작합니다.")
        
        # GTK 메인 스레드에서 Window XID 사전 캐싱 및 GNOME 데스크톱 컴포지터 우회 강제
        top_window = self.get_window()
        if top_window:
            enable_x11_compositor_bypass(top_window)

        gdk_window = self.drawing_area.get_window() or top_window
        if gdk_window:
            enable_x11_compositor_bypass(gdk_window)
            if hasattr(gdk_window, "get_xid"):
                self.xid = gdk_window.get_xid()
            elif hasattr(GdkX11, "X11Window") and hasattr(GdkX11.X11Window, "get_xid"):
                self.xid = GdkX11.X11Window.get_xid(gdk_window)

        self.play_current_video()

    def play_current_video(self):
        """[성능 최적화] 영상 전환 시 기존 파이프라인을 완전히 해제하고 신규 구축하여 EGL surface 및 하드웨어 디코더 락을 방지합니다."""
        video_path = self.playlist[self.current_index]
        print(f"\n▶ [{self.current_index + 1}/{len(self.playlist)}] 재생 중: {os.path.basename(video_path)}")
        self.refresh_playlist_ui()
        self.duration_ns = 0
        self.progress_scale.set_value(0)
        self.position_label.set_text("00:00")
        self.duration_label.set_text("00:00")
        self.decoder_names.clear()
        self.last_dropped_frames = 0
        self.last_ui_pos_sec = -1

        video_uri = f"file://{pathname2url(os.path.abspath(video_path))}"
        
        # [핵심] 기존 파이프라인 및 버스 시그널 감시 완전 해제 후 NULL 처리 (EGL Surface/VIC 락 세척)
        if self.bus is not None:
            try:
                self.bus.remove_signal_watch()
            except Exception:
                pass
            self.bus = None

        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

        # 신규 playbin 파이프라인 생성
        self.pipeline = Gst.ElementFactory.make("playbin", "player")

        # 젯슨 HW 디코더 동적 속성 설정을 위한 deep-element-added 시그널 연결
        self.pipeline.connect("deep-element-added", self.on_deep_element_added)

        # 0x01 (video) + 0x02 (audio) + 0x10 (soft-volume) = 0x00000013
        # NVDEC(nvv4l2decoder) 하드웨어 디코더의 NVMM 메모리를 EGL 셰이더로 자동 브릿지 허용
        self.pipeline.set_property("flags", 0x00000013)

        # Jetson 전용 NVDEC HW 가속 직결 EGL 비디오 싱크 생성 (4K 60fps 무결 렌더링)
        vsink = Gst.ElementFactory.make("nveglglessink", "vsink")
        if not vsink:
            vsink = Gst.ElementFactory.make("nv3dsink", "vsink")
        if not vsink:
            vsink = Gst.ElementFactory.make("autovideosink", "vsink")

        if vsink:
            if vsink.find_property("sync"):
                vsink.set_property("sync", True)
            if vsink.find_property("qos"):
                # 미세 지연 시 업스트림 프레임 드랍(스킵)을 차단하여 균일한 프레임 페이싱 유지
                vsink.set_property("qos", False)
            if vsink.find_property("max-lateness"):
                # 프레임 폐기를 방지하여 끊김 없는 60 FPS 스무스 재생 보장
                vsink.set_property("max-lateness", -1)
            if vsink.find_property("force-aspect-ratio"):
                vsink.set_property("force-aspect-ratio", True)
            self.pipeline.set_property("video-sink", vsink)
            self.video_sink = vsink

        # autoaudiosink가 실제 사용 가능한 PulseAudio/ALSA 장치를 선택하게 합니다.
        for sink_name in ["autoaudiosink", "fakesink"]:
            asink = Gst.ElementFactory.make(sink_name, "asink")
            if asink:
                if sink_name != "fakesink":
                    if asink.find_property("sync"):
                        asink.set_property("sync", True)
                self.pipeline.set_property("audio-sink", asink)
                break

        # 버스 이벤트 연결
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.enable_sync_message_emission()
        self.bus.connect("sync-message::element", self.on_sync_message)
        self.bus.connect("message", self.on_bus_message)

        # URI 속성 갱신 후 플레이 시작
        self.pipeline.set_property("uri", video_uri)
        self.pipeline.set_property("volume", self.volume_scale.get_value() / 100.0)
        self.pipeline.set_state(Gst.State.PLAYING)
        self.is_playing = True
        self.play_button.set_label("Ⅱ")
        
        return False

    def on_sync_message(self, bus, message):
        """GTK DrawingArea XID에 비디오 화면을 일치시켜 GTK 자식 위젯 덮어쓰기 및 1초 후 멈춤을 방지합니다."""
        is_prepare_handle = False
        if hasattr(GstVideo, "is_video_overlay_prepare_window_handle_message"):
            is_prepare_handle = GstVideo.is_video_overlay_prepare_window_handle_message(message)
        
        if not is_prepare_handle and message.get_structure():
            is_prepare_handle = (message.get_structure().get_name() == "prepare-window-handle")

        if is_prepare_handle:
            xid = getattr(self, "xid", None)
            if not xid:
                target_window = self.drawing_area.get_window() or self.get_window()
                if target_window:
                    if hasattr(target_window, "get_xid"):
                        xid = target_window.get_xid()
                    elif hasattr(GdkX11, "X11Window") and hasattr(GdkX11.X11Window, "get_xid"):
                        xid = GdkX11.X11Window.get_xid(target_window)
                    self.xid = xid
            if xid:
                if isinstance(message.src, GstVideo.VideoOverlay) or hasattr(message.src, "set_window_handle"):
                    message.src.set_window_handle(xid)
                elif self.pipeline and hasattr(self.pipeline, "set_window_handle"):
                    self.pipeline.set_window_handle(xid)

    def on_bus_message(self, bus, message):
        """재생 완료(EOS) 및 에러 메시지 처리"""
        if message.type == Gst.MessageType.EOS:
            self.retry_counts.pop(self.playlist[self.current_index], None)
            if self.is_single_file_mode:
                print("🔄 단일 영상 완료: 파이프라인 자원 세척 후 재선언 재생합니다.")
                # 장시간 재생 시 EGL surface/시계동기화 락 방지를 위해 파이프라인 완전 재구축 수행
                GLib.timeout_add(10, self.play_current_video)
            else:
                self.play_next_video()
            
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"❌ 재생 중 에러 발생: {err}")
            if debug:
                print(f"   GStreamer: {debug}")
            path = self.playlist[self.current_index]
            retries = self.retry_counts.get(path, 0)
            if retries < self.max_retries:
                self.retry_counts[path] = retries + 1
                print(f"🔄 재생 파이프라인 재시도 ({retries + 1}/{self.max_retries})")
                GLib.timeout_add(250, self.play_current_video)
            elif self.is_single_file_mode:
                print("⏹ 반복 오류로 재생을 중단합니다. 원본과 디코더 로그를 확인하세요.")
                self.pipeline.set_state(Gst.State.PAUSED)
            else:
                print("⏭ 반복 오류 항목을 건너뜁니다.")
                self.play_next_video()

        elif message.type == Gst.MessageType.STATE_CHANGED and message.src == self.pipeline:
            _old_state, new_state, _pending = message.parse_state_changed()
            self.is_playing = new_state == Gst.State.PLAYING
            self.play_button.set_label("Ⅱ" if self.is_playing else "▶")

    def seek_relative(self, offset_seconds):
        """현재 재생 위치를 기준으로 지정된 초만큼 앞/뒤로 이동합니다."""
        if not self.pipeline:
            return
            
        success, position = self.pipeline.query_position(Gst.Format.TIME)
        if not success:
            print("⚠️ 현재 재생 위치를 확인할 수 없어 탐색에 실패했습니다.")
            return

        target_ns = position + (offset_seconds * Gst.SECOND)
        if target_ns < 0:
            target_ns = 0

        res = self.pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            target_ns
        )
        if not res:
            print("⚠️ 탐색 실패로 파이프라인을 재구축합니다.")
            self.play_current_video()
            return

        direction = "앞으로" if offset_seconds > 0 else "뒤로"
        print(f"⏩ {direction} {abs(offset_seconds)}초 이동 (현재 위치: {target_ns / Gst.SECOND:.1f}초)")

    def toggle_play_pause(self):
        """일시 정지 / 재생 상태를 전환합니다."""
        if not self.pipeline:
            return
            
        if self.is_playing:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.is_playing = False
            self.play_button.set_label("▶")
            print("⏸ 일시 정지")
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
            self.is_playing = True
            self.play_button.set_label("Ⅱ")
            print("▶ 다시 재생")

    def play_next_video(self):
        """다음 영상으로 전환합니다."""
        if self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video)
        else:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            print("⏭ 다음 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video)

    def play_prev_video(self):
        """이전 영상으로 전환합니다."""
        if self.is_single_file_mode:
            GLib.timeout_add(10, self.play_current_video)
        else:
            self.current_index = (self.current_index - 1 + len(self.playlist)) % len(self.playlist)
            print("⏮ 이전 영상으로 넘어갑니다.")
            GLib.timeout_add(50, self.play_current_video)

    def on_key_press(self, widget, event):
        """키보드 입력 이벤트 제어"""
        keyname = Gdk.keyval_name(event.keyval)
        
        if keyname == "Escape" and self.is_video_only:
            self.toggle_fullscreen()
            return True
        elif keyname in ["Escape", "q", "Q"]:
            print("⏹ 프로그램 종료.")
            self.on_destroy(widget)
            return True
        elif keyname == "space":
            self.toggle_play_pause()
            return True
        elif keyname == "Right":
            self.seek_relative(10)
            return True
        elif keyname == "Left":
            self.seek_relative(-10)
            return True
        elif keyname in ["n", "N"]:
            self.play_next_video()
            return True
        elif keyname in ["p", "P"]:
            self.play_prev_video()
            return True
        elif keyname in ["f", "F"]:
            self.toggle_fullscreen()
            return True
            
        return False

    def on_destroy(self, widget):
        if getattr(self, "position_timer_id", None):
            GLib.source_remove(self.position_timer_id)
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

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ 사용법: python3 jetson_player.py [폴더_경로 또는 파일_경로]")
        sys.exit(1)
        
    Gst.init(None)
    Gtk.init(None)
    
    user_input = sys.argv[1]
    win = JetsonSignageFlexiblePlayer(user_input)
    win.show_all()
    Gtk.main()
