#pragma once
// QML Image 공급자: "image://qr/<URL 인코딩된 글자>" → QR 코드 이미지 (웹 리모컨 접속 안내)

#include "QrCode.h"

#include <QQuickImageProvider>
#include <QUrl>

namespace jvp {

class QrImageProvider : public QQuickImageProvider {
public:
    QrImageProvider() : QQuickImageProvider(QQuickImageProvider::Image) {}

    QImage requestImage(const QString &id, QSize *size, const QSize &requested) override
    {
        const QString text = QUrl::fromPercentEncoding(id.toUtf8());
        QImage img = qrImage(text, 8, 3);
        if (img.isNull())
            img = QImage(8, 8, QImage::Format_RGB32), img.fill(Qt::white);
        if (requested.isValid())
            img = img.scaled(requested, Qt::KeepAspectRatio, Qt::FastTransformation);   // 모듈 경계를 흐리지 않게
        if (size)
            *size = img.size();
        return img;
    }
};

} // namespace jvp
