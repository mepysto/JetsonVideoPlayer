// GIO 헤더는 Qt의 signals 매크로보다 먼저 포함해야 합니다 (GLib 구조체에 signals라는 이름이 있음).
#include <gio/gio.h>

#include "NetworkMount.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonValue>
#include <QLoggingCategory>
#include <QPointer>
#include <QRegularExpression>
#include <QSet>
#include <QUrl>

#include <unistd.h>

Q_LOGGING_CATEGORY(lcNetwork, "jvp.network")

namespace jvp {

// 비동기 작업 하나. NetworkMount가 먼저 사라져도 GIO 콜백이 안전하게 정리되도록 따로 둡니다.
struct NetworkMount::Request {
    QPointer<NetworkMount> owner;
    QString uri;
    GFile *file = nullptr;
    GMountOperation *op = nullptr;

    static void askPassword(GMountOperation *op, const char *message, const char *defaultUser,
                            const char *defaultDomain, GAskPasswordFlags flags, gpointer data)
    {
        auto *r = static_cast<Request *>(data);
        if (!r->owner) {
            g_mount_operation_reply(op, G_MOUNT_OPERATION_ABORTED);
            return;
        }
        r->owner->onAskPassword(op, QString::fromUtf8(message), QString::fromUtf8(defaultUser),
                                QString::fromUtf8(defaultDomain), static_cast<int>(flags));
    }

    static void askQuestion(GMountOperation *op, const char *message, const char **choices, gpointer data)
    {
        auto *r = static_cast<Request *>(data);
        if (!r->owner) {
            g_mount_operation_reply(op, G_MOUNT_OPERATION_ABORTED);
            return;
        }
        QStringList list;
        for (const char **c = choices; c && *c; ++c)
            list.append(QString::fromUtf8(*c));
        r->owner->onAskQuestion(op, QString::fromUtf8(message), list);
    }

