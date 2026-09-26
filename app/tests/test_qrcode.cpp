// QR 코드 이미지: 크기, 여백, 세 모서리의 파인더 패턴
#include "QrCode.h"

#include <QtTest>

using namespace jvp;

class TestQrCode : public QObject {
    Q_OBJECT

    // 모듈 (mx, my)가 검은지 (여백 포함 좌표계 아님: QR 모듈 좌표)
    static bool dark(const QImage &img, int scale, int border, int mx, int my)
    {
        const int px = (mx + border) * scale + scale / 2, py = (my + border) * scale + scale / 2;
        return qGray(img.pixel(px, py)) < 128;
    }

    static void checkFinder(const QImage &img, int scale, int border, int ox, int oy)
    {
        // 7×7: 바깥 테두리 검정, 그 안 한 줄 흰색, 가운데 3×3 검정
        for (int y = 0; y < 7; ++y) {
            for (int x = 0; x < 7; ++x) {
                const bool ring = x == 0 || y == 0 || x == 6 || y == 6;
                const bool core = x >= 2 && x <= 4 && y >= 2 && y <= 4;
                QCOMPARE(dark(img, scale, border, ox + x, oy + y), ring || core);
            }
        }
    }

private Q_SLOTS:
    void imageSizeAndFinderPatterns()
    {
        const QString url = "http://192.168.0.10:8888/?pin=4242";
        const int n = qrModuleCount(url);
        QVERIFY(n >= 21 && (n - 17) % 4 == 0);   // 버전 v → 17 + 4v
        const int scale = 5, border = 2;
        const QImage img = qrImage(url, scale, border);
        QVERIFY(!img.isNull());
        QCOMPARE(img.width(), (n + 2 * border) * scale);
        QCOMPARE(img.height(), img.width());

        // 여백은 흰색
        for (int i = 0; i < img.width(); i += scale) {
            QCOMPARE(qGray(img.pixel(i, 0)), 255);
            QCOMPARE(qGray(img.pixel(0, i)), 255);
            QCOMPARE(qGray(img.pixel(img.width() - 1, i)), 255);
        }
        checkFinder(img, scale, border, 0, 0);
        checkFinder(img, scale, border, n - 7, 0);
        checkFinder(img, scale, border, 0, n - 7);
        // 오른쪽 아래에는 파인더가 없음 (가운데가 반드시 검지는 않음 — 테두리 전체가 검은지만 확인)
        bool fullRing = true;
        for (int i = 0; i < 7; ++i)
            fullRing &= dark(img, scale, border, n - 7 + i, n - 7) && dark(img, scale, border, n - 7, n - 7 + i);
        QVERIFY(!fullRing);
        // 파인더 옆 구분선(흰색)
        for (int i = 0; i < 8; ++i)
            QVERIFY(!dark(img, scale, border, 7, i));
    }

    void deterministicAndScaled()
    {
        const QImage a = qrImage("hello", 1, 0), b = qrImage("hello", 1, 0);
        QCOMPARE(a, b);
        QCOMPARE(a.width(), qrModuleCount("hello"));
        QVERIFY(qrImage("hello", 1, 0) != qrImage("world", 1, 0));
        QCOMPARE(qrImage("x", 0, -3).width(), qrModuleCount("x"));   // 잘못된 값은 1, 0으로
    }

    void tooLongGivesNullImage()
    {
        QVERIFY(qrImage(QString(8000, QChar('a'))).isNull());
        QCOMPARE(qrModuleCount(QString(8000, QChar('a'))), 0);
    }
};

QTEST_GUILESS_MAIN(TestQrCode)
#include "test_qrcode.moc"
