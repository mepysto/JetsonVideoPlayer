import pytest

VID = "dQw4w9WgXcQ"
CANON = f"https://www.youtube.com/watch?v={VID}"


@pytest.mark.parametrize("raw", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://www.youtube.com/watch?v={VID}&list=RD{VID}&start_radio=1",
    f"https://youtu.be/{VID}?t=30",
    f"https://m.youtube.com/watch?v={VID}",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"youtube.com/watch?v={VID}",
    f"여기 링크: https://youtu.be/{VID} 보세요",
])
def test_extract_youtube_url_normalizes(jp, raw):
    assert jp.extract_youtube_url(raw) == CANON


@pytest.mark.parametrize("raw", ["", None, "https://example.com/video.mp4", "just text"])
def test_extract_youtube_url_rejects(jp, raw):
    assert jp.extract_youtube_url(raw) is None


@pytest.mark.parametrize("raw", [
    f"https://youtu.be/{VID}",
    f"https://www.youtube.com/watch?v={VID}&list=PL123",
    f"https://www.youtube.com/live/{VID}",
])
def test_extract_youtube_video_id(jp, raw):
    assert jp.extract_youtube_video_id(raw) == VID


def test_is_youtube_url(jp):
    assert jp.is_youtube_url(f"https://youtu.be/{VID}")
    assert not jp.is_youtube_url("/home/user/video.mp4")
    assert not jp.is_youtube_url(None)
