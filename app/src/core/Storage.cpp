#include "Storage.h"

#include "JsonFile.h"
#include "Library.h"
#include "Paths.h"

#include <QDateTime>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QLoggingCategory>
#include <QMutexLocker>
#include <algorithm>
#include <cmath>

#include <sys/stat.h>

Q_LOGGING_CATEGORY(lcStorage, "jvp.storage")

namespace jvp {

namespace {

// time.time()과 같은 초 단위 실수
double nowSeconds() { return double(QDateTime::currentMSecsSinceEpoch()) / 1000.0; }

qint64 ns(const QJsonValue &v) { return v.isDouble() ? qint64(v.toDouble()) : 0; }

// os.stat()의 (st_mtime, st_size). 파이썬과 같은 식(sec + nsec * 1e-9)으로 계산해야
// 파이썬 버전이 저장한 hw_cache.json의 mtime과 정확히 같은 값이 나옵니다.
std::optional<QPair<double, qint64>> fileSignature(const QString &path)
{
    struct stat st {};
    if (path.isEmpty() || ::stat(QFile::encodeName(path).constData(), &st) != 0)
        return std::nullopt;
    return QPair<double, qint64>(double(st.st_mtim.tv_sec) + double(st.st_mtim.tv_nsec) * 1e-9, st.st_size);
}

QByteArray toJson(const QJsonObject &o) { return QJsonDocument(o).toJson(QJsonDocument::Indented); }
QByteArray toJson(const QJsonArray &a) { return QJsonDocument(a).toJson(QJsonDocument::Indented); }

QString defaultPath(const QString &path, const char *fileName)
{
    return path.isEmpty() ? paths::cacheDir() + QLatin1Char('/') + QLatin1String(fileName) : path;
}

} // namespace

// ---------------------------------------------------------------- JsonStore

JsonStore::JsonStore(const QString &path) : m_path(path) {}

bool JsonStore::isDirty() const
{
    QMutexLocker lock(&m_mutex);
    return m_dirty;
}

void JsonStore::load()
{
    bool ok = false;
    const QJsonValue v = json::read(m_path, &ok);
    QMutexLocker lock(&m_mutex);
    if (!ok || !acceptLoaded(v))
        resetData();
    m_dirty = false;
}

void JsonStore::save()
{
    QMutexLocker lock(&m_mutex);
    if (!m_dirty)
        return;
    beforeSave();
    QString error;
    if (json::writeBytesAtomic(m_path, serialize(), &error))
        m_dirty = false;
    else
        qCWarning(lcStorage).noquote() << QStringLiteral("⚠️ 저장 실패 (%1): %2").arg(QFileInfo(m_path).fileName(), error);
}

// ---------------------------------------------------------------- HWSupportCache

HWSupportCache::HWSupportCache(const QString &path) : JsonStore(defaultPath(path, "hw_cache.json")) { load(); }

bool HWSupportCache::acceptLoaded(const QJsonValue &value)
{
    if (!value.isObject())
        return false;
    m_data = value.toObject();
    return true;
}

QByteArray HWSupportCache::serialize() const { return toJson(m_data); }

std::optional<QPair<bool, QString>> HWSupportCache::get(const QString &filePath) const
{
    const auto sig = fileSignature(filePath);
    if (!sig)
        return std::nullopt;
    QMutexLocker lock(&m_mutex);
    const QJsonObject e = m_data.value(filePath).toObject();
    if (!e.isEmpty() && e.value(QLatin1String("v")).toDouble(-1) == kVersion
        && e.value(QLatin1String("mtime")).toDouble(-1) == sig->first
        && e.value(QLatin1String("size")).toDouble(-1) == double(sig->second))
        return QPair<bool, QString>(e.value(QLatin1String("supported")).toBool(false),
                                    e.value(QLatin1String("reason")).toString());
    return std::nullopt;
}

void HWSupportCache::set(const QString &filePath, bool supported, const QString &reason)
{
    const auto sig = fileSignature(filePath).value_or(QPair<double, qint64>(0, 0));
    QMutexLocker lock(&m_mutex);
    m_data.insert(filePath, QJsonObject{{"mtime", sig.first},
                                        {"size", sig.second},
                                        {"supported", supported},
                                        {"reason", reason},
                                        {"v", kVersion}});
    markDirty();
}

// ---------------------------------------------------------------- ResumeCache

ResumeCache::ResumeCache(const QString &path) : JsonStore(defaultPath(path, "resume_cache.json")) { load(); }

bool ResumeCache::acceptLoaded(const QJsonValue &value)
{
    if (!value.isObject())
        return false;
    // 항목 중 객체가 아닌 것만 버립니다
    const QJsonObject in = value.toObject();
    m_data = {};
    for (auto it = in.constBegin(); it != in.constEnd(); ++it)
        if (it->isObject())
            m_data.insert(it.key(), *it);
    return true;
}

QByteArray ResumeCache::serialize() const { return toJson(m_data); }

void ResumeCache::beforeSave()
{
    // 최대 개수 유지 (가장 오래된 항목부터 정리)
    if (m_data.size() <= kMaxEntries)
        return;
    QStringList keys = m_data.keys();
    std::stable_sort(keys.begin(), keys.end(), [this](const QString &a, const QString &b) {
        return m_data.value(a).toObject().value(QLatin1String("updated_at")).toDouble(0)
            < m_data.value(b).toObject().value(QLatin1String("updated_at")).toDouble(0);
    });
    QJsonObject kept;
    for (qsizetype i = keys.size() - kMaxEntries; i < keys.size(); ++i)
        kept.insert(keys.at(i), m_data.value(keys.at(i)));
    m_data = kept;
}

QPair<qint64, qint64> ResumeCache::get(const QString &filePath) const
{
    QMutexLocker lock(&m_mutex);
    const QJsonObject e = m_data.value(filePath).toObject();
    if (e.isEmpty())
        return {0, 0};
    return {ns(e.value(QLatin1String("position_ns"))), ns(e.value(QLatin1String("duration_ns")))};
}

ResumeCache::Progress ResumeCache::progress(const QString &filePath) const
{
    QMutexLocker lock(&m_mutex);
    const QJsonObject e = m_data.value(filePath).toObject();
    Progress p;
    if (e.isEmpty())
        return p;
    const qint64 pos = ns(e.value(QLatin1String("position_ns"))), dur = ns(e.value(QLatin1String("duration_ns")));
    if (pos > 0 && dur > 0)
        p.ratio = double(pos) / double(dur);
    p.watched = e.value(QLatin1String("watched")).toBool(false);
    return p;
}

void ResumeCache::set(const QString &filePath, qint64 positionNs, qint64 durationNs)
{
    if (positionNs < kMinPositionNs)
        return;
    if (durationNs > 0 && double(positionNs) > double(durationNs) * kCompleteRatio) {
        markCompleted(filePath, durationNs);
        return;
    }
    QMutexLocker lock(&m_mutex);
    const QJsonObject prev = m_data.value(filePath).toObject();
    m_data.insert(filePath, QJsonObject{{"position_ns", positionNs},
                                        {"duration_ns", durationNs},
                                        {"updated_at", nowSeconds()},
                                        {"watched", prev.value(QLatin1String("watched")).toBool(false)}});
    markDirty();
}

void ResumeCache::markCompleted(const QString &filePath, qint64 durationNs)
{
    QMutexLocker lock(&m_mutex);
    const QJsonObject prev = m_data.value(filePath).toObject();
    if (prev.value(QLatin1String("watched")).toBool(false) && ns(prev.value(QLatin1String("position_ns"))) == 0)
        return;
    m_data.insert(filePath, QJsonObject{{"position_ns", 0},
                                        {"duration_ns", durationNs ? durationNs : ns(prev.value(QLatin1String("duration_ns")))},
                                        {"updated_at", nowSeconds()},
                                        {"watched", true}});
    markDirty();
}

void ResumeCache::clear(const QString &filePath)
{
    QMutexLocker lock(&m_mutex);
    if (m_data.contains(filePath)) {
        m_data.remove(filePath);
        markDirty();
    }
}

QList<ResumeCache::Entry> ResumeCache::recentInProgress(int limit,
                                                        const std::function<bool(const QString &)> &available) const
{
    struct Item {
        Entry entry;
        double updatedAt;
    };
    QList<Item> items;
    {
        QMutexLocker lock(&m_mutex);
        for (auto it = m_data.constBegin(); it != m_data.constEnd(); ++it) {
            const QJsonObject e = it->toObject();
            const qint64 pos = ns(e.value(QLatin1String("position_ns")));
            if (pos > 0)
                items.append({{it.key(), pos, ns(e.value(QLatin1String("duration_ns")))},
                              e.value(QLatin1String("updated_at")).toDouble(0)});
        }
    }
    std::stable_sort(items.begin(), items.end(), [](const Item &a, const Item &b) { return a.updatedAt > b.updatedAt; });
    QList<Entry> result;
    for (const Item &item : std::as_const(items)) {
        // 파일 확인(네트워크 폴더면 느릴 수 있음)은 잠금 밖에서
        if (available ? available(item.entry.path) : library::isFile(item.entry.path))
            result.append(item.entry);
        if (result.size() >= limit)
            break;
    }
    return result;
}

// ---------------------------------------------------------------- BookmarkCache

BookmarkCache::BookmarkCache(const QString &path) : JsonStore(defaultPath(path, "bookmarks.json")) { load(); }

bool BookmarkCache::acceptLoaded(const QJsonValue &value)
{
    if (!value.isObject())
        return false;
    m_data = value.toObject();
    return true;
}

QByteArray BookmarkCache::serialize() const { return toJson(m_data); }

QVariantList BookmarkCache::get(const QString &filePath) const
{
    QMutexLocker lock(&m_mutex);
    return m_data.value(filePath).toArray().toVariantList();
}

QPair<bool, QString> BookmarkCache::add(const QString &filePath, qint64 positionNs, const QString &labelIn)
{
    if (filePath.isEmpty())
        return {false, QStringLiteral("재생 중인 영상이 없습니다.")};
    QString label = labelIn;
    if (label.isEmpty()) {
        const qint64 total = qint64(double(positionNs) / double(kNsPerSecond));
        const qint64 h = total / 3600, m = (total / 60) % 60, s = total % 60;
        label = h > 0 ? QString::asprintf("%02lld:%02lld:%02lld", h, m, s) : QString::asprintf("%02lld:%02lld", m, s);
    }
    QMutexLocker lock(&m_mutex);
    QJsonArray entries = m_data.value(filePath).toArray();
    for (const QJsonValue &item : std::as_const(entries))
        if (std::llabs(ns(item.toObject().value(QLatin1String("position_ns"))) - positionNs) < kNsPerSecond)
            return {false, QStringLiteral("이미 등록된 북마크 지점입니다.")};
    QList<QJsonValue> list(entries.begin(), entries.end());
    list.append(QJsonObject{{"position_ns", positionNs}, {"label", label}, {"created_at", nowSeconds()}});
    std::stable_sort(list.begin(), list.end(), [](const QJsonValue &a, const QJsonValue &b) {
        return ns(a.toObject().value(QLatin1String("position_ns"))) < ns(b.toObject().value(QLatin1String("position_ns")));
    });
    QJsonArray sorted;
    for (const QJsonValue &v : std::as_const(list))
        sorted.append(v);
    m_data.insert(filePath, sorted);
    markDirty();
    return {true, label};
}

bool BookmarkCache::remove(const QString &filePath, int index)
{
    QMutexLocker lock(&m_mutex);
    QJsonArray entries = m_data.value(filePath).toArray();
    if (index < 0 || index >= entries.size())
        return false;
    entries.removeAt(index);
    m_data.insert(filePath, entries);
    markDirty();
    return true;
}

// ---------------------------------------------------------------- HistoryCache

HistoryCache::HistoryCache(const QString &path) : JsonStore(defaultPath(path, "history.json")) { load(); }

bool HistoryCache::acceptLoaded(const QJsonValue &value)
{
    if (!value.isArray())
        return false;
    m_data = value.toArray();
    return true;
}

QByteArray HistoryCache::serialize() const { return toJson(m_data); }

void HistoryCache::add(const QString &path)
{
    if (path.isEmpty() || !library::pathExists(path))
        return;
    const QString abs = library::absPath(path);
    QString title = QFileInfo(abs).fileName();
    if (title.isEmpty())
        title = abs;
    const QJsonObject entry{{"path", abs}, {"title", title}, {"is_dir", QFileInfo(abs).isDir()}, {"timestamp", nowSeconds()}};
    QMutexLocker lock(&m_mutex);
    QJsonArray next{entry};
    for (const QJsonValue &h : std::as_const(m_data))
        if (h.isObject() && h.toObject().value(QLatin1String("path")) != QJsonValue(abs) && next.size() < kHistoryLimit)
            next.append(h);
    m_data = next;
    markDirty();
}

QVariantList HistoryCache::all() const
{
    QMutexLocker lock(&m_mutex);
    return m_data.toVariantList();
}

// ---------------------------------------------------------------- LoudnessCache

QString fileKey(const QString &path)
{
    const auto sig = fileSignature(path);
    if (!sig)
        return {};
    return QStringLiteral("%1|%2|%3").arg(library::absPath(path)).arg(sig->second).arg(qint64(std::trunc(sig->first)));
}

LoudnessCache::LoudnessCache(const QString &path) : JsonStore(defaultPath(path, "loudness.json")) { load(); }

void LoudnessCache::resetData()
{
    m_order.clear();
    m_values.clear();
}

bool LoudnessCache::acceptLoaded(const QJsonValue &value)
{
    if (!value.isObject())
        return false;
    // 주의: QJsonObject는 키 순서를 보존하지 않아, 불러온 항목들 사이의 오래된 순서는 키 이름순이 됩니다.
    resetData();
    const QJsonObject in = value.toObject();
    for (auto it = in.constBegin(); it != in.constEnd(); ++it) {
        if (it->isNull())
            m_values.insert(it.key(), std::nullopt);
        else if (it->isDouble())
            m_values.insert(it.key(), it->toDouble());
        else
            continue;
        m_order << it.key();
    }
    return true;
}

void LoudnessCache::beforeSave()
{
    while (m_order.size() > kMaxEntries)
        m_values.remove(m_order.takeFirst());
}

QByteArray LoudnessCache::serialize() const
{
    QList<QPair<QString, QJsonValue>> items;
    items.reserve(m_order.size());
    for (const QString &k : m_order) {
        const auto v = m_values.value(k);
        items.append({k, v ? QJsonValue(*v) : QJsonValue(QJsonValue::Null)});
    }
    return json::serializeOrderedObject(items);
}

QPair<bool, std::optional<double>> LoudnessCache::lookup(const QString &path) const
{
    const QString key = fileKey(path);
    QMutexLocker lock(&m_mutex);
    if (!key.isNull() && m_values.contains(key))
        return {true, m_values.value(key)};
    return {false, std::nullopt};
}

void LoudnessCache::store(const QString &path, std::optional<double> lufs)
{
    const QString key = fileKey(path);
    if (key.isNull())
        return;
    QMutexLocker lock(&m_mutex);
    m_order.removeAll(key);
    m_order.append(key);
    m_values.insert(key, lufs ? std::optional<double>(std::round(*lufs * 100.0) / 100.0) : std::nullopt);
    markDirty();
}

// ---------------------------------------------------------------- 전역 인스턴스

HWSupportCache &hwCache()
{
    static HWSupportCache c;
    return c;
}

ResumeCache &resumeCache()
{
    static ResumeCache c;
    return c;
}

BookmarkCache &bookmarkCache()
{
    static BookmarkCache c;
    return c;
}

HistoryCache &historyCache()
{
    static HistoryCache c;
    return c;
}

LoudnessCache &loudnessCache()
{
    static LoudnessCache c;
    return c;
}

void saveAllStores()
{
    hwCache().save();
    resumeCache().save();
    bookmarkCache().save();
    historyCache().save();
    loudnessCache().save();
}

} // namespace jvp
