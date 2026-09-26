import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

CheckBox {
    id: control
    font.pixelSize: Theme.px(12)
    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        font: control.font
        color: control.hovered ? "#ffffff" : Theme.textSoft
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
}
