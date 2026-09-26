#!/usr/bin/env bash
# jetson-player .deb 만들기 (Qt 런타임을 /opt/jetson-player 에 함께 넣습니다)
#   ./app/packaging/build-deb.sh            → app/build-deb/jetson-player_<버전>_arm64.deb
# 필요: 최신 Qt (~/Qt/<버전>/gcc_arm64, 또는 CMAKE_PREFIX_PATH), cmake, ninja, dpkg-deb
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(dirname "$HERE")"
BUILD="$APP/build-deb"
STAGE="$BUILD/stage"
PREFIX=/opt/jetson-player
JOBS=${JOBS:-3}   # 8GB 보드에서 컴파일러를 너무 많이 띄우면 메모리가 부족합니다

cmake -S "$APP" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release -DJVP_DEPLOY_QT=ON -DCMAKE_INSTALL_PREFIX=$PREFIX
ninja -j"$JOBS" -C "$BUILD" jetson-player
rm -rf "$STAGE"
DESTDIR="$STAGE" cmake --install "$BUILD"

VERSION=$(sed -n 's/^project(jetson-player VERSION \([0-9.]*\).*/\1/p' "$APP/CMakeLists.txt")
# 실행 명령, 메뉴 항목, 아이콘, 키오스크 서비스
install -d "$STAGE/usr/bin" "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/scalable/apps" \
           "$STAGE/lib/systemd/system" "$STAGE/etc/default" "$STAGE/DEBIAN"
ln -sf $PREFIX/bin/jetson-player "$STAGE/usr/bin/jetson-player"
install -m755 "$HERE/jetson-player-kiosk" "$STAGE$PREFIX/bin/jetson-player-kiosk"
ln -sf $PREFIX/bin/jetson-player-kiosk "$STAGE/usr/bin/jetson-player-kiosk"
install -m644 "$HERE/jetson-player.desktop" "$STAGE/usr/share/applications/"
install -m644 "$APP/resources/remote/icon.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/jetson-player.svg"
install -m644 "$HERE/jetson-player-kiosk.service" "$STAGE/lib/systemd/system/"
install -m644 "$HERE/jetson-player-kiosk.default" "$STAGE/etc/default/jetson-player-kiosk"

SIZE=$(du -sk "$STAGE" --exclude=DEBIAN | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: jetson-player
Version: $VERSION
Architecture: arm64
Maintainer: Jetson Video Player <noreply@localhost>
Installed-Size: $SIZE
Section: video
Priority: optional
Depends: libgstreamer1.0-0, libgstreamer-plugins-base1.0-0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-libav, gstreamer1.0-pulseaudio, libass9, libglib2.0-0, libxcb-cursor0, libegl1, libgles2
Recommends: nvidia-l4t-gstreamer, yt-dlp, python3
Description: Hardware-accelerated video player for NVIDIA Jetson (Qt/QML)
 NVDEC zero-copy playback, libass subtitles, AI subtitles (whisper.cpp),
 subtitle translation, web remote control, MPRIS, TV/kiosk mode (EGLFS).
CTRL
echo "/etc/default/jetson-player-kiosk" > "$STAGE/DEBIAN/conffiles"
cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
command -v systemctl >/dev/null && systemctl daemon-reload || true
exit 0
POST
cat > "$STAGE/DEBIAN/prerm" <<'PRE'
#!/bin/sh
set -e
if [ "$1" = remove ] && command -v systemctl >/dev/null; then
    systemctl disable --now jetson-player-kiosk.service 2>/dev/null || true
fi
exit 0
PRE
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"
OUT="$BUILD/jetson-player_${VERSION}_arm64.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "📦 $OUT"
