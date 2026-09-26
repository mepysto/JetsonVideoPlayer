import QtQuick
import JetsonPlayer

// 화면 위쪽 가운데 짧은 알림 (속도, 탐색, 설정 변경 등)
Rectangle {
    id: osd
    visible: opacity > 0
    opacity: 0
    // 작은 창(미니 플레이어)에서는 창 너비에 맞춰 줄바꿈하고 글자도 줄입니다
    readonly property real maxWidth: parent ? parent.width - Theme.px(16) : 600
    readonly property bool compact: maxWidth < Theme.px(520)
    width: Math.min(label.implicitWidth + Theme.px(compact ? 20 : 48), maxWidth)
    height: label.height + Theme.px(compact ? 10 : 20)
    radius: 9; color: Theme.overlay; border.color: "#3b4455"
    Text {
        id: label
        anchors.centerIn: parent
        width: Math.min(implicitWidth, osd.maxWidth - Theme.px(osd.compact ? 20 : 48))
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        color: Theme.accent; font.pixelSize: Theme.px(osd.compact ? 13 : 19); font.bold: true; text: App.osdText
    }
    Behavior on opacity { NumberAnimation { duration: 150 } }
    Timer { id: hide; onTriggered: osd.opacity = 0 }
    Connections {
        target: App
        function onOsdShown(ms) { osd.opacity = 1; hide.interval = ms; hide.restart() }
    }
}
