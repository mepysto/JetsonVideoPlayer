#pragma once
// 영상 위 자막 그리기: 일반 자막(외곽선·언어별 색·아래에서 위로 쌓기)과 ASS(libass 이미지).
// 40ms마다 재생 위치를 보고 표시할 내용이 바뀌었을 때만 다시 그립니다.

#include <QtQml/qqmlregistration.h>
#include <QPointer>
#include <QQuickPaintedItem>
#include <QTimer>

#include "SubtitleTrack.h"

namespace jvp {

class SubtitleController;

class SubtitleOverlay : public QQuickPaintedItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QObject *controller READ controller WRITE setController NOTIFY controllerChanged)
    Q_PROPERTY(QRectF videoRect READ videoRect WRITE setVideoRect NOTIFY videoRectChanged)
public:
    explicit SubtitleOverlay(QQuickItem *parent = nullptr);

    QObject *controller() const;
    void setController(QObject *c);
    QRectF videoRect() const { return m_videoRect; }
    void setVideoRect(const QRectF &r);

    void paint(QPainter *painter) override;

    // 테스트·HUD용: 지금 보이는 일반 자막 줄
    QList<SubtitleLine> currentLines() const { return m_lines; }

signals:
    void controllerChanged();
    void videoRectChanged();

private:
    void tick();

    QPointer<SubtitleController> m_controller;
    QRectF m_videoRect;
    QTimer m_timer;
    QList<SubtitleLine> m_lines;
    QList<QImage> m_assImages;
    qint64 m_lastPos = -1;
};

} // namespace jvp
