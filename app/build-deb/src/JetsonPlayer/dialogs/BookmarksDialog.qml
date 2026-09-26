import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

DialogFrame {
    id: d
    title: "🔖 북마크"
    onOpened: list.model = App.bookmarkList()
    Column {
        spacing: 6
        Text { visible: list.count === 0; text: "이 영상에 북마크가 없습니다. (B: 현재 위치 추가)"; color: Theme.muted; font.pixelSize: Theme.px(12) }
        ListView {
            id: list
            width: Theme.px(360); height: Math.min(contentHeight, Theme.px(360)); clip: true
            delegate: RowLayout {
                required property var modelData
                required property int index
                width: ListView.view.width
                JButton { Layout.fillWidth: true; tool: true; text: "🔖 " + modelData.label; onClicked: { d.close(); App.jumpToMs(modelData.ms) } }
                JButton { tool: true; text: "✕"; onClicked: { App.removeBookmark(index); list.model = App.bookmarkList() } }
            }
        }
    }
}
