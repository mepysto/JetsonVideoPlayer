import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// GVfs 마운트 인증 (사용자·비밀번호·도메인)
DialogFrame {
    id: d
    title: "🔐 네트워크 폴더 로그인"
    property string message: ""
    closePolicy: Popup.CloseOnEscape
    onClosed: if (!accepted) App.network.cancel()
    property bool accepted: false
    function show(info) {
        accepted = false
        message = info.message || ""
        user.text = info.user || ""
        domain.text = info.domain || ""
        pass.text = ""
        open()
        (user.text.length ? pass : user).forceActiveFocus()
    }
    Column {
        spacing: 8
        width: Theme.px(360)
        Text { width: parent.width; wrapMode: Text.WordWrap; text: d.message; color: Theme.textSoft; font.pixelSize: Theme.px(12) }
        JField { id: user; width: parent.width; placeholderText: "사용자" }
        JField { id: pass; width: parent.width; placeholderText: "비밀번호"; echoMode: TextInput.Password; onAccepted: d.ok() }
        JField { id: domain; width: parent.width; placeholderText: "도메인 (선택)" }
        JCheck { id: remember; text: "로그인할 때까지 기억"; checked: true }
        Row {
            anchors.right: parent.right; spacing: 6
            JButton { text: "취소"; tool: true; onClicked: d.close() }
            JButton { text: "연결"; primary: true; onClicked: d.ok() }
        }
    }
    function ok() { accepted = true; App.network.reply(user.text, pass.text, domain.text, remember.checked); close() }
}
