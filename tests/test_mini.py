from jetson_player.ui.mini import mini_height


def test_mini_height_follows_video_aspect():
    assert mini_height(480, (1920, 1080)) == 270
    assert mini_height(480, (1080, 1920)) == 853      # 세로 영상
    assert mini_height(480, None) == 270               # 모르면 16:9
    assert mini_height(100, (4000, 100)) == 90         # 최소 높이
