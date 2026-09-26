#pragma once
// 웹 리모컨 접속 인증: 4자리 PIN으로 로그인하면 기기별 토큰(쿠키)을 발급합니다.
// - 토큰은 SHA-256 해시로만 저장합니다 (paths::configDir()/remote_tokens.json, 파이썬 버전과 같은 파일·형식).
// - 같은 IP에서 PIN을 연속으로 틀리면 잠시 로그인을 막습니다.
// 여러 스레드에서 불러도 안전합니다.

#include <QMutex>
#include <QHash>
#include <QString>
#include <QStringList>
#include <functional>

namespace jvp {

class RemoteAuth {
public:
    static constexpr int kMaxTokens = 20;
    static constexpr int kMaxFailures = 8;
    static constexpr double kLockSeconds = 300.0;

    using Clock = std::function<double()>;   // 단조 증가 시각(초) — 테스트에서 바꿔 끼웁니다

    struct LoginResult {
        enum Status { Ok, WrongPin, Locked } status = WrongPin;
        QString token;   // Ok일 때만
        bool ok() const { return status == Ok; }
    };

    // tokenFile이 비어 있으면 defaultTokenFile()
    explicit RemoteAuth(const QString &pin, const QString &tokenFile = QString(), Clock now = Clock());

    LoginResult login(const QString &ip, const QString &pin);
    bool isValid(const QString &token) const;
    bool isLocked(const QString &ip);
    // PIN을 바꾸고 기존에 로그인한 모든 기기를 로그아웃시킵니다.
    void reset(const QString &newPin);

    QString pin() const;
    QString tokenFile() const { return m_tokenFile; }

    static QString generatePin();          // "0000"~"9999"
    static QString defaultTokenFile();     // configDir()/remote_tokens.json
    static QString hashToken(const QString &token);

private:
    void load();
    void save();   // m_mutex 잠긴 상태에서 호출

    mutable QMutex m_mutex;
    QString m_pin;
    QString m_tokenFile;
    Clock m_now;
    QStringList m_tokenHashes;
    QHash<QString, QPair<int, double>> m_failures;   // ip → (실패 횟수, 첫 실패 시각)
};

} // namespace jvp
