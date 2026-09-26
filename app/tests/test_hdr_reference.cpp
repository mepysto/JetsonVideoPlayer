// HDR 톤매핑 참조 계산 (tests/test_hdr.py 이식) + 파이썬 numpy 참조 구현과의 수치 비교
#include "HdrReference.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QProcess>
#include <QStandardPaths>
#include <QTest>

#include <cmath>

using namespace jvp::hdr;

class TestHdrReference : public QObject {
    Q_OBJECT

private slots:
    void pqReferencePoints()
    {
        QVERIFY(std::abs(pqToNits(0.0)) < 1e-9);
        QVERIFY(std::abs(pqToNits(1.0) - 10000.0) < 10000.0 * 1e-6);
        QVERIFY(std::abs(pqToNits(0.5080784) - 100.0) < 100.0 * 1e-3);   // PQ 100nit
    }

    void tonemapKeepsMidtonesAndCompressesHighlights()
    {
        QCOMPARE(tonemap(0.5), 0.5);
        QVERIFY(tonemap(1.0) < 1.0);
        QVERIFY(std::abs(tonemap(10.0) - 1.0) < 1e-6);
        double prev = -1;
        for (int i = 0; i < 200; ++i) {   // 단조 증가
            const double t = tonemap(20.0 * i / 199);
            QVERIFY(t >= prev);
            prev = t;
        }
    }

    void sdrWhiteInHdrMapsNearDisplayWhite()
    {
        // HDR 안의 SDR 기준 백색(203nit, PQ≈0.58)은 SDR 화면에서 거의 흰색이어야 합니다.
        const double m1 = 2610.0 / 16384, m2 = 2523.0 / 4096 * 128, c1 = 3424.0 / 4096, c2 = 2413.0 / 4096 * 32,
                     c3 = 2392.0 / 4096 * 32;
        const double y = std::pow(203.0 / 10000, m1);
        const double pq = std::pow((c1 + c2 * y) / (1 + c3 * y), m2);
        const Vec3 out = reference({pq, pq, pq}, Transfer::Pq, false);
        for (double c : out)
            QVERIFY(c > 0.9);
    }

    void matrixFixIsIdentityForGrays()
    {
        const Vec3 gray{0.4, 0.4, 0.4};
        const Vec3 r = mul(matrixFix(), gray);
        for (int i = 0; i < 3; ++i)
            QVERIFY(std::abs(r[i] - 0.4) < 1e-9);
    }

    void matchesPythonNumpyReference()
    {
        // 저장소의 jetson_player/media/hdr.py (numpy)로 같은 입력을 계산해 비교합니다.
        const QString root = QFileInfo(QStringLiteral(__FILE__)).absoluteDir().absoluteFilePath("../..");
        const QString py = QStandardPaths::findExecutable("python3");
        if (py.isEmpty() || !QFileInfo::exists(root + "/jetson_player/media/hdr.py"))
            QSKIP("python3 또는 파이썬 원본 없음");
        const QList<Vec3> inputs{{0.1, 0.5, 0.9}, {0.58, 0.58, 0.58}, {0.9, 0.2, 0.1}, {0.3, 0.7, 0.4}, {1.0, 1.0, 1.0}};
        QString list;
        for (const auto &v : inputs)
            list += QStringLiteral("[%1,%2,%3],").arg(v[0]).arg(v[1]).arg(v[2]);
        const QString code = QStringLiteral(
            "import json,sys,importlib.util\n"
            "spec=importlib.util.spec_from_file_location('hdr', sys.argv[1]); hdr=importlib.util.module_from_spec(spec); spec.loader.exec_module(hdr)\n"
            "out=[]\n"
            "for v in [%1]:\n"
            "  for kind in ('pq','hlg'):\n"
            "    for fix in (False, True):\n"
            "      out.append([float(x) for x in hdr.reference(v, kind, fix)])\n"
            "print(json.dumps(out))\n").arg(list);
        QProcess p;
        p.start(py, {"-c", code, root + "/jetson_player/media/hdr.py"});
        QVERIFY(p.waitForFinished(20000));
        const auto doc = QJsonDocument::fromJson(p.readAllStandardOutput());
        if (!doc.isArray())
            QSKIP(qPrintable("numpy 참조 실행 실패: " + QString::fromUtf8(p.readAllStandardError()).left(200)));
        const QJsonArray arr = doc.array();
        int k = 0;
        double maxErr = 0;
        for (const auto &v : inputs)
            for (Transfer kind : {Transfer::Pq, Transfer::Hlg})
                for (bool fix : {false, true}) {
                    const Vec3 got = reference(v, kind, fix);
                    const QJsonArray want = arr.at(k++).toArray();
                    for (int i = 0; i < 3; ++i)
                        maxErr = std::max(maxErr, std::abs(got[i] - want.at(i).toDouble()));
                }
        qInfo("max |C++ - numpy| = %.3g over %d cases", maxErr, k);
        QVERIFY(maxErr < 1e-9);
    }
};

QTEST_GUILESS_MAIN(TestHdrReference)
#include "test_hdr_reference.moc"
