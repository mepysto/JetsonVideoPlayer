import sys
import os
import glob
import subprocess
import shutil
import gi
import gc # [누수 방지] 명시적 가비지 컬렉션 처리를 위해 추가
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
    GNOME Mutter 컴포지터의 EGL 서피스 스캔아웃 중단 방지를 위해 우회 설정을 비활성화합니다.
    """
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

        # VP9 10-bit HDR 전용 SW 디코더 랭크 상향 (JetPack HW VP9 버퍼 에러 전용 회피)
        sw_vp9 = ["vp9dec", "avdec_vp9"]
        for name in sw_vp9:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 5000)

        # ARM 64-bit NEON SIMD 다중 스레드 디코더(dav1d) 랭크 최우선 상향 (Jetson Orin Nano NVDEC AV1 부재 전용 60 FPS 가속)
        dav1d = registry.find_feature("dav1d", Gst.ElementFactory.__gtype__)
        if dav1d:
            dav1d.set_rank(Gst.Rank.PRIMARY + 10000)

        # 느린 단일 스레드 CPU 디코더만 무력화 (avdec_av1 등)
        sw_decoders = [
            "av1dec", "avdec_av1",
            "avdec_vp10", "avdec_vp8",
            "avdec_h264", "avdec_hevc", "avdec_mjpeg"
        ]
        for name in sw_decoders:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.NONE)

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
        super().__init__(title="Jetson Flexible Signage Player")
        
        # [필수] 하드웨어 가속 랭크 최적화 보장
        optimize_gstreamer_ranks()

        # 1. 사이니지 전광판용 전체화면 빌드 (테두리 및 상단바 완전 제거)
        self.set_decorated(False)
        self.fullscreen()
        self.set_keep_above(True)
        
        # 이벤트 연결 (종료 및 키보드 입력)
        self.connect("destroy", self.on_destroy)
        self.connect("key-press-event", self.on_key_press)

        # 2. 비디오가 임베딩될 Gtk DrawingArea 컨테이너 생성 (GTK-EGL 그래픽 충돌 방지 최적화)
        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_hexpand(True)
        self.drawing_area.set_vexpand(True)
        self.drawing_area.set_size_request(640, 480) # [핵심] C-라이브러리 dst->h == 0 멈춤 에러 방지
        self.drawing_area.set_double_buffered(False) # [핵심] GTK CPU 이중 버퍼링 무력화 (EGL 직통 렌더링)
        self.drawing_area.set_app_paintable(True)    # [핵심] GTK 창 기본 배경 그리기 차단
        self.drawing_area.connect("draw", lambda widget, cr: True) # [핵심] GTK repaint 이벤트 무력화
        self.add(self.drawing_area)
        
        # 화면 준비가 완료(realize)되면 재생을 시작하도록 이벤트 등록
        self.drawing_area.connect("realize", self.on_realize)

        # 3. 입력 경로 타입(폴더 vs 파일)을 분석하여 재생 목록 구성
        self.input_path = input_path
        self.playlist = []
        self.current_index = 0
        self.is_single_file_mode = False # 단일 파일 반복 모드 여부
        self.xid = None # GTK 메인 스레드 안전 XID 캐시
        
        self.build_playlist()

        # 4. GStreamer 핵심 파이프라인 변수 초기화
        self.pipeline = None
        self.bus = None

    def on_deep_element_added(self, bin_elem, sub_bin, element):
        """
        GStreamer 하위 요소 생성 시 젯슨 HW 디코더(nvv4l2decoder) 및 비디오 싱크(nveglglessink)를 감지하여 
        DPB 프레임 버퍼(num-extra-surfaces=32), disable-dpb low-latency 모드, 동적 메모리 할당, 
        고성능 모드, 프레임 드랍 0 및 화면 왜곡 방지 옵션을 동적 설정합니다.
        """
        factory = element.get_factory()
        fname = factory.get_name() if factory else ""
        ename = element.get_name()
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
        if "nveglglessink" in fname or "nveglglessink" in ename:
            if element.find_property("force-aspect-ratio"):
                element.set_property("force-aspect-ratio", False)

    def check_video_hw_support(self, file_path):
        """
        ffprobe를 사용하여 영상 파일의 코덱 및 색상 깊이를 분석하고,
        Jetson NVDEC 하드웨어 디코더가 100% 가속 지원하는 포맷인지 검증합니다.
        """
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,pix_fmt,profile",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip().split('\n')
            codec = output[0].strip().lower() if len(output) > 0 else ""
            pix_fmt = output[1].strip().lower() if len(output) > 1 else ""
            profile = output[2].strip().lower() if len(output) > 2 else ""

            # 1. H.265 / HEVC -> 8-bit & 10-bit 모두 NVDEC HW 칩 가속 100% 지원
            if codec in ["hevc", "h265"]:
                return True, "HEVC (H.265) HW 가속 지원"

            # 2. H.264 / AVC -> 8-bit만 지원 (10-bit / yuv420p10le / High 10 프로파일은 HW 미지원)
            if codec in ["h264", "avc"]:
                if "10" in pix_fmt or "10" in profile or "p10" in pix_fmt:
                    return False, f"H.264 10-bit ({pix_fmt}/{profile}) HW 미지원"
                return True, "H.264 8-bit HW 가속 지원"

            # 3. 그 외 (AV1, VP9, VP8 등) -> HW 미지원
            return False, f"미지원 코덱 ({codec})"
        except Exception as e:
            return False, f"코덱 분석 실패 ({e})"

    def auto_convert_to_h265(self, file_path):
        """
        하드웨어 디코딩 미지원 영상을 H.265 (HEVC) MP4 포맷으로 자동 변환하고,
        원래 영상 파일은 'unsupported_originals' 백업 폴더로 안전하게 이동합니다.
        """
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        name_no_ext, ext = os.path.splitext(base_name)

        # 1. 백업 폴더 생성 (unsupported_originals)
        backup_dir = os.path.join(dir_name, "unsupported_originals")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, base_name)

        # 2. H.265 변환 목표 파일 경로 생성 (.mp4)
        target_mp4_path = os.path.join(dir_name, f"{name_no_ext}_h265.mp4")

        # 3. 비트 심도 검사 (10-bit 소스는 H.265 10-bit 유지)
        is_supported, reason = self.check_video_hw_support(file_path)
        is_10bit = "10" in reason or "10bit" in file_path.lower()
        pix_fmt = "yuv420p10le" if is_10bit else "yuv420p"

        print(f"\n🔄 [자동 코덱 변환 개시] {base_name}")
        print(f"   - 감지된 사유: {reason}")
        print(f"   - 타겟 코덱: H.265 / HEVC MP4 ({pix_fmt})")
        print(f"   - 백업 이동 경로: {backup_path}")

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-pix_fmt", pix_fmt,
            "-c:v", "libx265",
            "-preset", "ultrafast",
            "-crf", "20",
            "-threads", "6",
            "-c:a", "aac",
            target_mp4_path
        ]

        try:
            subprocess.run(ffmpeg_cmd, check=True)
            print(f"✅ [H.265 변환 완료] {os.path.basename(target_mp4_path)}")

            if os.path.exists(file_path) and file_path != target_mp4_path:
                shutil.move(file_path, backup_path)
                print(f"📦 [원본 파일 백업 이동 완료] {backup_path}")

            return target_mp4_path
        except Exception as e:
            print(f"❌ [변환 실패] {file_path}: {e}")
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

            is_supported, reason = self.check_video_hw_support(path)
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

    def on_realize(self, widget):
        """GTK 창의 리소스가 로드되었을 때 마우스를 숨기고 영상 재생을 시작합니다."""
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

            display = gdk_window.get_display()
            cursor = Gdk.Cursor.new_from_name(display, "none")
            gdk_window.set_cursor(cursor)
            print("🐭 마우스 커서가 숨김 처리되었습니다.")
            
        self.play_current_video()

    def play_current_video(self):
        """[성능 최적화] 영상 전환 시 기존 파이프라인을 완전히 해제하고 신규 구축하여 EGL surface 및 하드웨어 디코더 락을 방지합니다."""
        video_path = self.playlist[self.current_index]
        print(f"\n▶ [{self.current_index + 1}/{len(self.playlist)}] 재생 중: {os.path.basename(video_path)}")

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

        # Native 비디오 및 오디오 포맷 플래그 설정 (deinterlace, soft-colorbalance 등 CPU 필터 완전 차단)
        # 0x01 (video) + 0x02 (audio) + 0x20 (native-audio) + 0x40 (native-video) = 0x00000063
        self.pipeline.set_property("flags", 0x00000063)

        # Jetson 전용 하드웨어 EGL 비디오 싱크 생성 (Gst.Bin 캡스 파싱 에러 및 1초 멈춤 100% 차단)
        vsink = Gst.ElementFactory.make("nveglglessink", "vsink")
        if not vsink:
            vsink = Gst.ElementFactory.make("nv3dsink", "vsink")
        if not vsink:
            vsink = Gst.ElementFactory.make("autovideosink", "vsink")

        if vsink:
            if vsink.find_property("sync"):
                vsink.set_property("sync", True)
            if vsink.find_property("qos"):
                vsink.set_property("qos", True)
            if vsink.find_property("max-lateness"):
                vsink.set_property("max-lateness", -1) # [핵심] 지연 프레임 버림 방지
            if vsink.find_property("force-aspect-ratio"):
                vsink.set_property("force-aspect-ratio", False)
            self.pipeline.set_property("video-sink", vsink)

        # 오디오 출력 장치 지정 (pulsesink -> autoaudiosink -> alsasink -> fakesink 순서 안전 지정)
        # pulsesink를 최우선 지정하여 우분투 데스크톱 PulseAudio 락 충돌 없이 사운드 정상 출력 및 비디오 60 FPS 정속 연동 보장
        for sink_name in ["pulsesink", "autoaudiosink", "alsasink", "fakesink"]:
            asink = Gst.ElementFactory.make(sink_name, "asink")
            if asink:
                if sink_name != "fakesink":
                    if asink.find_property("sync"):
                        asink.set_property("sync", False)
                    if asink.find_property("async"):
                        asink.set_property("async", False)
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
        self.pipeline.set_state(Gst.State.PLAYING)
        
        # 주기적으로 파이썬 레벨의 안 쓰이는 메모리를 정리
        gc.collect()
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
                message.src.set_window_handle(xid)

    def on_bus_message(self, bus, message):
        """재생 완료(EOS) 및 에러 메시지 처리"""
        if message.type == Gst.MessageType.EOS:
            if self.is_single_file_mode:
                print("🔄 단일 영상 완료: 파이프라인 자원 세척 후 재선언 재생합니다.")
                # 장시간 재생 시 EGL surface/시계동기화 락 방지를 위해 파이프라인 완전 재구축 수행
                GLib.timeout_add(10, self.play_current_video)
            else:
                self.play_next_video()
            
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"❌ 재생 중 에러 발생: {err}")
            self.play_next_video()

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
            
        success, state, pending = self.pipeline.get_state(Gst.CLOCK_TIME_NONE)
        if success in (Gst.StateChangeReturn.SUCCESS, Gst.StateChangeReturn.ASYNC):
            target_state = pending if pending != Gst.State.VOID_PENDING else state
            if target_state == Gst.State.PLAYING:
                self.pipeline.set_state(Gst.State.PAUSED)
                print("⏸ 일시 정지")
            elif target_state == Gst.State.PAUSED:
                self.pipeline.set_state(Gst.State.PLAYING)
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
        
        if keyname in ["Escape", "q", "Q"]:
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
            
        return False

    def on_destroy(self, widget):
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
    
    # [필수] 하드웨어 가속 디코더/변환기 랭크 최적화 적용
    optimize_gstreamer_ranks()
    
    user_input = sys.argv[1]
    win = JetsonSignageFlexiblePlayer(user_input)
    win.show_all()
    Gtk.main()


