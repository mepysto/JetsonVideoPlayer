// network.py 순수 함수 이식 검증 (tests/test_network.py 대응)
#include "NetworkUri.h"

#include <QTest>
#include <QVariantMap>

using namespace jvp::network;

namespace {
const QString ROOT = QStringLiteral("/run/user/1000/gvfs/smb-share:server=nas,share=video");

QStringList uris(const QVariantList &locs)
{
    QStringList out;
    for (const QVariant &l : locs)
        out << l.toMap().value("uri").toString();
    return out;
}
} // namespace

class TestNetworkUri : public QObject {
    Q_OBJECT
private slots:
    void normalizeUri_()
    {
        QCOMPARE(normalizeUri("  smb://nas/video/ "), QString("smb://nas/video"));
        QCOMPARE(normalizeUri("SMB://nas/video"), QString("smb://nas/video"));
        QCOMPARE(normalizeUri("\\\\NAS\\video\\드라마"), QString("smb://NAS/video/드라마"));
        QCOMPARE(normalizeUri("/home/me"), QString("/home/me"));
    }

    void isNetworkUri_()
    {
        QVERIFY(isNetworkUri("smb://nas/video") && isNetworkUri("nfs://nas/export"));
        QVERIFY(isNetworkUri(" SFTP://host/x "));
        QVERIFY(!isNetworkUri("/home/me/Videos") && !isNetworkUri("https://youtu.be/x"));
        QVERIFY(!isNetworkUri("") && !isNetworkUri("smbx://a"));
    }

    void displayName_()
    {
        QCOMPARE(displayName("smb://nas/video/%EB%93%9C%EB%9D%BC%EB%A7%88"), QString("nas/video/드라마"));
        QCOMPARE(displayName("smb://user@NAS:445/video/"), QString("nas/video"));
        QCOMPARE(displayName("smb://"), QString("smb://"));
    }

    void isGvfsPath_()
    {
        const QByteArray old = qgetenv("XDG_RUNTIME_DIR");
        qputenv("XDG_RUNTIME_DIR", "/run/user/1000");
        QCOMPARE(gvfsRoot(), QString("/run/user/1000/gvfs"));
        QVERIFY(isGvfsPath(ROOT + "/a.mkv"));
        QVERIFY(!isGvfsPath("/run/user/1000/gvfsx/a.mkv") && !isGvfsPath("/home/a.mkv") && !isGvfsPath(""));
        qputenv("XDG_RUNTIME_DIR", old);
    }

    void rememberAndCleanLocations()
    {
        QVariantList locs = rememberLocation({}, "smb://nas/video", ROOT);
        locs = rememberLocation(locs, "nfs://nas/export", "/run/user/1000/gvfs/nfs:host=nas,prefix=%2Fexport");
        locs = rememberLocation(locs, "smb://nas/video", ROOT);   // 다시 쓰면 맨 앞으로
        QCOMPARE(uris(locs), (QStringList{"smb://nas/video", "nfs://nas/export"}));
        QCOMPARE(locs.at(0).toMap().value("name").toString(), QString("nas/video"));
        QCOMPARE(locs.at(0).toMap().value("path").toString(), ROOT);

        const QVariantList junk{QVariantMap{{"uri", "https://x"}, {"path", "/p"}}, QString("junk"),
                                QVariantMap{{"uri", "smb://a/b"}, {"path", 3}}};
        QCOMPARE(cleanLocations(junk), QVariantList());
        QCOMPARE(cleanLocations(QString("not a list")), QVariantList());
        QVariantList many;
        for (int i = 0; i < 30; ++i)
            many << QVariantMap{{"uri", QString("smb://nas/%1").arg(i)}, {"path", QString("/p%1").arg(i)}};
        QCOMPARE(cleanLocations(many).size(), kMaxLocations);
        // 이름이 없으면 주소로 만들고, 같은 주소는 한 번만
        const QVariantList dup{QVariantMap{{"uri", "smb://nas/a"}, {"path", "/p"}},
                               QVariantMap{{"uri", "smb://nas/a"}, {"path", "/q"}, {"name", "x"}}};
        const QVariantList cleaned = cleanLocations(dup);
        QCOMPARE(cleaned.size(), 1);
        QCOMPARE(cleaned.at(0).toMap().value("name").toString(), QString("nas/a"));
        QCOMPARE(cleaned.at(0).toMap().value("path").toString(), QString("/p"));
    }

    void uriForPathMapsBackForRemount()
    {
        const QVariantList locs{QVariantMap{{"uri", "smb://nas/video"}, {"path", ROOT}, {"name", "nas/video"}}};
        QCOMPARE(uriForPath(locs, ROOT), QString("smb://nas/video"));
        QCOMPARE(uriForPath(locs, ROOT + "/드라마/ep 1.mkv"),
                 QString("smb://nas/video/%EB%93%9C%EB%9D%BC%EB%A7%88/ep%201.mkv"));
        QVERIFY(uriForPath(locs, ROOT + "x/a.mkv").isNull());
        QVERIFY(uriForPath(locs, "/home/a.mkv").isNull());
        // 더 깊은(긴) 위치가 우선
        QVariantList two = locs;
        two << QVariantMap{{"uri", "smb://nas/video/sub"}, {"path", ROOT + "/sub"}};
        QCOMPARE(uriForPath(two, ROOT + "/sub/a.mkv"), QString("smb://nas/video/sub/a.mkv"));
    }
};

QTEST_GUILESS_MAIN(TestNetworkUri)
#include "test_network_uri.moc"
