#pragma once
// 앱 전체 상태와 동작을 QML에 보여 주는 컨트롤러 (QML 싱글톤 App).
// 파이썬 버전의 창 클래스(여러 mixin)를 옮긴 것으로, 기능별로 소스 파일을 나눴습니다:
//   AppController.cpp  — 생성·설정·타이머·창/보기·단축키·종료
//   AppPlayback.cpp    — 재생·탐색·배속·볼륨·오류/EOS 정책·A-B·북마크·챕터·썸네일·수면·자동 재생·회전·HDR·오디오 효과
//   AppLibrary.cpp     — 재생목록 구성·열기·드롭·M3U·폴더 감시·기록·네트워크 폴더
//   AppServices.cpp    — 웹 리모컨·MPRIS·대사 검색·HUD

#include "Mpris.h"
#include "PlayerEngine.h"
#include "RemoteServer.h"
#include "Thumbnails.h"

#include <QElapsedTimer>
#include <QFileSystemWatcher>
#include <QHash>
#include <QJsonArray>
#include <QObject>
#include <QPointer>
#include <QRect>
#include <QSet>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>
#include <QtQml/qqmlregistration.h>
#include <optional>

class QQmlEngine;
class QJSEngine;
class QQuickWindow;

namespace jvp {

class AiController;
class DialogueIndex;
class EventBroker;
class LoudnessJob;
class MprisService;
class NetworkMount;
class OnlineSubsController;
class PlaylistModel;
class RemoteAuth;
class RemoteInfo;
class SceneAnalysisJob;
class SubtitleController;
class ThumbnailJob;
class TranslationController;
class YouTubeController;

class AppController : public QObject, public RemoteBackend, public MprisBackend {
    Q_OBJECT
    Q_MOC_INCLUDE("PlaylistModel.h")
    Q_MOC_INCLUDE("SubtitleController.h")
    Q_MOC_INCLUDE("AiController.h")
    Q_MOC_INCLUDE("OnlineSubsController.h")
    Q_MOC_INCLUDE("RemoteInfo.h")
    QML_NAMED_ELEMENT(App)
    QML_SINGLETON

    // 재생
    Q_PROPERTY(QString title READ title NOTIFY mediaChanged)
    Q_PROPERTY(QString nowPlayingText READ nowPlayingText NOTIFY mediaChanged)
    Q_PROPERTY(bool hasVideo READ hasVideo NOTIFY mediaChanged)
    Q_PROPERTY(bool playing READ playing NOTIFY playbackChanged)
    Q_PROPERTY(double rate READ rate NOTIFY playbackChanged)
    Q_PROPERTY(int volume READ volume NOTIFY playbackChanged)
    Q_PROPERTY(bool muted READ muted NOTIFY playbackChanged)
    Q_PROPERTY(QString repeatMode READ repeatMode NOTIFY playbackChanged)
    Q_PROPERTY(QString repeatModeLabel READ repeatModeLabel NOTIFY playbackChanged)
    Q_PROPERTY(double positionMs READ positionMs NOTIFY positionChanged)
    Q_PROPERTY(double durationMs READ durationMs NOTIFY positionChanged)
    Q_PROPERTY(QString positionText READ positionText NOTIFY positionChanged)
    Q_PROPERTY(QString durationText READ durationText NOTIFY positionChanged)
    Q_PROPERTY(QObject *frameBridge READ frameBridge CONSTANT)

    // 창·보기
    Q_PROPERTY(bool fullscreen READ fullscreen NOTIFY fullscreenChanged)
    Q_PROPERTY(bool miniMode READ miniMode NOTIFY miniModeChanged)
    Q_PROPERTY(bool keepAbove READ keepAbove NOTIFY viewChanged)
    Q_PROPERTY(bool sidebarVisible READ sidebarVisible WRITE setSidebarVisible NOTIFY viewChanged)
    Q_PROPERTY(int sidebarWidth READ sidebarWidth WRITE setSidebarWidth NOTIFY viewChanged)
    Q_PROPERTY(int windowWidth READ windowWidth WRITE setWindowWidth NOTIFY viewChanged)
    Q_PROPERTY(int windowHeight READ windowHeight WRITE setWindowHeight NOTIFY viewChanged)
    Q_PROPERTY(bool windowMaximized READ windowMaximized NOTIFY viewChanged)
    Q_PROPERTY(bool kiosk READ kiosk CONSTANT)
    Q_PROPERTY(QString uiMode READ uiMode NOTIFY viewChanged)
    Q_PROPERTY(bool controlsVisible READ controlsVisible NOTIFY viewChanged)
    Q_PROPERTY(bool cursorHidden READ cursorHidden NOTIFY viewChanged)
    Q_PROPERTY(QString osdText READ osdText NOTIFY osdShown)
    Q_PROPERTY(bool hudVisible READ hudVisible NOTIFY hudChanged)
    Q_PROPERTY(QString hudText READ hudText NOTIFY hudChanged)
    Q_PROPERTY(QString rotation READ rotation NOTIFY viewChanged)
    Q_PROPERTY(QString hdrMode READ hdrMode NOTIFY viewChanged)
    Q_PROPERTY(bool hdrMatrixFix READ hdrMatrixFix NOTIFY viewChanged)

