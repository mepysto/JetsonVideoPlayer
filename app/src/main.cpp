// Jetson Video Player (C++ / Qt6 / QML)
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QSurfaceFormat>
#include <QTimer>

#include "PlayerEngine.h"
#include "VideoItem.h"

int main(int argc, char *argv[])
{
    // 영상 프레임을 EGLImage로 GL에 올리므로 X11에서도 EGL + GLES 컨텍스트를 씁니다.
    if (qEnvironmentVariableIsEmpty("QT_XCB_GL_INTEGRATION"))
        qputenv("QT_XCB_GL_INTEGRATION", "xcb_egl");
    QSurfaceFormat fmt;
    fmt.setRenderableType(QSurfaceFormat::OpenGLES);
    fmt.setVersion(3, 0);
    fmt.setSwapInterval(1);
    QSurfaceFormat::setDefaultFormat(fmt);
    QQuickWindow::setGraphicsApi(QSGRendererInterface::OpenGL);

    QGuiApplication app(argc, argv);
    jvp::PlayerEngine::initGStreamer();
    qmlRegisterType<jvp::VideoItem>("JetsonPlayer.Video", 1, 0, "VideoItem");

    jvp::PlayerEngine engine;
    QQmlApplicationEngine qml;
    qml.rootContext()->setContextProperty("engine", &engine);
    qml.rootContext()->setContextProperty("frameBridge", engine.frameBridge());
    qml.load(QUrl(QStringLiteral("qrc:/Main.qml")));
    if (qml.rootObjects().isEmpty())
        return 1;
    if (qEnvironmentVariableIsSet("JVP_ONTOP"))
        if (auto *w = qobject_cast<QQuickWindow *>(qml.rootObjects().value(0)))
            w->setFlags(w->flags() | Qt::WindowStaysOnTopHint);
    // 테스트용: JVP_GRAB=경로:지연ms → 렌더링된 창을 이미지로 저장 (영상 GL 렌더링 포함)
    const QString grab = qEnvironmentVariable("JVP_GRAB");
    if (!grab.isEmpty()) {
        const QString path = grab.section(':', 0, 0);
        const int delay = grab.section(':', 1, 1).toInt();
        QTimer::singleShot(delay, [&qml, path] {
            if (auto *w = qobject_cast<QQuickWindow *>(qml.rootObjects().value(0)))
                w->grabWindow().save(path);
            qInfo() << "GRABBED" << path << "rendered frames" << 0;
        });
    }
    if (argc > 1) {
        jvp::PlayerEngine::OpenOptions opt;
        opt.hwOutput = qEnvironmentVariable("JVP_HW_VIDEO", "1") != "0";
        engine.open(jvp::pathToUri(QString::fromLocal8Bit(argv[1])), opt);
    }
    return app.exec();
}
