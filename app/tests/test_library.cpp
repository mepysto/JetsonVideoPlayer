// library.py 이식 검증 (tests/test_m3u.py, test_storage_settings.py의 정렬·h265·재스캔, test_subtitles.py의 스캔)
#include "Library.h"

#include <QDir>
#include <QFile>
#include <QSet>
#include <QTemporaryDir>
#include <QUrl>
#include <QTest>

#include <glib.h>
#include <memory>
#include <utime.h>

using namespace jvp::library;

namespace {
void writeFile(const QString &path, const QByteArray &bytes)
{
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Truncate));
    f.write(bytes);
}

QStringList relTo(const QString &base, const QStringList &paths)
{
    QStringList out;
    for (const QString &p : paths)
        out << QDir(base).relativeFilePath(p);
    return out;
}
} // namespace

class TestLibrary : public QObject {
    Q_OBJECT
    std::unique_ptr<QTemporaryDir> m_dir;
    QString p(const QString &name) const { return m_dir->filePath(name); }
    QString root() const { return m_dir->path(); }

private slots:
    void init()
    {
        m_dir = std::make_unique<QTemporaryDir>();
        QVERIFY(m_dir->isValid());
    }

    void pathHelpers()
    {
        QCOMPARE(extensionLower("/a/b.MKV"), QString(".mkv"));
        QCOMPARE(extensionLower("/a.d/noext"), QString());
        QCOMPARE(extensionLower(".hidden"), QString());
        QCOMPARE(extensionLower("a.tar.gz"), QString(".gz"));
        QCOMPARE(stem("/x/a.b.mkv"), QString("a.b"));
        QCOMPARE(stem("/x/.bashrc"), QString(".bashrc"));
        QCOMPARE(absPath("/a/./b/../c/"), QString("/a/c"));
        QCOMPARE(absPath("rel"), QDir::currentPath() + "/rel");
        QVERIFY(isVideoFile("x.M4V") && !isVideoFile("x.srt"));
    }

    void scanVideoFiles_()
    {
        writeFile(p("b.mp4"), "");
        writeFile(p("A.MKV"), "");
        writeFile(p("note.txt"), "x");
        writeFile(p(".hidden.mp4"), "");
        QDir(root()).mkpath("season1");
        writeFile(p("season1/ep1.webm"), "");
        QDir(root()).mkpath("unsupported_originals");
        writeFile(p("unsupported_originals/old.avi"), "");
        QDir(root()).mkpath(".secret");
        writeFile(p(".secret/x.mp4"), "");
        QCOMPARE(relTo(root(), scanVideoFiles(root())), (QStringList{"A.MKV", "b.mp4", "season1/ep1.webm"}));
    }

    void scanVideoFilesEmptyAndLinks()
    {
        QVERIFY(scanVideoFiles(root()).isEmpty());
        QVERIFY(scanVideoFiles(p("missing")).isEmpty());
        // 링크를 따라가되, 상위 폴더를 가리키는 링크로 끝없이 돌지 않아야 함
        QDir(root()).mkpath("real");
        writeFile(p("real/v.mkv"), "");
        QVERIFY(QFile::link(p("real"), p("linked")));
        QVERIFY(QFile::link(root(), p("real/loop")));
        QVERIFY(QFile::link(p("nowhere.mp4"), p("broken.mp4")));
        const QStringList found = relTo(root(), scanVideoFiles(root()));
        QCOMPARE(found, (QStringList{"linked/v.mkv", "real/v.mkv"}));
        QVERIFY(!found.contains("broken.mp4"));
    }

    void sortVideoPaths_()
    {
        writeFile(p("a.mp4"), QByteArray(10, 'x'));
        writeFile(p("b.mp4"), QByteArray(30, 'x'));
        writeFile(p("c.mp4"), QByteArray(20, 'x'));
        auto setTime = [](const QString &f, time_t mtime) {
            struct utimbuf t {1000, mtime};
            QCOMPARE(::utime(QFile::encodeName(f).constData(), &t), 0);
        };
        setTime(p("a.mp4"), 3000);
        setTime(p("b.mp4"), 1000);
        setTime(p("c.mp4"), 2000);
        const QStringList paths{p("c.mp4"), p("a.mp4"), p("b.mp4")};
        auto names = [](const QStringList &ps) {
            QStringList out;
            for (const QString &x : ps)
                out << x.section('/', -1);
            return out;
        };
        QCOMPARE(names(sortVideoPaths(paths, "name")), (QStringList{"a.mp4", "b.mp4", "c.mp4"}));
        QCOMPARE(names(sortVideoPaths(paths, "mtime")), (QStringList{"a.mp4", "c.mp4", "b.mp4"}));
        QCOMPARE(names(sortVideoPaths(paths, "size")), (QStringList{"b.mp4", "c.mp4", "a.mp4"}));
        QCOMPARE(names(sortVideoPaths(paths + QStringList{p("gone.mp4")}, "size")).last(), QString("gone.mp4"));
    }

