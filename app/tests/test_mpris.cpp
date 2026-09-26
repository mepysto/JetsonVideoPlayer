// MPRIS2: 속성 계산 단위 테스트 + 전용 dbus-daemon을 띄워 실제 D-Bus 호출·신호 확인
#include "Mpris.h"

#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusMessage>
#include <QDBusPendingCall>
#include <QDBusVariant>
#include <QProcess>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtTest>

using namespace jvp;

namespace {

struct FakePlayer : MprisBackend {
    bool media = true, playing = false, muted = false, fullscreen = false;
    int count = 3, index = 1;
    QString path = QStringLiteral("/videos/드라마/ep 1.final.mkv");
    qint64 durationNs = 60'000'000'000, positionNs = 5'000'000'000;
    double rate = 1.0, volume = 0.8;
    QString repeat = QStringLiteral("all"), art;
    QStringList calls;
    QList<qint64> seeks;
    double lastRelative = 0, lastVolume = -1;

    bool mprisHasMedia() const override { return media; }
    bool mprisIsPlaying() const override { return playing; }
    int mprisPlaylistCount() const override { return count; }
    int mprisCurrentIndex() const override { return index; }
    QString mprisCurrentPath() const override { return path; }
    qint64 mprisDurationNs() const override { return durationNs; }
    qint64 mprisPositionNs() const override { return positionNs; }
    double mprisRate() const override { return rate; }
    double mprisVolume() const override { return volume; }
    bool mprisMuted() const override { return muted; }
    QString mprisRepeatMode() const override { return repeat; }
    bool mprisFullscreen() const override { return fullscreen; }
    QString mprisArtPath() const override { return art; }
    void mprisRaise() override { calls << "raise"; }
    void mprisQuit() override { calls << "quit"; }
    void mprisNext() override { calls << "next"; }
    void mprisPrevious() override { calls << "previous"; }
    void mprisTogglePlayPause() override { calls << "toggle"; playing = !playing; }
    void mprisSeekTo(qint64 ns) override { calls << "seekTo"; seeks << ns; }
    void mprisSeekRelative(double s) override { calls << "seekRel"; lastRelative = s; }
    void mprisOpenPath(const QString &p) override { calls << "open:" + p; }
    void mprisOpenUrl(const QString &u) override { calls << "url:" + u; }
    void mprisSetVolume(double v) override { lastVolume = v; }
    void mprisSetRate(double r) override { rate = r; }
    void mprisSetRepeatMode(const QString &m) override { repeat = m; }
    void mprisToggleFullscreen() override { fullscreen = !fullscreen; calls << "fullscreen"; }
};

template<typename Pred>
bool spinUntil(Pred pred, int timeoutMs = 5000)
{
    QElapsedTimer t;
    t.start();
    while (!pred()) {
        if (t.elapsed() > timeoutMs)
            return false;
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
    }
    return true;
}

} // namespace

class SignalSpy : public QObject {
    Q_OBJECT
public:
    QList<QVariantMap> changed;
    QList<qlonglong> seeked;
public Q_SLOTS:
    void onPropertiesChanged(const QString &iface, const QVariantMap &props, const QStringList &)
    {
        if (iface == QLatin1String(MprisService::kPlayerIface))
            changed.append(props);
    }
    void onSeeked(qlonglong pos) { seeked.append(pos); }
};

class TestMpris : public QObject {
    Q_OBJECT
    QProcess m_daemon;
    QString m_address;

    // 서비스와 같은 스레드에서 블로킹 호출하면 교착되므로 비동기 호출 + 이벤트 루프로 기다립니다.
    QDBusMessage call(QDBusConnection &client, const QString &iface, const QString &method,
                      const QVariantList &args = {})
    {
        QDBusMessage msg = QDBusMessage::createMethodCall(MprisService::kBusName, MprisService::kObjectPath, iface, method);
        msg.setArguments(args);
        QDBusPendingCall pending = client.asyncCall(msg, 3000);
        spinUntil([&] { return pending.isFinished(); });
        return pending.reply();
    }
    QVariant getProp(QDBusConnection &client, const QString &iface, const QString &name)
    {
        const QDBusMessage r = call(client, "org.freedesktop.DBus.Properties", "Get", {iface, name});
        if (r.type() != QDBusMessage::ReplyMessage)
            return {};
        return r.arguments().value(0).value<QDBusVariant>().variant();
    }

private Q_SLOTS:
    void initTestCase()
    {
        const QString exe = QStandardPaths::findExecutable("dbus-daemon");
        if (exe.isEmpty())
            return;
        m_daemon.start(exe, {"--session", "--nofork", "--nopidfile", "--print-address=1"});
        if (!m_daemon.waitForStarted(3000))
            return;
        if (m_daemon.waitForReadyRead(5000))
            m_address = QString::fromUtf8(m_daemon.readLine()).trimmed();
    }

