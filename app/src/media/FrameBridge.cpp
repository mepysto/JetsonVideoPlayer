#include "FrameBridge.h"

#include <gst/app/gstappsink.h>
#include <gst/video/video.h>

namespace jvp {

FrameBridge::FrameBridge(QObject *parent) : QObject(parent) {}

FrameBridge::~FrameBridge() { clear(); }

void FrameBridge::attach(GstElement *appsink)
{
    g_object_set(appsink, "emit-signals", TRUE, "max-buffers", 2, "drop", TRUE, nullptr);
    g_signal_connect(appsink, "new-sample", G_CALLBACK(&FrameBridge::onNewSample), this);
    g_signal_connect(appsink, "new-preroll", G_CALLBACK(+[](GstElement *sink, gpointer self) -> GstFlowReturn {
                         GstSample *s = gst_app_sink_pull_preroll(GST_APP_SINK(sink));
                         if (s)
                             static_cast<FrameBridge *>(self)->push(s);
                         return GST_FLOW_OK;
                     }),
                     this);
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
    bool sizeChanged = false;
    {
        std::lock_guard<std::mutex> lock(m_mutex);
        if (m_latest.sample)
            gst_sample_unref(m_latest.sample);   // 아직 그리지 못한 프레임은 버림 (최신만 유지)
        f.serial = ++m_serial;
        m_latest = f;
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

VideoFrame FrameBridge::takeLatest(quint64 knownSerial)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    VideoFrame f = m_latest;
    if (!f.sample || f.serial == knownSerial)
        return {};
    gst_sample_ref(f.sample);
    return f;
}

void FrameBridge::clear()
{
    std::lock_guard<std::mutex> lock(m_mutex);
    if (m_latest.sample)
        gst_sample_unref(m_latest.sample);
    m_latest = {};
    m_size = {};
}

} // namespace jvp
