#include "Mpris.h"

#include <QDBusConnectionInterface>
#include <QDBusMessage>
#include <QDBusMetaType>
#include <QDir>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QUrl>
#include <cmath>

Q_LOGGING_CATEGORY(lcMpris, "jvp.mpris")

namespace jvp {

namespace {
constexpr qint64 kUs = 1000;   // ns → µs
const char *const kPropsIface = "org.freedesktop.DBus.Properties";

QString loopStatusFor(const QString &mode)
{
    if (mode == QLatin1String("all") || mode == QLatin1String("shuffle"))
        return QStringLiteral("Playlist");
    if (mode == QLatin1String("one"))
        return QStringLiteral("Track");
    return QStringLiteral("None");
}

QString fileUrl(const QString &path)
{
    return QUrl::fromLocalFile(QFileInfo(path).absoluteFilePath()).toString(QUrl::FullyEncoded);
}
} // namespace

MprisService::MprisService(MprisBackend *backend, QObject *parent)
    : QObject(parent), m_backend(backend), m_bus(QString())
{
    new detail::MprisRootAdaptor(this);
    new detail::MprisPlayerAdaptor(this);
}

MprisService::~MprisService() { stop(); }

bool MprisService::start(const QDBusConnection &bus)
{
    stop();
    if (!bus.isConnected()) {
        qCInfo(lcMpris) << "ℹ️ MPRIS 연동을 건너뜁니다: 세션 버스에 연결할 수 없습니다";
        return false;
    }
    m_bus = bus;
    if (!m_bus.registerObject(QLatin1String(kObjectPath), this, QDBusConnection::ExportAdaptors)) {
        qCInfo(lcMpris) << "ℹ️ MPRIS 연동을 건너뜁니다:" << m_bus.lastError().message();
        return false;
    }
    QDBusConnectionInterface *iface = m_bus.interface();
    const auto reply = iface ? iface->registerService(QLatin1String(kBusName), QDBusConnectionInterface::DontQueueService,
                                                      QDBusConnectionInterface::DontAllowReplacement)
                             : QDBusReply<QDBusConnectionInterface::RegisterServiceReply>();
    if (!reply.isValid() || reply.value() != QDBusConnectionInterface::ServiceRegistered) {
        qCInfo(lcMpris) << "ℹ️ MPRIS 연동을 건너뜁니다: 버스 이름을 얻지 못했습니다"
                        << (reply.isValid() ? QString() : reply.error().message());
        m_bus.unregisterObject(QLatin1String(kObjectPath));
        return false;
    }
    m_active = true;
    m_last.clear();
    qCInfo(lcMpris) << "🎛️ [MPRIS] 미디어 키/시스템 미디어 컨트롤 연동:" << kBusName;
    return true;
}

void MprisService::stop()
{
    if (!m_active)
        return;
    m_active = false;
    m_bus.unregisterObject(QLatin1String(kObjectPath));
    m_bus.unregisterService(QLatin1String(kBusName));
}

// ---- 속성 계산 ----------------------------------------------------------------

QVariantMap MprisService::metadata() const
{
    QVariantMap meta;
    const MprisBackend *p = m_backend;
    const int index = p ? p->mprisCurrentIndex() : -1;
    const QString path = p ? p->mprisCurrentPath() : QString();
    if (!p || path.isEmpty() || index < 0 || index >= p->mprisPlaylistCount()) {
        meta.insert(QStringLiteral("mpris:trackid"),
                    QVariant::fromValue(QDBusObjectPath(QStringLiteral("/org/mpris/MediaPlayer2/TrackList/NoTrack"))));
        return meta;
    }
    const bool remote = path.startsWith(QLatin1String("http://")) || path.startsWith(QLatin1String("https://"));
    const QFileInfo info(path);
    meta.insert(QStringLiteral("mpris:trackid"),
                QVariant::fromValue(QDBusObjectPath(QStringLiteral("/org/jetson_player/track/%1").arg(index))));
    // os.path.splitext: 마지막 확장자만 뗍니다
    const QString name = info.fileName();
    const qsizetype dot = name.lastIndexOf(QLatin1Char('.'));
    meta.insert(QStringLiteral("xesam:title"), dot > 0 ? name.left(dot) : name);
    meta.insert(QStringLiteral("xesam:url"), remote ? path : fileUrl(path));
    meta.insert(QStringLiteral("xesam:album"), QFileInfo(info.path()).fileName());
    const qint64 dur = p->mprisDurationNs();
    if (dur > 0)
        meta.insert(QStringLiteral("mpris:length"), QVariant::fromValue<qlonglong>(dur / kUs));
    const QString art = p->mprisArtPath();
    if (!art.isEmpty())
        meta.insert(QStringLiteral("mpris:artUrl"), fileUrl(art));
    return meta;
}

QVariantMap MprisService::playerProperties() const
{
    const MprisBackend *p = m_backend;
    if (!p)
        return {};
    const bool hasVideo = p->mprisPlaylistCount() > 0 && p->mprisHasMedia();
    const QString status = !hasVideo ? QStringLiteral("Stopped")
                                     : (p->mprisIsPlaying() ? QStringLiteral("Playing") : QStringLiteral("Paused"));
    const QString mode = p->mprisRepeatMode();
    const bool multi = p->mprisPlaylistCount() > 1;
    return {
        {QStringLiteral("PlaybackStatus"), status},
        {QStringLiteral("LoopStatus"), loopStatusFor(mode)},
        {QStringLiteral("Rate"), p->mprisRate()},
        {QStringLiteral("Shuffle"), mode == QLatin1String("shuffle")},
        {QStringLiteral("Metadata"), metadata()},
        {QStringLiteral("Volume"), p->mprisMuted() ? 0.0 : qMin(2.0, p->mprisVolume())},
        {QStringLiteral("Position"), QVariant::fromValue<qlonglong>(qMax<qint64>(0, p->mprisPositionNs()) / kUs)},
        {QStringLiteral("MinimumRate"), 0.25},
        {QStringLiteral("MaximumRate"), 3.0},
        {QStringLiteral("CanGoNext"), multi},
        {QStringLiteral("CanGoPrevious"), multi},
        {QStringLiteral("CanPlay"), hasVideo},
        {QStringLiteral("CanPause"), hasVideo},
        {QStringLiteral("CanSeek"), hasVideo && p->mprisDurationNs() > 0},
        {QStringLiteral("CanControl"), true},
    };
}

QVariantMap MprisService::rootProperties() const
{
    return {
        {QStringLiteral("CanQuit"), true},
        {QStringLiteral("CanRaise"), true},
        {QStringLiteral("CanSetFullscreen"), true},
        {QStringLiteral("Fullscreen"), m_backend && m_backend->mprisFullscreen()},
        {QStringLiteral("HasTrackList"), false},
        {QStringLiteral("Identity"), QStringLiteral("Jetson Video Player")},
        {QStringLiteral("DesktopEntry"), QStringLiteral("jetson-player")},
        {QStringLiteral("SupportedUriSchemes"), QStringList{QStringLiteral("file"), QStringLiteral("https")}},
        {QStringLiteral("SupportedMimeTypes"),
         QStringList{QStringLiteral("video/mp4"), QStringLiteral("video/x-matroska"), QStringLiteral("video/webm"),
                     QStringLiteral("video/quicktime"), QStringLiteral("video/x-msvideo")}},
    };
}

void MprisService::update(int intervalMs)
{
    if (!m_backend)
        return;
    QVariantMap props = playerProperties();
    const qint64 position = props.take(QStringLiteral("Position")).toLongLong();
    QVariantMap changed;
    for (auto it = props.cbegin(); it != props.cend(); ++it) {
        auto last = m_last.constFind(it.key());
        if (last == m_last.constEnd() || last.value() != it.value())
            changed.insert(it.key(), it.value());
    }
    if (!changed.isEmpty()) {
        m_last.insert(changed);
        if (m_active) {
            QDBusMessage msg = QDBusMessage::createSignal(QLatin1String(kObjectPath), QLatin1String(kPropsIface),
                                                          QStringLiteral("PropertiesChanged"));
            msg << QLatin1String(kPlayerIface) << changed << QStringList();
            m_bus.send(msg);
        }
    }
    // 재생 흐름과 맞지 않는 위치 변화(탐색) 감지: 호출 주기 기준 2초 이상 차이
    const double expected = m_lastPositionUs
                            + (m_backend->mprisIsPlaying() ? intervalMs * 1000.0 * m_backend->mprisRate() : 0.0);
    if (std::abs(position - expected) > 2'000'000.0)
        Q_EMIT seeked(position);
    m_lastPositionUs = position;
}

// ---- 동작 ---------------------------------------------------------------------

void MprisService::raise() { if (m_backend) m_backend->mprisRaise(); }
void MprisService::quit() { if (m_backend) m_backend->mprisQuit(); }
void MprisService::next() { if (m_backend) m_backend->mprisNext(); }
void MprisService::previous() { if (m_backend) m_backend->mprisPrevious(); }
void MprisService::playPause() { if (m_backend) m_backend->mprisTogglePlayPause(); }

void MprisService::pause()
{
    if (m_backend && m_backend->mprisIsPlaying())
        m_backend->mprisTogglePlayPause();
}

void MprisService::play()
{
    if (m_backend && !m_backend->mprisIsPlaying())
        m_backend->mprisTogglePlayPause();
}

void MprisService::stopPlayback()
{
    pause();
    if (m_backend)
        m_backend->mprisSeekTo(0);
}

void MprisService::seek(qlonglong offsetUs)
{
    if (m_backend)
        m_backend->mprisSeekRelative(offsetUs / 1e6);
}

void MprisService::setPosition(const QDBusObjectPath &trackId, qlonglong positionUs)
{
    // 다른 곡의 trackid로 온 요청은 무시 (MPRIS 규약)
    if (m_backend && trackId.path().endsWith(QStringLiteral("/%1").arg(m_backend->mprisCurrentIndex())))
        m_backend->mprisSeekTo(positionUs * kUs);
}

void MprisService::openUri(const QString &uri)
{
    if (!m_backend)
        return;
    if (uri.startsWith(QLatin1String("file://")))
        m_backend->mprisOpenPath(QUrl::fromPercentEncoding(uri.mid(7).toUtf8()));
    else if (uri.startsWith(QLatin1String("https://")))
        m_backend->mprisOpenUrl(uri);
}

void MprisService::setVolume(double v)
{
    if (m_backend && std::isfinite(v))
        m_backend->mprisSetVolume(qBound(0.0, v, 2.0));
}

void MprisService::setRate(double r)
{
    if (m_backend && std::isfinite(r) && r > 0)
        m_backend->mprisSetRate(r);
}

void MprisService::setLoopStatus(const QString &s)
{
    if (!m_backend)
        return;
    const QString mode = s == QLatin1String("Track") ? QStringLiteral("one")
                         : s == QLatin1String("None") ? QStringLiteral("none")
                                                      : QStringLiteral("all");
    m_backend->mprisSetRepeatMode(mode);
}

void MprisService::setShuffle(bool on)
{
    if (m_backend)
        m_backend->mprisSetRepeatMode(on ? QStringLiteral("shuffle") : QStringLiteral("all"));
}

void MprisService::setFullscreen(bool on)
{
    if (m_backend && on != m_backend->mprisFullscreen())
        m_backend->mprisToggleFullscreen();
}

// ---- 어댑터 -------------------------------------------------------------------

namespace detail {

MprisRootAdaptor::MprisRootAdaptor(MprisService *s) : QDBusAbstractAdaptor(s), m_s(s) {}
bool MprisRootAdaptor::fullscreen() const { return m_s->rootProperties().value(QStringLiteral("Fullscreen")).toBool(); }
QString MprisRootAdaptor::identity() const { return m_s->rootProperties().value(QStringLiteral("Identity")).toString(); }
QString MprisRootAdaptor::desktopEntry() const
{
    return m_s->rootProperties().value(QStringLiteral("DesktopEntry")).toString();
}
QStringList MprisRootAdaptor::supportedUriSchemes() const
{
    return m_s->rootProperties().value(QStringLiteral("SupportedUriSchemes")).toStringList();
}
QStringList MprisRootAdaptor::supportedMimeTypes() const
{
    return m_s->rootProperties().value(QStringLiteral("SupportedMimeTypes")).toStringList();
}

MprisPlayerAdaptor::MprisPlayerAdaptor(MprisService *s) : QDBusAbstractAdaptor(s), m_s(s)
{
    connect(s, &MprisService::seeked, this, &MprisPlayerAdaptor::Seeked);
}

QVariant MprisPlayerAdaptor::prop(const char *name) const
{
    return m_s->playerProperties().value(QLatin1String(name));
}

} // namespace detail
} // namespace jvp
