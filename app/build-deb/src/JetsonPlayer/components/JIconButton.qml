import QtQuick
import JetsonPlayer

// 아이콘(이모지/기호) 한 글자짜리 버튼
JButton {
    implicitWidth: Math.max(implicitHeight, contentItem.implicitWidth + leftPadding + rightPadding)
    font.pixelSize: Theme.px(15)
}
