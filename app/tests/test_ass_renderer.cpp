// AssRenderer(libass) — 파이썬의 Cairo ASS 그리기를 대신합니다.
#include "AssRenderer.h"

#include <QDir>
#include <QFile>
#include <QTemporaryDir>
#include <QtTest>

using namespace jvp;

namespace {

const char *kHeader = R"([Script Info]
ScriptType: v4.00+
PlayResX: 640
PlayResY: 360
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Red,Sans,60,&H000000FF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,10,10,10,1
Style: Blue,Sans,60,&H00FF0000,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
)";

const char *kEvents = R"(Dialogue: 0,0:00:00.00,0:00:02.00,Red,,0,0,0,,{\an7\pos(20,20)}HHHH
Dialogue: 0,0:00:03.00,0:00:04.00,Blue,,0,0,0,,{\an3}HHHH
Dialogue: 0,0:00:05.00,0:00:06.00,Red,,0,0,0,,{\p1}m 0 0 l 100 0 100 100 0 100{\p0}
)";

struct ColorStats {
    int red = 0, green = 0, blue = 0, total = 0;
};

// 거의 불투명한 픽셀만 보고 어느 색이 우세한지 셉니다 (premultiplied라도 불투명 픽셀은 원래 색)
ColorStats stats(const QImage &img)
{
    ColorStats s;
    for (int y = 0; y < img.height(); ++y) {
        const QRgb *line = reinterpret_cast<const QRgb *>(img.constScanLine(y));
        for (int x = 0; x < img.width(); ++x) {
            const QRgb p = line[x];
            if (qAlpha(p) < 200)
                continue;
            ++s.total;
            const int r = qRed(p), g = qGreen(p), b = qBlue(p);
            if (r > 200 && g < 60 && b < 60)
                ++s.red;
            else if (b > 200 && r < 60 && g < 60)
                ++s.blue;
            else if (g > 200 && r < 60 && b < 60)
                ++s.green;
        }
    }
    return s;
}

} // namespace

class TestAssRenderer : public QObject
{
    Q_OBJECT
    QTemporaryDir m_home;
    const QSize kFrame{1280, 720};

private slots:
    void initTestCase()
    {
        QVERIFY(m_home.isValid());
        qputenv("HOME", m_home.path().toUtf8()); // fontconfig 캐시도 실제 홈을 건드리지 않게
        qputenv("XDG_CACHE_HOME", (m_home.path() + "/.cache").toUtf8());
    }

    void rendersStyledEventsInPlace()
    {
        AssRenderer r;
        QVERIFY(r.loadData(QString::fromUtf8(kHeader) + QString::fromUtf8(kEvents)));
        QCOMPARE(r.playRes(), QSize(640, 360));
        QCOMPARE(r.eventCount(), 3);

        bool changed = false;
        const QImage red = r.render(1000, kFrame, 1.0, &changed);
        QVERIFY(changed);
        QVERIFY(!red.isNull());
        QCOMPARE(red.format(), QImage::Format_ARGB32_Premultiplied);
        // \an7\pos(20,20) → PlayRes 640x360을 1280x720으로 2배: 왼쪽 위 (40,40) 근처
        QVERIFY2(red.offset().x() >= 30 && red.offset().x() < 80, qPrintable(QString::number(red.offset().x())));
        QVERIFY2(red.offset().y() >= 30 && red.offset().y() < 100, qPrintable(QString::number(red.offset().y())));
        QVERIFY(red.offset().x() + red.width() < kFrame.width() / 2);
        ColorStats s = stats(red);
        QVERIFY(s.total > 500);
        QVERIFY2(s.red > s.total * 9 / 10, qPrintable(QStringLiteral("red %1/%2").arg(s.red).arg(s.total)));

        // 같은 시각을 다시 그리면 libass가 "바뀌지 않음"을 알려 줍니다
        const QImage again = r.render(1000, kFrame, 1.0, &changed);
        QVERIFY(!changed);
        QCOMPARE(again.offset(), red.offset());

        // \an3 → 오른쪽 아래, 파랑
        const QImage blue = r.render(3500, kFrame, 1.0, &changed);
        QVERIFY(changed);
        QVERIFY(!blue.isNull());
        QVERIFY(blue.offset().x() > kFrame.width() / 2);
        QVERIFY(blue.offset().y() > kFrame.height() / 2);
        QVERIFY(blue.offset().x() + blue.width() <= kFrame.width());
        s = stats(blue);
        QVERIFY2(s.blue > s.total * 9 / 10, qPrintable(QStringLiteral("blue %1/%2").arg(s.blue).arg(s.total)));
    }

