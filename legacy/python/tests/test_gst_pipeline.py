"""실제 GStreamer 파이프라인 테스트 (화면 없이 fakesink로 재생)"""
import gi
import pytest

gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from jetson_player.media.gst_setup import build_audio_sink_bin, make_audio_output, seek_flags  # noqa: E402

Gst.init(None)


def wait_for(pipeline, types, timeout_sec=10):
    msg = pipeline.get_bus().timed_pop_filtered(int(timeout_sec * Gst.SECOND), types | Gst.MessageType.ERROR)
    assert msg is not None, "타임아웃"
    if msg.type == Gst.MessageType.ERROR:
        pytest.fail(f"파이프라인 오류: {msg.parse_error()}")
    return msg


def make_playbin(path, audio_sink=None):
    pb = Gst.ElementFactory.make("playbin", None)
    pb.set_property("uri", Gst.filename_to_uri(str(path)))
    pb.set_property("video-sink", Gst.ElementFactory.make("fakesink", None))
    pb.set_property("audio-sink", audio_sink or Gst.ElementFactory.make("fakesink", None))
    return pb


def current_rate(pipeline):
    q = Gst.Query.new_segment(Gst.Format.TIME)
    assert pipeline.query(q)
    return q.parse_segment()[0]


@pytest.fixture
def playbin(media_dir):
    pb = make_playbin(media_dir / "a.mkv")
    pb.set_state(Gst.State.PAUSED)
    wait_for(pb, Gst.MessageType.ASYNC_DONE)
    yield pb
    pb.set_state(Gst.State.NULL)


def test_audio_sink_bin_plays_to_eos_with_filters(media_dir):
    dyn = Gst.ElementFactory.make("audiodynamic", None)
    gain = Gst.ElementFactory.make("volume", None)
    asink = make_audio_output(av_offset_ms=0, factory="fakesink")
    audio_bin = build_audio_sink_bin(asink, [dyn, gain])
    assert isinstance(audio_bin, Gst.Bin) and audio_bin.get_by_name("scaletempo")
    pb = make_playbin(media_dir / "a.mkv", audio_bin)
    pb.set_state(Gst.State.PLAYING)
    try:
        wait_for(pb, Gst.MessageType.EOS, timeout_sec=15)
    finally:
        pb.set_state(Gst.State.NULL)


def test_audio_sink_bin_falls_back_without_required_elements(monkeypatch):
    asink = Gst.ElementFactory.make("fakesink", None)
    real_make = Gst.ElementFactory.make
    monkeypatch.setattr(Gst.ElementFactory, "make", lambda name, n=None: None if name == "scaletempo" else real_make(name, n))
    assert build_audio_sink_bin(asink) is asink


def test_accurate_seek_lands_on_target(playbin):
    target = int(1.37 * Gst.SECOND)
    assert playbin.seek(1.0, Gst.Format.TIME, seek_flags("accurate"), Gst.SeekType.SET, target, Gst.SeekType.NONE, -1)
    wait_for(playbin, Gst.MessageType.ASYNC_DONE)
    ok, pos = playbin.query_position(Gst.Format.TIME)
    assert ok and abs(pos - target) <= 40 * Gst.MSECOND   # 25fps 한 프레임 이내


def test_seek_keeps_rate_but_seek_simple_resets_it(playbin):
    """seek_to()가 seek_simple 대신 rate를 넘기는 이유 (배속 초기화 버그 회귀 방지)"""
    playbin.seek(2.0, Gst.Format.TIME, seek_flags("accurate"), Gst.SeekType.SET, 0, Gst.SeekType.NONE, -1)
    wait_for(playbin, Gst.MessageType.ASYNC_DONE)
    assert current_rate(playbin) == pytest.approx(2.0)
    playbin.seek(2.0, Gst.Format.TIME, seek_flags("accurate"), Gst.SeekType.SET, Gst.SECOND, Gst.SeekType.NONE, -1)
    wait_for(playbin, Gst.MessageType.ASYNC_DONE)
    assert current_rate(playbin) == pytest.approx(2.0)
    playbin.seek_simple(Gst.Format.TIME, seek_flags("accurate"), Gst.SECOND // 2)
    wait_for(playbin, Gst.MessageType.ASYNC_DONE)
    assert current_rate(playbin) == pytest.approx(1.0)


def test_thumbnail_job_finishes_on_generated_video(media_dir, tmp_path, monkeypatch):
    from jetson_player.media import thumbnails

    monkeypatch.setattr(thumbnails, "THUMB_ROOT", str(tmp_path / "thumbs"))
    job = thumbnails.ThumbnailJob(str(media_dir / "b.mkv"))
    job._run()   # 스레드 대신 직접 실행 (콜백 없음)
    index = thumbnails.load_thumbnail_index(str(media_dir / "b.mkv"))
    assert index and index["complete"] and index["files"]
    assert all((tmp_path / "thumbs").rglob(f) for f in index["files"])


def test_passthrough_helpers(media_dir):
    from jetson_player.media.gst_setup import PASSTHROUGH_CAPS, audio_codec_of, sink_passthrough_formats
    assert audio_codec_of(str(media_dir / "a.mkv")) == "audio/x-vorbis"
    assert sink_passthrough_formats("fakesink") == set()          # 원음을 받는다고 알리지 않는 싱크
    assert sink_passthrough_formats("no-such-sink") == set()
    assert "audio/x-ac3" in PASSTHROUGH_CAPS


def test_hdr_shader_on_gl_matches_reference():
    """톤매핑 셰이더를 실제 GL에서 돌려 파이썬 참조 계산과 비교 (uniform은 GFloat여야 적용됨)"""
    import numpy as np
    from jetson_player.media.gst_setup import hdr_uniforms
    from jetson_player.media.hdr import VERTEX_SHADER, fragment_shader, reference
    if not all(Gst.ElementFactory.find(n) for n in ("glupload", "glshader", "gldownload")):
        pytest.skip("GL 요소 없음")
    p = Gst.parse_launch("videotestsrc num-buffers=3 pattern=solid-color foreground-color=0xffc83c28 "
                         "! video/x-raw,format=RGBA,width=16,height=16 ! glupload ! glshader name=sh "
                         "! gldownload ! video/x-raw,format=RGBA ! appsink name=s")
    sh = p.get_by_name("sh")
    sh.set_property("vertex", VERTEX_SHADER)
    sh.set_property("fragment", fragment_shader())
    sh.set_property("uniforms", hdr_uniforms("pq", True))
    p.set_state(Gst.State.PLAYING)
    sample = p.get_by_name("s").emit("try-pull-sample", 10 * Gst.SECOND)
    err = p.get_bus().pop_filtered(Gst.MessageType.ERROR)
    p.set_state(Gst.State.NULL)
    if sample is None or err is not None:
        pytest.skip(f"GL을 쓸 수 없습니다: {err.parse_error()[0].message if err else 'no sample'}")
    buf = sample.get_buffer()
    gpu = np.frombuffer(buf.extract_dup(0, buf.get_size()), dtype=np.uint8)[:3].astype(int)
    ref = np.round(reference(np.array([200, 60, 40]) / 255, "pq", True) * 255).astype(int)
    assert np.max(np.abs(gpu - ref)) <= 2, (gpu, ref)