    void cleanupTestCase()
    {
        QDBusConnection::disconnectFromBus("svc");
        QDBusConnection::disconnectFromBus("client");
        QDBusConnection::disconnectFromBus("svc2");
        if (m_daemon.state() != QProcess::NotRunning) {
            m_daemon.terminate();
            m_daemon.waitForFinished(3000);
        }
    }

    void propertiesWithoutBus()
    {
        FakePlayer p;
        MprisService s(&p);
        QVariantMap props = s.playerProperties();
        QCOMPARE(props.value("PlaybackStatus").toString(), QString("Paused"));
        QCOMPARE(props.value("LoopStatus").toString(), QString("Playlist"));
        QCOMPARE(props.value("Shuffle").toBool(), false);
        QCOMPARE(props.value("Volume").toDouble(), 0.8);
        QCOMPARE(props.value("Position").toLongLong(), 5'000'000LL);
        QVERIFY(props.value("CanGoNext").toBool() && props.value("CanSeek").toBool());
        QCOMPARE(props.value("MinimumRate").toDouble(), 0.25);
        const QVariantMap meta = props.value("Metadata").toMap();
        QCOMPARE(meta.value("mpris:trackid").value<QDBusObjectPath>().path(), QString("/org/jetson_player/track/1"));
        QCOMPARE(meta.value("xesam:title").toString(), QString("ep 1.final"));
        QCOMPARE(meta.value("xesam:album").toString(), QStringLiteral("드라마"));
        QVERIFY(meta.value("xesam:url").toString().startsWith("file:///videos/"));
        QCOMPARE(meta.value("mpris:length").toLongLong(), 60'000'000LL);

        p.playing = true;
        p.muted = true;
        p.repeat = "shuffle";
        props = s.playerProperties();
        QCOMPARE(props.value("PlaybackStatus").toString(), QString("Playing"));
        QCOMPARE(props.value("Volume").toDouble(), 0.0);
        QCOMPARE(props.value("Shuffle").toBool(), true);
        p.media = false;
        QCOMPARE(s.playerProperties().value("PlaybackStatus").toString(), QString("Stopped"));
        p.index = 7;   // 범위 밖
        QCOMPARE(s.metadata().value("mpris:trackid").value<QDBusObjectPath>().path(),
                 QString("/org/mpris/MediaPlayer2/TrackList/NoTrack"));
        p.index = 0;
        p.path = "https://youtu.be/abc";
        QCOMPARE(s.metadata().value("xesam:url").toString(), QString("https://youtu.be/abc"));
        QCOMPARE(s.rootProperties().value("Identity").toString(), QString("Jetson Video Player"));
    }

