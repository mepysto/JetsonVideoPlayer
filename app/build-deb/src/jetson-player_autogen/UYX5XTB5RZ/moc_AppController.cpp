/****************************************************************************
** Meta object code from reading C++ file 'AppController.h'
**
** Created by: The Qt Meta Object Compiler version 69 (Qt 6.11.3)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include "../../../../src/ui/AppController.h"
#include "PlaylistModel.h"
#include "SubtitleController.h"
#include "AiController.h"
#include "OnlineSubsController.h"
#include "RemoteInfo.h"
#include <QtCore/qmetatype.h>
#include <QtCore/QList>

#include <QtCore/qtmochelpers.h>

#include <memory>


#include <QtCore/qxptype_traits.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'AppController.h' doesn't include <QObject>."
#elif Q_MOC_OUTPUT_REVISION != 69
#error "This file was generated using the moc from 6.11.3. It"
#error "cannot be used with the include files from this version of Qt."
#error "(The moc has changed too much.)"
#endif

#ifndef Q_CONSTINIT
#define Q_CONSTINIT
#endif

QT_WARNING_PUSH
QT_WARNING_DISABLE_DEPRECATED
QT_WARNING_DISABLE_GCC("-Wuseless-cast")
namespace {
struct qt_meta_tag_ZN3jvp13AppControllerE_t {};
} // unnamed namespace

template <> constexpr inline auto jvp::AppController::qt_create_metaobjectdata<qt_meta_tag_ZN3jvp13AppControllerE_t>()
{
    namespace QMC = QtMocConstants;
    QtMocHelpers::StringRefStorage qt_stringData {
        "jvp::AppController",
        "QML.Element",
        "App",
        "QML.Singleton",
        "true",
        "mediaChanged",
        "",
        "playbackChanged",
        "positionChanged",
        "fullscreenChanged",
        "miniModeChanged",
        "viewChanged",
        "hudChanged",
        "settingsChanged",
        "marksChanged",
        "resumeCardsChanged",
        "autoplayChanged",
        "stateChanged",
        "subtitlesChanged",
        "chaptersChanged",
        "youtubeChanged",
        "osdShown",
        "ms",
        "quitRequested",
        "dialogRequested",
        "name",
        "QVariant",
        "arg",
        "dialogueIndexReady",
        "togglePlayPause",
        "seekRelative",
        "seconds",
        "scrubTo",
        "ratio",
        "seekToRatio",
        "seekToPercent",
        "pct",
        "jumpToMs",
        "frameStep",
        "direction",
        "setRate",
        "rate",
        "stepRate",
        "delta",
        "resetRate",
        "setVolume",
        "percent",
        "stepVolume",
        "toggleMute",
        "playNext",
        "playPrevious",
        "playIndex",
        "index",
        "queueNext",
        "path",
        "unqueue",
        "cycleRepeatMode",
        "setRepeatMode",
        "mode",
        "cycleAudioTrack",
        "setAudioTrack",
        "adjustAvSync",
        "deltaMs",
        "resetAvSync",
        "setAbRepeatA",
        "setAbRepeatB",
        "clearAbRepeat",
        "addBookmark",
        "removeBookmark",
        "bookmarkList",
        "QVariantList",
        "chapterList",
        "currentChapterIndex",
        "jumpToChapter",
        "chapterAt",
        "toggleSceneAnalysis",
        "thumbnailUrl",
        "toggleSubtitles",
        "startAiSubtitles",
        "startTranslation",
        "toggleAssStyles",
        "toggleNightMode",
        "setSleepTimer",
        "minutes",
        "cycleSleepTimer",
        "setRotation",
        "method",
        "cycleRotation",
        "toggleHdrTonemap",
        "toggleLoudness",
        "eqPresets",
        "setEqPreset",
        "key",
        "togglePassthrough",
        "cancelAutoplay",
        "autoplayNow",
        "setting",
        "setSetting",
        "value",
        "toggleSetting",
        "toggleFullscreen",
        "toggleMiniPlayer",
        "resizeMini",
        "factor",
        "moveWindowBy",
        "dx",
        "dy",
        "noteMouseActivity",
        "setControlsHovered",
        "hovered",
        "toggleRemainingTime",
        "toggleHud",
        "toggleKeepAbove",
        "toggleSidebar",
        "rememberWindowGeometry",
        "x",
        "y",
        "w",
        "h",
        "maximized",
        "miniGeometry",
        "QVariantMap",
        "screenW",
        "screenH",
        "restoreGeometry",
        "handleKey",
        "modifiers",
        "text",
        "handleEscape",
        "requestDialog",
        "helpRows",
        "formatTime",
        "captureScreenshot",
        "openLogFile",
        "copyText",
        "osd",
        "quit",
        "shutdown",
        "width",
        "height",
        "openUrls",
        "QList<QUrl>",
        "urls",
        "openPath",
        "dropUrls",
        "dropText",
        "suggestedM3uUrl",
        "QUrl",
        "saveM3u",
        "url",
        "rescanPlaylist",
        "quiet",
        "cyclePlaylistSort",
        "openCurrentLocation",
        "openLocation",
        "history",
        "networkLocations",
        "openNetworkUri",
        "uri",
        "refreshDialogueIndex",
        "searchDialogue",
        "query",
        "dialogueSearchStatus",
        "count",
        "jumpToDialogue",
        "video",
        "startMs",
        "clipboardYoutubeUrl",
        "startYoutube",
        "quality",
        "cancelYoutube",
        "title",
        "nowPlayingText",
        "hasVideo",
        "playing",
        "volume",
        "muted",
        "repeatMode",
        "repeatModeLabel",
        "positionMs",
        "durationMs",
        "positionText",
        "durationText",
        "frameBridge",
        "fullscreen",
        "miniMode",
        "keepAbove",
        "sidebarVisible",
        "sidebarWidth",
        "windowWidth",
        "windowHeight",
        "windowMaximized",
        "kiosk",
        "uiMode",
        "controlsVisible",
        "cursorHidden",
        "osdText",
        "hudVisible",
        "hudText",
        "rotation",
        "hdrMode",
        "hdrMatrixFix",
        "settings",
        "abA",
        "abB",
        "abActive",
        "abLabel",
        "timelineMarks",
        "resumeCards",
        "autoplay",
        "sleepMinutes",
        "sleepMenuLabel",
        "nightMode",
        "loudnessMenuLabel",
        "eqPresetName",
        "subtitleButtonText",
        "chaptersTitle",
        "chaptersEmptyText",
        "sceneAnalysisLabel",
        "sceneAnalysisAvailable",
        "youtubeLoading",
        "youtube",
        "playlist",
        "jvp::PlaylistModel*",
        "subtitles",
        "jvp::SubtitleController*",
        "ai",
        "jvp::AiController*",
        "translation",
        "jvp::TranslationController*",
        "onlineSubs",
        "jvp::OnlineSubsController*",
        "network",
        "remote",
        "jvp::RemoteInfo*"
    };

    QtMocHelpers::UintData qt_methods {
        // Signal 'mediaChanged'
        QtMocHelpers::SignalData<void()>(5, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'playbackChanged'
        QtMocHelpers::SignalData<void()>(7, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'positionChanged'
        QtMocHelpers::SignalData<void()>(8, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'fullscreenChanged'
        QtMocHelpers::SignalData<void()>(9, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'miniModeChanged'
        QtMocHelpers::SignalData<void()>(10, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'viewChanged'
        QtMocHelpers::SignalData<void()>(11, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'hudChanged'
        QtMocHelpers::SignalData<void()>(12, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'settingsChanged'
        QtMocHelpers::SignalData<void()>(13, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'marksChanged'
        QtMocHelpers::SignalData<void()>(14, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'resumeCardsChanged'
        QtMocHelpers::SignalData<void()>(15, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'autoplayChanged'
        QtMocHelpers::SignalData<void()>(16, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'stateChanged'
        QtMocHelpers::SignalData<void()>(17, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'subtitlesChanged'
        QtMocHelpers::SignalData<void()>(18, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'chaptersChanged'
        QtMocHelpers::SignalData<void()>(19, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'youtubeChanged'
        QtMocHelpers::SignalData<void()>(20, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'osdShown'
        QtMocHelpers::SignalData<void(int)>(21, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 22 },
        }}),
        // Signal 'quitRequested'
        QtMocHelpers::SignalData<void()>(23, 6, QMC::AccessPublic, QMetaType::Void),
        // Signal 'dialogRequested'
        QtMocHelpers::SignalData<void(const QString &, const QVariant &)>(24, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 25 }, { 0x80000000 | 26, 27 },
        }}),
        // Signal 'dialogueIndexReady'
        QtMocHelpers::SignalData<void()>(28, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'togglePlayPause'
        QtMocHelpers::MethodData<void()>(29, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'seekRelative'
        QtMocHelpers::MethodData<void(double)>(30, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 31 },
        }}),
        // Method 'scrubTo'
        QtMocHelpers::MethodData<void(double)>(32, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 33 },
        }}),
        // Method 'seekToRatio'
        QtMocHelpers::MethodData<void(double)>(34, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 33 },
        }}),
        // Method 'seekToPercent'
        QtMocHelpers::MethodData<void(double)>(35, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 36 },
        }}),
        // Method 'jumpToMs'
        QtMocHelpers::MethodData<void(double)>(37, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 22 },
        }}),
        // Method 'frameStep'
        QtMocHelpers::MethodData<void(int)>(38, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 39 },
        }}),
        // Method 'setRate'
        QtMocHelpers::MethodData<void(double)>(40, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 41 },
        }}),
        // Method 'stepRate'
        QtMocHelpers::MethodData<void(double)>(42, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 43 },
        }}),
        // Method 'resetRate'
        QtMocHelpers::MethodData<void()>(44, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setVolume'
        QtMocHelpers::MethodData<void(double)>(45, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 46 },
        }}),
        // Method 'stepVolume'
        QtMocHelpers::MethodData<void(int)>(47, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 43 },
        }}),
        // Method 'toggleMute'
        QtMocHelpers::MethodData<void()>(48, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'playNext'
        QtMocHelpers::MethodData<void()>(49, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'playPrevious'
        QtMocHelpers::MethodData<void()>(50, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'playIndex'
        QtMocHelpers::MethodData<void(int)>(51, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 52 },
        }}),
        // Method 'queueNext'
        QtMocHelpers::MethodData<void(const QString &)>(53, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 54 },
        }}),
        // Method 'unqueue'
        QtMocHelpers::MethodData<void(const QString &)>(55, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 54 },
        }}),
        // Method 'cycleRepeatMode'
        QtMocHelpers::MethodData<void()>(56, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setRepeatMode'
        QtMocHelpers::MethodData<void(const QString &)>(57, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 58 },
        }}),
        // Method 'cycleAudioTrack'
        QtMocHelpers::MethodData<void()>(59, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setAudioTrack'
        QtMocHelpers::MethodData<void(int)>(60, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 52 },
        }}),
        // Method 'adjustAvSync'
        QtMocHelpers::MethodData<void(int)>(61, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 62 },
        }}),
        // Method 'resetAvSync'
        QtMocHelpers::MethodData<void()>(63, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setAbRepeatA'
        QtMocHelpers::MethodData<void()>(64, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setAbRepeatB'
        QtMocHelpers::MethodData<void()>(65, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'clearAbRepeat'
        QtMocHelpers::MethodData<void()>(66, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'addBookmark'
        QtMocHelpers::MethodData<void()>(67, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'removeBookmark'
        QtMocHelpers::MethodData<void(int)>(68, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 52 },
        }}),
        // Method 'bookmarkList'
        QtMocHelpers::MethodData<QVariantList() const>(69, 6, QMC::AccessPublic, 0x80000000 | 70),
        // Method 'chapterList'
        QtMocHelpers::MethodData<QVariantList() const>(71, 6, QMC::AccessPublic, 0x80000000 | 70),
        // Method 'currentChapterIndex'
        QtMocHelpers::MethodData<int() const>(72, 6, QMC::AccessPublic, QMetaType::Int),
        // Method 'jumpToChapter'
        QtMocHelpers::MethodData<void(double)>(73, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 22 },
        }}),
        // Method 'chapterAt'
        QtMocHelpers::MethodData<QString(double) const>(74, 6, QMC::AccessPublic, QMetaType::QString, {{
            { QMetaType::Double, 22 },
        }}),
        // Method 'toggleSceneAnalysis'
        QtMocHelpers::MethodData<void()>(75, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'thumbnailUrl'
        QtMocHelpers::MethodData<QString(double) const>(76, 6, QMC::AccessPublic, QMetaType::QString, {{
            { QMetaType::Double, 22 },
        }}),
        // Method 'toggleSubtitles'
        QtMocHelpers::MethodData<void()>(77, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'startAiSubtitles'
        QtMocHelpers::MethodData<void()>(78, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'startTranslation'
        QtMocHelpers::MethodData<void()>(79, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleAssStyles'
        QtMocHelpers::MethodData<void()>(80, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleNightMode'
        QtMocHelpers::MethodData<void()>(81, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setSleepTimer'
        QtMocHelpers::MethodData<void(int)>(82, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 83 },
        }}),
        // Method 'cycleSleepTimer'
        QtMocHelpers::MethodData<void()>(84, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setRotation'
        QtMocHelpers::MethodData<void(const QString &)>(85, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 86 },
        }}),
        // Method 'cycleRotation'
        QtMocHelpers::MethodData<void()>(87, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleHdrTonemap'
        QtMocHelpers::MethodData<void()>(88, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleLoudness'
        QtMocHelpers::MethodData<void()>(89, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'eqPresets'
        QtMocHelpers::MethodData<QVariantList() const>(90, 6, QMC::AccessPublic, 0x80000000 | 70),
        // Method 'setEqPreset'
        QtMocHelpers::MethodData<void(const QString &)>(91, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 92 },
        }}),
        // Method 'togglePassthrough'
        QtMocHelpers::MethodData<void()>(93, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'cancelAutoplay'
        QtMocHelpers::MethodData<void()>(94, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'autoplayNow'
        QtMocHelpers::MethodData<void()>(95, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setting'
        QtMocHelpers::MethodData<QVariant(const QString &) const>(96, 6, QMC::AccessPublic, 0x80000000 | 26, {{
            { QMetaType::QString, 92 },
        }}),
        // Method 'setSetting'
        QtMocHelpers::MethodData<void(const QString &, const QVariant &)>(97, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 92 }, { 0x80000000 | 26, 98 },
        }}),
        // Method 'toggleSetting'
        QtMocHelpers::MethodData<void(const QString &)>(99, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 92 },
        }}),
        // Method 'toggleFullscreen'
        QtMocHelpers::MethodData<void()>(100, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleMiniPlayer'
        QtMocHelpers::MethodData<void()>(101, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'resizeMini'
        QtMocHelpers::MethodData<void(double)>(102, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 103 },
        }}),
        // Method 'moveWindowBy'
        QtMocHelpers::MethodData<void(double, double)>(104, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Double, 105 }, { QMetaType::Double, 106 },
        }}),
        // Method 'noteMouseActivity'
        QtMocHelpers::MethodData<void()>(107, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'setControlsHovered'
        QtMocHelpers::MethodData<void(bool)>(108, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Bool, 109 },
        }}),
        // Method 'toggleRemainingTime'
        QtMocHelpers::MethodData<void()>(110, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleHud'
        QtMocHelpers::MethodData<void()>(111, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleKeepAbove'
        QtMocHelpers::MethodData<void()>(112, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'toggleSidebar'
        QtMocHelpers::MethodData<void()>(113, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'rememberWindowGeometry'
        QtMocHelpers::MethodData<void(int, int, int, int, bool)>(114, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 115 }, { QMetaType::Int, 116 }, { QMetaType::Int, 117 }, { QMetaType::Int, 118 },
            { QMetaType::Bool, 119 },
        }}),
        // Method 'miniGeometry'
        QtMocHelpers::MethodData<QVariantMap(int, int)>(120, 6, QMC::AccessPublic, 0x80000000 | 121, {{
            { QMetaType::Int, 122 }, { QMetaType::Int, 123 },
        }}),
        // Method 'restoreGeometry'
        QtMocHelpers::MethodData<QVariantMap()>(124, 6, QMC::AccessPublic, 0x80000000 | 121),
        // Method 'handleKey'
        QtMocHelpers::MethodData<bool(int, int, const QString &)>(125, 6, QMC::AccessPublic, QMetaType::Bool, {{
            { QMetaType::Int, 92 }, { QMetaType::Int, 126 }, { QMetaType::QString, 127 },
        }}),
        // Method 'handleEscape'
        QtMocHelpers::MethodData<void()>(128, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'requestDialog'
        QtMocHelpers::MethodData<void(const QString &, const QVariant &)>(129, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 25 }, { 0x80000000 | 26, 27 },
        }}),
        // Method 'requestDialog'
        QtMocHelpers::MethodData<void(const QString &)>(129, 6, QMC::AccessPublic | QMC::MethodCloned, QMetaType::Void, {{
            { QMetaType::QString, 25 },
        }}),
        // Method 'helpRows'
        QtMocHelpers::MethodData<QVariantList() const>(130, 6, QMC::AccessPublic, 0x80000000 | 70),
        // Method 'formatTime'
        QtMocHelpers::MethodData<QString(double) const>(131, 6, QMC::AccessPublic, QMetaType::QString, {{
            { QMetaType::Double, 22 },
        }}),
        // Method 'captureScreenshot'
        QtMocHelpers::MethodData<void()>(132, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'openLogFile'
        QtMocHelpers::MethodData<void()>(133, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'copyText'
        QtMocHelpers::MethodData<void(const QString &, const QString &)>(134, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 127 }, { QMetaType::QString, 135 },
        }}),
        // Method 'copyText'
        QtMocHelpers::MethodData<void(const QString &)>(134, 6, QMC::AccessPublic | QMC::MethodCloned, QMetaType::Void, {{
            { QMetaType::QString, 127 },
        }}),
        // Method 'quit'
        QtMocHelpers::MethodData<void()>(136, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'shutdown'
        QtMocHelpers::MethodData<void(int, int, bool)>(137, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Int, 138 }, { QMetaType::Int, 139 }, { QMetaType::Bool, 119 },
        }}),
        // Method 'openUrls'
        QtMocHelpers::MethodData<void(const QList<QUrl> &)>(140, 6, QMC::AccessPublic, QMetaType::Void, {{
            { 0x80000000 | 141, 142 },
        }}),
        // Method 'openPath'
        QtMocHelpers::MethodData<void(const QString &)>(143, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 54 },
        }}),
        // Method 'dropUrls'
        QtMocHelpers::MethodData<void(const QList<QUrl> &)>(144, 6, QMC::AccessPublic, QMetaType::Void, {{
            { 0x80000000 | 141, 142 },
        }}),
        // Method 'dropText'
        QtMocHelpers::MethodData<void(const QString &)>(145, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 127 },
        }}),
        // Method 'suggestedM3uUrl'
        QtMocHelpers::MethodData<QUrl() const>(146, 6, QMC::AccessPublic, 0x80000000 | 147),
        // Method 'saveM3u'
        QtMocHelpers::MethodData<void(const QUrl &)>(148, 6, QMC::AccessPublic, QMetaType::Void, {{
            { 0x80000000 | 147, 149 },
        }}),
        // Method 'rescanPlaylist'
        QtMocHelpers::MethodData<void(bool)>(150, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::Bool, 151 },
        }}),
        // Method 'rescanPlaylist'
        QtMocHelpers::MethodData<void()>(150, 6, QMC::AccessPublic | QMC::MethodCloned, QMetaType::Void),
        // Method 'cyclePlaylistSort'
        QtMocHelpers::MethodData<void()>(152, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'openCurrentLocation'
        QtMocHelpers::MethodData<void()>(153, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'openLocation'
        QtMocHelpers::MethodData<void(const QString &)>(154, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 54 },
        }}),
        // Method 'history'
        QtMocHelpers::MethodData<QVariantList() const>(155, 6, QMC::AccessPublic, 0x80000000 | 70),
        // Method 'networkLocations'
        QtMocHelpers::MethodData<QVariantList() const>(156, 6, QMC::AccessPublic, 0x80000000 | 70),
        // Method 'openNetworkUri'
        QtMocHelpers::MethodData<void(const QString &)>(157, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 158 },
        }}),
        // Method 'refreshDialogueIndex'
        QtMocHelpers::MethodData<void()>(159, 6, QMC::AccessPublic, QMetaType::Void),
        // Method 'searchDialogue'
        QtMocHelpers::MethodData<QVariantList(const QString &)>(160, 6, QMC::AccessPublic, 0x80000000 | 70, {{
            { QMetaType::QString, 161 },
        }}),
        // Method 'dialogueSearchStatus'
        QtMocHelpers::MethodData<QString(const QString &, int) const>(162, 6, QMC::AccessPublic, QMetaType::QString, {{
            { QMetaType::QString, 161 }, { QMetaType::Int, 163 },
        }}),
        // Method 'jumpToDialogue'
        QtMocHelpers::MethodData<void(const QString &, double)>(164, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 165 }, { QMetaType::Double, 166 },
        }}),
        // Method 'clipboardYoutubeUrl'
        QtMocHelpers::MethodData<QString() const>(167, 6, QMC::AccessPublic, QMetaType::QString),
        // Method 'startYoutube'
        QtMocHelpers::MethodData<void(const QString &, const QString &)>(168, 6, QMC::AccessPublic, QMetaType::Void, {{
            { QMetaType::QString, 149 }, { QMetaType::QString, 169 },
        }}),
        // Method 'startYoutube'
        QtMocHelpers::MethodData<void(const QString &)>(168, 6, QMC::AccessPublic | QMC::MethodCloned, QMetaType::Void, {{
            { QMetaType::QString, 149 },
        }}),
        // Method 'cancelYoutube'
        QtMocHelpers::MethodData<void()>(170, 6, QMC::AccessPublic, QMetaType::Void),
    };
    QtMocHelpers::UintData qt_properties {
        // property 'title'
        QtMocHelpers::PropertyData<QString>(171, QMetaType::QString, QMC::DefaultPropertyFlags, 0),
        // property 'nowPlayingText'
        QtMocHelpers::PropertyData<QString>(172, QMetaType::QString, QMC::DefaultPropertyFlags, 0),
        // property 'hasVideo'
        QtMocHelpers::PropertyData<bool>(173, QMetaType::Bool, QMC::DefaultPropertyFlags, 0),
        // property 'playing'
        QtMocHelpers::PropertyData<bool>(174, QMetaType::Bool, QMC::DefaultPropertyFlags, 1),
        // property 'rate'
        QtMocHelpers::PropertyData<double>(41, QMetaType::Double, QMC::DefaultPropertyFlags, 1),
        // property 'volume'
        QtMocHelpers::PropertyData<int>(175, QMetaType::Int, QMC::DefaultPropertyFlags, 1),
        // property 'muted'
        QtMocHelpers::PropertyData<bool>(176, QMetaType::Bool, QMC::DefaultPropertyFlags, 1),
        // property 'repeatMode'
        QtMocHelpers::PropertyData<QString>(177, QMetaType::QString, QMC::DefaultPropertyFlags, 1),
        // property 'repeatModeLabel'
        QtMocHelpers::PropertyData<QString>(178, QMetaType::QString, QMC::DefaultPropertyFlags, 1),
        // property 'positionMs'
        QtMocHelpers::PropertyData<double>(179, QMetaType::Double, QMC::DefaultPropertyFlags, 2),
        // property 'durationMs'
        QtMocHelpers::PropertyData<double>(180, QMetaType::Double, QMC::DefaultPropertyFlags, 2),
        // property 'positionText'
        QtMocHelpers::PropertyData<QString>(181, QMetaType::QString, QMC::DefaultPropertyFlags, 2),
        // property 'durationText'
        QtMocHelpers::PropertyData<QString>(182, QMetaType::QString, QMC::DefaultPropertyFlags, 2),
        // property 'frameBridge'
        QtMocHelpers::PropertyData<QObject*>(183, QMetaType::QObjectStar, QMC::DefaultPropertyFlags | QMC::Constant),
        // property 'fullscreen'
        QtMocHelpers::PropertyData<bool>(184, QMetaType::Bool, QMC::DefaultPropertyFlags, 3),
        // property 'miniMode'
        QtMocHelpers::PropertyData<bool>(185, QMetaType::Bool, QMC::DefaultPropertyFlags, 4),
        // property 'keepAbove'
        QtMocHelpers::PropertyData<bool>(186, QMetaType::Bool, QMC::DefaultPropertyFlags, 5),
        // property 'sidebarVisible'
        QtMocHelpers::PropertyData<bool>(187, QMetaType::Bool, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 5),
        // property 'sidebarWidth'
        QtMocHelpers::PropertyData<int>(188, QMetaType::Int, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 5),
        // property 'windowWidth'
        QtMocHelpers::PropertyData<int>(189, QMetaType::Int, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 5),
        // property 'windowHeight'
        QtMocHelpers::PropertyData<int>(190, QMetaType::Int, QMC::DefaultPropertyFlags | QMC::Writable | QMC::StdCppSet, 5),
        // property 'windowMaximized'
        QtMocHelpers::PropertyData<bool>(191, QMetaType::Bool, QMC::DefaultPropertyFlags, 5),
        // property 'kiosk'
        QtMocHelpers::PropertyData<bool>(192, QMetaType::Bool, QMC::DefaultPropertyFlags | QMC::Constant),
        // property 'uiMode'
        QtMocHelpers::PropertyData<QString>(193, QMetaType::QString, QMC::DefaultPropertyFlags, 5),
        // property 'controlsVisible'
        QtMocHelpers::PropertyData<bool>(194, QMetaType::Bool, QMC::DefaultPropertyFlags, 5),
        // property 'cursorHidden'
        QtMocHelpers::PropertyData<bool>(195, QMetaType::Bool, QMC::DefaultPropertyFlags, 5),
        // property 'osdText'
        QtMocHelpers::PropertyData<QString>(196, QMetaType::QString, QMC::DefaultPropertyFlags, 15),
        // property 'hudVisible'
        QtMocHelpers::PropertyData<bool>(197, QMetaType::Bool, QMC::DefaultPropertyFlags, 6),
        // property 'hudText'
        QtMocHelpers::PropertyData<QString>(198, QMetaType::QString, QMC::DefaultPropertyFlags, 6),
        // property 'rotation'
        QtMocHelpers::PropertyData<QString>(199, QMetaType::QString, QMC::DefaultPropertyFlags, 5),
        // property 'hdrMode'
        QtMocHelpers::PropertyData<QString>(200, QMetaType::QString, QMC::DefaultPropertyFlags, 5),
        // property 'hdrMatrixFix'
        QtMocHelpers::PropertyData<bool>(201, QMetaType::Bool, QMC::DefaultPropertyFlags, 5),
        // property 'settings'
        QtMocHelpers::PropertyData<QVariantMap>(202, 0x80000000 | 121, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 7),
        // property 'abA'
        QtMocHelpers::PropertyData<double>(203, QMetaType::Double, QMC::DefaultPropertyFlags, 8),
        // property 'abB'
        QtMocHelpers::PropertyData<double>(204, QMetaType::Double, QMC::DefaultPropertyFlags, 8),
        // property 'abActive'
        QtMocHelpers::PropertyData<bool>(205, QMetaType::Bool, QMC::DefaultPropertyFlags, 8),
        // property 'abLabel'
        QtMocHelpers::PropertyData<QString>(206, QMetaType::QString, QMC::DefaultPropertyFlags, 8),
        // property 'timelineMarks'
        QtMocHelpers::PropertyData<QVariantList>(207, 0x80000000 | 70, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 8),
        // property 'resumeCards'
        QtMocHelpers::PropertyData<QVariantList>(208, 0x80000000 | 70, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 9),
        // property 'autoplay'
        QtMocHelpers::PropertyData<QVariantMap>(209, 0x80000000 | 121, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 10),
        // property 'sleepMinutes'
        QtMocHelpers::PropertyData<int>(210, QMetaType::Int, QMC::DefaultPropertyFlags, 11),
        // property 'sleepMenuLabel'
        QtMocHelpers::PropertyData<QString>(211, QMetaType::QString, QMC::DefaultPropertyFlags, 11),
        // property 'nightMode'
        QtMocHelpers::PropertyData<bool>(212, QMetaType::Bool, QMC::DefaultPropertyFlags, 7),
        // property 'loudnessMenuLabel'
        QtMocHelpers::PropertyData<QString>(213, QMetaType::QString, QMC::DefaultPropertyFlags, 11),
        // property 'eqPresetName'
        QtMocHelpers::PropertyData<QString>(214, QMetaType::QString, QMC::DefaultPropertyFlags, 7),
        // property 'subtitleButtonText'
        QtMocHelpers::PropertyData<QString>(215, QMetaType::QString, QMC::DefaultPropertyFlags, 12),
        // property 'chaptersTitle'
        QtMocHelpers::PropertyData<QString>(216, QMetaType::QString, QMC::DefaultPropertyFlags, 13),
        // property 'chaptersEmptyText'
        QtMocHelpers::PropertyData<QString>(217, QMetaType::QString, QMC::DefaultPropertyFlags, 13),
        // property 'sceneAnalysisLabel'
        QtMocHelpers::PropertyData<QString>(218, QMetaType::QString, QMC::DefaultPropertyFlags, 13),
        // property 'sceneAnalysisAvailable'
        QtMocHelpers::PropertyData<bool>(219, QMetaType::Bool, QMC::DefaultPropertyFlags, 13),
        // property 'youtubeLoading'
        QtMocHelpers::PropertyData<bool>(220, QMetaType::Bool, QMC::DefaultPropertyFlags, 14),
        // property 'youtube'
        QtMocHelpers::PropertyData<QVariantMap>(221, 0x80000000 | 121, QMC::DefaultPropertyFlags | QMC::EnumOrFlag, 14),
        // property 'playlist'
        QtMocHelpers::PropertyData<jvp::PlaylistModel*>(222, 0x80000000 | 223, QMC::DefaultPropertyFlags | QMC::EnumOrFlag | QMC::Constant),
        // property 'subtitles'
        QtMocHelpers::PropertyData<jvp::SubtitleController*>(224, 0x80000000 | 225, QMC::DefaultPropertyFlags | QMC::EnumOrFlag | QMC::Constant),
        // property 'ai'
        QtMocHelpers::PropertyData<jvp::AiController*>(226, 0x80000000 | 227, QMC::DefaultPropertyFlags | QMC::EnumOrFlag | QMC::Constant),
        // property 'translation'
        QtMocHelpers::PropertyData<jvp::TranslationController*>(228, 0x80000000 | 229, QMC::DefaultPropertyFlags | QMC::EnumOrFlag | QMC::Constant),
        // property 'onlineSubs'
        QtMocHelpers::PropertyData<jvp::OnlineSubsController*>(230, 0x80000000 | 231, QMC::DefaultPropertyFlags | QMC::EnumOrFlag | QMC::Constant),
        // property 'network'
        QtMocHelpers::PropertyData<QObject*>(232, QMetaType::QObjectStar, QMC::DefaultPropertyFlags | QMC::Constant),
        // property 'remote'
        QtMocHelpers::PropertyData<jvp::RemoteInfo*>(233, 0x80000000 | 234, QMC::DefaultPropertyFlags | QMC::EnumOrFlag | QMC::Constant),
    };
    QtMocHelpers::UintData qt_enums {
    };
    QtMocHelpers::UintData qt_constructors {};
    QtMocHelpers::ClassInfos qt_classinfo({
            {    1,    2 },
            {    3,    4 },
    });
    return QtMocHelpers::metaObjectData<AppController, void>(QMC::MetaObjectFlag{}, qt_stringData,
            qt_methods, qt_properties, qt_enums, qt_constructors, qt_classinfo);
}
Q_CONSTINIT const QMetaObject jvp::AppController::staticMetaObject = { {
    QMetaObject::SuperData::link<QObject::staticMetaObject>(),
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp13AppControllerE_t>.stringdata,
    qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp13AppControllerE_t>.data,
    qt_static_metacall,
    nullptr,
    qt_staticMetaObjectRelocatingContent<qt_meta_tag_ZN3jvp13AppControllerE_t>.metaTypes,
    nullptr
} };

void jvp::AppController::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    auto *_t = static_cast<AppController *>(_o);
    if (_c == QMetaObject::InvokeMetaMethod) {
        switch (_id) {
        case 0: _t->mediaChanged(); break;
        case 1: _t->playbackChanged(); break;
        case 2: _t->positionChanged(); break;
        case 3: _t->fullscreenChanged(); break;
        case 4: _t->miniModeChanged(); break;
        case 5: _t->viewChanged(); break;
        case 6: _t->hudChanged(); break;
        case 7: _t->settingsChanged(); break;
        case 8: _t->marksChanged(); break;
        case 9: _t->resumeCardsChanged(); break;
        case 10: _t->autoplayChanged(); break;
        case 11: _t->stateChanged(); break;
        case 12: _t->subtitlesChanged(); break;
        case 13: _t->chaptersChanged(); break;
        case 14: _t->youtubeChanged(); break;
        case 15: _t->osdShown((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 16: _t->quitRequested(); break;
        case 17: _t->dialogRequested((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QVariant>>(_a[2]))); break;
        case 18: _t->dialogueIndexReady(); break;
        case 19: _t->togglePlayPause(); break;
        case 20: _t->seekRelative((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 21: _t->scrubTo((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 22: _t->seekToRatio((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 23: _t->seekToPercent((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 24: _t->jumpToMs((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 25: _t->frameStep((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 26: _t->setRate((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 27: _t->stepRate((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 28: _t->resetRate(); break;
        case 29: _t->setVolume((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 30: _t->stepVolume((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 31: _t->toggleMute(); break;
        case 32: _t->playNext(); break;
        case 33: _t->playPrevious(); break;
        case 34: _t->playIndex((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 35: _t->queueNext((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 36: _t->unqueue((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 37: _t->cycleRepeatMode(); break;
        case 38: _t->setRepeatMode((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 39: _t->cycleAudioTrack(); break;
        case 40: _t->setAudioTrack((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 41: _t->adjustAvSync((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 42: _t->resetAvSync(); break;
        case 43: _t->setAbRepeatA(); break;
        case 44: _t->setAbRepeatB(); break;
        case 45: _t->clearAbRepeat(); break;
        case 46: _t->addBookmark(); break;
        case 47: _t->removeBookmark((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 48: { QVariantList _r = _t->bookmarkList();
            if (_a[0]) *reinterpret_cast<QVariantList*>(_a[0]) = std::move(_r); }  break;
        case 49: { QVariantList _r = _t->chapterList();
            if (_a[0]) *reinterpret_cast<QVariantList*>(_a[0]) = std::move(_r); }  break;
        case 50: { int _r = _t->currentChapterIndex();
            if (_a[0]) *reinterpret_cast<int*>(_a[0]) = std::move(_r); }  break;
        case 51: _t->jumpToChapter((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 52: { QString _r = _t->chapterAt((*reinterpret_cast<std::add_pointer_t<double>>(_a[1])));
            if (_a[0]) *reinterpret_cast<QString*>(_a[0]) = std::move(_r); }  break;
        case 53: _t->toggleSceneAnalysis(); break;
        case 54: { QString _r = _t->thumbnailUrl((*reinterpret_cast<std::add_pointer_t<double>>(_a[1])));
            if (_a[0]) *reinterpret_cast<QString*>(_a[0]) = std::move(_r); }  break;
        case 55: _t->toggleSubtitles(); break;
        case 56: _t->startAiSubtitles(); break;
        case 57: _t->startTranslation(); break;
        case 58: _t->toggleAssStyles(); break;
        case 59: _t->toggleNightMode(); break;
        case 60: _t->setSleepTimer((*reinterpret_cast<std::add_pointer_t<int>>(_a[1]))); break;
        case 61: _t->cycleSleepTimer(); break;
        case 62: _t->setRotation((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 63: _t->cycleRotation(); break;
        case 64: _t->toggleHdrTonemap(); break;
        case 65: _t->toggleLoudness(); break;
        case 66: { QVariantList _r = _t->eqPresets();
            if (_a[0]) *reinterpret_cast<QVariantList*>(_a[0]) = std::move(_r); }  break;
        case 67: _t->setEqPreset((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 68: _t->togglePassthrough(); break;
        case 69: _t->cancelAutoplay(); break;
        case 70: _t->autoplayNow(); break;
        case 71: { QVariant _r = _t->setting((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])));
            if (_a[0]) *reinterpret_cast<QVariant*>(_a[0]) = std::move(_r); }  break;
        case 72: _t->setSetting((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QVariant>>(_a[2]))); break;
        case 73: _t->toggleSetting((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 74: _t->toggleFullscreen(); break;
        case 75: _t->toggleMiniPlayer(); break;
        case 76: _t->resizeMini((*reinterpret_cast<std::add_pointer_t<double>>(_a[1]))); break;
        case 77: _t->moveWindowBy((*reinterpret_cast<std::add_pointer_t<double>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<double>>(_a[2]))); break;
        case 78: _t->noteMouseActivity(); break;
        case 79: _t->setControlsHovered((*reinterpret_cast<std::add_pointer_t<bool>>(_a[1]))); break;
        case 80: _t->toggleRemainingTime(); break;
        case 81: _t->toggleHud(); break;
        case 82: _t->toggleKeepAbove(); break;
        case 83: _t->toggleSidebar(); break;
        case 84: _t->rememberWindowGeometry((*reinterpret_cast<std::add_pointer_t<int>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[3])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[4])),(*reinterpret_cast<std::add_pointer_t<bool>>(_a[5]))); break;
        case 85: { QVariantMap _r = _t->miniGeometry((*reinterpret_cast<std::add_pointer_t<int>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[2])));
            if (_a[0]) *reinterpret_cast<QVariantMap*>(_a[0]) = std::move(_r); }  break;
        case 86: { QVariantMap _r = _t->restoreGeometry();
            if (_a[0]) *reinterpret_cast<QVariantMap*>(_a[0]) = std::move(_r); }  break;
        case 87: { bool _r = _t->handleKey((*reinterpret_cast<std::add_pointer_t<int>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[3])));
            if (_a[0]) *reinterpret_cast<bool*>(_a[0]) = std::move(_r); }  break;
        case 88: _t->handleEscape(); break;
        case 89: _t->requestDialog((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QVariant>>(_a[2]))); break;
        case 90: _t->requestDialog((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 91: { QVariantList _r = _t->helpRows();
            if (_a[0]) *reinterpret_cast<QVariantList*>(_a[0]) = std::move(_r); }  break;
        case 92: { QString _r = _t->formatTime((*reinterpret_cast<std::add_pointer_t<double>>(_a[1])));
            if (_a[0]) *reinterpret_cast<QString*>(_a[0]) = std::move(_r); }  break;
        case 93: _t->captureScreenshot(); break;
        case 94: _t->openLogFile(); break;
        case 95: _t->copyText((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[2]))); break;
        case 96: _t->copyText((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 97: _t->quit(); break;
        case 98: _t->shutdown((*reinterpret_cast<std::add_pointer_t<int>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[2])),(*reinterpret_cast<std::add_pointer_t<bool>>(_a[3]))); break;
        case 99: _t->openUrls((*reinterpret_cast<std::add_pointer_t<QList<QUrl>>>(_a[1]))); break;
        case 100: _t->openPath((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 101: _t->dropUrls((*reinterpret_cast<std::add_pointer_t<QList<QUrl>>>(_a[1]))); break;
        case 102: _t->dropText((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 103: { QUrl _r = _t->suggestedM3uUrl();
            if (_a[0]) *reinterpret_cast<QUrl*>(_a[0]) = std::move(_r); }  break;
        case 104: _t->saveM3u((*reinterpret_cast<std::add_pointer_t<QUrl>>(_a[1]))); break;
        case 105: _t->rescanPlaylist((*reinterpret_cast<std::add_pointer_t<bool>>(_a[1]))); break;
        case 106: _t->rescanPlaylist(); break;
        case 107: _t->cyclePlaylistSort(); break;
        case 108: _t->openCurrentLocation(); break;
        case 109: _t->openLocation((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 110: { QVariantList _r = _t->history();
            if (_a[0]) *reinterpret_cast<QVariantList*>(_a[0]) = std::move(_r); }  break;
        case 111: { QVariantList _r = _t->networkLocations();
            if (_a[0]) *reinterpret_cast<QVariantList*>(_a[0]) = std::move(_r); }  break;
        case 112: _t->openNetworkUri((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 113: _t->refreshDialogueIndex(); break;
        case 114: { QVariantList _r = _t->searchDialogue((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])));
            if (_a[0]) *reinterpret_cast<QVariantList*>(_a[0]) = std::move(_r); }  break;
        case 115: { QString _r = _t->dialogueSearchStatus((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<int>>(_a[2])));
            if (_a[0]) *reinterpret_cast<QString*>(_a[0]) = std::move(_r); }  break;
        case 116: _t->jumpToDialogue((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<double>>(_a[2]))); break;
        case 117: { QString _r = _t->clipboardYoutubeUrl();
            if (_a[0]) *reinterpret_cast<QString*>(_a[0]) = std::move(_r); }  break;
        case 118: _t->startYoutube((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1])),(*reinterpret_cast<std::add_pointer_t<QString>>(_a[2]))); break;
        case 119: _t->startYoutube((*reinterpret_cast<std::add_pointer_t<QString>>(_a[1]))); break;
        case 120: _t->cancelYoutube(); break;
        default: ;
        }
    }
    if (_c == QMetaObject::IndexOfMethod) {
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::mediaChanged, 0))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::playbackChanged, 1))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::positionChanged, 2))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::fullscreenChanged, 3))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::miniModeChanged, 4))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::viewChanged, 5))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::hudChanged, 6))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::settingsChanged, 7))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::marksChanged, 8))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::resumeCardsChanged, 9))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::autoplayChanged, 10))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::stateChanged, 11))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::subtitlesChanged, 12))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::chaptersChanged, 13))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::youtubeChanged, 14))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)(int )>(_a, &AppController::osdShown, 15))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::quitRequested, 16))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)(const QString & , const QVariant & )>(_a, &AppController::dialogRequested, 17))
            return;
        if (QtMocHelpers::indexOfMethod<void (AppController::*)()>(_a, &AppController::dialogueIndexReady, 18))
            return;
    }
    if (_c == QMetaObject::ReadProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 0: *reinterpret_cast<QString*>(_v) = _t->title(); break;
        case 1: *reinterpret_cast<QString*>(_v) = _t->nowPlayingText(); break;
        case 2: *reinterpret_cast<bool*>(_v) = _t->hasVideo(); break;
        case 3: *reinterpret_cast<bool*>(_v) = _t->playing(); break;
        case 4: *reinterpret_cast<double*>(_v) = _t->rate(); break;
        case 5: *reinterpret_cast<int*>(_v) = _t->volume(); break;
        case 6: *reinterpret_cast<bool*>(_v) = _t->muted(); break;
        case 7: *reinterpret_cast<QString*>(_v) = _t->repeatMode(); break;
        case 8: *reinterpret_cast<QString*>(_v) = _t->repeatModeLabel(); break;
        case 9: *reinterpret_cast<double*>(_v) = _t->positionMs(); break;
        case 10: *reinterpret_cast<double*>(_v) = _t->durationMs(); break;
        case 11: *reinterpret_cast<QString*>(_v) = _t->positionText(); break;
        case 12: *reinterpret_cast<QString*>(_v) = _t->durationText(); break;
        case 13: *reinterpret_cast<QObject**>(_v) = _t->frameBridge(); break;
        case 14: *reinterpret_cast<bool*>(_v) = _t->fullscreen(); break;
        case 15: *reinterpret_cast<bool*>(_v) = _t->miniMode(); break;
        case 16: *reinterpret_cast<bool*>(_v) = _t->keepAbove(); break;
        case 17: *reinterpret_cast<bool*>(_v) = _t->sidebarVisible(); break;
        case 18: *reinterpret_cast<int*>(_v) = _t->sidebarWidth(); break;
        case 19: *reinterpret_cast<int*>(_v) = _t->windowWidth(); break;
        case 20: *reinterpret_cast<int*>(_v) = _t->windowHeight(); break;
        case 21: *reinterpret_cast<bool*>(_v) = _t->windowMaximized(); break;
        case 22: *reinterpret_cast<bool*>(_v) = _t->kiosk(); break;
        case 23: *reinterpret_cast<QString*>(_v) = _t->uiMode(); break;
        case 24: *reinterpret_cast<bool*>(_v) = _t->controlsVisible(); break;
        case 25: *reinterpret_cast<bool*>(_v) = _t->cursorHidden(); break;
        case 26: *reinterpret_cast<QString*>(_v) = _t->osdText(); break;
        case 27: *reinterpret_cast<bool*>(_v) = _t->hudVisible(); break;
        case 28: *reinterpret_cast<QString*>(_v) = _t->hudText(); break;
        case 29: *reinterpret_cast<QString*>(_v) = _t->rotation(); break;
        case 30: *reinterpret_cast<QString*>(_v) = _t->hdrMode(); break;
        case 31: *reinterpret_cast<bool*>(_v) = _t->hdrMatrixFix(); break;
        case 32: *reinterpret_cast<QVariantMap*>(_v) = _t->settingsMap(); break;
        case 33: *reinterpret_cast<double*>(_v) = _t->abA(); break;
        case 34: *reinterpret_cast<double*>(_v) = _t->abB(); break;
        case 35: *reinterpret_cast<bool*>(_v) = _t->abActive(); break;
        case 36: *reinterpret_cast<QString*>(_v) = _t->abLabel(); break;
        case 37: *reinterpret_cast<QVariantList*>(_v) = _t->timelineMarks(); break;
        case 38: *reinterpret_cast<QVariantList*>(_v) = _t->resumeCards(); break;
        case 39: *reinterpret_cast<QVariantMap*>(_v) = _t->autoplay(); break;
        case 40: *reinterpret_cast<int*>(_v) = _t->sleepMinutes(); break;
        case 41: *reinterpret_cast<QString*>(_v) = _t->sleepMenuLabel(); break;
        case 42: *reinterpret_cast<bool*>(_v) = _t->nightMode(); break;
        case 43: *reinterpret_cast<QString*>(_v) = _t->loudnessMenuLabel(); break;
        case 44: *reinterpret_cast<QString*>(_v) = _t->eqPresetName(); break;
        case 45: *reinterpret_cast<QString*>(_v) = _t->subtitleButtonText(); break;
        case 46: *reinterpret_cast<QString*>(_v) = _t->chaptersTitle(); break;
        case 47: *reinterpret_cast<QString*>(_v) = _t->chaptersEmptyText(); break;
        case 48: *reinterpret_cast<QString*>(_v) = _t->sceneAnalysisLabel(); break;
        case 49: *reinterpret_cast<bool*>(_v) = _t->sceneAnalysisAvailable(); break;
        case 50: *reinterpret_cast<bool*>(_v) = _t->youtubeLoading(); break;
        case 51: *reinterpret_cast<QVariantMap*>(_v) = _t->youtubeState(); break;
        case 52: *reinterpret_cast<jvp::PlaylistModel**>(_v) = _t->playlistObjectTyped(); break;
        case 53: *reinterpret_cast<jvp::SubtitleController**>(_v) = _t->subtitlesObjectTyped(); break;
        case 54: *reinterpret_cast<jvp::AiController**>(_v) = _t->aiObjectTyped(); break;
        case 55: *reinterpret_cast<jvp::TranslationController**>(_v) = _t->translationObjectTyped(); break;
        case 56: *reinterpret_cast<jvp::OnlineSubsController**>(_v) = _t->onlineSubsObjectTyped(); break;
        case 57: *reinterpret_cast<QObject**>(_v) = _t->networkObject(); break;
        case 58: *reinterpret_cast<jvp::RemoteInfo**>(_v) = _t->remoteObjectTyped(); break;
        default: break;
        }
    }
    if (_c == QMetaObject::WriteProperty) {
        void *_v = _a[0];
        switch (_id) {
        case 17: _t->setSidebarVisible(*reinterpret_cast<bool*>(_v)); break;
        case 18: _t->setSidebarWidth(*reinterpret_cast<int*>(_v)); break;
        case 19: _t->setWindowWidth(*reinterpret_cast<int*>(_v)); break;
        case 20: _t->setWindowHeight(*reinterpret_cast<int*>(_v)); break;
        default: break;
        }
    }
}

const QMetaObject *jvp::AppController::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *jvp::AppController::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_staticMetaObjectStaticContent<qt_meta_tag_ZN3jvp13AppControllerE_t>.strings))
        return static_cast<void*>(this);
    if (!strcmp(_clname, "RemoteBackend"))
        return static_cast< RemoteBackend*>(this);
    if (!strcmp(_clname, "MprisBackend"))
        return static_cast< MprisBackend*>(this);
    return QObject::qt_metacast(_clname);
}

int jvp::AppController::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QObject::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 121)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 121;
    }
    if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 121)
            *reinterpret_cast<QMetaType *>(_a[0]) = QMetaType();
        _id -= 121;
    }
    if (_c == QMetaObject::ReadProperty || _c == QMetaObject::WriteProperty
            || _c == QMetaObject::ResetProperty || _c == QMetaObject::BindableProperty
            || _c == QMetaObject::RegisterPropertyMetaType) {
        qt_static_metacall(this, _c, _id, _a);
        _id -= 59;
    }
    return _id;
}

// SIGNAL 0
void jvp::AppController::mediaChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 0, nullptr);
}

// SIGNAL 1
void jvp::AppController::playbackChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 1, nullptr);
}

// SIGNAL 2
void jvp::AppController::positionChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 2, nullptr);
}

// SIGNAL 3
void jvp::AppController::fullscreenChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 3, nullptr);
}

// SIGNAL 4
void jvp::AppController::miniModeChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 4, nullptr);
}

// SIGNAL 5
void jvp::AppController::viewChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 5, nullptr);
}

// SIGNAL 6
void jvp::AppController::hudChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 6, nullptr);
}

// SIGNAL 7
void jvp::AppController::settingsChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 7, nullptr);
}

// SIGNAL 8
void jvp::AppController::marksChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 8, nullptr);
}

// SIGNAL 9
void jvp::AppController::resumeCardsChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 9, nullptr);
}

// SIGNAL 10
void jvp::AppController::autoplayChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 10, nullptr);
}

// SIGNAL 11
void jvp::AppController::stateChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 11, nullptr);
}

// SIGNAL 12
void jvp::AppController::subtitlesChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 12, nullptr);
}

// SIGNAL 13
void jvp::AppController::chaptersChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 13, nullptr);
}

// SIGNAL 14
void jvp::AppController::youtubeChanged()
{
    QMetaObject::activate(this, &staticMetaObject, 14, nullptr);
}

// SIGNAL 15
void jvp::AppController::osdShown(int _t1)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 15, nullptr, _t1);
}

// SIGNAL 16
void jvp::AppController::quitRequested()
{
    QMetaObject::activate(this, &staticMetaObject, 16, nullptr);
}

// SIGNAL 17
void jvp::AppController::dialogRequested(const QString & _t1, const QVariant & _t2)
{
    QMetaObject::activate<void>(this, &staticMetaObject, 17, nullptr, _t1, _t2);
}

// SIGNAL 18
void jvp::AppController::dialogueIndexReady()
{
    QMetaObject::activate(this, &staticMetaObject, 18, nullptr);
}
QT_WARNING_POP
