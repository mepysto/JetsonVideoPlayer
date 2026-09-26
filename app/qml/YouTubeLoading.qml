import QtQuick
import JetsonPlayer

Rectangle {
    width: Theme.px(420); height: col.implicitHeight + Theme.px(30)
    radius: 12; color: Theme.overlay; border.color: "#3b4455"
    Column {
        id: col
        anchors.centerIn: parent
        width: parent.width - Theme.px(30)
        spacing: Theme.px(8)
        Text { width: parent.width; text: App.youtube.title || "YouTube 영상 준비 중..."; color: Theme.text; font.bold: true; font.pixelSize: Theme.px(14); elide: Text.ElideRight }
        Rectangle {
            width: parent.width; height: 6; radius: 3; color: "#303744"
            Rectangle { width: parent.width * Math.min(1, (App.youtube.percent || 0) / 100); height: 6; radius: 3; color: Theme.accent }
        }
        Text { text: App.youtube.status || "⚡ 받는 중..."; color: Theme.muted; font.pixelSize: Theme.px(12) }
    }
}
