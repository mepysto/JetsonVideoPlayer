#pragma once
// 테스트용 초소형 HTTP/1.1 서버 (QTcpServer, 127.0.0.1). 요청을 기록하고 핸들러가 준 응답을 돌려줍니다.
// 네트워크에 나가지 않고 QNetworkAccessManager 코드(OpenSubtitles, Claude API)를 검증하는 데 씁니다.

#include <QByteArray>
#include <QHash>
#include <QList>
#include <QTcpServer>
#include <QTcpSocket>

#include <functional>

struct FakeRequest {
    QByteArray method;
    QByteArray target;                     // 경로 + 쿼리 (예: /api/v1/subtitles?languages=en%2Cko)
    QHash<QByteArray, QByteArray> headers; // 키는 소문자
    QByteArray body;
};

struct FakeResponse {
    int status = 200;
    QByteArray body;
    QByteArray contentType = "application/json";
    QList<QPair<QByteArray, QByteArray>> extraHeaders;
};

class FakeHttpServer : public QTcpServer {
public:
    using Handler = std::function<FakeResponse(const FakeRequest &)>;

    explicit FakeHttpServer(Handler handler) : m_handler(std::move(handler))
    {
        listen(QHostAddress::LocalHost, 0);
        connect(this, &QTcpServer::newConnection, this, [this] {
            while (QTcpSocket *s = nextPendingConnection()) {
                connect(s, &QTcpSocket::readyRead, s, [this, s] { onReadyRead(s); });
                connect(s, &QTcpSocket::disconnected, s, &QObject::deleteLater);
            }
        });
    }

    QByteArray baseUrl() const { return "http://127.0.0.1:" + QByteArray::number(serverPort()); }
    QList<FakeRequest> requests;

private:
    void onReadyRead(QTcpSocket *s)
    {
        QByteArray &buf = m_buffers[s];
        buf += s->readAll();
        const int headerEnd = buf.indexOf("\r\n\r\n");
        if (headerEnd < 0)
            return;
        FakeRequest req;
        const QList<QByteArray> lines = buf.left(headerEnd).split('\n');
        const QList<QByteArray> first = lines.value(0).trimmed().split(' ');
        req.method = first.value(0);
        req.target = first.value(1);
        for (int i = 1; i < lines.size(); ++i) {
            const int colon = lines[i].indexOf(':');
            if (colon > 0)
                req.headers.insert(lines[i].left(colon).trimmed().toLower(), lines[i].mid(colon + 1).trimmed());
        }
        const int length = req.headers.value("content-length", "0").toInt();
        if (buf.size() < headerEnd + 4 + length)
            return;   // 본문이 아직 다 오지 않음
        req.body = buf.mid(headerEnd + 4, length);
        m_buffers.remove(s);
        requests.append(req);
        const FakeResponse resp = m_handler(req);
        QByteArray out = "HTTP/1.1 " + QByteArray::number(resp.status) + " X\r\nContent-Type: " + resp.contentType
                         + "\r\nContent-Length: " + QByteArray::number(resp.body.size()) + "\r\nConnection: close\r\n";
        for (const auto &h : resp.extraHeaders)
            out += h.first + ": " + h.second + "\r\n";
        out += "\r\n" + resp.body;
        s->write(out);
        s->flush();
        s->disconnectFromHost();
    }

    Handler m_handler;
    QHash<QTcpSocket *, QByteArray> m_buffers;
};
