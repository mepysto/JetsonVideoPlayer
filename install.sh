#!/usr/bin/env bash
# ==============================================================================
# Jetson Video Player Installer
# ==============================================================================
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_SOURCE="$PROJECT_DIR/bin/jetson-player"
PY_SCRIPT="$PROJECT_DIR/jetson_player.py"

# 실행 권한 부여
chmod +x "$PY_SCRIPT"
chmod +x "$BIN_SOURCE"

# 설치 타겟 경로 결정 (기본: ~/.local/bin, --system: /usr/local/bin)
TARGET_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

if [ "$1" = "--system" ] || [ "$EUID" -eq 0 ]; then
    TARGET_DIR="/usr/local/bin"
    DESKTOP_DIR="/usr/share/applications"
fi

mkdir -p "$TARGET_DIR"
mkdir -p "$DESKTOP_DIR"

# 1. 실행 명령어 심볼릭 링크 생성 (jetson-player 및 jetson_player)
echo "🚀 Jetson Video Player 실행 파일을 $TARGET_DIR 에 등록합니다..."
ln -sf "$BIN_SOURCE" "$TARGET_DIR/jetson-player"
ln -sf "$BIN_SOURCE" "$TARGET_DIR/jetson_player"

# 2. Desktop 파일 등록 (애플리케이션 메뉴 및 파일 브라우저 연동)
DESKTOP_FILE="$DESKTOP_DIR/jetson-player.desktop"
echo "🖥️ 데스크톱 애플리케이션 항목 등록: $DESKTOP_FILE"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Name=Jetson Video Player
Comment=High-performance 4K 60FPS Video Player for NVIDIA Jetson
Exec=$TARGET_DIR/jetson-player %F
Terminal=false
Categories=AudioVideo;Player;Video;
MimeType=video/mp4;video/x-matroska;video/quicktime;video/webm;video/x-msvideo;video/avi;
StartupNotify=true
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo "=============================================================================="
echo "✅ 설치가 완료되었습니다!"
echo "=============================================================================="
echo "이제 터미널 어디서든 아래 명령어로 동영상 또는 폴더를 바로 재생할 수 있습니다:"
echo ""
echo "   jetson-player /경로/동영상파일.mp4"
echo "   jetson-player /경로/동영상폴더/"
echo "   jetson_player /경로/동영상폴더/"
echo ""
echo "※ PATH 확인: $TARGET_DIR 이 PATH에 포함되어 있어야 합니다."
echo "=============================================================================="
