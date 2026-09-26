"""스마트폰 웹 리모컨 HTTP 핸들러

인증: 4자리 PIN으로 로그인하면 쿠키 토큰을 발급합니다 (QR 코드의 ?pin= 링크로 자동 로그인).
보안: 상태를 바꾸는 요청은 JSON POST만 받으며(다른 사이트의 요청은 브라우저가 사전 차단),
      쿠키는 SameSite=Strict/HttpOnly로 발급합니다.
실시간: /api/events 로 상태 변경을 SSE로 푸시합니다 (폴링 불필요).
"""
import http.server
import ipaddress
import json
import logging
import os
import sys
import urllib.parse

log = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
COOKIE_NAME = "jvp_token"
MAX_BODY = 64 * 1024
SSE_HEARTBEAT_SEC = 5          # 폰이 연결 생존을 판단할 수 있게 자주 ping을 보냅니다.
SSE_WRITE_TIMEOUT_SEC = 10     # 응답 없는 클라이언트가 스레드를 붙잡지 않도록
# 원격 명령에서 받을 수 있는 인자 (그 외는 무시)
COMMAND_FIELDS = ("action", "val", "index", "delta", "percent", "url", "quality", "sec", "minutes")


def _read_static(name):
    with open(os.path.join(STATIC_DIR, name), encoding="utf-8") as f:
        return f.read()


REMOTE_HTML = _read_static("index.html")
LOGIN_HTML = _read_static("login.html")
SHARE_HTML = _read_static("share.html")
ICON_SVG = _read_static("icon.svg")
MANIFEST_JSON = json.dumps({
    "name": "Jetson Player Remote", "short_name": "Jetson 리모컨", "start_url": "/", "display": "standalone",
    "background_color": "#0c1017", "theme_color": "#0c1017",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
}, ensure_ascii=False)


class RemoteHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True   # SSE 연결이 남아 있어도 종료를 막지 않음

    def handle_error(self, request, client_address):
        """폰 화면 꺼짐·네트워크 전환으로 끊긴 연결은 흔하므로 조용히 넘기고, 그 외만 기록합니다."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return
        log.warning(f"⚠️ 리모컨 요청 처리 실패 ({client_address[0]})", exc_info=True)


def is_lan_client(address):
    """같은 네트워크(사설·링크 로컬·루프백 주소)에서 온 연결인지 판단합니다."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local


