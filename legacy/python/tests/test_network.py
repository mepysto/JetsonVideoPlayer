import os

from jetson_player import network
from jetson_player.network import (clean_locations, display_name, is_gvfs_path, is_network_uri, normalize_uri,
                                   remember_location, uri_for_path)

ROOT = "/run/user/1000/gvfs/smb-share:server=nas,share=video"


def test_normalize_uri():
    assert normalize_uri("  smb://nas/video/ ") == "smb://nas/video"
    assert normalize_uri("SMB://nas/video") == "smb://nas/video"
    assert normalize_uri("\\\\NAS\\video\\드라마") == "smb://NAS/video/드라마"


def test_is_network_uri():
    assert is_network_uri("smb://nas/video") and is_network_uri("nfs://nas/export")
    assert not is_network_uri("/home/me/Videos") and not is_network_uri("https://youtu.be/x")


def test_display_name():
    assert display_name("smb://nas/video/%EB%93%9C%EB%9D%BC%EB%A7%88") == "nas/video/드라마"


def test_is_gvfs_path(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert is_gvfs_path(ROOT + "/a.mkv")
    assert not is_gvfs_path("/run/user/1000/gvfsx/a.mkv") and not is_gvfs_path("/home/a.mkv")


def test_remember_and_clean_locations():
    locs = remember_location([], "smb://nas/video", ROOT)
    locs = remember_location(locs, "nfs://nas/export", "/run/user/1000/gvfs/nfs:host=nas,prefix=%2Fexport")
    locs = remember_location(locs, "smb://nas/video", ROOT)   # 다시 쓰면 맨 앞으로
    assert [l["uri"] for l in locs] == ["smb://nas/video", "nfs://nas/export"]
    assert clean_locations([{"uri": "https://x", "path": "/p"}, "junk", {"uri": "smb://a/b", "path": 3}]) == []
    assert len(clean_locations([{"uri": f"smb://nas/{i}", "path": f"/p{i}"} for i in range(30)])) == network.MAX_LOCATIONS


def test_uri_for_path_maps_back_for_remount():
    locs = [{"uri": "smb://nas/video", "path": ROOT, "name": "nas/video"}]
    assert uri_for_path(locs, ROOT) == "smb://nas/video"
    assert uri_for_path(locs, os.path.join(ROOT, "드라마", "ep 1.mkv")) == "smb://nas/video/%EB%93%9C%EB%9D%BC%EB%A7%88/ep%201.mkv"
    assert uri_for_path(locs, ROOT + "x/a.mkv") is None
    assert uri_for_path(locs, "/home/a.mkv") is None


def test_settings_keep_list_values(tmp_path, monkeypatch):
    from jetson_player import settings as settings_mod
    s = settings_mod.Settings(str(tmp_path / "settings.json"))
    s.set("network_locations", [{"uri": "smb://nas/v", "path": "/p", "name": "n"}])
    got = s.get("network_locations")
    got.append("mutated")
    assert s.get("network_locations") == [{"uri": "smb://nas/v", "path": "/p", "name": "n"}]
    s.set("network_locations", "not a list")
    assert s.get("network_locations") == []
