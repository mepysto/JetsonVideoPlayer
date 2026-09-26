// tests/test_dialogue_search.py 이식
#include "DialogueIndex.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QTemporaryDir>
#include <QThread>
#include <QtTest>

using namespace jvp;

class TestDialogueIndex : public QObject
{
    Q_OBJECT
    QTemporaryDir m_home;
    QString m_dir;

    void srt(const QString &name, const QList<QPair<int, QString>> &lines)
    {
        QStringList blocks;
        int n = 0;
        for (const auto &[startS, text] : lines)
            blocks << QStringLiteral("%1\n00:00:%2,000 --> 00:00:%3,000\n%4\n")
                          .arg(++n)
                          .arg(startS, 2, 10, QLatin1Char('0'))
                          .arg(startS + 1, 2, 10, QLatin1Char('0'))
                          .arg(text);
        QFile f(m_dir + QLatin1Char('/') + name);
        QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Truncate));
        f.write(blocks.join(QLatin1Char('\n')).toUtf8());
    }
    QStringList makeLibrary()
    {
        for (const char *name : {"a.mkv", "b.mkv"}) {
            QFile f(m_dir + QLatin1Char('/') + QLatin1String(name));
            f.open(QIODevice::WriteOnly);
            f.write("x");
        }
        srt("a.ko.srt", {{1, QStringLiteral("안녕하세요 여러분")}, {5, QStringLiteral("오늘은\n날씨가 좋네요")}});
        srt("b.en.srt", {{2, "Hello  World"}, {9, "Good WEATHER today"}});
        return {m_dir + "/a.mkv", m_dir + "/b.mkv"};
    }
    static QList<QPair<QString, qint64>> videosAndStarts(const QList<SearchHit> &hits)
    {
        QList<QPair<QString, qint64>> out;
        for (const SearchHit &h : hits)
            out.append({QFileInfo(h.video).fileName(), h.startMs});
        return out;
    }

private slots:
    void initTestCase()
    {
        QVERIFY(m_home.isValid());
        qputenv("HOME", m_home.path().toUtf8());
    }
    void init()
    {
        static int n = 0;
        m_dir = m_home.path() + QStringLiteral("/lib%1").arg(++n);
        QVERIFY(QDir().mkpath(m_dir));
    }

    void normalizeIgnoresCaseAndWhitespace()
    {
        QCOMPARE(DialogueIndex::normalize("  Hello\n  World "), QStringLiteral("hello world"));
        QCOMPARE(DialogueIndex::normalize(QStringLiteral("STRASSE Straße")), QStringLiteral("strasse strasse"));
    }
    void searchAcrossPlaylist()
    {
        const QStringList videos = makeLibrary();
        DialogueIndex index;
        QVERIFY(index.build(videos));
        const auto hits = index.search(QStringLiteral("날씨가 좋"));
        QCOMPARE(videosAndStarts(hits), (QList<QPair<QString, qint64>>{{"a.mkv", 5000}}));
        QVERIFY(hits[0].text.contains(QStringLiteral("오늘은")));
        QVERIFY(hits[0].label.contains(QStringLiteral("한국어")));
        const auto hw = index.search("hello world");
        QCOMPARE(hw.size(), 1);
        QCOMPARE(hw[0].startMs, 2000);
        QVERIFY(index.search("   ").isEmpty());
        QCOMPARE(index.lineCount(), 4);
    }
    void currentVideoResultsComeFirst()
    {
        const QStringList videos = makeLibrary();
        srt("a.ko.srt", {{1, "weather report"}});
        DialogueIndex index;
        index.build(videos);
        QCOMPARE(videosAndStarts(index.search("weather")),
                 (QList<QPair<QString, qint64>>{{"a.mkv", 1000}, {"b.mkv", 9000}}));
        QCOMPARE(videosAndStarts(index.search("weather", 200, videos[1])),
                 (QList<QPair<QString, qint64>>{{"b.mkv", 9000}, {"a.mkv", 1000}}));
    }
    void rebuildRereadsOnlyChangedSubtitles()
    {
        const QStringList videos = makeLibrary();
        QStringList parsed;
        DialogueIndex index(subtitles::findAllMatchingSubtitles, [&](const QString &p) {
            parsed << QFileInfo(p).fileName();
            return subtitles::parseSubtitleFileEvents(p);
        });
        index.build(videos);
        parsed.sort();
        QCOMPARE(parsed, (QStringList{"a.ko.srt", "b.en.srt"}));
        parsed.clear();
        index.build(videos);
        QVERIFY(parsed.isEmpty());
        QThread::msleep(10);
        srt("b.ai.ko.srt", {{3, QStringLiteral("새 AI 대사")}});
        index.build(videos);
        parsed.sort();
        QCOMPARE(parsed, (QStringList{"b.ai.ko.srt", "b.en.srt"}));
        const auto hits = index.search(QStringLiteral("새 ai"));
        QCOMPARE(hits.size(), 1);
        QCOMPARE(hits[0].startMs, 3000);

        // invalidate: 다음 build에서 그 영상만 다시 읽음
        parsed.clear();
        index.invalidate(videos[0]);
        index.build(videos);
        QCOMPARE(parsed, QStringList{"a.ko.srt"});
    }
    void cancelledBuildKeepsOldIndex()
    {
        const QStringList videos = makeLibrary();
        DialogueIndex index;
        QVERIFY(index.build(videos));
        QVERIFY(!index.build(videos, [] { return true; }));
        QCOMPARE(index.search("hello").size(), 1);
    }
    void limit()
    {
        QFile v(m_dir + "/a.mkv");
        v.open(QIODevice::WriteOnly);
        v.write("x");
        v.close();
        QList<QPair<int, QString>> lines;
        for (int i = 0; i < 10; ++i)
            lines.append({i, "la"});
        srt("a.srt", lines);
        DialogueIndex index;
        index.build({m_dir + "/a.mkv"});
        QCOMPARE(index.search("la", 3).size(), 3);
    }
};

QTEST_GUILESS_MAIN(TestDialogueIndex)
#include "test_dialogue_index.moc"
