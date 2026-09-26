import QtQuick
import QtQuick.Window
import JetsonPlayer.Video

Window {
    width: 1280; height: 720; visible: true; color: "black"
    title: "Jetson Video Player"
    VideoItem { anchors.fill: parent; bridge: frameBridge }
}
