// 네트워크 폴더: 주소 정리·저장 위치 (tests/test_network.py 이식) + GIO 마운트 완료 신호
#include "NetworkMount.h"

#include <QSignalSpy>
#include <QTemporaryDir>
#include <QtTest>

using namespace jvp;

static const QString ROOT = QStringLiteral("/run/user/1000/gvfs/smb-share:server=nas,share=video");

static QVariantMap loc(const QString &uri, const QVariant &path, const QVariant &name = QVariant())
{
    QVariantMap m{{"uri", uri}, {"path", path}};
    if (name.isValid())
        m.insert("name", name);
    return m;
}

class TestNetworkMount : public QObject {
    Q_OBJECT
private Q_SLOTS:
    void normalizeUri()
    {
        QCOMPARE(NetworkMount::normalizeUri("  smb://nas/video/ "), QString("smb://nas/video"));
        QCOMPARE(NetworkMount::normalizeUri("SMB://nas/video"), QString("smb://nas/video"));
        QCOMPARE(NetworkMount::normalizeUri(QStringLiteral("\\\\NAS\\video\\드라마")), QStringLiteral("smb://NAS/video/드라마"));
    }

    void isNetworkUri()
    {
        QVERIFY(NetworkMount::isNetworkUri("smb://nas/video") && NetworkMount::isNetworkUri("nfs://nas/export"));
        QVERIFY(NetworkMount::isNetworkUri("SFTP://host/x"));
        QVERIFY(!NetworkMount::isNetworkUri("/home/me/Videos") && !NetworkMount::isNetworkUri("https://youtu.be/x"));
    }

    void displayName()
    {
        QCOMPARE(NetworkMount::displayName("smb://nas/video/%EB%93%9C%EB%9D%BC%EB%A7%88"), QStringLiteral("nas/video/드라마"));
        QCOMPARE(NetworkMount::displayName("smb://nas/"), QString("nas"));
    }

    void isGvfsPath()
    {
        const QByteArray old = qgetenv("XDG_RUNTIME_DIR");
        qputenv("XDG_RUNTIME_DIR", "/run/user/1000");
        QVERIFY(NetworkMount::isGvfsPath(ROOT + "/a.mkv"));
        QVERIFY(!NetworkMount::isGvfsPath("/run/user/1000/gvfsx/a.mkv") && !NetworkMount::isGvfsPath("/home/a.mkv"));
        qputenv("XDG_RUNTIME_DIR", old);
    }

    void rememberAndCleanLocations()
    {
        QVariantList locs = NetworkMount::rememberLocation(QVariantList(), "smb://nas/video", ROOT);
        locs = NetworkMount::rememberLocation(locs, "nfs://nas/export", "/run/user/1000/gvfs/nfs:host=nas,prefix=%2Fexport");
        locs = NetworkMount::rememberLocation(locs, "smb://nas/video", ROOT);   // 다시 쓰면 맨 앞으로
        QCOMPARE(locs.size(), 2);
        QCOMPARE(locs[0].toMap().value("uri").toString(), QString("smb://nas/video"));
        QCOMPARE(locs[1].toMap().value("uri").toString(), QString("nfs://nas/export"));
        QCOMPARE(locs[0].toMap().value("name").toString(), QString("nas/video"));

        const QVariantList junk{loc("https://x", "/p"), QString("junk"), loc("smb://a/b", 3)};
        QVERIFY(NetworkMount::cleanLocations(junk).isEmpty());
        QVERIFY(NetworkMount::cleanLocations(QString("not a list")).isEmpty());
        QVariantList many;
        for (int i = 0; i < 30; ++i)
            many.append(loc(QStringLiteral("smb://nas/%1").arg(i), QStringLiteral("/p%1").arg(i)));
        QCOMPARE(NetworkMount::cleanLocations(many).size(), NetworkMount::kMaxLocations);
        QVariantList dup{loc("smb://a/b", "/p", "mine"), loc("smb://a/b", "/q")};
        const QVariantList clean = NetworkMount::cleanLocations(dup);
        QCOMPARE(clean.size(), 1);
        QCOMPARE(clean[0].toMap().value("name").toString(), QString("mine"));
    }

    void uriForPathMapsBackForRemount()
    {
        const QVariantList locs{loc("smb://nas/video", ROOT, "nas/video")};
        QCOMPARE(NetworkMount::uriForPath(locs, ROOT), QString("smb://nas/video"));
        QCOMPARE(NetworkMount::uriForPath(locs, ROOT + QStringLiteral("/드라마/ep 1.mkv")),
                 QString("smb://nas/video/%EB%93%9C%EB%9D%BC%EB%A7%88/ep%201.mkv"));
        QVERIFY(NetworkMount::uriForPath(locs, ROOT + "x/a.mkv").isEmpty());
        QVERIFY(NetworkMount::uriForPath(locs, "/home/a.mkv").isEmpty());
        // 더 긴(구체적인) 위치가 이김
        const QVariantList nested{loc("smb://nas/video", ROOT), loc("smb://nas/video/sub", ROOT + "/sub")};
        QCOMPARE(NetworkMount::uriForPath(nested, ROOT + "/sub/a.mkv"), QString("smb://nas/video/sub/a.mkv"));

        NetworkMount m;
        QVERIFY(!m.mountForPath("/home/a.mkv", locs));   // 모르는 경로는 마운트 시작 안 함
        QVERIFY(!m.isBusy());
    }

    void mountCompletesWithSignal()
    {
        // 로컬 폴더는 GVfs 볼륨이 아니므로 성공이든 오류든 finished가 한 번 와야 합니다 (멈추지 않음).
        QTemporaryDir dir;
        NetworkMount m;
        QSignalSpy spy(&m, &NetworkMount::finished);
        const QString uri = QUrl::fromLocalFile(dir.path()).toString();
        m.mount(uri);
        QVERIFY(m.isBusy());
        QVERIFY(spy.wait(10000));
        QCOMPARE(spy.size(), 1);
        QCOMPARE(spy[0][0].toString(), uri);
        const QString path = spy[0][1].toString(), error = spy[0][2].toString();
        QVERIFY(path.isEmpty() != error.isEmpty());   // 둘 중 하나만
        QVERIFY(!m.isBusy());
    }

    void destroyedWhileMountingIsSafe()
    {
        QTemporaryDir dir;
        auto *m = new NetworkMount;
        m->mount(QUrl::fromLocalFile(dir.path()).toString());
        delete m;   // 콜백은 나중에 와도 안전하게 정리
        QTest::qWait(300);
    }
};

QTEST_GUILESS_MAIN(TestNetworkMount)
#include "test_network_mount.moc"
