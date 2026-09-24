"""스마트폰 웹 리모컨 HTTP 핸들러"""
import http.server
import json
import os
import urllib.parse


REMOTE_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
with open(REMOTE_HTML_PATH, encoding="utf-8") as _f:
    REMOTE_HTML = _f.read()


class JetsonWebRemoteHandler(http.server.BaseHTTPRequestHandler):
    player = None

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(REMOTE_HTML.encode("utf-8"))
        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = self.player.get_remote_status() if self.player else {}
            self.wfile.write(json.dumps(status).encode("utf-8"))
        elif path == "/api/cmd":
            action = query.get("action", [""])[0]
            val = query.get("val", [None])[0]
            index = query.get("index", [None])[0]
            delta = query.get("delta", [None])[0]
            percent = query.get("percent", [None])[0]
            url = query.get("url", [None])[0]
            quality = query.get("quality", ["best"])[0]

            if self.player:
                self.player.handle_remote_command(action, val=val, index=index, delta=delta, percent=percent, url=url, quality=quality)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()
