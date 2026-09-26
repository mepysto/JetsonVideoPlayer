import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 챕터·장면을 썸네일 격자로 (방향키 + Enter 또는 클릭으로 이동)
DialogFrame {
    id: d
    title: App.chaptersTitle
    onOpened: { grid.model = App.chapterList(); grid.currentIndex = App.currentChapterIndex(); grid.forceActiveFocus() }
    Connections { target: App; function onChaptersChanged() { if (d.opened) grid.model = App.chapterList() } }
    Column {
        spacing: Theme.px(8)
        RowLayout {
            width: grid.width
            Text { Layout.fillWidth: true; text: grid.count ? "" : App.chaptersEmptyText; color: Theme.muted; font.pixelSize: Theme.px(12) }
            JButton { tool: true; text: App.sceneAnalysisLabel; enabled: App.sceneAnalysisAvailable; onClicked: { App.toggleSceneAnalysis(); d.close() } }
        }
        GridView {
            id: grid
            width: Theme.px(4 * 176); height: Math.min(Theme.px(3 * 130), Math.max(1, Math.ceil(count / 4)) * Theme.px(130))
            cellWidth: Theme.px(176); cellHeight: Theme.px(130)
            clip: true
            keyNavigationEnabled: true
            ScrollBar.vertical: ScrollBar { }
            highlight: Rectangle { color: Theme.rowActive; radius: 8; border.color: Theme.accent }
            delegate: Item {
                required property var modelData
                required property int index
                width: grid.cellWidth; height: grid.cellHeight
                Column {
                    anchors.centerIn: parent; spacing: 3
                    Rectangle {
                        width: Theme.px(160); height: Theme.px(90); color: "#0f141d"; radius: 4
                        Image { anchors.fill: parent; source: modelData.thumb; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                        Text { anchors.centerIn: parent; text: "🎞️"; visible: !modelData.thumb; font.pixelSize: 24 }
                    }
                    Text {
                        width: Theme.px(160); elide: Text.ElideRight; textFormat: Text.StyledText
                        text: (modelData.current ? "▶ " : "") + "<b>" + modelData.time + "</b>  " + modelData.title
                        color: Theme.textSoft; font.pixelSize: Theme.px(11)
                    }
                }
                MouseArea { anchors.fill: parent; onClicked: d.jump(modelData.ms) }
            }
            Keys.onReturnPressed: if (currentIndex >= 0) d.jump(model[currentIndex].ms)
        }
    }
    function jump(ms) { d.close(); App.jumpToChapter(ms) }
}
