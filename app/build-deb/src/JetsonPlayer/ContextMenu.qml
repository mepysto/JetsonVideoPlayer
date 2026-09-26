import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 영상 우클릭 빠른 조작 메뉴
Menu {
    MenuItem { text: App.playing ? "⏸ 일시정지 (Space)" : "▶ 재생 (Space)"; onTriggered: App.togglePlayPause() }
    MenuItem { text: "⏮ 이전 영상 (P)"; onTriggered: App.playPrevious() }
    MenuItem { text: "⏭ 다음 영상 (N)"; onTriggered: App.playNext() }
    Menu {
        title: "⚡ 재생 속도 (" + App.rate.toFixed(2) + "x)"
        Repeater {
            model: [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
            MenuItem { required property var modelData; text: modelData + "x"; checkable: true; checked: Math.abs(App.rate - modelData) < 0.01; onTriggered: App.setRate(modelData) }
        }
    }
    MenuItem { text: App.subtitleButtonText + "  —  켜기/끄기 (S)"; onTriggered: App.toggleSubtitles() }
    MenuItem { text: "재생 모드: " + App.repeatModeLabel + " (Shift+R)"; onTriggered: App.cycleRepeatMode() }
    MenuItem { text: "🔖 북마크 추가 (B)"; onTriggered: App.addBookmark() }
    MenuItem { text: "📸 스크린샷 (Ctrl+S)"; onTriggered: App.captureScreenshot() }
    MenuSeparator {}
    MenuItem { text: "📱 스마트폰 웹 리모컨 안내..."; onTriggered: App.requestDialog("remote", "") }
    MenuItem { text: "📌 항상 위에 표시 (T)"; checkable: true; checked: App.keepAbove; onTriggered: App.toggleKeepAbove() }
    MenuItem { text: App.fullscreen ? "⧉ 창 모드 (F)" : "⛶ 전체화면 (F)"; onTriggered: App.toggleFullscreen() }
    MenuItem { text: "ℹ️ 미디어 정보 (I)"; checkable: true; checked: App.hudVisible; onTriggered: App.toggleHud() }
    MenuItem { text: "❓ 단축키 안내 (F1)"; onTriggered: App.requestDialog("help", "") }
}
