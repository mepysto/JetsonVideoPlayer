#!/usr/bin/env bash
# Jetson Video Player (C++) 제거 — 설정·이어보기 기록은 남겨 둡니다
set -e
PREFIX="$HOME/.local"; DESKTOP_DIR="$HOME/.local/share/applications"; ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
if [ "$1" = "--system" ] || [ "$EUID" -eq 0 ]; then
    PREFIX=/usr/local; DESKTOP_DIR=/usr/share/applications; ICON_DIR=/usr/share/icons/hicolor/scalable/apps
fi
rm -f "$PREFIX/bin/jetson-player" "$PREFIX/bin/jetson_player" "$DESKTOP_DIR/jetson-player.desktop" "$ICON_DIR/jetson-player.svg"
rm -rf "$PREFIX/share/jetson-player"
command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
echo "✅ 제거했습니다. 설정·기록: ~/.config/jetson_video_player, ~/.cache/jetson_video_player"
echo "ℹ️ .deb로 설치했다면: sudo apt remove jetson-player"
