// tests/test_subtitles.py + tests/test_ass.py(글자 부분) 이식
#include "SubtitleParse.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QTemporaryDir>
#include <QtTest>

using namespace jvp;
using namespace jvp::subtitles;

namespace {

const char *kScript = R"([Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,40,40,50,1
Style: Sign,Arial,48,&H0000FFFF,&H000000FF,&H00202020,&H00000000,-1,1,0,0,100,100,0,0,3,2,0,8,10,10,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.50,0:00:04.00,Default,,0,0,0,,Hello {\b1}bold{\b0} and {\i1\c&H0000FF&}red italic{\r}\Nsecond line
Dialogue: 1,0:00:02.00,0:00:05.00,Sign,,0,0,0,,{\an7\pos(100,200)}Top sign
Dialogue: 0,0:00:03.00,0:00:03.50,Default,,0,0,0,,{\p1}m 0 0 l 100 0 100 100{\p0}
Dialogue: 0,0:00:06.00,0:00:07.00,*Default,,0,0,0,,{\fs80\bord5\3c&HFF0000&\an9}Big{\fad(200,200)} right
)";

SubtitleEvent ev(qint64 s, qint64 e, const QString &t) { return {s, e, t}; }

} // namespace

class TestSubtitleParse : public QObject
{
    Q_OBJECT
    QTemporaryDir m_home;
    QString m_dir; // 테스트마다 새 폴더

    void touch(const QStringList &names, const QString &dir = QString())
    {
        for (const QString &n : names) {
            QFile f((dir.isEmpty() ? m_dir : dir) + QLatin1Char('/') + n);
            QVERIFY(f.open(QIODevice::WriteOnly));
            f.write("x");
        }
    }
    QStringList baseNames(const QStringList &paths)
    {
        QStringList out;
        for (const QString &p : paths)
            out << QFileInfo(p).fileName();
        return out;
    }
    QString writeBytes(const QString &name, const QByteArray &data)
    {
        const QString p = m_dir + QLatin1Char('/') + name;
        QFile f(p);
        f.open(QIODevice::WriteOnly);
        f.write(data);
        return p;
    }

private slots:
    void initTestCase()
    {
        // 실제 ~/.cache를 건드리지 않도록 HOME을 임시 폴더로
        QVERIFY(m_home.isValid());
        qputenv("HOME", m_home.path().toUtf8());
        qunsetenv("XDG_CONFIG_HOME");
        QCOMPARE(QDir::homePath(), m_home.path());
    }
    void init()
    {
        static int n = 0;
        m_dir = m_home.path() + QStringLiteral("/case%1").arg(++n);
        QVERIFY(QDir().mkpath(m_dir));
    }

