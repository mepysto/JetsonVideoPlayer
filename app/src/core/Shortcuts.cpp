#include "Shortcuts.h"

#include <QHash>
#include <algorithm>

namespace jvp::shortcuts {

const QString kPlayback = QStringLiteral("재생 및 탐색");
const QString kMarks = QStringLiteral("구간 반복 & 북마크 & 캡처");
const QString kScreen = QStringLiteral("화면 및 오디오");
const QString kSubs = QStringLiteral("자막");
const QString kGeneral = QStringLiteral("파일 및 일반");
const QString kExtra = QStringLiteral("부가 기능");

namespace {

// 파이썬 표의 Gdk 키 이름 → Qt::Key. Qt는 글자 키를 대소문자 구분 없이 하나로,
// Shift로 바뀐 기호는 바뀐 기호(예: Shift+[ → Key_BraceLeft)로 알려 줘서 Gdk와 같은 방식으로 맞춰집니다.
int gdkKey(const QString &name)
{
    static const QHash<QString, int> named = {
        {"Escape", Qt::Key_Escape},
        {"space", Qt::Key_Space},
        {"Right", Qt::Key_Right},
        {"Left", Qt::Key_Left},
        {"Up", Qt::Key_Up},
        {"Down", Qt::Key_Down},
        {"parenright", Qt::Key_ParenRight},
        {"parenleft", Qt::Key_ParenLeft},
        {"greater", Qt::Key_Greater},
        {"less", Qt::Key_Less},
        {"period", Qt::Key_Period},
        {"comma", Qt::Key_Comma},
        {"bracketleft", Qt::Key_BracketLeft},
        {"bracketright", Qt::Key_BracketRight},
        {"braceleft", Qt::Key_BraceLeft},
        {"braceright", Qt::Key_BraceRight},
        {"backslash", Qt::Key_Backslash},
        {"bar", Qt::Key_Bar},
        {"question", Qt::Key_Question},
        {"F1", Qt::Key_F1},
        {"F5", Qt::Key_F5},
    };
    const auto it = named.constFind(name);
    if (it != named.constEnd())
        return *it;
    if (name.size() == 1 && name.at(0).unicode() < 128)
        return name.at(0).toUpper().unicode();   // 글자·숫자: Qt::Key_A == 'A', Qt::Key_0 == '0'
    Q_ASSERT_X(false, "shortcuts", "unknown key name");
    return Qt::Key_unknown;
}

Shortcut sc(std::initializer_list<const char *> names, const char *mods, const char *action, QVariantList args = {},
            const QString &helpKey = QString(), const QString &helpDesc = QString(), const QString &category = QString())
{
    Shortcut s;
    for (const char *n : names) {
        const int k = gdkKey(QString::fromLatin1(n));
        if (!s.keys.contains(k))
            s.keys << k;
    }
    s.modifiers = QString::fromLatin1(mods);
    s.action = QString::fromLatin1(action);
    s.args = std::move(args);
    s.helpKey = helpKey;
    s.helpDesc = helpDesc;
    s.category = category;
    return s;
}

QList<Shortcut> buildTable()
{
    // 도움말 인자가 없는 항목은 바로 앞 항목과 짝 (앞 항목의 설명이 둘 다 다룸)
    return {
        // 파일 / 캡처 / 북마크 (Ctrl 조합 우선)
        sc({"s", "S"}, "ctrl", "capture_screenshot", {}, "Ctrl + S", "현재 프레임 원본 무손실 스크린샷 저장", kMarks),
        sc({"o", "O"}, "ctrl_shift", "open_folder_dialog", {}, "Ctrl + Shift + O", "동영상 폴더 열기", kGeneral),
        sc({"o", "O"}, "ctrl", "open_file_dialog", {}, "Ctrl + O", "동영상 파일 열기", kGeneral),
        sc({"b", "B"}, "ctrl", "show_bookmarks_popover", {}, "Ctrl + B", "북마크 목록 (클릭 시 점프 / 삭제)", kMarks),
        sc({"b", "B"}, "plain", "add_bookmark", {}, "B", "현재 위치 북마크 추가", kMarks),

        // 종료 / 전체화면 해제
        sc({"Escape"}, "any", "handle_escape", {}, "Esc", "전체화면 해제 (일반 창에서는 종료)", kGeneral),
        sc({"q", "Q"}, "noctrl", "quit_player", {}, "Q", "플레이어 종료", kGeneral),

        // 재생 및 탐색
        sc({"space"}, "any", "toggle_play_pause", {}, "Space / 마우스 좌클릭", "재생 / 일시정지", kPlayback),
        sc({"Right"}, "shift", "seek_relative", {30}, "Shift + Left / Right", "30초 뒤로 / 앞으로", kPlayback),
        sc({"Left"}, "shift", "seek_relative", {-30}),
        sc({"Right"}, "ctrl", "frame_step", {1}, "Ctrl + Left / Right", "한 프레임 뒤로 / 앞으로 (일시정지 상태)", kPlayback),
        sc({"Left"}, "ctrl", "frame_step", {-1}),
        sc({"Right"}, "any", "seek_relative", {10}, "Left / Right", "10초 뒤로 / 앞으로", kPlayback),
        sc({"Left"}, "any", "seek_relative", {-10}),
        sc({"l", "L"}, "noctrl", "seek_relative", {10}, "J / L", "10초 뒤로 / 앞으로 (YouTube 스타일)", kPlayback),
        sc({"j", "J"}, "noctrl", "seek_relative", {-10}),
        sc({"n", "N"}, "noctrl", "play_next_video", {}, "P / N", "이전 영상 / 다음 영상 (대기열 우선)", kPlayback),
        sc({"p", "P"}, "noctrl", "play_prev_video"),

        // 볼륨 (Shift+Up/Down은 속도보다 먼저 검사)
        sc({"Up"}, "shift", "step_volume", {5}, "0 / 9 (또는 Shift + Up / Down)", "볼륨 5% 올리기 / 내리기 (최대 200% 부스트)", kScreen),
        sc({"Down"}, "shift", "step_volume", {-5}),
        sc({"0", "parenright"}, "noctrl", "step_volume", {5}),
        sc({"9", "parenleft"}, "noctrl", "step_volume", {-5}),
        sc({"m", "M"}, "noctrl", "toggle_mute", {}, "M", "음소거 켜기 / 끄기", kScreen),

        // 재생 속도
        sc({"Up", "d", "D"}, "plain", "step_playback_rate", {0.25}, "Up / Down 또는 D / A", "재생 속도 +0.25x / -0.25x", kPlayback),
        sc({"Down", "a", "A"}, "plain", "step_playback_rate", {-0.25}),
        sc({"greater", "period"}, "shift", "step_playback_rate", {0.25}, "> / <", "재생 속도 빠르게 / 느리게", kPlayback),
        sc({"less", "comma"}, "shift", "step_playback_rate", {-0.25}),
        sc({"r", "R"}, "shift", "cycle_repeat_mode", {}, "Shift + R", "재생 모드 순환 (전체반복 → 한곡반복 → 순차정지 → 셔플)", kPlayback),
        sc({"r", "R"}, "ctrl", "cycle_repeat_mode"),
        sc({"r", "R"}, "plain", "reset_playback_rate", {}, "R", "재생 속도 1.0x 복원", kPlayback),

        // 오디오 트랙 / AV 싱크
        sc({"a", "A"}, "shift", "cycle_audio_track", {}, "Shift + A", "오디오(음성) 트랙 전환", kScreen),
        sc({"z", "Z"}, "shift", "adjust_av_sync", {-50}, "Shift + Z / X", "오디오(AV) 싱크 50ms 앞당김 / 늦춤", kScreen),
        sc({"x", "X"}, "shift", "adjust_av_sync", {50}),
        sc({"c", "C"}, "shift", "reset_av_sync", {}, "Shift + C", "오디오(AV) 싱크 0ms 초기화", kScreen),

        // 구간 반복
        sc({"bracketleft", "braceleft"}, "shift", "set_ab_repeat_a", {}, "Shift + [ / ]", "A-B 구간 반복 시작점(A) / 끝점(B) 설정", kMarks),
        sc({"bracketright", "braceright"}, "shift", "set_ab_repeat_b"),
        sc({"backslash", "bar"}, "any", "clear_ab_repeat", {}, "\\ (백슬래시)", "A-B 구간 반복 해제", kMarks),

        // 자막
        sc({"s", "S"}, "plain", "toggle_subtitles", {}, "S", "자막 켜기 / 끄기 (내장 자막 포함)", kSubs),
        sc({"c", "C"}, "plain", "show_subtitle_popover", {}, "C", "자막 선택 및 크기/싱크 설정 창", kSubs),
        sc({"bracketleft"}, "plain", "adjust_subtitle_scale", {-0.1}, "[ / ]", "자막 크기 -10% / +10%", kSubs),
        sc({"bracketright"}, "plain", "adjust_subtitle_scale", {0.1}),
        sc({"z", "Z"}, "plain", "adjust_subtitle_sync", {-500}, "Z / X", "자막 싱크 -0.5초 / +0.5초", kSubs),
        sc({"x", "X"}, "plain", "adjust_subtitle_sync", {500}),
        sc({"comma"}, "plain", "adjust_subtitle_sync", {-100}, ", / .", "자막 싱크 -0.1초 / +0.1초", kSubs),
        sc({"period"}, "plain", "adjust_subtitle_sync", {100}),
        sc({"g", "G"}, "plain", "start_ai_subtitles", {}, "G", "🤖 AI 자막 생성 (Whisper, 음성 인식)", kSubs),
        sc({"g", "G"}, "shift", "start_translation", {}, "Shift + G", "🌐 켜 둔 자막을 한국어(설정 언어)로 번역", kSubs),
        sc({"f", "F"}, "ctrl", "show_dialogue_search", {}, "Ctrl + F", "🔎 대사 검색 (재생목록 전체 자막에서 찾아 그 장면으로 이동)", kSubs),

        // 화면
        sc({"f", "F"}, "noctrl", "toggle_fullscreen", {}, "F / 마우스 더블클릭", "영상 전용 전체화면", kScreen),
        sc({"w", "W"}, "plain", "toggle_mini_player", {}, "W", "🗗 미니 플레이어 (작은 창 항상 위 · 드래그 이동 · 더블클릭 복귀)", kScreen),
        sc({"t", "T"}, "noctrl", "toggle_keep_above", {}, "T", "항상 위에 표시", kScreen),
        sc({"i", "I"}, "noctrl", "toggle_hud", {}, "I", "Jetson 하드웨어 & 미디어 정보 HUD", kScreen),
        sc({"v", "V"}, "plain", "cycle_video_rotation", {}, "V", "화면 회전 (90° 단위 / 좌우·상하 반전)", kScreen),
        sc({"e", "E"}, "plain", "toggle_night_mode", {}, "E", "🌙 야간 모드 (큰 소리 줄이고 작은 대사 키우기)", kScreen),

        // 부가 기능
        sc({"h", "H"}, "plain", "cycle_sleep_timer", {}, "H", "⏾ 수면 타이머 (15 → 30 → 60분 → 영상 끝 → 끄기)", kExtra),
        sc({"k", "K"}, "plain", "show_chapters_menu", {}, "K", "챕터 / 장면 목록", kExtra),

        sc({"F5"}, "any", "rescan_playlist", {}, "F5", "🔄 재생목록 새로고침 (폴더에 추가·삭제된 영상 반영)", kGeneral),
        sc({"F1", "question"}, "any", "show_help_dialog", {}, "F1 또는 ?", "단축키 도움말", kGeneral),
    };
}

// 도움말에만 표시되는 마우스 조작
QList<HelpRow> mouseHelp()
{
    return {
        {kPlayback, QStringLiteral("마우스 휠 위 / 아래"), QStringLiteral("비디오 영역에서 10초 앞으로 / 뒤로")},
        {kPlayback, QStringLiteral("진행바에 마우스 올리기"), QStringLiteral("해당 시각 미리보기 (썸네일)")},
        {kGeneral, QStringLiteral("마우스 우클릭"), QStringLiteral("빠른 조작 메뉴")},
    };
}

} // namespace

QVariantMap Shortcut::toVariantMap() const
{
    QVariantList k;
    for (int key : keys)
        k << key;
    return {{QStringLiteral("keys"), k},
            {QStringLiteral("modifiers"), modifiers},
            {QStringLiteral("action"), action},
            {QStringLiteral("args"), args},
            {QStringLiteral("helpKey"), helpKey},
            {QStringLiteral("helpDesc"), helpDesc},
            {QStringLiteral("category"), category}};
}

const QStringList &categoryOrder()
{
    static const QStringList order = {kPlayback, kMarks, kScreen, kSubs, kExtra, kGeneral};
    return order;
}

const QList<Shortcut> &shortcuts()
{
    static const QList<Shortcut> table = buildTable();
    return table;
}

bool modsMatch(const QString &mods, bool shift, bool ctrl)
{
    if (mods == QLatin1String("any"))
        return true;
    if (mods == QLatin1String("plain"))
        return !shift && !ctrl;
    if (mods == QLatin1String("shift"))
        return shift && !ctrl;
    if (mods == QLatin1String("ctrl"))
        return ctrl && !shift;
    if (mods == QLatin1String("ctrl_shift"))
        return ctrl && shift;
    if (mods == QLatin1String("noctrl"))
        return !ctrl;
    return false;
}

const Shortcut *matchShortcut(int qtKey, bool shift, bool ctrl)
{
    for (const Shortcut &s : shortcuts())
        if (s.keys.contains(qtKey) && modsMatch(s.modifiers, shift, ctrl))
            return &s;
    return nullptr;
}

const Shortcut *findShortcut(int qtKey, Qt::KeyboardModifiers modifiers, const QString &text)
{
    const bool shift = modifiers.testFlag(Qt::ShiftModifier);
    const bool ctrl = modifiers.testFlag(Qt::ControlModifier);
    if (const Shortcut *s = matchShortcut(qtKey, shift, ctrl))
        return s;
    if (text.size() == 1 && text.at(0).unicode() > 0x20 && text.at(0).unicode() < 0x7f) {
        const int fromText = text.at(0).toUpper().unicode();
        if (fromText != qtKey)
            return matchShortcut(fromText, shift, ctrl);
    }
    return nullptr;
}

QList<HelpRow> helpRows()
{
    QList<HelpRow> rows;
    for (const Shortcut &s : shortcuts())
        if (!s.helpKey.isEmpty())
            rows.append({s.category, s.helpKey, s.helpDesc});
    rows += mouseHelp();
    std::stable_sort(rows.begin(), rows.end(), [](const HelpRow &a, const HelpRow &b) {
        return categoryOrder().indexOf(a.category) < categoryOrder().indexOf(b.category);
    });
    return rows;
}

QVariantList helpRowsVariant()
{
    QVariantList out;
    for (const HelpRow &r : helpRows())
        out << QVariantMap{{QStringLiteral("category"), r.category},
                           {QStringLiteral("key"), r.key},
                           {QStringLiteral("desc"), r.desc}};
    return out;
}

QString markdownTables()
{
    QStringList out;
    QString current;
    for (const HelpRow &r : helpRows()) {
        if (r.category != current) {
            current = r.category;
            out << QStringLiteral("\n### %1\n| 조작 | 기능 |\n| --- | --- |").arg(r.category);
        }
        const bool plain = r.key.contains(QStringLiteral("마우스")) || r.key.contains(QStringLiteral("진행바"));
        const QString keys = plain ? r.key : QStringLiteral("`%1`").arg(r.key);
        out << QStringLiteral("| %1 | %2 |").arg(keys, r.desc);
    }
    return out.join(QLatin1Char('\n')).trimmed() + QLatin1Char('\n');
}

} // namespace jvp::shortcuts
