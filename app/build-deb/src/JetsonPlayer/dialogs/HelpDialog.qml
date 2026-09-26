import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 단축키 안내 (C++ 단축키 표에서 생성 — 키 처리와 항상 일치)
DialogFrame {
    id: d
    title: "⌨️ Jetson Video Player 단축키 안내"
    ListView {
        width: Theme.px(560); height: Math.min(Theme.px(620), d.parent ? d.parent.height * 0.8 : 600)
        clip: true
        model: App.helpRows()
        section.property: "category"
        section.delegate: Text { text: section; color: Theme.accent; font.bold: true; font.pixelSize: Theme.px(13); topPadding: 8 }
        ScrollBar.vertical: ScrollBar { }
        delegate: Row {
            required property var modelData
            spacing: Theme.px(16)
            Text { width: Theme.px(200); text: modelData.key; color: "#ffffff"; font.pixelSize: Theme.px(12); font.bold: true; wrapMode: Text.WordWrap }
            Text { width: Theme.px(320); text: modelData.desc; color: Theme.textSoft; font.pixelSize: Theme.px(12); wrapMode: Text.WordWrap }
        }
    }
}
