#pragma once
// 영상을 그리는 Qt Quick 아이템. FrameBridge의 프레임을 렌더 스레드에서 GL 텍스처로 올려 그립니다.
// - NVMM(RGBA): NvBufSurface → EGLImage → GL_TEXTURE_EXTERNAL_OES (복사 없음)
// - 시스템 메모리 I420/NV12/RGBA: 평면별 텍스처 업로드 + 셰이더에서 YUV→RGB
// HDR(PQ/HLG) 톤매핑, 회전·반전, 레터박스를 셰이더/정점에서 처리합니다.

#include <QPointer>
#include <QQuickItem>

namespace jvp {

class FrameBridge;

class VideoItem : public QQuickItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QObject *bridge READ bridge WRITE setBridge NOTIFY bridgeChanged)
    Q_PROPERTY(int hdrMode READ hdrMode WRITE setHdrMode NOTIFY hdrChanged)          // 0 SDR, 1 PQ, 2 HLG
    Q_PROPERTY(bool hdrMatrixFix READ hdrMatrixFix WRITE setHdrMatrixFix NOTIFY hdrChanged)
    Q_PROPERTY(QString rotation READ rotation WRITE setRotation NOTIFY rotationChanged) // identity, 90r, 180, 90l, horiz, vert
    Q_PROPERTY(QRectF videoRect READ videoRect NOTIFY videoRectChanged)            // 아이템 안에서 영상이 그려지는 영역
    Q_PROPERTY(QSizeF videoSize READ videoSize NOTIFY videoRectChanged)

public:
    explicit VideoItem(QQuickItem *parent = nullptr);

    QObject *bridge() const;
    void setBridge(QObject *bridge);
    int hdrMode() const { return m_hdrMode; }
    void setHdrMode(int mode);
    bool hdrMatrixFix() const { return m_hdrFix; }
    void setHdrMatrixFix(bool fix);
    QString rotation() const { return m_rotation; }
    void setRotation(const QString &r);
    QRectF videoRect() const;
    QSizeF videoSize() const { return m_videoSize; }

signals:
    void bridgeChanged();
    void hdrChanged();
    void rotationChanged();
    void videoRectChanged();

protected:
    QSGNode *updatePaintNode(QSGNode *old, UpdatePaintNodeData *) override;
    void geometryChange(const QRectF &newGeometry, const QRectF &oldGeometry) override;

private:
    QPointer<FrameBridge> m_bridge;
    int m_hdrMode = 0;
    bool m_hdrFix = false;
    QString m_rotation = QStringLiteral("identity");
    QSizeF m_videoSize;   // 픽셀 종횡비를 반영한 표시 크기
};

} // namespace jvp
