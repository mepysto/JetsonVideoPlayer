#pragma once
// YouTube URL 처리와 yt-dlp 기반 다운로드 매니저 (파이썬 jetson_player/youtube.py 이식).
// 파이썬 버전은 yt_dlp 모듈의 progress hook을 썼고, 여기서는 yt-dlp CLI를 QProcess로 실행해
// --progress-template / --print after_move:… 로 진행률과 최종 파일 경로를 받습니다.
// 실행기는 주입할 수 있어(setRunnerFactory) 테스트에서 네트워크 없이 대기열을 검증합니다.

#include <QObject>
#include <QPair>
#include <QString>
#include <QStringList>
#include <QVariantMap>

#include <functional>
#include <memory>

class QProcess;

namespace jvp::youtube {

bool isYoutubeUrl(const QString &url);
// 유튜브 링크를 https://www.youtube.com/watch?v=<ID> 로 정규화 (믹스·재생목록 파라미터 제거). 아니면 null QString
QString extractYoutubeUrl(const QString &text);
QString extractYoutubeVideoId(const QString &url);   // 11자리 ID 또는 null
// 화질 선택("best"/"1080p"/"720p"/"audio") → yt-dlp 포맷 (H.264 우선, AV1 제외 — Jetson NVDEC)
QString formatForQuality(const QString &quality);
// yt-dlp의 YouTube 서명 해독용 JS 런타임 (Deno 우선, 없으면 Node.js): (이름, 경로) 또는 빈 쌍
QPair<QString, QString> jsRuntime();
QString formatSpeed(double bytesPerSec);
QString formatEta(qint64 seconds);
QString findYtDlp();   // PATH 또는 ~/.local/bin/yt-dlp (없으면 빈 문자열)

// yt-dlp 프로세스 실행기 (주입 가능). 출력은 줄 단위(stdout/stderr 합침)로 전달합니다.
class DownloadRunner : public QObject {
    Q_OBJECT
public:
    using QObject::QObject;
    virtual void start(const QString &program, const QStringList &args) = 0;
    virtual void kill() = 0;
signals:
    void lineReceived(const QString &line);
    void finished(int exitCode, bool crashed);
};

class ProcessRunner : public DownloadRunner {
    Q_OBJECT
public:
    explicit ProcessRunner(QObject *parent = nullptr);
    void start(const QString &program, const QStringList &args) override;
    void kill() override;

private:
    QProcess *m_proc;
    QByteArray m_buffer;
};

using RunnerFactory = std::function<DownloadRunner *()>;

// YouTube 영상 다운로드를 대기열로 관리합니다 (한 번에 하나씩 순서대로, 취소 가능). GUI 스레드에서 씁니다.
class YouTubeManager : public QObject {
    Q_OBJECT
public:
    static const QString kCancelledMessage;   // "사용자가 다운로드를 취소했습니다."

    explicit YouTubeManager(const QString &downloadDir = QString(), QObject *parent = nullptr);
    ~YouTubeManager() override;

    void setRunnerFactory(RunnerFactory factory);   // 기본: ProcessRunner (실제 yt-dlp)
    void setProgram(const QString &program);         // 기본: findYtDlp()
    QString downloadDir() const { return m_downloadDir; }

    // 반환: ("cached" | "started" | "downloading" | "queued" | "error", 대기 순번)
    QPair<QString, int> downloadAsync(const QString &url, const QString &quality = QStringLiteral("best"));
    bool cancelCurrent();
    bool cancelPending(const QString &url);
    // 파이썬 get_status()와 같은 모양: active,title,url,percent,speed,eta,filepath,error,completed,queue[{url,quality}]
    QVariantMap status() const;
    QString findExistingVideo(const QString &urlOrId) const;
    static QString titleFromFilename(const QString &path);
    QStringList buildArguments(const QString &url, const QString &quality) const;

signals:
    void progress(const QString &url, double percent, const QString &speed, const QString &eta, const QString &title);
    void finished(const QString &url, const QString &filePath, const QString &title);
    void failed(const QString &url, const QString &error);
    void statusChanged();

private:
    struct Job {
        QString url, quality;
    };
    void begin(const Job &job);
    void startNext();
    void onLine(const QString &line);
    void onFinished(int exitCode, bool crashed);
    void cleanupPartialFiles(const QString &url);

    QString m_downloadDir;
    QString m_program;
    RunnerFactory m_factory;
    DownloadRunner *m_runner = nullptr;
    QList<Job> m_pending;
    QVariantMap m_current;
    bool m_cancelRequested = false;
    QString m_finalPath, m_finalTitle, m_lastError;
};

} // namespace jvp::youtube