    void actionsWithoutBus()
    {
        FakePlayer p;
        MprisService s(&p);
        s.play();
        QVERIFY(p.playing);
        s.play();   // 이미 재생 중이면 그대로
        QCOMPARE(p.calls.count("toggle"), 1);
        s.stopPlayback();
        QVERIFY(!p.playing);
        QCOMPARE(p.seeks.last(), 0);
        s.setPosition(QDBusObjectPath("/org/jetson_player/track/1"), 2'000'000);
        QCOMPARE(p.seeks.last(), 2'000'000'000LL);
        s.setPosition(QDBusObjectPath("/org/jetson_player/track/2"), 9);   // 다른 곡 → 무시
        QCOMPARE(p.seeks.size(), 2);
        s.seek(-5'000'000);
        QCOMPARE(p.lastRelative, -5.0);
        s.openUri("file:///tmp/a%20b.mkv");
        QCOMPARE(p.calls.last(), QString("open:/tmp/a b.mkv"));
        s.openUri("https://youtu.be/x");
        QCOMPARE(p.calls.last(), QString("url:https://youtu.be/x"));
        s.setVolume(5.0);
        QCOMPARE(p.lastVolume, 2.0);
        s.setLoopStatus("Track");
        QCOMPARE(p.repeat, QString("one"));
        s.setShuffle(true);
        QCOMPARE(p.repeat, QString("shuffle"));
        s.setFullscreen(true);
        s.setFullscreen(true);
        QCOMPARE(p.calls.count("fullscreen"), 1);
    }

    void noBusDoesNotCrash()
    {
        FakePlayer p;
        MprisService s(&p);
        const QDBusConnection bad = QDBusConnection::connectToBus("unix:path=/nonexistent/jvp-bus", "bad");
        QVERIFY(!s.start(bad));
        QVERIFY(!s.isActive());
        s.update();   // 비활성이어도 안전
        QDBusConnection::disconnectFromBus("bad");
    }

    void overDBus()
    {
        if (m_address.isEmpty())
            QSKIP("dbus-daemon을 띄울 수 없습니다");
        QDBusConnection svcBus = QDBusConnection::connectToBus(m_address, "svc");
        QDBusConnection client = QDBusConnection::connectToBus(m_address, "client");
        QVERIFY(svcBus.isConnected() && client.isConnected());

        FakePlayer p;
        MprisService s(&p);
        QVERIFY(s.start(svcBus));
        QVERIFY(s.isActive());

        // 같은 이름은 두 번 얻을 수 없음 → 조용히 false
        QDBusConnection svc2 = QDBusConnection::connectToBus(m_address, "svc2");
        FakePlayer p2;
        MprisService other(&p2);
        QVERIFY(!other.start(svc2));

        SignalSpy spy;
        QVERIFY(client.connect(MprisService::kBusName, MprisService::kObjectPath, "org.freedesktop.DBus.Properties",
                               "PropertiesChanged", &spy, SLOT(onPropertiesChanged(QString, QVariantMap, QStringList))));
        QVERIFY(client.connect(MprisService::kBusName, MprisService::kObjectPath, MprisService::kPlayerIface,
                               "Seeked", &spy, SLOT(onSeeked(qlonglong))));

        QCOMPARE(getProp(client, MprisService::kPlayerIface, "PlaybackStatus").toString(), QString("Paused"));
        QCOMPARE(getProp(client, MprisService::kRootIface, "Identity").toString(), QString("Jetson Video Player"));
        QCOMPARE(getProp(client, MprisService::kPlayerIface, "Position").toLongLong(), 5'000'000LL);

        QCOMPARE(call(client, MprisService::kPlayerIface, "PlayPause").type(), QDBusMessage::ReplyMessage);
        QVERIFY(p.playing);
        call(client, MprisService::kPlayerIface, "Next");
        QCOMPARE(p.calls.last(), QString("next"));
        call(client, MprisService::kPlayerIface, "Seek", {QVariant::fromValue<qlonglong>(10'000'000)});
        QCOMPARE(p.lastRelative, 10.0);
        call(client, MprisService::kPlayerIface, "SetPosition",
             {QVariant::fromValue(QDBusObjectPath("/org/jetson_player/track/1")), QVariant::fromValue<qlonglong>(3'000'000)});
        QCOMPARE(p.seeks.last(), 3'000'000'000LL);
        call(client, MprisService::kPlayerIface, "OpenUri", {QString("file:///tmp/x.mkv")});
        QCOMPARE(p.calls.last(), QString("open:/tmp/x.mkv"));
        call(client, MprisService::kRootIface, "Raise");
        QCOMPARE(p.calls.last(), QString("raise"));

        // Set Volume/LoopStatus
        const QDBusMessage set = call(client, "org.freedesktop.DBus.Properties", "Set",
                                      {QString(MprisService::kPlayerIface), QString("Volume"),
                                       QVariant::fromValue(QDBusVariant(1.5))});
        QCOMPARE(set.type(), QDBusMessage::ReplyMessage);
        QCOMPARE(p.lastVolume, 1.5);
        call(client, "org.freedesktop.DBus.Properties", "Set",
             {QString(MprisService::kPlayerIface), QString("LoopStatus"), QVariant::fromValue(QDBusVariant(QString("Track")))});
        QCOMPARE(p.repeat, QString("one"));

        // update(): 처음엔 전부, 다음엔 바뀐 것만
        s.update();
        QVERIFY(spinUntil([&] { return !spy.changed.isEmpty(); }));
        QVERIFY(spy.changed.first().contains("Metadata"));
        QVERIFY(spy.changed.first().contains("PlaybackStatus"));
        spy.changed.clear();
        s.update();
        p.playing = false;
        s.update();
        QVERIFY(spinUntil([&] { return !spy.changed.isEmpty(); }));
        QCOMPARE(spy.changed.last().keys(), QStringList{"PlaybackStatus"});
        QCOMPARE(spy.changed.last().value("PlaybackStatus").toString(), QString("Paused"));

        // 위치가 크게 튀면 Seeked
        spy.seeked.clear();
        p.positionNs = 40'000'000'000;
        s.update();
        QVERIFY(spinUntil([&] { return !spy.seeked.isEmpty(); }));
        QCOMPARE(spy.seeked.last(), 40'000'000LL);

        s.stop();
        QVERIFY(!s.isActive());
        QVERIFY(!client.interface()->isServiceRegistered(MprisService::kBusName).value());
    }
};

QTEST_GUILESS_MAIN(TestMpris)
#include "test_mpris.moc"
