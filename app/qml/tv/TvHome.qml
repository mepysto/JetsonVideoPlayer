import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// TV 홈: 큰 타일 — 이어보기 / 재생목록 / 열기
FocusScope {
    id: home
    signal chosen()
    Rectangle { anchors.fill: parent; color: Theme.bg; opacity: App.hasVideo ? 0.92 : 1.0 }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.px(40)
        spacing: Theme.px(24)
        Text { text: "JETSON VIDEO PLAYER"; color: "#ffffff"; font.pixelSize: Theme.px(22); font.bold: true; font.letterSpacing: 2 }

        Text { visible: resume.count > 0; text: "⏱️ 이어보기"; color: Theme.accent; font.pixelSize: Theme.px(15); font.bold: true }
        ListView {
            id: resume
            visible: count > 0
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.px(150)
            orientation: ListView.Horizontal
            spacing: Theme.px(16)
            model: App.resumeCards
            focus: count > 0
            keyNavigationEnabled: true
            KeyNavigation.down: actions
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: Theme.px(300); height: Theme.px(140); radius: 12
                color: "#141a24"
                border.color: ListView.isCurrentItem && resume.activeFocus ? Theme.accent : "#232c3d"
                border.width: ListView.isCurrentItem && resume.activeFocus ? 3 : 1
                Column {
                    anchors.fill: parent; anchors.margins: Theme.px(12); spacing: Theme.px(8)
                    Text { width: parent.width; text: modelData.title; color: Theme.text; font.pixelSize: Theme.px(14); font.bold: true; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
                    Rectangle { width: parent.width; height: 6; radius: 3; color: "#303744"
                        Rectangle { width: parent.width * modelData.fraction; height: 6; radius: 3; color: Theme.accent } }
                    Text { text: modelData.meta; color: Theme.muted; font.pixelSize: Theme.px(11) }
                }
                MouseArea { anchors.fill: parent; onClicked: home.open(modelData.path) }
                Keys.onReturnPressed: home.open(modelData.path)
            }
        }

        Row {
            id: actions
            spacing: Theme.px(16)
            focus: resume.count === 0
            KeyNavigation.up: resume
            KeyNavigation.down: list
            JButton { id: a1; text: "📁 폴더 열기"; focus: true; KeyNavigation.right: a2; onClicked: dialogs.open("openFolder"); Keys.onReturnPressed: clicked() }
            JButton { id: a2; text: "🌐 네트워크 폴더"; KeyNavigation.right: a3; onClicked: dialogs.open("network"); Keys.onReturnPressed: clicked() }
            JButton { id: a3; text: "▶️ 유튜브"; KeyNavigation.right: a4; onClicked: dialogs.open("youtube"); Keys.onReturnPressed: clicked() }
            JButton { id: a4; text: "📱 리모컨 연결"; onClicked: dialogs.open("remote"); Keys.onReturnPressed: clicked() }
        }

        Text { visible: list.count > 0; text: "📂 재생목록 (" + App.playlist.count + ")"; color: Theme.accent; font.pixelSize: Theme.px(15); font.bold: true }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: App.playlist
            keyNavigationEnabled: true
            KeyNavigation.up: actions
            highlight: Rectangle { color: Theme.rowActive; radius: 8; border.color: Theme.accent; border.width: list.activeFocus ? 2 : 0 }
            highlightMoveDuration: 80
            delegate: Item {
                id: row
                required property int index
                required property int depth
                required property bool isFolder
                required property bool expanded
                required property string title
                required property int playlistIndex
                required property bool active
                required property bool watched
                width: ListView.view.width; height: Theme.px(isFolder ? 36 : 42)
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    x: Theme.px(12) + depth * Theme.px(20)
                    width: parent.width - x - 12
                    elide: Text.ElideMiddle
                    text: (isFolder ? (expanded ? "▼ " : "▶ ") : active ? "▶ " : watched ? "✓ " : "") + title
                    color: active ? Theme.accent : isFolder ? "#cbd5e1" : Theme.textSoft
                    font.pixelSize: Theme.px(14); font.bold: isFolder || active
                }
                MouseArea { anchors.fill: parent; onClicked: row.activate() }
                Keys.onReturnPressed: row.activate()
                function activate() {
                    if (isFolder) App.playlist.toggleExpanded(index)
                    else { App.playIndex(playlistIndex); home.chosen() }
                }
            }
        }
    }
    function open(path) { App.openPath(path); home.chosen() }
}
