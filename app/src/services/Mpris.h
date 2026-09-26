#pragma once
// MPRIS2 D-Bus 연동: 키보드 미디어 키, GNOME 상단 미디어 위젯, playerctl, KDE Connect(폰)로 플레이어를 조작합니다.
//
// 버스 이름: org.mpris.MediaPlayer2.jetson_player, 객체: /org/mpris/MediaPlayer2
// D-Bus 호출은 이 객체의 스레드(메인)로 전달되므로 백엔드는 플레이어 메서드를 바로 불러도 됩니다.
// 세션 버스가 없거나 이름이 이미 쓰이면 start()가 false를 돌려주고 조용히 비활성으로 남습니다.

#include <QDBusAbstractAdaptor>
#include <QDBusConnection>
#include <QDBusObjectPath>
#include <QObject>
#include <QStringList>
#include <QVariantMap>

namespace jvp {

// 앱 컨트롤러가 구현합니다. 모두 메인 스레드에서 불립니다.
class MprisBackend {
public:
    virtual ~MprisBackend() = default;
    // ---- 상태 ----
    virtual bool mprisHasMedia() const = 0;          // 재생목록이 있고 파이프라인이 열려 있음
    virtual bool mprisIsPlaying() const = 0;
    virtual int mprisPlaylistCount() const = 0;
    virtual int mprisCurrentIndex() const = 0;
    virtual QString mprisCurrentPath() const = 0;    // 로컬 경로 또는 http(s) URL, 없으면 빈 문자열
    virtual qint64 mprisDurationNs() const = 0;      // 모르면 0 이하
    virtual qint64 mprisPositionNs() const = 0;
    virtual double mprisRate() const = 0;
    virtual double mprisVolume() const = 0;          // 선형 0~2 (1 = 100%)
    virtual bool mprisMuted() const = 0;
    virtual QString mprisRepeatMode() const = 0;     // "all" | "one" | "none" | "shuffle"
    virtual bool mprisFullscreen() const = 0;
    virtual QString mprisArtPath() const = 0;        // 대표 썸네일 파일, 없으면 빈 문자열
    // ---- 동작 ----
    virtual void mprisRaise() = 0;
    virtual void mprisQuit() = 0;
    virtual void mprisNext() = 0;
    virtual void mprisPrevious() = 0;
    virtual void mprisTogglePlayPause() = 0;
    virtual void mprisSeekTo(qint64 ns) = 0;           // 절대 위치
    virtual void mprisSeekRelative(double seconds) = 0;
    virtual void mprisOpenPath(const QString &localPath) = 0;
    virtual void mprisOpenUrl(const QString &url) = 0;   // https:// (YouTube 등)
    virtual void mprisSetVolume(double linear) = 0;      // 0~2
    virtual void mprisSetRate(double rate) = 0;
    virtual void mprisSetRepeatMode(const QString &mode) = 0;
    virtual void mprisToggleFullscreen() = 0;
};

class MprisService : public QObject {
    Q_OBJECT
public:
    static constexpr const char *kBusName = "org.mpris.MediaPlayer2.jetson_player";
    static constexpr const char *kObjectPath = "/org/mpris/MediaPlayer2";
    static constexpr const char *kRootIface = "org.mpris.MediaPlayer2";
    static constexpr const char *kPlayerIface = "org.mpris.MediaPlayer2.Player";

    explicit MprisService(MprisBackend *backend, QObject *parent = nullptr);
    ~MprisService() override;

    // 버스에 객체와 이름을 등록합니다. 버스가 없거나 이름이 이미 쓰이면 false (앱 기능에는 영향 없음).
    bool start(const QDBusConnection &bus = QDBusConnection::sessionBus());
    void stop();
    bool isActive() const { return m_active; }

    // [메인 스레드, 주기 호출] 바뀐 속성만 PropertiesChanged로 알리고, 위치가 튀면 Seeked를 보냅니다.
    // intervalMs는 호출 주기 (탐색 감지 기준).
    void update(int intervalMs = 500);

    // 현재 속성 (D-Bus 없이도 만들 수 있음 — 테스트용)
    QVariantMap playerProperties() const;   // Position 포함
    QVariantMap rootProperties() const;
    QVariantMap metadata() const;

    MprisBackend *backend() const { return m_backend; }

