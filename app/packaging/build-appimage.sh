#!/usr/bin/env bash
# jetson-player AppImage 만들기 (설치 없이 바로 실행: chmod +x 후 더블클릭 또는 ./Jetson_Video_Player-*.AppImage)
#   ./app/packaging/build-appimage.sh      → app/build-appimage/Jetson_Video_Player-<버전>-aarch64.AppImage
# 필요: 최신 Qt (~/Qt/<버전>/gcc_arm64, 또는 CMAKE_PREFIX_PATH), cmake, ninja, 인터넷(appimagetool 처음 한 번 받기)
#
# 함께 넣는 것: Qt 런타임·QML 모듈, libass(자막)와 그 의존성, libxcb-cursor
# 기기 것을 쓰는 것: GStreamer와 플러그인(NVDEC nvv4l2decoder 포함), NVIDIA/GL 드라이버, glib
#   → 보드의 JetPack 드라이버와 반드시 맞아야 하므로 넣지 않습니다.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(dirname "$HERE")"
BUILD="$APP/build-appimage"
APPDIR="$BUILD/AppDir"
JOBS=${JOBS:-3}   # 8GB 보드에서 컴파일러를 너무 많이 띄우면 메모리가 부족합니다
ARCH=aarch64

cmake -S "$APP" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release -DJVP_DEPLOY_QT=ON -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_INSTALL_LIBDIR=lib
ninja -j"$JOBS" -C "$BUILD" jetson-player
rm -rf "$APPDIR"
DESTDIR="$APPDIR" cmake --install "$BUILD"

# 기본 JetPack에 없을 수 있는 라이브러리를 함께 넣습니다
for lib in libass.so.9 libunibreak.so.5 libfribidi.so.0 libxcb-cursor.so.0; do
    src=$(ldconfig -p | awk -v l="$lib" '$1 == l && /aarch64|AArch64/ { print $NF; exit }')
    [ -n "$src" ] || { echo "❌ $lib 없음 (sudo apt install 로 먼저 설치하세요)" >&2; exit 1; }
    cp -L "$src" "$APPDIR/usr/lib/$lib"
done

# 메뉴 항목·아이콘 (appimagetool은 AppDir 최상위의 .desktop과 아이콘을 씁니다)
install -Dm644 "$HERE/jetson-player.desktop" "$APPDIR/usr/share/applications/jetson-player.desktop"
install -Dm644 "$APP/resources/remote/icon.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/jetson-player.svg"
cp "$HERE/jetson-player.desktop" "$APPDIR/"
cp "$APP/resources/remote/icon.svg" "$APPDIR/jetson-player.svg"
ln -sf jetson-player.svg "$APPDIR/.DirIcon"

cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
# 실행 파일의 RPATH는 직접 링크한 라이브러리만 찾으므로, libass가 쓰는 libunibreak 등을 위해 추가합니다
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$HERE/usr/bin/jetson-player" "$@"
RUN
chmod 755 "$APPDIR/AppRun"

TOOL="$BUILD/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fL -o "$TOOL.part" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod 755 "$TOOL.part" && mv "$TOOL.part" "$TOOL"
fi
VERSION=$(sed -n 's/^project(jetson-player VERSION \([0-9.]*\).*/\1/p' "$APP/CMakeLists.txt")
OUT="$BUILD/Jetson_Video_Player-$VERSION-$ARCH.AppImage"
# FUSE가 없는 환경에서도 appimagetool 자체가 돌도록 풀어서 실행합니다
# 임시 이름으로 만든 뒤 바꿔치기 (이전 AppImage가 실행 중이어도 덮어쓸 수 있게)
ARCH=$ARCH VERSION=$VERSION APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --no-appstream "$APPDIR" "$OUT.part"
mv -f "$OUT.part" "$OUT"
echo "📦 $OUT"
