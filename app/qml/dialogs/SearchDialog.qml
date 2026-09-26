import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 대사 검색: 재생목록 전체 자막에서 찾아 그 장면으로 (지금 영상 결과가 먼저)
DialogFrame {
    id: d
    title: "🔎 대사 검색"
    onOpened: { App.refreshDialogueIndex(); query.forceActiveFocus(); run() }
    function run() { results.model = App.searchDialogue(query.text); status.text = App.dialogueSearchStatus(query.text, results.count) }
    Column {
        spacing: Theme.px(8)
        JField {
            id: query
            width: Theme.px(600)
            placeholderText: "대사 검색 (재생목록 전체 자막)"
            onTextChanged: debounce.restart()
            onAccepted: if (results.count > 0) d.jump(results.model[0])
            Keys.onDownPressed: { results.forceActiveFocus(); results.currentIndex = 0 }
        }
        Timer { id: debounce; interval: 150; onTriggered: d.run() }
        Connections { target: App; function onDialogueIndexReady() { d.run() } }
        Text { id: status; color: Theme.muted; font.pixelSize: Theme.px(12) }
        ListView {
            id: results
            width: Theme.px(600); height: Theme.px(420)
            clip: true
            keyNavigationEnabled: true
            ScrollBar.vertical: ScrollBar { }
            highlight: Rectangle { color: Theme.rowActive; radius: 6 }
            delegate: Item {
                required property var modelData
                required property int index
                width: ListView.view.width; height: col.implicitHeight + 8
                Column {
                    id: col
                    x: 6; y: 4; width: parent.width - 12
                    Text {
                        textFormat: Text.StyledText
                        text: "<b>" + modelData.time + "</b>  " + modelData.name + (modelData.current ? "  · <font color='#e9ff5b'>지금 영상</font>" : "")
                        color: Theme.muted; font.pixelSize: Theme.px(11)
                    }
                    Text { width: parent.width; textFormat: Text.StyledText; text: modelData.html; color: Theme.textSoft; font.pixelSize: Theme.px(13); wrapMode: Text.WordWrap }
                }
                MouseArea { anchors.fill: parent; onClicked: d.jump(modelData) }
                Keys.onReturnPressed: d.jump(modelData)
            }
        }
    }
    function jump(hit) { App.jumpToDialogue(hit.video, hit.startMs) }
}
