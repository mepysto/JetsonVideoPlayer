#include "Library.h"

#include "JsonFile.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QRegularExpression>
#include <QSet>
#include <QStringDecoder>
#include <QUrl>
#include <algorithm>

#include <glib.h>
#include <sys/stat.h>

namespace jvp::library {

namespace {

// os.stat()의 st_mtime/st_size (없으면 0). 초 단위 소수까지 파이썬과 같은 식으로 계산합니다.
bool statFile(const QString &path, double *mtime, qint64 *size)
{
    struct stat st {};
    if (::stat(QFile::encodeName(path).constData(), &st) != 0)
        return false;
    if (mtime)
        *mtime = double(st.st_mtim.tv_sec) + double(st.st_mtim.tv_nsec) * 1e-9;
    if (size)
        *size = st.st_size;
    return true;
}

// 파이썬 splitext 규칙: 마지막 구성 요소에서, 맨 앞의 점들은 확장자로 보지 않습니다 (".bashrc" → 확장자 없음)
int extensionIndex(const QString &path)
{
    const int sep = path.lastIndexOf(QLatin1Char('/'));
    const int dot = path.lastIndexOf(QLatin1Char('.'));
    if (dot <= sep)
        return -1;
    for (int i = sep + 1; i < dot; ++i)
        if (path.at(i) != QLatin1Char('.'))
            return dot;
    return -1;
}

QString baseName(const QString &path) { return path.mid(path.lastIndexOf(QLatin1Char('/')) + 1); }

QString joinPath(const QString &a, const QString &b)
{
    if (b.startsWith(QLatin1Char('/')))
        return b;
    if (a.isEmpty() || a.endsWith(QLatin1Char('/')))
        return a + b;
    return a + QLatin1Char('/') + b;
}

void walk(const QString &root, QStringList &found, QSet<QString> &visited)
{
    // followlinks=True에서 링크가 상위 폴더를 가리키면 끝없이 돌 수 있어, 지금 내려가는 경로의
    // 조상(실제 경로 기준)과 같은 폴더는 다시 들어가지 않습니다. 서로 다른 링크로 같은 폴더를 보는 건 허용 (파이썬과 같음)
    const QString canonical = QFileInfo(root).canonicalFilePath();
    if (canonical.isEmpty() || visited.contains(canonical))
        return;
    visited.insert(canonical);
    struct Leave {
        QSet<QString> &set;
        QString key;
        ~Leave() { set.remove(key); }
    } leave{visited, canonical};

    const QStringList names = QDir(root).entryList(QDir::AllEntries | QDir::Hidden | QDir::System | QDir::NoDotAndDotDot,
                                                   QDir::NoSort);
    QStringList dirs, files;
    for (const QString &name : names) {
        const QFileInfo fi(joinPath(root, name));
        if (fi.isDir())
            dirs << name;
        else
            files << name;
    }
    std::sort(files.begin(), files.end());
    for (const QString &name : std::as_const(files)) {
        if (name.startsWith(QLatin1Char('.')))
            continue;
        if (videoExts().contains(extensionLower(name))) {
            const QString full = joinPath(root, name);
            if (isFile(full))
                found << full;
        }
    }
    std::sort(dirs.begin(), dirs.end());
    for (const QString &name : std::as_const(dirs)) {
        if (name == QLatin1String("unsupported_originals") || name.startsWith(QLatin1Char('.')))
            continue;
        walk(joinPath(root, name), found, visited);
    }
}

} // namespace

QString absPath(const QString &path)
{
    const QString p = path.startsWith(QLatin1Char('/')) ? path : joinPath(QDir::currentPath(), path);
    return QDir::cleanPath(p);
}

QString extensionLower(const QString &path)
{
    const int i = extensionIndex(path);
    return i < 0 ? QString() : path.mid(i).toLower();
}

QString stem(const QString &fileName)
{
    const QString name = baseName(fileName);
    const int i = extensionIndex(name);
    return i < 0 ? name : name.left(i);
}

bool pathExists(const QString &path)
{
    struct stat st {};
    return !path.isEmpty() && ::stat(QFile::encodeName(path).constData(), &st) == 0;
}

bool isFile(const QString &path)
{
    struct stat st {};
    return !path.isEmpty() && ::stat(QFile::encodeName(path).constData(), &st) == 0 && S_ISREG(st.st_mode);
}

const QStringList &videoExts()
{
    static const QStringList exts = {".webm", ".mp4", ".mkv", ".mov", ".avi", ".ts", ".m4v"};
    return exts;
}

bool isVideoFile(const QString &path) { return videoExts().contains(extensionLower(path)); }

QStringList scanVideoFiles(const QString &dirPath)
{
    QStringList found;
    QSet<QString> visited;
    if (QFileInfo(dirPath).isDir())
        walk(dirPath, found, visited);
    std::sort(found.begin(), found.end());
    return found;
}

QStringList sortVideoPaths(const QStringList &paths, const QString &mode)
{
    QStringList out = paths;
    if (mode == QLatin1String("mtime") || mode == QLatin1String("size")) {
        const bool byTime = mode == QLatin1String("mtime");
        QHash<QString, double> key;
        for (const QString &p : paths) {
            double mtime = 0;
            qint64 size = 0;
            statFile(p, &mtime, &size);
            key.insert(p, byTime ? mtime : double(size));
        }
        // 큰 값 먼저, 같으면 경로 이름순
        std::sort(out.begin(), out.end(), [&](const QString &a, const QString &b) {
            const double ka = key.value(a), kb = key.value(b);
            return ka != kb ? ka > kb : a < b;
        });
        return out;
    }
    std::sort(out.begin(), out.end());
    return out;
}

QStringList preferH265Versions(const QStringList &paths, const std::function<bool(const QString &)> &exists)
{
    QStringList result;
    QSet<QString> done;
    const QSet<QString> pathSet(paths.begin(), paths.end());
    for (const QString &path : paths) {
        if (done.contains(path) || !exists(path))
            continue;
        const QString s = stem(path);
        QString final = path;
        if (!s.endsWith(QLatin1String("_h265"))) {
            const int slash = path.lastIndexOf(QLatin1Char('/'));
            const QString dir = slash < 0 ? QString() : path.left(slash);
            const QString h265 = joinPath(dir, s + QStringLiteral("_h265.mp4"));
            if (pathSet.contains(h265) || exists(h265)) {
                final = h265;
                done.insert(path);
            }
        }
        if (!result.contains(final)) {
            result << final;
            done.insert(final);
        }
    }
    return result;
}

MergeResult mergeRescanned(const QStringList &playlist, const QString &root, const QStringList &scanned,
                           const QString &current)
{
    const QString absRoot = absPath(root);
    QString prefix = absRoot;
    while (prefix.endsWith(QLatin1Char('/')))
        prefix.chop(1);
    prefix += QLatin1Char('/');
    auto inside = [&](const QString &p) { return p == absRoot || p.startsWith(prefix); };

    const QSet<QString> scannedSet(scanned.begin(), scanned.end());
    MergeResult r;
    r.playlist = scanned;
    for (const QString &p : playlist)
        if (!inside(p) && !scannedSet.contains(p))
            r.playlist << p;
    if (!current.isEmpty() && !r.playlist.contains(current))
        r.playlist << current;
    const QSet<QString> oldSet(playlist.begin(), playlist.end());
    const QSet<QString> newSet(r.playlist.begin(), r.playlist.end());
    for (const QString &p : std::as_const(r.playlist))
        if (!oldSet.contains(p))
            r.added << p;
    for (const QString &p : playlist)
        if (!newSet.contains(p))
            r.removed << p;
    return r;
}

const QStringList &playlistExts()
{
    static const QStringList exts = {".m3u", ".m3u8"};
    return exts;
}

bool isPlaylistFile(const QString &path) { return playlistExts().contains(extensionLower(path)); }

namespace {

QString decodePlaylist(QByteArray raw)
{
    // utf-8-sig: BOM이 있으면 떼고 엄격한 UTF-8로
    QByteArray utf8 = raw;
    if (utf8.startsWith("\xEF\xBB\xBF"))
        utf8.remove(0, 3);
    QStringDecoder dec(QStringDecoder::Utf8, QStringDecoder::Flag::Stateless);
    QString text = dec.decode(utf8);
    if (!dec.hasError())
        return text;
    // 옛 윈도우 재생목록(한국어)은 CP949 — Qt는 ICU 없이 CP949를 모르므로 GLib(iconv)로 변환합니다
    gsize written = 0;
    GError *err = nullptr;
    gchar *conv = g_convert(raw.constData(), raw.size(), "UTF-8", "CP949", nullptr, &written, &err);
    if (conv) {
        text = QString::fromUtf8(conv, qsizetype(written));
        g_free(conv);
        return text;
    }
    g_clear_error(&err);
    return QString::fromLatin1(raw);
}

// urllib.parse.urlsplit(line).path 후 unquote — file://host/path 의 path 부분
QString fileUriPath(const QString &line)
{
    QString rest = line.mid(int(qstrlen("file:")));
    if (rest.startsWith(QLatin1String("//"))) {
        rest = rest.mid(2);
        int end = rest.size();
        for (QChar c : {QLatin1Char('/'), QLatin1Char('?'), QLatin1Char('#')}) {
            const int i = rest.indexOf(c);
            if (i >= 0)
                end = std::min(end, i);
        }
        rest = rest.mid(end);
    }
    for (QChar c : {QLatin1Char('#'), QLatin1Char('?')}) {
        const int i = rest.indexOf(c);
        if (i >= 0)
            rest.truncate(i);
    }
    return QUrl::fromPercentEncoding(rest.toUtf8());
}

} // namespace

M3uResult parseM3u(const QString &path)
{
    M3uResult r;
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return r;
    r.ok = true;
    const QString text = decodePlaylist(f.readAll());
    const QString base = QFileInfo(absPath(path)).path();

    // str.splitlines()와 같은 줄 구분자
    static const QRegularExpression lineSep(QStringLiteral("\r\n|[\n\r\v\f\x1c\x1d\x1e\x85  ]"));
    for (QString line : text.split(lineSep)) {
        line = line.trimmed();
        if (line.isEmpty() || line.startsWith(QLatin1Char('#')))
            continue;
        if (line.startsWith(QLatin1String("file://"))) {
            line = fileUriPath(line);
        } else if (line.contains(QLatin1String("://"))) {
            ++r.skipped;   // 온라인 주소는 지원하지 않음
            continue;
        }
        const QString full = QDir::cleanPath(joinPath(base, line));
        if (isFile(full) && isVideoFile(full)) {
            if (!r.videos.contains(full))
                r.videos << full;
        } else {
            ++r.skipped;
        }
    }
    return r;
}

bool writeM3u(const QStringList &paths, const QString &dest)
{
    const QDir base(QFileInfo(absPath(dest)).path());
    QStringList lines{QStringLiteral("#EXTM3U")};
    for (const QString &raw : paths) {
        const QString p = absPath(raw);
        const QString rel = base.relativeFilePath(p);
        lines << QStringLiteral("#EXTINF:-1,") + stem(p);
        lines << (rel.startsWith(QLatin1String("..")) ? p : rel);
    }
    return json::writeBytesAtomic(dest, (lines.join(QLatin1Char('\n')) + QLatin1Char('\n')).toUtf8());
}

} // namespace jvp::library