    // 표시·기능 상태
    Q_PROPERTY(QVariantMap settings READ settingsMap NOTIFY settingsChanged)
    Q_PROPERTY(double abA READ abA NOTIFY marksChanged)
    Q_PROPERTY(double abB READ abB NOTIFY marksChanged)
    Q_PROPERTY(bool abActive READ abActive NOTIFY marksChanged)
    Q_PROPERTY(QString abLabel READ abLabel NOTIFY marksChanged)
    Q_PROPERTY(QVariantList timelineMarks READ timelineMarks NOTIFY marksChanged)
    Q_PROPERTY(QVariantList resumeCards READ resumeCards NOTIFY resumeCardsChanged)
    Q_PROPERTY(QVariantMap autoplay READ autoplay NOTIFY autoplayChanged)
    Q_PROPERTY(int sleepMinutes READ sleepMinutes NOTIFY stateChanged)
    Q_PROPERTY(QString sleepMenuLabel READ sleepMenuLabel NOTIFY stateChanged)
    Q_PROPERTY(bool nightMode READ nightMode NOTIFY settingsChanged)
    Q_PROPERTY(QString loudnessMenuLabel READ loudnessMenuLabel NOTIFY stateChanged)
    Q_PROPERTY(QString eqPresetName READ eqPresetName NOTIFY settingsChanged)
    Q_PROPERTY(QString subtitleButtonText READ subtitleButtonText NOTIFY subtitlesChanged)
    Q_PROPERTY(QString chaptersTitle READ chaptersTitle NOTIFY chaptersChanged)
    Q_PROPERTY(QString chaptersEmptyText READ chaptersEmptyText NOTIFY chaptersChanged)
    Q_PROPERTY(QString sceneAnalysisLabel READ sceneAnalysisLabel NOTIFY chaptersChanged)
    Q_PROPERTY(bool sceneAnalysisAvailable READ sceneAnalysisAvailable NOTIFY chaptersChanged)
    Q_PROPERTY(bool youtubeLoading READ youtubeLoading NOTIFY youtubeChanged)
    Q_PROPERTY(QVariantMap youtube READ youtubeState NOTIFY youtubeChanged)

    // 하위 객체
    Q_PROPERTY(jvp::PlaylistModel *playlist READ playlistObjectTyped CONSTANT)
    Q_PROPERTY(jvp::SubtitleController *subtitles READ subtitlesObjectTyped CONSTANT)
    Q_PROPERTY(jvp::AiController *ai READ aiObjectTyped CONSTANT)
    Q_PROPERTY(jvp::TranslationController *translation READ translationObjectTyped CONSTANT)
    Q_PROPERTY(jvp::OnlineSubsController *onlineSubs READ onlineSubsObjectTyped CONSTANT)
    Q_PROPERTY(QObject *network READ networkObject CONSTANT)
    Q_PROPERTY(jvp::RemoteInfo *remote READ remoteObjectTyped CONSTANT)

public:
    struct Options {
        QString input;            // 파일·폴더·M3U·YouTube 주소
        bool kiosk = false;       // 전체화면 고정 (TV 박스)
        QString uiMode;           // "desktop" / "tv" / 비어 있으면 설정값
        bool startServices = true;   // 웹 리모컨·MPRIS (테스트에서 끔)
    };

    explicit AppController(const Options &opt, QObject *parent = nullptr);
    ~AppController() override;

    static AppController *instance();
    static AppController *create(QQmlEngine *, QJSEngine *);   // QML 싱글톤 공장

