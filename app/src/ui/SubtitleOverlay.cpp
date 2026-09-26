#include "SubtitleOverlay.h"

#include "AssRenderer.h"
#include "SubtitleController.h"

#include <QFontMetricsF>
#include <QPainter>
#include <QPainterPath>
#include <QQuickWindow>
#include <QTextLayout>

namespace jvp {

namespace {
// 파이썬 버전과 같은 글꼴 (한글이 있는 Noto CJK를 우선)
const QString kFontFamily = QStringLiteral("Noto Sans CJK KR");
constexpr int kTickMs = 40;
} // namespace

SubtitleOverlay::SubtitleOverlay(QQuickItem *parent) : QQuickPaintedItem(parent)
{
    setAcceptedMouseButtons(Qt::NoButton);   // 클릭은 아래 영상 영역으로
    setAntialiasing(true);
    m_timer.setInterval(kTickMs);
    connect(&m_timer, &QTimer::timeout, this, &SubtitleOverlay::tick);
    m_timer.start();
}

QObject *SubtitleOverlay::controller() const { return m_controller.data(); }

void SubtitleOverlay::setController(QObject *c)
{
    m_controller = qobject_cast<SubtitleController *>(c);
    if (m_controller)
        connect(m_controller, &SubtitleController::changed, this, [this] { m_lastPos = -2; tick(); });
    emit controllerChanged();
}

void SubtitleOverlay::setVideoRect(const QRectF &r)
{
    if (r == m_videoRect)
        return;
    m_videoRect = r;
    m_lastPos = -2;   // 크기가 바뀌면 ASS를 다시 그림
    emit videoRectChanged();
    tick();
}

void SubtitleOverlay::tick()
{
    if (!m_controller || !isVisible())
        return;
    const QList<SubtitleTrackPtr> tracks = m_controller->activeTracks();
    const qint64 pos = m_controller->positionMs();
    QList<SubtitleLine> lines;
    QList<QImage> ass;
    bool assChanged = false;
    if (pos >= 0 && !tracks.isEmpty()) {
        lines = activeLines(tracks, pos, m_controller->offsetMs());
        const QRectF vr = m_videoRect.isEmpty() ? boundingRect() : m_videoRect;
        const qreal dpr = window() ? window()->effectiveDevicePixelRatio() : 1.0;
        const QSize px = (vr.size() * dpr).toSize();
        for (const SubtitleTrackPtr &t : tracks) {
            if (auto r = t->assRenderer()) {
                bool changed = false;
                QImage img = r->render(pos - m_controller->offsetMs(), px, m_controller->fontScale(), &changed);
                assChanged |= changed || m_lastPos == -2;
                if (!img.isNull()) {
                    img.setDevicePixelRatio(dpr);
                    ass << img;
                }
            }
        }
    }
    const bool assCountChanged = ass.size() != m_assImages.size();
    if (lines != m_lines || assChanged || assCountChanged) {
        m_lines = lines;
        m_assImages = ass;
        update();
    }
    m_lastPos = pos;
}

void SubtitleOverlay::paint(QPainter *p)
{
    const QRectF vr = m_videoRect.isEmpty() ? boundingRect() : m_videoRect;
    for (const QImage &img : std::as_const(m_assImages))
        p->drawImage(vr.topLeft(), img);
    if (m_lines.isEmpty() || !m_controller)
        return;

    // 일반 자막: 영상 높이의 5.2% (여러 트랙이면 조금 작게), 아래 6% 여백에서 위로 쌓기
    const int nTracks = qMax(1, int(m_controller->activeTracks().size()));
    const qreal factor = nTracks == 1 ? 0.052 : (nTracks == 2 ? 0.042 : 0.035);
    const qreal fontPx = qMax<qreal>(12, vr.height() * factor * m_controller->fontScale());
    QFont font(kFontFamily);
    font.setPixelSize(int(fontPx));
    font.setBold(true);
    QFontMetricsF fm(font);
    const qreal maxWidth = vr.width() * 0.92;
    const qreal outline = qMax<qreal>(2.0, fontPx * 0.14);
    p->setRenderHint(QPainter::Antialiasing);

    // 줄바꿈된 줄 단위로 모아 아래에서 위로 배치
    struct Piece { QString text; QColor color; };
    QList<Piece> pieces;
    for (const SubtitleLine &l : m_lines) {
        QTextLayout layout(l.text, font);
        layout.beginLayout();
        while (true) {
            QTextLine tl = layout.createLine();
            if (!tl.isValid())
                break;
            tl.setLineWidth(maxWidth);
        }
        layout.endLayout();
        for (int i = 0; i < layout.lineCount(); ++i) {
            const QTextLine tl = layout.lineAt(i);
            pieces << Piece{l.text.mid(tl.textStart(), tl.textLength()).trimmed(), QColor(l.color)};
        }
    }
    const qreal lineH = fm.height();
    const qreal gap = fontPx * 0.12;
    qreal y = vr.bottom() - vr.height() * 0.06;
    for (int i = pieces.size() - 1; i >= 0; --i) {
        const Piece &pc = pieces[i];
        const qreal w = fm.horizontalAdvance(pc.text);
        const qreal x = vr.left() + (vr.width() - w) / 2;
        QPainterPath path;
        path.addText(QPointF(x, y - fm.descent()), font, pc.text);
        p->strokePath(path, QPen(QColor(0, 0, 0, 235), outline * 2, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
        p->fillPath(path, pc.color.isValid() ? pc.color : Qt::white);
        y -= lineH + gap;
    }
}

} // namespace jvp
