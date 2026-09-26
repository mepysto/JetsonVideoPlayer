import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 공통 팝오버 (GTK popover 모양)
Popup {
    id: pop
    property string title: ""
    default property alias content: body.data
    padding: Theme.px(10)
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle {
        color: Theme.panel
        border.color: Theme.panelBorder
        radius: 9
    }
    contentItem: Column {
        spacing: Theme.px(6)
        Text {
            visible: pop.title.length > 0
            text: pop.title
            color: Theme.accent
            font.pixelSize: Theme.px(13)
            font.bold: true
        }
        Column {
            id: body
            spacing: Theme.px(6)
        }
    }
}
