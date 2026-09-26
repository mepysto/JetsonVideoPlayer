import QtQuick
import JetsonPlayer
import QtQuick.Controls.Basic

// ⋯ 더 보기 메뉴: 자주 쓰지 않는 기능과 설정을 한곳에 (파이썬 버전 ui/menu.py와 같은 구성)
Menu {
    id: menu
    readonly property bool hasVideo: App.hasVideo

    // 1) 지금 영상
    MenuItem { text: "🔖 북마크 목록 (Ctrl+B)"; enabled: menu.hasVideo; onTriggered: App.requestDialog("bookmarks", "") }
    MenuItem { text: "➕ 현재 위치 북마크 (B)"; enabled: menu.hasVideo; onTriggered: App.addBookmark() }
    MenuItem { text: "📸 스크린샷 캡처 (Ctrl+S)"; enabled: menu.hasVideo; onTriggered: App.captureScreenshot() }
    MenuItem { text: App.ai.menuLabel; enabled: menu.hasVideo; onTriggered: App.startAiSubtitles() }
    MenuItem { text: App.translation.menuLabel; enabled: menu.hasVideo; onTriggered: App.startTranslation() }
    MenuItem { text: "📑 챕터 / 장면 목록 (K)"; enabled: menu.hasVideo; onTriggered: App.requestDialog("chapters", "") }
    MenuItem { text: "🔎 대사 검색 (Ctrl+F)"; enabled: menu.hasVideo; onTriggered: App.requestDialog("search", "") }
    MenuItem { text: "🌐 온라인 자막 찾기 (OpenSubtitles)..."; enabled: menu.hasVideo; onTriggered: App.requestDialog("onlineSubs", "") }
    MenuSeparator {}

    // 2) 재생·화면·소리 설정
    MenuItem { text: "🌙 야간 모드: 대사 크게·폭음 작게 (E)"; checkable: true; checked: App.nightMode; onTriggered: App.toggleNightMode() }
    Menu {
        title: App.sleepMenuLabel
        Repeater {
            model: [[0, "끄기"], [15, "15분 후"], [30, "30분 후"], [60, "60분 후"], [-1, "현재 영상이 끝나면"]]
            MenuItem {
                required property var modelData
                text: modelData[1]; checkable: true; checked: App.sleepMinutes === modelData[0]
                onTriggered: App.setSleepTimer(modelData[0])
            }
        }
    }
    Menu {
        title: "🔄 화면 회전 (V)"
        Repeater {
            model: [["identity", "원래대로"], ["90r", "오른쪽으로 90°"], ["180", "180°"], ["90l", "왼쪽으로 90°"],
                    ["horiz", "좌우 반전"], ["vert", "상하 반전"]]
            MenuItem {
                required property var modelData
                text: modelData[1]; checkable: true; checked: App.rotation === modelData[0]
                onTriggered: App.setRotation(modelData[0])
            }
        }
    }
    MenuItem { text: "⏭ 다음 영상 5초 카운트다운"; checkable: true; checked: App.settings.autoplay_countdown; onTriggered: App.toggleSetting("autoplay_countdown") }
    MenuItem { text: "🎨 ASS 자막을 원래 글꼴·색·위치로"; checkable: true; checked: App.settings.subtitle_ass_styles; onTriggered: App.toggleAssStyles() }
    MenuItem { text: "🌈 HDR 영상 톤매핑 (SDR 화면에서 자연스러운 색)"; checkable: true; checked: App.settings.hdr_tonemap; onTriggered: App.toggleHdrTonemap() }
    MenuItem { text: App.loudnessMenuLabel; checkable: true; checked: App.settings.loudness_normalize; onTriggered: App.toggleLoudness() }
    Menu {
        title: "🎚️ EQ: " + App.eqPresetName
        Repeater {
            model: App.eqPresets()
            MenuItem {
                required property var modelData
                text: modelData.name; checkable: true; checked: App.settings.eq_preset === modelData.key
                onTriggered: App.setEqPreset(modelData.key)
            }
        }
    }
    MenuItem { text: "🔈 HDMI 패스스루 (AC3/DTS 원음 → AV 리시버, 실험적)"; checkable: true; checked: App.settings.audio_passthrough; onTriggered: App.togglePassthrough() }
    Menu {
        title: "🤖 AI 자막 설정"
        Menu {
            title: "인식 언어"
            Repeater {
                model: App.ai.languages()
                MenuItem {
                    required property var modelData
                    text: modelData.name; checkable: true; checked: App.settings.whisper_language === modelData.key
                    onTriggered: App.setSetting("whisper_language", modelData.key)
                }
            }
        }
        Menu {
            title: "인식 모델"
            Repeater {
                model: App.ai.models()
                MenuItem {
                    required property var modelData
                    text: modelData.label; checkable: true; checked: App.settings.whisper_model === modelData.name
                    onTriggered: App.setSetting("whisper_model", modelData.name)
                }
            }
        }
        MenuItem { text: "영어로 번역하며 인식"; checkable: true; checked: App.settings.whisper_translate; onTriggered: App.toggleSetting("whisper_translate") }
        MenuItem { text: "YouTube 영상은 자동 생성"; checkable: true; checked: App.settings.youtube_auto_ai_subtitles; onTriggered: App.toggleSetting("youtube_auto_ai_subtitles") }
        MenuItem { text: "AI 자막을 만들면 자동으로 번역"; checkable: true; checked: App.settings.whisper_auto_translate; onTriggered: App.toggleSetting("whisper_auto_translate") }
        Menu {
            title: "번역할 언어"
            Repeater {
                model: [["ko", "한국어"], ["en", "영어"], ["ja", "일본어"], ["zh", "중국어"]]
                MenuItem {
                    required property var modelData
                    text: modelData[1]; checkable: true; checked: App.settings.translate_target === modelData[0]
                    onTriggered: App.setSetting("translate_target", modelData[0])
                }
            }
        }
        Menu {
            title: "번역 엔진"
            Repeater {
                model: [["auto", "자동"], ["local", "로컬 번역 모델 (NLLB-200)"], ["claude", "Claude API"]]
                MenuItem {
                    required property var modelData
                    text: modelData[1]; checkable: true; checked: App.settings.translate_backend === modelData[0]
                    onTriggered: App.setSetting("translate_backend", modelData[0])
                }
            }
        }
    }
    Menu {
        title: "🖥️ 화면 모드"
        Repeater {
            model: [["auto", "자동 (키오스크면 TV)"], ["desktop", "데스크톱"], ["tv", "TV (리모컨·큰 글씨)"]]
            MenuItem {
                required property var modelData
                text: modelData[1]; checkable: true; checked: App.settings.ui_mode === modelData[0]
                onTriggered: App.setSetting("ui_mode", modelData[0])
            }
        }
    }
    MenuSeparator {}

    // 3) 도구 / 정보
    MenuItem { text: "🌐 네트워크 폴더 열기 (SMB/NFS)..."; onTriggered: App.requestDialog("network", "") }
    MenuItem { text: "📱 스마트폰 웹 리모컨..."; onTriggered: App.requestDialog("remote", "") }
    MenuItem { text: "ℹ️ 미디어 정보 HUD (I)"; checkable: true; checked: App.hudVisible; onTriggered: App.toggleHud() }
    MenuItem { text: "📌 항상 위에 표시 (T)"; checkable: true; checked: App.keepAbove; onTriggered: App.toggleKeepAbove() }
    MenuItem { text: "🗗 미니 플레이어 (W)"; onTriggered: App.toggleMiniPlayer() }
    MenuItem { text: "📄 로그 파일 보기"; onTriggered: App.openLogFile() }
    MenuItem { text: "❓ 단축키 안내 (F1)"; onTriggered: App.requestDialog("help", "") }
}
