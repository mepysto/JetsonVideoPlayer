#include "AssRenderer.h"

#include <QLoggingCategory>
#include <QMutexLocker>
#include <QRect>
#include <algorithm>
#include <cstdarg>

extern "C" {
#include <ass/ass.h>
}

Q_LOGGING_CATEGORY(lcAss, "jvp.ass")

namespace jvp {

namespace {

void assMessage(int level, const char *fmt, va_list args, void *)
{
    // libass 수준: 0 치명, 1 오류, 2 경고, 4 정보 … 7 디버그. 정보 이하는 글꼴 선택 등 잡음이라 debug로만.
    const QString msg = QString::vasprintf(fmt, args).trimmed();
    if (level <= 2)
        qCWarning(lcAss).noquote() << msg;
    else
        qCDebug(lcAss).noquote() << msg;
}

inline uint div255(uint v) { return (v + 128 + ((v + 128) >> 8)) >> 8; }

} // namespace

AssRenderer::AssRenderer()
{
    m_library = ass_library_init();
    if (!m_library) {
        qCWarning(lcAss) << "⚠️ libass 초기화 실패";
        return;
    }
    ass_set_message_cb(m_library, assMessage, nullptr);
    ass_set_extract_fonts(m_library, 1); // 스크립트 안 [Fonts] 섹션의 글꼴도 사용
    m_renderer = ass_renderer_init(m_library);
    if (!m_renderer)
        qCWarning(lcAss) << "⚠️ libass 렌더러 초기화 실패";
}

AssRenderer::~AssRenderer()
{
    if (m_track)
        ass_free_track(m_track);
    if (m_renderer)
        ass_renderer_done(m_renderer);
    if (m_library)
        ass_library_done(m_library);
}

void AssRenderer::resetTrack()
{
    if (m_track)
        ass_free_track(m_track);
    m_track = nullptr;
    m_dirty = true;
}

bool AssRenderer::loadFile(const QString &path)
{
    const subtitles::SubtitleText t = subtitles::readSubtitleText(path);
    if (!t.ok) {
        qCWarning(lcAss) << "⚠️ ASS 파일을 열 수 없음:" << path;
        return false;
    }
    return loadData(t.content);
}

bool AssRenderer::loadData(const QString &content)
{
    QMutexLocker lock(&m_mutex);
    resetTrack();
    if (!m_library)
        return false;
    // 인코딩 판별은 우리가 이미 했으므로 libass에는 UTF-8을 넘기고 codepage는 비웁니다.
    QByteArray utf8 = content.toUtf8();
    m_track = ass_read_memory(m_library, utf8.data(), size_t(utf8.size()), nullptr);
    if (!m_track)
        qCWarning(lcAss) << "⚠️ ASS 스크립트 해석 실패";
    return m_track != nullptr;
}

bool AssRenderer::loadEmbeddedHeader(const QByteArray &codecPrivate)
{
    QMutexLocker lock(&m_mutex);
    resetTrack();
    if (!m_library)
        return false;
    m_track = ass_new_track(m_library);
    if (!m_track)
        return false;
    QByteArray copy = codecPrivate; // libass API가 char*를 받으므로 사본
    ass_process_codec_private(m_track, copy.data(), int(copy.size()));
    return true;
}

void AssRenderer::addChunk(const QByteArray &data, qint64 startMs, qint64 durationMs)
{
    QMutexLocker lock(&m_mutex);
    if (!m_track || data.isEmpty())
        return;
    QByteArray copy = data;
    ass_process_chunk(m_track, copy.data(), int(copy.size()), startMs, durationMs);
    m_dirty = true;
}

void AssRenderer::addFont(const QString &name, const QByteArray &data)
{
    QMutexLocker lock(&m_mutex);
    if (!m_library || data.isEmpty())
        return;
    QByteArray n = name.toUtf8();
    ass_add_font(m_library, n.data(), data.constData(), int(data.size()));
    m_fontsReady = false; // 새 글꼴은 ass_set_fonts를 다시 불러야 보입니다
    m_dirty = true;
}

bool AssRenderer::hasTrack() const
{
    QMutexLocker lock(&m_mutex);
    return m_track != nullptr;
}

int AssRenderer::eventCount() const
{
    QMutexLocker lock(&m_mutex);
    return m_track ? m_track->n_events : 0;
}

QSize AssRenderer::playRes() const
{
    QMutexLocker lock(&m_mutex);
    return m_track ? QSize(m_track->PlayResX, m_track->PlayResY) : QSize();
}

SubtitleEvents AssRenderer::plainEvents() const
{
    struct Row {
        SubtitleEvent ev;
        int order;
    };
    QList<Row> rows;
    {
        QMutexLocker lock(&m_mutex);
        if (!m_track)
            return {};
        for (int i = 0; i < m_track->n_events; ++i) {
            const ASS_Event &e = m_track->events[i];
            if (e.Duration <= 0 || !e.Text)
                continue;
            const QString plain = subtitles::assTextToPlain(QString::fromUtf8(e.Text));
            if (!plain.isEmpty())
                rows.append({{e.Start, e.Start + e.Duration, plain}, i});
        }
    }
    std::stable_sort(rows.begin(), rows.end(), [](const Row &a, const Row &b) {
        return a.ev.startMs != b.ev.startMs ? a.ev.startMs < b.ev.startMs : a.order < b.order;
    });
    SubtitleEvents out;
    for (const Row &r : rows)
        out.append(r.ev);
    return out;
}

void AssRenderer::setStorageSize(const QSize &size)
{
    QMutexLocker lock(&m_mutex);
    if (size == m_storageSize)
        return;
    m_storageSize = size;
    if (m_renderer && size.isValid())
        ass_set_storage_size(m_renderer, size.width(), size.height());
    m_dirty = true;
}

bool AssRenderer::configure(const QSize &frameSize, qreal fontScale)
{
    if (!m_renderer)
        return false;
    if (!m_fontsReady) {
        // fontconfig로 시스템 글꼴을 찾습니다 (첫 호출은 글꼴 캐시 확인으로 조금 걸릴 수 있음)
        ass_set_fonts(m_renderer, nullptr, "sans-serif", ASS_FONTPROVIDER_AUTODETECT, nullptr, 1);
        m_fontsReady = true;
        m_dirty = true;
    }
    if (frameSize != m_frameSize) {
        m_frameSize = frameSize;
        ass_set_frame_size(m_renderer, frameSize.width(), frameSize.height());
        if (!m_storageSize.isValid()) // 원본 크기를 모르면 화면비 보정 없이 프레임 크기 기준
            ass_set_storage_size(m_renderer, frameSize.width(), frameSize.height());
        m_dirty = true;
    }
    if (!qFuzzyCompare(fontScale, m_fontScale)) {
        m_fontScale = fontScale;
        ass_set_font_scale(m_renderer, fontScale);
        m_dirty = true;
    }
    return true;
}

QImage AssRenderer::render(qint64 timeMs, const QSize &frameSize, qreal fontScale, bool *changed)
{
    QMutexLocker lock(&m_mutex);
    auto finish = [&](const QImage &img, bool diff) {
        if (changed)
            *changed = diff;
        return img;
    };
    if (!m_track || frameSize.isEmpty() || !configure(frameSize, fontScale)) {
        const bool diff = !m_last.isNull();
        m_last = QImage();
        return finish(m_last, diff);
    }

    int detect = 0;
    ASS_Image *images = ass_render_frame(m_renderer, m_track, timeMs, &detect);
    if (detect == 0 && !m_dirty)
        return finish(m_last, false); // libass가 같다고 보장 — 다시 합성할 필요 없음
    m_dirty = false;

    QRect bounds;
    for (ASS_Image *img = images; img; img = img->next)
        if (img->w > 0 && img->h > 0)
            bounds |= QRect(img->dst_x, img->dst_y, img->w, img->h);
    bounds &= QRect(QPoint(0, 0), frameSize);
    if (bounds.isEmpty()) {
        const bool diff = !m_last.isNull();
        m_last = QImage();
        return finish(m_last, diff);
    }

    // libass는 단색 알파 비트맵 목록을 돌려주므로 순서대로 "over" 합성합니다.
    QImage out(bounds.size(), QImage::Format_ARGB32_Premultiplied);
    out.fill(Qt::transparent);
    for (ASS_Image *img = images; img; img = img->next) {
        if (img->w <= 0 || img->h <= 0)
            continue;
        const uint r = (img->color >> 24) & 0xFF, g = (img->color >> 16) & 0xFF, b = (img->color >> 8) & 0xFF;
        const uint alpha = 255 - (img->color & 0xFF); // ASS 알파는 0이 불투명
        if (alpha == 0)
            continue;
        const QRect dst = QRect(img->dst_x, img->dst_y, img->w, img->h) & bounds;
        for (int y = dst.top(); y <= dst.bottom(); ++y) {
            const unsigned char *src = img->bitmap + (y - img->dst_y) * img->stride;
            QRgb *line = reinterpret_cast<QRgb *>(out.scanLine(y - bounds.top()));
            for (int x = dst.left(); x <= dst.right(); ++x) {
                const uint k = div255(src[x - img->dst_x] * alpha);
                if (!k)
                    continue;
                QRgb &p = line[x - bounds.left()];
                const uint inv = 255 - k;
                p = qRgba(div255(r * k + qRed(p) * inv), div255(g * k + qGreen(p) * inv),
                          div255(b * k + qBlue(p) * inv), k + div255(qAlpha(p) * inv));
            }
        }
    }
    out.setOffset(bounds.topLeft());
    m_last = out;
    return finish(m_last, true);
}

} // namespace jvp
