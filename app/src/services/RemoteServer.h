#pragma once
// 스마트폰 웹 리모컨 HTTP/1.1 서버 (QTcpServer 위에 직접 구현 — 필요한 것이 적어 QtHttpServer 없이).
//
// 인증: 4자리 PIN으로 로그인하면 쿠키 토큰을 발급합니다 (QR 코드의 ?pin= 링크로 자동 로그인).
// 보안: 상태를 바꾸는 요청은 JSON POST만 받으며(다른 사이트의 요청은 브라우저가 사전 차단),
//       쿠키는 SameSite=Strict/HttpOnly로 발급합니다. 기본으로 사설망(LAN) 밖 연결은 거부합니다.
// 실시간: /api/events 로 상태 변경을 SSE로 푸시합니다 (폴링 불필요).
//
// 서버는 자신이 속한 스레드(보통 메인 스레드)의 이벤트 루프에서 돌고, RemoteBackend도 그 스레드에서 불립니다.
// 그래서 백엔드는 잠금 없이 플레이어 상태를 읽어도 됩니다. 페이지(index/login/share.html)는
// 파이썬 버전의 파일을 그대로 Qt 리소스(:/remote/)로 넣어 같은 API로 동작합니다.

#include <QHash>
#include <QHostAddress>
#include <QJsonObject>
#include <QList>
#include <QObject>
#include <QPointer>
#include <QVariantMap>
#include <functional>

class QTcpServer;
class QTcpSocket;

namespace jvp {

class EventBroker;
class RemoteAuth;

// 앱 컨트롤러가 구현합니다. 모든 메서드는 서버 스레드에서 불립니다.
class RemoteBackend {
public:
    virtual ~RemoteBackend() = default;
    // GET /api/status 응답 (SSE "status" 이벤트와 같은 모양)
    virtual QJsonObject remoteStatus() = 0;
    // 현재 영상의 i번째 썸네일 파일 경로. 없거나 i가 범위 밖(잘못된 값은 -1)이면 빈 문자열
    virtual QString remoteThumbnailPath(int i) = 0;
    // 재생목록 index번 영상의 대표 썸네일 경로 (캐시가 있을 때만)
    virtual QString remotePlaylistThumbnailPath(int index) = 0;
    // 대사 검색: {"indexing": bool, "results": [{index, sec, name, text, ...}]}
    virtual QJsonObject remoteSearch(const QString &query) = 0;
    // 원격 명령. params에는 COMMAND_FIELDS 중 값이 있는 것만 들어 있고 "action"은 항상 있습니다.
    virtual void handleRemoteCommand(const QVariantMap &params) = 0;
};

class RemoteServer : public QObject {
    Q_OBJECT
public:
    static constexpr qint64 kMaxBody = 64 * 1024;
    static const QStringList &commandFields();   // action, val, index, delta, percent, url, quality, sec, minutes
    static QList<quint16> defaultPorts() { return {8888, 8889, 8890, 8080}; }
    static inline const char *kCookieName = "jvp_token";

    // 포인터는 소유하지 않습니다. auth가 nullptr이면 누구나 접속 가능(로그인 없음), backend가 nullptr이면 빈 응답.
    RemoteServer(RemoteBackend *backend, RemoteAuth *auth, EventBroker *broker, QObject *parent = nullptr);
    ~RemoteServer() override;

    // ports를 차례로 시도해 처음 성공한 포트에서 듣습니다 (0.0.0.0). 0은 임의 포트.
    bool start(const QList<quint16> &ports = defaultPorts(), const QHostAddress &address = QHostAddress::AnyIPv4);
    void stop();
    bool isListening() const;
    quint16 port() const;

    QString url() const;        // http://<LAN IP>:<port>
    QString loginUrl() const;   // url()/?pin=XXXX  (QR 코드용)

    // 사설 네트워크 밖(공인 IP)에서 온 연결을 거부 (기본 켬)
    void setLanOnly(bool on) { m_lanOnly = on; }
    bool lanOnly() const { return m_lanOnly; }
    // LAN 판정 함수 교체 (테스트용). 비우면 isLanClient.
    void setLanCheck(std::function<bool(const QHostAddress &)> check) { m_lanCheck = std::move(check); }

    void setSseHeartbeatMs(int ms) { m_heartbeatMs = ms; }       // 기본 5000
    void setSseWriteTimeoutMs(int ms) { m_writeTimeoutMs = ms; } // 기본 10000
    void setIdleTimeoutMs(int ms) { m_idleTimeoutMs = ms; }      // keep-alive 연결 유휴 제한, 기본 60000

    int connectionCount() const { return m_conns.size(); }
    int sseClientCount() const;

    // 같은 네트워크(사설·링크 로컬·루프백 주소, IPv4-mapped IPv6 포함)에서 온 연결인지 — 파이썬 is_lan_client와 같은 판정
    static bool isLanClient(const QString &address);
    static bool isLanClient(const QHostAddress &address);

Q_SIGNALS:
    void started(quint16 port);

private:
    struct Request;
    struct Conn;

    void onNewConnection();
    void onReadyRead(QTcpSocket *sock);
    void processBuffer(QTcpSocket *sock);
    void handle(QTcpSocket *sock, const Request &req);
    void handleGet(QTcpSocket *sock, const Request &req);
    void handlePost(QTcpSocket *sock, const Request &req);
    void serveThumbnail(QTcpSocket *sock, const Request &req);
    void serveEvents(QTcpSocket *sock);
    void pushEvents();
    void sseWrite(QTcpSocket *sock, const QByteArray &chunk);
    void sseHeartbeat(QTcpSocket *sock);
    void dropConnection(QTcpSocket *sock);

    void send(QTcpSocket *sock, int code, const QByteArray &body, const QByteArray &contentType,
              const QList<QPair<QByteArray, QByteArray>> &headers = {}, bool close = false);
    void sendJson(QTcpSocket *sock, int code, const QJsonObject &obj,
                  const QList<QPair<QByteArray, QByteArray>> &headers = {}, bool close = false);
    bool authorized(const Request &req) const;
    QString clientIp(QTcpSocket *sock) const;

    RemoteBackend *m_backend;
    RemoteAuth *m_auth;
    QPointer<EventBroker> m_broker;
    QTcpServer *m_server;
    QHash<QTcpSocket *, Conn *> m_conns;
    std::function<bool(const QHostAddress &)> m_lanCheck;
    bool m_lanOnly = true;
    int m_heartbeatMs = 5000;
    int m_writeTimeoutMs = 10000;
    int m_idleTimeoutMs = 60000;
};

} // namespace jvp
