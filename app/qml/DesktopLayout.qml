import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 데스크톱 레이아웃: 상단바 / (영상 | 재생목록) / 하단 컨트롤
FocusScope {
    id: root
    focus: true
    readonly property bool videoOnly: App.fullscreen || App.miniMode

    Keys.onPressed: (event) => { event.accepted = App.handleKey(event.key, event.modifiers, event.text) }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TopBar {
            Layout.fillWidth: true
            visible: !root.videoOnly
        }

        SplitView {
            id: split
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: Rectangle {
                implicitWidth: 4
                color: SplitHandle.hovered || SplitHandle.pressed ? Theme.accent : Theme.border
            }
            VideoArea {
                id: videoArea
                SplitView.fillWidth: true
                SplitView.minimumWidth: 160
                onRequestFocus: root.forceActiveFocus()
            }
            PlaylistPanel {
                id: playlist
                visible: App.sidebarVisible && !root.videoOnly
                SplitView.preferredWidth: App.sidebarWidth
                SplitView.minimumWidth: 200
                // 사용자가 손잡이를 끌 때만 저장 (처음 배치 때의 임시 너비가 저장되지 않게)
                onWidthChanged: if (split.resizing && visible && width > 0) App.sidebarWidth = width
                onDone: root.forceActiveFocus()
            }
        }

        ControlBar {
            Layout.fillWidth: true
            visible: !root.videoOnly
            onDone: root.forceActiveFocus()
        }
    }
}
