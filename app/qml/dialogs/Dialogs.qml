import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic
import QtQuick.Dialogs

// 이름으로 여는 대화상자 모음 (App.requestDialog(name) → 여기)
Item {
    id: root
    function open(name, arg) {
        switch (name) {
        case "openFile": fileDialog.open(); break
        case "openFolder": folderDialog.open(); break
        case "saveM3u": saveDialog.currentFile = App.suggestedM3uUrl(); saveDialog.open(); break
        case "help": help.open(); break
        case "search": search.open(); break
        case "chapters": chapters.open(); break
        case "bookmarks": bookmarks.open(); break
        case "network": network.open(); break
        case "onlineSubs": onlineSubs.open(); break
        case "osAccount": account.open(); break
        case "remote": remote.open(); break
        case "youtube": youtube.open(); break
        case "mountPassword": password.show(arg); break
        }
    }

    FileDialog {
        id: fileDialog
        title: "동영상 파일 열기"
        fileMode: FileDialog.OpenFiles
        nameFilters: ["동영상·재생목록 (*.mp4 *.mkv *.avi *.mov *.webm *.ts *.m4v *.m3u *.m3u8 *.MP4 *.MKV)", "모든 파일 (*)"]
        onAccepted: App.openUrls(selectedFiles)
    }
    FolderDialog {
        id: folderDialog
        title: "동영상 폴더 열기"
        onAccepted: App.openUrls([selectedFolder])
    }
    FileDialog {
        id: saveDialog
        title: "재생목록 저장 (M3U)"
        fileMode: FileDialog.SaveFile
        nameFilters: ["M3U8 재생목록 (*.m3u8 *.m3u)"]
        onAccepted: App.saveM3u(selectedFile)
    }
    HelpDialog { id: help }
    SearchDialog { id: search }
    ChaptersDialog { id: chapters }
    BookmarksDialog { id: bookmarks }
    NetworkDialog { id: network }
    PasswordDialog { id: password }
    OnlineSubsDialog { id: onlineSubs }
    AccountDialog { id: account }
    RemoteDialog { id: remote }
    YouTubeDialog { id: youtube }
}
