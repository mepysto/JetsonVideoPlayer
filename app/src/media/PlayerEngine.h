#pragma once
// GStreamer playbin 파이프라인: 영상(HW NVMM zero-copy / SW), 오디오 효과 체인, 내장 자막, 챕터, 탐색·배속.
// 재생목록·이어보기·재시도 같은 정책은 PlayerController가 맡고, 여기는 파이프라인만 다룹니다.

#include "FrameBridge.h"
#include "GstUtil.h"

#include <QObject>
#include <QVariantList>
#include <gst/gst.h>

namespace jvp {

class PlayerEngine : public QObject {
    Q_OBJECT
public:
    explicit PlayerEngine(QObject *parent = nullptr);
    ~PlayerEngine() override;

    static void initGStreamer();   // 디코더 우선순위 등 한 번만

    struct OpenOptions {
        bool hwOutput = true;          // NVDEC → nvvidconv(NVMM RGBA) → GL (복사 없음)
        qint64 startNs = 0;            // 0보다 크면 PAUSED로 준비한 뒤 정확히 그 위치에서 시작
        double rate = 1.0;
        bool keepAssRaw = true;        // 내장 ASS를 스타일 그대로 받기
        bool passthrough = false;      // HDMI 원음 (pulsesink 직결, 효과 없음)
        int avOffsetMs = 0;
    };

    bool open(const QString &uri, const OpenOptions &opt);
    void stop();                       // 파이프라인 해제 (NULL)
    bool isOpen() const { return m_pipeline != nullptr; }

    void play();
    void pause();
    bool isPlaying() const { return m_playing; }
    bool seek(qint64 ns, SeekMode mode);
    bool setRate(double rate);
    double rate() const { return m_rate; }
    void stepFrame(int direction);

    qint64 position() const;           // ns, 모르면 -1
    qint64 duration() const;           // ns, 모르면 -1

    void setVolume(double linear);     // 0~2
    void setMuted(bool muted);
    void setAvOffsetMs(int ms);

    int audioTrackCount() const;
    int currentAudioTrack() const;
    void setAudioTrack(int index);
    int textTrackCount() const;
    int currentTextTrack() const;
    void setTextTrack(int index);
    QString textTrackLanguage(int index) const;

    // 오디오 효과 (없으면 무시)
    void setEqualizer(const QList<double> &bandsDb);
    void setNightMode(bool on);
    void setLoudnessGainDb(double db);

    FrameBridge *frameBridge() const { return m_bridge; }
    bool saveCurrentFrame(const QString &path);   // 원래 해상도의 현재 프레임을 PNG로 (스크린샷)
    QString activeVideoDecoder() const;
    bool usingHwOutput() const { return m_hwOutput; }
    bool passthroughActive() const { return m_passthrough; }
    QString videoTransfer() const;     // "pq" / "hlg" / "" (디코딩된 영상 caps 기준)
    QSize videoSize() const;

signals:
    void playingChanged(bool playing);
    void asyncDone();                  // preroll/탐색 완료
    void endOfStream();
    void errorOccurred(const QString &message, const QString &debug, bool fromPassthrough);
    void streamsChanged();             // 오디오/자막 트랙 수가 바뀜
    void chaptersFound(const QVariantList &chapters);          // [{ns, title}]
    void decoderSelected(const QString &factory, bool hardware);
    // 내장 자막 (스트리밍 스레드에서 발생 → 연결은 Queued로)
    void embeddedText(qint64 startMs, qint64 endMs, const QString &text);
    void embeddedAss(const QString &header, qint64 startMs, qint64 endMs, const QString &block);

private:
    static gboolean onBusMessage(GstBus *, GstMessage *msg, gpointer self);
    static void onDeepElementAdded(GstBin *, GstBin *, GstElement *element, gpointer self);
    static gboolean onAutoplugContinue(GstElement *, GstPad *, GstCaps *caps, gpointer self);
    static GstFlowReturn onTextSample(GstElement *sink, gpointer self);
    void handleMessage(GstMessage *msg);
    GstElement *buildVideoSink(bool hw);
    GstElement *buildAudioSink(bool passthrough, int avOffsetMs);

    GstElement *m_pipeline = nullptr;
    guint m_busWatch = 0;
    FrameBridge *m_bridge = nullptr;
    bool m_playing = false;
    bool m_hwOutput = false;
    bool m_passthrough = false;
    bool m_keepAssRaw = true;
    double m_rate = 1.0;
    qint64 m_pendingSeek = 0;
    bool m_rateAppliedOnPreroll = true;

    GstElement *m_eq = nullptr, *m_nightDyn = nullptr, *m_nightGain = nullptr, *m_loudness = nullptr;
    GstElement *m_audioSink = nullptr;
    QString m_decoder;
    bool m_decoderIsHw = false;
};

} // namespace jvp
