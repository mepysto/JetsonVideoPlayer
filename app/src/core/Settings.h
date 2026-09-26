#pragma once
// 사용자 설정(볼륨, 자막 크기, 반복 모드, 창/사이드바 크기 등)의 영구 저장.
// 파이썬 버전과 같은 settings.json을 같은 키·같은 검증 규칙으로 읽고 씁니다 — 두 버전을 오가도 설정이 유지되도록.

#include <QMutex>
#include <QObject>
#include <QStringList>
#include <QVariant>
#include <QVariantMap>

namespace jvp {

class Settings : public QObject {
    Q_OBJECT
public:
    // path를 비우면 paths::configDir()/settings.json
    explicit Settings(const QString &path = QString(), QObject *parent = nullptr);

    static Settings *instance();                  // 프로세스 전역 설정 (기본 경로)

    static QStringList keys();                    // DEFAULTS 순서
    static QVariant defaultValue(const QString &key);
    static bool isKnownKey(const QString &key);
    // 저장 파일이 손상되었거나 이전 버전 값이어도 안전한 값만 받아들입니다 (알 수 없는 키면 무효 QVariant)
    static QVariant validate(const QString &key, const QVariant &value);

    QString path() const { return m_path; }

    Q_INVOKABLE QVariant value(const QString &key) const;
    // 검증된 값을 저장하고 돌려줍니다. 알 수 없는 키는 경고 후 무시 (무효 QVariant)
    Q_INVOKABLE QVariant setValue(const QString &key, const QVariant &value);
    Q_INVOKABLE void update(const QVariantMap &values);
    // 바뀐 값이 있을 때만 씁니다. 실제로 썼으면 true
    Q_INVOKABLE bool save();

    int intValue(const QString &key) const { return value(key).toInt(); }
    double doubleValue(const QString &key) const { return value(key).toDouble(); }
    bool boolValue(const QString &key) const { return value(key).toBool(); }
    QString stringValue(const QString &key) const { return value(key).toString(); }
    QVariantList listValue(const QString &key) const { return value(key).toList(); }

signals:
    void valueChanged(const QString &key);

private:
    void load();

    QString m_path;
    mutable QMutex m_mutex;
    QVariantMap m_values;
    QVariantMap m_saved;
};

} // namespace jvp
