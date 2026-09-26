#include "OnlineSubsController.h"

#include "AppController.h"
#include "OpenSubtitles.h"
#include "Paths.h"
#include "Settings.h"
#include "SubtitleParse.h"

#include <QDir>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QSaveFile>

Q_LOGGING_CATEGORY(lcOs, "jvp.opensubtitles")

namespace jvp {

namespace {
QString uniquePath(const QString &path)
{
    if (!QFileInfo::exists(path))
        return path;
    const QFileInfo fi(path);
    const QString stem = fi.absolutePath() + QLatin1Char('/') + fi.completeBaseName();
    for (int n = 2;; ++n) {
        const QString cand = QStringLiteral("%1.%2.%3").arg(stem).arg(n).arg(fi.suffix());
        if (!QFileInfo::exists(cand))
            return cand;
    }
}

opensubtitles::OpenSubtitlesClient *makeClient(QObject *parent)
{
    const auto c = opensubtitles::loadCredentials();
    return new opensubtitles::OpenSubtitlesClient(c.value("api_key"), c.value("username"), c.value("password"),
                                                  QString(), parent);
}
} // namespace

OnlineSubsController::OnlineSubsController(AppController *app) : QObject(app), m_app(app) {}

bool OnlineSubsController::hasKey() const { return !opensubtitles::loadCredentials().value("api_key").isEmpty(); }

QString OnlineSubsController::defaultQuery() const
{
    return opensubtitles::queryFromFilename(m_app->currentPath());
}

QVariantMap OnlineSubsController::credentials() const
{
    const auto c = opensubtitles::loadCredentials();
    return {{"api_key", c.value("api_key")}, {"username", c.value("username")}, {"password", c.value("password")}};
}

void OnlineSubsController::saveCredentials(const QString &apiKey, const QString &username, const QString &password)
{
    if (apiKey.trimmed().isEmpty())
        return;
    QMap<QString, QString> c{{"api_key", apiKey.trimmed()}, {"username", username.trimmed()}, {"password", password}};
    if (!opensubtitles::saveCredentials(c))
        m_app->showOsd(QStringLiteral("❌ 저장 실패: %1").arg(opensubtitles::credentialsFile()), 3000);
    emit changed();
}

void OnlineSubsController::search(const QString &query, const QString &languages)
{
    const QString video = m_app->currentPath();
    if (m_busy || video.isEmpty() || !QFileInfo(video).isFile())
        return;
    QStringList langs;
    for (const QString &l : languages.split(QLatin1Char(',')))
        if (!l.trimmed().isEmpty())
            langs << l.trimmed().toLower();
    if (langs.isEmpty())
        langs = {QStringLiteral("ko"), QStringLiteral("en")};
    Settings::instance()->setValue(QStringLiteral("opensubtitles_languages"), langs.join(QLatin1Char(',')));
    m_video = video;
    m_busy = true;
    m_status = QStringLiteral("🔎 검색 중...");
    m_results.clear();
    emit changed();
    auto *client = makeClient(this);
    client->search(video, langs,
                   [this, client](const QList<opensubtitles::SubtitleResult> &found, const QString &error) {
                       client->deleteLater();
                       m_busy = false;
                       m_results.clear();
                       if (!error.isEmpty()) {
                           m_status = QStringLiteral("❌ %1").arg(error);
                       } else {
                           for (const auto &r : found)
                               m_results << QVariantMap{{"fileId", r.fileId}, {"language", r.language},
                                                        {"release", r.release.isEmpty() ? r.fileName : r.release},
                                                        {"fileName", r.fileName}, {"downloads", r.downloads},
                                                        {"hashMatch", r.hashMatch}, {"title", r.title}};
                           m_status = found.isEmpty() ? QStringLiteral("찾은 자막이 없습니다. 검색어를 바꿔 보세요.")
                                                      : QStringLiteral("%1개 찾음 · 두 번 누르면(또는 Enter) 받아서 켭니다. ✓ = 이 영상 파일과 정확히 맞는 자막").arg(found.size());
                       }
                       emit changed();
                   },
                   query.trimmed());
}

void OnlineSubsController::download(int index)
{
    if (m_busy || index < 0 || index >= m_results.size())
        return;
    const QVariantMap r = m_results[index].toMap();
    const QString video = m_video;
    m_busy = true;
    m_status = QStringLiteral("⬇️ 받는 중: %1").arg(r.value("release").toString());
    emit changed();
    auto *client = makeClient(this);
    client->download(r.value("fileId").toLongLong(), [this, client, video, r](const QByteArray &content, const QString &error) {
        client->deleteLater();
        m_busy = false;
        m_status.clear();
        emit changed();
        if (!error.isEmpty() || content.isEmpty()) {
            m_app->showOsd(QStringLiteral("❌ 자막 받기 실패: %1").arg((error.isEmpty() ? QStringLiteral("빈 파일") : error).left(60)), 4000);
            return;
        }
        saveDownloaded(video, r, content);
    });
}

void OnlineSubsController::saveDownloaded(const QString &video, const QVariantMap &r, const QByteArray &content)
{
    QString path = opensubtitles::subtitleSavePath(video, r.value("language").toString(), r.value("fileName").toString());
    if (!QFileInfo(QFileInfo(path).absolutePath()).isWritable()) {
        // 영상 폴더에 쓸 수 없으면 캐시 폴더에 (다음 재생에서도 자동으로 불러옴)
        QDir().mkpath(paths::aiSubtitleCacheDir());
        const QString videoStem = QFileInfo(video).absolutePath() + QLatin1Char('/') + QFileInfo(video).completeBaseName();
        path = paths::aiSubtitleCacheDir() + QLatin1Char('/') + subtitles::cachedAiSubtitleStem(video) + path.mid(videoStem.size());
    }
    path = uniquePath(path);
    QSaveFile f(path);
    if (!f.open(QIODevice::WriteOnly) || f.write(content) != content.size() || !f.commit()) {
        m_app->showOsd(QStringLiteral("❌ 저장 실패: %1").arg(path), 4000);
        return;
    }
    qCInfo(lcOs).noquote() << "🔎 [온라인 자막]" << r.value("release").toString() << "→" << path;
    if (m_app->currentPath() == video) {
        m_app->addExternalSubtitle(path);
        emit downloaded();
    }
}

} // namespace jvp
