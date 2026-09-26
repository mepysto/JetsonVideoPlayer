import QtQuick
import JetsonPlayer

// 영상이 끝나면 "다음: …" 카드와 카운트다운
Rectangle {
    visible: App.autoplay.visible
    width: Theme.px(360); height: col.implicitHeight + Theme.px(24)
    radius: 12; color: Theme.overlay; border.color: "#3b4455"
    Column {
        id: col
        anchors.centerIn: parent; width: parent.width - Theme.px(24); spacing: Theme.px(8)
        Text { text: "다음 영상 " + Math.ceil(App.autoplay.remaining) + "초 후 재생"; color: Theme.muted; font.pixelSize: Theme.px(12) }
        Text { width: parent.width; text: App.autoplay.title; color: Theme.text; font.bold: true; font.pixelSize: Theme.px(14); elide: Text.ElideMiddle }
        Rectangle {
            width: parent.width; height: 4; radius: 2; color: "#303744"
            Rectangle { width: parent.width * App.autoplay.fraction; height: 4; radius: 2; color: Theme.accent }
        }
        Row {
            spacing: Theme.px(8)
            JButton { text: "▶ 지금 재생"; primary: true; onClicked: App.autoplayNow() }
            JButton { text: "취소"; tool: true; onClicked: App.cancelAutoplay() }
        }
    }
}
