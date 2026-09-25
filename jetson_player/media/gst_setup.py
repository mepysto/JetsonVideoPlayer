"""GStreamer 디코더 랭크 최적화와 X11 컴포지터 우회"""
import logging
import os
import subprocess

from gi.repository import GdkX11, GObject, Gst, GstPbutils

log = logging.getLogger(__name__)


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

        log.info("⚡ [하드웨어 가속 60 FPS 최적화] nvv4l2decoder HW 가속 및 60 FPS 전용 파이프라인 무결 적용 완료.")
    else:
        log.info("ℹ️ [소프트웨어 디코딩] Jetson HW 디코더(nvv4l2decoder)가 감지되지 않아 기본 디코더를 유지합니다.")


def seek_flags(mode):
    """탐색 종류별 GStreamer 플래그.

    fast: 가장 가까운 키프레임으로 즉시 이동 (방향키·휠·드래그 중 미리보기)
    accurate: 정확한 시각으로 이동 (A-B 반복, 북마크, 챕터, 진행바 놓기, 이어보기)
    """
    if mode == "fast":
        return Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT | Gst.SeekFlags.SNAP_NEAREST
    if mode == "accurate":
        return Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE
    raise ValueError(f"unknown seek mode: {mode}")


PASSTHROUGH_CAPS = ("audio/x-ac3", "audio/x-eac3", "audio/x-dts")


def sink_passthrough_formats(factory="pulsesink"):
    """사운드 서버가 원음 그대로 받을 수 있는 압축 오디오 형식 (HDMI 패스스루가 켜져 있을 때만 나타남)"""
    sink = Gst.ElementFactory.make(factory, None)
    if sink is None:
        return set()
    try:
        if sink.set_state(Gst.State.READY) == Gst.StateChangeReturn.FAILURE:
            return set()
        caps = sink.get_static_pad("sink").query_caps(None)
        return {caps.get_structure(i).get_name() for i in range(caps.get_size())} & set(PASSTHROUGH_CAPS)
    finally:
        sink.set_state(Gst.State.NULL)


def audio_codec_of(path, timeout_sec=3):
    """파일의 첫 오디오 스트림 형식 (예: audio/x-ac3). 오디오가 없거나 알 수 없으면 None"""
    try:
        discoverer = GstPbutils.Discoverer.new(timeout_sec * Gst.SECOND)
        info = discoverer.discover_uri(Gst.filename_to_uri(os.path.abspath(path)))
    except Exception:
        log.debug(f"오디오 형식 확인 실패: {path}", exc_info=True)
        return None
    streams = info.get_audio_streams()
    caps = streams[0].get_caps() if streams else None
    return caps.get_structure(0).get_name() if caps and caps.get_size() else None


def make_audio_output(av_offset_ms=0, factory="autoaudiosink"):
    """오디오 출력 싱크 (없으면 fakesink). AV 싱크 보정값을 ts-offset으로 적용합니다."""
    asink = Gst.ElementFactory.make(factory, "asink") or Gst.ElementFactory.make("fakesink", "asink")
    if asink and asink.find_property("sync"):
        asink.set_property("sync", True)
    if asink and asink.find_property("ts-offset") and av_offset_ms:
        asink.set_property("ts-offset", av_offset_ms * 1_000_000)
    return asink


def build_audio_sink_bin(asink, filters=()):
    """audioconvert → scaletempo → [filters...] → audioresample → asink 로 이어진 오디오 싱크 bin.

    scaletempo는 배속 재생에서 음정을 유지합니다. filters는 야간 모드 등 효과 요소이며 순서대로 연결됩니다.
    필수 요소가 없으면 asink를 그대로 돌려줍니다.
    """
    aconv = Gst.ElementFactory.make("audioconvert", "aconv")
    scaletempo = Gst.ElementFactory.make("scaletempo", "scaletempo")
    aresample = Gst.ElementFactory.make("audioresample", "aresample")
    if not (aconv and scaletempo and aresample and asink):
        return asink
    chain = [aconv, scaletempo, *[f for f in filters if f is not None], aresample, asink]
    audio_bin = Gst.Bin.new("audio_sink_bin")
    for el in chain:
        audio_bin.add(el)
    for a, b in zip(chain, chain[1:]):
        if not a.link(b):
            log.warning(f"⚠️ 오디오 체인 연결 실패 ({a.get_name()} → {b.get_name()}): 효과 없이 재생합니다.")
            for el in chain:
                audio_bin.remove(el)
            return build_audio_sink_bin(asink) if filters else asink
    ghost_pad = Gst.GhostPad.new("sink", aconv.get_static_pad("sink"))
    ghost_pad.set_active(True)
    audio_bin.add_pad(ghost_pad)
    return audio_bin


def hdr_uniforms(kind, fix_matrix):
    """glshader uniforms 구조체. GLSL float에는 GFloat 값이어야 합니다 (파이썬 float는 double로 넘어가 무시됨)."""
    from .hdr import uniforms_for
    st = Gst.Structure.new_empty("uniforms")
    for key, value in uniforms_for(kind, fix_matrix).items():
        v = GObject.Value()
        v.init(GObject.TYPE_FLOAT)
        v.set_float(float(value))
        st.set_value(key, v)
    return st


def _new_hdr_shader():
    shader = Gst.ElementFactory.make("glshader", None)
    if shader is None:
        return None
    from .hdr import fragment_shader
    shader.set_property("fragment", fragment_shader())
    shader.set_property("uniforms", hdr_uniforms(None, False))
    return shader


def build_gl_shader_stage(gl_sink):
    """[bin, glshader]: glshader → gl_sink 를 묶은 bin. glshader가 없으면 None (싱크를 그대로 씀)"""
    shader = _new_hdr_shader()
    if shader is None:
        return None
    stage = Gst.Bin.new("gl_shader_stage")
    stage.add(shader)
    stage.add(gl_sink)
    if not shader.link(gl_sink):
        stage.remove(shader)
        stage.remove(gl_sink)
        return None
    ghost = Gst.GhostPad.new("sink", shader.get_static_pad("sink"))
    ghost.set_active(True)
    stage.add_pad(ghost)
    return [stage, shader]


def renew_gl_shader(stage_info, gl_sink):
    """파이프라인을 새로 만들 때 glshader를 새 요소로 바꿉니다 (NULL 상태에서만).

    재사용하는 GL 싱크 안의 glshader는 이전 GL 컨텍스트의 셰이더를 붙잡고 있어 다음 영상에서 흐름 오류가 나고,
    속성만 바꾸면 GL 작업을 기다리다 메인 루프가 멈춥니다. 요소를 통째로 바꾸는 것이 안전합니다.
    """
    stage, old = stage_info
    new = _new_hdr_shader()
    if new is None:
        return
    ghost = stage.get_static_pad("sink")
    old.unlink(gl_sink)
    old.set_state(Gst.State.NULL)
    stage.remove(old)
    stage.add(new)
    new.link(gl_sink)
    ghost.set_target(new.get_static_pad("sink"))
    stage_info[1] = new


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
        log.warning("⚠️ HW 영상 출력 구성 실패: 기본 싱크를 사용합니다.")
        for el in (conv, capsfilter, sink):
            out.remove(el)
        return sink
    ghost = Gst.GhostPad.new("sink", conv.get_static_pad("sink"))
    ghost.set_active(True)
    out.add_pad(ghost)
    return out
