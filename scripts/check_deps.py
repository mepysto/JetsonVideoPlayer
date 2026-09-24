#!/usr/bin/env python3
"""Jetson Video Player 실행 환경 점검 (install.sh가 실행, 단독 실행 가능)

필수 항목이 빠졌으면 종료 코드 1, 선택 항목만 빠졌으면 0을 반환하고 설치 명령을 안내합니다.
"""
import importlib
import os
import shutil
import subprocess
import sys

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
problems = {"required": [], "optional": []}


def report(status, name, detail="", required=True, fix=None):
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    if status != OK and fix:
        problems["required" if required else "optional"].append(fix)


def check_python_module(module, name, required=True, fix=None):
    try:
        importlib.import_module(module)
        report(OK, name)
        return True
    except Exception as e:
        report(FAIL if required else WARN, name, f"없음 ({type(e).__name__})", required, fix)
        return False


def check_gi_namespace(namespace, version, fix, required=True):
    try:
        import gi
        gi.require_version(namespace, version)
        importlib.import_module(f"gi.repository.{namespace}")
        report(OK, f"{namespace} {version}")
    except Exception as e:
        report(FAIL if required else WARN, f"{namespace} {version}", f"없음 ({type(e).__name__})", required, fix)


def check_gst_element(element, why, required=True, fix=None):
    try:
        found = subprocess.run(["gst-inspect-1.0", element], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        found = False
    report(OK if found else (FAIL if required else WARN), f"GStreamer {element}", "" if found else why, required, fix)


def main():
    print("🔎 Python / GTK / GStreamer")
    print(f"  {OK} Python {sys.version.split()[0]}")
    if check_python_module("gi", "PyGObject (gi)", fix="python3-gi"):
        check_gi_namespace("Gtk", "3.0", "gir1.2-gtk-3.0")
        check_gi_namespace("Gst", "1.0", "gir1.2-gstreamer-1.0")
        check_gi_namespace("GstPbutils", "1.0", "gir1.2-gst-plugins-base-1.0")
        check_gi_namespace("GstVideo", "1.0", "gir1.2-gst-plugins-base-1.0")
        check_gi_namespace("PangoCairo", "1.0", "gir1.2-pango-1.0")
        check_gi_namespace("GdkX11", "3.0", "gir1.2-gtk-3.0")
    check_python_module("numpy", "numpy (썸네일·장면 분석)", fix="python3-numpy")
    check_python_module("dbus", "dbus-python (미디어 키 · MPRIS)", required=False, fix="python3-dbus")
    check_python_module("yt_dlp", "yt-dlp (YouTube)", required=False, fix="pip:yt-dlp")
    check_python_module("anthropic", "anthropic (Claude API 자막 번역, 선택)", required=False, fix="pip:anthropic")

    print("🎞️ GStreamer 요소")
    check_gst_element("nvv4l2decoder", "NVDEC 하드웨어 디코딩 불가 → 소프트웨어 디코딩으로 재생", required=False, fix="nvidia-l4t-gstreamer")
    check_gst_element("nvvidconv", "하드웨어 영상 변환 불가", required=False, fix="nvidia-l4t-gstreamer")
    check_gst_element("gtkglsink", "영상 출력 요소", fix="gstreamer1.0-gtk3")
    check_gst_element("scaletempo", "배속 재생 음정 보정", fix="gstreamer1.0-plugins-good")
    check_gst_element("audiodynamic", "야간 모드", required=False, fix="gstreamer1.0-plugins-good")
    check_gst_element("avdec_h264", "소프트웨어 디코딩 (하드웨어 미지원 형식)", required=False, fix="gstreamer1.0-libav")

    print("🧰 외부 도구")
    report(OK if shutil.which("ffprobe") else WARN, "ffprobe", "" if shutil.which("ffprobe") else "코덱 판별이 GStreamer로 대체됨 (느림)", False, "ffmpeg")
    whisper = os.path.expanduser("~/.local/share/jetson_video_player/whisper.cpp/build/bin/whisper-cli")
    report(OK if os.path.exists(whisper) else WARN, "AI 자막 엔진 (whisper.cpp)",
           "" if os.path.exists(whisper) else "선택 설치: ./scripts/setup_whisper.sh", False)
    nllb = os.path.expanduser("~/.local/share/jetson_video_player/nllb/model/model.bin")
    report(OK if os.path.exists(nllb) else WARN, "AI 자막 번역 엔진 (NLLB-200)",
           "" if os.path.exists(nllb) else "선택 설치: ./scripts/setup_translator.sh", False)

    apt = sorted({p for p in problems["required"] + problems["optional"] if not p.startswith("pip:")})
    pip = sorted({p[4:] for p in problems["required"] + problems["optional"] if p.startswith("pip:")})
    if apt or pip:
        print("\n📦 설치 안내")
        if apt:
            print(f"   sudo apt install {' '.join(apt)}")
        if pip:
            print(f"   python3 -m pip install --user {' '.join(pip)}")
    if problems["required"]:
        print("\n❌ 필수 구성 요소가 없어 플레이어가 실행되지 않을 수 있습니다.")
        return 1
    print("\n✅ 필수 구성 요소가 모두 준비되었습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
