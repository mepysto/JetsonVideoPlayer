#pragma once
// SSE(Server-Sent Events) 방송: 메인 스레드가 상태를 게시하면 연결된 리모컨들이 즉시 받습니다.
// 어느 스레드에서 publish해도 안전합니다. 같은 이름으로 직전과 똑같은 내용을 게시하면 무시합니다
// (500ms마다 상태를 게시해도 바뀐 것만 폰으로 나가도록).

#include <QByteArray>
#include <QHash>
#include <QJsonValue>
#include <QList>
#include <QMutex>
#include <QObject>
#include <QStringList>
#include <QWaitCondition>

namespace jvp {

class EventBroker : public QObject {
    Q_OBJECT
public:
    struct Event {
        QString name;
        QByteArray data;   // 한 줄짜리 JSON (UTF-8)
        bool operator==(const Event &o) const { return name == o.name && data == o.data; }
    };

    explicit EventBroker(QObject *parent = nullptr);

    // payload가 직전과 같으면 보내지 않습니다. 새로 게시했으면 true.
    bool publish(const QString &name, const QJsonValue &payload);

    // 현재 버전과 이름별 최신 이벤트 (처음 게시된 이름 순서)
    qint64 snapshot(QList<Event> *events) const;
    // since 이후 게시된 이벤트와 새 버전 (기다리지 않음)
    QList<Event> newerThan(qint64 since, qint64 *version) const;
    // since 이후 게시된 이벤트가 생길 때까지 최대 timeoutMs 기다립니다 (작업 스레드용, 시간 초과면 빈 목록).
    QList<Event> waitNewer(qint64 since, int timeoutMs, qint64 *version);

    void close();
    bool isClosed() const;
    qint64 version() const;

    static QByteArray toJson(const QJsonValue &value);   // 공백 없는 JSON (json.dumps(separators=(",", ":")))

Q_SIGNALS:
    void published();   // 게시한 스레드에서 발생 — 다른 스레드의 수신자는 큐로 받습니다
    void closed();

private:
    QList<Event> collect(qint64 since) const;   // m_mutex 잠긴 상태에서 호출

    mutable QMutex m_mutex;
    QWaitCondition m_cond;
    qint64 m_version = 0;
    QStringList m_order;                                  // 이름이 처음 게시된 순서 (파이썬 dict 순서와 같게)
    QHash<QString, QPair<qint64, QByteArray>> m_latest;  // 이름 → (버전, JSON)
    bool m_closed = false;
};

} // namespace jvp
