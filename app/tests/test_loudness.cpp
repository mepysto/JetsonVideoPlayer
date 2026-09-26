// 음량 측정: BS.1770 기준 신호로 필터 부호·게이팅을 검증합니다 (tests/test_loudness.py 이식).
#include "Loudness.h"
#include "media_test_util.h"

#include <QSignalSpy>
#include <QTest>

#include <gst/app/gstappsink.h>

using namespace jvp;
using namespace jvp::loudness;

namespace {
std::vector<float> sine(double amplitude, double seconds = 5.0, double freq = 997.0)
{
    const int n = int(kRate * seconds);
    std::vector<float> out(size_t(n) * 2);
    for (int i = 0; i < n; ++i) {
        const float v = float(amplitude * std::sin(2 * M_PI * freq * i / kRate));
        out[2 * i] = out[2 * i + 1] = v;
    }
    return out;
}
} // namespace

class TestLoudness : public QObject {
    Q_OBJECT
    QString m_dir;

private slots:
    void initTestCase()
    {
        m_dir = testutil::isolateHome();
        PlayerEngine::initGStreamer();
    }

    void gainLimits()
    {
        QCOMPARE(gainFor(-23.0), 7.0);
        QCOMPARE(gainFor(-40.0), 12.0);
        QCOMPARE(gainFor(5.0), -12.0);
        QCOMPARE(gainFor(std::nullopt), 0.0);
        QVERIFY(std::abs(dbToLinear(-6.0206) - 0.5) < 1e-4);
    }

    void kWeightingCoefficients()
    {
        // numpy.convolve(shelf, hpf) 결과와 같은 4차 계수
        QVERIFY(std::abs(kWeightB()[0] - 1.53512485958697) < 1e-12);
        QVERIFY(std::abs(kWeightA()[4] - 0.73248077421585 * 0.99007225036621) < 1e-12);
    }

    void silenceHasNoLoudness()
    {
        LoudnessMeter m;
        std::vector<float> zeros(kRate * 4, 0.f);
        m.feed(zeros.data(), zeros.size());
        QVERIFY(!m.integrated().has_value());
    }

    void meterGatesQuietParts()
    {
        // 앞 절반 -20dBFS 사인, 뒤 절반 무음 → 무음은 게이트로 빠져 -20 부근 (필터 전 기준 근사)
        LoudnessMeter m;
        auto s = sine(0.1, 3.0);
        std::vector<float> zeros(size_t(kRate) * 3 * 2, 0.f);
        m.feed(s.data(), s.size());
        m.feed(zeros.data(), zeros.size());
        const auto v = m.integrated();
        QVERIFY(v.has_value());
        const double expected = -0.691 + 10 * std::log10(2 * 0.1 * 0.1 / 2);
        QVERIFY2(std::abs(*v - expected) < 0.3, qPrintable(QString::number(*v)));
    }

    void measureFileMatchesBs1770Reference()
    {
        // 997Hz 사인 두 채널 진폭 0.5 → BS.1770: 0 LUFS(진폭 1) - 6.02dB ≈ -6.0 LUFS
        if (!testutil::hasElements({"audiotestsrc", "wavenc", "audioiirfilter"}))
            QSKIP("GStreamer 요소 없음");
        const QString path = m_dir + QStringLiteral("/tone.wav");
        QVERIFY(testutil::runPipeline(QStringLiteral(
            "audiotestsrc wave=sine freq=997 volume=0.5 num-buffers=240 samplesperbuffer=1000 "
            "! audio/x-raw,rate=48000,channels=2,format=S16LE ! wavenc ! filesink location=\"%1\"").arg(path)));
        const auto res = measureFile(path);
        QVERIFY2(res.ok(), qPrintable(res.error));
        QVERIFY(res.lufs.has_value());
        qInfo("997 Hz sine, amplitude 0.5: %.3f LUFS", *res.lufs);
        QVERIFY(std::abs(*res.lufs - -6.02) < 0.3);
    }

    void measureSkipsVideoDecoding()
    {
        const QString path = m_dir + QStringLiteral("/a.mkv");
        if (!testutil::makeTestVideo(path))
            QSKIP("테스트 영상을 만들 수 없습니다");
        MeterPipeline mp(pathToUri(path));
        QVERIFY(mp.sink());
        gst_element_set_state(mp.pipeline(), GST_STATE_PLAYING);
        GstSample *s = gst_app_sink_try_pull_sample(GST_APP_SINK(mp.sink()), 5 * GST_SECOND);
        QVERIFY(s);
        gst_sample_unref(s);
        QStringList videoDecoders, audioDecoders;
        GstIterator *it = gst_bin_iterate_recurse(GST_BIN(mp.pipeline()));
        GValue item = G_VALUE_INIT;
        while (gst_iterator_next(it, &item) == GST_ITERATOR_OK) {
            auto *el = GST_ELEMENT(g_value_get_object(&item));
            if (GstElementFactory *f = gst_element_get_factory(el)) {
                const QString klass = QString::fromUtf8(gst_element_factory_get_metadata(f, GST_ELEMENT_METADATA_KLASS));
                const QString name = QString::fromUtf8(gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(f)));
                if (klass.contains("Decoder") && klass.contains("Video"))
                    videoDecoders << name;
                if (klass.contains("Decoder") && klass.contains("Audio"))
                    audioDecoders << name;
            }
            g_value_reset(&item);
        }
        g_value_unset(&item);
        gst_iterator_free(it);
        QVERIFY2(videoDecoders.isEmpty(), qPrintable(videoDecoders.join(',')));
        QVERIFY(!audioDecoders.isEmpty());
    }

    void noAudioIsNulloptButFailuresError()
    {
        const QString path = m_dir + QStringLiteral("/noaudio.mkv");
        if (!testutil::makeTestVideo(path, 1, 25, false, 160, 120))
            QSKIP("vp8enc 없음");
        const auto none = measureFile(path);
        QVERIFY2(none.ok(), qPrintable(none.error));     // 오디오 없음 → 저장해도 되는 결과
        QVERIFY(!none.lufs.has_value());
        const auto missing = measureFile(m_dir + QStringLiteral("/missing.mkv"));
        QVERIFY(!missing.ok());                            // 읽기 실패 → 저장하면 안 되는 실패
    }

    void jobReportsOnOwnerThread()
    {
        const QString path = m_dir + QStringLiteral("/a.mkv");
        if (!QFile::exists(path))
            QSKIP("테스트 영상 없음");
        LoudnessJob job(path);
        QSignalSpy spy(&job, &LoudnessJob::done);
        job.start();
        QVERIFY(spy.wait(20000));
        const auto args = spy.takeFirst();
        QVERIFY(args.at(1).toString().isEmpty());
        QVERIFY(args.at(0).isValid());   // audiotestsrc 기본 사인 (볼륨 0.8)
        qInfo("test clip: %.2f LUFS", args.at(0).toDouble());

        // 취소하면 done이 오지 않고, 소멸자가 스레드를 정리합니다.
        auto *job2 = new LoudnessJob(path);
        QSignalSpy spy2(job2, &LoudnessJob::done);
        job2->start();
        job2->cancel();
        delete job2;
        QTest::qWait(50);
        QCOMPARE(spy2.count(), 0);
    }
};

QTEST_GUILESS_MAIN(TestLoudness)
#include "test_loudness.moc"
