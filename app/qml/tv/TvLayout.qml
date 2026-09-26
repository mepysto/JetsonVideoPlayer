import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// TV(10-foot) 레이아웃: 리모컨·키보드 방향키만으로 조작. 영상은 항상 전체 화면.
//   영상 중: OK(Enter) → 조작 패널, ←/→ 10초 탐색, ↑/↓ 볼륨, Back(Esc) → 패널 닫기 / 홈
//   홈: 이어보기·재생목록·열기 타일을 방향키로 이동, OK로 선택
FocusScope {
    id: root
    focus: true
    property bool homeOpen: !App.hasVideo
    property bool panelOpen: false

    VideoArea { anchors.fill: parent }

    TvHome {
        id: home
        anchors.fill: parent
        visible: root.homeOpen
        focus: root.homeOpen
        onChosen: { root.homeOpen = false; root.forceActiveFocus() }
    }
    TvPanel {
        id: panel
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        visible: root.panelOpen && !root.homeOpen
        focus: visible
        onCloseRequested: { root.panelOpen = false; root.forceActiveFocus() }
    }

    Keys.onPressed: (event) => {
        if (root.homeOpen) return
        switch (event.key) {
        case Qt.Key_Return: case Qt.Key_Enter: case Qt.Key_Select:
            root.panelOpen = true; panel.forceActiveFocus(); event.accepted = true; break
        case Qt.Key_Escape: case Qt.Key_Back: case Qt.Key_Backspace:
            if (root.panelOpen) { root.panelOpen = false } else { root.homeOpen = true; home.forceActiveFocus() }
            event.accepted = true; break
        case Qt.Key_Up: App.stepVolume(5); event.accepted = true; break
        case Qt.Key_Down: App.stepVolume(-5); event.accepted = true; break
        case Qt.Key_Menu: case Qt.Key_M: tvMenu.popup(); event.accepted = true; break
        default:
            event.accepted = App.handleKey(event.key, event.modifiers, event.text)
        }
    }
    MoreMenu { id: tvMenu; x: (root.width - width) / 2; y: root.height * 0.15 }
}
