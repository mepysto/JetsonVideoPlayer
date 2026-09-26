// shortcuts.py 이식 검증 (tests/test_shortcuts.py 대응)
#include "Shortcuts.h"

#include <QDir>
#include <QFileInfo>
#include <QProcess>
#include <QStandardPaths>
#include <QTest>

using namespace jvp::shortcuts;

class TestShortcuts : public QObject {
    Q_OBJECT
private slots:
    void keyMapping_data()
    {
        QTest::addColumn<int>("key");
        QTest::addColumn<bool>("shift");
        QTest::addColumn<bool>("ctrl");
        QTest::addColumn<QString>("action");
        QTest::addColumn<QVariantList>("args");
        QTest::newRow("ctrl s") << int(Qt::Key_S) << false << true << "capture_screenshot" << QVariantList();
        QTest::newRow("s") << int(Qt::Key_S) << false << false << "toggle_subtitles" << QVariantList();
        QTest::newRow("ctrl shift O") << int(Qt::Key_O) << true << true << "open_folder_dialog" << QVariantList();
        QTest::newRow("ctrl o") << int(Qt::Key_O) << false << true << "open_file_dialog" << QVariantList();
        QTest::newRow("b") << int(Qt::Key_B) << false << false << "add_bookmark" << QVariantList();
        QTest::newRow("shift right") << int(Qt::Key_Right) << true << false << "seek_relative" << QVariantList{30};
        QTest::newRow("right") << int(Qt::Key_Right) << false << false << "seek_relative" << QVariantList{10};
        QTest::newRow("ctrl right") << int(Qt::Key_Right) << false << true << "frame_step" << QVariantList{1};
        QTest::newRow("up") << int(Qt::Key_Up) << false << false << "step_playback_rate" << QVariantList{0.25};
        QTest::newRow("shift up") << int(Qt::Key_Up) << true << false << "step_volume" << QVariantList{5};
        QTest::newRow("shift A") << int(Qt::Key_A) << true << false << "cycle_audio_track" << QVariantList();
        QTest::newRow("a") << int(Qt::Key_A) << false << false << "step_playback_rate" << QVariantList{-0.25};
        QTest::newRow("shift {") << int(Qt::Key_BraceLeft) << true << false << "set_ab_repeat_a" << QVariantList();
        QTest::newRow("[") << int(Qt::Key_BracketLeft) << false << false << "adjust_subtitle_scale" << QVariantList{-0.1};
        QTest::newRow("shift .") << int(Qt::Key_Period) << true << false << "step_playback_rate" << QVariantList{0.25};
        QTest::newRow("shift >") << int(Qt::Key_Greater) << true << false << "step_playback_rate" << QVariantList{0.25};
        QTest::newRow(".") << int(Qt::Key_Period) << false << false << "adjust_subtitle_sync" << QVariantList{100};
        QTest::newRow("shift R") << int(Qt::Key_R) << true << false << "cycle_repeat_mode" << QVariantList();
        QTest::newRow("r") << int(Qt::Key_R) << false << false << "reset_playback_rate" << QVariantList();
        QTest::newRow("escape") << int(Qt::Key_Escape) << false << false << "handle_escape" << QVariantList();
        QTest::newRow("shift )") << int(Qt::Key_ParenRight) << true << false << "step_volume" << QVariantList{5};
        QTest::newRow("shift ?") << int(Qt::Key_Question) << true << false << "show_help_dialog" << QVariantList();
        QTest::newRow("|") << int(Qt::Key_Bar) << true << false << "clear_ab_repeat" << QVariantList();
    }
    void keyMapping()
    {
        QFETCH(int, key);
        QFETCH(bool, shift);
        QFETCH(bool, ctrl);
        QFETCH(QString, action);
        QFETCH(QVariantList, args);
        const Shortcut *sc = matchShortcut(key, shift, ctrl);
        QVERIFY(sc);
        QCOMPARE(sc->action, action);
        QCOMPARE(sc->args, args);
        Qt::KeyboardModifiers mods;
        if (shift)
            mods |= Qt::ShiftModifier;
        if (ctrl)
            mods |= Qt::ControlModifier;
        QCOMPARE(findShortcut(key, mods), sc);
    }

