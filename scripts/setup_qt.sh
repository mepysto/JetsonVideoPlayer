#!/usr/bin/env bash
# 최신 Qt(데스크톱, linux arm64)를 ~/Qt 에 설치합니다 (우분투 apt의 Qt 6.4는 너무 오래됨).
#   ./scripts/setup_qt.sh            → 기본 버전 설치
#   QT_VERSION=6.11.3 ./scripts/setup_qt.sh
set -euo pipefail
QT_VERSION=${QT_VERSION:-6.11.3}
AQT_LIB="$HOME/.local/share/aqt-lib"
if [ -d "$HOME/Qt/$QT_VERSION/gcc_arm64" ]; then
    echo "✅ Qt $QT_VERSION 이 이미 있습니다: $HOME/Qt/$QT_VERSION/gcc_arm64"
    exit 0
fi
echo "📦 aqtinstall 준비 ($AQT_LIB)"
python3 -m pip install --quiet --target "$AQT_LIB" --upgrade aqtinstall
echo "⬇️ Qt $QT_VERSION 받는 중 (약 1.7GB)..."
PYTHONPATH="$AQT_LIB" python3 -m aqt install-qt linux_arm64 desktop "$QT_VERSION" linux_gcc_arm64 \
    -O "$HOME/Qt" -m qtimageformats qtshadertools
echo "✅ 설치 완료: $HOME/Qt/$QT_VERSION/gcc_arm64 (CMake가 자동으로 찾습니다)"
