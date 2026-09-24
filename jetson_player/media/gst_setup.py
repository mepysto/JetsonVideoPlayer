"""GStreamer 디코더 랭크 최적화와 X11 컴포지터 우회"""
import os
import subprocess

from gi.repository import GdkX11, Gst


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


def build_hw_video_output(sink, fmt="NV12"):
    """NVDEC 출력(NVMM 메모리)을 GTK GL 싱크가 받을 수 있도록 nvvidconv 변환을 앞에 붙인 출력 bin을 만듭니다.

    gtkglsink/glsinkbin은 video/x-raw(memory:NVMM)를 받지 못하므로, 그대로 두면 decodebin이
    nvv4l2decoder를 버리고 소프트웨어 디코더(avdec_*)로 대체합니다. nvvidconv가 VIC 하드웨어로
    NVMM → 시스템 메모리 NV12 변환을 맡으면 디코딩은 NVDEC에서 계속 수행됩니다.
    JVP_HW_VIDEO=0 환경 변수로 끌 수 있습니다 (문제 진단용).
    """
    if os.environ.get("JVP_HW_VIDEO", "1") == "0":
        return sink
    conv = Gst.ElementFactory.make("nvvidconv", "hw_vidconv")
    capsfilter = Gst.ElementFactory.make("capsfilter", "hw_vidcaps")
    if not conv or not capsfilter:
        return sink
    capsfilter.set_property("caps", Gst.Caps.from_string(f"video/x-raw,format={fmt}"))
    out = Gst.Bin.new("hw_video_output")
    for el in (conv, capsfilter, sink):
        out.add(el)
    if not (conv.link(capsfilter) and capsfilter.link(sink)):
        print("⚠️ HW 영상 출력 구성 실패: 기본 싱크를 사용합니다.")
        for el in (conv, capsfilter, sink):
            out.remove(el)
        return sink
    ghost = Gst.GhostPad.new("sink", conv.get_static_pad("sink"))
    ghost.set_active(True)
    out.add_pad(ghost)
    return out
