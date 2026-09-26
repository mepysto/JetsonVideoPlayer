import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// 메뉴 항목: 체크 항목이 섞인 메뉴에서는 일반 항목도 체크 표시 자리만큼 들여써서 글자 시작 위치를 맞춥니다
MenuItem {
    readonly property real checkGutter: indicator ? indicator.width + spacing : 0
    leftPadding: padding + (!checkable && menu && menu.hasCheckable ? checkGutter : 0)
}
