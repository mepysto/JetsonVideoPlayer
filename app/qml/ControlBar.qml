import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 하단 컨트롤: 진행바 + 재생 버튼 + 속도 + 볼륨 + 자막 + 전체화면
Rectangle {
    id: bar
    signal done()
    implicitHeight: col.implicitHeight + Theme.px(12)
    color: Theme.bar
    Rectangle { width: parent.width; height: 1; color: Theme.border }

    ColumnLayout {
        id: col
        anchors.fill: parent
        anchors.margins: Theme.px(6)
        spacing: Theme.px(2)
        RowLayout {
            spacing: Theme.px(10)
            Text { text: App.positionText; color: Theme.muted; font.pixelSize: Theme.px(12); font.family: Theme.mono }
            SeekBar { Layout.fillWidth: true; enabled: App.hasVideo }
            Text {
                text: App.durationText; color: Theme.muted; font.pixelSize: Theme.px(12); font.family: Theme.mono
                MouseArea { anchors.fill: parent; onClicked: App.toggleRemainingTime() }
            }
        }
        RowLayout {
            spacing: Theme.px(4)
            JIconButton { text: "⏮"; enabled: App.playlist.count > 1; ToolTip.text: "이전 영상 (P)"; onClicked: App.playPrevious() }
            JButton { text: "↶ 10"; enabled: App.hasVideo; ToolTip.text: "10초 뒤로 (←)"; onClicked: App.seekRelative(-10) }
            JButton {
                primary: true; text: App.playing ? "⏸" : "▶"
                enabled: App.hasVideo
                ToolTip.text: (App.playing ? "일시정지" : "재생") + " (Space)"
                implicitWidth: Theme.px(40); implicitHeight: Theme.px(40)
                font.pixelSize: Theme.px(16)
                onClicked: App.togglePlayPause()
            }
            JButton { text: "10 ↷"; enabled: App.hasVideo; ToolTip.text: "10초 앞으로 (→)"; onClicked: App.seekRelative(10) }
            JIconButton { text: "⏭"; enabled: App.playlist.count > 1; ToolTip.text: "다음 영상 (N)"; onClicked: App.playNext() }
            JIconButton { text: "‹"; enabled: App.hasVideo; ToolTip.text: "한 프레임 뒤로 (Ctrl+←)"; onClicked: App.frameStep(-1) }
            JButton {
                id: speedBtn
                text: "⚡ " + App.rate.toFixed(App.rate % 0.25 === 0 && App.rate % 0.5 !== 0 ? 2 : 1) + "x"
                enabled: App.hasVideo
                fg: Theme.accent; font.bold: true
                ToolTip.text: "재생 속도 (↑/↓, R: 1.0x)"
                onClicked: speedPopup.open()
                SpeedPopup { id: speedPopup; y: -height - 6 }
            }
            JIconButton { text: "›"; enabled: App.hasVideo; ToolTip.text: "한 프레임 앞으로 (Ctrl+→)"; onClicked: App.frameStep(1) }
            Item { Layout.fillWidth: true }
            JIconButton { text: App.muted || App.volume === 0 ? "🔇" : "🔊"; ToolTip.text: "음소거 (M)"; onClicked: App.toggleMute() }
            JSlider {
                Layout.preferredWidth: Theme.px(110)
                from: 0; to: 200; stepSize: 1
                value: App.volume
                fill: App.volume > 100 ? "#ff9800" : Theme.accent
                onMoved: App.setVolume(value)
                ToolTip.visible: hovered; ToolTip.text: Math.round(value) + "%"
            }
            JButton {
                id: subBtn
                text: App.subtitleButtonText
                enabled: App.hasVideo
                ToolTip.text: "자막 선택·크기·싱크 (C)"
                onClicked: subPopup.open()
                SubtitlePopup { id: subPopup; y: -height - 6; x: -width + subBtn.width }
            }
            JIconButton { text: App.fullscreen ? "⧉" : "⛶"; ToolTip.text: "전체화면 (F)"; onClicked: App.toggleFullscreen() }
        }
    }
}
