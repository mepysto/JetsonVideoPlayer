#pragma once
// 키보드 단축키 정의 테이블 (파이썬 shortcuts.py 이식).
// 키 처리, 도움말(F1), README 단축키 표가 모두 이 테이블 하나에서 만들어집니다.
// 표는 위에서부터 차례로 검사하며 처음 일치하는 항목이 실행됩니다.
//
// modifiers 조건:
//   "plain" : Shift/Ctrl 없이   "shift" : Shift (Ctrl 없이)   "ctrl" : Ctrl (Shift 없이)
//   "ctrl_shift": Ctrl+Shift    "noctrl": Ctrl 없이 (Shift 무관)  "any" : 조건 없음

#include <QList>
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>
#include <Qt>

namespace jvp::shortcuts {

struct Shortcut {
    QList<int> keys;        // Qt::Key 값 (글자는 대소문자 구분 없이 Qt::Key_A 하나)
    QString modifiers;      // 위 조건 이름
    QString action;         // 파이썬 창 메서드 이름 그대로 (예: "seek_relative")
    QVariantList args;      // 예: {30} / {-0.25}
    QString helpKey;        // 도움말에 보일 키 (비어 있으면 도움말에서 생략 — 짝이 되는 앞 항목이 설명)
    QString helpDesc;
    QString category;

    QVariantMap toVariantMap() const;   // QML용 {keys, modifiers, action, args, helpKey, helpDesc, category}
};

// 카테고리 이름 (도움말 제목)
extern const QString kPlayback, kMarks, kScreen, kSubs, kGeneral, kExtra;
const QStringList &categoryOrder();

const QList<Shortcut> &shortcuts();

bool modsMatch(const QString &mods, bool shift, bool ctrl);
// 눌린 키에 해당하는 첫 항목 (없으면 nullptr).
// qtKey로 먼저 찾고, 없으면 text(한 글자 ASCII)로 다시 찾습니다 — 키 배열이 달라 key()가 다른 경우 대비.
const Shortcut *findShortcut(int qtKey, Qt::KeyboardModifiers modifiers, const QString &text = QString());
// 테스트·조합 검사용: shift/ctrl 상태를 직접 지정
const Shortcut *matchShortcut(int qtKey, bool shift, bool ctrl);   // (오버로드로 두면 enum·문자열 인자가 bool로 바뀌어 엉뚱한 쪽이 불림)

struct HelpRow {
    QString category;
    QString key;
    QString desc;
};
// 카테고리 순서대로 (마우스 조작 포함)
QList<HelpRow> helpRows();
QVariantList helpRowsVariant();   // QML용 [{category, key, desc}]
// README용 마크다운 표 (파이썬 markdown_tables()와 같은 출력)
QString markdownTables();

} // namespace jvp::shortcuts
