import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 전체화면에서 마우스를 움직이면 나타나는 컨트롤
Rectangle {
    implicitHeight: col.implicitHeight + Theme.px(16)
    radius: 12; color: Qt.rgba(17 / 255, 21 / 255, 29 / 255, 0.92); border.color: "#303744"
    HoverHandler { onHoveredChanged: App.setControlsHovered(hovered) }
    ColumnLayout {
        id: col
        anchors.fill: parent; anchors.margins: Theme.px(8)
        RowLayout {
            spacing: Theme.px(10)
            Text { text: App.positionText; color: Theme.muted; font.pixelSize: Theme.px(12); font.family: Theme.mono }
            SeekBar { Layout.fillWidth: true }
            Text { text: App.durationText; color: Theme.muted; font.pixelSize: Theme.px(12); font.family: Theme.mono }
        }
        RowLayout {
            JIconButton { text: "⏮"; onClicked: App.playPrevious() }
            JButton { text: "↶ 10"; onClicked: App.seekRelative(-10) }
            JButton { primary: true; text: App.playing ? "⏸" : "▶"; implicitWidth: Theme.px(36); implicitHeight: Theme.px(36); onClicked: App.togglePlayPause() }
            JButton { text: "10 ↷"; onClicked: App.seekRelative(10) }
            JIconButton { text: "⏭"; onClicked: App.playNext() }
            JButton { text: "⚡ " + App.rate.toFixed(2) + "x"; fg: Theme.accent; onClicked: App.resetRate() }
            Item { Layout.fillWidth: true }
            JIconButton { text: App.muted ? "🔇" : "🔊"; onClicked: App.toggleMute() }
            JSlider { Layout.preferredWidth: Theme.px(110); from: 0; to: 200; value: App.volume; onMoved: App.setVolume(value) }
            JButton { text: "🔖 북마크"; onClicked: App.addBookmark() }
            JButton { text: App.subtitleButtonText; onClicked: App.toggleSubtitles() }
            JButton { text: "📸 캡처"; onClicked: App.captureScreenshot() }
            JIconButton { text: "⧉"; onClicked: App.toggleFullscreen() }
        }
    }
}
