pragma Singleton
import QtQuick

// 파이썬(GTK) 버전 style.css와 같은 색·크기 — 사용자에게 익숙한 모양 유지
QtObject {
    readonly property color bg: "#090b10"
    readonly property color bar: "#11151d"
    readonly property color border: "#252b36"
    readonly property color sidebar: "#0e1117"
    readonly property color panel: "#131822"
    readonly property color panelBorder: "#2a3240"
    readonly property color field: "#161b24"
    readonly property color text: "#f4f6fb"
    readonly property color textSoft: "#dce2ec"
    readonly property color muted: "#8f98a8"
    readonly property color accent: "#e9ff5b"
    readonly property color accentHover: "#f2ff91"
    readonly property color hover: "#252b36"
    readonly property color rowActive: "#242b35"
    readonly property color danger: "#fca5a5"
    readonly property color overlay: Qt.rgba(14 / 255, 17 / 255, 23 / 255, 0.90)
    readonly property string mono: "monospace"
    readonly property int radius: 7
    // TV(10-foot) 모드에서는 글자와 터치 영역을 키웁니다
    property real scale: 1.0
    // TV 모드: 리모컨 방향키로 옮긴 초점도 테두리로 보여줍니다 (데스크톱은 Tab 이동일 때만)
    property bool tv: false
    function px(v) { return Math.round(v * scale) }
}
