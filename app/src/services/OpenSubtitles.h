#pragma once
// OpenSubtitles.com REST API (v1)로 자막 검색·다운로드 (파이썬 jetson_player/subtitles/opensubtitles.py 이식).
// API 키는 https://www.opensubtitles.com/consumers 에서 무료로 발급받습니다. 계정을 넣으면 하루 다운로드 한도가 늘어납니다.
// 자격 정보: ~/.config/jetson_video_player/opensubtitles.json (권한 600) 또는 JVP_OPENSUBTITLES_KEY 환경 변수.
// 모든 요청은 QNetworkAccessManager로 비동기 처리하고, 결과는 콜백으로 (클라이언트가 사는 스레드에서) 받습니다.

#include <QList>
#include <QMap>
#include <QObject>
#include <QString>
#include <QStringList>

#include <functional>

class QNetworkAccessManager;
class QNetworkReply;

namespace jvp::opensubtitles {

inline constexpr char kApiBase[] = "https://api.opensubtitles.com/api/v1";
inline constexpr char kUserAgent[] = "JetsonVideoPlayer v1.0";
constexpr int kTimeoutMs = 15000;
constexpr qint64 kHashChunk = 64 * 1024;

struct SubtitleResult {
    qint64 fileId = 0;
    QString language;
    QString release;
    QString fileName;
    int downloads = 0;
    bool hashMatch = false;
    QString title;
};

// OpenSubtitles 해시: 파일 크기 + 앞/뒤 64KB를 64비트 정수로 더한 값 (16자리 16진수). 실패 시 빈 문자열 + error
QString moviehash(const QString &path, QString *error = nullptr);
// 검색어: 파일 이름에서 화질·코덱·그룹 태그를 떼어 냅니다 (Movie.Name.2019.1080p.x265-GRP → Movie Name 2019)
QString queryFromFilename(const QString &path);

QString credentialsFile();   // paths::configDir()/opensubtitles.json
// {"api_key", "username", "password", "token"} — 환경 변수 키가 있으면 우선합니다.
QMap<QString, QString> loadCredentials(const QString &path = credentialsFile());
bool saveCredentials(const QMap<QString, QString> &creds, const QString &path = credentialsFile());   // 권한 600

QList<SubtitleResult> parseSearchResults(const QByteArray &json);   // 해시 일치 먼저, 다운로드 수 순
// 영상 옆 <영상 이름>.<언어>.<확장자>
QString subtitleSavePath(const QString &videoPath, const QString &language, const QString &contentName = QString());
// urllib.parse.urlencode와 같은 인코딩 (공백 '+', 쉼표 %2C)
QByteArray urlEncode(const QList<QPair<QString, QString>> &params);

class OpenSubtitlesClient : public QObject {
    Q_OBJECT
public:
    using SearchCallback = std::function<void(const QList<SubtitleResult> &results, const QString &error)>;
    using LoginCallback = std::function<void(const QString &token, const QString &error)>;
    using DownloadCallback = std::function<void(const QByteArray &content, const QString &error)>;

    explicit OpenSubtitlesClient(const QString &apiKey, const QString &username = QString(),
                                 const QString &password = QString(), const QString &token = QString(),
                                 QObject *parent = nullptr);
    ~OpenSubtitlesClient() override;

    bool hasApiKey() const { return !m_apiKey.isEmpty(); }
    void setApiBase(const QString &base) { m_apiBase = base; }   // 테스트용
    QString token() const { return m_token; }

    // 해시가 맞는 자막을 먼저, 이후 다운로드 수 순서 (해시 계산은 작업 스레드에서)
    void search(const QString &videoPath, const QStringList &languages, SearchCallback done,
                const QString &query = QString());
    // 계정이 있으면 토큰을 받아 둡니다 (다운로드 한도 증가). 계정이 없으면 빈 토큰으로 즉시 완료
    void login(LoginCallback done);
    // 자막 파일 내용. 먼저 POST /download로 임시 링크를 받은 뒤 그 링크를 GET
    void download(qint64 fileId, DownloadCallback done);

private:
    using JsonCallback = std::function<void(const QByteArray &body, const QString &error)>;
    void request(const QByteArray &method, const QString &path, const QByteArray &query, const QByteArray &body,
                 bool auth, JsonCallback done);
    void requestDownloadLink(qint64 fileId, DownloadCallback done);

    QString m_apiKey, m_username, m_password, m_token;
    QString m_apiBase = QString::fromLatin1(kApiBase);
    QNetworkAccessManager *m_nam;
};

} // namespace jvp::opensubtitles
