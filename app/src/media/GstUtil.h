#pragma once
// GStreamer 공통 도우미: 탐색 플래그, 요소 존재 확인, 참조 관리

#include <gst/gst.h>
#include <QString>

namespace jvp {

enum class SeekMode { Fast, Accurate };

// fast: 가장 가까운 키프레임 (드래그 중 미리보기) / accurate: 정확한 시각 (나머지 모든 탐색)
inline GstSeekFlags seekFlags(SeekMode mode)
{
    if (mode == SeekMode::Fast)
        return GstSeekFlags(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_KEY_UNIT | GST_SEEK_FLAG_SNAP_NEAREST);
    return GstSeekFlags(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_ACCURATE);
}

inline bool hasElement(const char *name)
{
    GstElementFactory *f = gst_element_factory_find(name);
    if (!f)
        return false;
    gst_object_unref(f);
    return true;
}

inline QString fromUtf8(const gchar *s) { return s ? QString::fromUtf8(s) : QString(); }

// g_free가 필요한 문자열을 QString으로
inline QString takeString(gchar *s)
{
    QString r = fromUtf8(s);
    g_free(s);
    return r;
}

// 파일 경로 → file:// URI
QString pathToUri(const QString &path);

} // namespace jvp
