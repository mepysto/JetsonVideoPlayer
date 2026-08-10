import sys
import os
import glob
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
from gi.repository import Gst, Gtk, Gdk, GstVideo, GLib

def optimize_gstreamer_ranks():
    """
    Jetson 하드웨어 디코더(nvv4l2decoder) 및 비디오 변환기(nvvidconv)의 랭크를 최우선(PRIMARY + 1000)으로 설정하고,
    CPU 소프트웨어 디코더를 무력화하여 4K 60fps 영상을 FULL 60 FPS 하드웨어 가속으로 매끄럽게 재생합니다.
    """
    registry = Gst.Registry.get()
    
    # 1. Jetson 하드웨어 디코더 존재 여부 감지
    hw_decoder = registry.find_feature("nvv4l2decoder", Gst.ElementFactory.__gtype__)
    
    if hw_decoder:
        # Jetson 하드웨어 디코더 및 변환기 최우선 (PRIMARY + 1000)
        hw_elements = ["nvv4l2decoder", "nvvidconv"]
        for name in hw_elements:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.PRIMARY + 1000)
        
        # CPU 소프트웨어 디코더 랭크 무력화 (NONE) -> HW 디코딩 강제 (CPU 폭탄 및 프레임 끊김 완벽 방지)
        sw_decoders = [
            "av1dec", "dav1d", "avdec_av1",
            "vp9dec", "avdec_vp9", "avdec_vp10", "avdec_vp8",
            "avdec_h264", "avdec_hevc", "avdec_mjpeg"
        ]
        for name in sw_decoders:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.NONE)

        # CPU 소프트웨어 비디오 변환기/스케일러 랭크 무력화
        for name in ["videoconvert", "videoscale"]:
            elem = registry.find_feature(name, Gst.ElementFactory.__gtype__)
            if elem:
                elem.set_rank(Gst.Rank.NONE)

        print("⚡ [하드웨어 가속 60 FPS] Jetson NVMM 하드웨어 디코더 및 GPU 가속 랭크 적용 완료.")
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

        # 2. 비디오가 임베딩될 Gtk DrawingArea 컨테이너 생성
        self.drawing_area = Gtk.DrawingArea()
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
        GStreamer 하위 요소 생성 시 젯슨 HW 디코더(nvv4l2decoder)를 감지하여 
        DPB 프레임 버퍼(num-extra-surfaces=32) 및 고성능 모드를 동적 설정합니다.
        """
        factory = element.get_factory()
        fname = factory.get_name() if factory else ""
        ename = element.get_name()
        if "nvv4l2decoder" in fname or "nvv4l2decoder" in ename:
            if element.find_property("num-extra-surfaces"):
                element.set_property("num-extra-surfaces", 32)
            if element.find_property("enable-max-performance"):
                element.set_property("enable-max-performance", True)

    def build_playlist(self):
        """입력값을 분석하여 재생 목록을 동적으로 구성합니다."""
        abs_path = os.path.abspath(self.input_path)
        
        if os.path.isdir(abs_path):
            self.is_single_file_mode = False
            extensions = ['*.webm', '*.mp4', '*.mkv', '*.mov']
            for ext in extensions:
                self.playlist.extend(glob.glob(os.path.join(abs_path, ext)))
                self.playlist.extend(glob.glob(os.path.join(abs_path, ext.upper())))
            self.playlist.sort()
            
            if not self.playlist:
                print(f"❌ 에러: [{self.input_path}] 폴더 내에 재생 가능한 영상 파일이 없습니다.")
                sys.exit(1)
            print(f"📂 [폴더 순환 모드] 총 {len(self.playlist)}개의 영상을 순서대로 재생합니다.")

        elif os.path.isfile(abs_path):
            self.is_single_file_mode = True
            self.playlist.append(abs_path)
            print(f"🎬 [단일 파일 반복 모드] 지정된 파일을 무한 반복 재생합니다.")
            
        else:
            print(f"❌ 에러: [{self.input_path}] 존재하지 않는 파일이거나 올바르지 않은 경로입니다.")
            sys.exit(1)

        for idx, path in enumerate(self.playlist):
            print(f"   [{idx}] {os.path.basename(path)}")

    def on_realize(self, widget):
        """GTK 창의 리소스가 로드되었을 때 마우스를 숨기고 영상 재생을 시작합니다."""
        if self.pipeline is not None:
            return
        print("🖥️ GUI 창 준비 완료. 영상 재생을 시작합니다.")
        
        # GTK 메인 스레드에서 Window XID 사전 캐싱 (장시간 재생 시 X11 데드락 방지)
        gdk_window = self.drawing_area.get_window() or self.get_window()
        if gdk_window:
            if hasattr(gdk_window, "get_xid"):
                self.xid = gdk_window.get_xid()
            elif hasattr(Gdk, "X11Window") and hasattr(Gdk.X11Window, "get_xid"):
                self.xid = Gdk.X11Window.get_xid(gdk_window)

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

        # Native 비디오 포맷 플래그 설정 (GStreamer의 불필요한 소프트웨어 converter 삽입 방지)
        current_flags = self.pipeline.get_property("flags")
        self.pipeline.set_property("flags", current_flags | 0x00000020) # GST_PLAY_FLAG_NATIVE_VIDEO

        # Jetson 하드웨어 가속 비디오 싱크 빈 구축 (nvvidconv compute-hw=1 + NVMM NV12 + nveglglessink sync=false qos=true)
        # sync=false 및 compute-hw=1 적용으로 오디오 시계 드리프트 및 프레임 끊김 현상을 완벽 방지
        vsink_desc = "nvvidconv compute-hw=1 ! video/x-raw(memory:NVMM), format=NV12 ! nveglglessink sync=false qos=true"
        try:
            vsink_bin = Gst.parse_bin_from_description(vsink_desc, True)
            self.pipeline.set_property("video-sink", vsink_bin)
        except Exception as e:
            print(f"⚠️ 커스텀 비디오 싱크 생성 실패, 기본 nveglglessink 사용: {e}")
            vsink = Gst.ElementFactory.make("nveglglessink", "vsink")
            if vsink:
                if vsink.find_property("sync"):
                    vsink.set_property("sync", False)
                if vsink.find_property("qos"):
                    vsink.set_property("qos", True)
                self.pipeline.set_property("video-sink", vsink)

        # 오디오 출력 장치 지정 (pulsesink -> alsasink -> autoaudiosink -> fakesink 순서 안전 지정)
        for sink_name in ["pulsesink", "alsasink", "autoaudiosink", "fakesink"]:
            asink = Gst.ElementFactory.make(sink_name, "asink")
            if asink:
                if sink_name != "fakesink" and asink.find_property("sync"):
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
        self.pipeline.set_state(Gst.State.PLAYING)
        
        # 주기적으로 파이썬 레벨의 안 쓰이는 메모리를 정리
        gc.collect()
        return False

    def on_sync_message(self, bus, message):
        """GTK DrawingArea에 비디오 화면을 일치시킵니다."""
        is_prepare_handle = False
        if hasattr(GstVideo, "is_video_overlay_prepare_window_handle_message"):
            is_prepare_handle = GstVideo.is_video_overlay_prepare_window_handle_message(message)
        
        if not is_prepare_handle and message.get_structure():
            is_prepare_handle = (message.get_structure().get_name() == "prepare-window-handle")

        if is_prepare_handle:
            xid = getattr(self, "xid", None)
            if not xid:
                sys_window = self.drawing_area.get_window() or self.get_window()
                if sys_window:
                    if hasattr(sys_window, "get_xid"):
                        xid = sys_window.get_xid()
                    elif hasattr(Gdk, "X11Window") and hasattr(Gdk.X11Window, "get_xid"):
                        xid = Gdk.X11Window.get_xid(sys_window)
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


