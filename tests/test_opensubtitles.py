import io
import json
import os
import stat
import urllib.error

import pytest

from jetson_player.subtitles import opensubtitles as osub


def test_moviehash_of_zero_file_is_its_size(tmp_path):
    f = tmp_path / "zero.bin"
    f.write_bytes(b"\0" * 131072)
    assert osub.moviehash(str(f)) == "0000000000020000"


def test_moviehash_sums_head_and_tail_words(tmp_path):
    f = tmp_path / "v.bin"
    data = bytearray(200_000)
    data[0:8] = (1).to_bytes(8, "little")                 # 앞 64KB 첫 단어
    data[-8:] = (0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")  # 뒤 64KB 마지막 단어 (오버플로 확인)
    f.write_bytes(bytes(data))
    assert osub.moviehash(str(f)) == f"{(200_000 + 1 + 0xFFFFFFFFFFFFFFFF) & 0xFFFFFFFFFFFFFFFF:016x}"
    small = tmp_path / "s.bin"
    small.write_bytes(b"x" * 1000)
    with pytest.raises(osub.OpenSubtitlesError):
        osub.moviehash(str(small))


@pytest.mark.parametrize("name, expected", [
    ("The.Movie.Name.2019.1080p.WEB-DL.x265-GRP.mkv", "The Movie Name 2019"),
    ("[SubGroup] Show_Name - 05 (1080p).mkv", "Show Name - 05"),
    ("드라마 12화.mp4", "드라마 12화"),
])
def test_query_from_filename(name, expected):
    assert osub.query_from_filename(name) == expected


SEARCH_JSON = {"data": [
    {"attributes": {"language": "en", "download_count": 900, "moviehash_match": False, "release": "Other.Release",
                    "feature_details": {"title": "Movie", "year": 2019}, "files": [{"file_id": 11, "file_name": "a.srt"}]}},
    {"attributes": {"language": "ko", "download_count": 10, "moviehash_match": True, "release": "Exact.Release",
                    "feature_details": {"title": "Movie", "year": 2019}, "files": [{"file_id": 22, "file_name": "b.ass"}]}},
    {"attributes": {"language": "ko", "files": []}},
]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(routes, log):
    def opener(req, timeout=None):
        log.append((req.get_method(), req.full_url, dict(req.header_items()), req.data))
        for prefix, payload in routes:
            if req.full_url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        raise AssertionError(req.full_url)
    return opener


def test_search_sorts_hash_match_first_and_sends_key(tmp_path):
    video = tmp_path / "Movie.2019.1080p.mkv"
    video.write_bytes(b"\0" * 200_000)
    calls = []
    client = osub.OpenSubtitlesClient("KEY", opener=fake_opener([(osub.API_BASE + "/subtitles", SEARCH_JSON)], calls))
    results = client.search(str(video), languages=("ko", "en"))
    assert [r.file_id for r in results] == [22, 11]
    assert results[0].hash_match and results[0].title == "Movie (2019)"
    method, url, headers, _ = calls[0]
    assert method == "GET" and "moviehash=" in url and "languages=en%2Cko" in url and "query=Movie+2019" in url
    assert headers["Api-key"] == "KEY" and headers["User-agent"].startswith("JetsonVideoPlayer")


def test_download_logs_in_and_fetches_link(tmp_path):
    calls = []
    routes = [(osub.API_BASE + "/login", {"token": "TOK"}),
              (osub.API_BASE + "/download", {"link": "https://dl.example/x.srt", "remaining": 5}),
              ("https://dl.example/", b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")]
    client = osub.OpenSubtitlesClient("KEY", username="me", password="pw", opener=fake_opener(routes, calls))
    assert client.download(22).startswith(b"1\n")
    assert [c[1].split("/")[-1] for c in calls] == ["login", "download", "x.srt"]
    assert calls[1][2]["Authorization"] == "Bearer TOK" and json.loads(calls[1][3]) == {"file_id": 22}


def test_http_errors_become_readable(tmp_path):
    err = urllib.error.HTTPError(osub.API_BASE + "/download", 406, "x", {}, io.BytesIO(b'{"message": "quota exceeded"}'))
    client = osub.OpenSubtitlesClient("KEY", opener=fake_opener([(osub.API_BASE, err)], []))
    with pytest.raises(osub.OpenSubtitlesError, match="406 quota exceeded"):
        client.download(1)


def test_credentials_file_is_private(tmp_path, monkeypatch):
    monkeypatch.delenv("JVP_OPENSUBTITLES_KEY", raising=False)
    path = str(tmp_path / "cfg" / "os.json")
    osub.save_credentials({"api_key": "K", "username": "", "password": "p"}, path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert osub.load_credentials(path) == {"api_key": "K", "password": "p"}
    monkeypatch.setenv("JVP_OPENSUBTITLES_KEY", "ENV")
    assert osub.load_credentials(path)["api_key"] == "ENV"


def test_save_path(tmp_path):
    assert osub.subtitle_save_path("/v/movie.mkv", "ko", "x.ASS") == "/v/movie.ko.ass"
    assert osub.subtitle_save_path("/v/movie.mkv", "pt-BR", "x.zip") == "/v/movie.pt-br.srt"
