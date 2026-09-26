#include "SubtitleController.h"

#include "AssRenderer.h"
#include "SubtitleParse.h"

#include <QFileInfo>
#include <QLoggingCategory>

Q_LOGGING_CATEGORY(lcSubs, "jvp.subtitles")

namespace jvp {

using namespace subtitles;

namespace {
const QString kEmbeddedColor = QStringLiteral("#FFFFFF");
bool isAssPath(const QString &path)
{
    const QString s = QFileInfo(path).suffix().toLower();
    return s == QLatin1String("ass") || s == QLatin1String("ssa");
}
} // namespace

SubtitleController::SubtitleController(QObject *parent) : QObject(parent) {}

std::shared_ptr<AssRenderer> SubtitleController::assFor(const QString &path) const
{
    if (!m_assStyles || path.isEmpty() || !isAssPath(path))
        return nullptr;
    auto r = std::make_shared<AssRenderer>();
    if (!r->loadFile(path))
        return nullptr;
    return r;
}

void SubtitleController::clear()
{
    m_entries.clear();
    m_active.clear();
    m_embedded = std::make_shared<SubtitleTrack>(QStringLiteral("💬 내장 자막"), kEmbeddedColor);
    m_embeddedAss.reset();
    m_embeddedLangs.clear();
    m_embeddedIndex = 0;
    emit changed();
}

void SubtitleController::loadForVideo(const QString &videoPath)
{
    clear();
    const QStringList files = findAllMatchingSubtitles(videoPath);
    for (int i = 0; i < files.size(); ++i) {
        const SubtitleEvents events = parseSubtitleFileEvents(files[i]);
        if (events.isEmpty())
            continue;
        Entry e;
        e.path = files[i];
        e.label = subtitleLabel(files[i]);
        e.color = subtitleColor(files[i], m_entries.size());
        e.track = std::make_shared<SubtitleTrack>(e.label, e.color, events, assFor(files[i]));
        m_entries << e;
    }
    // 기본은 첫 번째(한국어 우선 정렬) 하나만 켭니다 — 여러 자막이 화면을 가리지 않게.
    if (!m_entries.isEmpty()) {
        m_active = {0};
        m_enabled = true;
        qCInfo(lcSubs).noquote() << "💬 [자막 자동 활성화]" << m_entries.first().label
                                 << (m_entries.size() > 1 ? QStringLiteral("(총 %1개)").arg(m_entries.size()) : QString());
    }
    emit changed();
}

int SubtitleController::addFile(const QString &path, bool activate)
{
    const SubtitleEvents events = parseSubtitleFileEvents(path);
    if (events.isEmpty())
        return -1;
    Entry e;
    e.path = path;
    e.label = subtitleLabel(path);
    e.color = subtitleColor(path, m_entries.size());
    e.track = std::make_shared<SubtitleTrack>(e.label, e.color, events, assFor(path));
    m_entries << e;
    const int idx = m_entries.size() - 1;
    if (activate) {
        m_active.insert(idx);
        m_enabled = true;
    }
    emit changed();
    return idx;
}

int SubtitleController::addLive(const QString &label, const QString &color, bool isTranslation, const QString &lang)
{
    Entry e;
    e.label = label;
    e.color = color;
    e.isTranslation = isTranslation;
    e.lang = lang;
    e.track = std::make_shared<SubtitleTrack>(label, color);
    m_entries << e;
    const int idx = m_entries.size() - 1;
    m_active = {idx};   // 만드는 중인 자막을 바로 보여 줍니다
    m_enabled = true;
    emit changed();
    return idx;
}

SubtitleController::Entry *SubtitleController::entry(int index)
{
    return index >= 0 && index < m_entries.size() ? &m_entries[index] : nullptr;
}

int SubtitleController::indexOfTrack(const SubtitleTrackPtr &track) const
{
    for (int i = 0; i < m_entries.size(); ++i)
        if (m_entries[i].track == track)
            return i;
    return -1;
}

void SubtitleController::removeEntry(int index)
{
    if (index < 0 || index >= m_entries.size())
        return;
    m_entries.removeAt(index);
    QSet<int> shifted;
    for (int a : std::as_const(m_active))
        if (a != index)
            shifted.insert(a > index ? a - 1 : a);
    m_active = shifted;
    if (m_active.isEmpty() && !m_entries.isEmpty())
        m_active = {0};
    emit changed();
}

void SubtitleController::updateEntry(int index, const QString &path, const QString &label, const QString &lang)
{
    Entry *e = entry(index);
    if (!e)
        return;
    if (!path.isNull())
        e->path = path;
    if (!label.isNull()) {
        e->label = label;
        e->track->setLabel(label);   // 트랙 객체는 그대로 (작업이 들고 있는 포인터가 계속 유효)
    }
    if (!lang.isNull())
        e->lang = lang;
    emit changed();
}

void SubtitleController::setActiveOnly(int index)
{
    m_active = {index};
    m_enabled = true;
    emit changed();
}

void SubtitleController::resetEmbedded(const QStringList &languages, int current)
{
    m_embedded = std::make_shared<SubtitleTrack>(QStringLiteral("💬 내장 자막"), kEmbeddedColor);
    m_embeddedAss.reset();
    setEmbeddedTracks(languages, current);
}

void SubtitleController::setEmbeddedTracks(const QStringList &languages, int current)
{
    if (languages.size() != m_embeddedLangs.size() && !languages.isEmpty())
        qCInfo(lcSubs) << "💬 [내장 자막 감지]" << languages.size() << "개 트랙";
    m_embeddedLangs = languages;
    m_embeddedIndex = qBound(0, current, qMax(0, int(languages.size()) - 1));
    emit changed();
}

QString SubtitleController::embeddedLabel() const
{
    const QString lang = m_embeddedLangs.value(m_embeddedIndex);
    return QStringLiteral("내장 자막 %1/%2").arg(m_embeddedIndex + 1).arg(m_embeddedLangs.size())
           + (lang.isEmpty() ? QString() : QStringLiteral(" (%1)").arg(lang));
}

void SubtitleController::setEmbeddedEnabled(bool on)
{
    m_embeddedEnabled = on;
    emit changed();
}

void SubtitleController::addEmbeddedText(qint64 startMs, qint64 endMs, const QString &text)
{
    if (m_embedded)
        m_embedded->addEvents({SubtitleEvent{startMs, endMs, text}});
}

void SubtitleController::addEmbeddedAss(const QString &header, qint64 startMs, qint64 endMs, const QString &block)
{
    if (!m_embedded)
        return;
    if (m_assStyles && !m_embeddedAss) {
        auto r = std::make_shared<AssRenderer>();
        if (r->loadEmbeddedHeader(header.toUtf8())) {
            m_embeddedAss = r;
            m_embedded->setAssRenderer(r);
        }
    }
    if (m_embeddedAss)
        m_embeddedAss->addChunk(block.toUtf8(), startMs, endMs - startMs);
    // 검색·리모컨용 글자도 같이 쌓습니다 (ASS 트랙은 일반 자막 그리기에서 빠짐)
    const QString plain = assBlockToPlain(block);
    if (!plain.isEmpty())
        m_embedded->addEvents({SubtitleEvent{startMs, endMs, plain}});
}

QList<SubtitleTrackPtr> SubtitleController::activeTracks() const
{
    QList<SubtitleTrackPtr> out;
    if (!m_enabled)
        return out;
    QList<int> idx(m_active.begin(), m_active.end());
    std::sort(idx.begin(), idx.end());
    for (int i : idx)
        if (i >= 0 && i < m_entries.size())
            out << m_entries[i].track;
    // 외부 자막이 없을 때만 내장 자막을 보여 줍니다
    if (m_entries.isEmpty() && embeddedCount() > 0 && m_embeddedEnabled && m_embedded)
        out << m_embedded;
    return out;
}

QString SubtitleController::buttonText() const
{
    const int total = int(m_entries.size());
    if (total == 0 && embeddedCount() > 0) {
        const QString count = embeddedCount() > 1 ? QStringLiteral(" (%1)").arg(embeddedCount()) : QString();
        return QStringLiteral("💬 내장%1 %2").arg(count, m_embeddedEnabled ? "ON" : "OFF");
    }
    if (total == 0)
        return QStringLiteral("💬 자막 없음");
    if (total == 1)
        return m_enabled && !m_active.isEmpty() ? QStringLiteral("💬 자막 ON") : QStringLiteral("💬 자막 OFF");
    return QStringLiteral("💬 자막 (%1/%2)").arg(m_enabled ? m_active.size() : 0).arg(total);
}

QVariantList SubtitleController::tracksForQml() const
{
    QVariantList list;
    for (int i = 0; i < m_entries.size(); ++i)
        list << QVariantMap{{"label", m_entries[i].label}, {"color", m_entries[i].color},
                            {"active", m_enabled && m_active.contains(i)}, {"path", m_entries[i].path}};
    return list;
}

void SubtitleController::toggle()
{
    if (m_entries.isEmpty()) {
        if (embeddedCount() > 0)
            toggleEmbedded();
        else
            qCInfo(lcSubs) << "ℹ️ 현재 영상에 로드된 자막이 없습니다.";
        return;
    }
    m_enabled = !m_enabled;
    if (m_enabled && m_active.isEmpty())
        for (int i = 0; i < m_entries.size(); ++i)
            m_active.insert(i);
    emit osd(m_enabled ? QStringLiteral("💬 자막 ON") : QStringLiteral("💬 자막 OFF"));
    emit changed();
}

void SubtitleController::buttonClicked()
{
    if (m_entries.isEmpty()) {
        if (embeddedCount() > 1)
            cycleEmbeddedTrack();
        else if (embeddedCount() == 1)
            toggleEmbedded();
        return;
    }
    if (m_entries.size() == 1)
        toggle();
    else
        emit popupRequested();
}

void SubtitleController::toggleTrack(int index)
{
    if (index < 0 || index >= m_entries.size())
        return;
    if (!m_enabled) {
        m_enabled = true;
        m_active.clear();
    }
    if (m_active.contains(index))
        m_active.remove(index);
    else
        m_active.insert(index);
    if (m_active.isEmpty())
        m_enabled = false;
    emit changed();
}

void SubtitleController::toggleEmbedded()
{
    m_embeddedEnabled = !m_embeddedEnabled;
    emit osd(QStringLiteral("💬 %1 %2").arg(embeddedLabel(), m_embeddedEnabled ? "ON" : "OFF"));
    emit changed();
}

void SubtitleController::cycleEmbeddedTrack()
{
    // 트랙1 → 트랙2 → … → 끄기 → 트랙1
    if (embeddedCount() <= 0)
        return;
    int next = 0;
    if (!m_embeddedEnabled) {
        m_embeddedEnabled = true;
    } else {
        next = m_embeddedIndex + 1;
        if (next >= embeddedCount()) {
            m_embeddedEnabled = false;
            next = m_embeddedIndex;
        }
    }
    const bool trackChanged = next != m_embeddedIndex;
    m_embeddedIndex = next;
    // 트랙이 바뀌면 이전 트랙에서 미리 받아 둔 대사를 버립니다.
    m_embedded = std::make_shared<SubtitleTrack>(QStringLiteral("💬 내장 자막"), kEmbeddedColor);
    m_embeddedAss.reset();
    if (trackChanged)
        emit embeddedTrackRequested(m_embeddedIndex);
    emit osd(m_embeddedEnabled ? QStringLiteral("💬 %1").arg(embeddedLabel()) : QStringLiteral("💬 내장 자막 OFF"));
    emit changed();
}

void SubtitleController::setFontScale(double s)
{
    m_fontScale = qBound(0.6, s, 1.6);
    emit changed();
}

void SubtitleController::adjustScale(double delta)
{
    const double s = qRound(qBound(0.6, m_fontScale + delta, 1.6) * 100) / 100.0;
    if (qFuzzyCompare(s, m_fontScale))
        return;
    setFontScale(s);
    emit fontScaleChanged(m_fontScale);
    emit osd(QStringLiteral("🗚 자막 크기: %1%").arg(int(m_fontScale * 100 + 0.5)));
}

void SubtitleController::resetScale()
{
    if (qFuzzyCompare(m_fontScale, 1.0))
        return;
    setFontScale(1.0);
    emit fontScaleChanged(m_fontScale);
    emit osd(QStringLiteral("🗚 자막 크기: 100%"));
}

static QString signedSeconds(int ms)
{
    return QStringLiteral("%1%2s").arg(ms >= 0 ? "+" : "").arg(ms / 1000.0, 0, 'f', 1);
}

void SubtitleController::adjustSync(int deltaMs)
{
    m_offsetMs += deltaMs;
    emit osd(QStringLiteral("⏱️ 자막 싱크: %1").arg(signedSeconds(m_offsetMs)));
    emit changed();
}

void SubtitleController::resetSync()
{
    if (m_offsetMs == 0)
        return;
    m_offsetMs = 0;
    emit osd(QStringLiteral("⏱️ 자막 싱크: 0.0s"));
    emit changed();
}

void SubtitleController::setAssStyles(bool on)
{
    m_assStyles = on;
    for (Entry &e : m_entries)
        if (e.track)
            e.track->setAssRenderer(on ? assFor(e.path) : nullptr);
    emit changed();
}

} // namespace jvp
