import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 최근 재생한 파일·폴더
JPopup {
    id: pop
    title: "🕒 최근 재생 항목"
    width: Theme.px(340)
    onAboutToShow: list.model = App.history()
    Text {
        visible: list.count === 0
        text: "최근 재생 기록이 없습니다."
        color: Theme.muted
        font.pixelSize: Theme.px(12)
    }
    ListView {
        id: list
        width: pop.width - 2 * pop.padding
        height: Math.min(contentHeight, Theme.px(320))
        clip: true
        delegate: JButton {
            required property var modelData
            width: ListView.view.width
            tool: true
            text: (modelData.isDir ? "📁 " : "🎬 ") + modelData.title
            textAlign: Text.AlignLeft
            ToolTip.text: modelData.path
            onClicked: { pop.close(); App.openPath(modelData.path) }
        }
    }
}