class JetsonWebRemoteHandler(http.server.BaseHTTPRequestHandler):
    player = None       # 플레이어 창 (get_remote_status, handle_remote_command, remote_thumbnail_path)
    auth = None         # RemoteAuth
    broker = None       # EventBroker
    lan_only = True     # 사설 네트워크 밖(공인 IP)에서 온 연결을 거부
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # ---- 공통 --------------------------------------------------------------
    def _token(self):
        cookies = self.headers.get("Cookie", "")
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME:
                return value
        return self.headers.get("X-JVP-Token", "")

    def _authorized(self):
        return self.auth is None or self.auth.is_valid(self._token())

    def _send(self, code, body=b"", content_type="application/json", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, headers=None):
        self._send(code, json.dumps(obj, ensure_ascii=False), headers=headers)

    def _cookie_header(self, token):
        return {"Set-Cookie": f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"}

    def _reject_non_lan(self):
        if self.lan_only and not is_lan_client(self.client_address[0]):
            self.close_connection = True   # 읽지 않은 요청 본문이 다음 요청으로 해석되지 않도록
            self._send(403, b"forbidden", "text/plain")
            return True
        return False

    # ---- GET -----------------------------------------------------------
    def do_GET(self):
        if self._reject_non_lan():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            pin = query.get("pin", [None])[0]
            if pin and self.auth is not None:
                # QR 코드 링크: PIN으로 바로 로그인하고 주소창에서 PIN을 지웁니다.
                token = self.auth.login(self.client_address[0], pin)
                if token and token != "locked":
                    headers = self._cookie_header(token)
                    headers["Location"] = "/"
                    self._send(302, b"", "text/plain", headers)
                    return
            page = REMOTE_HTML if self._authorized() else LOGIN_HTML
            self._send(200, page, "text/html; charset=utf-8")
            return

        if path == "/share":
            # 폰에서 링크 보내기 (북마클릿·공유). 페이지는 상태를 바꾸지 않고, 버튼을 누르면 /api/cmd로 POST합니다.
            self._send(200, SHARE_HTML, "text/html; charset=utf-8")
            return
        if path == "/manifest.json":
            self._send(200, MANIFEST_JSON, "application/manifest+json")
            return
        if path == "/icon.svg":
            self._send(200, ICON_SVG, "image/svg+xml", {"Cache-Control": "max-age=86400"})
            return

        if not path.startswith("/api/"):
            self._send(404, b"not found", "text/plain")
            return
        if not self._authorized():
            self._json(401, {"error": "login required"})
            return

        if path == "/api/status":
            self._json(200, self.player.get_remote_status() if self.player else {})
        elif path == "/api/events":
            self._serve_events()
        elif path == "/api/thumb":
            self._serve_thumbnail(query)
        elif path == "/api/search":
            q = query.get("q", [""])[0][:200]
            self._json(200, self.player.remote_search(q) if self.player else {"indexing": False, "results": []})
        else:
            self._send(404, b"not found", "text/plain")

    def _serve_thumbnail(self, query):
        """i=N: 현재 영상의 N번째 썸네일, p=N: 재생목록 N번 영상의 대표 썸네일(캐시가 있을 때)"""
        def as_int(key):
            try:
                return int(query.get(key, [""])[0])
            except ValueError:
                return None
        path = None
        if self.player:
            if "p" in query:
                path = self.player.remote_playlist_thumbnail_path(as_int("p"))
            else:
                path = self.player.remote_thumbnail_path(as_int("i"))
        if not path or not os.path.isfile(path):
            self._send(404, b"", "image/jpeg")
            return
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=3600"})

    def _serve_events(self):
        """SSE: 접속 즉시 현재 상태를 보내고, 이후 변경될 때마다 이벤트를 보냅니다."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(SSE_WRITE_TIMEOUT_SEC)
        version, latest = self.broker.snapshot()
        try:
            # retry: 끊겼을 때 브라우저가 2초 후 자동 재연결
            self.wfile.write(b"retry: 2000\n\n")
            for name, (_ver, data) in latest.items():
                self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.write(b"event: ping\ndata: {}\n\n")
            self.wfile.flush()
            while not self.broker.closed:
                items, version = self.broker.wait_newer(version, SSE_HEARTBEAT_SEC)
                if items:
                    for name, data in items:
                        self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode("utf-8"))
                else:
                    self.wfile.write(b"event: ping\ndata: {}\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass

    # ---- POST ----------------------------------------------------------
    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return None
        if "application/json" not in self.headers.get("Content-Type", ""):
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def do_POST(self):
        if self._reject_non_lan():
            return
        path = urllib.parse.urlparse(self.path).path
        data = self._read_json()
        if data is None:
            self._json(400, {"error": "JSON body required"})
            return

        if path == "/api/login":
            token = self.auth.login(self.client_address[0], str(data.get("pin", ""))) if self.auth else "open"
            if token == "locked":
                self._json(429, {"error": "too many attempts, try again in 5 minutes"})
            elif token:
                self._json(200, {"status": "ok"}, headers=self._cookie_header(token))
            else:
                self._json(401, {"error": "wrong PIN"})
            return

        if not self._authorized():
            self._json(401, {"error": "login required"})
            return
        if path == "/api/cmd":
            params = {k: data[k] for k in COMMAND_FIELDS if k in data and data[k] is not None}
            if not params.get("action"):
                self._json(400, {"error": "action required"})
                return
            if self.player:
                self.player.handle_remote_command(**params)
            self._json(200, {"status": "ok"})
        else:
            self._send(404, b"not found", "text/plain")
