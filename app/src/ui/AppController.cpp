#include "AppController.h"

#include "AiController.h"
#include "DialogueIndex.h"
#include "Loudness.h"
#include "Log.h"
#include "NetworkMount.h"
#include "OnlineSubsController.h"
#include "PlaylistModel.h"
#include "RemoteInfo.h"
#include "Settings.h"
#include "Shortcuts.h"
#include "Storage.h"
#include "SubtitleController.h"
#include "SystemInfo.h"
#include "YouTubeController.h"

#include <QClipboard>
#include <QDateTime>
#include <QDesktopServices>
#include <QDir>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJSEngine>
#include <QLoggingCategory>
#include <QQmlEngine>
#include <QQuickWindow>
#include <QScreen>
#include <QStandardPaths>
#include <QUrl>

Q_LOGGING_CATEGORY(lcApp, "jvp.app")

namespace jvp {

namespace {
constexpr int kHideControlsMs = 2500;
constexpr int kMiniMargin = 24;
constexpr int kMiniMinWidth = 240;
constexpr int kMiniMaxWidth = 1280;
} // namespace

AppController *AppController::s_instance = nullptr;

AppController *AppController::instance() { return s_instance; }

AppController *AppController::create(QQmlEngine *, QJSEngine *)
{
    // 싱글톤은 main()이 먼저 만들어 둡니다. QML 엔진이 지우지 않도록 C++ 소유로 표시합니다.
    QJSEngine::setObjectOwnership(s_instance, QJSEngine::CppOwnership);
    return s_instance;
}

AppController::AppController(const Options &opt, QObject *parent) : QObject(parent), m_opt(opt)
{
    s_instance = this;
    Settings *s = Settings::instance();

    m_engine = new PlayerEngine(this);
    m_subs = new SubtitleController(this);
    m_subs->setPositionProvider([this] {
        qint64 p = m_engine->position();
        if (p < 0)
            p = m_lastPosNs;
        return p / 1'000'000;
    });
    m_subs->setFontScale(s->doubleValue(QStringLiteral("subtitle_font_scale")));
    m_subs->setAssStyles(s->boolValue(QStringLiteral("subtitle_ass_styles")));
    m_subs->setEmbeddedEnabled(s->boolValue(QStringLiteral("embedded_subs_enabled")));
    connect(m_subs, &SubtitleController::changed, this, &AppController::subtitlesChanged);
    connect(m_subs, &SubtitleController::osd, this, [this](const QString &t) { showOsd(t); });
    connect(m_subs, &SubtitleController::fontScaleChanged, this,
            [](double v) { Settings::instance()->setValue(QStringLiteral("subtitle_font_scale"), v); });
    connect(m_subs, &SubtitleController::embeddedTrackRequested, this, [this](int i) { m_engine->setTextTrack(i); });
    connect(m_subs, &SubtitleController::popupRequested, this, [this] { requestDialog(QStringLiteral("subtitles")); });

    m_playlistModel = new PlaylistModel(this);
    m_playlistModel->setProgressProvider([](const QString &path) {
        const auto p = resumeCache().progress(path);
        // 진행 중이면 진행률 막대, 다 봤고 진행 중이 아니면 ✓ (파이썬과 같게)
        return PlaylistModel::Progress{p.ratio.value_or(-1), p.watched && !p.ratio};
    });
    connect(m_playlistModel, &PlaylistModel::playRequested, this, &AppController::playIndex);
    connect(m_playlistModel, &PlaylistModel::sortCycleRequested, this, &AppController::cyclePlaylistSort);

    m_ai = new AiController(this);
    m_translation = new TranslationController(this);
    m_onlineSubs = new OnlineSubsController(this);
    m_youtube = new YouTubeController(this);
    connect(m_youtube, &YouTubeController::changed, this, &AppController::youtubeChanged);
    m_network = new NetworkMount(this);
    connect(m_network, &NetworkMount::passwordRequested, this,
            [this](const QString &message, const QString &user, const QString &domain, int flags) {
                requestDialog(QStringLiteral("mountPassword"),
                              QVariantMap{{"message", message}, {"user", user}, {"domain", domain}, {"flags", flags}});
            });
    connect(m_network, &NetworkMount::questionAsked, this, [this](const QString &message, const QStringList &choices) {
        requestDialog(QStringLiteral("mountQuestion"), QVariantMap{{"message", message}, {"choices", choices}});
    });
    connect(m_network, &NetworkMount::finished, this, &AppController::onMountFinished);
    m_remoteInfo = new RemoteInfo(this);

    // 엔진 → 재생 정책
    connect(m_engine, &PlayerEngine::asyncDone, this, &AppController::onEngineAsyncDone);
    connect(m_engine, &PlayerEngine::endOfStream, this, &AppController::onEngineEos);
    connect(m_engine, &PlayerEngine::errorOccurred, this, &AppController::onEngineError);
    connect(m_engine, &PlayerEngine::playingChanged, this, &AppController::onEnginePlayingChanged);
    connect(m_engine, &PlayerEngine::streamsChanged, this, &AppController::onStreamsChanged);
    connect(m_engine, &PlayerEngine::chaptersFound, this, &AppController::onChaptersFound);
    connect(m_engine, &PlayerEngine::embeddedText, m_subs, &SubtitleController::addEmbeddedText, Qt::QueuedConnection);
    connect(m_engine, &PlayerEngine::embeddedAss, m_subs, &SubtitleController::addEmbeddedAss, Qt::QueuedConnection);

    // 저장된 설정
    m_volume = s->intValue(QStringLiteral("volume"));
    m_preMuteVolume = m_volume;
    if (s->boolValue(QStringLiteral("muted"))) {
        m_muted = true;
    }
    m_repeatMode = s->stringValue(QStringLiteral("repeat_mode"));
    m_sidebarVisible = s->boolValue(QStringLiteral("sidebar_visible"));
    m_sidebarWidth = s->intValue(QStringLiteral("sidebar_width"));
    m_windowWidth = s->intValue(QStringLiteral("window_width"));
    m_windowHeight = s->intValue(QStringLiteral("window_height"));
    m_windowMaximized = s->boolValue(QStringLiteral("window_maximized"));
    m_hudVisible = s->boolValue(QStringLiteral("hud_visible"));
    m_miniWidth = s->intValue(QStringLiteral("mini_width"));
    connect(s, &Settings::valueChanged, this, &AppController::emitSettings);

    m_positionTimer.setInterval(250);
    connect(&m_positionTimer, &QTimer::timeout, this, &AppController::onPositionTick);
    m_scrubTimer.setSingleShot(true);
    m_scrubTimer.setInterval(150);
    connect(&m_scrubTimer, &QTimer::timeout, this, [this] {
        if (m_scrubTarget >= 0 && m_scrubTarget != m_scrubLast) {
            m_scrubLast = m_scrubTarget;
            seekTo(m_scrubTarget, SeekMode::Fast);
        }
    });
    m_hideTimer.setSingleShot(true);
    m_hideTimer.setInterval(kHideControlsMs);
    connect(&m_hideTimer, &QTimer::timeout, this, &AppController::onHideTimer);
    m_loudnessRamp.setInterval(100);
    connect(&m_loudnessRamp, &QTimer::timeout, this, [this] {
        ++m_loudnessRampStep;
        const double db = m_loudnessRampFrom + (m_loudnessTargetDb - m_loudnessRampFrom) * m_loudnessRampStep / 10.0;
        m_loudnessCurrentDb = db;
        m_engine->setLoudnessGainDb(db);
        if (m_loudnessRampStep >= 10)
            m_loudnessRamp.stop();
    });
    m_sleepTimer.setInterval(1000);
    connect(&m_sleepTimer, &QTimer::timeout, this, &AppController::onSleepTick);
    m_autoplayTimer.setInterval(100);
    connect(&m_autoplayTimer, &QTimer::timeout, this, [this] {
        emit autoplayChanged();
        if (m_autoplayClock.elapsed() >= 5000)
            finishAutoplay(true);
    });
    m_rescanDebounce.setSingleShot(true);
    m_rescanDebounce.setInterval(2000);
    connect(&m_rescanDebounce, &QTimer::timeout, this, [this] { rescanPlaylist(true); });
    m_watchPoll.setInterval(60'000);
    connect(&m_watchPoll, &QTimer::timeout, this, [this] { rescanPlaylist(true); });
    m_flushTimer.setInterval(10'000);
    connect(&m_flushTimer, &QTimer::timeout, this, &AppController::flushCaches);

    // 명령줄 입력 (YouTube 주소는 start()에서 받기 시작)
    if (!m_opt.input.isEmpty() && !YouTubeController::isYoutubeUrl(m_opt.input))
        buildPlaylist(m_opt.input);
    refreshPlaylistModel();
    refreshResumeCards();
}

AppController::~AppController()
{
    if (!m_shuttingDown)
        shutdown(m_windowWidth, m_windowHeight, m_windowMaximized);
    if (s_instance == this)
        s_instance = nullptr;
}

void AppController::attachWindow(QQuickWindow *window)
{
    m_window = window;
}

void AppController::start()
{
    if (m_started)
        return;
    m_started = true;
    m_positionTimer.start();
    m_flushTimer.start();
    if (m_opt.startServices)
        startServices();
    if (!m_playlist.isEmpty()) {
        playCurrent();
        startFolderWatch();
    }
    startBackgroundHwChecker();
    if (!m_opt.input.isEmpty() && YouTubeController::isYoutubeUrl(m_opt.input))
        QTimer::singleShot(0, this, [this] { startYoutube(m_opt.input, QStringLiteral("best")); });
    // 설정을 복원하는 동안에는 OSD를 띄우지 않습니다.
    QTimer::singleShot(0, this, [this] { m_restoringSettings = false; });
}

// ---- 속성 -------------------------------------------------------------------

QString AppController::currentPath() const
{
    return m_index >= 0 && m_index < m_playlist.size() ? m_playlist[m_index] : QString();
}

QString AppController::title() const
{
    const QString p = currentPath();
    if (p.isEmpty())
        return {};
    if (p.startsWith(QLatin1String("http://")) || p.startsWith(QLatin1String("https://")))
        return QStringLiteral("YouTube / 온라인 스트림");
    return QFileInfo(p).fileName();
}

QString AppController::nowPlayingText() const
{
    const QString p = currentPath();
    if (p.isEmpty())
        return QStringLiteral("재생 중인 영상 없음");
    QString name = QFileInfo(p).fileName();
    const QFileInfo root(m_inputPath);
    if (!m_inputPath.isEmpty() && root.isDir()) {
        const QString rel = QDir(root.absoluteFilePath()).relativeFilePath(p);
        if (!rel.startsWith(QLatin1String("..")))
            name = rel;
    }
    return QStringLiteral("재생 중  ·  %1   %2/%3").arg(name).arg(m_index + 1).arg(m_playlist.size());
}

QString AppController::repeatModeLabel() const
{
    static const QHash<QString, QString> names{{"all", "🔁 전체 반복"}, {"one", "🔂 1곡 반복"},
                                               {"none", "➡️ 순차 재생 후 정지"}, {"shuffle", "🔀 셔플 무작위 재생"}};
    return names.value(m_repeatMode, names.value("all"));
}

QString AppController::formatTime(double ms) const
{
    const qint64 total = qMax<qint64>(0, qint64(ms / 1000));
    const qint64 h = total / 3600, m = total % 3600 / 60, s = total % 60;
    return h ? QStringLiteral("%1:%2:%3").arg(h).arg(m, 2, 10, QLatin1Char('0')).arg(s, 2, 10, QLatin1Char('0'))
             : QStringLiteral("%1:%2").arg(m, 2, 10, QLatin1Char('0')).arg(s, 2, 10, QLatin1Char('0'));
}

QString AppController::positionText() const { return formatTime(positionMs()); }

QString AppController::durationText() const
{
    if (m_durationNs <= 0)
        return QStringLiteral("00:00");
    if (Settings::instance()->boolValue(QStringLiteral("time_display_remaining")))
        return QLatin1Char('-') + formatTime(qMax<double>(0, durationMs() - positionMs()));
    return formatTime(durationMs());
}

QObject *AppController::frameBridge() const { return m_engine->frameBridge(); }
QObject *AppController::playlistObject() const { return m_playlistModel; }
PlaylistModel *AppController::playlistObjectTyped() const { return m_playlistModel; }
QObject *AppController::subtitlesObject() const { return m_subs; }
SubtitleController *AppController::subtitlesObjectTyped() const { return m_subs; }
QObject *AppController::aiObject() const { return m_ai; }
AiController *AppController::aiObjectTyped() const { return m_ai; }
QObject *AppController::translationObject() const { return m_translation; }
TranslationController *AppController::translationObjectTyped() const { return m_translation; }
QObject *AppController::onlineSubsObject() const { return m_onlineSubs; }
OnlineSubsController *AppController::onlineSubsObjectTyped() const { return m_onlineSubs; }
QObject *AppController::networkObject() const { return m_network; }
QObject *AppController::remoteObject() const { return m_remoteInfo; }
RemoteInfo *AppController::remoteObjectTyped() const { return m_remoteInfo; }

QString AppController::uiMode() const
{
    // 명령줄 --tv/--desktop > 설정 (auto: 키오스크면 TV)
    QString mode = m_opt.uiMode;
    if (mode.isEmpty())
        mode = Settings::instance()->stringValue(QStringLiteral("ui_mode"));
    if (mode == QLatin1String("auto"))
        mode = m_opt.kiosk ? QStringLiteral("tv") : QStringLiteral("desktop");
    return mode;
}

QVariantMap AppController::settingsMap() const
{
    QVariantMap m;
    for (const QString &k : Settings::keys())
        m.insert(k, Settings::instance()->value(k));
    return m;
}

QVariant AppController::setting(const QString &key) const { return Settings::instance()->value(key); }

void AppController::setSetting(const QString &key, const QVariant &value)
{
    Settings::instance()->setValue(key, value);
}

void AppController::toggleSetting(const QString &key)
{
    Settings::instance()->setValue(key, !Settings::instance()->boolValue(key));
}

void AppController::emitSettings(const QString &key)
{
    if (key == QLatin1String("ui_mode"))
        emit viewChanged();
    if (key == QLatin1String("time_display_remaining"))
        emit positionChanged();
    emit settingsChanged();
    emit stateChanged();
}

QString AppController::subtitleButtonText() const { return m_subs->buttonText(); }

void AppController::setSidebarVisible(bool v)
{
    if (v == m_sidebarVisible)
        return;
    m_sidebarVisible = v;
    emit viewChanged();
}

void AppController::setSidebarWidth(int w)
{
    if (w < 200 || w == m_sidebarWidth)
        return;
    m_sidebarWidth = w;
    emit viewChanged();
}

void AppController::setWindowWidth(int w)
{
    if (w == m_windowWidth || w < 480)
        return;
    m_windowWidth = w;
    emit viewChanged();
}

void AppController::setWindowHeight(int h)
{
    if (h == m_windowHeight || h < 320)
        return;
    m_windowHeight = h;
    emit viewChanged();
}

// ---- OSD / HUD --------------------------------------------------------------

void AppController::showOsd(const QString &text, int ms)
{
    if (m_restoringSettings || text.isEmpty())
        return;
    m_osdText = text;
    emit osdShown(qMax(400, ms));
}

void AppController::toggleHud()
{
    m_hudVisible = !m_hudVisible;
    if (m_hudVisible)
        updateHud();
    emit hudChanged();
}

// ---- 창·보기 -----------------------------------------------------------------

void AppController::setFullscreen(bool on)
{
    if (on == m_fullscreen)
        return;
    if (on) {
        m_sidebarBeforeVideoOnly = m_sidebarVisible;
        m_fullscreen = true;
        m_controlsVisible = false;
        m_cursorHidden = true;     // 전체화면 전환 시 커서 즉시 숨김
        showOsd(QStringLiteral("🖥️ 전체화면 (영상 전용)"));
    } else {
        m_fullscreen = false;
        m_controlsVisible = false;
        m_cursorHidden = false;
        m_hideTimer.stop();
        showOsd(QStringLiteral("🖥️ 창 모드 복귀"));
    }
    emit fullscreenChanged();
    emit viewChanged();
}

void AppController::toggleFullscreen()
{
    if (m_opt.kiosk)
        return;   // 키오스크는 항상 전체화면
    if (m_mini)
        exitMini();
    setFullscreen(!m_fullscreen);
}

void AppController::toggleMiniPlayer()
{
    if (m_mini)
        exitMini();
    else
        enterMini();
}

void AppController::enterMini()
{
    if (m_opt.kiosk)
        return;
    if (m_fullscreen)
        setFullscreen(false);
    m_mini = true;
    m_controlsVisible = false;
    emit miniModeChanged();
    emit viewChanged();
    showOsd(QStringLiteral("🗗 미니 플레이어 — 드래그: 이동 · 휠: 볼륨 · Ctrl+휠: 크기 · 더블클릭: 원래대로"), 3000);
}

void AppController::exitMini()
{
    if (!m_mini)
        return;
    if (m_window) {
        Settings::instance()->setValue(QStringLiteral("mini_x"), m_window->x());
        Settings::instance()->setValue(QStringLiteral("mini_y"), m_window->y());
    }
    Settings::instance()->setValue(QStringLiteral("mini_width"), m_miniWidth);
    m_mini = false;
    m_controlsVisible = false;
    m_cursorHidden = false;
    m_hideTimer.stop();
    emit miniModeChanged();
    emit viewChanged();
    showOsd(QStringLiteral("🗖 원래 창으로"));
}

void AppController::rememberWindowGeometry(int x, int y, int w, int h, bool maximized)
{
    m_restoreRect = QRect(x, y, w, h);
    m_restoreMaximized = maximized;
}

static int miniHeight(int width, QSize video)
{
    if (video.width() <= 0 || video.height() <= 0)
        video = QSize(16, 9);
    return qMax(90, int(qRound(double(width) * video.height() / video.width())));
}

QVariantMap AppController::miniGeometry(int screenW, int screenH)
{
    const int w = qBound(kMiniMinWidth, m_miniWidth, kMiniMaxWidth);
    QSize video = m_engine->videoSize();
    if (m_rotation == QLatin1String("90r") || m_rotation == QLatin1String("90l"))
        video.transpose();
    const int h = miniHeight(w, video);
    int x = Settings::instance()->intValue(QStringLiteral("mini_x"));
    int y = Settings::instance()->intValue(QStringLiteral("mini_y"));
    if (x < 0 || y < 0) {
        // 화면 오른쪽 아래 (작업 영역 기준)
        QRect area(0, 0, screenW, screenH);
        if (m_window && m_window->screen())
            area = m_window->screen()->availableGeometry();
        x = area.x() + area.width() - w - kMiniMargin;
        y = area.y() + area.height() - h - kMiniMargin;
    }
    m_miniWidth = w;
    return {{"x", x}, {"y", y}, {"width", w}, {"height", h}};
}

QVariantMap AppController::restoreGeometry()
{
    QRect r = m_restoreRect;
    if (!r.isValid())
        r = QRect(100, 100, m_windowWidth, m_windowHeight);
    return {{"x", r.x()}, {"y", r.y()}, {"width", r.width()}, {"height", r.height()}, {"maximized", m_restoreMaximized}};
}

void AppController::resizeMini(double factor)
{
    if (!m_mini || !m_window)
        return;
    const int w = qBound(kMiniMinWidth, int(m_miniWidth * factor), kMiniMaxWidth);
    QSize video = m_engine->videoSize();
    if (m_rotation == QLatin1String("90r") || m_rotation == QLatin1String("90l"))
        video.transpose();
    m_miniWidth = w;
    m_window->resize(w, miniHeight(w, video));
}

void AppController::moveWindowBy(double dx, double dy)
{
    // 창 관리자에 맡기는 끌기 대신 직접 옮깁니다 (창 관리자에 따라 끌기가 불안정).
    if (m_window && m_mini)
        m_window->setPosition(m_window->x() + int(dx), m_window->y() + int(dy));
}

void AppController::noteMouseActivity()
{
    if (!m_fullscreen && !m_mini) {
        if (m_cursorHidden) {
            m_cursorHidden = false;
            emit viewChanged();
        }
        return;
    }
    showControlsTemporarily();
}

void AppController::showControlsTemporarily()
{
    const bool changed = !m_controlsVisible || m_cursorHidden;
    m_controlsVisible = true;
    m_cursorHidden = false;
    m_hideTimer.start();
    if (changed)
        emit viewChanged();
}

void AppController::setControlsHovered(bool hovered)
{
    m_controlsHovered = hovered;
    if (hovered)
        m_hideTimer.stop();
    else if (m_fullscreen || m_mini)
        m_hideTimer.start();
}

void AppController::onHideTimer()
{
    if (!(m_fullscreen || m_mini))
        return;
    if (m_controlsHovered) {
        m_hideTimer.start();
        return;
    }
    m_controlsVisible = false;
    m_cursorHidden = true;
    emit viewChanged();
}

void AppController::toggleRemainingTime()
{
    toggleSetting(QStringLiteral("time_display_remaining"));
}

void AppController::toggleKeepAbove()
{
    m_keepAbove = !m_keepAbove;
    emit viewChanged();
    showOsd(QStringLiteral("📌 항상 위에 표시: %1").arg(m_keepAbove ? "ON" : "OFF"));
}

void AppController::toggleSidebar()
{
    setSidebarVisible(!m_sidebarVisible);
}

void AppController::requestDialog(const QString &name, const QVariant &arg)
{
    if (name == QLatin1String("onlineSubs")) {
        const QString p = currentPath();
        if (p.isEmpty() || p.startsWith(QLatin1String("http")) || !QFileInfo(p).isFile()) {
            showOsd(QStringLiteral("ℹ️ 로컬 영상을 재생 중일 때 찾을 수 있습니다."));
            return;
        }
    }
    emit dialogRequested(name, arg);
}

QVariantList AppController::helpRows() const { return shortcuts::helpRowsVariant(); }

void AppController::handleEscape()
{
    if (m_mini)
        exitMini();
    else if (m_fullscreen && !m_opt.kiosk)
        toggleFullscreen();
    else if (!m_opt.kiosk)
        quit();
}

bool AppController::handleKey(int key, int modifiers, const QString &text)
{
    const shortcuts::Shortcut *sc = shortcuts::findShortcut(key, Qt::KeyboardModifiers(modifiers), text);
    if (!sc)
        return false;
    const QString &a = sc->action;
    const QVariantList &args = sc->args;
    auto arg = [&](int i) { return args.value(i); };
    // 파이썬 버전 창 메서드 이름 → 여기 동작
    if (a == QLatin1String("toggle_play_pause")) togglePlayPause();
    else if (a == QLatin1String("seek_relative")) seekRelative(arg(0).toDouble());
    else if (a == QLatin1String("step_playback_rate")) stepRate(arg(0).toDouble());
    else if (a == QLatin1String("reset_playback_rate")) resetRate();
    else if (a == QLatin1String("step_volume")) stepVolume(arg(0).toInt());
    else if (a == QLatin1String("toggle_mute")) toggleMute();
    else if (a == QLatin1String("play_next_video")) playNext();
    else if (a == QLatin1String("play_prev_video")) playPrevious();
    else if (a == QLatin1String("frame_step")) frameStep(arg(0).toInt());
    else if (a == QLatin1String("cycle_repeat_mode")) cycleRepeatMode();
    else if (a == QLatin1String("cycle_audio_track")) cycleAudioTrack();
    else if (a == QLatin1String("adjust_av_sync")) adjustAvSync(arg(0).toInt());
    else if (a == QLatin1String("reset_av_sync")) resetAvSync();
    else if (a == QLatin1String("set_ab_repeat_a")) setAbRepeatA();
    else if (a == QLatin1String("set_ab_repeat_b")) setAbRepeatB();
    else if (a == QLatin1String("clear_ab_repeat")) clearAbRepeat();
    else if (a == QLatin1String("add_bookmark")) addBookmark();
    else if (a == QLatin1String("show_bookmarks_popover")) requestDialog(QStringLiteral("bookmarks"));
    else if (a == QLatin1String("show_chapters_menu")) requestDialog(QStringLiteral("chapters"));
    else if (a == QLatin1String("show_dialogue_search")) {
        if (m_playlist.isEmpty())
            showOsd(QStringLiteral("ℹ️ 재생목록이 비어 있습니다."));
        else
            requestDialog(QStringLiteral("search"));
    }
    else if (a == QLatin1String("show_help_dialog")) requestDialog(QStringLiteral("help"));
    else if (a == QLatin1String("show_subtitle_popover")) {
        if (m_subs->entries().isEmpty())
            qCInfo(lcApp) << "ℹ️ 현재 영상에 사용 가능한 자막이 없습니다.";
        requestDialog(QStringLiteral("subtitles"));
    }
    else if (a == QLatin1String("toggle_subtitles")) toggleSubtitles();
    else if (a == QLatin1String("adjust_subtitle_scale")) m_subs->adjustScale(arg(0).toDouble());
    else if (a == QLatin1String("adjust_subtitle_sync")) m_subs->adjustSync(arg(0).toInt());
    else if (a == QLatin1String("start_ai_subtitles")) startAiSubtitles();
    else if (a == QLatin1String("start_translation")) startTranslation();
    else if (a == QLatin1String("capture_screenshot")) captureScreenshot();
    else if (a == QLatin1String("toggle_fullscreen")) toggleFullscreen();
    else if (a == QLatin1String("toggle_mini_player")) toggleMiniPlayer();
    else if (a == QLatin1String("toggle_hud")) toggleHud();
    else if (a == QLatin1String("toggle_keep_above")) toggleKeepAbove();
    else if (a == QLatin1String("toggle_night_mode")) toggleNightMode();
    else if (a == QLatin1String("cycle_sleep_timer")) cycleSleepTimer();
    else if (a == QLatin1String("cycle_video_rotation")) cycleRotation();
    else if (a == QLatin1String("open_file_dialog")) requestDialog(QStringLiteral("openFile"));
    else if (a == QLatin1String("open_folder_dialog")) requestDialog(QStringLiteral("openFolder"));
    else if (a == QLatin1String("rescan_playlist")) rescanPlaylist(false);
    else if (a == QLatin1String("handle_escape")) handleEscape();
    else if (a == QLatin1String("quit_player")) quit();
    else {
        qCWarning(lcApp) << "단축키 동작이 구현되지 않았습니다:" << a;
        return false;
    }
    return true;
}

// ---- 기타 도구 ----------------------------------------------------------------

void AppController::captureScreenshot()
{
    if (!m_engine->isOpen()) {
        showOsd(QStringLiteral("캡처할 재생 영상이 없습니다."));
        return;
    }
    const QString dir = QDir::homePath() + QStringLiteral("/Pictures/JetsonVideoPlayer");
    QDir().mkpath(dir);
    const QString name = QStringLiteral("Screenshot_%1.png").arg(QDateTime::currentDateTime().toString("yyyyMMdd_HHmmss"));
    const QString path = dir + QLatin1Char('/') + name;
    // 원본 해상도의 현재 프레임 (자막·OSD 없이). 실패하면 창을 그대로 저장합니다.
    bool saved = m_engine->saveCurrentFrame(path);
    if (!saved && m_window)
        saved = m_window->grabWindow().save(path);
    if (saved) {
        showOsd(QStringLiteral("📸 스크린샷 저장 완료: %1").arg(name), 2000);
        qCInfo(lcApp).noquote() << "📸 [스크린샷 캡처] 저장 완료:" << path;
    } else {
        showOsd(QStringLiteral("⚠️ 스크린샷 캡처 실패"));
    }
}

void AppController::openLogFile()
{
    const QString path = log::logFilePath();
    if (path.isEmpty() || !QFileInfo::exists(path)) {
        showOsd(QStringLiteral("⚠️ 로그 파일이 없습니다."));
        return;
    }
    if (!QDesktopServices::openUrl(QUrl::fromLocalFile(path)))
        SystemInfo::openFileLocation(path);
}

void AppController::copyText(const QString &text, const QString &osd)
{
    QGuiApplication::clipboard()->setText(text);
    showOsd(osd.isEmpty() ? QStringLiteral("📋 복사했습니다") : osd, 1500);
}

void AppController::quit()
{
    qCInfo(lcApp) << "⏹ 프로그램 종료.";
    emit quitRequested();
}

void AppController::captureSettings()
{
    Settings *s = Settings::instance();
    QVariantMap v{
        {"volume", m_muted ? m_preMuteVolume : m_volume},
        {"muted", m_muted},
        {"subtitle_font_scale", m_subs->fontScale()},
        {"repeat_mode", m_repeatMode},
        {"sidebar_width", m_sidebarWidth},
        {"sidebar_visible", (m_fullscreen || m_mini) ? m_sidebarBeforeVideoOnly : m_sidebarVisible},
        {"hud_visible", m_hudVisible},
        {"embedded_subs_enabled", m_subs->embeddedEnabled()},
        {"mini_width", m_miniWidth},
    };
    if (!m_fullscreen && !m_mini && !m_windowMaximized) {
        v.insert("window_width", m_windowWidth);
        v.insert("window_height", m_windowHeight);
    }
    if (!m_fullscreen && !m_mini && !m_opt.kiosk)
        v.insert("window_maximized", m_windowMaximized);
    s->update(v);
}

void AppController::flushCaches()
{
    saveAllStores();
    captureSettings();
    Settings::instance()->save();
}

void AppController::shutdown(int width, int height, bool maximized)
{
    if (m_shuttingDown)
        return;
    m_shuttingDown = true;
    if (!m_fullscreen && !m_mini) {
        m_windowMaximized = maximized;
        if (!maximized && width >= 480 && height >= 320) {
            m_windowWidth = width;
            m_windowHeight = height;
        }
    }
    stopFolderWatch();
    m_positionTimer.stop();
    m_flushTimer.stop();
    m_sleepTimer.stop();
    m_autoplayTimer.stop();
    for (QObject *job : {static_cast<QObject *>(m_thumbJob.data()), static_cast<QObject *>(m_sceneJob.data()),
                         static_cast<QObject *>(m_loudnessJob.data())})
        delete job;   // 소멸자가 취소하고 작업 스레드를 기다립니다
    m_ai->cancel();
    m_translation->cancel();
    stopServices();
    // 마지막 위치를 이어보기에 남깁니다
    if (m_engine->isOpen() && !currentPath().isEmpty()) {
        const qint64 pos = m_engine->position();
        if (pos > 0)
            resumeCache().set(currentPath(), pos, m_durationNs);
    }
    m_engine->stop();
    flushCaches();
}

} // namespace jvp
