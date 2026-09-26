#!/usr/bin/env bash
# ==============================================================================
# Jetson Video Player (C++ / Qt 6 / QML) 설치
#   ./install.sh                 빌드 후 ~/.local 에 설치 (jetson-player 명령, 앱 메뉴 항목)
#   sudo ./install.sh --system   /usr/local 에 설치 (모든 사용자)
#   ./install.sh --set-default   영상 파일을 더블클릭하면 이 플레이어로 열리게 기본 앱 지정
#   ./install.sh --deb           .deb 패키지를 만들어 설치 (Qt 포함, 키오스크 서비스 포함)
# 처음이라면: ./scripts/install_build_deps.sh && ./scripts/setup_qt.sh
# 이전 Python 버전은 legacy/python/ (jetson-player-py 명령)
# ==============================================================================
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$PROJECT_DIR/app"
SYSTEM=0; SET_DEFAULT=0; DEB=0
for arg in "$@"; do
    case "$arg" in
        --system) SYSTEM=1 ;;
        --set-default) SET_DEFAULT=1 ;;
        --deb) DEB=1 ;;
        -h|--help) sed -n '3,9p' "$0"; exit 0 ;;
        *) echo "알 수 없는 옵션: $arg"; exit 1 ;;
    esac
done
[ "$EUID" -eq 0 ] && SYSTEM=1

if [ "$DEB" -eq 1 ]; then
    "$APP/packaging/build-deb.sh"
    sudo apt-get install -y "$(ls -t "$APP"/build-deb/jetson-player_*_arm64.deb | head -1)"
    exit 0
fi

# 0. 점검: 빌드 도구와 최신 Qt
for tool in cmake ninja pkg-config; do
    command -v "$tool" >/dev/null || { echo "❌ $tool 이 없습니다: ./scripts/install_build_deps.sh"; exit 1; }
done
QT_FOUND=$(compgen -G "$HOME/Qt/6.*/gcc_arm64" || compgen -G "$HOME/Qt/6.*/gcc_64" || true)
if [ -z "$QT_FOUND" ] && [ -z "${CMAKE_PREFIX_PATH:-}" ]; then
    echo "❌ 최신 Qt(6.8 이상)가 없습니다: ./scripts/setup_qt.sh"
    exit 1
fi

if [ "$SYSTEM" -eq 1 ]; then
    PREFIX=/usr/local; DESKTOP_DIR=/usr/share/applications; ICON_DIR=/usr/share/icons/hicolor/scalable/apps
else
    PREFIX="$HOME/.local"; DESKTOP_DIR="$HOME/.local/share/applications"; ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
fi

# 1. 빌드 (8GB 보드에서 메모리가 모자라지 않게 동시 컴파일 3개)
echo "🔨 빌드 중 (처음에는 5분 정도 걸립니다)..."
cmake -S "$APP" -B "$APP/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" >/dev/null
ninja -j"${JOBS:-3}" -C "$APP/build" jetson-player

# 2. 설치: 실행 파일, 번역 보조 스크립트, 메뉴 항목, 아이콘
cmake --install "$APP/build" --prefix "$PREFIX" >/dev/null
# 예전 Python 버전의 jetson_player 링크(이전 경로를 가리켜 깨져 있음)를 정리합니다
[ -L "$PREFIX/bin/jetson_player" ] && ln -sf "$PREFIX/bin/jetson-player" "$PREFIX/bin/jetson_player"
mkdir -p "$DESKTOP_DIR" "$ICON_DIR"
install -m644 "$APP/resources/remote/icon.svg" "$ICON_DIR/jetson-player.svg"
sed "s|^Exec=jetson-player|Exec=$PREFIX/bin/jetson-player|" "$APP/packaging/jetson-player.desktop" > "$DESKTOP_DIR/jetson-player.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$(dirname "$(dirname "$ICON_DIR")")" >/dev/null 2>&1 || true

if [ "$SET_DEFAULT" -eq 1 ] && command -v xdg-mime >/dev/null; then
    for t in video/mp4 video/x-matroska video/webm video/quicktime video/x-msvideo video/avi video/mp2t video/x-m4v video/mpeg; do
        xdg-mime default jetson-player.desktop "$t"
    done
    echo "🎬 영상 파일 기본 앱을 Jetson Video Player로 지정했습니다."
fi

echo "=============================================================================="
echo "✅ 설치 완료: $PREFIX/bin/jetson-player"
echo "   jetson-player /경로/동영상.mp4 | /경로/폴더/ | 재생목록.m3u8 | https://youtu.be/..."
echo "   jetson-player --tv       TV 화면 (리모컨·큰 글씨)"
case ":$PATH:" in *":$PREFIX/bin:"*) ;; *) echo "⚠️ $PREFIX/bin 이 PATH에 없습니다: export PATH=\"$PREFIX/bin:\$PATH\"" ;; esac
echo "🤖 (선택) AI 자막:  $PROJECT_DIR/scripts/setup_whisper.sh"
echo "🌐 (선택) 자막 번역: $PROJECT_DIR/scripts/setup_translator.sh"
echo "📺 전용 기기(키오스크) 모드는 .deb 설치 후: sudo jetson-player-kiosk enable"
echo "=============================================================================="
