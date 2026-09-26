import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

Slider {
    id: control
    property color fill: Theme.accent
    hoverEnabled: true
    background: Rectangle {
        x: control.leftPadding
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: control.availableWidth
        height: Theme.px(4)
        radius: 3
        color: "#303744"
        Rectangle {
            width: control.visualPosition * parent.width
            height: parent.height
            radius: 3
            color: control.fill
        }
    }
    handle: Rectangle {
        x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: Theme.px(13); height: width; radius: width / 2
        color: "#ffffff"
        border.color: control.visualFocus ? Theme.accent : "transparent"
        border.width: 2
    }
}
