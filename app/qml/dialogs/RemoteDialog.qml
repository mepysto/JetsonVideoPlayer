import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 스마트폰 웹 리모컨: QR 코드로 바로 로그인, 주소·PIN 안내
DialogFrame {
    id: d
    title: "📱 스마트폰 웹 리모컨"
    Column {
        spacing: 8
        width: Theme.px(340)
        Image { anchors.horizontalCenter: parent.horizontalCenter; source: d.opened ? "image://qr/" + encodeURIComponent(App.remote.loginUrl) : ""; width: Theme.px(220); height: width; smooth: false; cache: false }
        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "휴대폰 카메라로 QR 코드를 찍으세요"; color: Theme.textSoft; font.pixelSize: Theme.px(12) }
        Text { width: parent.width; wrapMode: Text.WrapAnywhere; horizontalAlignment: Text.AlignHCenter; text: App.remote.url; color: Theme.accent; font.pixelSize: Theme.px(14); font.bold: true }
        Text { anchors.horizontalCenter: parent.horizontalCenter; text: "PIN " + App.remote.pin; color: "#ffffff"; font.pixelSize: Theme.px(22); font.bold: true; font.letterSpacing: 6 }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; spacing: 6
            JButton { tool: true; text: "📋 주소 복사"; onClicked: App.copyText(App.remote.url, "📋 리모컨 주소를 복사했습니다") }
            JButton { tool: true; text: "🔐 새 PIN (모든 기기 로그아웃)"; onClicked: App.remote.regeneratePin() }
        }
    }
}
