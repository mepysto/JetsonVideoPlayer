// tests/test_subtitle_timeline.py 이식
#include "AssRenderer.h"
#include "SubtitleTrack.h"

#include <QtConcurrent>
#include <QtTest>

using namespace jvp;

class TestSubtitleTrack : public QObject
{
    Q_OBJECT
private slots:
    void activeAtAndBoundaries()
    {
        SubtitleTrack tr(QStringLiteral("🇰🇷 한국어 (a.ko.srt)"), "#FFFFFF",
                         {{1000, 2000, QStringLiteral("하나")}, {2000, 3000, QStringLiteral("둘")}, {5000, 9000, QStringLiteral("셋")}});
        QCOMPARE(tr.activeAt(999), QStringList());
        QCOMPARE(tr.activeAt(1000), QStringList{QStringLiteral("하나")});
        QCOMPARE(tr.activeAt(1999), QStringList{QStringLiteral("하나")});
        QCOMPARE(tr.activeAt(2000), QStringList{QStringLiteral("둘")}); // 끝 시각은 포함하지 않음
        QCOMPARE(tr.activeAt(4000), QStringList());
        QCOMPARE(tr.activeAt(8999), QStringList{QStringLiteral("셋")});
    }
    void overlappingAndLongEvents()
    {
        SubtitleTrack tr("x", "#fff", {{0, 60000, QStringLiteral("긴 제목")}, {1000, 2000, QStringLiteral("대사")}});
        QCOMPARE(tr.activeAt(1500), (QStringList{QStringLiteral("긴 제목"), QStringLiteral("대사")}));
        QCOMPARE(tr.activeAt(30000), QStringList{QStringLiteral("긴 제목")});
    }
    void addEventsIncrementallyOutOfOrder()
    {
        SubtitleTrack tr(QStringLiteral("🤖 AI"), "#B388FF");
        tr.addEvents({{5000, 6000, QStringLiteral("나중")}});
        tr.addEvents({{1000, 2000, QStringLiteral("먼저")}, {3000, 3000, QStringLiteral("길이0 무시")}, {4000, 4500, "   "}});
        QCOMPARE(tr.size(), 2);
        QCOMPARE(tr.activeAt(1500), QStringList{QStringLiteral("먼저")});
        QCOMPARE(tr.activeAt(5500), QStringList{QStringLiteral("나중")});
    }
    void nextChangeAfter()
    {
        SubtitleTrack tr("x", "#fff", {{1000, 2000, "a"}, {5000, 6000, "b"}});
        QCOMPARE(tr.nextChangeAfter(0), std::optional<qint64>(1000));
        QCOMPARE(tr.nextChangeAfter(1500), std::optional<qint64>(2000));
        QCOMPARE(tr.nextChangeAfter(2500), std::optional<qint64>(5000));
        QVERIFY(!tr.nextChangeAfter(7000).has_value());
    }
    void activeLinesMultiTrackBadgesAndOffset()
    {
        auto ko = std::make_shared<SubtitleTrack>(QStringLiteral("🇰🇷 한국어 (a.ko.srt)"), "#FFFFFF",
                                                  SubtitleEvents{{1000, 2000, QStringLiteral("안녕\n하세요")}});
        auto en = std::make_shared<SubtitleTrack>(QStringLiteral("🇺🇸 영어 (a.en.srt)"), "#FFE066",
                                                  SubtitleEvents{{1000, 2000, "Hello"}});
        QCOMPARE(activeLines({ko}, 1500),
                 (QList<SubtitleLine>{{QStringLiteral("안녕"), "#FFFFFF"}, {QStringLiteral("하세요"), "#FFFFFF"}}));
        QCOMPARE(activeLines({ko, en}, 1500),
                 (QList<SubtitleLine>{{QStringLiteral("[KR] 안녕"), "#FFFFFF"},
                                      {QStringLiteral("하세요"), "#FFFFFF"},
                                      {QStringLiteral("[EN] Hello"), "#FFE066"}}));
        // 오프셋 +500ms: 자막이 0.5초 늦게 표시
        QVERIFY(activeLines({ko}, 1200, 500).isEmpty());
        QVERIFY(!activeLines({ko}, 1600, 500).isEmpty());
    }
    void activeLinesSkipsAssTracks()
    {
        auto plain = std::make_shared<SubtitleTrack>("a", "#FFFFFF", SubtitleEvents{{0, 1000, "plain"}});
        auto styled = std::make_shared<SubtitleTrack>("b", "#FFFFFF", SubtitleEvents{{0, 1000, "styled"}},
                                                      std::make_shared<AssRenderer>());
        QCOMPARE(activeLines({plain, styled}, 500), (QList<SubtitleLine>{{"plain", "#FFFFFF"}}));
        styled->setAssRenderer(nullptr);
        QCOMPARE(activeLines({plain, styled}, 500).size(), 2);
    }
    void shortBadgeTest()
    {
        QCOMPARE(shortBadge(QStringLiteral("🇯🇵 일본어 (x.ja.srt)")), QStringLiteral("[JP] "));
        QCOMPARE(shortBadge(QStringLiteral("🤖 AI 자막 (auto)")), QStringLiteral("[AI] "));
        QCOMPARE(shortBadge(QStringLiteral("📄 x.srt")), QString());
    }
    void duplicateEventsAreAddedOnce()
    {
        SubtitleTrack track(QStringLiteral("내장"), "#fff");
        track.addEvents({{0, 1000, "a"}, {0, 1000, "a"}});
        track.addEvents({{0, 1000, "a"}, {500, 1500, "b"}}); // 탐색 후 다시 도착
        QCOMPARE(track.size(), 2);
        QCOMPARE(track.activeAt(700), (QStringList{"a", "b"}));
    }
    void concurrentAddAndQuery()
    {
        SubtitleTrack track("ai", "#fff");
        auto writer = QtConcurrent::run([&] {
            for (int i = 0; i < 2000; ++i)
                track.addEvents({{i * 10LL, i * 10LL + 15, QString::number(i)}});
        });
        while (!writer.isFinished())
            track.activeAt(5000);
        writer.waitForFinished();
        QCOMPARE(track.size(), 2000);
        QCOMPARE(track.activeAt(12), (QStringList{"0", "1"}));
    }
};

QTEST_GUILESS_MAIN(TestSubtitleTrack)
#include "test_subtitle_track.moc"
