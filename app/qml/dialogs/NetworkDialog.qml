import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 네트워크 폴더(SMB/NFS) 열기: 주소 입력 + 최근 위치
DialogFrame {
    id: d
    title: "🌐 네트워크 폴더 열기"
    onOpened: { const locs = App.networkLocations(); recent.model = locs; addr.text = locs.length ? locs[0].uri : ""; addr.forceActiveFocus(); addr.selectAll() }
    Column {
        spacing: 8
        width: Theme.px(460)
        Text {
            width: parent.width; wrapMode: Text.WordWrap; textFormat: Text.StyledText
            color: Theme.textSoft; font.pixelSize: Theme.px(12)
            text: "NAS·공유 폴더 주소를 입력하세요.<br><small>예: <tt>smb://192.168.0.10/video/드라마</tt> · <tt>nfs://nas/export/movies</tt> · <tt>\\\\NAS\\video</tt></small>"
        }
        JField { id: addr; width: parent.width; placeholderText: "smb://서버/공유/폴더"; onAccepted: d.go(text) }
        Text { visible: recent.count > 0; text: "최근 위치"; color: Theme.muted; font.pixelSize: Theme.px(11) }
        Repeater {
            id: recent
            JButton { required property var modelData; width: d.width - 2 * d.padding; tool: true; text: "🌐 " + modelData.name; ToolTip.text: modelData.uri; onClicked: d.go(modelData.uri) }
        }
        Row {
            anchors.right: parent.right; spacing: 6
            JButton { text: "취소"; tool: true; onClicked: d.close() }
            JButton { text: "연결"; primary: true; onClicked: d.go(addr.text) }
        }
    }
    function go(uri) { if (uri.trim().length === 0) return; d.close(); App.openNetworkUri(uri.trim()) }
}
