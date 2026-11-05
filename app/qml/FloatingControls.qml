import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 전체화면에서 마우스를 움직이면 나타나는 컨트롤
Rectangle {
    id: bar
    // 포인터가 바 위에 있거나 메뉴가 열려 있는 동안은 숨기지 않습니다 (바가 숨으면 메뉴도 함께 사라집니다)
    readonly property bool keepVisible: hover.hovered || speedPopup.opened || subPopup.opened
    onKeepVisibleChanged: App.setControlsHovered(keepVisible)
    implicitHeight: col.implicitHeight + Theme.px(16)
    radius: 12; color: Qt.rgba(17 / 255, 21 / 255, 29 / 255, 0.92); border.color: "#303744"
    HoverHandler { id: hover }
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
            JIconButton { text: "⏮"; enabled: App.playlist.count > 1; onClicked: App.playPrevious() }
            JButton { text: "↶ 10"; onClicked: App.seekRelative(-10) }
            JButton { primary: true; text: App.playing ? "⏸" : "▶"; implicitWidth: Theme.px(36); implicitHeight: Theme.px(36); onClicked: App.togglePlayPause() }
            JButton { text: "10 ↷"; onClicked: App.seekRelative(10) }
            JIconButton { text: "⏭"; enabled: App.playlist.count > 1; onClicked: App.playNext() }
            JButton {
                text: "⚡ " + App.rate.toFixed(2) + "x"; fg: Theme.accent
                onClicked: speedPopup.open()
                SpeedPopup { id: speedPopup; y: -height - 6 }
            }
            Item { Layout.fillWidth: true }
            JIconButton { text: App.muted ? "🔇" : "🔊"; onClicked: App.toggleMute() }
            JSlider { Layout.preferredWidth: Theme.px(110); from: 0; to: 200; value: App.volume; onMoved: App.setVolume(value) }
            JButton { text: "🔖 북마크"; onClicked: App.addBookmark() }
            JButton {
                id: subBtn
                text: App.subtitleButtonText
                onClicked: subPopup.open()
                SubtitlePopup { id: subPopup; y: -height - 6; x: -width + subBtn.width }
            }
            JButton { text: "📸 캡처"; onClicked: App.captureScreenshot() }
            JIconButton { text: "⧉"; onClicked: App.toggleFullscreen() }
        }
    }
}
