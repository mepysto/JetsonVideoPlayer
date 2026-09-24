#!/usr/bin/env bash
# ==============================================================================
# Jetson Video Player Uninstaller
# ==============================================================================
set -e

TARGET_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

if [ "$1" = "--system" ] || [ "$EUID" -eq 0 ]; then
    TARGET_DIR="/usr/local/bin"
    DESKTOP_DIR="/usr/share/applications"
    ICON_DIR="/usr/share/icons/hicolor/scalable/apps"
fi

echo "🗑️ Jetson Video Player 등록 항목을 제거합니다..."

rm -f "$TARGET_DIR/jetson-player"
rm -f "$TARGET_DIR/jetson_player"
rm -f "$DESKTOP_DIR/jetson-player.desktop"
rm -f "$ICON_DIR/jetson-player.svg"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

echo "✅ 제거가 완료되었습니다."
echo "ℹ️ 설정과 이어보기 기록은 남겨 두었습니다: ~/.config/jetson_video_player, ~/.cache/jetson_video_player"
echo "ℹ️ AI 엔진을 지우려면: rm -rf ~/.local/share/jetson_video_player"
