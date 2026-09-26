import QtQuick
import QtQuick.Controls.Basic
import JetsonPlayer

// 영상 영역: 영상 + 자막 + 대기 화면 + OSD/HUD + 떠 있는 컨트롤 + 마우스·드래그 앤 드롭
Rectangle {
    id: area
    color: "black"
    signal requestFocus()

    VideoItem {
        id: video
        anchors.fill: parent
        bridge: App.frameBridge
        orientation: App.rotation
        hdrMode: App.hdrMode === "pq" ? 1 : App.hdrMode === "hlg" ? 2 : 0
        hdrMatrixFix: App.hdrMatrixFix
    }

    SubtitleOverlay {
        anchors.fill: parent
        controller: App.subtitles
        videoRect: video.videoRect
    }

    // 마우스: 클릭 재생/일시정지(더블클릭과 구분), 더블클릭 전체화면, 휠 탐색, 우클릭 메뉴,
    // 미니 플레이어에서는 끌어서 창 이동·휠 볼륨·Ctrl+휠 크기·더블클릭 복귀
    MouseArea {
        id: mouse
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        cursorShape: App.cursorHidden ? Qt.BlankCursor : Qt.ArrowCursor
        property point pressPos
        onPositionChanged: (m) => {
            App.noteMouseActivity()
            if (App.miniMode && pressed)
                App.moveWindowBy(m.x - pressPos.x, m.y - pressPos.y)
        }
        onPressed: (m) => { pressPos = Qt.point(m.x, m.y); area.requestFocus() }
        onClicked: (m) => {
            if (m.button === Qt.RightButton) { contextMenu.popup(); return }
            if (!App.miniMode) clickTimer.restart()
        }
        onDoubleClicked: (m) => {
            clickTimer.stop()
            if (m.button !== Qt.LeftButton) return
            if (App.miniMode) App.toggleMiniPlayer(); else App.toggleFullscreen()
        }
        onWheel: (w) => {
            const up = w.angleDelta.y > 0
            if (App.miniMode) {
                if (w.modifiers & Qt.ControlModifier) App.resizeMini(up ? 1.1 : 1 / 1.1)
                else App.stepVolume(up ? 5 : -5)
            } else {
                App.seekRelative(up ? 10 : -10)
            }
        }
        Timer { id: clickTimer; interval: 250; onTriggered: App.togglePlayPause() }
    }

    DropArea {
        anchors.fill: parent
        onDropped: (drop) => {
            if (drop.hasUrls) App.dropUrls(drop.urls)
            else if (drop.hasText) App.dropText(drop.text)
        }
    }

    Placeholder { anchors.centerIn: parent; visible: !App.hasVideo && !App.youtubeLoading }
    YouTubeLoading { anchors.centerIn: parent; visible: App.youtubeLoading }
    Osd { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: Theme.px(25) }
    Hud { anchors.left: parent.left; anchors.top: parent.top; anchors.margins: Theme.px(16); visible: App.hudVisible }
    AutoplayCard { anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: Theme.px(24) }

    FloatingControls {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.margins: Theme.px(12)
        visible: App.fullscreen && App.controlsVisible
    }
    MiniControls {
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom
        anchors.bottomMargin: Theme.px(8)
        visible: App.miniMode && App.controlsVisible
    }
    Rectangle {   // A-B 구간 반복 표시
        visible: App.abActive || App.abA >= 0
        anchors.right: parent.right; anchors.top: parent.top; anchors.margins: Theme.px(12)
        color: "#2e1065"; border.color: "#7c3aed"; radius: 6
        width: abText.implicitWidth + 16; height: abText.implicitHeight + 6
        Text { id: abText; anchors.centerIn: parent; color: Theme.accent; font.bold: true; font.pixelSize: Theme.px(11); text: App.abLabel }
        MouseArea { anchors.fill: parent; onClicked: App.clearAbRepeat() }
    }

    ContextMenu { id: contextMenu }
}
