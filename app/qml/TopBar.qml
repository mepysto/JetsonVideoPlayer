import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: bar
    implicitHeight: Theme.px(40)
    color: Theme.bar
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }

    component Sep: Rectangle { width: 1; Layout.fillHeight: true; Layout.margins: 6; color: Theme.border }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 6
        spacing: 4
        Text {
            text: "JETSON VIDEO PLAYER"
            color: "#ffffff"
            font.pixelSize: Theme.px(15)
            font.bold: true
            font.letterSpacing: 1
        }
        Sep {}
        JButton { text: "📂 파일"; ToolTip.text: "동영상 파일 열기 (Ctrl+O)"; onClicked: dialogs.open("openFile") }
        JButton { text: "📁 폴더"; ToolTip.text: "동영상 폴더 열기 (Ctrl+Shift+O)"; onClicked: dialogs.open("openFolder") }
        JButton { id: recentBtn; text: "🕒 최근"; ToolTip.text: "최근 재생한 영상/폴더"; onClicked: historyPopup.open() }
        JButton { id: ytBtn; text: "▶️ 유튜브"; ToolTip.text: "유튜브 영상 받아서 재생"; onClicked: ytPopup.open() }
        Sep {}
        JButton {
            text: ({ "all": "🔁", "one": "🔂", "none": "➡️", "shuffle": "🔀" })[App.repeatMode] || "🔁"
            ToolTip.text: "재생 모드: " + App.repeatModeLabel + " (Shift+R)"
            onClicked: App.cycleRepeatMode()
        }
        Sep {}
        Text {
            Layout.fillWidth: true
            text: App.nowPlayingText
            color: Theme.textSoft
            font.pixelSize: Theme.px(13)
            elide: Text.ElideMiddle
        }
        JButton { text: "✕"; ToolTip.text: "종료 (Q / Esc)"; onClicked: App.quit() }
        JButton { id: moreBtn; text: "⋯"; ToolTip.text: "더 보기: 북마크, 캡처, 리모컨, HUD, AI 자막, 화면·소리 설정, 도움말"; onClicked: moreMenu.popup(moreBtn, 0, moreBtn.height) }
        JButton { text: "☷  재생목록"; ToolTip.text: "재생목록 열기/닫기"; onClicked: App.sidebarVisible = !App.sidebarVisible }
    }

    HistoryPopup { id: historyPopup; parent: recentBtn; y: recentBtn.height + 4 }
    YouTubePopup { id: ytPopup; parent: ytBtn; y: ytBtn.height + 4 }
    MoreMenu { id: moreMenu }
}
