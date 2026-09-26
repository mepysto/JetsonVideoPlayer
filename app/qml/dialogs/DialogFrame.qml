import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 가운데 뜨는 대화상자 틀 (Esc로 닫힘)
Popup {
    id: frame
    property string title: ""
    default property alias content: body.data
    parent: Overlay.overlay
    anchors.centerIn: parent
    modal: true
    focus: true
    padding: Theme.px(14)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { color: Theme.panel; border.color: Theme.panelBorder; radius: 10 }
    Overlay.modal: Rectangle { color: "#80000000" }
    contentItem: Column {
        spacing: Theme.px(10)
        Text { text: frame.title; color: Theme.accent; font.pixelSize: Theme.px(15); font.bold: true; visible: text.length > 0 }
        Item {
            id: body
            implicitWidth: childrenRect.width
            implicitHeight: childrenRect.height
            width: implicitWidth; height: implicitHeight
        }
    }
}
