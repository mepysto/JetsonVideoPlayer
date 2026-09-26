// 웹 리모컨: 인증·이벤트 방송 단위 테스트 + 실제 소켓(127.0.0.1)으로 HTTP 서버 통합 테스트
// (tests/test_remote.py, tests/test_remote_http.py 이식)
#include "EventBroker.h"
#include "Paths.h"
#include "RemoteAuth.h"
#include "RemoteServer.h"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QThread>
#include <QtTest>

using namespace jvp;

namespace {

struct FakeBackend : RemoteBackend {
    QList<QVariantMap> commands;
    QStringList searches;
    QString thumbFile;
    QList<int> thumbRequests, playlistThumbRequests;

    QJsonObject remoteStatus() override { return {{"title", "t"}, {"is_playing", true}}; }
    QString remoteThumbnailPath(int i) override
    {
        thumbRequests.append(i);
        return i == 0 ? thumbFile : QString();
    }
    QString remotePlaylistThumbnailPath(int i) override
    {
        playlistThumbRequests.append(i);
        return i == 3 ? thumbFile : QString();
    }
    QJsonObject remoteSearch(const QString &q) override
    {
        searches.append(q);
        return {{"indexing", false},
                {"results", QJsonArray{QJsonObject{{"index", 0}, {"sec", 1.5}, {"name", "a.mkv"}, {"text", q}}}}};
    }
    void handleRemoteCommand(const QVariantMap &params) override { commands.append(params); }
};

struct Response {
    int status = 0;
    QList<QPair<QByteArray, QByteArray>> headers;
    QByteArray body;
    bool closed = false;
    QByteArray header(const QByteArray &name) const
    {
        for (const auto &h : headers)
            if (h.first.compare(name, Qt::CaseInsensitive) == 0)
                return h.second;
        return {};
    }
    QJsonObject json() const { return QJsonDocument::fromJson(body).object(); }
};

// 서버가 같은 스레드에서 돌므로 블로킹 대기 대신 이벤트 루프를 돌리며 기다립니다.
template<typename Pred>
bool spinUntil(Pred pred, int timeoutMs = 5000)
{
    QElapsedTimer t;
    t.start();
    while (!pred()) {
        if (t.elapsed() > timeoutMs)
            return false;
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::usleep(500);
    }
    return true;
}

// buf에서 응답 하나를 떼어 냅니다 (완성되지 않았으면 false).
bool takeResponse(QByteArray &buf, Response *out, bool connectionClosed)
{
    const qsizetype end = buf.indexOf("\r\n\r\n");
    if (end < 0)
        return false;
    const QList<QByteArray> lines = buf.left(end).split('\n');
    Response r;
    r.status = lines.value(0).split(' ').value(1).toInt();
    qint64 length = -1;
    for (int i = 1; i < lines.size(); ++i) {
        const QByteArray line = lines[i].trimmed();
        const qsizetype c = line.indexOf(':');
        if (c <= 0)
            continue;
        r.headers.append({line.left(c).trimmed(), line.mid(c + 1).trimmed()});
        if (line.left(c).trimmed().toLower() == "content-length")
            length = line.mid(c + 1).trimmed().toLongLong();
    }
    if (length < 0) {
        if (!connectionClosed)
            return false;
        length = buf.size() - end - 4;
    }
    if (buf.size() < end + 4 + length)
        return false;
    r.body = buf.mid(end + 4, length);
    buf.remove(0, end + 4 + length);
    *out = r;
    return true;
}

QByteArray rawRequest(const QByteArray &method, const QByteArray &path, const QByteArray &body,
                      const QList<QPair<QByteArray, QByteArray>> &headers)
{
    QByteArray req = method + ' ' + path + " HTTP/1.1\r\nHost: 127.0.0.1\r\n";
    for (const auto &h : headers)
        req += h.first + ": " + h.second + "\r\n";
    if (!body.isNull())
        req += "Content-Length: " + QByteArray::number(body.size()) + "\r\n";
    return req + "\r\n" + body;
}

class Client {
public:
    explicit Client(quint16 port)
    {
        sock.connectToHost(QHostAddress::LocalHost, port);
        spinUntil([&] { return sock.state() == QAbstractSocket::ConnectedState; });
    }
    Response send(const QByteArray &raw)
    {
        sock.write(raw);
        Response r;
        const bool ok = spinUntil([&] {
            buf += sock.readAll();
            return takeResponse(buf, &r, sock.state() != QAbstractSocket::ConnectedState);
        });
        buf += sock.readAll();
        if (!ok)
            qWarning() << "응답 시간 초과" << raw.left(60);
        r.closed = spinUntil([&] { return sock.state() == QAbstractSocket::UnconnectedState; }, 0);
        return r;
    }
    bool waitClosed(int ms = 2000)
    {
        return spinUntil([&] { sock.readAll(); return sock.state() == QAbstractSocket::UnconnectedState; }, ms);
    }
    QTcpSocket sock;
    QByteArray buf;
};

Response request(quint16 port, const QByteArray &method, const QByteArray &path,
                 const QJsonObject *body = nullptr, const QByteArray &cookie = {})
{
    QList<QPair<QByteArray, QByteArray>> headers;
    QByteArray data;
    if (body) {
        headers.append(qMakePair(QByteArray("Content-Type"), QByteArray("application/json")));
        data = QJsonDocument(*body).toJson(QJsonDocument::Compact);
    }
    if (!cookie.isEmpty())
        headers.append(qMakePair(QByteArray("Cookie"), cookie));
    Client c(port);
    return c.send(rawRequest(method, path, data, headers));
}

Response post(quint16 port, const QByteArray &path, const QJsonObject &body, const QByteArray &cookie = {})
{
    return request(port, "POST", path, &body, cookie);
}

} // namespace

