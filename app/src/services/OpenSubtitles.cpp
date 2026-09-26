#include "OpenSubtitles.h"

#include "Paths.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFutureWatcher>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLoggingCategory>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QRegularExpression>
#include <QSaveFile>
#include <QtConcurrent/QtConcurrentRun>

#include <algorithm>

Q_LOGGING_CATEGORY(lcOpenSubs, "jvp.opensubtitles")

namespace jvp::opensubtitles {

namespace {
qint64 jsonInt(const QJsonValue &v)
{
    if (v.isString())
        return v.toString().toLongLong();
    return v.toInteger(qint64(v.toDouble()));
}

// os.path.splitext(basename)[0]
QString stemOf(const QString &path)
{
    const QString base = QFileInfo(path).fileName();
    int lead = 0;
    while (lead < base.size() && base[lead] == QLatin1Char('.'))
        ++lead;
    const int dot = base.lastIndexOf(QLatin1Char('.'));
    return dot > lead ? base.left(dot) : base;
}

// 파이썬 str.strip(" -")
QString stripChars(QString s, const QString &chars)
{
    while (!s.isEmpty() && chars.contains(s.front()))
        s.remove(0, 1);
    while (!s.isEmpty() && chars.contains(s.back()))
        s.chop(1);
    return s;
}
} // namespace

QString moviehash(const QString &path, QString *error)
{
    QFile f(path);
    const qint64 size = QFileInfo(path).size();
    auto fail = [&](const QString &msg) {
        if (error)
            *error = msg;
        return QString();
    };
    if (!f.open(QIODevice::ReadOnly))
        return fail(f.errorString());
    if (size < kHashChunk * 2)
        return fail(QStringLiteral("파일이 너무 작습니다"));
    quint64 total = quint64(size);
    for (qint64 offset : {qint64(0), size - kHashChunk}) {
        if (!f.seek(offset))
            return fail(f.errorString());
        const QByteArray chunk = f.read(kHashChunk);
        if (chunk.size() != kHashChunk)
            return fail(QStringLiteral("읽기 실패"));
        const auto *p = reinterpret_cast<const uchar *>(chunk.constData());
        for (qint64 i = 0; i < kHashChunk; i += 8) {
            quint64 w = 0;
            for (int b = 7; b >= 0; --b)
                w = (w << 8) | p[i + b];   // 리틀 엔디언
            total += w;                     // 64비트에서 자연스럽게 넘침 (& 0xFFFFFFFFFFFFFFFF)
        }
    }
    return QStringLiteral("%1").arg(total, 16, 16, QLatin1Char('0'));
}

QString queryFromFilename(const QString &path)
{
    static const QRegularExpression brackets(QStringLiteral(R"([\[\(][^\]\)]*[\]\)])"));
    static const QRegularExpression seps(QStringLiteral("[._]+"));
    static const QRegularExpression tags(
        QStringLiteral(R"(\b(?:480p|720p|1080p|2160p|4k|x264|x265|h264|h265|hevc|web-?dl|webrip|bluray|brrip|hdtv|aac|ddp?5|remux)\b)"),
        QRegularExpression::CaseInsensitiveOption | QRegularExpression::UseUnicodePropertiesOption);
    static const QRegularExpression spaces(QStringLiteral("\\s+"), QRegularExpression::UseUnicodePropertiesOption);
    QString stem = stemOf(path);
    stem.replace(brackets, QStringLiteral(" "));
    stem.replace(seps, QStringLiteral(" "));
    const auto m = tags.match(stem);
    if (m.hasMatch())
        stem = stem.left(m.capturedStart());
    stem.replace(spaces, QStringLiteral(" "));
    return stripChars(stem, QStringLiteral(" -"));
}

QString credentialsFile() { return paths::configDir() + QStringLiteral("/opensubtitles.json"); }

QMap<QString, QString> loadCredentials(const QString &path)
{
    QMap<QString, QString> creds;
    QFile f(path);
    if (f.open(QIODevice::ReadOnly)) {
        const QJsonDocument doc = QJsonDocument::fromJson(f.readAll());
        if (doc.isObject()) {
            const QJsonObject o = doc.object();
            for (auto it = o.begin(); it != o.end(); ++it)
                if (it.value().isString())
                    creds.insert(it.key(), it.value().toString());
        }
    }
    const QString env = qEnvironmentVariable("JVP_OPENSUBTITLES_KEY");
    if (!env.isEmpty())
        creds.insert(QStringLiteral("api_key"), env);
    return creds;
}

bool saveCredentials(const QMap<QString, QString> &creds, const QString &path)
{
    QDir().mkpath(QFileInfo(path).absolutePath());
    QJsonObject o;
    for (auto it = creds.begin(); it != creds.end(); ++it)
        if (!it.value().isEmpty())
            o.insert(it.key(), it.value());
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly))
        return false;
    // 임시 파일 단계에서 600으로 — 비밀번호가 잠시라도 다른 사용자에게 보이지 않게
    f.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);
    f.write(QJsonDocument(o).toJson(QJsonDocument::Indented));
    return f.commit();
}

