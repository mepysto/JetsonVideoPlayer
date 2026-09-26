#include "RemoteAuth.h"

#include "Paths.h"

#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLoggingCategory>
#include <QRandomGenerator>
#include <QSaveFile>

Q_LOGGING_CATEGORY(lcAuth, "jvp.remote.auth")

namespace jvp {

namespace {
double monotonicSeconds()
{
    static QElapsedTimer timer = [] { QElapsedTimer t; t.start(); return t; }();
    return timer.nsecsElapsed() / 1e9;
}

// hmac.compare_digest처럼 길이만 새고 내용은 새지 않는 비교
bool constantTimeEquals(const QByteArray &a, const QByteArray &b)
{
    if (a.size() != b.size())
        return false;
    unsigned char diff = 0;
    for (qsizetype i = 0; i < a.size(); ++i)
        diff |= static_cast<unsigned char>(a[i] ^ b[i]);
    return diff == 0;
}
} // namespace

RemoteAuth::RemoteAuth(const QString &pin, const QString &tokenFile, Clock now)
    : m_pin(pin), m_tokenFile(tokenFile.isEmpty() ? defaultTokenFile() : tokenFile),
      m_now(now ? std::move(now) : Clock(monotonicSeconds))
{
    load();
}

QString RemoteAuth::defaultTokenFile() { return paths::configDir() + QStringLiteral("/remote_tokens.json"); }

QString RemoteAuth::generatePin()
{
    return QStringLiteral("%1").arg(QRandomGenerator::system()->bounded(10000), 4, 10, QLatin1Char('0'));
}

QString RemoteAuth::hashToken(const QString &token)
{
    return QString::fromLatin1(QCryptographicHash::hash(token.toUtf8(), QCryptographicHash::Sha256).toHex());
}

QString RemoteAuth::pin() const
{
    QMutexLocker lock(&m_mutex);
    return m_pin;
}

void RemoteAuth::load()
{
    QFile f(m_tokenFile);
    if (!f.open(QIODevice::ReadOnly))
        return;
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll());
    if (!doc.isArray())
        return;
    QStringList hashes;
    for (const QJsonValue &v : doc.array())
        if (v.isString())
            hashes.append(v.toString());
    m_tokenHashes = hashes.mid(qMax<qsizetype>(0, hashes.size() - kMaxTokens));
}

void RemoteAuth::save()
{
    // 임시 파일에 쓴 뒤 교체 — 저장 중 전원이 꺼져도 기존 파일이 깨지지 않게 (파이썬 atomic_write_json과 같은 형식)
    QDir().mkpath(QFileInfo(m_tokenFile).absolutePath());
    QSaveFile f(m_tokenFile);
    if (!f.open(QIODevice::WriteOnly)) {
        qCWarning(lcAuth) << "⚠️ 리모컨 토큰 저장 실패:" << f.errorString();
        return;
    }
    f.write(QJsonDocument(QJsonArray::fromStringList(m_tokenHashes)).toJson(QJsonDocument::Indented));
    if (!f.commit())
        qCWarning(lcAuth) << "⚠️ 리모컨 토큰 저장 실패:" << f.errorString();
}

bool RemoteAuth::isLocked(const QString &ip)
{
    QMutexLocker lock(&m_mutex);
    const auto it = m_failures.constFind(ip);
    if (it == m_failures.constEnd())
        return false;
    const double now = m_now();
    const auto [count, first] = *it;
    if (count >= kMaxFailures && now - first < kLockSeconds)
        return true;
    if (count && now - first >= kLockSeconds)
        m_failures.remove(ip);
    return false;
}

RemoteAuth::LoginResult RemoteAuth::login(const QString &ip, const QString &pin)
{
    if (isLocked(ip))
        return {LoginResult::Locked, {}};
    QMutexLocker lock(&m_mutex);
    if (!constantTimeEquals(pin.trimmed().toUtf8(), m_pin.toUtf8())) {
        auto it = m_failures.find(ip);
        if (it == m_failures.end())
            m_failures.insert(ip, {1, m_now()});
        else
            it->first += 1;
        return {LoginResult::WrongPin, {}};
    }
    // secrets.token_urlsafe(24)와 같은 모양: 24바이트 난수의 base64url (패딩 없음)
    QByteArray raw(24, Qt::Uninitialized);
    QRandomGenerator::system()->fillRange(reinterpret_cast<quint32 *>(raw.data()), raw.size() / 4);
    const QString token = QString::fromLatin1(
        raw.toBase64(QByteArray::Base64UrlEncoding | QByteArray::OmitTrailingEquals));
    m_failures.remove(ip);
    m_tokenHashes.append(hashToken(token));
    while (m_tokenHashes.size() > kMaxTokens)
        m_tokenHashes.removeFirst();
    save();
    return {LoginResult::Ok, token};
}

bool RemoteAuth::isValid(const QString &token) const
{
    if (token.isEmpty())
        return false;
    const QByteArray h = hashToken(token).toLatin1();
    QMutexLocker lock(&m_mutex);
    bool found = false;
    for (const QString &known : m_tokenHashes)
        found |= constantTimeEquals(h, known.toLatin1());   // 일치해도 끝까지 비교
    return found;
}

void RemoteAuth::reset(const QString &newPin)
{
    QMutexLocker lock(&m_mutex);
    m_pin = newPin;
    m_tokenHashes.clear();
    m_failures.clear();
    save();
}

} // namespace jvp
