#pragma once
// 웹 리모컨 접속 안내 (QML: App.remote.url / loginUrl / pin / regeneratePin())

#include <QObject>
#include <QtQml/qqmlregistration.h>
#include <QPointer>

namespace jvp {

class RemoteAuth;
class RemoteServer;

class RemoteInfo : public QObject {
    Q_OBJECT
    QML_ANONYMOUS
    Q_PROPERTY(QString url READ url NOTIFY changed)
    Q_PROPERTY(QString loginUrl READ loginUrl NOTIFY changed)
    Q_PROPERTY(QString pin READ pin NOTIFY changed)
    Q_PROPERTY(bool running READ running NOTIFY changed)
public:
    explicit RemoteInfo(QObject *parent = nullptr) : QObject(parent) {}

    void attach(RemoteServer *server, RemoteAuth *auth);
    QString url() const;
    QString loginUrl() const;
    QString pin() const;
    bool running() const;

    // 새 PIN을 만들고 기존에 연결된 기기를 모두 로그아웃시킵니다.
    Q_INVOKABLE void regeneratePin();

signals:
    void changed();

private:
    QPointer<RemoteServer> m_server;
    RemoteAuth *m_auth = nullptr;
};

} // namespace jvp
