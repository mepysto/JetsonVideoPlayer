import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 진행바: 끄는 동안 키프레임 미리보기, 놓으면 정확한 위치로. 마우스를 올리면 썸네일·챕터 미리보기.
// 북마크·A-B 구간·챕터 위치를 눈금으로 표시합니다.
Item {
    id: bar
    implicitHeight: Theme.px(22)
    readonly property real duration: Math.max(1, App.durationMs)

    JSlider {
        id: slider
        anchors.fill: parent
        from: 0; to: 1
        focusPolicy: Qt.NoFocus
        value: pressed ? value : (App.durationMs > 0 ? App.positionMs / bar.duration : 0)
        onMoved: App.scrubTo(value)                 // 150ms마다 한 번 키프레임 탐색
        onPressedChanged: if (!pressed) App.seekToRatio(value)   // 놓으면 정확한 위치로
    }
    Repeater {   // 눈금
        model: App.timelineMarks
        Rectangle {
            required property var modelData
            x: slider.leftPadding + modelData * (slider.availableWidth) - 1
            y: 0; width: 2; height: Theme.px(5)
            color: "#8f98a8"
        }
    }
    MouseArea {  // 미리보기 (클릭은 슬라이더로 통과)
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onPositionChanged: (m) => {
            const r = Math.max(0, Math.min(1, (m.x - slider.leftPadding) / slider.availableWidth))
            preview.ratio = r
            preview.x = Math.max(0, Math.min(bar.width - preview.width, m.x - preview.width / 2))
            preview.visible = App.durationMs > 0
        }
        onExited: preview.visible = false
    }
    Rectangle {
        id: preview
        property real ratio: 0
        visible: false
        y: -height - 6
        width: Theme.px(172); height: col.implicitHeight + 8
        color: Theme.panel; border.color: Theme.panelBorder; radius: 8
        Column {
            id: col
            anchors.centerIn: parent
            spacing: 2
            Image {
                width: Theme.px(160); height: sourceSize.height > 0 ? width * sourceSize.height / sourceSize.width : 0
                source: preview.visible ? App.thumbnailUrl(preview.ratio * App.durationMs) : ""
                visible: status === Image.Ready
                asynchronous: true; cache: true
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: App.formatTime(preview.ratio * App.durationMs) + (App.chapterAt(preview.ratio * App.durationMs) ? "  " + App.chapterAt(preview.ratio * App.durationMs) : "")
                color: Theme.accent; font.bold: true; font.pixelSize: Theme.px(12)
            }
        }
    }
}
