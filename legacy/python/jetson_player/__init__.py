"""Jetson Video Player: NVIDIA Jetson 하드웨어 가속(nvv4l2decoder) GTK3/GStreamer 영상 플레이어.

GTK는 import 시점에 디스플레이에 연결하므로, 하위 모듈이 로드되기 전에
이 파일에서 실행 환경(PATH, DISPLAY)과 gi 라이브러리 버전을 먼저 설정합니다.
"""
import glob
import os

import gi

# Deno 및 Node.js 런타임 경로 환경변수 자동 보정 (yt-dlp의 4K/1080p 고화질 디사이퍼링 완벽 지원)
NODE_PATHS = [
    os.path.expanduser("~/.deno/bin"),
    os.path.expanduser("~/.local/bin"),
    # nvm으로 설치된 Node.js (버전이 높은 것부터)
    *sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin")), reverse=True),
    "/usr/bin",
    "/usr/local/bin",
]
for p in NODE_PATHS:
    if os.path.isdir(p) and p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{p}:{os.environ.get('PATH', '')}"

# 환경 변수 자동 설정 (cannot open display 에러 방지)
if "DISPLAY" not in os.environ:
    if os.path.exists("/tmp/.X11-unix/X1"):
        os.environ["DISPLAY"] = ":1"
    else:
        os.environ["DISPLAY"] = ":0"
if "XDG_RUNTIME_DIR" not in os.environ:
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"

# 필요한 GStreamer 및 GTK 컴포넌트 버전 고정
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GstPbutils', '1.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkX11', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
gi.require_version('GdkPixbuf', '2.0')
