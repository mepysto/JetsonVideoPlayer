cmake_minimum_required(VERSION 3.22)
project(jetson-player VERSION 2.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

find_package(Qt6 6.4 REQUIRED COMPONENTS Core Gui Quick Qml Network DBus Concurrent Test)
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
