cmake_minimum_required(VERSION 3.22)
project(jetson-player VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

# 최신 Qt(aqt로 ~/Qt/<버전>/gcc_arm64에 설치)를 기본으로 찾습니다. 우분투 apt의 Qt 6.4는 너무 오래돼
# (QML 모듈·싱글톤 선언, loadFromModule, QtQuick.Dialogs 등) 지원하지 않습니다.
if(NOT CMAKE_PREFIX_PATH AND NOT DEFINED ENV{CMAKE_PREFIX_PATH})
  file(GLOB _jvp_qt_dirs LIST_DIRECTORIES true "$ENV{HOME}/Qt/6.*/gcc_arm64" "$ENV{HOME}/Qt/6.*/gcc_64")
  if(_jvp_qt_dirs)
    list(SORT _jvp_qt_dirs COMPARE NATURAL ORDER DESCENDING)
    list(GET _jvp_qt_dirs 0 _jvp_qt_dir)
    set(CMAKE_PREFIX_PATH ${_jvp_qt_dir})
    message(STATUS "Qt: ${_jvp_qt_dir}")
  endif()
endif()

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Quick QuickControls2 Qml Network DBus Concurrent Test)
qt_standard_project_setup(REQUIRES 6.8)
# Qt 라이브러리가 시스템 경로 밖(~/Qt)에 있으므로 설치한 실행 파일에도 경로를 남깁니다.
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH ON)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0
                  gstreamer-pbutils-1.0 gstreamer-audio-1.0 gstreamer-tag-1.0)
pkg_check_modules(ASS REQUIRED IMPORTED_TARGET libass)
pkg_check_modules(GIO REQUIRED IMPORTED_TARGET gio-2.0)
pkg_check_modules(EGL REQUIRED IMPORTED_TARGET egl glesv2)

# Jetson NVMM (NvBufSurface) — 있으면 NVDEC 출력을 복사 없이 GL 텍스처로 씁니다.
set(JETSON_MMAPI_INCLUDE /usr/src/jetson_multimedia_api/include)
find_library(NVBUFSURFACE_LIB nvbufsurface PATHS /usr/lib/aarch64-linux-gnu/nvidia /usr/lib/aarch64-linux-gnu/tegra)
if(NVBUFSURFACE_LIB AND EXISTS ${JETSON_MMAPI_INCLUDE}/nvbufsurface.h)
  set(JVP_HAVE_NVMM ON)
  message(STATUS "Jetson NVMM zero-copy: ${NVBUFSURFACE_LIB}")
else()
  set(JVP_HAVE_NVMM OFF)
  message(STATUS "Jetson NVMM zero-copy: not available (software upload path only)")
endif()

add_subdirectory(src)

enable_testing()
add_subdirectory(tests)

include(GNUInstallDirs)
install(TARGETS jetson-player RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
# 로컬 번역(NLLB) 보조 프로세스 스크립트 — Translator.cpp가 ../share/jetson-player/ 에서 찾습니다
install(PROGRAMS tools/nllb_worker.py DESTINATION ${CMAKE_INSTALL_DATADIR}/jetson-player)
