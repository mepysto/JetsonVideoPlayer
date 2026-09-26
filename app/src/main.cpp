// Jetson Video Player (C++ / Qt 6 / QML)
//   jetson-player [파일 | 폴더 | 재생목록.m3u8 | YouTube 주소] [--kiosk] [--tv | --desktop] [--log-level LEVEL]
#include <QCommandLineParser>
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQuickWindow>
#include <QSurfaceFormat>
#include <QTimer>

#include "AppController.h"
#include "FrameBridge.h"
#include "Log.h"
#include "PlayerEngine.h"
#include "QrImageProvider.h"
#include "YouTubeController.h"

#include <QSocketNotifier>
#include <csignal>
#include <cstdio>
#include <sys/socket.h>
#include <unistd.h>

namespace {
// SIGTERM/SIGINT(systemd 정지, Ctrl+C) → Qt 이벤트 루프에서 정상 종료 (이어보기 위치·설정 저장)
int g_signalFd[2] = {-1, -1};
void onSignal(int)
{
    const char c = 1;
    [[maybe_unused]] auto n = ::write(g_signalFd[0], &c, 1);
}
void installQuitOnSignal(QObject *parent)
{
    if (::socketpair(AF_UNIX, SOCK_STREAM, 0, g_signalFd) != 0)
        return;
    auto *notifier = new QSocketNotifier(g_signalFd[1], QSocketNotifier::Read, parent);
    QObject::connect(notifier, &QSocketNotifier::activated, parent, [] {
        char c;
        [[maybe_unused]] auto n = ::read(g_signalFd[1], &c, 1);
        QCoreApplication::quit();
    });
    struct sigaction sa = {};
    sa.sa_handler = onSignal;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_RESTART;
    sigaction(SIGTERM, &sa, nullptr);
    sigaction(SIGINT, &sa, nullptr);
}
} // namespace

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
    QGuiApplication::setApplicationName(QStringLiteral("jetson-player"));
    QGuiApplication::setApplicationDisplayName(QStringLiteral("Jetson Video Player"));
    QGuiApplication::setApplicationVersion(QStringLiteral(JVP_VERSION));
    QGuiApplication::setDesktopFileName(QStringLiteral("jetson-player"));

    QCommandLineParser cli;
    cli.setApplicationDescription(QStringLiteral("Jetson 하드웨어 가속 동영상 플레이어"));
    cli.addHelpOption();
    cli.addVersionOption();
    cli.addPositionalArgument(QStringLiteral("input"), QStringLiteral("동영상 파일, 폴더, M3U 재생목록 또는 YouTube 주소"));
    const QCommandLineOption kiosk(QStringLiteral("kiosk"), QStringLiteral("전체화면 고정 (TV 박스·전용 기기)"));
    const QCommandLineOption tv(QStringLiteral("tv"), QStringLiteral("TV 화면 (리모컨·큰 글씨)"));
    const QCommandLineOption desktop(QStringLiteral("desktop"), QStringLiteral("데스크톱 화면"));
    const QCommandLineOption level(QStringLiteral("log-level"), QStringLiteral("DEBUG / INFO / WARNING / ERROR"),
                                   QStringLiteral("level"));
    const QCommandLineOption noServices(QStringLiteral("no-services"), QStringLiteral("웹 리모컨·MPRIS를 켜지 않음 (테스트용)"));
    cli.addOptions({kiosk, tv, desktop, level, noServices});
    cli.process(app);

    installQuitOnSignal(&app);
    jvp::log::setupLogging(cli.isSet(level) ? cli.value(level) : qEnvironmentVariable("JVP_LOG_LEVEL"));
    jvp::PlayerEngine::initGStreamer();

    jvp::AppController::Options opt;
    opt.input = cli.positionalArguments().value(0);
    opt.kiosk = cli.isSet(kiosk);
    opt.uiMode = cli.isSet(tv) ? QStringLiteral("tv") : cli.isSet(desktop) ? QStringLiteral("desktop") : QString();
    opt.startServices = !cli.isSet(noServices);
    auto *controller = new jvp::AppController(opt, &app);
    // 파이썬 버전과 같게: 명령줄로 준 경로가 잘못됐으면 창을 띄우지 않고 끝냅니다.
    if (!opt.input.isEmpty() && !jvp::YouTubeController::isYoutubeUrl(opt.input) && controller->playlistPaths().isEmpty()) {
        std::fprintf(stderr, "재생할 수 있는 영상이 없습니다: %s\n", qPrintable(opt.input));
        return 1;
    }

    QQmlApplicationEngine engine;
    engine.addImageProvider(QStringLiteral("qr"), new jvp::QrImageProvider);
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, [] { QCoreApplication::exit(1); },
                     Qt::QueuedConnection);
    engine.loadFromModule("JetsonPlayer", "Main");
    auto *window = engine.rootObjects().isEmpty() ? nullptr : qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    if (!window)
        return 1;
    controller->attachWindow(window);
    QObject::connect(controller, &jvp::AppController::quitRequested, &app, [window] { window->close(); });
    QObject::connect(&app, &QGuiApplication::aboutToQuit, controller, [controller, window] {
        controller->shutdown(window->width(), window->height(), window->visibility() == QWindow::Maximized);
    });

    // 테스트용: JVP_ONTOP=1 → 항상 위, JVP_GRAB=경로:지연ms → 그린 창을 이미지로 저장 (영상 GL 렌더링 포함)
    if (qEnvironmentVariableIsSet("JVP_ONTOP"))
        window->setFlags(window->flags() | Qt::WindowStaysOnTopHint);
    const QString grab = qEnvironmentVariable("JVP_GRAB");
    if (!grab.isEmpty()) {
        const QString path = grab.section(':', 0, 0);
        const int delay = grab.section(':', 1, 1).toInt();
        QTimer::singleShot(delay, window, [window, controller, path] {
            window->grabWindow().save(path);
            qInfo().noquote() << "GRABBED" << path << "rendered frames"
                              << controller->engine()->frameBridge()->renderedFrames();
        });
    }
    // 창이 뜬 뒤 첫 영상 재생·서비스 시작
    QTimer::singleShot(0, controller, &jvp::AppController::start);
    const int rc = app.exec();
    jvp::log::shutdownLogging();
    return rc;
}
