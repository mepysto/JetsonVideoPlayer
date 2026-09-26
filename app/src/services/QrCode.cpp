#include "QrCode.h"

#include "vendor/qrcodegen.hpp"

#include <QLoggingCategory>
#include <QPainter>
#include <optional>
#include <stdexcept>

Q_LOGGING_CATEGORY(lcQr, "jvp.qr")

namespace jvp {

namespace {
std::optional<qrcodegen::QrCode> encode(const QString &text)
{
    try {
        return qrcodegen::QrCode::encodeText(text.toUtf8().constData(), qrcodegen::QrCode::Ecc::MEDIUM);
    } catch (const std::exception &e) {   // data_too_long
        qCWarning(lcQr) << "⚠️ QR 코드를 만들 수 없습니다:" << e.what();
        return std::nullopt;
    }
}
} // namespace

int qrModuleCount(const QString &text)
{
    const auto qr = encode(text);
    return qr ? qr->getSize() : 0;
}

QImage qrImage(const QString &text, int scale, int border)
{
    scale = qMax(1, scale);
    border = qMax(0, border);
    const auto qr = encode(text);
    if (!qr)
        return {};
    const int n = qr->getSize();
    const int side = (n + 2 * border) * scale;
    QImage img(side, side, QImage::Format_RGB32);
    img.fill(Qt::white);
    QPainter p(&img);
    for (int y = 0; y < n; ++y)
        for (int x = 0; x < n; ++x)
            if (qr->getModule(x, y))
                p.fillRect((x + border) * scale, (y + border) * scale, scale, scale, Qt::black);
    return img;
}

} // namespace jvp
