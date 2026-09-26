#pragma once
// 온라인 자막 찾기 (OpenSubtitles.com): 검색 → 골라서 받기 → 바로 켜기 (파이썬 ui/online_subs.py)

#include <QObject>
#include <QtQml/qqmlregistration.h>
#include <QVariantList>
#include <QVariantMap>

namespace jvp {

class AppController;

class OnlineSubsController : public QObject {
    Q_OBJECT
    QML_ANONYMOUS
    Q_PROPERTY(bool hasKey READ hasKey NOTIFY changed)
    Q_PROPERTY(QVariantList results READ results NOTIFY changed)
    Q_PROPERTY(QString status READ status NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
public:
    explicit OnlineSubsController(AppController *app);

    bool hasKey() const;
    QVariantList results() const { return m_results; }
    QString status() const { return m_status; }
    bool busy() const { return m_busy; }

    Q_INVOKABLE QString defaultQuery() const;
    Q_INVOKABLE void search(const QString &query, const QString &languages);
    Q_INVOKABLE void download(int index);
    Q_INVOKABLE QVariantMap credentials() const;
    Q_INVOKABLE void saveCredentials(const QString &apiKey, const QString &username, const QString &password);

signals:
    void changed();
    void downloaded();   // 받아서 켰음 → 대화상자 닫기

private:
    void saveDownloaded(const QString &video, const QVariantMap &result, const QByteArray &content);

    AppController *m_app;
    QString m_video;          // 검색한 영상 (검색 도중 영상이 바뀌어도 맞는 영상에 저장)
    QVariantList m_results;
    QString m_status;
    bool m_busy = false;
};

} // namespace jvp
