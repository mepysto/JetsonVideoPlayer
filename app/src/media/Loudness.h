#pragma once
// 음량 평준화: 영상의 통합 음량(ITU-R BS.1770 / EBU R128, LUFS)을 측정해 목표 음량에 맞출 이득을 계산합니다.
// 측정은 GStreamer로 오디오만 디코딩해(48kHz 스테레오 float) K-가중 필터(audioiirfilter)를 거친 뒤
// 400ms 블록 게이팅을 C++에서 계산합니다. (파이썬 jetson_player/media/loudness.py 이식)

#include <QObject>
#include <QString>
#include <QVariant>

#include <array>
#include <cmath>
#include <atomic>
#include <functional>
#include <optional>
#include <thread>
#include <vector>

#include <gst/gst.h>

namespace jvp::loudness {

constexpr int kRate = 48000;
constexpr double kTargetLufs = -16.0;
constexpr double kMaxBoostDb = 12.0;
constexpr double kMaxCutDb = 12.0;
constexpr int kStep = kRate / 10;      // 100ms — 400ms 블록(75% 겹침)을 100ms 합 네 개로 만듭니다
constexpr double kBlockSec = 0.4;
constexpr double kAbsoluteGate = -70.0;
constexpr double kRelativeGate = -10.0;

// BS.1770 K-가중 필터(48kHz): 고역 선반 × 고역 통과를 곱한 4차 필터 계수
const std::array<double, 5> &kWeightB();
const std::array<double, 5> &kWeightA();

// K-가중된 스테레오 샘플을 받아 통합 음량(LUFS)을 계산합니다 (채널 가중치 L=R=1).
class LoudnessMeter {
public:
    void feed(const float *interleaved, size_t samples);   // samples = 프레임 수 × 2 (L,R 교차)
    std::optional<double> integrated() const;              // 소리가 거의 없으면 nullopt

private:
    std::vector<double> m_steps;     // 100ms마다 두 채널 제곱합
    double m_pendingSum = 0.0;       // 아직 100ms가 차지 않은 부분
    int m_pendingFrames = 0;
};

// 목표 음량에 맞추는 이득 (dB, ±12dB 제한). 측정값이 없으면 0
double gainFor(std::optional<double> lufs, double target = kTargetLufs);
inline double dbToLinear(double db) { return std::pow(10.0, db / 20.0); }

// 영상 파일의 첫 오디오 → 48kHz 스테레오 float → K-가중 → appsink.
// 영상·이미지·자막 디코더는 고르지 않습니다(autoplug-select → EXPOSE, 연결하지 않고 버림).
class MeterPipeline {
public:
    explicit MeterPipeline(const QString &uri);
    ~MeterPipeline();
    MeterPipeline(const MeterPipeline &) = delete;
    MeterPipeline &operator=(const MeterPipeline &) = delete;

    GstElement *pipeline() const { return m_pipeline; }
    GstElement *sink() const { return m_sink; }
    bool sawAudio() const { return m_audio.load(); }       // 오디오 스트림을 봤는지
    bool streamsComplete() const { return m_complete.load(); }   // no-more-pads — 모든 스트림이 나왔는지

private:
    static void onPadAdded(GstElement *, GstPad *pad, gpointer self);
    static void onNoMorePads(GstElement *, gpointer self);
    GstElement *m_pipeline = nullptr;
    GstElement *m_conv = nullptr;
    GstElement *m_sink = nullptr;
    std::atomic<bool> m_audio{false};
    std::atomic<bool> m_complete{false};
};

struct MeasureResult {
    std::optional<double> lufs;   // 오디오가 없거나 무음이면 nullopt (저장해도 되는 결과)
    QString error;                // 비어 있지 않으면 측정 실패(읽기·디코딩 오류, 시간 초과) — 저장하면 안 됨
    bool ok() const { return error.isEmpty(); }
};

// 파일 전체의 통합 음량. 호출한 스레드를 막으므로 작업 스레드에서 부르세요.
MeasureResult measureFile(const QString &path, const std::function<bool()> &cancelled = {}, int timeoutSec = 900);

} // namespace jvp::loudness

namespace jvp {

// 백그라운드 음량 측정 (낮은 우선순위 스레드). done은 소유 스레드에서 발생합니다.
// 취소되면 done은 발생하지 않습니다.
class LoudnessJob : public QObject {
    Q_OBJECT
public:
    explicit LoudnessJob(const QString &path, QObject *parent = nullptr);
    ~LoudnessJob() override;   // 취소 후 스레드가 끝날 때까지 기다립니다

    void start();
    void cancel();
    bool isRunning() const { return m_running.load(); }
    QString path() const { return m_path; }

signals:
    // lufs: double(LUFS) 또는 무효 QVariant(오디오 없음/무음). error가 비어 있지 않으면 실패.
    void done(const QVariant &lufs, const QString &error);

private:
    QString m_path;
    std::thread m_thread;
    std::atomic<bool> m_cancelled{false};
    std::atomic<bool> m_running{false};
};

} // namespace jvp
