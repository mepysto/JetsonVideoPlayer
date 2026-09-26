#pragma once
// YouTube 영상 받아서 재생 (yt-dlp): 이미 받은 영상은 바로 재생, 재생 중인 게 없으면 로딩 화면,
// 재생 중이면 받은 뒤 "다음에 재생" 대기열에. (파이썬 ui/youtube.py)

#include <QJsonObject>
#include <QObject>
#include <QVariantMap>

namespace jvp {

class AppController;
namespace youtube {
class YouTubeManager;
}

class YouTubeController : public QObject {
    Q_OBJECT
public:
    explicit YouTubeController(AppController *app);

    static bool isYoutubeUrl(const QString &text);

    void start(const QString &url, const QString &quality);
    void cancelCurrent();
    void cancelPending(const QString &url);

    bool loading() const { return m_loadingVisible; }
    QVariantMap state() const;          // QML: active, title, percent, speed, status, queue
    QJsonObject remoteStatus() const;   // 웹 리모컨 yt_download

signals:
    void changed();

private:
    void onProgress(const QString &url, double percent, const QString &speed, const QString &eta, const QString &title);
    void onFinished(const QString &url, const QString &path, const QString &title);
    void onFailed(const QString &url, const QString &error);
    void addAndPlay(const QString &path, bool playNow);

    AppController *m_app;
    youtube::YouTubeManager *m_mgr;
    bool m_loadingVisible = false;      // 재생 중인 영상이 없을 때만 전체 로딩 화면
    bool m_playWhenDone = false;        // 지금 받는 영상을 끝나자마자 재생할지 (아니면 대기열)
    QString m_loadingTitle;
    QString m_loadingStatus;
    double m_percent = 0;
    qint64 m_lastOsdMs = 0;
};

} // namespace jvp
