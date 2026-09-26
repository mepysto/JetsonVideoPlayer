import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 메뉴: 가장 긴 항목에 맞춘 너비 (창 너비를 넘지 않음)
// Popup.Window(별도 창)는 Jetson X11에서 내용이 그려지지 않고 EGLFS 키오스크에서는 지원되지 않아 쓰지 않습니다.
Menu {
    id: menu
    // 체크 항목이 하나라도 있으면 JMenuItem이 모든 항목의 글자 시작 위치를 맞춥니다
    readonly property bool hasCheckable: {
        for (let i = 0; i < count; ++i) {
            const it = itemAt(i)
            if (it && it.checkable)
                return true
        }
        return false
    }
    delegate: JMenuItem {}
    width: {
        let w = Theme.px(200)
        for (let i = 0; i < count; ++i) {
            const it = itemAt(i)
            if (it)
                w = Math.max(w, it.implicitWidth)
        }
        w += leftPadding + rightPadding
        return parent && parent.Window.window ? Math.min(w, parent.Window.window.width) : w
    }
}