    void attachWindow(QQuickWindow *window);   // QML 창이 만들어진 뒤 (창 이동·캡처용)
    void start();                              // 첫 영상 재생, 폴더 감시, 서비스 시작

    // ---- 속성 --------------------------------------------------------------
    QString title() const;
    QString nowPlayingText() const;
    bool hasVideo() const { return m_engine->isOpen(); }
    bool playing() const { return m_playing; }
    double rate() const { return m_rate; }
    int volume() const { return m_volume; }
    bool muted() const { return m_muted; }
    QString repeatMode() const { return m_repeatMode; }
    QString repeatModeLabel() const;
    double positionMs() const { return m_lastPosNs / 1e6; }
    double durationMs() const { return m_durationNs / 1e6; }
    QString positionText() const;
    QString durationText() const;
    QObject *frameBridge() const;

    bool fullscreen() const { return m_fullscreen; }
    bool miniMode() const { return m_mini; }
    bool keepAbove() const { return m_keepAbove; }
    bool sidebarVisible() const { return m_sidebarVisible; }
    void setSidebarVisible(bool v);
    int sidebarWidth() const { return m_sidebarWidth; }
    void setSidebarWidth(int w);
    int windowWidth() const { return m_windowWidth; }
    void setWindowWidth(int w);
    int windowHeight() const { return m_windowHeight; }
    void setWindowHeight(int h);
    bool windowMaximized() const { return m_windowMaximized; }
    bool kiosk() const { return m_opt.kiosk; }
    QString uiMode() const;
    bool controlsVisible() const { return m_controlsVisible; }
    bool cursorHidden() const { return m_cursorHidden; }
    QString osdText() const { return m_osdText; }
    bool hudVisible() const { return m_hudVisible; }
    QString hudText() const { return m_hudText; }
    QString rotation() const { return m_rotation; }
    QString hdrMode() const { return m_hdrMode; }
    bool hdrMatrixFix() const { return m_hdrMatrixFix; }

    QVariantMap settingsMap() const;
    double abA() const { return m_abA < 0 ? -1 : m_abA / 1e6; }
    double abB() const { return m_abB < 0 ? -1 : m_abB / 1e6; }
    bool abActive() const { return m_abActive; }
    QString abLabel() const;
    QVariantList timelineMarks() const { return m_timelineMarks; }
    QVariantList resumeCards() const { return m_resumeCards; }
    QVariantMap autoplay() const;
    int sleepMinutes() const { return m_sleepMinutes; }
    QString sleepMenuLabel() const;
    bool nightMode() const;
    QString loudnessMenuLabel() const;
    QString eqPresetName() const;
    QString subtitleButtonText() const;
    QString chaptersTitle() const;
    QString chaptersEmptyText() const;
    QString sceneAnalysisLabel() const;
    bool sceneAnalysisAvailable() const;
    bool youtubeLoading() const;
    QVariantMap youtubeState() const;

    QObject *playlistObject() const;
    PlaylistModel *playlistObjectTyped() const;
    QObject *subtitlesObject() const;
    SubtitleController *subtitlesObjectTyped() const;
    QObject *aiObject() const;
    AiController *aiObjectTyped() const;
    QObject *translationObject() const;
    TranslationController *translationObjectTyped() const;
    QObject *onlineSubsObject() const;
    OnlineSubsController *onlineSubsObjectTyped() const;
    QObject *networkObject() const;
    QObject *remoteObject() const;
    RemoteInfo *remoteObjectTyped() const;

    PlayerEngine *engine() const { return m_engine; }
    SubtitleController *subtitleController() const { return m_subs; }
    QString currentPath() const;
    QStringList playlistPaths() const { return m_playlist; }
    int currentIndex() const { return m_index; }
    qint64 positionNs() const { return m_lastPosNs; }
    qint64 durationNs() const { return m_durationNs; }
    QString remoteUrl() const;
    void showOsd(const QString &text, int ms = 1200);
    void refreshSubtitleUi();
    void addExternalSubtitle(const QString &path);   // 드래그 앤 드롭·온라인 자막

