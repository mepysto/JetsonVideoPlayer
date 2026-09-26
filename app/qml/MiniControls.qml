import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 미니 플레이어 아래쪽 작은 컨트롤
Rectangle {
    width: row.implicitWidth + Theme.px(16); height: row.implicitHeight + Theme.px(4)
    radius: 12; color: Qt.rgba(17 / 255, 21 / 255, 29 / 255, 0.92); border.color: "#303744"
    HoverHandler { onHoveredChanged: App.setControlsHovered(hovered) }
    Row {
        id: row
        anchors.centerIn: parent
        JIconButton { text: "⏮"; ToolTip.text: "이전 영상"; onClicked: App.playPrevious() }
        JIconButton { text: App.playing ? "⏸" : "▶"; ToolTip.text: "재생 / 일시정지"; onClicked: App.togglePlayPause() }
        JIconButton { text: "⏭"; ToolTip.text: "다음 영상"; onClicked: App.playNext() }
        JIconButton { text: "🗖"; ToolTip.text: "원래 창으로 (W)"; onClicked: App.toggleMiniPlayer() }
    }
}
