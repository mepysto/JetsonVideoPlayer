#pragma once
// GStreamer appsink(스트리밍 스레드) → Qt Quick 렌더 스레드로 최신 영상 프레임을 넘기는 다리.
// 프레임은 GstSample 참조로만 넘기므로 복사가 없습니다 (NVMM이면 GPU 메모리 그대로).

#include <QImage>
#include <QObject>
#include <QSize>
#include <atomic>
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

    // [렌더 스레드] 가장 최근 프레임의 참조를 가져옵니다 (sample은 호출자가 unref).
    VideoFrame takeLatest(quint64 knownSerial);

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

    std::mutex m_mutex;
    VideoFrame m_latest;
    quint64 m_serial = 0;
    QSize m_size;
    double m_par = 1.0;
    std::atomic<quint64> m_rendered{0};
};

} // namespace jvp
