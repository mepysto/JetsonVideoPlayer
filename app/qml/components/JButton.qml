import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 평평한 버튼 (GTK 버전의 button / .primary / .tree-tool-btn 모양)
Button {
    id: control
    property bool primary: false
    property bool tool: false          // 작은 도구 버튼 (재생목록 도구 등)
    property bool active: false        // 켜진 상태 강조
    property int textAlign: Text.AlignHCenter
    readonly property bool focusRing: visualFocus || (Theme.tv && activeFocus)
    property color fg: primary || active ? "#111318" : (tool ? "#a0aec0" : Theme.textSoft)
    font.pixelSize: Theme.px(tool ? 11 : 13)
    font.bold: primary
    padding: Theme.px(tool ? 4 : 6)
    leftPadding: Theme.px(tool ? 8 : 10)
    rightPadding: leftPadding
    focusPolicy: Qt.TabFocus
    hoverEnabled: true
    contentItem: Text {
        text: control.text
        font: control.font
        color: control.enabled ? (control.hovered && !control.primary && !control.active ? "#ffffff" : control.fg) : Theme.muted
        horizontalAlignment: control.textAlign
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: control.primary ? height / 2 : (control.tool ? 5 : Theme.radius)
        color: control.primary ? (!control.enabled ? "#2d3748" : control.hovered ? Theme.accentHover : Theme.accent)
             : control.active ? Theme.accent
             : control.down ? "#2d3748"
             : control.hovered || control.focusRing ? Theme.hover
             : control.tool ? "#1a202c" : "transparent"
        border.color: control.focusRing ? Theme.accent : "transparent"
        border.width: control.focusRing ? 2 : 0
    }
    ToolTip.visible: hovered && ToolTip.text.length > 0
    ToolTip.delay: 600
}
