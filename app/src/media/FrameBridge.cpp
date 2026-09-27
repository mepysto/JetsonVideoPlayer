#include "FrameBridge.h"

#include <gst/app/gstappsink.h>
#include <gst/video/video.h>
#ifdef JVP_HAVE_NVMM
#include <nvbufsurface.h>
#endif

namespace jvp {

FrameBridge::FrameBridge(QObject *parent) : QObject(parent) {}

FrameBridge::~FrameBridge() { clear(); }

void FrameBridge::attach(GstElement *appsink)
{
    g_object_set(appsink, "emit-signals", TRUE, "max-buffers", 2, "drop", TRUE, "ts-offset", -kLeadNs, nullptr);   // runningTimeNow 참고
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_sink)
            gst_object_unref(m_sink);
        m_sink = GST_ELEMENT(gst_object_ref(appsink));
    }
    g_signal_connect(appsink, "new-sample", G_CALLBACK(&FrameBridge::onNewSample), this);
    g_signal_connect(appsink, "new-preroll", G_CALLBACK(+[](GstElement *sink, gpointer self) -> GstFlowReturn {
                         GstSample *s = gst_app_sink_pull_preroll(GST_APP_SINK(sink));
                         if (s)
                             static_cast<FrameBridge *>(self)->push(s);
                         return GST_FLOW_OK;
                     }),
                     this);
    // 탐색(flush) 때 이전 구간의 프레임을 버립니다 (running time 기준이 바뀌므로).
    GstPad *pad = gst_element_get_static_pad(appsink, "sink");
    gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_EVENT_FLUSH, +[](GstPad *, GstPadProbeInfo *info, gpointer self) {
                          if (GST_EVENT_TYPE(GST_PAD_PROBE_INFO_EVENT(info)) == GST_EVENT_FLUSH_START) {
                              auto *b = static_cast<FrameBridge *>(self);
                              std::lock_guard<std::mutex> lock(b->m_mutex);
                              b->clearQueue();
                          }
                          return GST_PAD_PROBE_OK;
                      },
                      this, nullptr);
    gst_object_unref(pad);
}

GstFlowReturn FrameBridge::onNewSample(GstElement *sink, gpointer self)
{
    GstSample *s = gst_app_sink_pull_sample(GST_APP_SINK(sink));
    if (s)
        static_cast<FrameBridge *>(self)->push(s);
    return GST_FLOW_OK;
}

static FrameFormat formatOf(GstCaps *caps, int *w, int *h, double *par)
{
    if (!caps || gst_caps_get_size(caps) == 0)
        return FrameFormat::None;
    GstVideoInfo info;
    if (!gst_video_info_from_caps(&info, caps))
        return FrameFormat::None;
    *w = GST_VIDEO_INFO_WIDTH(&info);
    *h = GST_VIDEO_INFO_HEIGHT(&info);
    *par = GST_VIDEO_INFO_PAR_D(&info) ? double(GST_VIDEO_INFO_PAR_N(&info)) / GST_VIDEO_INFO_PAR_D(&info) : 1.0;
    GstCapsFeatures *features = gst_caps_get_features(caps, 0);
    const bool nvmm = features && gst_caps_features_contains(features, "memory:NVMM");
    switch (GST_VIDEO_INFO_FORMAT(&info)) {
    case GST_VIDEO_FORMAT_RGBA:
        return nvmm ? FrameFormat::NvmmRgba : FrameFormat::Rgba;
    case GST_VIDEO_FORMAT_I420:
        return FrameFormat::I420;
    case GST_VIDEO_FORMAT_NV12:
        return FrameFormat::Nv12;
    default:
        return FrameFormat::None;
    }
}

void FrameBridge::push(GstSample *sample)
{
    VideoFrame f;
    f.sample = sample;
    f.format = formatOf(gst_sample_get_caps(sample), &f.width, &f.height, &f.pixelAspect);
    GstBuffer *buf = gst_sample_get_buffer(sample);
    const GstSegment *seg = gst_sample_get_segment(sample);
    if (buf && seg && GST_BUFFER_PTS_IS_VALID(buf))
        f.runningTime = gst_segment_to_running_time(seg, GST_FORMAT_TIME, GST_BUFFER_PTS(buf));
    bool sizeChanged = false;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        f.serial = ++m_serial;
        if (m_latest.sample)
            gst_sample_unref(m_latest.sample);
        m_latest = f;
        gst_sample_ref(sample);   // m_latest와 대기열이 각자 참조를 가집니다
        // 렌더 스레드가 멈춰 있어도 GPU 버퍼 풀을 다 잡고 있지 않도록 몇 개만 둡니다.
        while (m_queue.size() >= 3) {
            gst_sample_unref(m_queue.front().sample);
            m_queue.pop_front();
        }
        m_queue.push_back(f);
        if (QSize(f.width, f.height) != m_size || f.pixelAspect != m_par) {
            m_size = QSize(f.width, f.height);
            m_par = f.pixelAspect;
            sizeChanged = true;
        }
    }
    if (sizeChanged)
        emit videoSizeChanged(QSize(f.width, f.height), f.pixelAspect);
    emit frameReady();
}

