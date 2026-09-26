#pragma once
// 이어보기/북마크/최근 기록/HW 적합성/음량 캐시의 JSON 영구 저장소 (파이썬 storage.py 이식).
// 파일 이름과 JSON 형식이 파이썬 버전과 같아서 기존 사용자 데이터를 그대로 읽습니다.
// 각 저장소는 스레드 안전하며, 바뀐 경우에만(dirty) save()가 원자적으로 씁니다.

#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QList>
#include <QMutex>
#include <QPair>
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <functional>
#include <optional>

namespace jvp {

constexpr qint64 kNsPerSecond = 1'000'000'000;

// 파일이 없거나 손상됐거나 형식이 틀리면 빈 값으로 시작합니다.
class JsonStore {
public:
    explicit JsonStore(const QString &path);
    virtual ~JsonStore() = default;
    JsonStore(const JsonStore &) = delete;
    JsonStore &operator=(const JsonStore &) = delete;

    QString path() const { return m_path; }
    bool isDirty() const;
    void save();   // 바뀐 경우에만 (실패하면 경고만 남기고 dirty 유지)

protected:
    // 하위 클래스 생성자에서 호출 (가상 함수 때문에 기반 생성자에서는 부를 수 없음)
    void load();
    // [잠금 보유] 불러온 값을 검증해 받아들이면 true, 아니면 false (→ 빈 값)
    virtual bool acceptLoaded(const QJsonValue &value) = 0;
    virtual void resetData() = 0;
    virtual void beforeSave() {}                  // [잠금 보유] 저장 직전 정리
    virtual QByteArray serialize() const = 0;     // [잠금 보유]
    void markDirty() { m_dirty = true; }          // [잠금 보유]

    mutable QMutex m_mutex;

private:
    QString m_path;
    bool m_dirty = false;
};

// 영상 파일별 NVDEC 지원 판정 결과 캐시 (파일 크기/수정 시각이 같을 때만 재사용). hw_cache.json
class HWSupportCache : public JsonStore {
public:
    static constexpr int kVersion = 2;   // v2: 실제 NVDEC 능력 기준 판정
    explicit HWSupportCache(const QString &path = QString());
    // (지원 여부, 사유). 캐시가 없거나 파일이 바뀌었으면 nullopt
    std::optional<QPair<bool, QString>> get(const QString &filePath) const;
    void set(const QString &filePath, bool supported, const QString &reason);

protected:
    bool acceptLoaded(const QJsonValue &value) override;
    void resetData() override { m_data = {}; }
    QByteArray serialize() const override;

private:
    QJsonObject m_data;
};

// 마지막 재생 위치(이어보기)와 끝까지 봤는지(watched). resume_cache.json
// 항목 형식: {"position_ns", "duration_ns", "updated_at", "watched"} — position_ns가 0이면 진행 중 위치 없음
class ResumeCache : public JsonStore {
public:
    static constexpr int kMaxEntries = 200;
    static constexpr qint64 kMinPositionNs = 5 * kNsPerSecond;
    static constexpr double kCompleteRatio = 0.95;

    struct Entry {
        QString path;
        qint64 positionNs = 0;
        qint64 durationNs = 0;
        bool operator==(const Entry &o) const
        {
            return path == o.path && positionNs == o.positionNs && durationNs == o.durationNs;
        }
    };
    struct Progress {
        std::optional<double> ratio;   // 0~1, 진행 중 위치가 없으면 nullopt
        bool watched = false;
    };

    explicit ResumeCache(const QString &path = QString());
    QPair<qint64, qint64> get(const QString &filePath) const;   // (position_ns, duration_ns), 없으면 (0, 0)
    Progress progress(const QString &filePath) const;
    // 5초 미만은 저장하지 않고, 95%를 넘으면 시청 완료 처리
    void set(const QString &filePath, qint64 positionNs, qint64 durationNs);
    void markCompleted(const QString &filePath, qint64 durationNs = 0);
    void clear(const QString &filePath);
    // 이어볼 수 있는 최근 영상 (최근 것부터). available: 넣을지 판단 (기본: 파일이 있을 때)
    QList<Entry> recentInProgress(int limit = 5,
                                  const std::function<bool(const QString &)> &available = nullptr) const;

protected:
    bool acceptLoaded(const QJsonValue &value) override;
    void resetData() override { m_data = {}; }
    void beforeSave() override;
    QByteArray serialize() const override;

private:
    QJsonObject m_data;
};

// 영상별 북마크 {경로: [{"position_ns", "label", "created_at"}, ...]}. bookmarks.json
class BookmarkCache : public JsonStore {
public:
    explicit BookmarkCache(const QString &path = QString());
    // QVariantMap{position_ns, label, created_at} 목록 (시간순)
    QVariantList get(const QString &filePath) const;
    // (성공, 라벨 또는 실패 사유). label을 비우면 "MM:SS"/"HH:MM:SS"
    QPair<bool, QString> add(const QString &filePath, qint64 positionNs, const QString &label = QString());
    bool remove(const QString &filePath, int index);

protected:
    bool acceptLoaded(const QJsonValue &value) override;
    void resetData() override { m_data = {}; }
    QByteArray serialize() const override;

private:
    QJsonObject m_data;
};

// 최근 재생한 파일/폴더 (최신순, 최대 kHistoryLimit개). history.json
constexpr int kHistoryLimit = 15;
class HistoryCache : public JsonStore {
public:
    explicit HistoryCache(const QString &path = QString());
    void add(const QString &path);   // 없는 경로는 무시
    QVariantList all() const;        // QVariantMap{path, title, is_dir, timestamp}

protected:
    bool acceptLoaded(const QJsonValue &value) override;
    void resetData() override { m_data = {}; }
    QByteArray serialize() const override;

private:
    QJsonArray m_data;
};

// 파일이 바뀌면 달라지는 키 "절대경로|크기|수정시각(정수초)". 파일이 없으면 null QString
QString fileKey(const QString &path);

// 영상별 통합 음량(LUFS) {파일 키: LUFS 또는 null(오디오 없음)}. loudness.json
// 오래된 것부터 지우기 위해 삽입 순서를 지킵니다 (다시 저장하면 맨 뒤로).
class LoudnessCache : public JsonStore {
public:
    static constexpr int kMaxEntries = 2000;
    explicit LoudnessCache(const QString &path = QString());
    // (측정했는지, LUFS — 오디오가 없었으면 nullopt)
    QPair<bool, std::optional<double>> lookup(const QString &path) const;
    void store(const QString &path, std::optional<double> lufs);

protected:
    bool acceptLoaded(const QJsonValue &value) override;
    void resetData() override;
    void beforeSave() override;
    QByteArray serialize() const override;

private:
    QStringList m_order;                             // 삽입 순서
    QHash<QString, std::optional<double>> m_values;
};

// 프로세스 전역 저장소 (기본 경로: paths::cacheDir())
HWSupportCache &hwCache();
ResumeCache &resumeCache();
BookmarkCache &bookmarkCache();
HistoryCache &historyCache();
LoudnessCache &loudnessCache();
void saveAllStores();   // 종료 시 한 번에

} // namespace jvp
