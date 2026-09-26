import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 유튜브 링크를 받아서(H.264) 재생 — 클립보드에 링크가 있으면 미리 채웁니다
JPopup {
    id: pop
    title: "▶️ 유튜브 받아서 재생"
    width: Theme.px(420)
    onOpened: { url.text = App.clipboardYoutubeUrl(); url.forceActiveFocus(); url.selectAll() }
    JField {
        id: url
        width: pop.width - 2 * pop.padding
        placeholderText: "유튜브 링크 붙여넣기"
        onAccepted: go()
    }
    RowLayout {
        width: pop.width - 2 * pop.padding
        ComboBox {
            id: quality
            Layout.fillWidth: true
            textRole: "label"
            valueRole: "value"
            model: [{ label: "최고 화질 (H.264)", value: "best" }, { label: "1080p", value: "1080p" },
                    { label: "720p (빠름)", value: "720p" }, { label: "오디오만", value: "audio" }]
        }
        JButton { text: "⬇️ 받아서 재생"; primary: true; onClicked: pop.go() }
    }
    Text {
        visible: App.youtube.active || App.youtube.queue.length > 0
        width: pop.width - 2 * pop.padding
        wrapMode: Text.WordWrap
        color: Theme.muted
        font.pixelSize: Theme.px(12)
        text: App.youtube.active ? ("⬇️ " + App.youtube.title + "  " + Math.round(App.youtube.percent) + "%  " + App.youtube.speed
                                   + (App.youtube.queue.length ? "\n대기 " + App.youtube.queue.length + "개" : ""))
                                 : "대기 " + App.youtube.queue.length + "개"
    }
    JButton {
        visible: App.youtube.active
        text: "⏹ 지금 받는 것 취소"
        tool: true
        onClicked: App.cancelYoutube()
    }
    function go() {
        if (url.text.trim().length === 0) return
        App.startYoutube(url.text.trim(), quality.currentValue)
        pop.close()
    }
}
