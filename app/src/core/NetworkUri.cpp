#include "NetworkUri.h"

#include "Library.h"

#include <QDir>
#include <QSet>
#include <QUrl>
#include <QVariantMap>

#include <unistd.h>

namespace jvp::network {

namespace {

struct UrlParts {
    QString scheme, netloc, path;
};

// urllib.parse.urlsplit과 같은 규칙으로 나눕니다 (QUrl은 잘못된 주소를 고치거나 거부해 결과가 달라짐)
UrlParts urlSplit(QString url)
{
    UrlParts p;
    const int colon = url.indexOf(QLatin1Char(':'));
    if (colon > 0 && url.at(0).unicode() < 128 && url.at(0).isLetter()) {
        bool valid = true;
        for (int i = 0; i < colon && valid; ++i) {
            const QChar c = url.at(i);
            valid = c.unicode() < 128 && (c.isLetterOrNumber() || c == QLatin1Char('+') || c == QLatin1Char('-')
                                          || c == QLatin1Char('.'));
        }
        if (valid) {
            p.scheme = url.left(colon).toLower();
            url = url.mid(colon + 1);
        }
    }
    if (url.startsWith(QLatin1String("//"))) {
        int end = url.size();
        for (QChar c : {QLatin1Char('/'), QLatin1Char('?'), QLatin1Char('#')}) {
            const int i = url.indexOf(c, 2);
            if (i >= 0)
                end = std::min(end, i);
        }
        p.netloc = url.mid(2, end - 2);
        url = url.mid(end);
    }
    for (QChar c : {QLatin1Char('#'), QLatin1Char('?')}) {
        const int i = url.indexOf(c);
        if (i >= 0)
            url.truncate(i);
    }
    p.path = url;
    return p;
}

// SplitResult.hostname: 사용자 정보·포트를 떼고 소문자
QString hostname(const QString &netloc)
{
    QString host = netloc.mid(netloc.lastIndexOf(QLatin1Char('@')) + 1);
    if (host.startsWith(QLatin1Char('['))) {
        const int close = host.indexOf(QLatin1Char(']'));
        host = host.mid(1, close < 0 ? -1 : close - 1);
    } else {
        const int colon = host.indexOf(QLatin1Char(':'));
        if (colon >= 0)
            host.truncate(colon);
    }
    return host.toLower();
}

QString strip(const QString &s, QChar c, bool left, bool right)
{
    int b = 0, e = s.size();
    while (left && b < e && s.at(b) == c)
        ++b;
    while (right && e > b && s.at(e - 1) == c)
        --e;
    return s.mid(b, e - b);
}

QVariantMap makeLocation(const QString &uri, const QString &path, const QString &name)
{
    return {{QStringLiteral("uri"), uri}, {QStringLiteral("path"), path}, {QStringLiteral("name"), name}};
}

bool isString(const QVariant &v) { return v.metaType().id() == QMetaType::QString; }

} // namespace

const QStringList &networkSchemes()
{
    static const QStringList s = {"smb", "nfs", "sftp", "ftp", "ftps", "dav", "davs", "afp"};
    return s;
}

QString gvfsRoot()
{
    QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    if (runtime.isEmpty())
        runtime = QStringLiteral("/run/user/%1").arg(::getuid());
    return QDir::cleanPath(runtime + QStringLiteral("/gvfs"));
}

bool isGvfsPath(const QString &path)
{
    return !path.isEmpty() && library::absPath(path).startsWith(gvfsRoot() + QLatin1Char('/'));
}

bool isNetworkUri(const QString &text) { return networkSchemes().contains(urlSplit(text.trimmed()).scheme); }

QString normalizeUri(const QString &input)
{
    QString text = input.trimmed();
    if (text.startsWith(QLatin1String("\\\\")))
        text = QStringLiteral("smb://") + strip(text, QLatin1Char('\\'), true, false).replace(QLatin1Char('\\'), QLatin1Char('/'));
    const int sep = text.indexOf(QLatin1String("://"));
    if (sep >= 0)
        text = text.left(sep).toLower() + QStringLiteral("://") + strip(text.mid(sep + 3), QLatin1Char('/'), false, true);
    return text;
}

QString displayName(const QString &uri)
{
    const UrlParts p = urlSplit(uri);
    const QString path = strip(QUrl::fromPercentEncoding(p.path.toUtf8()), QLatin1Char('/'), true, true);
    const QString name = strip(hostname(p.netloc) + QLatin1Char('/') + path, QLatin1Char('/'), false, true);
    return name.isEmpty() ? uri : name;
}

QVariantList cleanLocations(const QVariant &value)
{
    if (value.metaType().id() != QMetaType::QVariantList)
        return {};
    QVariantList result;
    QSet<QString> seen;
    for (const QVariant &item : value.toList()) {
        if (item.metaType().id() != QMetaType::QVariantMap)
            continue;
        const QVariantMap m = item.toMap();
        const QVariant uri = m.value(QStringLiteral("uri")), path = m.value(QStringLiteral("path"));
        if (!(isString(uri) && isString(path) && isNetworkUri(uri.toString())) || seen.contains(uri.toString()))
            continue;
        seen.insert(uri.toString());
        const QVariant name = m.value(QStringLiteral("name"));
        result << makeLocation(uri.toString(), path.toString(),
                               isString(name) ? name.toString() : displayName(uri.toString()));
    }
    return result.mid(0, kMaxLocations);
}

QVariantList rememberLocation(const QVariantList &locations, const QString &uri, const QString &path)
{
    QVariantList result{makeLocation(uri, library::absPath(path), displayName(uri))};
    QVariantList rest;
    for (const QVariant &loc : cleanLocations(locations))
        if (loc.toMap().value(QStringLiteral("uri")).toString() != uri)
            rest << loc;
    return result + rest.mid(0, kMaxLocations - 1);
}

QString uriForPath(const QVariantList &locations, const QString &pathIn)
{
    const QString path = library::absPath(pathIn);
    QVariantMap best;
    for (const QVariant &v : cleanLocations(locations)) {
        const QVariantMap loc = v.toMap();
        const QString root = loc.value(QStringLiteral("path")).toString();
        if (path == root || path.startsWith(strip(root, QLatin1Char('/'), false, true) + QLatin1Char('/'))) {
            if (best.isEmpty() || root.size() > best.value(QStringLiteral("path")).toString().size())
                best = loc;
        }
    }
    if (best.isEmpty())
        return {};
    const QString bestUri = best.value(QStringLiteral("uri")).toString();
    const QString rel = QDir(best.value(QStringLiteral("path")).toString()).relativeFilePath(path);
    if (rel == QLatin1String(".") || rel.isEmpty())
        return bestUri;
    QStringList parts;
    for (const QString &part : rel.split(QLatin1Char('/')))
        parts << QString::fromLatin1(QUrl::toPercentEncoding(part));   // quote(): 영숫자와 -._~ 만 그대로
    return strip(bestUri, QLatin1Char('/'), false, true) + QLatin1Char('/') + parts.join(QLatin1Char('/'));
}

} // namespace jvp::network
