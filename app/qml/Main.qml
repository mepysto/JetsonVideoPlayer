import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// 주 창. 데스크톱(창) 레이아웃과 TV(10-foot) 레이아웃이 같은 컨트롤러(App)를 씁니다.
ApplicationWindow {
    id: win
    width: App.windowWidth
    height: App.windowHeight
    minimumWidth: App.miniMode ? 160 : 480
    minimumHeight: App.miniMode ? 90 : 320
    visible: true
    color: Theme.bg
    title: App.title.length ? App.title + " — Jetson Video Player" : "Jetson Video Player"
    flags: App.miniMode ? (Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
         : App.keepAbove ? (Qt.Window | Qt.WindowStaysOnTopHint) : Qt.Window

    // 기본(Basic) 컨트롤(메뉴, 콤보박스, 대화상자)을 어두운 테마로
    palette.window: Theme.panel
    palette.windowText: Theme.text
    palette.base: Theme.field
    palette.alternateBase: Theme.sidebar
    palette.text: Theme.textSoft
    palette.button: "#1c222e"
    palette.buttonText: Theme.textSoft
    palette.highlight: Theme.accent
    palette.highlightedText: "#111318"
    palette.light: "#2a3240"
    palette.mid: "#303744"
    palette.dark: "#11151d"
    palette.toolTipBase: Theme.panel
    palette.toolTipText: Theme.text
    palette.placeholderText: Theme.muted

    readonly property bool tvMode: App.uiMode === "tv"
    readonly property bool videoOnly: App.fullscreen || App.miniMode

    Component.onCompleted: {
        Theme.scale = tvMode ? 1.6 : 1.0
        Theme.tv = tvMode
        if (App.windowMaximized && !App.kiosk)
            win.showMaximized()
        if (App.kiosk)
            win.showFullScreen()
    }
    onTvModeChanged: { Theme.scale = tvMode ? 1.6 : 1.0; Theme.tv = tvMode }

    // 전체화면 / 미니 / 일반 창 전환은 컨트롤러 상태를 따라갑니다.
    Connections {
        target: App
        function onFullscreenChanged() {
            if (App.fullscreen) win.showFullScreen()
            else if (!App.kiosk) win.showNormal()
        }
        function onMiniModeChanged() {
            if (App.miniMode) {
                App.rememberWindowGeometry(win.x, win.y, win.width, win.height, win.visibility === Window.Maximized)
                win.showNormal()
                const g = App.miniGeometry(Screen.desktopAvailableWidth, Screen.desktopAvailableHeight)
                win.width = g.width; win.height = g.height; win.x = g.x; win.y = g.y
            } else {
                const r = App.restoreGeometry()
                win.width = r.width; win.height = r.height; win.x = r.x; win.y = r.y
                if (r.maximized) win.showMaximized()
            }
        }
        function onQuitRequested() { win.close() }
        function onDialogRequested(name, arg) { dialogs.open(name, arg) }
    }
    onClosing: App.shutdown(win.width, win.height, win.visibility === Window.Maximized)
    onWidthChanged: if (!videoOnly && visibility !== Window.Maximized) App.windowWidth = width
    onHeightChanged: if (!videoOnly && visibility !== Window.Maximized) App.windowHeight = height

    Loader {
        anchors.fill: parent
        sourceComponent: tvMode ? tvLayout : desktopLayout
        focus: true
    }
    Component { id: desktopLayout; DesktopLayout { } }
    Component { id: tvLayout; TvLayout { } }

    Dialogs { id: dialogs }

    // 전역 단축키: 입력칸에 글자를 넣는 중이 아니면 단축키 표(Shortcuts)로 처리
    Shortcut { sequences: ["Ctrl+Q"]; onActivated: App.quit() }
}
