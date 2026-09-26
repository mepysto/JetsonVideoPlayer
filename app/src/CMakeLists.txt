# 핵심 로직(GUI 없음)과 미디어/서비스를 라이브러리로 묶어 앱과 테스트가 함께 씁니다.
file(GLOB_RECURSE CORE_SOURCES CONFIGURE_DEPENDS core/*.cpp core/*.h)
file(GLOB_RECURSE MEDIA_SOURCES CONFIGURE_DEPENDS media/*.cpp media/*.h)
file(GLOB_RECURSE SERVICE_SOURCES CONFIGURE_DEPENDS services/*.cpp services/*.h)
file(GLOB_RECURSE UI_SOURCES CONFIGURE_DEPENDS ui/*.cpp ui/*.h)

add_library(jvpcore STATIC ${CORE_SOURCES} ${MEDIA_SOURCES} ${SERVICE_SOURCES} ${UI_SOURCES})
target_include_directories(jvpcore PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/core
                           ${CMAKE_CURRENT_SOURCE_DIR}/media ${CMAKE_CURRENT_SOURCE_DIR}/services ${CMAKE_CURRENT_SOURCE_DIR}/ui)
target_link_libraries(jvpcore PUBLIC Qt6::Core Qt6::Gui Qt6::Quick Qt6::Qml Qt6::Network Qt6::DBus Qt6::Concurrent
                      PkgConfig::GST PkgConfig::ASS PkgConfig::GIO PkgConfig::EGL)
# 웹 리모컨 페이지: 파이썬 버전의 정적 파일 그대로 → qrc:/remote/ (같은 API를 쓰므로 수정 없이 동작)
set(REMOTE_STATIC_DIR ${CMAKE_SOURCE_DIR}/resources/remote)
qt_add_resources(jvpcore "remote_static" PREFIX "/remote" BASE ${REMOTE_STATIC_DIR}
  FILES ${REMOTE_STATIC_DIR}/index.html ${REMOTE_STATIC_DIR}/login.html ${REMOTE_STATIC_DIR}/share.html
        ${REMOTE_STATIC_DIR}/icon.svg)
if(JVP_HAVE_NVMM)
  target_compile_definitions(jvpcore PUBLIC JVP_HAVE_NVMM)
  target_include_directories(jvpcore PUBLIC ${JETSON_MMAPI_INCLUDE})
  target_link_libraries(jvpcore PUBLIC ${NVBUFSURFACE_LIB})
endif()

qt_add_executable(jetson-player main.cpp)
# QML 파일은 app/qml 아래 상대 경로 그대로 qrc:/ 에 올립니다 (예: qrc:/Main.qml, qrc:/components/Osd.qml)
file(GLOB_RECURSE QML_FILES CONFIGURE_DEPENDS RELATIVE ${CMAKE_SOURCE_DIR}/qml ${CMAKE_SOURCE_DIR}/qml/*.qml ${CMAKE_SOURCE_DIR}/qml/*.js)
set(QML_ABS)
foreach(f ${QML_FILES})
  set_source_files_properties(${CMAKE_SOURCE_DIR}/qml/${f} PROPERTIES QT_RESOURCE_ALIAS ${f})
  list(APPEND QML_ABS ${CMAKE_SOURCE_DIR}/qml/${f})
endforeach()
qt_add_qml_module(jetson-player
  URI JetsonPlayer
  VERSION 1.0
  QML_FILES ${QML_ABS}
  RESOURCE_PREFIX /
  NO_RESOURCE_TARGET_PATH
  NO_PLUGIN_OPTIONAL
)
target_link_libraries(jetson-player PRIVATE jvpcore)