class TestRemoteServer : public QObject {
    Q_OBJECT
private:
    QTemporaryDir m_home;
    FakeBackend *m_backend = nullptr;
    RemoteAuth *m_auth = nullptr;
    EventBroker *m_broker = nullptr;
    RemoteServer *m_server = nullptr;
    quint16 m_port = 0;

    QByteArray login()
    {
        const Response r = post(m_port, "/api/login", {{"pin", "4242"}});
        if (r.status != 200)
            return {};
        return r.header("Set-Cookie").split(';').value(0);
    }

private Q_SLOTS:
    void initTestCase()
    {
        // 실제 ~/.config를 건드리지 않도록 모든 경로를 임시 폴더로
        QVERIFY(m_home.isValid());
        qputenv("HOME", m_home.path().toUtf8());
        qputenv("XDG_CONFIG_HOME", (m_home.path() + "/config").toUtf8());
        QVERIFY(paths::configDir().startsWith(m_home.path()));
    }

    void init()
    {
        static int n = 0;
        m_backend = new FakeBackend;
        m_auth = new RemoteAuth("4242", m_home.filePath(QStringLiteral("tokens%1.json").arg(++n)));
        m_broker = new EventBroker;
        m_server = new RemoteServer(m_backend, m_auth, m_broker);
        m_server->setSseHeartbeatMs(200);
        QVERIFY(m_server->start({0}, QHostAddress::LocalHost));
        m_port = m_server->port();
        QVERIFY(m_port > 0);
    }

    void cleanup()
    {
        m_broker->close();
        delete m_server;
        delete m_broker;
        delete m_auth;
        delete m_backend;
    }

    // ---- RemoteAuth / EventBroker (test_remote.py) ----
    void pinLoginAndTokenPersistence()
    {
        const QString f = m_home.filePath("persist.json");
        RemoteAuth auth("1234", f);
        QCOMPARE(auth.login("1.1.1.1", "0000").status, RemoteAuth::LoginResult::WrongPin);
        const auto r = auth.login("1.1.1.1", "1234");
        QVERIFY(r.ok() && !r.token.isEmpty());
        QVERIFY(auth.isValid(r.token));
        QVERIFY(!auth.isValid("forged") && !auth.isValid(""));
        QVERIFY(RemoteAuth("1234", f).isValid(r.token));   // 재시작 후에도 유지
        QFile file(f);
        QVERIFY(file.open(QIODevice::ReadOnly));
        const QByteArray saved = file.readAll();
        QVERIFY(!saved.contains(r.token.toUtf8()));         // 원문 토큰은 저장하지 않음
        QVERIFY(saved.contains(RemoteAuth::hashToken(r.token).toUtf8()));
        QVERIFY(auth.login("1.1.1.1", " 1234 ").ok());       // 앞뒤 공백은 무시
    }

