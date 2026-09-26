#pragma once
// 테스트 공용: 실제 ~/.cache·~/.config를 건드리지 않도록 HOME을 임시 폴더로 바꾸고,
// GStreamer로 짧은 테스트 영상을 만듭니다 (MJPEG는 쓰지 않음 — Jetson HW JPEG 디코더 크래시).

#include <QDir>
#include <QElapsedTimer>
#include <QString>
#include <QTemporaryDir>
#include <QTest>

#include <gst/gst.h>

#include "PlayerEngine.h"

namespace testutil {

// HOME을 바꾸기 전의 실제 홈 (whisper/NLLB 설치 위치 확인용)
inline QString &realHome()
{
    static QString home;
    return home;
}

// 한 번만: 실제 HOME을 기억하고 임시 HOME/XDG_CONFIG_HOME으로 바꿉니다.
inline QString isolateHome()
{
    static QTemporaryDir *dir = nullptr;
    if (!dir) {
        realHome() = QDir::homePath();
        dir = new QTemporaryDir();
        qputenv("HOME", dir->path().toUtf8());
        qputenv("XDG_CONFIG_HOME", (dir->path() + QStringLiteral("/.config")).toUtf8());
    }
    return dir->path();
}

inline bool hasElements(std::initializer_list<const char *> names)
{
    jvp::PlayerEngine::initGStreamer();
    for (const char *n : names)
        if (!jvp::hasElement(n))
            return false;
    return true;
}

// gst-launch 문법의 파이프라인을 EOS/오류까지 돌립니다.
inline bool runPipeline(const QString &desc, int timeoutSec = 30, QString *error = nullptr)
{
    jvp::PlayerEngine::initGStreamer();
    GError *err = nullptr;
    GstElement *p = gst_parse_launch(desc.toUtf8().constData(), &err);
    if (!p) {
        if (error)
            *error = err ? QString::fromUtf8(err->message) : QStringLiteral("parse");
        g_clear_error(&err);
        return false;
    }
    g_clear_error(&err);
    gst_element_set_state(p, GST_STATE_PLAYING);
    GstBus *bus = gst_element_get_bus(p);
    GstMessage *msg = gst_bus_timed_pop_filtered(bus, GstClockTime(timeoutSec) * GST_SECOND,
                                                 GstMessageType(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
    bool ok = msg && GST_MESSAGE_TYPE(msg) == GST_MESSAGE_EOS;
    if (msg && !ok && error) {
        GError *e = nullptr;
        gst_message_parse_error(msg, &e, nullptr);
        *error = e ? QString::fromUtf8(e->message) : QString();
        g_clear_error(&e);
    }
    if (msg)
        gst_message_unref(msg);
    gst_object_unref(bus);
    gst_element_set_state(p, GST_STATE_NULL);
    gst_object_unref(p);
    return ok;
}

// VP8(+Vorbis) MKV. pattern: videotestsrc 패턴 (장면 전환 테스트용으로 바꿀 수 있음)
inline bool makeTestVideo(const QString &path, int seconds = 3, int fps = 25, bool audio = true,
                          int width = 320, int height = 180)
{
    if (!hasElements({"videotestsrc", "vp8enc", "matroskamux", "filesink"}))
        return false;
    if (audio && !hasElements({"audiotestsrc", "vorbisenc", "audioconvert"}))
        return false;
    QString desc = QStringLiteral("videotestsrc num-buffers=%1 ! video/x-raw,width=%2,height=%3,framerate=%4/1 ! "
                                  "vp8enc deadline=1 keyframe-max-dist=%5 ! matroskamux name=m ! filesink location=\"%6\" ")
                       .arg(seconds * fps).arg(width).arg(height).arg(fps).arg(std::max(1, fps / 5)).arg(path);
    if (audio) {
        const int samples = 1024;
        desc += QStringLiteral("audiotestsrc num-buffers=%1 samplesperbuffer=%2 ! audioconvert ! vorbisenc ! m.")
                    .arg(seconds * 44100 / samples).arg(samples);
    }
    return runPipeline(desc);
}

// 조건이 참이 될 때까지 이벤트 루프를 돌립니다.
template <typename F>
bool waitUntil(F cond, int timeoutMs = 5000)
{
    QElapsedTimer t;
    t.start();
    while (!cond()) {
        if (t.elapsed() > timeoutMs)
            return false;
        QTest::qWait(10);
    }
    return true;
}

} // namespace testutil