    // ---- 재생 --------------------------------------------------------------
    Q_INVOKABLE void togglePlayPause();
    Q_INVOKABLE void seekRelative(double seconds);
    Q_INVOKABLE void scrubTo(double ratio);        // 진행바를 끄는 중 (150ms마다 키프레임 탐색)
    Q_INVOKABLE void seekToRatio(double ratio);    // 진행바를 놓음 (정확한 위치)
    Q_INVOKABLE void seekToPercent(double pct);
    Q_INVOKABLE void jumpToMs(double ms);
    Q_INVOKABLE void frameStep(int direction);
    Q_INVOKABLE void setRate(double rate);
    Q_INVOKABLE void stepRate(double delta);
    Q_INVOKABLE void resetRate() { setRate(1.0); }
    Q_INVOKABLE void setVolume(double percent);
    Q_INVOKABLE void stepVolume(int delta);
    Q_INVOKABLE void toggleMute();
    Q_INVOKABLE void playNext();
    Q_INVOKABLE void playPrevious();
    Q_INVOKABLE void playIndex(int index);
    Q_INVOKABLE void queueNext(const QString &path);
    Q_INVOKABLE void unqueue(const QString &path);
    Q_INVOKABLE void cycleRepeatMode();
    Q_INVOKABLE void setRepeatMode(const QString &mode);
    Q_INVOKABLE void cycleAudioTrack();
    Q_INVOKABLE void setAudioTrack(int index);
    Q_INVOKABLE void adjustAvSync(int deltaMs);
    Q_INVOKABLE void resetAvSync();

    // A-B · 북마크 · 챕터
    Q_INVOKABLE void setAbRepeatA();
    Q_INVOKABLE void setAbRepeatB();
    Q_INVOKABLE void clearAbRepeat();
    Q_INVOKABLE void addBookmark();
    Q_INVOKABLE void removeBookmark(int index);
    Q_INVOKABLE QVariantList bookmarkList() const;
    Q_INVOKABLE QVariantList chapterList() const;
    Q_INVOKABLE int currentChapterIndex() const;
    Q_INVOKABLE void jumpToChapter(double ms);
    Q_INVOKABLE QString chapterAt(double ms) const;
    Q_INVOKABLE void toggleSceneAnalysis();
    Q_INVOKABLE QString thumbnailUrl(double ms) const;

    // 자막 · AI
    Q_INVOKABLE void toggleSubtitles();
    Q_INVOKABLE void startAiSubtitles();
    Q_INVOKABLE void startTranslation();
    Q_INVOKABLE void toggleAssStyles();

    // 시청 설정
    Q_INVOKABLE void toggleNightMode();
    Q_INVOKABLE void setSleepTimer(int minutes);
    Q_INVOKABLE void cycleSleepTimer();
    Q_INVOKABLE void setRotation(const QString &method);
    Q_INVOKABLE void cycleRotation();
    Q_INVOKABLE void toggleHdrTonemap();
    Q_INVOKABLE void toggleLoudness();
    Q_INVOKABLE QVariantList eqPresets() const;
    Q_INVOKABLE void setEqPreset(const QString &key);
    Q_INVOKABLE void togglePassthrough();
    Q_INVOKABLE void cancelAutoplay();
    Q_INVOKABLE void autoplayNow();

    // 설정
    Q_INVOKABLE QVariant setting(const QString &key) const;
    Q_INVOKABLE void setSetting(const QString &key, const QVariant &value);
    Q_INVOKABLE void toggleSetting(const QString &key);

    // ---- 창·보기 --------------------------------------------------------------
    Q_INVOKABLE void toggleFullscreen();
    Q_INVOKABLE void toggleMiniPlayer();
    Q_INVOKABLE void resizeMini(double factor);
    Q_INVOKABLE void moveWindowBy(double dx, double dy);
    Q_INVOKABLE void noteMouseActivity();
    Q_INVOKABLE void setControlsHovered(bool hovered);
    Q_INVOKABLE void toggleRemainingTime();
    Q_INVOKABLE void toggleHud();
    Q_INVOKABLE void toggleKeepAbove();
    Q_INVOKABLE void toggleSidebar();
    Q_INVOKABLE void rememberWindowGeometry(int x, int y, int w, int h, bool maximized);
    Q_INVOKABLE QVariantMap miniGeometry(int screenW, int screenH);
    Q_INVOKABLE QVariantMap restoreGeometry();
    Q_INVOKABLE bool handleKey(int key, int modifiers, const QString &text);
    Q_INVOKABLE void handleEscape();
    Q_INVOKABLE void requestDialog(const QString &name, const QVariant &arg = {});
    Q_INVOKABLE QVariantList helpRows() const;
    Q_INVOKABLE QString formatTime(double ms) const;
    Q_INVOKABLE void captureScreenshot();
    Q_INVOKABLE void openLogFile();
    Q_INVOKABLE void copyText(const QString &text, const QString &osd = QString());
    Q_INVOKABLE void quit();
    Q_INVOKABLE void shutdown(int width, int height, bool maximized);