    void tokenStoreKeepsLatest20()
    {
        const QString f = m_home.filePath("max.json");
        RemoteAuth auth("1111", f);
        QString first;
        for (int i = 0; i < 21; ++i) {
            const auto r = auth.login("1.1.1.1", "1111");
            if (i == 0)
                first = r.token;
        }
        QVERIFY(!auth.isValid(first));
        QFile file(f);
        QVERIFY(file.open(QIODevice::ReadOnly));
        QCOMPARE(QJsonDocument::fromJson(file.readAll()).array().size(), 20);
    }

    void bruteforceLockoutAndExpiry()
    {
        double t = 1000.0;
        RemoteAuth auth("4321", m_home.filePath("lock.json"), [&] { return t; });
        for (int i = 0; i < 8; ++i)
            QCOMPARE(auth.login("9.9.9.9", "0000").status, RemoteAuth::LoginResult::WrongPin);
        QCOMPARE(auth.login("9.9.9.9", "4321").status, RemoteAuth::LoginResult::Locked);  // 맞는 PIN이어도 잠금 중
        QVERIFY(auth.login("8.8.8.8", "4321").ok());                                     // 다른 IP는 영향 없음
        t += 301;
        QVERIFY(auth.login("9.9.9.9", "4321").ok());
    }

    void resetRevokesTokens()
    {
        RemoteAuth auth("1111", m_home.filePath("reset.json"));
        const auto r = auth.login("1.1.1.1", "1111");
        auth.reset("2222");
        QVERIFY(!auth.isValid(r.token));
        QVERIFY(!auth.login("1.1.1.1", "1111").ok());
        QVERIFY(auth.login("1.1.1.1", "2222").ok());
        QVERIFY(!RemoteAuth("2222", m_home.filePath("reset.json")).isValid(r.token));
    }

    void generatePin()
    {
        QSet<QString> pins;
        for (int i = 0; i < 50; ++i) {
            const QString p = RemoteAuth::generatePin();
            QCOMPARE(p.size(), 4);
            bool ok = false;
            p.toInt(&ok);
            QVERIFY(ok);
            pins.insert(p);
        }
        QVERIFY(pins.size() > 1);
    }

    void defaultTokenFileIsInConfigDir()
    {
        QCOMPARE(RemoteAuth::defaultTokenFile(), paths::configDir() + "/remote_tokens.json");
        RemoteAuth auth("5555");
        QVERIFY(auth.login("1.1.1.1", "5555").ok());
        QVERIFY(QFile::exists(paths::configDir() + "/remote_tokens.json"));
    }

    void eventBrokerDedupAndWait()
    {
        EventBroker b;
        QVERIFY(b.publish("status", QJsonObject{{"a", 1}}));
        QVERIFY(!b.publish("status", QJsonObject{{"a", 1}}));   // 같은 내용은 재전송 안 함
        qint64 ver = 0;
        auto items = b.waitNewer(0, 10, &ver);
        QCOMPARE(items.size(), 1);
        QCOMPARE(items[0].name, QString("status"));
        QCOMPARE(items[0].data, QByteArray("{\"a\":1}"));

        QList<EventBroker::Event> got;
        qint64 gotVer = 0;
        QThread *t = QThread::create([&] { got = b.waitNewer(ver, 2000, &gotVer); });
        t->start();
        QThread::msleep(50);
        b.publish("playlist", QJsonArray{1, 2});
        QVERIFY(t->wait(3000));
        delete t;
        QCOMPARE(got.size(), 1);
        QCOMPARE(got[0].name, QString("playlist"));
        QCOMPARE(got[0].data, QByteArray("[1,2]"));
        QVERIFY(b.waitNewer(gotVer, 10, &gotVer).isEmpty());
        QCOMPARE(EventBroker::toJson(QJsonValue("x")), QByteArray("\"x\""));
    }

