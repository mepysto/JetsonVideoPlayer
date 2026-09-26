import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 네트워크 폴더 연결 중 질문 (예: SFTP 서버 키 확인) — 고른 답을 App.network.answer(i)로
DialogFrame {
    id: d
    title: "🌐 네트워크 폴더 확인"
    property string message: ""
    property var choices: []
    property bool answered: false
    onClosed: if (!answered) App.network.cancel()
    function show(info) {
        answered = false
        message = info.message || ""
        choices = info.choices || []
        open()
    }
    Column {
        spacing: 10
        width: Theme.px(420)
        Text { width: parent.width; wrapMode: Text.WordWrap; text: d.message; color: Theme.textSoft; font.pixelSize: Theme.px(12) }
        Row {
            anchors.right: parent.right; spacing: 6
            Repeater {
                model: d.choices
                JButton {
                    required property var modelData
                    required property int index
                    text: modelData; primary: index === 0
                    onClicked: { d.answered = true; App.network.answer(index); d.close() }
                }
            }
        }
    }
}
