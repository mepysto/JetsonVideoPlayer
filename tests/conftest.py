import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def jp():
    """GTK를 import하지 않는 순수 모듈들의 공개 이름을 하나의 네임스페이스로 묶어 제공합니다."""
    from jetson_player import library, storage, youtube
    from jetson_player.subtitles import parse, timeline

    ns = types.SimpleNamespace()
    for module in (parse, timeline, youtube, library, storage):
        for name in dir(module):
            if not name.startswith("_"):
                setattr(ns, name, getattr(module, name))
    return ns


def make_test_video(path, seconds=3, fps=25, audio=True):
    """videotestsrc/audiotestsrc로 짧은 MKV(VP8 + Vorbis)를 만듭니다. 필요한 요소가 없으면 테스트를 건너뜁니다.

    MJPEG는 쓰지 않습니다: Jetson에서 GdkX11을 불러온 프로세스가 HW JPEG 디코더로 재생하면 크래시합니다.
    """
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    need = ["videotestsrc", "vp8enc", "matroskamux", "filesink"] + (["audiotestsrc", "vorbisenc", "audioconvert"] if audio else [])
    missing = [n for n in need if not Gst.ElementFactory.find(n)]
    if missing:
        pytest.skip(f"GStreamer 요소 없음: {', '.join(missing)}")
    desc = (f"videotestsrc num-buffers={seconds * fps} ! video/x-raw,width=320,height=180,framerate={fps}/1 "
            f"! timeoverlay ! vp8enc deadline=1 keyframe-max-dist={fps // 5} ! matroskamux name=m ! filesink location={path} ")
    if not Gst.ElementFactory.find("timeoverlay"):
        desc = desc.replace("! timeoverlay ", "")
    if audio:
        samples = 1024
        desc += f"audiotestsrc num-buffers={seconds * 44100 // samples} samplesperbuffer={samples} ! audioconvert ! vorbisenc ! m."
    pipeline = Gst.parse_launch(desc)
    pipeline.set_state(Gst.State.PLAYING)
    msg = pipeline.get_bus().timed_pop_filtered(30 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipeline.set_state(Gst.State.NULL)
    if msg is None or msg.type != Gst.MessageType.EOS:
        pytest.skip(f"테스트 영상을 만들 수 없습니다: {msg.parse_error() if msg else 'timeout'}")
    return str(path)


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory):
    """3초짜리 테스트 영상 두 개와 각자의 SRT 자막이 든 폴더"""
    d = tmp_path_factory.mktemp("media")
    for name, line in (("a", "AAA line"), ("b", "BBB line")):
        make_test_video(d / f"{name}.mkv")
        (d / f"{name}.srt").write_text(f"1\n00:00:00,000 --> 00:00:03,000\n{line}\n", encoding="utf-8")
    return d