    // ---- D-Bus 메서드 (어댑터가 부름) ----
    void raise();
    void quit();
    void next();
    void previous();
    void pause();
    void play();
    void playPause();
    void stopPlayback();
    void seek(qlonglong offsetUs);
    void setPosition(const QDBusObjectPath &trackId, qlonglong positionUs);
    void openUri(const QString &uri);
    void setVolume(double v);
    void setRate(double r);
    void setLoopStatus(const QString &s);
    void setShuffle(bool on);
    void setFullscreen(bool on);

Q_SIGNALS:
    void seeked(qlonglong positionUs);

private:
    MprisBackend *m_backend;
    QDBusConnection m_bus;
    bool m_active = false;
    QVariantMap m_last;
    qint64 m_lastPositionUs = 0;
};

namespace detail {

class MprisRootAdaptor : public QDBusAbstractAdaptor {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.mpris.MediaPlayer2")
    Q_PROPERTY(bool CanQuit READ canQuit)
    Q_PROPERTY(bool CanRaise READ canRaise)
    Q_PROPERTY(bool CanSetFullscreen READ canSetFullscreen)
    Q_PROPERTY(bool Fullscreen READ fullscreen WRITE setFullscreen)
    Q_PROPERTY(bool HasTrackList READ hasTrackList)
    Q_PROPERTY(QString Identity READ identity)
    Q_PROPERTY(QString DesktopEntry READ desktopEntry)
    Q_PROPERTY(QStringList SupportedUriSchemes READ supportedUriSchemes)
    Q_PROPERTY(QStringList SupportedMimeTypes READ supportedMimeTypes)
public:
    explicit MprisRootAdaptor(MprisService *s);
    bool canQuit() const { return true; }
    bool canRaise() const { return true; }
    bool canSetFullscreen() const { return true; }
    bool fullscreen() const;
    void setFullscreen(bool on) { m_s->setFullscreen(on); }
    bool hasTrackList() const { return false; }
    QString identity() const;
    QString desktopEntry() const;
    QStringList supportedUriSchemes() const;
    QStringList supportedMimeTypes() const;
public Q_SLOTS:
    void Raise() { m_s->raise(); }
    void Quit() { m_s->quit(); }

private:
    MprisService *m_s;
};

class MprisPlayerAdaptor : public QDBusAbstractAdaptor {
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.mpris.MediaPlayer2.Player")
    Q_PROPERTY(QString PlaybackStatus READ playbackStatus)
    Q_PROPERTY(QString LoopStatus READ loopStatus WRITE setLoopStatus)
    Q_PROPERTY(double Rate READ rate WRITE setRate)
    Q_PROPERTY(bool Shuffle READ shuffle WRITE setShuffle)
    Q_PROPERTY(QVariantMap Metadata READ metadata)
    Q_PROPERTY(double Volume READ volume WRITE setVolume)
    Q_PROPERTY(qlonglong Position READ position)
    Q_PROPERTY(double MinimumRate READ minimumRate)
    Q_PROPERTY(double MaximumRate READ maximumRate)
    Q_PROPERTY(bool CanGoNext READ canGoNext)
    Q_PROPERTY(bool CanGoPrevious READ canGoPrevious)
    Q_PROPERTY(bool CanPlay READ canPlay)
    Q_PROPERTY(bool CanPause READ canPause)
    Q_PROPERTY(bool CanSeek READ canSeek)
    Q_PROPERTY(bool CanControl READ canControl)
public:
    explicit MprisPlayerAdaptor(MprisService *s);
    QString playbackStatus() const { return prop("PlaybackStatus").toString(); }
    QString loopStatus() const { return prop("LoopStatus").toString(); }
    void setLoopStatus(const QString &v) { m_s->setLoopStatus(v); }
    double rate() const { return prop("Rate").toDouble(); }
    void setRate(double v) { m_s->setRate(v); }
    bool shuffle() const { return prop("Shuffle").toBool(); }
    void setShuffle(bool v) { m_s->setShuffle(v); }
    QVariantMap metadata() const { return m_s->metadata(); }
    double volume() const { return prop("Volume").toDouble(); }
    void setVolume(double v) { m_s->setVolume(v); }
    qlonglong position() const { return prop("Position").toLongLong(); }
    double minimumRate() const { return 0.25; }
    double maximumRate() const { return 3.0; }
    bool canGoNext() const { return prop("CanGoNext").toBool(); }
    bool canGoPrevious() const { return prop("CanGoPrevious").toBool(); }
    bool canPlay() const { return prop("CanPlay").toBool(); }
    bool canPause() const { return prop("CanPause").toBool(); }
    bool canSeek() const { return prop("CanSeek").toBool(); }
    bool canControl() const { return true; }
public Q_SLOTS:
    void Next() { m_s->next(); }
    void Previous() { m_s->previous(); }
    void Pause() { m_s->pause(); }
    void PlayPause() { m_s->playPause(); }
    void Stop() { m_s->stopPlayback(); }
    void Play() { m_s->play(); }
    void Seek(qlonglong offset) { m_s->seek(offset); }
    void SetPosition(const QDBusObjectPath &trackId, qlonglong position) { m_s->setPosition(trackId, position); }
    void OpenUri(const QString &uri) { m_s->openUri(uri); }
Q_SIGNALS:
    void Seeked(qlonglong position);

private:
    QVariant prop(const char *name) const;
    MprisService *m_s;
};

} // namespace detail
} // namespace jvp
