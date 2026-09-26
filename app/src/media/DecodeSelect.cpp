#include "DecodeSelect.h"

#include <cstring>

namespace jvp::decodeselect {

namespace {
bool klassHas(GstElementFactory *factory, const char *word)
{
    const char *k = gst_element_factory_get_metadata(factory, GST_ELEMENT_METADATA_KLASS);
    return k && std::strstr(k, word);
}

void onDeepElementAdded(GstBin *, GstBin *, GstElement *element, gpointer)
{
    GstElementFactory *f = gst_element_get_factory(element);
    if (f && std::strcmp(gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(f)), "decodebin") == 0)
        g_signal_connect(element, "autoplug-select", G_CALLBACK(skipHardwareDecoders), nullptr);
}
} // namespace

gint skipNonAudioDecoders(GstElement *, GstPad *, GstCaps *, GstElementFactory *factory, gpointer)
{
    if (klassHas(factory, "Decoder")
        && (klassHas(factory, "Video") || klassHas(factory, "Image") || klassHas(factory, "Subtitle")))
        return kExpose;
    return kTry;
}

gint skipHardwareDecoders(GstElement *, GstPad *, GstCaps *, GstElementFactory *factory, gpointer)
{
    const char *name = gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory));
    if (klassHas(factory, "Decoder") && (std::strncmp(name, "nvv4l2", 6) == 0 || std::strcmp(name, "nvjpegdec") == 0))
        return kSkip;
    return kTry;
}

void forceSoftwareDecoding(GstElement *playbin)
{
    g_signal_connect(playbin, "deep-element-added", G_CALLBACK(onDeepElementAdded), nullptr);
}

} // namespace jvp::decodeselect
