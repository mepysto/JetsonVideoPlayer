#pragma once
// 타임라인 hover 미리보기용 썸네일을 백그라운드에서 생성·캐시합니다 (NVDEC 하드웨어 디코딩).
// 영상 전체를 디코딩하지 않고 N개 지점만 키프레임 탐색으로 추출하므로 긴 4K 영상도 수 초 안에 끝납니다.
// 결과: ~/.cache/jetson_video_player/thumbs/<hash>/index.json + 000.jpg ...
// 캐시 폴더 이름·index.json 형식이 파이썬 버전과 같아 기존 캐시를 그대로 씁니다.

#include <QJsonObject>
#include <QList>
#include <QMetaType>
#include <QObject>
#include <QString>
#include <QStringList>

#include <atomic>
#include <optional>
#include <thread>

namespace jvp {

constexpr int kThumbWidth = 160;
constexpr int kThumbIndexVersion = 1;

struct ThumbnailIndex {
    QString dir;                       // 썸네일 파일이 있는 폴더
    qint64 duration = 0;               // ns
    QList<qint64> positions;           // 각 썸네일 시각 (ns, 시간순)
    QStringList files;                 // "000.jpg" ...
    QList<qint64> scenes;              // 썸네일로 찾은 빠른 장면 전환 (ns)
    std::optional<QList<qint64>> scenesPrecise;   // 정밀 분석 결과 (있으면)

    bool isValid() const { return !files.isEmpty() && files.size() == positions.size(); }
    QString filePath(int i) const;
    QJsonObject toJson() const;        // version/complete 포함 (dir 제외)
    static ThumbnailIndex fromJson(const QJsonObject &o, const QString &dir);
};

// sha1("절대경로|크기|mtime(정수)")의 앞 20자 — 파이썬 thumbnail_cache_dir과 같음
QString thumbnailCacheDir(const QString &videoPath);
// 완성된 캐시 인덱스 (version 1, complete) 또는 nullopt
std::optional<ThumbnailIndex> loadThumbnailIndex(const QString &videoPath);
// 영상 길이에 따른 썸네일 개수: 10초 간격, 최소 20장, 최대 120장
int thumbnailSampleCount(qint64 durationNs);
// ns에 가장 가까운 썸네일 번호 (없으면 -1). preferAfter: 그 시각 이후의 첫 썸네일 (장면 시작 미리보기용)
int nearestThumbnail(const ThumbnailIndex &index, qint64 ns, bool preferAfter = false);

// 한 영상의 썸네일 생성 작업. 신호는 모두 소유 스레드에서 발생합니다.
class ThumbnailJob : public QObject {
    Q_OBJECT
public:
    explicit ThumbnailJob(const QString &path, QObject *parent = nullptr);
    ~ThumbnailJob() override;   // 취소 후 스레드가 끝날 때까지 기다립니다

    void start();                // 캐시가 있으면 스레드 없이 곧바로(다음 이벤트 루프에서) done
    void cancel();
    bool isRunning() const { return m_running.load(); }

signals:
    void progress(const jvp::ThumbnailIndex &partial);   // 10장마다 (scenes는 비어 있음)
    void done(const jvp::ThumbnailIndex &index);
    void failed(const QString &reason);                   // 영상이 아니거나 파이프라인 실패 (취소 시에는 없음)

private:
    void generate();
    QString m_path;
    std::thread m_thread;
    std::atomic<bool> m_cancelled{false};
    std::atomic<bool> m_running{false};
};

// [사용자 요청 시] 모든 프레임을 16x9 크기로 하드웨어 디코딩해 장면 전환을 프레임 단위로 찾습니다.
// 비참조 프레임은 건너뛰어(skip-frames=1) 4K 영상도 실시간의 약 10배 속도로 분석합니다.
// 결과는 썸네일 인덱스의 "scenes_precise"에 저장되어 다음부터 즉시 사용됩니다.
class SceneAnalysisJob : public QObject {
    Q_OBJECT
public:
    explicit SceneAnalysisJob(const QString &path, QObject *parent = nullptr);
    ~SceneAnalysisJob() override;

    void start();
    void cancel();
    bool isRunning() const { return m_running.load(); }
    double progressValue() const { return m_progress.load(); }

signals:
    void progress(double fraction);                          // 0~1, 2%마다
    // ok=false: 취소 또는 실패 (파이썬의 on_done(None))
    void done(const QList<qint64> &scenes, bool ok);

private:
    std::optional<QList<qint64>> analyze(bool hw, QString *error, bool *sawFrame);
    QString m_path;
    std::thread m_thread;
    std::atomic<bool> m_cancelled{false};
    std::atomic<bool> m_running{false};
    std::atomic<double> m_progress{0.0};
};

} // namespace jvp

Q_DECLARE_METATYPE(jvp::ThumbnailIndex)
