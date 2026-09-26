import pytest
from gi.repository import Gst

from jetson_player.media.gst_setup import seek_flags


def test_fast_seek_snaps_to_nearest_keyframe():
    flags = seek_flags("fast")
    assert flags & Gst.SeekFlags.FLUSH
    assert flags & Gst.SeekFlags.KEY_UNIT
    assert flags & Gst.SeekFlags.SNAP_NEAREST == Gst.SeekFlags.SNAP_NEAREST
    assert not flags & Gst.SeekFlags.ACCURATE


def test_accurate_seek_decodes_to_exact_position():
    flags = seek_flags("accurate")
    assert flags & Gst.SeekFlags.FLUSH
    assert flags & Gst.SeekFlags.ACCURATE
    assert not flags & Gst.SeekFlags.KEY_UNIT


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        seek_flags("sloppy")
