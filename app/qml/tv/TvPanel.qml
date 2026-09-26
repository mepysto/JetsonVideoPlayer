import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// TV 영상 조작 패널: 큰 진행바와 버튼. ←/→로 버튼 이동, OK로 실행, Back으로 닫기.
FocusScope {
    id: panel
    signal closeRequested()
    implicitHeight: col.implicitHeight + Theme.px(40)
    Rectangle { anchors.fill: parent; gradient: Gradient { GradientStop { position: 0; color: "transparent" } GradientStop { position: 0.4; color: "#e6000000" } } }
    Keys.onEscapePressed: panel.closeRequested()
    Keys.onBackPressed: panel.closeRequested()
    Timer { interval: 8000; running: panel.visible; onTriggered: panel.closeRequested(); repeat: false; id: autoHide }
    Keys.onPressed: autoHide.restart()

    ColumnLayout {
        id: col
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: Theme.px(32)
        spacing: Theme.px(12)
        Text { text: App.title; color: "#ffffff"; font.pixelSize: Theme.px(18); font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
        RowLayout {
            spacing: Theme.px(12)
            Text { text: App.positionText; color: Theme.textSoft; font.pixelSize: Theme.px(14); font.family: Theme.mono }
            SeekBar { Layout.fillWidth: true }
            Text { text: App.durationText; color: Theme.textSoft; font.pixelSize: Theme.px(14); font.family: Theme.mono }
        }
        Row {
            id: buttons
            spacing: Theme.px(10)
            Repeater {
                id: rep
                model: [
                    { t: "⏮", a: () => App.playPrevious() }, { t: "↶ 30", a: () => App.seekRelative(-30) },
                    { t: "⏯", a: () => App.togglePlayPause() }, { t: "30 ↷", a: () => App.seekRelative(30) },
                    { t: "⏭", a: () => App.playNext() }, { t: "💬 자막", a: () => App.toggleSubtitles() },
                    { t: "⚡ 속도", a: () => App.stepRate(0.25) }, { t: "📑 챕터", a: () => dialogs.open("chapters") },
                    { t: "🔎 대사", a: () => dialogs.open("search") }, { t: "⚙️ 설정", a: () => App.requestDialog("tvMenu", "") }
                ]
                JButton {
                    required property var modelData
                    required property int index
                    text: modelData.t
                    font.pixelSize: Theme.px(16)
                    focus: index === 2
                    KeyNavigation.left: index > 0 ? rep.itemAt(index - 1) : null
                    KeyNavigation.right: index < rep.count - 1 ? rep.itemAt(index + 1) : null
                    onClicked: modelData.a()
                    Keys.onReturnPressed: modelData.a()
                }
            }
        }
    }
}
