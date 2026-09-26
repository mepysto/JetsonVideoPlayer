// media/codecs.py 이식 검증 (tests/test_codecs.py 대응)
#include "Codecs.h"

#include <QTest>

using namespace jvp::codecs;

class TestCodecs : public QObject {
    Q_OBJECT
private slots:
    void chromaAndDepth_data()
    {
        QTest::addColumn<QString>("pixFmt");
        QTest::addColumn<QString>("chroma");
        QTest::addColumn<int>("depth");
        QTest::newRow("yuv420p") << "yuv420p" << "420" << 8;
        QTest::newRow("yuvj420p") << "yuvj420p" << "420" << 8;
        QTest::newRow("yuv420p10le") << "yuv420p10le" << "420" << 10;
        QTest::newRow("p010le") << "p010le" << "420" << 10;
        QTest::newRow("nv12") << "nv12" << "420" << 8;
        QTest::newRow("yuv444p12le") << "yuv444p12le" << "444" << 12;
        QTest::newRow("yuv422p10le") << "yuv422p10le" << "422" << 10;
        QTest::newRow("gbrp") << "gbrp" << "444" << 8;
        QTest::newRow("empty") << "" << QString() << 8;
    }
    void chromaAndDepth()
    {
        QFETCH(QString, pixFmt);
        QFETCH(QString, chroma);
        QFETCH(int, depth);
        const ChromaDepth r = jvp::codecs::chromaAndDepth(pixFmt);
        QCOMPARE(r.chroma, chroma);
        QCOMPARE(r.chroma.isNull(), chroma.isNull());
        QCOMPARE(r.depth, depth);
    }

    void nvdecSupports_data()
    {
        QTest::addColumn<QString>("codec");
        QTest::addColumn<QString>("pixFmt");
        QTest::addColumn<QString>("profile");
        QTest::addColumn<bool>("ok");
        QTest::newRow("h264 8bit") << "h264" << "yuv420p" << "High" << true;
        QTest::newRow("h264 10bit") << "h264" << "yuv420p10le" << "High 10" << false;
        QTest::newRow("h264 444") << "h264" << "yuv444p" << "High 4:4:4 Predictive" << false;
        QTest::newRow("hevc main10") << "hevc" << "yuv420p10le" << "Main 10" << true;
        QTest::newRow("hevc rext") << "hevc" << "yuv444p10le" << "Rext" << false;
        QTest::newRow("vp9 p0") << "vp9" << "yuv420p" << "Profile 0" << true;
        QTest::newRow("vp9 p2") << "vp9" << "yuv420p10le" << "Profile 2" << true;
        QTest::newRow("vp9 p3") << "vp9" << "yuv444p12le" << "Profile 3" << false;
        QTest::newRow("av1 main") << "av1" << "yuv420p10le" << "Main" << true;
        QTest::newRow("av1 12bit") << "av1" << "yuv420p12le" << "Professional" << false;
        QTest::newRow("vp8") << "vp8" << "yuv420p" << "" << false;
        QTest::newRow("mpeg4") << "mpeg4" << "yuv420p" << "" << false;
        QTest::newRow("hevc no fmt") << "hevc" << "" << "Main" << true;
        QTest::newRow("vp9 no fmt p1") << "vp9" << "" << "Profile 1" << false;
    }
    void nvdecSupports()
    {
        QFETCH(QString, codec);
        QFETCH(QString, pixFmt);
        QFETCH(QString, profile);
        QFETCH(bool, ok);
        QCOMPARE(jvp::codecs::nvdecSupports(codec, pixFmt, profile).supported, ok);
    }

    void aliases()
    {
        QVERIFY(jvp::codecs::nvdecSupports("avc1", "yuv420p").supported);
        QVERIFY(jvp::codecs::nvdecSupports("hvc1", "yuv420p").supported);
        QVERIFY(jvp::codecs::nvdecSupports("av01", "yuv420p").supported);
        QVERIFY(jvp::codecs::nvdecSupports("H265", "yuv420p").supported);
        QCOMPARE(nvdecMaxBits("hev1"), 12);
    }

    void reasons()
    {
        // 사유 문구는 파이썬 버전과 같아야 합니다 (HUD·로그에 그대로 표시)
        QCOMPARE(jvp::codecs::nvdecSupports("h264", "yuv420p").reason, QString("H264 8-bit 4:2:0 NVDEC 지원"));
        QCOMPARE(jvp::codecs::nvdecSupports("h264", "yuv420p10le").reason, QString("H264 10-bit는 NVDEC 미지원 (최대 8-bit)"));
        QCOMPARE(jvp::codecs::nvdecSupports("hevc", "yuv422p").reason, QString("HEVC 4:2:2 샘플링은 NVDEC 미지원"));
        QCOMPARE(jvp::codecs::nvdecSupports("", "").reason, QString("NVDEC 미지원 코덱 (알 수 없음)"));
        QCOMPARE(jvp::codecs::nvdecSupports("vp8", "").reason, QString("NVDEC 미지원 코덱 (VP8)"));
        QCOMPARE(jvp::codecs::nvdecSupports("vp9", "", "Profile 1").reason, QString("VP9 Profile 1 (4:2:0 아님)"));
        QCOMPARE(jvp::codecs::nvdecSupports("hevc", "", "Main").reason, QString("HEVC NVDEC 지원 (형식 정보 부족)"));
    }
};

QTEST_GUILESS_MAIN(TestCodecs)
#include "test_codecs.moc"