    void unknownKey()
    {
        QVERIFY(!matchShortcut(Qt::Key_F12, false, false));
        QVERIFY(!findShortcut(Qt::Key_F12, Qt::NoModifier, QString()));
        QVERIFY(!findShortcut(Qt::Key_unknown, Qt::NoModifier, "ㅁ"));   // 한글 입력 상태의 글자는 대응 없음
    }

    void textFallback()
    {
        // key()가 모르는 값이어도 입력 글자로 찾습니다
        const Shortcut *sc = findShortcut(Qt::Key_unknown, Qt::ShiftModifier, "?");
        QVERIFY(sc);
        QCOMPARE(sc->action, QString("show_help_dialog"));
        QCOMPARE(findShortcut(0, Qt::NoModifier, "m")->action, QString("toggle_mute"));
    }

    void noFullyShadowedRows()
    {
        // 앞 항목에 완전히 가려져 절대 실행될 수 없는 항목이 없어야 합니다
        for (const Shortcut &sc : shortcuts()) {
            for (int key : sc.keys) {
                bool reachable = false;
                for (bool s : {false, true})
                    for (bool c : {false, true})
                        reachable = reachable || (modsMatch(sc.modifiers, s, c) && matchShortcut(key, s, c) == &sc);
                QVERIFY2(reachable, qPrintable(QString("%1 (%2) → %3 는 앞 항목에 가려집니다")
                                                   .arg(key, 0, 16).arg(sc.modifiers, sc.action)));
            }
        }
    }

    void tableShape()
    {
        QCOMPARE(shortcuts().size(), 58);   // 파이썬 표와 같은 항목 수
        for (const Shortcut &sc : shortcuts()) {
            QVERIFY(!sc.keys.isEmpty() && !sc.keys.contains(int(Qt::Key_unknown)));
            QVERIFY(sc.helpKey.isEmpty() || categoryOrder().contains(sc.category));
        }
        const QVariantMap m = shortcuts().at(8).toVariantMap();
        QCOMPARE(m.value("action").toString(), QString("seek_relative"));
        QCOMPARE(m.value("args").toList(), QVariantList{30});
    }

    void helpAndMarkdown()
    {
        const QList<HelpRow> rows = helpRows();
        QVERIFY(std::any_of(rows.begin(), rows.end(), [](const HelpRow &r) { return r.key == "Ctrl + S"; }));
        QCOMPARE(rows.first().category, kPlayback);
        QCOMPARE(rows.last().category, kGeneral);
        QCOMPARE(helpRowsVariant().size(), rows.size());
        const QString md = markdownTables();
        QVERIFY(md.contains("| `Ctrl + S` |") && md.contains("### 자막"));
        QVERIFY(md.contains("| 마우스 우클릭 | 빠른 조작 메뉴 |"));
        QVERIFY(md.startsWith("### 재생 및 탐색\n| 조작 | 기능 |\n| --- | --- |\n"));
    }

    void markdownMatchesPython()
    {
        // 저장소의 파이썬 원본이 있으면 출력이 글자 하나까지 같은지 비교
        const QString repo = QFileInfo(QStringLiteral(__FILE__)).absoluteDir().absoluteFilePath("../..");
        const QString python = QStandardPaths::findExecutable("python3");
        if (python.isEmpty() || !QFileInfo::exists(repo + "/jetson_player/shortcuts.py"))
            QSKIP("파이썬 원본 없음");
        QProcess proc;
        proc.setWorkingDirectory(repo);
        proc.start(python, {"-c", "import sys; from jetson_player.shortcuts import markdown_tables; "
                                  "sys.stdout.buffer.write(markdown_tables().encode('utf-8'))"});
        QVERIFY(proc.waitForFinished(30000));
        if (proc.exitCode() != 0)
            QSKIP("파이썬 모듈을 불러올 수 없음");
        QCOMPARE(markdownTables(), QString::fromUtf8(proc.readAllStandardOutput()));
    }
};

QTEST_GUILESS_MAIN(TestShortcuts)
#include "test_shortcuts.moc"