QList<SubtitleResult> parseSearchResults(const QByteArray &json)
{
    QList<SubtitleResult> results;
    for (const QJsonValue &item : QJsonDocument::fromJson(json).object().value("data").toArray()) {
        const QJsonObject attrs = item.toObject().value("attributes").toObject();
        const QJsonArray files = attrs.value("files").toArray();
        if (files.isEmpty())
            continue;
        const QJsonObject file0 = files.first().toObject();
        const qint64 fileId = jsonInt(file0.value("file_id"));
        if (!fileId)
            continue;
        const QJsonObject details = attrs.value("feature_details").toObject();
        QString title = details.value("title").toString();
        if (title.isEmpty())
            title = details.value("movie_name").toString();
        const qint64 year = jsonInt(details.value("year"));
        if (year)
            title = QStringLiteral("%1 (%2)").arg(title).arg(year);
        SubtitleResult r;
        r.fileId = fileId;
        r.language = attrs.value("language").toString();
        if (r.language.isEmpty())
            r.language = QStringLiteral("?");
        r.fileName = file0.value("file_name").toString();
        r.release = attrs.value("release").toString();
        if (r.release.isEmpty())
            r.release = r.fileName;
        r.downloads = int(jsonInt(attrs.value("download_count")));
        r.hashMatch = attrs.value("moviehash_match").toBool();
        r.title = title;
        results.append(r);
    }
    std::stable_sort(results.begin(), results.end(), [](const SubtitleResult &a, const SubtitleResult &b) {
        if (a.hashMatch != b.hashMatch)
            return a.hashMatch;
        return a.downloads > b.downloads;
    });
    return results;
}

QString subtitleSavePath(const QString &videoPath, const QString &language, const QString &contentName)
{
    static const QStringList exts{".srt", ".ass", ".ssa", ".vtt", ".smi", ".sub"};
    const QString base = QFileInfo(contentName).fileName();
    const int dot = base.lastIndexOf('.');
    QString ext = dot > 0 ? base.mid(dot).toLower() : QString();
    if (!exts.contains(ext))
        ext = QStringLiteral(".srt");
    // os.path.splitext(video_path)[0]: 폴더는 그대로, 파일 이름의 마지막 확장자만 뗍니다.
    const QString videoBase = QFileInfo(videoPath).fileName();
    const QString stem = videoPath.left(videoPath.size() - videoBase.size()) + stemOf(videoPath);
    static const QRegularExpression notLang(QStringLiteral("[^a-z-]"));
    QString lang = language.toLower().remove(notLang).left(5);
    if (lang.isEmpty())
        lang = QStringLiteral("sub");
    return QStringLiteral("%1.%2%3").arg(stem, lang, ext);
}

QByteArray urlEncode(const QList<QPair<QString, QString>> &params)
{
    QByteArrayList parts;
    for (const auto &p : params)
        parts << p.first.toUtf8().toPercentEncoding(" ").replace(' ', '+') + '='
                     + p.second.toUtf8().toPercentEncoding(" ").replace(' ', '+');
    // toPercentEncoding은 영숫자와 -._~ 만 남깁니다 (quote_plus와 같음, 공백은 '+')
    return parts.join('&');
}

// ---- 클라이언트 ------------------------------------------------------------------------------

OpenSubtitlesClient::OpenSubtitlesClient(const QString &apiKey, const QString &username, const QString &password,
                                         const QString &token, QObject *parent)
    : QObject(parent), m_apiKey(apiKey), m_username(username), m_password(password), m_token(token),
      m_nam(new QNetworkAccessManager(this))
{
}

OpenSubtitlesClient::~OpenSubtitlesClient() = default;

