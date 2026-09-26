import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

TextField {
    id: control
    color: Theme.textSoft
    placeholderTextColor: Theme.muted
    font.pixelSize: Theme.px(12)
    selectByMouse: true
    background: Rectangle {
        color: Theme.field
        radius: 6
        border.color: control.activeFocus ? Theme.accent : "#2a3344"
    }
}