    // ---- HTTP (test_remote_http.py) ----
    void requiresLoginAndServesLoginPage()
    {
        QCOMPARE(request(m_port, "GET", "/api/status").status, 401);
        QCOMPARE(post(m_port, "/api/cmd", {{"action", "next"}}).status, 401);
        const Response r = request(m_port, "GET", "/");
        QCOMPARE(r.status, 200);
        QVERIFY(QString::fromUtf8(r.body).contains(QStringLiteral("로그인")));
        QVERIFY(r.header("Content-Type").startsWith("text/html"));
        QVERIFY(m_backend->commands.isEmpty());
        QCOMPARE(post(m_port, "/api/login", {{"pin", "0000"}}).status, 401);
    }

    void loginServesRemotePageAndStatus()
    {
        const QByteArray cookie = login();
        QVERIFY(cookie.startsWith("jvp_token="));
        Response r = request(m_port, "GET", "/", nullptr, cookie);
        QCOMPARE(r.status, 200);
        QVERIFY(r.body.size() > 10000);   // index.html
        r = request(m_port, "GET", "/api/status", nullptr, cookie);
        QCOMPARE(r.status, 200);
        QCOMPARE(r.json().value("title").toString(), QString("t"));
        QCOMPARE(r.header("Cache-Control"), QByteArray("no-store"));
        QCOMPARE(request(m_port, "GET", "/api/nope", nullptr, cookie).status, 404);
        QCOMPARE(request(m_port, "GET", "/nope").status, 404);
    }

    void tokenHeaderFallback()
    {
        const QByteArray token = login().split('=').value(1);
        Client c(m_port);
        const Response r = c.send(rawRequest("GET", "/api/status", QByteArray(), {{"X-JVP-Token", token}}));
        QCOMPARE(r.status, 200);
        // 다른 쿠키만 있으면 헤더로 대체
        const Response r2 = c.send(rawRequest("GET", "/api/status", QByteArray(),
                                              {{"Cookie", "other=1"}, {"X-JVP-Token", token}}));
        QCOMPARE(r2.status, 200);
    }

    void manifestAndIconWithoutLogin()
    {
        Response r = request(m_port, "GET", "/manifest.json");
        QCOMPARE(r.status, 200);
        QCOMPARE(r.json().value("start_url").toString(), QString("/"));
        QCOMPARE(r.header("Content-Type"), QByteArray("application/manifest+json"));
        r = request(m_port, "GET", "/icon.svg");
        QCOMPARE(r.status, 200);
        QCOMPARE(r.header("Content-Type"), QByteArray("image/svg+xml"));
        QVERIFY(r.body.contains("<svg"));
    }

    void commandsNeedJsonPost()
    {
        const QByteArray cookie = login();
        QCOMPARE(request(m_port, "GET", "/api/cmd?action=next", nullptr, cookie).status, 404);
        {
            Client c(m_port);
            const Response r = c.send(rawRequest("POST", "/api/cmd", "action=next",
                                                 {{"Cookie", cookie}, {"Content-Type", "application/x-www-form-urlencoded"}}));
            QCOMPARE(r.status, 400);
            QCOMPARE(r.json().value("error").toString(), QString("JSON body required"));
        }
        {
            Client c(m_port);   // JSON이지만 객체가 아님
            QCOMPARE(c.send(rawRequest("POST", "/api/cmd", "[1]", {{"Cookie", cookie}, {"Content-Type", "application/json"}})).status, 400);
        }
        QCOMPARE(post(m_port, "/api/cmd", {{"val", 1}}, cookie).status, 400);   // action 없음
        QCOMPARE(post(m_port, "/api/cmd", {{"action", ""}}, cookie).status, 400);
        const Response r = post(m_port, "/api/cmd", {{"action", "seek_abs"}, {"sec", 12}, {"evil", "x"}, {"url", QJsonValue()}}, cookie);
        QCOMPARE(r.status, 200);
        QCOMPARE(r.json().value("status").toString(), QString("ok"));
        QCOMPARE(m_backend->commands.size(), 1);
        const QVariantMap cmd = m_backend->commands[0];
        QCOMPARE(cmd.keys(), (QStringList{"action", "sec"}));
        QCOMPARE(cmd.value("action").toString(), QString("seek_abs"));
        QCOMPARE(cmd.value("sec").toInt(), 12);
        QCOMPARE(post(m_port, "/api/other", {{"action", "x"}}, cookie).status, 404);
    }