    static void mounted(GObject *source, GAsyncResult *result, gpointer data)
    {
        auto *r = static_cast<Request *>(data);
        GError *err = nullptr;
        QString error, path;
        if (!g_file_mount_enclosing_volume_finish(G_FILE(source), result, &err)) {
            // 이미 마운트되어 있으면 성공과 같습니다.
            if (!g_error_matches(err, G_IO_ERROR, G_IO_ERROR_ALREADY_MOUNTED)) {
                error = QString::fromUtf8(err->message);
                qCWarning(lcNetwork).noquote() << "⚠️ 네트워크 폴더 연결 실패 (" + r->uri + "):" << error;
            }
            g_error_free(err);
        }
        if (error.isEmpty()) {
            char *local = g_file_get_path(r->file);
            path = local ? QString::fromUtf8(local) : QString();
            g_free(local);
            if (path.isEmpty() || !QFileInfo::exists(path)) {
                path.clear();
                error = QStringLiteral("로컬 경로로 열 수 없습니다 (gvfs-fuse 패키지가 필요합니다)");
            }
        }
        g_signal_handlers_disconnect_by_data(r->op, r);
        if (NetworkMount *owner = r->owner) {
            if (owner->m_asking == r->op) {
                g_object_unref(owner->m_asking);
                owner->m_asking = nullptr;
            }
            owner->onFinished(r->uri, path, error);
        }
        g_object_unref(r->op);
        g_object_unref(r->file);
        delete r;
    }
};

NetworkMount::NetworkMount(QObject *parent) : QObject(parent) {}

NetworkMount::~NetworkMount()
{
    if (m_asking) {
        g_mount_operation_reply(m_asking, G_MOUNT_OPERATION_ABORTED);
        g_object_unref(m_asking);
        m_asking = nullptr;
    }
}

void NetworkMount::mount(const QString &uri)
{
    auto *r = new Request;
    r->owner = this;
    r->uri = uri;
    r->file = g_file_new_for_uri(uri.toUtf8().constData());
    r->op = g_mount_operation_new();
    g_signal_connect(r->op, "ask-password", G_CALLBACK(Request::askPassword), r);
    g_signal_connect(r->op, "ask-question", G_CALLBACK(Request::askQuestion), r);
    ++m_pending;
    qCInfo(lcNetwork).noquote() << "🌐 연결 중:" << uri;
    g_file_mount_enclosing_volume(r->file, G_MOUNT_MOUNT_NONE, r->op, nullptr, &Request::mounted, r);
}

bool NetworkMount::mountForPath(const QString &localPath, const QVariantList &locations)
{
    const QString uri = uriForPath(locations, localPath);
    if (uri.isEmpty())
        return false;
    // 파일이 아니라 저장된 공유(루트) 주소를 마운트합니다 — enclosing volume이면 충분.
    mount(uri);
    return true;
}

void NetworkMount::onAskPassword(GMountOperation *op, const QString &message, const QString &user,
                                 const QString &domain, int flags)
{
    if (m_asking && m_asking != op) {
        // 이전 질문에 답이 없는 채로 새 질문이 오면 이전 것은 취소 (답은 한 번에 하나만 받음)
        g_mount_operation_reply(m_asking, G_MOUNT_OPERATION_ABORTED);
        g_object_unref(m_asking);
        m_asking = nullptr;
    }
    if (!m_asking)
        m_asking = G_MOUNT_OPERATION(g_object_ref(op));
    Q_EMIT passwordRequested(message, user, domain, flags);
}

void NetworkMount::onAskQuestion(GMountOperation *op, const QString &message, const QStringList &choices)
{
    if (m_asking && m_asking != op) {
        g_mount_operation_reply(m_asking, G_MOUNT_OPERATION_ABORTED);
        g_object_unref(m_asking);
        m_asking = nullptr;
    }
    if (!m_asking)
        m_asking = G_MOUNT_OPERATION(g_object_ref(op));
    Q_EMIT questionAsked(message, choices);
}

void NetworkMount::reply(const QString &user, const QString &password, const QString &domain, bool remember)
{
    if (!m_asking)
        return;
    GMountOperation *op = m_asking;
    m_asking = nullptr;
    if (user.isEmpty() && password.isEmpty()) {
        g_mount_operation_set_anonymous(op, TRUE);   // 익명 접속을 지원하는 공유라면
    } else {
        g_mount_operation_set_username(op, user.toUtf8().constData());
        g_mount_operation_set_password(op, password.toUtf8().constData());
    }
    if (!domain.isEmpty())
        g_mount_operation_set_domain(op, domain.toUtf8().constData());
    g_mount_operation_set_password_save(op, remember ? G_PASSWORD_SAVE_PERMANENTLY : G_PASSWORD_SAVE_NEVER);
    g_mount_operation_reply(op, G_MOUNT_OPERATION_HANDLED);
    g_object_unref(op);
}

void NetworkMount::answer(int choice)
{
    if (!m_asking)
        return;
    GMountOperation *op = m_asking;
    m_asking = nullptr;
    g_mount_operation_set_choice(op, choice);
    g_mount_operation_reply(op, G_MOUNT_OPERATION_HANDLED);
    g_object_unref(op);
}

void NetworkMount::cancel()
{
    if (!m_asking)
        return;
    GMountOperation *op = m_asking;
    m_asking = nullptr;
    g_mount_operation_reply(op, G_MOUNT_OPERATION_ABORTED);
    g_object_unref(op);
}

void NetworkMount::onFinished(const QString &uri, const QString &path, const QString &error)
{
    --m_pending;
    if (error.isEmpty())
        qCInfo(lcNetwork).noquote() << "🌐 [네트워크 폴더]" << uri << "→" << path;
    Q_EMIT finished(uri, path, error);
}

// ---- 순수 함수 -------------------------------------------------------------------

namespace {
QString absPath(const QString &path) { return QDir::cleanPath(QFileInfo(path).absoluteFilePath()); }

QString scheme(const QString &text)
{
    static const QRegularExpression re(QStringLiteral("^([A-Za-z][A-Za-z0-9+.-]*):"));
    const auto m = re.match(text.trimmed());
    return m.hasMatch() ? m.captured(1).toLower() : QString();
}

QVariantList asList(const QVariant &value)
{
    if (value.typeId() == QMetaType::QJsonArray)
        return value.toJsonArray().toVariantList();
    if (value.typeId() == QMetaType::QJsonValue && value.toJsonValue().isArray())
        return value.toJsonValue().toArray().toVariantList();
    if (value.typeId() == QMetaType::QVariantList || value.typeId() == QMetaType::QStringList)
        return value.toList();
    return {};
}

bool isString(const QVariant &v) { return v.typeId() == QMetaType::QString; }
} // namespace

QStringList NetworkMount::networkSchemes()
{
    return {QStringLiteral("smb"), QStringLiteral("nfs"), QStringLiteral("sftp"), QStringLiteral("ftp"),
            QStringLiteral("ftps"), QStringLiteral("dav"), QStringLiteral("davs"), QStringLiteral("afp")};
}

QString NetworkMount::gvfsRoot()
{
    QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    if (runtime.isEmpty())
        runtime = QStringLiteral("/run/user/%1").arg(::getuid());
    return runtime + QStringLiteral("/gvfs");
}

bool NetworkMount::isGvfsPath(const QString &path)
{
    return !path.isEmpty() && absPath(path).startsWith(gvfsRoot() + QLatin1Char('/'));
}

bool NetworkMount::isNetworkUri(const QString &text) { return networkSchemes().contains(scheme(text)); }

QString NetworkMount::normalizeUri(const QString &input)
{
    QString text = input.trimmed();
    if (text.startsWith(QLatin1String("\\\\"))) {
        qsizetype i = 0;
        while (i < text.size() && text.at(i) == QLatin1Char('\\'))
            ++i;
        text = QStringLiteral("smb://") + text.mid(i).replace(QLatin1Char('\\'), QLatin1Char('/'));
    }
    const qsizetype sep = text.indexOf(QLatin1String("://"));
    if (sep >= 0) {
        QString rest = text.mid(sep + 3);
        while (rest.endsWith(QLatin1Char('/')))
            rest.chop(1);
        text = text.left(sep).toLower() + QStringLiteral("://") + rest;
    }
    return text;
}

QString NetworkMount::displayName(const QString &uri)
{
    const QUrl url(uri);
    QString path = url.path(QUrl::FullyDecoded);
    while (path.startsWith(QLatin1Char('/')))
        path.remove(0, 1);
    while (path.endsWith(QLatin1Char('/')))
        path.chop(1);
    QString name = url.host() + QLatin1Char('/') + path;
    while (name.endsWith(QLatin1Char('/')))
        name.chop(1);
    return name.isEmpty() ? uri : name;
}

QVariantList NetworkMount::cleanLocations(const QVariant &value)
{
    QVariantList result;
    QSet<QString> seen;
    for (const QVariant &item : asList(value)) {
        if (item.typeId() != QMetaType::QVariantMap)
            continue;
        const QVariantMap m = item.toMap();
        const QVariant uri = m.value(QStringLiteral("uri")), path = m.value(QStringLiteral("path"));
        if (!isString(uri) || !isString(path) || !isNetworkUri(uri.toString()) || seen.contains(uri.toString()))
            continue;
        seen.insert(uri.toString());
        const QVariant name = m.value(QStringLiteral("name"));
        result.append(QVariantMap{{QStringLiteral("uri"), uri.toString()},
                                  {QStringLiteral("path"), path.toString()},
                                  {QStringLiteral("name"), isString(name) ? name.toString() : displayName(uri.toString())}});
        if (result.size() >= kMaxLocations)
            break;
    }
    return result;
}

QVariantList NetworkMount::rememberLocation(const QVariant &locations, const QString &uri, const QString &path)
{
    QVariantList result{QVariantMap{{QStringLiteral("uri"), uri},
                                    {QStringLiteral("path"), absPath(path)},
                                    {QStringLiteral("name"), displayName(uri)}}};
    for (const QVariant &loc : cleanLocations(locations)) {
        if (loc.toMap().value(QStringLiteral("uri")).toString() == uri)
            continue;
        if (result.size() >= kMaxLocations)
            break;
        result.append(loc);
    }
    return result;
}

QString NetworkMount::uriForPath(const QVariant &locations, const QString &localPath)
{
    const QString path = absPath(localPath);
    QVariantMap best;
    for (const QVariant &v : cleanLocations(locations)) {
        const QVariantMap loc = v.toMap();
        QString root = loc.value(QStringLiteral("path")).toString();
        QString rootSlash = root;
        while (rootSlash.endsWith(QLatin1Char('/')))
            rootSlash.chop(1);
        if (path == root || path.startsWith(rootSlash + QLatin1Char('/'))) {
            if (best.isEmpty() || root.size() > best.value(QStringLiteral("path")).toString().size())
                best = loc;
        }
    }
    if (best.isEmpty())
        return {};
    const QString bestUri = best.value(QStringLiteral("uri")).toString();
    const QString rel = QDir(best.value(QStringLiteral("path")).toString()).relativeFilePath(path);
    if (rel.isEmpty() || rel == QLatin1String("."))
        return bestUri;
    QStringList parts;
    for (const QString &p : rel.split(QLatin1Char('/')))
        parts.append(QString::fromLatin1(QUrl::toPercentEncoding(p)));
    QString base = bestUri;
    while (base.endsWith(QLatin1Char('/')))
        base.chop(1);
    return base + QLatin1Char('/') + parts.join(QLatin1Char('/'));
}

} // namespace jvp
