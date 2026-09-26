#include "RemoteServer.h"

#include "EventBroker.h"
#include "RemoteAuth.h"
#include "SystemInfo.h"

#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLoggingCategory>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTimer>
#include <QUrl>
#include <cmath>

Q_LOGGING_CATEGORY(lcRemote, "jvp.remote")

namespace jvp {

namespace {
constexpr qsizetype kMaxHeaderBytes = 64 * 1024;   // 요청 줄 + 헤더
constexpr int kMaxConnections = 128;                // 폰 몇 대 × 브라우저 연결 수를 넉넉히
constexpr qint64 kMaxSseBacklog = 4 * 1024 * 1024;  // 읽지 않는 SSE 클라이언트에 쌓아 둘 최대치

using Headers = QList<QPair<QByteArray, QByteArray>>;

QByteArray readResource(const QString &name)
{
    QFile f(QStringLiteral(":/remote/") + name);
    if (!f.open(QIODevice::ReadOnly)) {
        qCWarning(lcRemote) << "⚠️ 리모컨 리소스 없음:" << name;
        return {};
    }
    return f.readAll();
}

const QByteArray &remoteHtml() { static const QByteArray d = readResource(QStringLiteral("index.html")); return d; }
const QByteArray &loginHtml() { static const QByteArray d = readResource(QStringLiteral("login.html")); return d; }
const QByteArray &shareHtml() { static const QByteArray d = readResource(QStringLiteral("share.html")); return d; }
const QByteArray &iconSvg() { static const QByteArray d = readResource(QStringLiteral("icon.svg")); return d; }

const QByteArray &manifestJson()
{
    static const QByteArray d = QJsonDocument(QJsonObject{
        {"name", "Jetson Player Remote"},
        {"short_name", QStringLiteral("Jetson 리모컨")},
        {"start_url", "/"},
        {"display", "standalone"},
        {"background_color", "#0c1017"},
        {"theme_color", "#0c1017"},
        {"icons", QJsonArray{QJsonObject{{"src", "/icon.svg"}, {"sizes", "any"},
                                         {"type", "image/svg+xml"}, {"purpose", "any"}}}},
    }).toJson(QJsonDocument::Compact);
    return d;
}

QByteArray reasonPhrase(int code)
{
    switch (code) {
    case 100: return "Continue";
    case 200: return "OK";
    case 302: return "Found";
    case 400: return "Bad Request";
    case 401: return "Unauthorized";
    case 403: return "Forbidden";
    case 404: return "Not Found";
    case 429: return "Too Many Requests";
    case 431: return "Request Header Fields Too Large";
    case 501: return "Not Implemented";
    default: return "Unknown";
    }
}

// urllib.parse.parse_qs와 같게: '+'는 공백, 퍼센트 디코딩, 값이 빈 항목은 버림, 같은 키는 처음 값
QHash<QString, QString> parseQuery(const QByteArray &query)
{
    QHash<QString, QString> result;
    for (const QByteArray &part : query.split('&')) {
        const qsizetype eq = part.indexOf('=');
        if (eq < 0)
            continue;
        auto decode = [](QByteArray s) { return QUrl::fromPercentEncoding(s.replace('+', ' ')); };
        const QString key = decode(part.left(eq));
        const QString value = decode(part.mid(eq + 1));
        if (value.isEmpty() || result.contains(key))
            continue;
        result.insert(key, value);
    }
    return result;
}

// 파이썬 truthiness: 빈 문자열·0·false·null·빈 배열/객체는 거짓
bool truthy(const QJsonValue &v)
{
    switch (v.type()) {
    case QJsonValue::Bool: return v.toBool();
    case QJsonValue::Double: return v.toDouble() != 0.0;
    case QJsonValue::String: return !v.toString().isEmpty();
    case QJsonValue::Array: return !v.toArray().isEmpty();
    case QJsonValue::Object: return !v.toObject().isEmpty();
    default: return false;
    }
}

// 파이썬 str(value): 숫자 PIN(4242)도 "4242"로
QString pyStr(const QJsonValue &v)
{
    switch (v.type()) {
    case QJsonValue::String: return v.toString();
    case QJsonValue::Bool: return v.toBool() ? QStringLiteral("True") : QStringLiteral("False");
    case QJsonValue::Double: {
        const double d = v.toDouble();
        if (std::isfinite(d) && d == std::floor(d) && std::fabs(d) < 1e15)
            return QString::number(static_cast<qint64>(d));
        return QString::number(d);
    }
    case QJsonValue::Null:
    case QJsonValue::Undefined: return QStringLiteral("None");
    default: return QString::fromUtf8(EventBroker::toJson(v));
    }
}

// 파이썬 int(): 앞뒤 공백 허용, 실패하면 -1 (백엔드는 음수를 '없음'으로 봅니다)
int toIndex(const QString &s)
{
    bool ok = false;
    const int v = s.trimmed().toInt(&ok);
    return ok ? v : -1;
}

// q[:200] — 코드 포인트 기준으로 자르되 서로게이트 쌍을 가르지 않게
QString leftCodePoints(const QString &s, int n)
{
    qsizetype i = 0;
    for (int count = 0; i < s.size() && count < n; ++count)
        i += (s.at(i).isHighSurrogate() && i + 1 < s.size() && s.at(i + 1).isLowSurrogate()) ? 2 : 1;
    return s.left(i);
}

QHostAddress unmapped(const QHostAddress &addr)
{
    if (addr.protocol() == QAbstractSocket::IPv6Protocol) {
        bool ok = false;
        const quint32 v4 = addr.toIPv4Address(&ok);
        if (ok)
            return QHostAddress(v4);
    }
    return addr;
}
} // namespace

struct RemoteServer::Request {
    QByteArray method;
    QByteArray target;
    QByteArray version;
    QByteArray path;
    QHash<QString, QString> query;
    Headers headers;   // 이름은 소문자
    QByteArray body;
    QString ip;
    bool keepAlive = true;