    void preferH265Versions_()
    {
        for (const char *n : {"a.mkv", "a_h265.mp4", "b.mkv"})
            writeFile(p(n), "x");
        const QStringList paths{p("a.mkv"), p("a_h265.mp4"), p("b.mkv"), p("gone.mkv")};
        QCOMPARE(relTo(root(), preferH265Versions(paths)), (QStringList{"a_h265.mp4", "b.mkv"}));
        // exists를 바꿔 넣을 수 있음: 목록에 있는 변환본이면 파일 확인 없이도 교체
        const auto always = [](const QString &) { return true; };
        QCOMPARE(preferH265Versions({"/v/x.mkv", "/v/x_h265.mp4", "/v/x.mkv"}, always), (QStringList{"/v/x_h265.mp4"}));
    }

    void mergeRescannedKeepsOutsideItemsAndCurrent()
    {
        const QStringList playlist{"/v/a.mkv", "/v/b.mkv", "/yt/clip.mp4", "/v/sub/c.mkv"};
        MergeResult r = mergeRescanned(playlist, "/v", {"/v/a.mkv", "/v/sub/c.mkv", "/v/d.mkv"}, "/v/b.mkv");
        QCOMPARE(QSet<QString>(r.playlist.begin(), r.playlist.end()),
                 (QSet<QString>{"/v/a.mkv", "/v/sub/c.mkv", "/v/d.mkv", "/yt/clip.mp4", "/v/b.mkv"}));   // b는 재생 중
        QCOMPARE(r.added, QStringList{"/v/d.mkv"});
        QVERIFY(r.removed.isEmpty());
        r = mergeRescanned(playlist, "/v", {"/v/a.mkv"}, "/v/a.mkv");
        QCOMPARE(r.removed, (QStringList{"/v/b.mkv", "/v/sub/c.mkv"}));
        QVERIFY(r.playlist.contains("/yt/clip.mp4"));
        QCOMPARE(mergeRescanned({"/vv/x.mkv"}, "/v", {}).playlist, QStringList{"/vv/x.mkv"});   // /vv는 /v 밖
        QCOMPARE(mergeRescanned({"/v/x.mkv"}, "/v/", {}).playlist, QStringList());               // 끝의 / 무관
    }

    void parseM3uRelativeAbsoluteAndSkips()
    {
        QDir(root()).mkpath("shows");
        writeFile(p("a.mkv"), "x");
        writeFile(p("shows/b 1.mp4"), "x");
        writeFile(p("elsewhere.mkv"), "x");
        writeFile(p("notes.txt"), "x");
        const QString text = QString("#EXTM3U\n#EXTINF:-1,A\na.mkv\n\nshows/b 1.mp4\r\n%1\nfile://%2/a.mkv\n"
                                     "https://example.com/x.mp4\nmissing.mkv\nnotes.txt\n")
                                 .arg(p("elsewhere.mkv"), root());
        writeFile(p("list.m3u8"), text.toUtf8());
        const M3uResult r = parseM3u(p("list.m3u8"));
        QVERIFY(r.ok);
        QCOMPARE(relTo(root(), r.videos), (QStringList{"a.mkv", "shows/b 1.mp4", "elsewhere.mkv"}));
        QCOMPARE(r.skipped, 3);
    }

    void parseM3uFileUriPercentAndBom()
    {
        writeFile(p("드라마 1.mkv"), "x");
        const QByteArray line = "file://" + QUrl::toPercentEncoding(p("드라마 1.mkv"), "/") + "\n";
        writeFile(p("u.m3u8"), "\xEF\xBB\xBF" + line);
        QCOMPARE(parseM3u(p("u.m3u8")).videos, QStringList{p("드라마 1.mkv")});
    }

    void parseM3uCp949()
    {
        writeFile(p("드라마.mkv"), "x");
        const QByteArray utf8 = QString("드라마.mkv\n").toUtf8();
        gsize written = 0;
        gchar *cp = g_convert(utf8.constData(), utf8.size(), "CP949", "UTF-8", nullptr, &written, nullptr);
        if (!cp)
            QSKIP("iconv에 CP949가 없습니다");
        writeFile(p("old.m3u"), QByteArray(cp, qsizetype(written)));
        g_free(cp);
        QCOMPARE(parseM3u(p("old.m3u")).videos, QStringList{p("드라마.mkv")});
    }

    void parseM3uMissingFile()
    {
        const M3uResult r = parseM3u(p("nope.m3u"));
        QVERIFY(!r.ok);
        QVERIFY(r.videos.isEmpty());
    }

    void writeThenParseRoundTrip()
    {
        QDir(root()).mkpath("sub");
        const QStringList paths{p("sub/x.mkv"), p("y.mp4")};
        for (const QString &x : paths)
            writeFile(x, "x");
        const QString dest = p("sub/saved.m3u8");
        QVERIFY(writeM3u(paths, dest));
        QFile f(dest);
        QVERIFY(f.open(QIODevice::ReadOnly));
        const QString text = QString::fromUtf8(f.readAll());
        QVERIFY(text.startsWith("#EXTM3U"));
        QVERIFY(text.contains("\n#EXTINF:-1,x\nx.mkv\n"));
        QVERIFY(text.contains(paths[1]));   // 밖은 절대 경로
        const M3uResult r = parseM3u(dest);
        QCOMPARE(r.videos, paths);
        QCOMPARE(r.skipped, 0);
        QVERIFY(isPlaylistFile("a.M3U8") && isPlaylistFile("b.m3u") && !isPlaylistFile("a.mkv"));
    }
};

QTEST_GUILESS_MAIN(TestLibrary)
#include "test_library.moc"