    void numericPinAndLockoutOverHttp()
    {
        QCOMPARE(post(m_port, "/api/login", {{"pin", 4242}}).status, 200);   // 파이썬 str(4242)
        for (int i = 0; i < 8; ++i)
            QCOMPARE(post(m_port, "/api/login", {{"pin", "0000"}}).status, 401);
        const Response r = post(m_port, "/api/login", {{"pin", "4242"}});
        QCOMPARE(r.status, 429);
        QVERIFY(r.json().value("error").toString().contains("too many attempts"));
    }

    void qrLinkLoginRedirectsWithCookie()
    {
        const Response r = request(m_port, "GET", "/?pin=4242");
        QCOMPARE(r.status, 302);
        QCOMPARE(r.header("Location"), QByteArray("/"));
        const QByteArray cookie = r.header("Set-Cookie");
        QVERIFY(cookie.contains("HttpOnly"));
        QVERIFY(cookie.contains("SameSite=Strict"));
        QVERIFY(cookie.contains("Max-Age=31536000"));
        QVERIFY(cookie.contains("Path=/"));
        QCOMPARE(request(m_port, "GET", "/api/status", nullptr, cookie.split(';').value(0)).status, 200);
        // 틀린 PIN이면 로그인 페이지
        const Response bad = request(m_port, "GET", "/?pin=1111");
        QCOMPARE(bad.status, 200);
        QVERIFY(QString::fromUtf8(bad.body).contains(QStringLiteral("로그인")));
    }

    void sseSendsSnapshotRetryPingAndDeltas()
    {
        m_broker->publish("status", QJsonObject{{"n", 1}});
        m_broker->publish("playlist", QJsonArray{1});
        const QByteArray cookie = login();
        Client c(m_port);
        c.sock.write(rawRequest("GET", "/api/events", QByteArray(), {{"Cookie", cookie}}));
        QByteArray stream;
        QStringList lines;
        bool published = false;
        auto pings = [&] { return lines.count("event: ping"); };
        const bool ok = spinUntil([&] {
            stream += c.sock.readAll();
            lines = QString::fromUtf8(stream).split('\n');
            if (!published && lines.contains("data: {\"n\":1}")) {
                published = true;
                m_broker->publish("status", QJsonObject{{"n", 1}});   // 같은 내용 → 안 나감
                m_broker->publish("status", QJsonObject{{"n", 2}});
            }
            return lines.contains("data: {\"n\":2}") && pings() >= 2;
        }, 5000);
        QVERIFY2(ok, stream.constData());
        QVERIFY(stream.startsWith("HTTP/1.1 200 OK\r\n"));
        QVERIFY(stream.contains("Content-Type: text/event-stream\r\n"));
        QVERIFY(lines.contains("retry: 2000"));
        QVERIFY(lines.contains("event: status"));
        QVERIFY(lines.contains("data: [1]"));
        QCOMPARE(lines.count("data: {\"n\":1}"), 1);
        QCOMPARE(m_server->sseClientCount(), 1);
        // 방송 종료 → 연결 닫힘
        m_broker->close();
        QVERIFY(c.waitClosed());
        QVERIFY(spinUntil([&] { return m_server->sseClientCount() == 0; }));
    }

    void sseRequiresLogin() { QCOMPARE(request(m_port, "GET", "/api/events").status, 401); }

    void sharePageIsPublicButSendingNeedsLogin()
    {
        const Response r = request(m_port, "GET", "/share?url=https%3A%2F%2Fyoutu.be%2Fabc");
        QCOMPARE(r.status, 200);
        QVERIFY(r.body.contains("JETSON"));
        QVERIFY(m_backend->commands.isEmpty());   // 페이지를 여는 것만으로는 아무것도 보내지 않음
        QCOMPARE(post(m_port, "/api/cmd", {{"action", "yt"}, {"url", "https://youtu.be/abc"}}).status, 401);
    }

    void nonLanClientsAreRejected()
    {
        m_server->setLanCheck([](const QHostAddress &) { return false; });
        Client c(m_port);
        Response r = c.send(rawRequest("GET", "/", QByteArray(), {}));
        QCOMPARE(r.status, 403);
        QVERIFY(c.waitClosed());   // 403 뒤 연결을 닫음
        QCOMPARE(post(m_port, "/api/login", {{"pin", "4242"}}).status, 403);
        m_server->setLanOnly(false);
        QCOMPARE(request(m_port, "GET", "/").status, 200);
    }

