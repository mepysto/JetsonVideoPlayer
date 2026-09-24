#!/usr/bin/env bash
# ==============================================================================
# Jetson Video Player Installer
#   ./install.sh                 ~/.local/bin 에 실행 명령 등록 (사용자 설치)
#   sudo ./install.sh --system   /usr/local/bin 에 등록 (모든 사용자)
#   ./install.sh --set-default   영상 파일을 더블클릭하면 이 플레이어로 열리도록 기본 앱 지정
# ==============================================================================
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_SOURCE="$PROJECT_DIR/bin/jetson-player"
PY_SCRIPT="$PROJECT_DIR/jetson_player.py"
ICON_SOURCE="$PROJECT_DIR/jetson_player/remote/static/icon.svg"

SYSTEM=0
SET_DEFAULT=0
for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM=1 ;;
        --set-default) SET_DEFAULT=1 ;;
        -h|--help) sed -n '3,6p' "$0"; exit 0 ;;
        *) echo "알 수 없는 옵션: $arg"; exit 1 ;;
    esac
done
[ "$EUID" -eq 0 ] && SYSTEM=1

# 영상 형식 (파일 관리자 연동 및 --set-default 대상)
MIME_TYPES="video/mp4;video/x-matroska;video/webm;video/quicktime;video/x-msvideo;video/avi;video/mp2t;video/x-m4v;video/mpeg;"

# 0. 실행 환경 점검 (필수 구성 요소가 없으면 안내 후 중단)
echo "=============================================================================="
echo "🔎 실행 환경 점검"
echo "=============================================================================="
if ! python3 "$PROJECT_DIR/scripts/check_deps.py"; then
    echo ""
    echo "위 안내에 따라 필수 패키지를 설치한 뒤 다시 실행하세요."
    exit 1
fi
echo ""

chmod +x "$PY_SCRIPT" "$BIN_SOURCE" "$PROJECT_DIR"/scripts/*.sh

if [ "$SYSTEM" -eq 1 ]; then
    TARGET_DIR="/usr/local/bin"
    DESKTOP_DIR="/usr/share/applications"
    ICON_DIR="/usr/share/icons/hicolor/scalable/apps"
else
    TARGET_DIR="$HOME/.local/bin"
    DESKTOP_DIR="$HOME/.local/share/applications"
    ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
fi
mkdir -p "$TARGET_DIR" "$DESKTOP_DIR" "$ICON_DIR"

# 1. 실행 명령어 심볼릭 링크 (jetson-player 및 jetson_player)
echo "🚀 실행 파일을 $TARGET_DIR 에 등록합니다..."
ln -sf "$BIN_SOURCE" "$TARGET_DIR/jetson-player"
ln -sf "$BIN_SOURCE" "$TARGET_DIR/jetson_player"

# 2. 아이콘과 데스크톱 항목 (애플리케이션 메뉴, 파일 관리자 '다른 앱으로 열기')
cp "$ICON_SOURCE" "$ICON_DIR/jetson-player.svg"
DESKTOP_FILE="$DESKTOP_DIR/jetson-player.desktop"
echo "🖥️ 데스크톱 애플리케이션 항목 등록: $DESKTOP_FILE"
cat <<DESKTOP > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Name=Jetson Video Player
GenericName=Video Player
Comment=NVDEC hardware-accelerated video player for NVIDIA Jetson
Exec=$TARGET_DIR/jetson-player %f
Icon=jetson-player
Terminal=false
Categories=AudioVideo;Player;Video;
MimeType=$MIME_TYPES
StartupNotify=true
DESKTOP

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q "$(dirname "$(dirname "$ICON_DIR")")" >/dev/null 2>&1 || true
fi

# 3. (선택) 영상 파일 기본 앱으로 지정
if [ "$SET_DEFAULT" -eq 1 ]; then
    if command -v xdg-mime >/dev/null 2>&1; then
        echo "🎬 영상 파일 기본 앱을 Jetson Video Player로 지정합니다..."
        IFS=';' read -ra TYPES <<< "$MIME_TYPES"
        for t in "${TYPES[@]}"; do
            [ -n "$t" ] && xdg-mime default jetson-player.desktop "$t"
        done
    else
        echo "⚠️ xdg-mime이 없어 기본 앱을 지정하지 못했습니다."
    fi
fi

echo "=============================================================================="
echo "✅ 설치가 완료되었습니다!"
echo "=============================================================================="
echo "터미널 어디서든 아래 명령어로 동영상 또는 폴더를 바로 재생할 수 있습니다:"
echo ""
echo "   jetson-player /경로/동영상파일.mp4"
echo "   jetson-player /경로/동영상폴더/"
echo ""
case ":$PATH:" in
    *":$TARGET_DIR:"*) ;;
    *) echo "⚠️ $TARGET_DIR 이 PATH에 없습니다. ~/.bashrc 에 추가하세요:  export PATH=\"$TARGET_DIR:\$PATH\"" ;;
esac
if [ "$SET_DEFAULT" -eq 0 ]; then
    echo "💡 영상 파일을 더블클릭하면 이 플레이어로 열리게 하려면:  ./install.sh --set-default"
fi
echo ""
echo "🤖 (선택) AI 자막 생성:        $PROJECT_DIR/scripts/setup_whisper.sh"
echo "🌐 (선택) AI 자막 한국어 번역:  $PROJECT_DIR/scripts/setup_translator.sh"
echo "=============================================================================="
