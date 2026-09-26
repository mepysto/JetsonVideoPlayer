import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

DialogFrame {
    id: d
    title: "OpenSubtitles 설정"
    onOpened: { const c = App.onlineSubs.credentials(); key.text = c.api_key || ""; user.text = c.username || ""; pass.text = c.password || "" }
    Column {
        spacing: 8
        width: Theme.px(440)
        Text {
            width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.StyledText
            color: Theme.textSoft; font.pixelSize: Theme.px(12)
            onLinkActivated: (link) => Qt.openUrlExternally(link)
            text: "OpenSubtitles.com의 무료 <b>API 키</b>가 필요합니다.<br><a href='https://www.opensubtitles.com/consumers'>https://www.opensubtitles.com/consumers</a> 에서 발급받으세요.<br><small>계정을 넣으면 하루 다운로드 한도가 늘어납니다 (선택). 정보는 ~/.config/jetson_video_player/opensubtitles.json 에 본인만 읽을 수 있게 저장됩니다.</small>"
        }
        JField { id: key; width: parent.width; placeholderText: "API 키" }
        JField { id: user; width: parent.width; placeholderText: "아이디 (선택)" }
        JField { id: pass; width: parent.width; placeholderText: "비밀번호 (선택)"; echoMode: TextInput.Password }
        Row {
            anchors.right: parent.right; spacing: 6
            JButton { text: "취소"; tool: true; onClicked: d.close() }
            JButton {
                text: "저장"; primary: true; enabled: key.text.trim().length > 0
                onClicked: { App.onlineSubs.saveCredentials(key.text.trim(), user.text.trim(), pass.text); d.close(); dialogs.open("onlineSubs") }
            }
        }
    }
}
