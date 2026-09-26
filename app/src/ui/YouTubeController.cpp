#include "YouTubeController.h"

#include "AiController.h"
#include "AppController.h"
#include "Paths.h"
#include "YouTube.h"

#include <QDateTime>
#include <QLoggingCategory>
#include <QTimer>

Q_LOGGING_CATEGORY(lcYt, "jvp.youtube")

namespace jvp {

YouTubeController::YouTubeController(AppController *app)
    : QObject(app), m_app(app), m_mgr(new youtube::YouTubeManager(paths::youtubeDir(), this))
{
    connect(m_mgr, &youtube::YouTubeManager::progress, this, &YouTubeController::onProgress);
    connect(m_mgr, &youtube::YouTubeManager::finished, this, &YouTubeController::onFinished);
    connect(m_mgr, &youtube::YouTubeManager::failed, this, &YouTubeController::onFailed);
    connect(m_mgr, &youtube::YouTubeManager::statusChanged, this, &YouTubeController::changed);
}

bool YouTubeController::isYoutubeUrl(const QString &text) { return youtube::isYoutubeUrl(text.trimmed()); }

QVariantMap YouTubeController::state() const
{
    QVariantMap s = m_mgr->status();
    if (m_loadingVisible) {
        s.insert("title", m_loadingTitle);
        s.insert("status", m_loadingStatus);
        s.insert("percent", m_percent);
    }
    return s;
}

QJsonObject YouTubeController::remoteStatus() const { return QJsonObject::fromVariantMap(m_mgr->status()); }

void YouTubeController::addAndPlay(const QString &path, bool playNow)
{
    qobject_cast<AiController *>(m_app->aiObject())->markForAuto(path);
    if (playNow || m_app->playlistPaths().isEmpty())
        m_app->addToPlaylistAndPlay(path);
    else {
        m_app->appendToPlaylist(path);   // 보던 영상을 끊지 않고 "다음에 재생" 대기열로
        m_app->queueNext(path);
    }
}

void YouTubeController::start(const QString &url, const QString &quality)
{
    const QString norm = youtube::extractYoutubeUrl(url);
    if (norm.isEmpty()) {
        m_app->showOsd(QStringLiteral("⚠️ 올바른 유튜브 링크가 아닙니다."), 2000);
        return;
    }
    const QString existing = m_mgr->findExistingVideo(norm);
    if (!existing.isEmpty()) {
        qCInfo(lcYt).noquote() << "⚡ [YouTube] 이미 받은 영상을 바로 재생합니다:" << existing;
        m_app->showOsd(QStringLiteral("⚡ 이미 받은 유튜브 영상입니다. 바로 재생합니다!"), 2000);
        m_loadingVisible = false;
        emit changed();
        addAndPlay(existing, true);
        return;
    }
    // 재생 중인 영상이 없을 때만 전체 로딩 화면을 띄우고, 완료 시 바로 재생합니다.
    const bool nothingPlaying = m_app->playlistPaths().isEmpty() || !m_app->hasVideo();
    const QString qDesc = quality == QLatin1String("best") ? QStringLiteral("최고 화질")
                          : quality == QLatin1String("audio") ? QStringLiteral("오디오") : quality;
    const auto [result, position] = m_mgr->downloadAsync(norm, quality);
    if (result == QLatin1String("started")) {
        qCInfo(lcYt).noquote() << "⬇️ [YouTube 다운로드 시작]" << norm << "(품질:" << quality << ")";
        m_playWhenDone = nothingPlaying;
        if (nothingPlaying) {
            m_loadingVisible = true;
            m_loadingTitle = QStringLiteral("YouTube 영상 받는 중...");
            m_loadingStatus = QStringLiteral("⬇️ %1 다운로드 준비 중...").arg(qDesc);
            m_percent = 0;
        } else {
            m_app->showOsd(QStringLiteral("⬇️ [유튜브] %1 다운로드를 시작합니다.").arg(qDesc), 1500);
        }
    } else if (result == QLatin1String("queued")) {
        m_app->showOsd(QStringLiteral("🕒 다운로드 대기열 %1번째로 추가했습니다.").arg(position), 2500);
    } else if (result == QLatin1String("downloading")) {
        m_app->showOsd(QStringLiteral("⬇️ 이미 받고 있는 영상입니다."), 2000);
    } else if (result == QLatin1String("error")) {
        m_app->showOsd(QStringLiteral("❌ yt-dlp를 찾을 수 없습니다 (pip install --user yt-dlp)"), 4000);
    }
    emit changed();
}

void YouTubeController::onProgress(const QString &, double percent, const QString &speed, const QString &eta,
                                   const QString &title)
{
    m_percent = percent;
    const qint64 now = QDateTime::currentMSecsSinceEpoch();
    if (m_loadingVisible) {
        if (!title.isEmpty() && title != QLatin1String("YouTube Video"))
            m_loadingTitle = title;
        const QString info = speed.isEmpty() ? QString() : QStringLiteral(" (%1, 남은시간 %2)").arg(speed, eta);
        m_loadingStatus = QStringLiteral("⬇️ 받는 중 %1%%2").arg(int(percent)).arg(info);
    } else if (now - m_lastOsdMs >= 800 || percent >= 99.0) {
        m_lastOsdMs = now;
        m_app->showOsd(QStringLiteral("⬇️ %1% (%2, 남은시간 %3)").arg(int(percent)).arg(speed, eta), 1200);
    }
    emit changed();
}

void YouTubeController::onFinished(const QString &, const QString &path, const QString &title)
{
    qCInfo(lcYt).noquote() << "🎉 [YouTube 다운로드 완료]" << path;
    const bool playNow = m_playWhenDone || !m_app->hasVideo();
    m_playWhenDone = false;
    m_loadingVisible = false;
    if (playNow)
        m_app->showOsd(QStringLiteral("▶️ 재생: %1").arg(title.left(30)), 3000);
    else
        m_app->showOsd(QStringLiteral("🎉 다운로드 완료 → 다음에 재생: %1").arg(title.left(25)), 3500);
    emit changed();
    if (!path.isEmpty())
        addAndPlay(path, playNow);
}

void YouTubeController::onFailed(const QString &, const QString &error)
{
    const bool cancelled = error == youtube::YouTubeManager::kCancelledMessage;
    if (cancelled)
        qCInfo(lcYt).noquote() << "⏹ [YouTube]" << error;
    else
        qCWarning(lcYt).noquote() << "❌ [YouTube]" << error;
    m_app->showOsd(cancelled ? QStringLiteral("⏹ 다운로드를 취소했습니다.")
                             : QStringLiteral("❌ 다운로드 실패: %1").arg(error.left(40)), 3000);
    m_playWhenDone = false;
    if (m_loadingVisible) {
        m_loadingTitle = cancelled ? QStringLiteral("다운로드 취소") : QStringLiteral("다운로드 실패");
        m_loadingStatus = error.left(60);
        QTimer::singleShot(cancelled ? 2500 : 3500, this, [this] {
            m_loadingVisible = false;
            emit changed();
        });
    }
    emit changed();
}

void YouTubeController::cancelCurrent() { m_mgr->cancelCurrent(); }

void YouTubeController::cancelPending(const QString &url)
{
    if (m_mgr->cancelPending(url))
        emit changed();
}

} // namespace jvp
