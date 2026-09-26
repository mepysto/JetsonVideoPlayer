include("/home/btree/Dev/JetsonVideoPlayer/app/build-deb/.qt/QtDeploySupport.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/jetson-player-plugins.cmake" OPTIONAL)
set(__QT_DEPLOY_I18N_CATALOGS "qtbase;qtdeclarative")

qt6_deploy_qml_imports(TARGET jetson-player PLUGINS_FOUND plugins_found)
qt6_deploy_runtime_dependencies(
    EXECUTABLE "/home/btree/Dev/JetsonVideoPlayer/app/build-deb/src/jetson-player"
    ADDITIONAL_MODULES ${plugins_found}
    GENERATE_QT_CONF
    NO_TRANSLATIONS
)