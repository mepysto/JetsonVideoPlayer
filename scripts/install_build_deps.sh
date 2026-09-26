#!/usr/bin/env bash
# C++ 앱을 빌드하는 데 필요한 시스템 패키지 (sudo 필요)
set -euo pipefail
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config python3-pip \
    libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav \
    gstreamer1.0-tools gstreamer1.0-pulseaudio \
    libass-dev libglib2.0-dev libegl-dev libgles-dev libxcb-cursor0 libxkbcommon-x11-0 \
    libfontconfig1-dev libdbus-1-dev
# Jetson: NVDEC 출력을 복사 없이 화면에 올리는 데 필요 (nvbufsurface.h). Jetson이 아니면 없어도 빌드됩니다.
if dpkg -l nvidia-l4t-core >/dev/null 2>&1; then
    sudo apt-get install -y --no-install-recommends nvidia-l4t-jetson-multimedia-api || true
fi
echo "✅ 빌드 도구 준비 완료. 다음: ./scripts/setup_qt.sh && ./install.sh"