bool FrameBridge::runningTimeNow(GstClockTime *now)
{
    GstElement *sink = nullptr;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (!m_sink)
            return false;
        sink = GST_ELEMENT(gst_object_ref(m_sink));
    }
    // playbin(playsink)이 A/V 오프셋을 적용하며 영상 싱크의 ts-offset을 0 이상으로 되돌리므로 다시 맞춥니다.
    gint64 offset = 0;
    g_object_get(sink, "ts-offset", &offset, nullptr);
    if (offset != -kLeadNs)
        g_object_set(sink, "ts-offset", -kLeadNs, nullptr);
    bool ok = false;
    GstState state = GST_STATE_NULL;
    if (gst_element_get_state(sink, &state, nullptr, 0) != GST_STATE_CHANGE_FAILURE && state == GST_STATE_PLAYING) {
        if (GstClock *clock = gst_element_get_clock(sink)) {
            const GstClockTime t = gst_clock_get_time(clock);
            const GstClockTime base = gst_element_get_base_time(sink);
            ok = t >= base;
            *now = t - base;
            gst_object_unref(clock);
        }
    }
    gst_object_unref(sink);
    return ok;
}

VideoFrame FrameBridge::takeFrame(std::optional<GstClockTime> target)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    if (m_queue.empty())
        return {};
    size_t pick = m_queue.size() - 1;
    if (target) {
        // 보여야 할 시각이 지난 프레임 중 가장 늦은 것 (running time을 모르는 프레임은 바로)
        bool found = false;
        for (size_t k = 0; k < m_queue.size(); ++k) {
            const GstClockTime rt = m_queue[k].runningTime;
            if (!GST_CLOCK_TIME_IS_VALID(rt) || rt <= *target) {
                pick = k;
                found = true;
            }
        }
        if (!found)
            return {};
    }
    for (size_t k = 0; k < pick; ++k)
        gst_sample_unref(m_queue[k].sample);
    VideoFrame f = m_queue[pick];   // 대기열의 참조를 호출자에게 넘깁니다
    m_queue.erase(m_queue.begin(), m_queue.begin() + pick + 1);
    return f;
}

bool FrameBridge::hasPending()
{
    std::lock_guard<std::mutex> lock(m_mutex);
    return !m_queue.empty();
}

void FrameBridge::clearQueue()
{
    for (const VideoFrame &f : m_queue)
        gst_sample_unref(f.sample);
    m_queue.clear();
}

void FrameBridge::clear()
{
    std::lock_guard<std::mutex> lock(m_mutex);
    clearQueue();
    if (m_sink) {
        gst_object_unref(m_sink);
        m_sink = nullptr;
    }
    if (m_latest.sample)
        gst_sample_unref(m_latest.sample);
    m_latest = {};
    m_size = {};
}

QImage FrameBridge::snapshot()
{
    VideoFrame f;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        f = m_latest;
        if (!f.sample)
            return {};
        gst_sample_ref(f.sample);
    }
    QImage out;
    GstBuffer *buf = gst_sample_get_buffer(f.sample);
#ifdef JVP_HAVE_NVMM
    if (f.format == FrameFormat::NvmmRgba && buf) {
        // GPU 메모리(NvBufSurface)를 CPU로 매핑해 복사합니다.
        GstMapInfo map;
        if (gst_buffer_map(buf, &map, GST_MAP_READ)) {
            auto *surf = reinterpret_cast<NvBufSurface *>(map.data);
            if (surf && surf->numFilled > 0 && NvBufSurfaceMap(surf, 0, 0, NVBUF_MAP_READ) == 0) {
                NvBufSurfaceSyncForCpu(surf, 0, 0);
                const NvBufSurfaceParams &p = surf->surfaceList[0];
                const QImage view(static_cast<const uchar *>(p.mappedAddr.addr[0]), int(p.width), int(p.height),
                                  int(p.planeParams.pitch[0]), QImage::Format_RGBA8888);
                out = view.convertToFormat(QImage::Format_RGB888);
                NvBufSurfaceUnMap(surf, 0, 0);
            }
            gst_buffer_unmap(buf, &map);
        }
        gst_sample_unref(f.sample);
        return out;
    }
#endif
    // 시스템 메모리 프레임: GStreamer로 RGB 변환
    GstCaps *caps = gst_caps_new_simple("video/x-raw", "format", G_TYPE_STRING, "RGB", nullptr);
    GError *err = nullptr;
    GstSample *rgb = gst_video_convert_sample(f.sample, caps, 3 * GST_SECOND, &err);
    gst_caps_unref(caps);
    g_clear_error(&err);
    if (rgb) {
        GstVideoInfo info;
        GstBuffer *rb = gst_sample_get_buffer(rgb);
        GstMapInfo map;
        if (gst_video_info_from_caps(&info, gst_sample_get_caps(rgb)) && rb && gst_buffer_map(rb, &map, GST_MAP_READ)) {
            out = QImage(map.data, GST_VIDEO_INFO_WIDTH(&info), GST_VIDEO_INFO_HEIGHT(&info),
                         GST_VIDEO_INFO_PLANE_STRIDE(&info, 0), QImage::Format_RGB888).copy();
            gst_buffer_unmap(rb, &map);
        }
        gst_sample_unref(rgb);
    }
    gst_sample_unref(f.sample);
    return out;
}

} // namespace jvp