    // ---- 재생목록 · 열기 ------------------------------------------------------
    Q_INVOKABLE void openUrls(const QList<QUrl> &urls);
    Q_INVOKABLE void openPath(const QString &path);
    Q_INVOKABLE void dropUrls(const QList<QUrl> &urls);
    Q_INVOKABLE void dropText(const QString &text);
    Q_INVOKABLE QUrl suggestedM3uUrl() const;
    Q_INVOKABLE void saveM3u(const QUrl &url);
    Q_INVOKABLE void rescanPlaylist(bool quiet = false);
    Q_INVOKABLE void cyclePlaylistSort();
    Q_INVOKABLE void openCurrentLocation();
    Q_INVOKABLE void openLocation(const QString &path);
    Q_INVOKABLE QVariantList history() const;
    Q_INVOKABLE QVariantList networkLocations() const;
    Q_INVOKABLE void openNetworkUri(const QString &uri);

    // 대사 검색
    Q_INVOKABLE void refreshDialogueIndex();
    Q_INVOKABLE QVariantList searchDialogue(const QString &query);
    Q_INVOKABLE QString dialogueSearchStatus(const QString &query, int count) const;
    Q_INVOKABLE void jumpToDialogue(const QString &video, double startMs);

    // YouTube
    Q_INVOKABLE QString clipboardYoutubeUrl() const;
    Q_INVOKABLE void startYoutube(const QString &url, const QString &quality = QStringLiteral("best"));
    Q_INVOKABLE void cancelYoutube();

    // 다른 컨트롤러가 부르는 재생 진입점
    void playPathAt(const QString &path, qint64 startNs);   // 재생목록에 있으면 그 위치로, 없으면 추가
    void addToPlaylistAndPlay(const QString &path);         // YouTube 다운로드 완료 등
    void appendToPlaylist(const QString &path);             // 재생목록 끝에 추가만 (이미 있으면 그대로)

    // ---- RemoteBackend ------------------------------------------------------
    QJsonObject remoteStatus() override;
    QString remoteThumbnailPath(int i) override;
    QString remotePlaylistThumbnailPath(int index) override;
    QJsonObject remoteSearch(const QString &query) override;
    void handleRemoteCommand(const QVariantMap &params) override;

