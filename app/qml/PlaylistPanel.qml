import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 재생목록: 폴더 트리(접기/펼치기), 검색, 정렬, 진행률·시청 완료·대기열 표시, 우클릭 메뉴
Rectangle {
    id: panel
    signal done()
    color: Theme.sidebar
    Rectangle { width: 1; height: parent.height; color: Theme.border }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.px(10)
        spacing: Theme.px(8)
        RowLayout {
            Text { text: "재생목록"; color: "#ffffff"; font.pixelSize: Theme.px(15); font.bold: true; Layout.fillWidth: true }
            Text { text: App.playlist.count + "개"; color: Theme.muted; font.pixelSize: Theme.px(12) }
            JButton { tool: true; text: "↕ " + App.playlist.sortLabel; ToolTip.text: "정렬: 이름 / 최근 수정 / 크기"; onClicked: App.playlist.cycleSort() }
        }
        JField {
            id: search
            Layout.fillWidth: true
            placeholderText: "🔍 영상 검색..."
            onTextChanged: App.playlist.filter = text
            onAccepted: { App.playlist.playFirstMatch(); panel.done() }
            Keys.onEscapePressed: { if (text.length) text = ""; else panel.done() }
        }
        RowLayout {
            spacing: 4
            JButton { tool: true; text: "전체 펼치기"; onClicked: App.playlist.expandAll() }
            JButton { tool: true; text: "전체 접기"; onClicked: App.playlist.collapseAll() }
            Item { Layout.fillWidth: true }
            JButton { tool: true; text: "🔄"; ToolTip.text: "새로고침 (F5)"; onClicked: App.rescanPlaylist() }
            JButton { tool: true; text: "📂 위치"; ToolTip.text: "지금 영상 위치 열기"; onClicked: App.openCurrentLocation() }
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: App.playlist
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { }
            currentIndex: App.playlist.activeRow
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            delegate: Rectangle {
                id: row
                required property int index
                required property int depth
                required property bool isFolder
                required property bool expanded
                required property string title
                required property string path
                required property int playlistIndex
                required property bool active
                required property bool watched
                required property real progress
                required property int queuePosition
                required property bool missing
                required property int childCount
                width: ListView.view.width
                height: Theme.px(isFolder ? 30 : 34)
                radius: 8
                color: active ? Theme.rowActive : rowMouse.containsMouse ? "#1a1f29" : "transparent"
                Rectangle { visible: active; width: 3; height: parent.height; color: Theme.accent }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.px(6) + depth * Theme.px(14)
                    anchors.rightMargin: Theme.px(6)
                    spacing: Theme.px(6)
                    Text {
                        text: isFolder ? (expanded ? "▼" : "▶") : active ? "▶" : watched ? "✓" : "🎬"
                        color: active ? Theme.accent : isFolder ? Theme.muted : watched ? "#34d399" : Theme.textSoft
                        font.pixelSize: Theme.px(isFolder ? 10 : 12)
                    }
                    Text {
                        Layout.fillWidth: true
                        text: isFolder ? title + "  (" + childCount + ")" : title
                        color: missing ? Theme.muted : active ? Theme.accent : isFolder ? "#cbd5e1" : Theme.textSoft
                        font.pixelSize: Theme.px(13)
                        font.bold: active || isFolder
                        font.strikeout: missing
                        elide: Text.ElideMiddle
                    }
                    Text {
                        visible: queuePosition > 0
                        text: "⏭" + queuePosition
                        color: Theme.accent; font.pixelSize: Theme.px(11)
                    }
                    Rectangle {
                        visible: !isFolder && progress > 0 && progress < 1
                        Layout.preferredWidth: Theme.px(36); Layout.preferredHeight: 4; radius: 2; color: "#303744"
                        Rectangle { width: parent.width * progress; height: 4; radius: 2; color: Theme.accent }
                    }
                }
                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: (m) => {
                        if (m.button === Qt.RightButton) { rowMenu.row = row; rowMenu.popup(); return }
                        if (isFolder) App.playlist.toggleExpanded(index)
                        else if (!active) { App.playIndex(playlistIndex); panel.done() }
                    }
                }
                ToolTip.visible: rowMouse.containsMouse && !isFolder
                ToolTip.delay: 800
                ToolTip.text: path
            }
        }
    }

    JMenu {
        id: rowMenu
        property var row: null
        MenuItem { text: "▶️ 지금 재생"; enabled: rowMenu.row && !rowMenu.row.isFolder; onTriggered: App.playIndex(rowMenu.row.playlistIndex) }
        MenuItem {
            text: rowMenu.row && rowMenu.row.queuePosition > 0 ? "✕ 대기열에서 제거" : "⏭ 다음에 재생 (대기열 추가)"
            enabled: rowMenu.row && !rowMenu.row.isFolder
            onTriggered: rowMenu.row.queuePosition > 0 ? App.unqueue(rowMenu.row.path) : App.queueNext(rowMenu.row.path)
        }
        MenuSeparator {}
        MenuItem { text: "📂 파일 위치 열기 (파일 브라우저)"; onTriggered: App.openLocation(rowMenu.row.path) }
        MenuItem { text: "📋 전체 경로 복사"; onTriggered: App.copyText(rowMenu.row.path, "📋 파일 경로가 복사되었습니다!") }
        MenuItem { text: "📋 파일 이름 복사"; onTriggered: App.copyText(rowMenu.row.title, "📋 파일 이름이 복사되었습니다!") }
        MenuSeparator {}
        MenuItem { text: "🔄 재생목록 새로고침 (F5)"; onTriggered: App.rescanPlaylist() }
        MenuItem { text: "💾 재생목록 저장 (M3U)"; onTriggered: App.requestDialog("saveM3u") }
    }
}
