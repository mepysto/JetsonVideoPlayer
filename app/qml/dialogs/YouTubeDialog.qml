import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

DialogFrame {
    id: d
    title: "▶️ 유튜브 받아서 재생"
    onOpened: { url.text = App.clipboardYoutubeUrl(); url.forceActiveFocus(); url.selectAll() }
    Column {
        spacing: 8
        JField { id: url; width: Theme.px(440); placeholderText: "유튜브 링크 붙여넣기"; onAccepted: d.go() }
        RowLayout {
            width: Theme.px(440)
            ComboBox { id: quality; Layout.fillWidth: true; textRole: "label"; valueRole: "value"
                model: [{ label: "최고 화질 (H.264)", value: "best" }, { label: "1080p", value: "1080p" }, { label: "720p (빠름)", value: "720p" }, { label: "오디오만", value: "audio" }] }
            JButton { text: "⬇️ 받아서 재생"; primary: true; onClicked: d.go() }
        }
    }
    function go() { if (!url.text.trim().length) return; App.startYoutube(url.text.trim(), quality.currentValue); d.close() }
}
