import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 메뉴: 가장 긴 항목에 맞춘 너비, 창 밖으로 나갈 수 있는 별도 팝업 창 (Qt 6.8+, 지원하지 않는 화면에서는 창 안에 그림)
Menu {
    id: menu
    popupType: Popup.Window
    width: {
        let w = Theme.px(200)
        for (let i = 0; i < count; ++i) {
            const it = itemAt(i)
            if (it)
                w = Math.max(w, it.implicitWidth)
        }
        return w + leftPadding + rightPadding
    }
}