    // ---- MprisBackend --------------------------------------------------------
    bool mprisHasMedia() const override;
    bool mprisIsPlaying() const override { return m_playing; }
    int mprisPlaylistCount() const override { return int(m_playlist.size()); }
    int mprisCurrentIndex() const override { return m_index; }
    QString mprisCurrentPath() const override { return currentPath(); }
    qint64 mprisDurationNs() const override { return m_durationNs; }
    qint64 mprisPositionNs() const override { return m_lastPosNs; }
    double mprisRate() const override { return m_rate; }
    double mprisVolume() const override { return m_volume / 100.0; }
    bool mprisMuted() const override { return m_muted; }
    QString mprisRepeatMode() const override { return m_repeatMode; }
    bool mprisFullscreen() const override { return m_fullscreen; }
    QString mprisArtPath() const override;
    void mprisRaise() override;
    void mprisQuit() override { quit(); }
    void mprisNext() override { playNext(); }
    void mprisPrevious() override { playPrevious(); }
    void mprisTogglePlayPause() override { togglePlayPause(); }
    void mprisSeekTo(qint64 ns) override { seekTo(ns, SeekMode::Accurate); }
    void mprisSeekRelative(double seconds) override { seekRelative(seconds); }
    void mprisOpenPath(const QString &localPath) override { openPath(localPath); }
    void mprisOpenUrl(const QString &url) override { startYoutube(url); }
    void mprisSetVolume(double linear) override { setVolume(linear * 100.0); }
    void mprisSetRate(double r) override { setRate(r); }
    void mprisSetRepeatMode(const QString &mode) override { setRepeatMode(mode); }
    void mprisToggleFullscreen() override { toggleFullscreen(); }

signals:
    void mediaChanged();
    void playbackChanged();
    void positionChanged();
    void fullscreenChanged();
    void miniModeChanged();
    void viewChanged();
    void hudChanged();
    void settingsChanged();
    void marksChanged();
    void resumeCardsChanged();
    void autoplayChanged();
    void stateChanged();
    void subtitlesChanged();
    void chaptersChanged();
    void youtubeChanged();
    void osdShown(int ms);
    void quitRequested();
    void dialogRequested(const QString &name, const QVariant &arg);
    void dialogueIndexReady();

private:
    // 재생 (AppPlayback.cpp)
    void playCurrent(qint64 startNs = 0, std::optional<qint64> openAtNs = std::nullopt);
    void restartCurrent(qint64 atNs, int delayMs);
    void schedulePlayCurrent(int delayMs);
    bool seekTo(qint64 ns, SeekMode mode);
    void onEngineAsyncDone();
    void onEngineEos();
    void onEngineError(const QString &message, const QString &debug, bool fromPassthrough);
    void onEnginePlayingChanged(bool playing);
    void onStreamsChanged();
    void onChaptersFound(const QVariantList &chapters);
    void onPositionTick();
    void applyVolumeToEngine();
    int popQueuedIndex();
    int randomOtherIndex() const;
    void refreshTimelineMarks();
    void resetAbRepeat(bool announce);
    void startThumbnails(const QString &path);
    void setSceneChapters(const QList<qint64> &scenes);
    QList<QPair<qint64, QString>> chapters() const;
    void updateHdr();
    void startLoudnessFor(const QString &path);
    void applyMeasuredLoudness(const QString &path, std::optional<double> lufs);
    void setLoudnessGain(double db, bool ramp);
    void applyEqPreset();
    bool usePassthroughFor(const QString &path);
    void startAutoplayCountdown(int nextIndex);
    void finishAutoplay(bool run);
    int sleepRemainingSec() const;
    void onSleepTick();
    void sleepNow();
    void cancelSleepFade();
    void applySleepFade();

    // 재생목록 (AppLibrary.cpp)
    bool buildPlaylist(const QString &input, const std::optional<QStringList> &scanned = std::nullopt);
    void loadPath(const QString &input, const std::optional<QStringList> &scanned = std::nullopt);
    void loadFiles(const QStringList &files);
    void refreshPlaylistModel();
    void applyPlaylistSort(bool resort);
    bool playlistIsFolder() const;
    void startFolderWatch();
    void stopFolderWatch();
    void scheduleRescan();
    void applyRescan(const QString &root, const std::optional<QStringList> &scanned, bool quiet);
    void startBackgroundHwChecker();
    void scanNetworkFolderThenLoad(const QString &folder);
    void reconnectNetworkPath(const QString &path);
    void onMountFinished(const QString &uri, const QString &localPath, const QString &error);
    void refreshResumeCards();

    // 서비스 (AppServices.cpp)
    void startServices();
    void stopServices();
    void publishRemoteStatus();
    QJsonArray remotePlaylistGroups();
    void updateHud();

    // 보기 (AppController.cpp)
    void setFullscreen(bool on);
    void enterMini();
    void exitMini();
    void showControlsTemporarily();
    void onHideTimer();
    void captureSettings();
    void flushCaches();
    void emitSettings(const QString &key);

    static AppController *s_instance;
    Options m_opt;
    QPointer<QQuickWindow> m_window;
    PlayerEngine *m_engine = nullptr;
    SubtitleController *m_subs = nullptr;
    PlaylistModel *m_playlistModel = nullptr;
    AiController *m_ai = nullptr;
    TranslationController *m_translation = nullptr;
    OnlineSubsController *m_onlineSubs = nullptr;
    YouTubeController *m_youtube = nullptr;
    NetworkMount *m_network = nullptr;
    RemoteInfo *m_remoteInfo = nullptr;

    // 재생목록
    QStringList m_playlist;
    int m_index = 0;
    QString m_inputPath;
    bool m_singleFile = false;
    bool m_fromFiles = false;       // 직접 고른 파일 목록 (폴더 감시·새로고침 대상 아님)
    bool m_fromM3u = false;
    QStringList m_queue;
    bool m_started = false;