    void isLanClient_data()
    {
        QTest::addColumn<QString>("addr");
        QTest::addColumn<bool>("expected");
        const QList<QPair<QString, bool>> cases = {
            {"192.168.0.10", true}, {"10.1.2.3", true}, {"172.16.5.5", true}, {"127.0.0.1", true},
            {"169.254.1.1", true}, {"::1", true}, {"fe80::1", true}, {"fd00::5", true},
            {"::ffff:192.168.1.2", true}, {"8.8.8.8", false}, {"2001:4860:4860::8888", false},
            {"::ffff:8.8.8.8", false}, {"not-an-ip", false}, {"172.32.0.1", false}, {"100.64.0.1", false},
            {"", false},
        };
        for (const auto &c : cases)
            QTest::newRow(qPrintable(c.first.isEmpty() ? QStringLiteral("empty") : c.first)) << c.first << c.second;
    }
    void isLanClient()
    {
        QFETCH(QString, addr);
        QFETCH(bool, expected);
        QCOMPARE(RemoteServer::isLanClient(addr), expected);
    }

    void dialogueSearchApi()
    {
        QCOMPARE(request(m_port, "GET", "/api/search?q=hi").status, 401);
        const QByteArray cookie = login();
        Response r = request(m_port, "GET", "/api/search?q=%EC%95%88%EB%85%95", nullptr, cookie);
        QCOMPARE(r.status, 200);
        QCOMPARE(r.json().value("results").toArray().at(0).toObject().value("text").toString(), QStringLiteral("안녕"));
        request(m_port, "GET", "/api/search?q=a+b", nullptr, cookie);
        QCOMPARE(m_backend->searches.last(), QString("a b"));
        request(m_port, "GET", "/api/search?q=" + QByteArray(300, 'x'), nullptr, cookie);
        QCOMPARE(m_backend->searches.last().size(), 200);
        r = post(m_port, "/api/cmd", {{"action", "play_at"}, {"index", 0}, {"sec", 1.5}}, cookie);
        QCOMPARE(r.status, 200);
        const QVariantMap cmd = m_backend->commands.last();
        QCOMPARE(cmd.size(), 3);
        QCOMPARE(cmd.value("action").toString(), QString("play_at"));
        QCOMPARE(cmd.value("index").toInt(), 0);
        QCOMPARE(cmd.value("sec").toDouble(), 1.5);
    }

    void thumbnails()
    {
        const QString jpg = m_home.filePath("thumb.jpg");
        QFile f(jpg);
        QVERIFY(f.open(QIODevice::WriteOnly));
        f.write("\xff\xd8\xff fake jpeg");
        f.close();
        m_backend->thumbFile = jpg;
        QCOMPARE(request(m_port, "GET", "/api/thumb?i=0").status, 401);
        const QByteArray cookie = login();
        Response r = request(m_port, "GET", "/api/thumb?i=0", nullptr, cookie);
        QCOMPARE(r.status, 200);
        QCOMPARE(r.header("Content-Type"), QByteArray("image/jpeg"));
        QCOMPARE(r.header("Cache-Control"), QByteArray("max-age=3600"));
        QVERIFY(r.body.startsWith("\xff\xd8\xff"));
        QCOMPARE(request(m_port, "GET", "/api/thumb?i=1", nullptr, cookie).status, 404);
        QCOMPARE(request(m_port, "GET", "/api/thumb?i=abc", nullptr, cookie).status, 404);
        QCOMPARE(m_backend->thumbRequests.last(), -1);
        QCOMPARE(request(m_port, "GET", "/api/thumb?p=3&v=1", nullptr, cookie).status, 200);
        QCOMPARE(m_backend->playlistThumbRequests.last(), 3);
        QCOMPARE(request(m_port, "GET", "/api/thumb?p=2", nullptr, cookie).status, 404);
    }

