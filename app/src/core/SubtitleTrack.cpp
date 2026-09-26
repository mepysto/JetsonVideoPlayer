#include "SubtitleTrack.h"

#include "AssRenderer.h"

#include <QMutexLocker>
#include <algorithm>

namespace jvp {

QString shortBadge(const QString &label)
{
    static const QList<QPair<QString, QString>> badges = {
        {QStringLiteral("한국어"), QStringLiteral("[KR] ")},  {QStringLiteral("영어"), QStringLiteral("[EN] ")},
        {QStringLiteral("중국어"), QStringLiteral("[TW] ")},  {QStringLiteral("대만"), QStringLiteral("[TW] ")},
        {QStringLiteral("zh-tw"), QStringLiteral("[TW] ")},   {QStringLiteral("일본어"), QStringLiteral("[JP] ")},
        {QStringLiteral("스페인어"), QStringLiteral("[ES] ")}, {QStringLiteral("프랑스어"), QStringLiteral("[FR] ")},
        {QStringLiteral("독일어"), QStringLiteral("[DE] ")},  {QStringLiteral("AI"), QStringLiteral("[AI] ")},
    };
    const QString lower = label.toLower();
    for (const auto &[key, badge] : badges)
        if (lower.contains(key.toLower()))
            return badge;
    return {};
}

SubtitleTrack::SubtitleTrack(const QString &label, const QString &color, const SubtitleEvents &events,
                             std::shared_ptr<AssRenderer> ass)
    : m_label(label), m_color(color), m_ass(std::move(ass))
{
    addEvents(events);
}

std::shared_ptr<AssRenderer> SubtitleTrack::assRenderer() const
{
    QMutexLocker lock(&m_mutex);
    return m_ass;
}

void SubtitleTrack::setAssRenderer(std::shared_ptr<AssRenderer> ass)
{
    QMutexLocker lock(&m_mutex);
    m_ass = std::move(ass);
}

void SubtitleTrack::addEvents(const SubtitleEvents &events)
{
    SubtitleEvents fresh;
    for (const SubtitleEvent &e : events)
        if (e.endMs > e.startMs && !e.text.trimmed().isEmpty())
            fresh.append(e);
    if (fresh.isEmpty())
        return;
    QMutexLocker lock(&m_mutex);
    qint64 longest = 0;
    bool added = false;
    for (const SubtitleEvent &e : fresh) {
        if (!m_seen.emplace(e.startMs, e.endMs, e.text).second)
            continue;
        m_events.append(e);
        longest = std::max(longest, e.endMs - e.startMs);
        added = true;
    }
    if (!added)
        return;
    std::stable_sort(m_events.begin(), m_events.end(), [](const SubtitleEvent &a, const SubtitleEvent &b) {
        return a.startMs != b.startMs ? a.startMs < b.startMs : a.endMs < b.endMs;
    });
    m_starts.resize(m_events.size());
    for (qsizetype i = 0; i < m_events.size(); ++i)
        m_starts[i] = m_events[i].startMs;
    m_maxDuration = std::max(m_maxDuration, longest);
}

int SubtitleTrack::size() const
{
    QMutexLocker lock(&m_mutex);
    return int(m_events.size());
}

SubtitleEvents SubtitleTrack::events() const
{
    QMutexLocker lock(&m_mutex);
    return m_events;
}

QStringList SubtitleTrack::activeAt(qint64 tMs) const
{
    QStringList found;
    QMutexLocker lock(&m_mutex);
    // t보다 늦게 시작하는 첫 이벤트 바로 앞에서부터, 가장 긴 대사 길이만큼만 거슬러 올라갑니다.
    qsizetype i = std::upper_bound(m_starts.cbegin(), m_starts.cend(), tMs) - m_starts.cbegin() - 1;
    for (; i >= 0 && m_starts[i] >= tMs - m_maxDuration; --i) {
        const SubtitleEvent &e = m_events[i];
        if (e.startMs <= tMs && tMs < e.endMs)
            found.prepend(e.text);
    }
    return found;
}

std::optional<qint64> SubtitleTrack::nextChangeAfter(qint64 tMs) const
{
    QMutexLocker lock(&m_mutex);
    const qsizetype idx = std::upper_bound(m_starts.cbegin(), m_starts.cend(), tMs) - m_starts.cbegin();
    std::optional<qint64> best;
    auto consider = [&](qint64 v) {
        if (!best || v < *best)
            best = v;
    };
    if (idx < m_starts.size())
        consider(m_starts[idx]);
    for (qsizetype i = idx - 1; i >= 0 && m_starts[i] >= tMs - m_maxDuration; --i)
        if (m_events[i].endMs > tMs)
            consider(m_events[i].endMs);
    return best;
}

QList<SubtitleLine> activeLines(const QList<SubtitleTrackPtr> &tracks, qint64 positionMs, qint64 offsetMs)
{
    const qint64 t = positionMs - offsetMs;
    const bool multi = tracks.size() > 1;
    QList<SubtitleLine> lines;
    for (const SubtitleTrackPtr &track : tracks) {
        if (!track || track->assRenderer())
            continue; // ASS 스타일 트랙은 AssRenderer가 따로 그립니다
        const QString badge = multi ? shortBadge(track->label()) : QString();
        const QString color = track->color().isEmpty() ? QStringLiteral("#FFFFFF") : track->color();
        for (const QString &text : track->activeAt(t)) {
            int n = 0;
            for (const QString &raw : text.split(QLatin1Char('\n'))) {
                const QString part = raw.trimmed();
                if (part.isEmpty())
                    continue;
                lines.append({(n++ == 0 ? badge : QString()) + part, color});
            }
        }
    }
    return lines;
}

} // namespace jvp
