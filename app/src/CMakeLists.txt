# 핵심 로직(GUI 없음)과 미디어/서비스를 라이브러리로 묶어 앱과 테스트가 함께 씁니다.
file(GLOB_RECURSE CORE_SOURCES CONFIGURE_DEPENDS core/*.cpp core/*.h)
file(GLOB_RECURSE MEDIA_SOURCES CONFIGURE_DEPENDS media/*.cpp media/*.h)
file(GLOB_RECURSE SERVICE_SOURCES CONFIGURE_DEPENDS services/*.cpp services/*.h)
# QML 타입(영상 아이템)은 QML 모듈 쪽에 둡니다
list(FILTER MEDIA_SOURCES EXCLUDE REGEX "/VideoItem\\.(cpp|h)$")

add_library(jvpcore STATIC ${CORE_SOURCES} ${MEDIA_SOURCES} ${SERVICE_SOURCES})
target_include_directories(jvpcore PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/core
                           ${CMAKE_CURRENT_SOURCE_DIR}/media ${CMAKE_CURRENT_SOURCE_DIR}/services)
target_link_libraries(jvpcore PUBLIC Qt6::Core Qt6::Gui Qt6::Quick Qt6::Qml Qt6::Network Qt6::DBus Qt6::Concurrent
                      PkgConfig::GST PkgConfig::ASS PkgConfig::GIO PkgConfig::EGL)
set(REMOTE_STATIC_DIR ${CMAKE_SOURCE_DIR}/resources/remote)
qt_add_resources(jvpcore "remote_static" PREFIX "/remote" BASE ${REMOTE_STATIC_DIR}
  FILES ${REMOTE_STATIC_DIR}/index.html ${REMOTE_STATIC_DIR}/login.html ${REMOTE_STATIC_DIR}/share.html
        ${REMOTE_STATIC_DIR}/icon.svg)
if(JVP_HAVE_NVMM)
  target_compile_definitions(jvpcore PUBLIC JVP_HAVE_NVMM)
  target_include_directories(jvpcore PUBLIC ${JETSON_MMAPI_INCLUDE})
  target_link_libraries(jvpcore PUBLIC ${NVBUFSURFACE_LIB})
endif()

# 앱: QML 모듈 JetsonPlayer (QML 파일 + QML에 보이는 C++ 타입)
qt_add_executable(jetson-player main.cpp)
file(GLOB_RECURSE UI_SOURCES CONFIGURE_DEPENDS ui/*.cpp ui/*.h)
file(GLOB_RECURSE QML_FILES CONFIGURE_DEPENDS RELATIVE ${CMAKE_SOURCE_DIR}/qml ${CMAKE_SOURCE_DIR}/qml/*.qml)
set(QML_SOURCES)
foreach(f ${QML_FILES})
  set(abs ${CMAKE_SOURCE_DIR}/qml/${f})
  # 모듈 안 경로는 app/qml 기준 상대 경로 그대로 (components/JButton.qml 등)
  set_source_files_properties(${abs} PROPERTIES QT_RESOURCE_ALIAS ${f})
  if(f STREQUAL "components/Theme.qml")
    set_source_files_properties(${abs} PROPERTIES QT_QML_SINGLETON_TYPE TRUE)
  endif()
  list(APPEND QML_SOURCES ${abs})
endforeach()
qt_add_qml_module(jetson-player
  URI JetsonPlayer
  DEPENDENCIES QtQuick
  VERSION 1.0
  QML_FILES ${QML_SOURCES}
  SOURCES ${UI_SOURCES} media/VideoItem.cpp media/VideoItem.h
)
target_include_directories(jetson-player PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/ui)
target_link_libraries(jetson-player PRIVATE jvpcore Qt6::QuickControls2)
target_compile_definitions(jetson-player PRIVATE JVP_VERSION="${PROJECT_VERSION}")