    void keepAliveAndPipelining()
    {
        const QByteArray cookie = login();
        Client c(m_port);
        Response a = c.send(rawRequest("GET", "/api/status", QByteArray(), {{"Cookie", cookie}}));
        QCOMPARE(a.status, 200);
        QVERIFY(!a.closed);
        // 두 요청을 한 번에 보내도 차례로 응답
        c.sock.write(rawRequest("GET", "/manifest.json", QByteArray(), {}) + rawRequest("GET", "/icon.svg", QByteArray(), {}));
        Response m, i;
        QVERIFY(spinUntil([&] { c.buf += c.sock.readAll(); return takeResponse(c.buf, &m, false); }));
        QVERIFY(spinUntil([&] { c.buf += c.sock.readAll(); return takeResponse(c.buf, &i, false); }));
        QCOMPARE(m.header("Content-Type"), QByteArray("application/manifest+json"));
        QCOMPARE(i.header("Content-Type"), QByteArray("image/svg+xml"));
        // Connection: close면 응답 뒤 닫음
        const Response last = c.send(rawRequest("GET", "/manifest.json", QByteArray(), {{"Connection", "close"}}));
        QCOMPARE(last.status, 200);
        QVERIFY(c.waitClosed());
    }

    void bodyLimitsAndBadRequests()
    {
        Client big(m_port);
        const QByteArray header = "POST /api/login HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: "
                                  + QByteArray::number(RemoteServer::kMaxBody + 1) + "\r\n\r\n";
        big.sock.write(header);
        Response r;
        QVERIFY(spinUntil([&] { big.buf += big.sock.readAll(); return takeResponse(big.buf, &r, false); }));
        QCOMPARE(r.status, 400);
        QVERIFY(big.waitClosed());

        Client bad(m_port);
        QCOMPARE(bad.send("garbage\r\n\r\n").status, 400);
        Client head(m_port);
        QCOMPARE(head.send(rawRequest("HEAD", "/", QByteArray(), {})).status, 501);
        QCOMPARE(post(m_port, "/api/login", QJsonObject()).status, 401);   // pin 없음 → 틀린 PIN
        Client empty(m_port);
        QCOMPARE(empty.send(rawRequest("POST", "/api/login", QByteArray(""), {{"Content-Type", "application/json"}})).status, 400);
    }

    void bodyArrivingInPieces()
    {
        Client c(m_port);
        const QByteArray raw = rawRequest("POST", "/api/login", "{\"pin\":\"4242\"}", {{"Content-Type", "application/json"}});
        c.sock.write(raw.left(20));
        spinUntil([] { return false; }, 50);
        c.sock.write(raw.mid(20, raw.size() - 25));
        spinUntil([] { return false; }, 50);
        c.sock.write(raw.right(5));
        Response r;
        QVERIFY(spinUntil([&] { c.buf += c.sock.readAll(); return takeResponse(c.buf, &r, false); }));
        QCOMPARE(r.status, 200);
        QVERIFY(r.header("Set-Cookie").startsWith("jvp_token="));
    }

    void openServerWithoutAuth()
    {
        FakeBackend backend;
        RemoteServer open(&backend, nullptr, nullptr);
        QVERIFY(open.start({0}, QHostAddress::LocalHost));
        QCOMPARE(request(open.port(), "GET", "/api/status").status, 200);
        const Response r = post(open.port(), "/api/login", {{"pin", "x"}});
        QCOMPARE(r.status, 200);
        QVERIFY(r.header("Set-Cookie").startsWith("jvp_token=open;"));
        QCOMPARE(post(open.port(), "/api/cmd", {{"action", "next"}}).status, 200);
        QCOMPARE(backend.commands.size(), 1);
    }

    void portFallbackAndUrls()
    {
        RemoteServer second(m_backend, m_auth, m_broker);
        // 첫 포트가 이미 쓰이면 다음 포트로
        QVERIFY(second.start({m_port, 0}, QHostAddress::LocalHost));
        QVERIFY(second.port() != m_port);
        QVERIFY(m_server->url().startsWith("http://"));
        QVERIFY(m_server->url().endsWith(":" + QString::number(m_port)));
        QCOMPARE(m_server->loginUrl(), m_server->url() + "/?pin=4242");
        second.stop();
        QVERIFY(!second.isListening());
        QCOMPARE(second.port(), quint16(0));
    }
};

QTEST_GUILESS_MAIN(TestRemoteServer)
#include "test_remote_server.moc"