    // 재생 상태
    bool m_playing = false;
    double m_rate = 1.0;
    int m_volume = 100;
    bool m_muted = false;
    int m_preMuteVolume = 100;
    QString m_repeatMode = QStringLiteral("all");
    qint64 m_lastPosNs = 0;
    qint64 m_durationNs = 0;
    qint64 m_pendingStartNs = 0;    // 아직 첫 탐색 전이면 HW 실패 시 이 위치에서 다시 시작
    bool m_restartScheduled = false;
    std::optional<bool> m_hwExpected;
    QSet<QString> m_hwOutputDisabled;
    QSet<QString> m_passthroughFailed;
    bool m_passthroughHintShown = false;
    QHash<QString, int> m_retryCounts;
    static constexpr int kMaxRetries = 2;
    QElapsedTimer m_eosAt;
    int m_audioTrack = 0;
    int m_audioTracks = 0;
    int m_avOffsetMs = 0;
    QTimer m_positionTimer;
    int m_lastUiSecond = -1;
    int m_ticks = 0;
    QTimer m_scrubTimer;
    qint64 m_scrubTarget = -1;
    qint64 m_scrubLast = -1;

    // A-B · 챕터 · 썸네일
    qint64 m_abA = -1;
    qint64 m_abB = -1;
    bool m_abActive = false;
    QVariantList m_timelineMarks;
    QList<QPair<qint64, QString>> m_tocChapters;
    QList<QPair<qint64, QString>> m_sceneChapters;
    std::optional<ThumbnailIndex> m_thumbIndex;
    QPointer<ThumbnailJob> m_thumbJob;
    QPointer<SceneAnalysisJob> m_sceneJob;
    double m_sceneProgress = 0;

    // 보기
    bool m_fullscreen = false;
    bool m_mini = false;
    bool m_keepAbove = false;
    bool m_sidebarVisible = true;
    bool m_sidebarBeforeVideoOnly = true;
    int m_sidebarWidth = 360;
    int m_windowWidth = 1280;
    int m_windowHeight = 720;
    bool m_windowMaximized = false;
    QRect m_restoreRect;
    bool m_restoreMaximized = false;
    int m_miniWidth = 480;
    bool m_controlsVisible = false;
    bool m_controlsHovered = false;
    bool m_cursorHidden = false;
    QTimer m_hideTimer;
    QString m_osdText;
    bool m_restoringSettings = true;
    bool m_hudVisible = false;
    QString m_hudText;
    QString m_rotation = QStringLiteral("identity");
    QString m_hdrTransfer;          // 디코딩된 영상의 전달 특성 ("pq" / "hlg" / "")
    QString m_hdrMode;              // 셰이더에 넘길 값 (톤매핑이 꺼져 있으면 "")
    bool m_hdrMatrixFix = false;
    QVariantList m_resumeCards;

    // 오디오 효과
    QPointer<LoudnessJob> m_loudnessJob;
    QString m_loudnessPath;
    std::optional<double> m_loudnessLufs;
    double m_loudnessCurrentDb = 0;
    double m_loudnessTargetDb = 0;
    QTimer m_loudnessRamp;
    int m_loudnessRampStep = 0;
    double m_loudnessRampFrom = 0;

    // 수면 타이머 · 자동 재생
    int m_sleepMinutes = 0;
    QElapsedTimer m_sleepClock;
    qint64 m_sleepDeadlineMs = -1;  // m_sleepClock 기준
    QTimer m_sleepTimer;
    bool m_sleepFading = false;
    double m_sleepFadeBase = 1.0;
    int m_autoplayIndex = -1;
    QString m_autoplayTitle;
    QElapsedTimer m_autoplayClock;
    QTimer m_autoplayTimer;

    // 폴더 감시
    QFileSystemWatcher *m_watcher = nullptr;
    QTimer m_rescanDebounce;
    QTimer m_watchPoll;
    bool m_rescanRunning = false;
    bool m_hwCheckerStarted = false;

    // 서비스
    RemoteAuth *m_remoteAuth = nullptr;
    EventBroker *m_broker = nullptr;
    RemoteServer *m_remoteServer = nullptr;
    MprisService *m_mpris = nullptr;
    QTimer m_remoteTimer;
    QTimer m_flushTimer;
    QJsonArray m_remoteGroupsCache;
    QString m_remoteGroupsKey;
    std::unique_ptr<DialogueIndex> m_dialogueIndex;
    bool m_indexRunning = false;
    bool m_indexAgain = false;
    QStringList m_remoteSearchIndexedFor;
    bool m_shuttingDown = false;
};

} // namespace jvp