    void srtTimeToMs()
    {
        QCOMPARE(subtitles::srtTimeToMs("00:01:23,456"), 83456);
        QCOMPARE(subtitles::srtTimeToMs("01:00:00.5"), 3600500);
        QCOMPARE(subtitles::srtTimeToMs("02:03.100"), 123100);
        QCOMPARE(subtitles::srtTimeToMs("garbage"), 0);
    }
    void msToSrtTimeRoundtrip()
    {
        for (qint64 ms : {0, 999, 83456, 3723004})
            QCOMPARE(subtitles::srtTimeToMs(msToSrtTime(ms)), ms);
        QCOMPARE(msToSrtTime(3723004), QStringLiteral("01:02:03,004"));
    }
    void parseSrt()
    {
        const QString c = "1\n00:00:01,000 --> 00:00:02,500\n<i>Hello</i>\nWorld\n\n2\n00:00:03,000 --> 00:00:04,000\nBye\n";
        QCOMPARE(parseSrtOrVttToEvents(c), (SubtitleEvents{ev(1000, 2500, "Hello\nWorld"), ev(3000, 4000, "Bye")}));
    }
    void parseVtt()
    {
        QCOMPARE(parseSrtOrVttToEvents("WEBVTT\n\n00:01.000 --> 00:02.000\nHi\n"), (SubtitleEvents{ev(1000, 2000, "Hi")}));
    }
    void parseSmi()
    {
        const QString c = QStringLiteral("<SAMI><BODY><SYNC Start=1000><P>안녕<br>하세요</P>"
                                         "<SYNC Start=3000><P>&nbsp;</P><SYNC Start=5000><P>끝</P></BODY></SAMI>");
        const SubtitleEvents events = parseSmiToEvents(c);
        QCOMPARE(events.first(), ev(1000, 3000, QStringLiteral("안녕\n하세요")));
        QCOMPARE(events.last().startMs, 5000);
        QCOMPARE(events.last().text, QStringLiteral("끝"));
        QCOMPARE(events.last().endMs, 9000); // 마지막은 4초
    }
    void parseAss()
    {
        const QString c = "[Events]\n"
                          "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                          "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\b1}Hello\\NWorld, again\n";
        QCOMPARE(parseAssToEvents(c), (SubtitleEvents{ev(1000, 2500, "Hello\nWorld, again")}));
    }
    void assScriptPlain()
    {
        const SubtitleEvents events = parseAssToEvents(QString::fromUtf8(kScript));
        QCOMPARE(events.size(), 3); // 그리기(\p1)만 있는 대사는 제외
        QCOMPARE(events[0], ev(1500, 4000, "Hello bold and red italic\nsecond line"));
        QCOMPARE(events[1], ev(2000, 5000, "Top sign"));
        QCOMPARE(events[2], ev(6000, 7000, "Big right"));
    }
    void assTagArgumentsStartingWithLetters()
    {
        // \fnComic Sans, \rSign처럼 인자가 영문자로 시작해도 태그 이름과 구분 — 글자로 새지 않아야 함
        QCOMPARE(assTextToPlain("{\\fnComic Sans}Hello {\\rSign}World {\\r\\fscx120\\blur2\\b1}bold"),
                 QStringLiteral("Hello World bold"));
        QCOMPARE(assTextToPlain("a\\hb\\nc{\\pos(1,2)\\move(1,2,3,4)}d"), QStringLiteral("a b\ncd"));
        // \p0으로 그리기 모드가 끝나면 글자가 다시 보임, \pos는 그리기 태그가 아님
        QCOMPARE(assTextToPlain("{\\pos(10,10)\\p2}m 0 0 l 1 1{\\p0}after"), QStringLiteral("after"));
        QCOMPARE(assTextToPlain("{\\p1}m 0 0 l 100 0"), QString());
    }
    void assBlockToPlain()
    {
        QCOMPARE(subtitles::assBlockToPlain("7,0,Sign,,0,0,0,,{\\an5}Center, with comma"),
                 QStringLiteral("Center, with comma"));
        QCOMPARE(subtitles::assBlockToPlain("broken"), QString());
    }
    void legacySsa()
    {
        const QString ssa = "[Script Info]\nPlayResY: 480\n[V4 Styles]\n"
                            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, TertiaryColour, BackColour, "
                            "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding\n"
                            "Style: Default,Arial,24,16777215,65535,65535,-2147483640,-1,0,1,2,0,6,30,30,10,0,0\n"
                            "[Events]\n"
                            "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                            "Dialogue: Marked=0,0:00:00.00,0:00:02.00,Default,,0000,0000,0000,,{\\a1}Old style\n";
        QCOMPARE(parseAssToEvents(ssa), (SubtitleEvents{ev(0, 2000, "Old style")}));
        QCOMPARE(assTimeToMs("1:02:03.45"), 3723450);
        QCOMPARE(assTimeToMs("0:00:01.5"), 1500);
        QCOMPARE(assTimeToMs("junk"), 0);
    }
    void assWithoutFormatLineAndCrlf()
    {
        const QString c = "[Events]\r\nDialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,B\r\n"
                          "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,A\r\n"
                          "Dialogue: 0,0:00:05.00,0:00:05.00,Default,,0,0,0,,zero\r\n";
        QCOMPARE(parseAssToEvents(c), (SubtitleEvents{ev(1000, 2000, "A"), ev(3000, 4000, "B")}));
    }
    void parseFileByExtension()
    {
        const QString p = writeBytes("x.ass", kScript);
        QVERIFY(parseSubtitleFileEvents(p).first().text.startsWith("Hello bold"));
        QVERIFY(parseSubtitleFileEvents(m_dir + "/missing.srt").isEmpty());
    }

    void encodings()
    {
        auto check = [&](const QByteArray &raw, const QString &text, const char *enc) {
            const SubtitleText t = readSubtitleText(writeBytes("enc.srt", raw));
            QVERIFY(t.ok);
            QCOMPARE(t.content, text);
            QCOMPARE(t.encoding, QString::fromLatin1(enc));
        };
        // 기대값은 파이썬 read_subtitle_text의 실제 결과
        check(QByteArray::fromHex("efbbbf68690d0a7468657265"), "hi\nthere", "utf-8-sig");
        check(QByteArray::fromHex("bec8b3e7208c63b9e6b0a2c7cf"), QStringLiteral("안녕 똠방각하"), "cp949");
        check(QByteArray::fromHex("fffe61006200"), "ab", "utf-16");
        check(QByteArray::fromHex("feff00610062"), "ab", "utf-16");
        check(QByteArray::fromHex("636166e921"), QStringLiteral("café!"), "latin-1");
        check(QByteArray::fromHex("636166e9"), QStringLiteral("café"), "latin-1");
        check("a\rb", "a\nb", "utf-8-sig");
        QVERIFY(!readSubtitleText(m_dir + "/nope.srt").ok);
    }

    void labelAndColor()
    {
        QVERIFY(subtitleLabel("/x/movie.ko.srt").contains(QStringLiteral("한국어")));
        QVERIFY(subtitleLabel("/x/movie.en.srt").contains(QStringLiteral("영어")));
        QCOMPARE(subtitleLabel("/x/movie.ko.srt"), QStringLiteral("🇰🇷 한국어 (movie.ko.srt)"));
        QCOMPARE(subtitleLabel("/x/movie.srt"), QStringLiteral("📄 movie.srt"));
        QCOMPARE(subtitleLabel("/x/movie.jpn.ass"), QStringLiteral("🇯🇵 일본어 (movie.jpn.ass)"));
        QCOMPARE(subtitleColor("/x/movie.ko.srt"), languageColor("ko"));
        QCOMPARE(subtitleColor("/x/movie.ko.srt"), QStringLiteral("#FFFFFF"));
        QCOMPARE(subtitleColor("/x/movie.zh-tw.srt"), QStringLiteral("#64D2FF"));
        QCOMPARE(subtitleColor("/x/movie.rus.srt"), QStringLiteral("#FF8A80"));
        QCOMPARE(subtitleColor("/x/movie.srt", 1), kFallbackPalette[1]);
        QCOMPARE(subtitleColor("/x/movie.srt", 7), kFallbackPalette[1]);
    }
    void aiLabelAndColor()
    {
        QCOMPARE(subtitleLabel("/x/movie.ai.en.srt"), QStringLiteral("🤖 AI 영어 (movie.ai.en.srt)"));
        QVERIFY(subtitleLabel("/x/movie.ai.ko.srt").startsWith(QStringLiteral("🤖 AI 한국어")));
        QCOMPARE(subtitleColor("/x/movie.ai.en.srt"), kAiSubtitleColor);
        QCOMPARE(subtitleLabel("/x/movie.ai.auto.srt"), QStringLiteral("🤖 AI 자막 (movie.ai.auto.srt)"));
        QVERIFY(isAiSubtitle("/x/Movie.AI.en.srt"));
        QVERIFY(!isAiSubtitle("/x.ai.d/movie.srt"));
    }
    void stripMarkupTest()
    {
        QCOMPARE(stripMarkup("<i>Hello</i> &amp; <span foreground='red'>bye</span>"), QStringLiteral("Hello & bye"));
        QCOMPARE(stripMarkup("plain"), QStringLiteral("plain"));
        QCOMPARE(stripMarkup(" &#65;&#x42;&nbsp;"), QStringLiteral("AB"));
    }

    void cachedStemMatchesPython()
    {
        // 기대값은 파이썬 hashlib.sha1(폴더).hexdigest()[:8] — 기존 캐시 파일 이름과 같아야 함
        QCOMPARE(cachedAiSubtitleStem("/x/movie.mkv"), QStringLiteral("movie.629e2b1d"));
        QCOMPARE(cachedAiSubtitleStem(QStringLiteral("/home/사용자/영상/드라마 1화.mkv")),
                 QStringLiteral("드라마 1화.c8888e09"));
    }
    void findCachedAi()
    {
        const QString video = m_dir + "/Movie.mkv";
        const QString cache = m_dir + "/cache";
        QDir().mkpath(cache);
        const QString stem = cachedAiSubtitleStem(video);
        touch({stem + ".ai.ko.srt", "Movie.ai.en.srt", "Movie.en.srt", stem + ".txt", "Other.ai.ko.srt"}, cache);
        QStringList expected{"Movie.ai.en.srt", stem + ".ai.ko.srt"};
        std::sort(expected.begin(), expected.end()); // 파이썬처럼 이름 순
        QCOMPARE(baseNames(findCachedAiSubtitles(video, cache)), expected);
        QVERIFY(findCachedAiSubtitles(video, m_dir + "/none").isEmpty());
        // 기본 위치는 (가짜) HOME 아래 ~/.cache/jetson_video_player/ai_subtitles
        const QString def = m_home.path() + "/.cache/jetson_video_player/ai_subtitles";
        QDir().mkpath(def);
        touch({stem + ".ai.ja.srt"}, def);
        QCOMPARE(findCachedAiSubtitles(video), (QStringList{def + "/" + stem + ".ai.ja.srt"}));
        // findAllMatchingSubtitles에도 포함
        touch({"Movie.mkv"});
        QCOMPARE(baseNames(findAllMatchingSubtitles(video)), (QStringList{stem + ".ai.ja.srt"}));
        QFile::remove(def + "/" + stem + ".ai.ja.srt");
    }

    void findAllMatching()
    {
        touch({"Movie.mkv", "Movie.en.srt", "Movie.ko.srt", "Other.srt", "Movie.smi"});
        const QStringList found = baseNames(findAllMatchingSubtitles(m_dir + "/Movie.mkv"));
        QVERIFY(!found.contains("Other.srt"));
        QCOMPARE(found.first(), QStringLiteral("Movie.ko.srt"));
        QCOMPARE(QSet<QString>(found.begin(), found.end()), (QSet<QString>{"Movie.en.srt", "Movie.ko.srt", "Movie.smi"}));
    }
    void otherVideosAiSubtitleIsNotBorrowed()
    {
        touch({"a.mp4", "b.mp4", "a.ai.en.srt"});
        QVERIFY(findAllMatchingSubtitles(m_dir + "/b.mp4").isEmpty());
        QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/a.mp4")), QStringList{"a.ai.en.srt"});
    }
    void prefixNamedVideos()
    {
        touch({"ep1.mkv", "ep10.mkv", "ep1.ko.srt", "ep10.ko.srt"});
        QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/ep1.mkv")), QStringList{"ep1.ko.srt"});
        QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/ep10.mkv")), QStringList{"ep10.ko.srt"});
    }
    void orphanFallback()
    {
        touch({"movie_h265.mp4", "movie.ko.srt"});
        QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/movie_h265.mp4")), QStringList{"movie.ko.srt"});
        touch({"other.mp4", "other.en.srt"});
        QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/movie_h265.mp4")), QStringList{"movie.ko.srt"});
    }
    void ownerPrefersPrefixOverSubstring()
    {
        touch({"a.mkv", "b.mkv", "a.ko.srt", "b.ai.ko.srt"});
        for (int i = 0; i < 5; ++i) {
            QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/a.mkv")), QStringList{"a.ko.srt"});
            QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/b.mkv")), QStringList{"b.ai.ko.srt"});
        }
    }
    void sortOrderKoEnJa()
    {
        touch({"v.mkv", "v.zh.srt", "v.ja.srt", "v.en.srt", "v.ko.srt", "v.srt"});
        QCOMPARE(baseNames(findAllMatchingSubtitles(m_dir + "/v.mkv")),
                 (QStringList{"v.ko.srt", "v.en.srt", "v.ja.srt", "v.srt", "v.zh.srt"}));
    }
};

QTEST_GUILESS_MAIN(TestSubtitleParse)
#include "test_subtitle_parse.moc"
