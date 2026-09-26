#pragma once
// 네트워크 폴더(SMB/NFS/SFTP 등): GVfs로 마운트하고 gvfs-fuse 로컬 경로로 재생합니다.
//
// 마운트한 공유는 /run/user/<uid>/gvfs/smb-share:server=…,share=…/ 아래 일반 파일처럼 보이므로
// 썸네일·AI 자막·이어보기 등 기존 기능을 그대로 쓸 수 있습니다. 주소와 로컬 경로의 대응은
// settings["network_locations"]에 저장해 두고, 재부팅 뒤 이어보기를 누르면 mountForPath로 다시 마운트합니다.
//
// GIO 비동기 콜백은 GLib 메인 컨텍스트에서 돌고, 리눅스의 Qt 메인 스레드가 바로 그 컨텍스트를 돌리므로
// 신호는 모두 메인 스레드에서 나옵니다. (GIO 헤더는 Qt의 signals 매크로와 부딪혀 .cpp에서만 포함합니다.)

#include <QObject>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

typedef struct _GMountOperation GMountOperation;

namespace jvp {

class NetworkMount : public QObject {
    Q_OBJECT
public:
    // GAskPasswordFlags와 같은 값
    enum AskFlag {
        NeedPassword = 1 << 0,
        NeedUsername = 1 << 1,
        NeedDomain = 1 << 2,
        SavingSupported = 1 << 3,
        AnonymousSupported = 1 << 4,
    };
    Q_ENUM(AskFlag)
    static constexpr int kMaxLocations = 10;

    explicit NetworkMount(QObject *parent = nullptr);
    ~NetworkMount() override;

    // uri를 마운트하고 finished(uri, localPath, error)를 보냅니다 (성공이면 error가 비어 있음).
    // 이미 마운트되어 있어도 성공으로 봅니다. 인증이 필요하면 passwordRequested가 나오고,
    // reply()나 cancel()로 답해야 진행됩니다.
    void mount(const QString &uri);
    // 연결이 끊긴 gvfs 경로(재부팅 후 이어보기 등)의 공유를 다시 마운트합니다.
    // 저장된 위치에서 주소를 찾지 못하면 false (마운트 시작 안 함). finished의 uri는 공유 주소입니다.
    bool mountForPath(const QString &localPath, const QVariantList &locations);
    bool isBusy() const { return m_pending > 0; }

    // ---- 순수 함수 (network.py) ----
    static QStringList networkSchemes();                  // smb, nfs, sftp, ftp, ftps, dav, davs, afp
    static QString gvfsRoot();                            // $XDG_RUNTIME_DIR/gvfs
    static bool isGvfsPath(const QString &path);
    static bool isNetworkUri(const QString &text);
    static QString normalizeUri(const QString &text);    // \\서버\공유 → smb://서버/공유, 끝의 / 제거
    static QString displayName(const QString &uri);      // 서버/공유/폴더
    // [{uri, path, name}] 검증 (최대 kMaxLocations개)
    static QVariantList cleanLocations(const QVariant &value);
    // 최근 사용한 위치를 맨 앞으로 (같은 주소는 한 번만)
    static QVariantList rememberLocation(const QVariant &locations, const QString &uri, const QString &path);
    // 로컬 gvfs 경로를 저장된 위치의 네트워크 주소로 되돌림 (재마운트용). 모르면 빈 문자열.
    static QString uriForPath(const QVariant &locations, const QString &path);

public Q_SLOTS:
    // passwordRequested에 대한 답. remember면 키링에 영구 저장 (지원할 때)
    void reply(const QString &user, const QString &password, const QString &domain, bool remember);
    // 질문(askQuestion)에 대한 답: choices 중 고른 번호
    void answer(int choice);
    // 인증·질문을 취소 → 마운트는 오류로 끝남
    void cancel();

Q_SIGNALS:
    void passwordRequested(const QString &message, const QString &defaultUser, const QString &defaultDomain, int flags);
    void questionAsked(const QString &message, const QStringList &choices);   // 예: SFTP 호스트 키 확인
    void finished(const QString &uri, const QString &localPath, const QString &error);

private:
    struct Request;
    friend struct Request;
    void onAskPassword(GMountOperation *op, const QString &message, const QString &user, const QString &domain,
                       int flags);
    void onAskQuestion(GMountOperation *op, const QString &message, const QStringList &choices);
    void onFinished(const QString &uri, const QString &path, const QString &error);

    GMountOperation *m_asking = nullptr;   // 답을 기다리는 작업 (참조 보유)
    int m_pending = 0;
};

} // namespace jvp
