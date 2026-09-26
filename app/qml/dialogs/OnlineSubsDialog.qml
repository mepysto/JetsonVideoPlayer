import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Layouts

// OpenSubtitles 검색 → 골라서 받기(두 번 누르기/Enter) → 바로 켜기
DialogFrame {
    id: d
    title: "🌐 온라인 자막 찾기 (OpenSubtitles)"
    readonly property var os: App.onlineSubs
    onOpened: {
        if (!os.hasKey) { d.close(); dialogs.open("osAccount"); return }
        query.text = os.defaultQuery(); langs.text = App.settings.opensubtitles_languages; os.search(query.text, langs.text)
    }
    Column {
        spacing: 8
        RowLayout {
            width: Theme.px(640)
            JField { id: query; Layout.fillWidth: true; onAccepted: d.os.search(text, langs.text) }
            JField { id: langs; Layout.preferredWidth: Theme.px(90); ToolTip.visible: hovered; ToolTip.text: "언어 코드 (쉼표로 구분): ko, en, ja, zh-cn ..." }
            JButton { text: "🔎 검색"; enabled: !d.os.busy; onClicked: d.os.search(query.text, langs.text) }
            JButton { text: "⚙️"; ToolTip.text: "API 키 / 계정 설정"; onClicked: dialogs.open("osAccount") }
        }
        Text { text: d.os.status; color: Theme.muted; font.pixelSize: Theme.px(12) }
        ListView {
            id: results
            width: Theme.px(640); height: Theme.px(360); clip: true
            model: d.os.results
            keyNavigationEnabled: true
            highlight: Rectangle { color: Theme.rowActive; radius: 6 }
            ScrollBar.vertical: ScrollBar { }
            delegate: Item {
                required property var modelData
                required property int index
                width: ListView.view.width; height: col.implicitHeight + 8
                Column {
                    id: col; x: 6; y: 4; width: parent.width - 12
                    Text { width: parent.width; elide: Text.ElideRight; text: (modelData.hashMatch ? "✓ " : "") + "[" + modelData.language + "] " + modelData.release; color: Theme.textSoft; font.bold: true; font.pixelSize: Theme.px(13) }
                    Text { text: modelData.title + " · 다운로드 " + modelData.downloads + "회"; color: Theme.muted; font.pixelSize: Theme.px(11) }
                }
                MouseArea { anchors.fill: parent; onClicked: results.currentIndex = index; onDoubleClicked: d.os.download(index) }
                Keys.onReturnPressed: d.os.download(index)
            }
        }
        Text { text: "두 번 누르면(또는 Enter) 받아서 바로 켭니다. ✓ = 이 영상 파일과 정확히 맞는 자막"; color: Theme.muted; font.pixelSize: Theme.px(11) }
    }
    Connections { target: d.os; function onDownloaded() { d.close() } }
}
