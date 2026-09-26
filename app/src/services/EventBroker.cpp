#include "EventBroker.h"

#include <QDeadlineTimer>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

namespace jvp {

EventBroker::EventBroker(QObject *parent) : QObject(parent) {}

QByteArray EventBroker::toJson(const QJsonValue &value)
{
    if (value.isObject())
        return QJsonDocument(value.toObject()).toJson(QJsonDocument::Compact);
    if (value.isArray())
        return QJsonDocument(value.toArray()).toJson(QJsonDocument::Compact);
    // QJsonDocument는 객체·배열만 받으므로 스칼라는 배열에 넣어 직렬화한 뒤 괄호를 벗깁니다.
    QByteArray wrapped = QJsonDocument(QJsonArray{value}).toJson(QJsonDocument::Compact);
    return wrapped.mid(1, wrapped.size() - 2);
}

bool EventBroker::publish(const QString &name, const QJsonValue &payload)
{
    const QByteArray data = toJson(payload);
    {
        QMutexLocker lock(&m_mutex);
        auto it = m_latest.constFind(name);
        if (it != m_latest.constEnd() && it->second == data)
            return false;
        ++m_version;
        if (it == m_latest.constEnd())
            m_order.append(name);
        m_latest.insert(name, {m_version, data});
        m_cond.wakeAll();
    }
    Q_EMIT published();
    return true;
}

QList<EventBroker::Event> EventBroker::collect(qint64 since) const
{
    QList<Event> items;
    for (const QString &name : m_order) {
        const auto &entry = m_latest[name];
        if (entry.first > since)
            items.append({name, entry.second});
    }
    return items;
}

qint64 EventBroker::snapshot(QList<Event> *events) const
{
    QMutexLocker lock(&m_mutex);
    if (events)
        *events = collect(0);
    return m_version;
}

QList<EventBroker::Event> EventBroker::newerThan(qint64 since, qint64 *version) const
{
    QMutexLocker lock(&m_mutex);
    if (version)
        *version = m_version;
    return collect(since);
}

QList<EventBroker::Event> EventBroker::waitNewer(qint64 since, int timeoutMs, qint64 *version)
{
    QMutexLocker lock(&m_mutex);
    QDeadlineTimer deadline(timeoutMs);
    while (m_version <= since && !m_closed) {
        if (!m_cond.wait(&m_mutex, deadline))
            break;
    }
    if (version)
        *version = m_version;
    return collect(since);
}

void EventBroker::close()
{
    {
        QMutexLocker lock(&m_mutex);
        if (m_closed)
            return;
        m_closed = true;
        m_cond.wakeAll();
    }
    Q_EMIT closed();
}

bool EventBroker::isClosed() const
{
    QMutexLocker lock(&m_mutex);
    return m_closed;
}

qint64 EventBroker::version() const
{
    QMutexLocker lock(&m_mutex);
    return m_version;
}

} // namespace jvp
