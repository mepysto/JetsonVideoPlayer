#pragma once
// GStreamer appsink(스트리밍 스레드) → Qt Quick 렌더 스레드로 영상 프레임을 넘기는 다리.
// 프레임은 GstSample 참조로만 넘기므로 복사가 없습니다 (NVMM이면 GPU 메모리 그대로).
// appsink는 프레임을 조금 일찍(kLeadNs) 내보내고, 렌더 스레드가 화면 갱신(vsync)마다
// 파이프라인 시계로 "다음 vsync에 보여야 할 프레임"을 골라 갑니다 (도착 시각의 흔들림과 무관한 고른 3:2 등).

#include <QImage>
#include <QObject>
#include <QSize>
#include <optional>
#include <atomic>
#include <deque>
#include <mutex>

#include <gst/gst.h>

namespace jvp {

enum class FrameFormat { None, NvmmRgba, Rgba, I420, Nv12 };

struct VideoFrame {
    GstSample *sample = nullptr;   // 소유 (unref 필요)
    FrameFormat format = FrameFormat::None;
    int width = 0;
    int height = 0;
    double pixelAspect = 1.0;
    quint64 serial = 0;            // 새 프레임인지 판단
    GstClockTime runningTime = GST_CLOCK_TIME_NONE;   // 이 프레임을 보여야 할 파이프라인 running time
};

class FrameBridge : public QObject {
    Q_OBJECT
public:
    explicit FrameBridge(QObject *parent = nullptr);
    ~FrameBridge() override;

    // appsink를 이 다리에 연결합니다 (new-sample 콜백 등록). 스트리밍 스레드에서 호출됩니다.
    void attach(GstElement *appsink);
    // 파이프라인을 버릴 때 들고 있는 프레임을 놓습니다 (다음 영상에 이전 프레임이 남지 않게).
    void clear();

    // appsink가 프레임을 보여야 할 시각보다 이만큼 먼저 넘깁니다 (렌더 스레드가 미리 골라 둘 수 있게).
    static constexpr qint64 kLeadNs = 35 * GST_MSECOND;

    // [렌더 스레드] 재생 중이면 지금의 파이프라인 running time을 돌려줍니다 (일시정지·준비 중이면 false).
    bool runningTimeNow(GstClockTime *now);
    // [렌더 스레드] 새로 보여 줄 프레임을 가져옵니다 (sample은 호출자가 unref, 없으면 sample == nullptr).
    // target이 있으면 running time이 target 이하인 프레임 중 가장 늦은 것을, 없으면 가장 최근 프레임을 고릅니다.
    // 고른 프레임보다 오래된 것은 버립니다.
    VideoFrame takeFrame(std::optional<GstClockTime> target);
    // 아직 보여 주지 않은 프레임이 남아 있는지
    bool hasPending();

    // 가장 최근 프레임을 원래 해상도의 RGB 이미지로 복사합니다 (스크린샷). 없으면 null 이미지
    QImage snapshot();

    quint64 renderedFrames() const { return m_rendered; }
    void markRendered() { ++m_rendered; }

signals:
    void frameReady();
    void videoSizeChanged(QSize size, double pixelAspect);

private:
    static GstFlowReturn onNewSample(GstElement *sink, gpointer self);
    void push(GstSample *sample);
    void clearQueue();   // m_mutex를 잡은 채로 호출

    std::mutex m_mutex;
    GstElement *m_sink = nullptr;     // 시계·상태 조회용 (참조 보유)
    std::deque<VideoFrame> m_queue;   // 아직 보여 주지 않은 프레임 (각자 sample 참조 보유)
    VideoFrame m_latest;              // 가장 최근에 받은 프레임 (스크린샷용)
    quint64 m_serial = 0;
    QSize m_size;
    double m_par = 1.0;
    std::atomic<quint64> m_rendered{0};
};

} // namespace jvp
