import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

JPopup {
    id: pop
    title: "⚡ 재생 속도"
    Grid {
        columns: 4; spacing: Theme.px(4)
        Repeater {
            model: [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
            JButton {
                required property var modelData
                tool: true; active: Math.abs(App.rate - modelData) < 0.01
                text: modelData + "x"
                onClicked: { App.setRate(modelData); pop.close() }
            }
        }
    }
    Text { text: "↑/↓ 또는 D/A: ±0.25x · R: 1.0x (음정 유지)"; color: Theme.muted; font.pixelSize: Theme.px(11) }
}