void OpenSubtitlesClient::request(const QByteArray &method, const QString &path, const QByteArray &query,
                                  const QByteArray &body, bool auth, JsonCallback done)
{
    if (m_apiKey.isEmpty()) {
        QMetaObject::invokeMethod(this, [done] { done({}, QStringLiteral("API 키가 없습니다")); }, Qt::QueuedConnection);
        return;
    }
    QByteArray url = m_apiBase.toUtf8() + path.toUtf8();
    if (!query.isEmpty())
        url += '?' + query;
    QNetworkRequest req(QUrl::fromEncoded(url, QUrl::StrictMode));
    req.setRawHeader("Api-Key", m_apiKey.toUtf8());
    req.setRawHeader("User-Agent", kUserAgent);
    req.setRawHeader("Accept", "application/json");
    if (!body.isNull())
        req.setRawHeader("Content-Type", "application/json");
    if (auth && !m_token.isEmpty())
        req.setRawHeader("Authorization", "Bearer " + m_token.toUtf8());
    req.setTransferTimeout(kTimeoutMs);
    QNetworkReply *reply = m_nam->sendCustomRequest(req, method, body);
    connect(reply, &QNetworkReply::finished, this, [reply, done] {
        reply->deleteLater();
        const int status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const QByteArray data = reply->readAll();
        if (status >= 400) {
            const QString detail = QJsonDocument::fromJson(data).object().value("message").toString();
            done({}, QStringLiteral("HTTP %1 %2").arg(status).arg(detail).trimmed());
            return;
        }
        if (reply->error() != QNetworkReply::NoError) {
            done({}, QStringLiteral("연결 실패: %1").arg(reply->errorString()));
            return;
        }
        done(data.trimmed().isEmpty() ? QByteArray("{}") : data, {});
    });
}

void OpenSubtitlesClient::search(const QString &videoPath, const QStringList &languages, SearchCallback done,
                                 const QString &query)
{
    // 해시는 파일 앞뒤 128KB를 읽으므로(느린 네트워크 드라이브일 수 있음) 작업 스레드에서 계산합니다.
    auto *watcher = new QFutureWatcher<QString>(this);
    connect(watcher, &QFutureWatcher<QString>::finished, this, [this, watcher, videoPath, languages, done, query] {
        const QString hash = watcher->result();
        watcher->deleteLater();
        QStringList langs = languages;
        langs.sort();
        QList<QPair<QString, QString>> params{{"languages", langs.join(',')}};   // 키 이름 순 (파이썬 sorted)
        if (!hash.isEmpty())
            params.append({"moviehash", hash});
        params.append({"query", query.isEmpty() ? queryFromFilename(videoPath) : query});
        request("GET", QStringLiteral("/subtitles"), urlEncode(params), QByteArray(), false,
                [done](const QByteArray &body, const QString &error) {
                    if (!error.isEmpty())
                        done({}, error);
                    else
                        done(parseSearchResults(body), {});
                });
    });
    watcher->setFuture(QtConcurrent::run([videoPath] { return moviehash(videoPath); }));
}

void OpenSubtitlesClient::login(LoginCallback done)
{
    if (m_username.isEmpty() || m_password.isEmpty()) {
        QMetaObject::invokeMethod(this, [done] { done({}, {}); }, Qt::QueuedConnection);
        return;
    }
    const QByteArray body =
        QJsonDocument(QJsonObject{{"username", m_username}, {"password", m_password}}).toJson(QJsonDocument::Compact);
    request("POST", QStringLiteral("/login"), {}, body, false, [this, done](const QByteArray &data, const QString &error) {
        if (!error.isEmpty()) {
            done({}, error);
            return;
        }
        m_token = QJsonDocument::fromJson(data).object().value("token").toString();
        done(m_token, {});
    });
}

void OpenSubtitlesClient::download(qint64 fileId, DownloadCallback done)
{
    if (!m_username.isEmpty() && !m_password.isEmpty() && m_token.isEmpty()) {
        login([this, fileId, done](const QString &, const QString &error) {
            if (!error.isEmpty())
                done({}, error);
            else
                requestDownloadLink(fileId, done);
        });
        return;
    }
    requestDownloadLink(fileId, done);
}

void OpenSubtitlesClient::requestDownloadLink(qint64 fileId, DownloadCallback done)
{
    const QByteArray body = QJsonDocument(QJsonObject{{"file_id", fileId}}).toJson(QJsonDocument::Compact);
    request("POST", QStringLiteral("/download"), {}, body, true, [this, done](const QByteArray &data, const QString &error) {
        if (!error.isEmpty()) {
            done({}, error);
            return;
        }
        const QJsonObject o = QJsonDocument::fromJson(data).object();
        const QString link = o.value("link").toString();
        if (link.isEmpty()) {
            const QString msg = o.value("message").toString();
            done({}, msg.isEmpty() ? QStringLiteral("다운로드 링크를 받지 못했습니다") : msg);
            return;
        }
        QNetworkRequest req{QUrl(link)};
        req.setRawHeader("User-Agent", kUserAgent);
        req.setTransferTimeout(kTimeoutMs);
        QNetworkReply *reply = m_nam->get(req);
        connect(reply, &QNetworkReply::finished, this, [reply, done] {
            reply->deleteLater();
            if (reply->error() != QNetworkReply::NoError)
                done({}, QStringLiteral("다운로드 실패: %1").arg(reply->errorString()));
            else
                done(reply->readAll(), {});
        });
    });
}

} // namespace jvp::opensubtitles
