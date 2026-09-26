import pytest

from jetson_player.media.codecs import chroma_and_depth, nvdec_supports


@pytest.mark.parametrize("pix_fmt,expected", [
    ("yuv420p", ("420", 8)), ("yuvj420p", ("420", 8)), ("yuv420p10le", ("420", 10)),
    ("p010le", ("420", 10)), ("nv12", ("420", 8)), ("yuv444p12le", ("444", 12)),
    ("yuv422p10le", ("422", 10)), ("gbrp", ("444", 8)), ("", (None, 8)),
])
def test_chroma_and_depth(pix_fmt, expected):
    assert chroma_and_depth(pix_fmt) == expected


@pytest.mark.parametrize("codec,pix_fmt,profile,ok", [
    ("h264", "yuv420p", "High", True),
    ("h264", "yuv420p10le", "High 10", False),          # H.264 10-bit
    ("h264", "yuv444p", "High 4:4:4 Predictive", False),
    ("hevc", "yuv420p10le", "Main 10", True),
    ("hevc", "yuv444p10le", "Rext", False),
    ("vp9", "yuv420p", "Profile 0", True),
    ("vp9", "yuv420p10le", "Profile 2", True),          # 실측: nvv4l2decoder 재생 확인
    ("vp9", "yuv444p12le", "Profile 3", False),         # 실측: 첫 프레임에서 실패
    ("av1", "yuv420p10le", "Main", True),               # 실측: nvv4l2decoder 재생 확인
    ("av1", "yuv420p12le", "Professional", False),
    ("vp8", "yuv420p", "", False),
    ("mpeg4", "yuv420p", "", False),
    ("hevc", "", "Main", True),                          # 형식 정보 부족 → 코덱으로 판단
    ("vp9", "", "Profile 1", False),
])
def test_nvdec_supports(codec, pix_fmt, profile, ok):
    assert nvdec_supports(codec, pix_fmt, profile)[0] is ok


def test_aliases():
    assert nvdec_supports("avc1", "yuv420p")[0] and nvdec_supports("hvc1", "yuv420p")[0] and nvdec_supports("av01", "yuv420p")[0]
