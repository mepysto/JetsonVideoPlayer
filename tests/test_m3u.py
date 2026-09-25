import os

from jetson_player.library import is_playlist_file, parse_m3u, write_m3u


def test_parse_m3u_relative_absolute_and_skips(tmp_path):
    (tmp_path / "shows").mkdir()
    for n in ("a.mkv", "shows/b 1.mp4"):
        (tmp_path / n).write_bytes(b"x")
    other = tmp_path / "elsewhere.mkv"
    other.write_bytes(b"x")
    pl = tmp_path / "list.m3u8"
    pl.write_text("#EXTM3U\n#EXTINF:-1,A\na.mkv\n\nshows/b 1.mp4\n"
                  f"{other}\nfile://{tmp_path}/a.mkv\nhttps://example.com/x.mp4\nmissing.mkv\nnotes.txt\n",
                  encoding="utf-8")
    videos, skipped = parse_m3u(str(pl))
    assert [os.path.relpath(v, tmp_path) for v in videos] == ["a.mkv", os.path.join("shows", "b 1.mp4"), "elsewhere.mkv"]
    assert skipped == 3


def test_parse_m3u_cp949(tmp_path):
    (tmp_path / "드라마.mkv").write_bytes(b"x")
    pl = tmp_path / "old.m3u"
    pl.write_bytes("드라마.mkv\n".encode("cp949"))
    assert [os.path.basename(v) for v in parse_m3u(str(pl))[0]] == ["드라마.mkv"]


def test_write_then_parse_round_trip(tmp_path):
    (tmp_path / "sub").mkdir()
    paths = [tmp_path / "sub" / "x.mkv", tmp_path / "y.mp4"]
    for p in paths:
        p.write_bytes(b"x")
    dest = tmp_path / "sub" / "saved.m3u8"
    write_m3u([str(p) for p in paths], str(dest))
    text = dest.read_text(encoding="utf-8")
    assert text.startswith("#EXTM3U") and "\nx.mkv\n" in text and str(paths[1]) in text   # 밖은 절대 경로
    assert parse_m3u(str(dest)) == ([str(p) for p in paths], 0)
    assert is_playlist_file("a.M3U8") and not is_playlist_file("a.mkv")