    QByteArray header(const QByteArray &lowerName) const
    {
        for (const auto &h : headers)
            if (h.first == lowerName)
                return h.second;
        return {};
    }
    bool hasHeader(const QByteArray &lowerName) const
    {
        for (const auto &h : headers)
            if (h.first == lowerName)
                return true;
        return false;
    }
};

struct RemoteServer::Conn {
    QByteArray buf;
    bool sse = false;
    bool closing = false;
    bool sentContinue = false;
    qint64 version = 0;
    QTimer *timer = nullptr;   // HTTP: 유휴 제한, SSE: 하트비트
    QElapsedTimer lastDrain;   // 마지막으로 전송 버퍼가 비었거나 줄어든 시각
};

const QStringList &RemoteServer::commandFields()
{
    static const QStringList fields{QStringLiteral("action"), QStringLiteral("val"),     QStringLiteral("index"),
                                    QStringLiteral("delta"),  QStringLiteral("percent"), QStringLiteral("url"),
                                    QStringLiteral("quality"), QStringLiteral("sec"),    QStringLiteral("minutes")};
    return fields;
}

RemoteServer::RemoteServer(RemoteBackend *backend, RemoteAuth *auth, EventBroker *broker, QObject *parent)
    : QObject(parent), m_backend(backend), m_auth(auth), m_broker(broker), m_server(new QTcpServer(this))
{
    connect(m_server, &QTcpServer::newConnection, this, &RemoteServer::onNewConnection);
    if (m_broker) {
        // 다른 스레드에서 게시해도 큐로 이 스레드에 넘어옵니다.
        connect(m_broker, &EventBroker::published, this, &RemoteServer::pushEvents);
        connect(m_broker, &EventBroker::closed, this, [this] {
            for (auto it = m_conns.cbegin(); it != m_conns.cend(); ++it)
                if (it.value()->sse)
                    it.key()->disconnectFromHost();
        });
    }
}

RemoteServer::~RemoteServer() { stop(); }

bool RemoteServer::start(const QList<quint16> &ports, const QHostAddress &address)
{
    stop();
    for (quint16 port : ports) {
        if (m_server->listen(address, port)) {
            qCInfo(lcRemote).noquote() << "📱 [웹 리모컨 서버 활성화] 스마트폰 접속 주소:"
                                       << (address.isLoopback() ? QStringLiteral("http://%1:%2").arg(address.toString()).arg(m_server->serverPort()) : url());
            Q_EMIT started(m_server->serverPort());
            return true;
        }
        qCDebug(lcRemote) << "포트" << port << "사용 불가:" << m_server->errorString();
    }
    qCWarning(lcRemote) << "⚠️ 웹 리모컨 서버를 열 수 없습니다 (모든 포트 사용 중)";
    return false;
}

void RemoteServer::stop()
{
    if (m_server->isListening())
        m_server->close();
    const auto socks = m_conns.keys();
    for (QTcpSocket *s : socks) {
        s->abort();
        dropConnection(s);
    }
}

bool RemoteServer::isListening() const { return m_server->isListening(); }
quint16 RemoteServer::port() const { return m_server->isListening() ? m_server->serverPort() : 0; }

QString RemoteServer::url() const
{
    return QStringLiteral("http://%1:%2").arg(SystemInfo::localIp()).arg(port());
}

QString RemoteServer::loginUrl() const
{
    return m_auth ? url() + QStringLiteral("/?pin=") + m_auth->pin() : url();
}

int RemoteServer::sseClientCount() const
{
    int n = 0;
    for (const Conn *c : m_conns)
        n += c->sse ? 1 : 0;
    return n;
}

bool RemoteServer::isLanClient(const QString &address)
{
    QHostAddress addr;
    // QHostAddress는 "127.1" 같은 축약형도 받지만 파이썬 ipaddress는 거부하므로 점 네 개짜리만 IPv4로 인정
    if (!address.contains(QLatin1Char(':')) && address.count(QLatin1Char('.')) != 3)
        return false;
    if (!addr.setAddress(address))
        return false;
    return isLanClient(addr);
}

bool RemoteServer::isLanClient(const QHostAddress &address)
{
    // 파이썬 ipaddress의 is_private / is_loopback / is_link_local 범위
    static const QList<QPair<QHostAddress, int>> v4 = {
        QHostAddress::parseSubnet(QStringLiteral("0.0.0.0/8")),
        QHostAddress::parseSubnet(QStringLiteral("10.0.0.0/8")),
        QHostAddress::parseSubnet(QStringLiteral("127.0.0.0/8")),
        QHostAddress::parseSubnet(QStringLiteral("169.254.0.0/16")),
        QHostAddress::parseSubnet(QStringLiteral("172.16.0.0/12")),
        QHostAddress::parseSubnet(QStringLiteral("192.0.0.0/29")),
        QHostAddress::parseSubnet(QStringLiteral("192.0.0.170/31")),
        QHostAddress::parseSubnet(QStringLiteral("192.0.2.0/24")),
        QHostAddress::parseSubnet(QStringLiteral("192.168.0.0/16")),
        QHostAddress::parseSubnet(QStringLiteral("198.18.0.0/15")),
        QHostAddress::parseSubnet(QStringLiteral("198.51.100.0/24")),
        QHostAddress::parseSubnet(QStringLiteral("203.0.113.0/24")),
        QHostAddress::parseSubnet(QStringLiteral("240.0.0.0/4")),
        QHostAddress::parseSubnet(QStringLiteral("255.255.255.255/32")),
    };
    static const QList<QPair<QHostAddress, int>> v6 = {
        QHostAddress::parseSubnet(QStringLiteral("::1/128")),
        QHostAddress::parseSubnet(QStringLiteral("::/128")),
        QHostAddress::parseSubnet(QStringLiteral("100::/64")),
        QHostAddress::parseSubnet(QStringLiteral("2001::/23")),
        QHostAddress::parseSubnet(QStringLiteral("2001:db8::/32")),
        QHostAddress::parseSubnet(QStringLiteral("2001:10::/28")),
        QHostAddress::parseSubnet(QStringLiteral("fc00::/7")),
        QHostAddress::parseSubnet(QStringLiteral("fe80::/10")),
    };
    const QHostAddress addr = unmapped(address);
    if (addr.isNull())
        return false;
    const auto &nets = addr.protocol() == QAbstractSocket::IPv4Protocol ? v4 : v6;
    for (const auto &net : nets)
        if (addr.isInSubnet(net))
            return true;
    return false;
}

// ---- 연결 관리 ---------------------------------------------------------------

void RemoteServer::onNewConnection()
{
    while (QTcpSocket *sock = m_server->nextPendingConnection()) {
        if (m_conns.size() >= kMaxConnections) {
            qCWarning(lcRemote) << "⚠️ 리모컨 연결이 너무 많아 새 연결을 거부합니다";
            sock->abort();
            sock->deleteLater();
            continue;
        }
        auto *c = new Conn;
        c->lastDrain.start();
        c->timer = new QTimer(sock);
        c->timer->setSingleShot(true);
        c->timer->setInterval(m_idleTimeoutMs);
        m_conns.insert(sock, c);

        connect(c->timer, &QTimer::timeout, this, [this, sock] {
            Conn *conn = m_conns.value(sock);
            if (!conn)
                return;
            if (conn->sse)
                sseHeartbeat(sock);
            else
                sock->abort();   // 오래 쓰지 않는 keep-alive 연결 정리
        });
        connect(sock, &QTcpSocket::readyRead, this, [this, sock] { onReadyRead(sock); });
        connect(sock, &QTcpSocket::bytesWritten, this, [this, sock] {
            Conn *conn = m_conns.value(sock);
            if (!conn)
                return;
            conn->lastDrain.restart();
            if (!conn->sse)
                conn->timer->start();
        });
        connect(sock, &QTcpSocket::disconnected, this, [this, sock] { dropConnection(sock); });
        // 폰 화면 꺼짐·네트워크 전환으로 끊긴 연결은 흔하므로 조용히 정리합니다.
        connect(sock, &QTcpSocket::errorOccurred, this, [this, sock](QAbstractSocket::SocketError) {
            if (sock->state() == QAbstractSocket::UnconnectedState)
                dropConnection(sock);
        });
        c->timer->start();
        if (sock->bytesAvailable())
            onReadyRead(sock);
    }
}

void RemoteServer::dropConnection(QTcpSocket *sock)
{
    Conn *c = m_conns.take(sock);
    if (!c)
        return;
    delete c;
    sock->disconnect(this);
    sock->deleteLater();
}

void RemoteServer::onReadyRead(QTcpSocket *sock)
{
    Conn *c = m_conns.value(sock);
    if (!c)
        return;
    const QByteArray data = sock->readAll();
    if (c->sse || c->closing)
        return;   // SSE 연결에서 오는 데이터는 의미 없음
    c->buf += data;
    c->timer->start();
    processBuffer(sock);
}

void RemoteServer::processBuffer(QTcpSocket *sock)
{
    // 파이프라이닝: 버퍼에 요청이 여러 개 있으면 차례로 처리합니다.
    while (true) {
        Conn *c = m_conns.value(sock);
        if (!c || c->sse || c->closing)
            return;
        const qsizetype headerEnd = c->buf.indexOf("\r\n\r\n");
        if (headerEnd < 0) {
            if (c->buf.size() > kMaxHeaderBytes)
                send(sock, 431, "request header too large", "text/plain", {}, true);
            return;
        }
        if (headerEnd > kMaxHeaderBytes) {
            send(sock, 431, "request header too large", "text/plain", {}, true);
            return;
        }

        Request req;
        req.ip = clientIp(sock);
        const QList<QByteArray> lines = c->buf.left(headerEnd).split('\n');
        const QList<QByteArray> requestLine = lines.value(0).trimmed().split(' ');
        if (requestLine.size() != 3 || !requestLine[2].startsWith("HTTP/")) {
            send(sock, 400, "bad request", "text/plain", {}, true);
            return;
        }
        req.method = requestLine[0];
        req.target = requestLine[1];
        req.version = requestLine[2];
        for (int i = 1; i < lines.size(); ++i) {
            const QByteArray line = lines[i].trimmed();
            if (line.isEmpty())
                continue;
            const qsizetype colon = line.indexOf(':');
            if (colon <= 0) {
                send(sock, 400, "bad request", "text/plain", {}, true);
                return;
            }
            req.headers.append({line.left(colon).trimmed().toLower(), line.mid(colon + 1).trimmed()});
        }
        const QByteArray connHeader = req.header("connection").toLower();
        req.keepAlive = req.version == "HTTP/1.0" ? connHeader.contains("keep-alive") : !connHeader.contains("close");

        // 사설망 밖 연결은 본문을 읽기 전에 끊습니다 (읽지 않은 본문이 다음 요청으로 해석되지 않도록 연결도 닫음).
        const QHostAddress peer = unmapped(sock->peerAddress());
        if (m_lanOnly && !(m_lanCheck ? m_lanCheck(peer) : isLanClient(peer))) {
            send(sock, 403, "forbidden", "text/plain", {}, true);
            return;
        }
        if (req.hasHeader("transfer-encoding")) {
            send(sock, 501, "chunked body not supported", "text/plain", {}, true);
            return;
        }
        qint64 length = 0;
        if (req.hasHeader("content-length")) {
            bool ok = false;
            length = req.header("content-length").toLongLong(&ok);
            if (!ok || length < 0) {
                send(sock, 400, "bad request", "text/plain", {}, true);
                return;
            }
        }
        if (length > kMaxBody) {
            // 본문을 받지 않고 거절 — 남은 본문과 섞이지 않게 연결을 닫습니다.
            sendJson(sock, 400, {{"error", "JSON body required"}}, {}, true);
            return;
        }
        const qsizetype total = headerEnd + 4 + length;
        if (c->buf.size() < total) {
            if (!c->sentContinue && req.version == "HTTP/1.1"
                && req.header("expect").toLower() == "100-continue") {
                c->sentContinue = true;
                sock->write("HTTP/1.1 100 Continue\r\n\r\n");
            }
            return;
        }
        req.body = c->buf.mid(headerEnd + 4, length);
        c->buf.remove(0, total);
        c->sentContinue = false;

        QByteArray target = req.target;
        if (target.startsWith("http://") || target.startsWith("https://")) {
            const qsizetype slash = target.indexOf('/', target.indexOf("://") + 3);
            target = slash < 0 ? QByteArray("/") : target.mid(slash);
        }
        if (const qsizetype hash = target.indexOf('#'); hash >= 0)
            target.truncate(hash);
        const qsizetype q = target.indexOf('?');
        req.path = q < 0 ? target : target.left(q);
        req.query = parseQuery(q < 0 ? QByteArray() : target.mid(q + 1));

        handle(sock, req);
    }
}

QString RemoteServer::clientIp(QTcpSocket *sock) const { return unmapped(sock->peerAddress()).toString(); }

// ---- 응답 -------------------------------------------------------------------

void RemoteServer::send(QTcpSocket *sock, int code, const QByteArray &body, const QByteArray &contentType,
                        const Headers &headers, bool close)
{
    Conn *c = m_conns.value(sock);
    if (!c)
        return;
    QByteArray out = "HTTP/1.1 " + QByteArray::number(code) + ' ' + reasonPhrase(code) + "\r\n";
    out += "Server: JetsonPlayerRemote\r\n";
    out += "Content-Type: " + contentType + "\r\n";
    out += "Content-Length: " + QByteArray::number(body.size()) + "\r\n";
    bool hasCacheControl = false;
    for (const auto &h : headers)
        hasCacheControl |= h.first.compare("Cache-Control", Qt::CaseInsensitive) == 0;
    // 파이썬 버전은 no-store를 늘 붙인 뒤 max-age를 덧붙였지만, 두 값이 섞이면 no-store가 이기므로 여기서는 대체합니다.
    if (!hasCacheControl)
        out += "Cache-Control: no-store\r\n";
    for (const auto &h : headers)
        out += h.first + ": " + h.second + "\r\n";
    if (close)
        out += "Connection: close\r\n";
    out += "\r\n";
    out += body;
    sock->write(out);
    if (close) {
        c->closing = true;
        c->buf.clear();
        sock->disconnectFromHost();   // 보낼 데이터를 다 보낸 뒤 닫힘
    }
}

void RemoteServer::sendJson(QTcpSocket *sock, int code, const QJsonObject &obj, const Headers &headers, bool close)
{
    send(sock, code, QJsonDocument(obj).toJson(QJsonDocument::Compact), "application/json", headers, close);
}

bool RemoteServer::authorized(const Request &req) const
{
    if (!m_auth)
        return true;
    QString token;
    bool found = false;
    for (const QByteArray &part : req.header("cookie").split(';')) {
        const QByteArray p = part.trimmed();
        const qsizetype eq = p.indexOf('=');
        const QByteArray name = eq < 0 ? p : p.left(eq);
        if (name == kCookieName) {
            token = QString::fromUtf8(eq < 0 ? QByteArray() : p.mid(eq + 1));
            found = true;
            break;
        }
    }
    if (!found)
        token = QString::fromUtf8(req.header("x-jvp-token"));
    return m_auth->isValid(token);
}

static Headers cookieHeader(const QString &token)
{
    return {{"Set-Cookie", QByteArray(RemoteServer::kCookieName) + '=' + token.toUtf8()
                               + "; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"}};
}

void RemoteServer::handle(QTcpSocket *sock, const Request &req)
{
    if (req.method == "GET")
        handleGet(sock, req);
    else if (req.method == "POST")
        handlePost(sock, req);
    else
        send(sock, 501, "Unsupported method", "text/plain", {}, true);
    // Connection: close 요청이면 응답 뒤 닫습니다 (SSE는 스스로 관리).
    Conn *c = m_conns.value(sock);
    if (c && !c->sse && !c->closing && !req.keepAlive) {
        c->closing = true;
        sock->disconnectFromHost();
    }
}

void RemoteServer::handleGet(QTcpSocket *sock, const Request &req)
{
    const QByteArray &path = req.path;
    if (path == "/") {
        const QString pin = req.query.value(QStringLiteral("pin"));
        if (!pin.isEmpty() && m_auth) {
            // QR 코드 링크: PIN으로 바로 로그인하고 주소창에서 PIN을 지웁니다.
            const auto r = m_auth->login(req.ip, pin);
            if (r.ok()) {
                Headers h = cookieHeader(r.token);
                h.append(qMakePair(QByteArray("Location"), QByteArray("/")));
                send(sock, 302, QByteArray(), "text/plain", h);
                return;
            }
        }
        send(sock, 200, authorized(req) ? remoteHtml() : loginHtml(), "text/html; charset=utf-8");
        return;
    }
    if (path == "/share") {
        // 폰에서 링크 보내기 (북마클릿·공유). 페이지는 상태를 바꾸지 않고, 버튼을 누르면 /api/cmd로 POST합니다.
        send(sock, 200, shareHtml(), "text/html; charset=utf-8");
        return;
    }
    if (path == "/manifest.json") {
        send(sock, 200, manifestJson(), "application/manifest+json");
        return;
    }
    if (path == "/icon.svg") {
        send(sock, 200, iconSvg(), "image/svg+xml", {{"Cache-Control", "max-age=86400"}});
        return;
    }
    if (!path.startsWith("/api/")) {
        send(sock, 404, "not found", "text/plain");
        return;
    }
    if (!authorized(req)) {
        sendJson(sock, 401, {{"error", "login required"}});
        return;
    }
    if (path == "/api/status") {
        sendJson(sock, 200, m_backend ? m_backend->remoteStatus() : QJsonObject());
    } else if (path == "/api/events") {
        serveEvents(sock);
    } else if (path == "/api/thumb") {
        serveThumbnail(sock, req);
    } else if (path == "/api/search") {
        const QString q = leftCodePoints(req.query.value(QStringLiteral("q")), 200);
        sendJson(sock, 200, m_backend ? m_backend->remoteSearch(q)
                                      : QJsonObject{{"indexing", false}, {"results", QJsonArray()}});
    } else {
        send(sock, 404, "not found", "text/plain");
    }
}

void RemoteServer::serveThumbnail(QTcpSocket *sock, const Request &req)
{
    // i=N: 현재 영상의 N번째 썸네일, p=N: 재생목록 N번 영상의 대표 썸네일(캐시가 있을 때)
    QString path;
    if (m_backend) {
        if (req.query.contains(QStringLiteral("p")))
            path = m_backend->remotePlaylistThumbnailPath(toIndex(req.query.value(QStringLiteral("p"))));
        else
            path = m_backend->remoteThumbnailPath(toIndex(req.query.value(QStringLiteral("i"))));
    }
    QFile f(path);
    if (path.isEmpty() || !QFileInfo(path).isFile() || !f.open(QIODevice::ReadOnly)) {
        send(sock, 404, QByteArray(), "image/jpeg");
        return;
    }
    send(sock, 200, f.readAll(), "image/jpeg", {{"Cache-Control", "max-age=3600"}});
}

// ---- SSE --------------------------------------------------------------------

static QByteArray sseEvent(const QString &name, const QByteArray &data)
{
    return "event: " + name.toUtf8() + "\ndata: " + data + "\n\n";
}

void RemoteServer::serveEvents(QTcpSocket *sock)
{
    // 접속 즉시 현재 상태를 보내고, 이후 변경될 때마다 이벤트를 보냅니다.
    Conn *c = m_conns.value(sock);
    c->sse = true;
    c->buf.clear();
    QList<EventBroker::Event> events;
    c->version = m_broker ? m_broker->snapshot(&events) : 0;
    // retry: 끊겼을 때 브라우저가 2초 후 자동 재연결
    QByteArray out = "HTTP/1.1 200 OK\r\nServer: JetsonPlayerRemote\r\nContent-Type: text/event-stream\r\n"
                     "Cache-Control: no-store\r\nConnection: close\r\n\r\nretry: 2000\n\n";
    for (const auto &e : events)
        out += sseEvent(e.name, e.data);
    out += "event: ping\ndata: {}\n\n";
    c->timer->setInterval(m_heartbeatMs);
    sseWrite(sock, out);
    if (m_broker && m_broker->isClosed())
        sock->disconnectFromHost();
}

void RemoteServer::sseWrite(QTcpSocket *sock, const QByteArray &chunk)
{
    Conn *c = m_conns.value(sock);
    if (!c)
        return;
    // 응답 없는 클라이언트(화면 꺼진 폰 등)가 메모리를 붙잡지 않도록: 전송이 오래 막혀 있으면 끊습니다.
    if (sock->bytesToWrite() == 0)
        c->lastDrain.restart();
    else if (c->lastDrain.elapsed() > m_writeTimeoutMs || sock->bytesToWrite() > kMaxSseBacklog) {
        sock->abort();
        return;
    }
    sock->write(chunk);
    sock->flush();
    if (m_conns.contains(sock))
        c->timer->start();   // 하트비트는 마지막 전송으로부터 m_heartbeatMs 뒤
}

void RemoteServer::sseHeartbeat(QTcpSocket *sock) { sseWrite(sock, "event: ping\ndata: {}\n\n"); }

void RemoteServer::pushEvents()
{
    if (!m_broker)
        return;
    const auto socks = m_conns.keys();
    for (QTcpSocket *sock : socks) {
        Conn *c = m_conns.value(sock);
        if (!c || !c->sse)
            continue;
        qint64 version = c->version;
        const auto items = m_broker->newerThan(c->version, &version);
        c->version = version;
        if (items.isEmpty())
            continue;
        QByteArray out;
        for (const auto &e : items)
            out += sseEvent(e.name, e.data);
        sseWrite(sock, out);
    }
}

// ---- POST -------------------------------------------------------------------

void RemoteServer::handlePost(QTcpSocket *sock, const Request &req)
{
    QJsonObject data;
    bool valid = false;
    if (!req.body.isEmpty() && req.header("content-type").contains("application/json")) {
        QJsonParseError err;
        const QJsonDocument doc = QJsonDocument::fromJson(req.body, &err);
        if (err.error == QJsonParseError::NoError && doc.isObject()) {
            data = doc.object();
            valid = true;
        }
    }
    if (!valid) {
        sendJson(sock, 400, {{"error", "JSON body required"}});
        return;
    }

    if (req.path == "/api/login") {
        if (!m_auth) {
            sendJson(sock, 200, {{"status", "ok"}}, cookieHeader(QStringLiteral("open")));
            return;
        }
        const auto r = m_auth->login(req.ip, data.contains(QStringLiteral("pin")) ? pyStr(data.value(QStringLiteral("pin")))
                                                                                   : QString());
        if (r.status == RemoteAuth::LoginResult::Locked)
            sendJson(sock, 429, {{"error", "too many attempts, try again in 5 minutes"}});
        else if (r.ok())
            sendJson(sock, 200, {{"status", "ok"}}, cookieHeader(r.token));
        else
            sendJson(sock, 401, {{"error", "wrong PIN"}});
        return;
    }

    if (!authorized(req)) {
        sendJson(sock, 401, {{"error", "login required"}});
        return;
    }
    if (req.path == "/api/cmd") {
        QVariantMap params;
        for (const QString &key : commandFields()) {
            const QJsonValue v = data.value(key);
            if (!v.isUndefined() && !v.isNull())
                params.insert(key, v.toVariant());
        }
        if (!truthy(data.value(QStringLiteral("action")))) {
            sendJson(sock, 400, {{"error", "action required"}});
            return;
        }
        if (m_backend)
            m_backend->handleRemoteCommand(params);
        sendJson(sock, 200, {{"status", "ok"}});
    } else {
        send(sock, 404, "not found", "text/plain");
    }
}

} // namespace jvp
