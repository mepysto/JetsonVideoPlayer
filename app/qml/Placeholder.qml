import QtQuick
import JetsonPlayer
import QtQuick.Layouts

// 대기 화면: 열기 버튼 + 이어보기 카드
Column {
    spacing: Theme.px(14)
    Text { anchors.horizontalCenter: parent.horizontalCenter; text: "🎬"; font.pixelSize: Theme.px(54) }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: "재생할 동영상 또는 폴더를 드래그 앤 드롭하세요"
        color: Theme.textSoft; font.pixelSize: Theme.px(16); font.bold: true
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: "상단의 빠른 조작 바 또는 아래 버튼으로 즉시 선택할 수 있습니다 (단축키: Ctrl+O)"
        color: Theme.muted; font.pixelSize: Theme.px(12)
    }
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Theme.px(12)
        JButton { text: "📂 동영상 파일 열기"; primary: true; onClicked: dialogs.open("openFile") }
        JButton { text: "📁 폴더 열기"; tool: true; onClicked: dialogs.open("openFolder") }
        JButton { text: "▶️ 유튜브 영상 재생"; tool: true; onClicked: dialogs.open("youtube") }
        JButton { text: "🌐 네트워크 폴더"; tool: true; onClicked: dialogs.open("network") }
    }
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Theme.px(8)
        visible: cards.count > 0
        Text { text: "⏱️ 이어보기"; color: Theme.accent; font.bold: true; font.pixelSize: Theme.px(13) }
        Repeater {
            id: cards
            model: App.resumeCards
            delegate: Rectangle {
                required property var modelData
                width: Theme.px(420); height: Theme.px(62); radius: 8
                color: cardMouse.containsMouse ? "#1c2433" : "#141a24"
                border.color: "#232c3d"
                Column {
                    anchors.fill: parent; anchors.margins: Theme.px(8); spacing: 4
                    Text { width: parent.width; text: modelData.title; color: Theme.text; font.pixelSize: Theme.px(13); font.bold: true; elide: Text.ElideMiddle }
                    Rectangle {
                        width: parent.width; height: 4; radius: 2; color: "#303744"
                        Rectangle { width: parent.width * modelData.fraction; height: 4; radius: 2; color: Theme.accent }
                    }
                    Text { text: modelData.meta; color: Theme.muted; font.pixelSize: Theme.px(11) }
                }
                MouseArea { id: cardMouse; anchors.fill: parent; hoverEnabled: true; onClicked: App.openPath(modelData.path) }
            }
        }
    }
}