    void emptyWhenNothingToShow()
    {
        AssRenderer r;
        QVERIFY(r.loadData(QString::fromUtf8(kHeader) + QString::fromUtf8(kEvents)));
        bool changed = false;
        QVERIFY(!r.render(1000, kFrame, 1.0, &changed).isNull());
        QVERIFY(r.render(2500, kFrame, 1.0, &changed).isNull());
        QVERIFY(changed); // 보이던 자막이 사라짐
        QVERIFY(r.render(2600, kFrame, 1.0, &changed).isNull());
        QVERIFY(!changed);
        QVERIFY(r.render(99000, kFrame, 1.0, &changed).isNull());
        // 트랙이 없으면 항상 빈 결과
        AssRenderer none;
        QVERIFY(none.render(0, kFrame).isNull());
        QVERIFY(!none.hasTrack());
    }

    void drawingIsRenderedButNotText()
    {
        AssRenderer r;
        QVERIFY(r.loadData(QString::fromUtf8(kHeader) + QString::fromUtf8(kEvents)));
        // libass는 \p1 그림도 그립니다 (파이썬 버전은 건너뛰었음), 글자 추출에서는 빠짐
        QVERIFY(!r.render(5500, kFrame).isNull());
        const SubtitleEvents plain = r.plainEvents();
        QCOMPARE(plain.size(), 2);
        QCOMPARE(plain[0], (SubtitleEvent{0, 2000, "HHHH"}));
        QCOMPARE(plain[1], (SubtitleEvent{3000, 4000, "HHHH"}));
    }

    void fontScaleEnlargesText()
    {
        AssRenderer r;
        QVERIFY(r.loadData(QString::fromUtf8(kHeader) + QString::fromUtf8(kEvents)));
        // \pos로 놓은 간판(sign)은 libass가 배율을 적용하지 않으므로 일반 대사(\an3)로 확인
        const QImage normal = r.render(3500, kFrame, 1.0);
        bool changed = false;
        const QImage big = r.render(3500, kFrame, 1.5, &changed);
        QVERIFY(changed); // 설정이 바뀌면 같은 시각이어도 다시 합성
        QVERIFY(big.height() > normal.height() * 5 / 4);
        QVERIFY(big.width() > normal.width() * 5 / 4);
    }

    void embeddedHeaderAndChunks()
    {
        AssRenderer r;
        QVERIFY(r.loadEmbeddedHeader(QByteArray(kHeader)));
        QVERIFY(r.hasTrack());
        QCOMPARE(r.eventCount(), 0);
        const QByteArray block = "0,0,Blue,,0,0,0,,{\\an5}Center";
        r.addChunk(block, 1000, 1000);
        r.addChunk(block, 1000, 1000); // 탐색 후 같은 블록 — ReadOrder로 걸러짐
        r.addChunk("1,0,Red,,0,0,0,,Later", 5000, 500);
        QCOMPARE(r.eventCount(), 2);
        QVERIFY(r.render(500, kFrame).isNull());
        const QImage img = r.render(1500, kFrame);
        QVERIFY(!img.isNull());
        const QPoint center = img.offset() + QPoint(img.width() / 2, img.height() / 2);
        QVERIFY(qAbs(center.x() - kFrame.width() / 2) < 40);
        QVERIFY(qAbs(center.y() - kFrame.height() / 2) < 40);
        const ColorStats s = stats(img);
        QVERIFY(s.blue > s.total * 9 / 10);
        const SubtitleEvents plain = r.plainEvents();
        QCOMPARE(plain.size(), 2);
        QCOMPARE(plain[0], (SubtitleEvent{1000, 2000, "Center"}));
        QCOMPARE(plain[1], (SubtitleEvent{5000, 5500, "Later"}));
    }

    void loadFileWithLegacyEncoding()
    {
        // CP949로 저장된 ASS도 우리 쪽에서 인코딩을 판별해 UTF-8로 넘깁니다
        const QString path = m_home.path() + "/k.ass";
        QFile f(path);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write(kHeader);
        f.write("Dialogue: 0,0:00:00.00,0:00:02.00,Red,,0,0,0,,");
        f.write(QByteArray::fromHex("bec8b3e7")); // "안녕" (CP949)
        f.write("\n");
        f.close();
        AssRenderer r;
        QVERIFY(r.loadFile(path));
        QCOMPARE(r.plainEvents().value(0).text, QStringLiteral("안녕"));
        QVERIFY(!r.loadFile(m_home.path() + "/missing.ass"));
    }
};

QTEST_GUILESS_MAIN(TestAssRenderer)
#include "test_ass_renderer.moc"
