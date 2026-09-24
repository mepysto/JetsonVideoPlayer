"""웹 리모컨 HTTP 서버 통합 테스트 (실제 소켓, 가짜 플레이어)"""
import http.client
import http.server
import json
import threading
import time

import pytest

from jetson_player.remote import server as srv
from jetson_player.remote.auth import RemoteAuth
from jetson_player.remote.events import EventBroker


class FakePlayer:
    def __init__(self):
        self.commands = []

    def get_remote_status(self):
        return {"title": "t", "is_playing": True}

    def handle_remote_command(self, **params):
        self.commands.append(params)

    def remote_thumbnail_path(self, i):
        return None

    def remote_playlist_thumbnail_path(self, i):
        return None


@pytest.fixture
def remote(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "SSE_HEARTBEAT_SEC", 0.2)
    player, broker = FakePlayer(), EventBroker()
    handler = type("H", (srv.JetsonWebRemoteHandler,), {
        "player": player, "auth": RemoteAuth("4242", str(tmp_path / "tokens.json")), "broker": broker})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], player, broker
    broker.close()
    server.shutdown()
    server.server_close()


def request(port, method, path, body=None, cookie=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if cookie:
        headers["Cookie"] = cookie
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = c.getresponse()
    return r, r.read()


def login(port):
    r, _ = request(port, "POST", "/api/login", {"pin": "4242"})
    assert r.status == 200
    return r.getheader("Set-Cookie").split(";")[0]


def test_requires_login_and_serves_login_page(remote):
    port, player, _ = remote
    assert request(port, "GET", "/api/status")[0].status == 401
    assert request(port, "POST", "/api/cmd", {"action": "next"})[0].status == 401
    r, body = request(port, "GET", "/")
    assert r.status == 200 and "로그인" in body.decode()
    assert player.commands == []


def test_manifest_and_icon_without_login(remote):
    port, _, _ = remote
    r, body = request(port, "GET", "/manifest.json")
    assert r.status == 200 and json.loads(body)["start_url"] == "/"
    assert request(port, "GET", "/icon.svg")[0].status == 200


def test_commands_need_json_post(remote):
    port, player, _ = remote
    cookie = login(port)
    assert request(port, "GET", "/api/cmd?action=next", cookie=cookie)[0].status == 404
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("POST", "/api/cmd", body="action=next", headers={"Cookie": cookie, "Content-Type": "application/x-www-form-urlencoded"})
    assert c.getresponse().status == 400
    r, _ = request(port, "POST", "/api/cmd", {"action": "seek_abs", "sec": 12, "evil": "x"}, cookie=cookie)
    assert r.status == 200 and player.commands == [{"action": "seek_abs", "sec": 12}]


def test_qr_link_login_redirects_with_cookie(remote):
    port, _, _ = remote
    r, _ = request(port, "GET", "/?pin=4242")
    assert r.status == 302 and r.getheader("Location") == "/"
    assert "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Strict" in r.getheader("Set-Cookie")


def test_sse_sends_snapshot_retry_and_ping(remote):
    port, _, broker = remote
    broker.publish("status", {"n": 1})
    cookie = login(port)
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/api/events", headers={"Cookie": cookie})
    r = c.getresponse()
    assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
    seen, end = [], time.time() + 3
    while time.time() < end and not ("event: ping" in seen and any(l.startswith("data: {\"n\":2") for l in seen)):
        line = r.fp.readline().decode().strip()
        if line:
            seen.append(line)
        if line == 'data: {"n":1}':
            broker.publish("status", {"n": 2})
    assert "retry: 2000" in seen
    assert 'data: {"n":1}' in seen and 'data: {"n":2}' in seen
    assert "event: ping" in seen
