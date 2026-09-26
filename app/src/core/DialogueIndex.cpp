#include "DialogueIndex.h"

#include <QFile>
#include <QMutexLocker>
#include <QRegularExpression>
#include <algorithm>

#include <sys/stat.h>

namespace jvp {

namespace {

// 파이썬 os.stat().st_mtime_ns — 같은 초 안의 변경도 알아채려고 나노초까지 봅니다.
bool mtimeNs(const QString &path, qint64 *out)
{
    struct stat st;
    if (::stat(QFile::encodeName(path).constData(), &st) != 0)
        return false;
    *out = qint64(st.st_mtim.tv_sec) * 1000000000LL + st.st_mtim.tv_nsec;
    return true;
}

} // namespace

DialogueIndex::DialogueIndex(FindSubtitles find, ParseSubtitle parse)
    : m_find(std::move(find)), m_parse(std::move(parse))
{
}

QString DialogueIndex::normalize(const QString &text)
{
    static const QRegularExpression spaces(QStringLiteral("\\s+"), QRegularExpression::UseUnicodePropertiesOption);
    // Qt의 toCaseFolded는 1:1 단순 접기라 파이썬 casefold()와 달리 ß를 ss로 바꾸지 않아 따로 처리
    return QString(text)
        .replace(spaces, QStringLiteral(" "))
        .trimmed()
        .toCaseFolded()
        .replace(QChar(0x00DF), QStringLiteral("ss"))
        .replace(QChar(0x1E9E), QStringLiteral("ss"));
}

bool DialogueIndex::build(const QStringList &videos, const std::function<bool()> &cancelled)
{
    quint64 generation;
    QHash<QString, Entry> known;
    {
        QMutexLocker lock(&m_mutex);
        m_videos = videos;
        generation = ++m_generation;
        known = m_entries;
    }
    QHash<QString, Entry> fresh;
    for (const QString &video : videos) {
        if (cancelled && cancelled())
            return false;
        Signature sig;
        for (const QString &p : m_find(video)) {
            qint64 ns;
            if (mtimeNs(p, &ns))
                sig.append({p, ns});
        }
        const auto cached = known.constFind(video);
        if (cached != known.cend() && cached->sig == sig) {
            fresh.insert(video, *cached);
            continue;
        }
        Entry entry{sig, {}};
        for (const auto &[subPath, mtime] : sig) {
            Q_UNUSED(mtime)
            const QString label = subtitles::subtitleLabel(subPath);
            for (const SubtitleEvent &e : m_parse(subPath))
                if (!e.text.trimmed().isEmpty())
                    entry.lines.append({e.startMs, normalize(e.text), e.text.trimmed(), label});
        }
        std::stable_sort(entry.lines.begin(), entry.lines.end(),
                         [](const Line &a, const Line &b) { return a.startMs < b.startMs; });
        fresh.insert(video, entry);
    }
    QMutexLocker lock(&m_mutex);
    if (m_generation == generation) // 그 사이 새 build가 시작됐으면 그쪽 결과가 이깁니다
        m_entries = fresh;
    return true;
}

void DialogueIndex::invalidate(const QString &video)
{
    QMutexLocker lock(&m_mutex);
    m_entries.remove(video);
}

QList<SearchHit> DialogueIndex::search(const QString &query, int limit, const QString &firstVideo) const
{
    const QString needle = normalize(query);
    if (needle.isEmpty())
        return {};
    QStringList order;
    QHash<QString, Entry> entries;
    {
        QMutexLocker lock(&m_mutex);
        order = m_videos;
        entries = m_entries; // 암시적 공유라 복사 비용 없음
    }
    if (!firstVideo.isEmpty() && entries.contains(firstVideo)) {
        order.removeAll(firstVideo);
        order.prepend(firstVideo);
    }
    QList<SearchHit> hits;
    for (const QString &video : order) {
        const auto it = entries.constFind(video);
        if (it == entries.cend())
            continue;
        for (const Line &line : it->lines) {
            if (!line.norm.contains(needle))
                continue;
            hits.append({video, line.startMs, line.text, line.label});
            if (hits.size() >= limit)
                return hits;
        }
    }
    return hits;
}

int DialogueIndex::lineCount() const
{
    QMutexLocker lock(&m_mutex);
    int n = 0;
    for (const Entry &e : m_entries)
        n += int(e.lines.size());
    return n;
}

} // namespace jvp
