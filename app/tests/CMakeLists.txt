# QtTest 단위 테스트: tests/test_*.cpp 파일마다 실행 파일 하나
file(GLOB TEST_SOURCES CONFIGURE_DEPENDS test_*.cpp)
foreach(src ${TEST_SOURCES})
  get_filename_component(name ${src} NAME_WE)
  add_executable(${name} ${src})
  target_link_libraries(${name} PRIVATE jvpcore Qt6::Test)
  add_test(NAME ${name} COMMAND ${name})
  set_tests_properties(${name} PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endforeach()
