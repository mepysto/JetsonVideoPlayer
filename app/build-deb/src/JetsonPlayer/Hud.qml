import QtQuick
import JetsonPlayer

Rectangle {
    width: text.implicitWidth + Theme.px(36); height: text.implicitHeight + Theme.px(28)
    radius: 10; color: Qt.rgba(10 / 255, 14 / 255, 22 / 255, 0.92); border.color: "#3b4455"
    Text { id: text; anchors.centerIn: parent; textFormat: Text.StyledText; color: Theme.accent; font.family: Theme.mono; font.pixelSize: Theme.px(13); text: App.hudText }
}
