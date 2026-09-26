import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// 자막 선택·크기·싱크, AI 자막·번역
JPopup {
    id: pop
    title: "💬 자막"
    width: Theme.px(380)
    readonly property var s: App.subtitles
    Text {
        visible: s.tracks.length === 0 && s.embeddedCount === 0
        text: "자막 없음 — 🤖 AI 자막을 만들어 보세요 (G)"
        color: Theme.muted; font.pixelSize: Theme.px(12)
    }
    Repeater {
        model: s.tracks
        delegate: Row {
            required property var modelData
            required property int index
            spacing: 6
            Rectangle { width: 10; height: 10; radius: 5; color: modelData.color; anchors.verticalCenter: parent.verticalCenter }
            JCheck {
                width: pop.width - 2 * pop.padding - 20
                text: modelData.label
                checked: modelData.active
                onClicked: App.subtitles.toggleTrack(index)
            }
        }
    }
    JCheck {
        visible: s.embeddedCount > 0
        text: "💬 " + s.embeddedLabel + (s.embeddedCount > 1 ? "  (Shift+클릭: 다음 트랙)" : "")
        checked: s.embeddedEnabled
        onClicked: App.subtitles.toggleEmbedded()
    }
    JButton { visible: s.embeddedCount > 1; tool: true; text: "다음 내장 자막 트랙"; onClicked: App.subtitles.cycleEmbeddedTrack() }
    RowLayout {
        spacing: 4
        Text { text: "크기 " + Math.round(s.fontScale * 100) + "%"; color: Theme.textSoft; font.pixelSize: Theme.px(12); Layout.preferredWidth: Theme.px(80) }
        JButton { tool: true; text: "−"; onClicked: App.subtitles.adjustScale(-0.1) }
        JButton { tool: true; text: "+"; onClicked: App.subtitles.adjustScale(0.1) }
        JButton { tool: true; text: "기본"; onClicked: App.subtitles.resetScale() }
    }
    RowLayout {
        spacing: 4
        Text { text: "싱크 " + (s.offsetMs / 1000).toFixed(1) + "초"; color: Theme.textSoft; font.pixelSize: Theme.px(12); Layout.preferredWidth: Theme.px(80) }
        JButton { tool: true; text: "-0.5"; onClicked: App.subtitles.adjustSync(-500) }
        JButton { tool: true; text: "-0.1"; onClicked: App.subtitles.adjustSync(-100) }
        JButton { tool: true; text: "+0.1"; onClicked: App.subtitles.adjustSync(100) }
        JButton { tool: true; text: "+0.5"; onClicked: App.subtitles.adjustSync(500) }
        JButton { tool: true; text: "0"; onClicked: App.subtitles.resetSync() }
    }
    JButton { width: pop.width - 2 * pop.padding; tool: true; text: App.ai.menuLabel; onClicked: { App.startAiSubtitles(); pop.close() } }
    JButton { width: pop.width - 2 * pop.padding; tool: true; text: App.translation.menuLabel; onClicked: { App.startTranslation(); pop.close() } }
    JButton { width: pop.width - 2 * pop.padding; tool: true; text: "🌐 온라인 자막 찾기..."; onClicked: { App.requestDialog("onlineSubs", ""); pop.close() } }
    Text { text: "S: 켜기/끄기 · [ ]: 크기 · Z/X ,/.: 싱크"; color: Theme.muted; font.pixelSize: Theme.px(11) }
}
