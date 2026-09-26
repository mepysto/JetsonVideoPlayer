#include "YouTube.h"

#include "Paths.h"

#include <QDir>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QProcess>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>

Q_LOGGING_CATEGORY(lcYoutube, "jvp.youtube")

namespace jvp::youtube {

namespace {
const QRegularExpression &urlInTextRe()
{
    static const QRegularExpression re(QStringLiteral(R"(https?://[^\s<>"]*(?:youtube\.com|youtu\.be)[^\s<>"]*)"));
    return re;
}

const QRegularExpression &idRe()
{
    static const QRegularExpression re(QStringLiteral(R"((?:v=|/shorts/|/embed/|/live/|youtu\.be/)([a-zA-Z0-9_-]{11})(?:[&?]|$))"));
    return re;
}

QString canonical(const QString &vid) { return QStringLiteral("https://www.youtube.com/watch?v=") + vid; }

// path[len(prefix):].split("/")[0].split("?")[0].split("&")[0]
QString firstSegment(const QString &s) { return s.section('/', 0, 0).section('?', 0, 0).section('&', 0, 0); }

QString queryV(const QUrl &u)
{
    const QUrlQuery q(u);
    return q.queryItemValue(QStringLiteral("v"), QUrl::FullyDecoded);
}

constexpr const char *kPrefixes[] = {"/shorts/", "/embed/", "/live/"};
const QString kProgressTag = QStringLiteral("[jvp-progress] ");
const QString kFileTag = QStringLiteral("[jvp-file] ");
const QString kTitleTag = QStringLiteral("[jvp-title] ");

double numberOrZero(const QString &s)
{
    bool ok = false;
    const double v = s.toDouble(&ok);   // "NA" → 0
    return ok ? v : 0.0;
}
} // namespace

bool isYoutubeUrl(const QString &url)
{
    if (url.isEmpty())
        return false;
    const QString u = url.trimmed().toLower();
    if (!u.contains(QLatin1String("youtube.com")) && !u.contains(QLatin1String("youtu.be")))
        return false;
    for (const char *p : {"http://", "https://", "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
        if (u.startsWith(QLatin1String(p)))
            return true;
    return urlInTextRe().match(url.trimmed()).hasMatch();
}

QString extractYoutubeUrl(const QString &text)
{
    if (text.isEmpty())
        return {};
    const QString t = text.trimmed();
    const auto m = urlInTextRe().match(t);
    QString candidate = m.hasMatch() ? m.captured(0) : t;
    if (!isYoutubeUrl(candidate)) {
        const auto m2 = idRe().match(t);
        const QString lower = t.toLower();
        if (m2.hasMatch() && (lower.contains(QLatin1String("youtube")) || lower.contains(QLatin1String("youtu.be"))))
            return canonical(m2.captured(1));
        return {};
    }
    if (!candidate.startsWith(QLatin1String("http://")) && !candidate.startsWith(QLatin1String("https://")))
        candidate = QStringLiteral("https://") + candidate;

    // 믹스(list=RD...)나 재생목록 파라미터가 섞여 있어도 단일 비디오(v=...)면 깔끔하게 정규화
    const QUrl parsed(candidate);
    if (parsed.isValid()) {
        const QString netloc = parsed.authority(), path = parsed.path();
        if (netloc.contains(QLatin1String("youtube.com")) && path.startsWith(QLatin1String("/watch"))) {
            const QString vid = queryV(parsed);
            if (!vid.isEmpty())
                return canonical(vid);
        }
        if (netloc.contains(QLatin1String("youtu.be"))) {
            QString p = path;
            while (p.startsWith('/'))
                p.remove(0, 1);
            while (p.endsWith('/'))
                p.chop(1);
            const QString vid = p.section('?', 0, 0).section('&', 0, 0);
            if (!vid.isEmpty())
                return canonical(vid);
        }
        for (const char *prefix : kPrefixes) {
            if (path.startsWith(QLatin1String(prefix))) {
                const QString vid = firstSegment(path.mid(int(strlen(prefix))));
                if (!vid.isEmpty())
                    return canonical(vid);
            }
        }
    }
    return candidate;
}

QString extractYoutubeVideoId(const QString &url)
{
    if (url.isEmpty())
        return {};
    const QString norm = extractYoutubeUrl(url);
    const QString target = norm.isEmpty() ? url.trimmed() : norm;
    const QUrl parsed(target);
    if (parsed.isValid()) {
        const QString path = parsed.path();
        if (path.contains(QLatin1String("watch"))) {
            const QString vid = queryV(parsed);
            if (!vid.isEmpty())
                return vid;
        }
        if (parsed.authority().contains(QLatin1String("youtu.be"))) {
            QString p = path;
            while (p.startsWith('/'))
                p.remove(0, 1);
            const QString vid = p.section('?', 0, 0).section('&', 0, 0);
            if (vid.size() == 11)
                return vid;
        }
        for (const char *prefix : kPrefixes)
            if (path.startsWith(QLatin1String(prefix))) {
                const QString vid = firstSegment(path.mid(int(strlen(prefix))));
                if (vid.size() == 11)
                    return vid;
            }
    }
    const auto m = idRe().match(target);
    return m.hasMatch() ? m.captured(1) : QString();
}

QPair<QString, QString> jsRuntime()
{
    for (const char *name : {"deno", "node"}) {
        const QString path = QStandardPaths::findExecutable(QString::fromLatin1(name));
        if (!path.isEmpty())
            return {QString::fromLatin1(name), path};
    }
    return {};
}

QString formatForQuality(const QString &quality)
{
    // Jetson NVDEC 하드웨어 가속을 보장하고 화면 미출력(AV1 DPB 결함)을 막기 위해 H.264(avc1) 최우선, AV1 배제
    if (quality == QLatin1String("1080p") || quality == QLatin1String("720p")) {
        const QString h = quality.chopped(1);
        return QStringLiteral("bestvideo[height<=%1][vcodec^=avc1]+bestaudio[ext=m4a]/"
                              "bestvideo[height<=%1][vcodec^=avc1]+bestaudio/"
                              "bestvideo[height<=%1][vcodec!*='av01'][vcodec!*='av1']+bestaudio[ext=m4a]/"
                              "best[height<=%1][vcodec^=avc1]/"
                              "best[height<=%1][vcodec!*='av01']/"
                              "best[height<=%1]")
            .arg(h);
    }
    if (quality == QLatin1String("audio"))
        return QStringLiteral("bestaudio[ext=m4a]/bestaudio");
    return QStringLiteral("bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/"
                          "bestvideo[vcodec^=avc1]+bestaudio/"
                          "bestvideo[vcodec!*='av01'][vcodec!*='av1']+bestaudio[ext=m4a]/"
                          "bestvideo[vcodec!*='av01'][vcodec!*='av1']+bestaudio/"
                          "best[vcodec^=avc1]/"
                          "best[vcodec!*='av01']/"
                          "best");
}

QString formatSpeed(double speed)
{
    if (speed > 1024 * 1024)
        return QStringLiteral("%1 MB/s").arg(speed / (1024 * 1024), 0, 'f', 1);
    if (speed > 1024)
        return QStringLiteral("%1 KB/s").arg(speed / 1024, 0, 'f', 0);
    return QStringLiteral("%1 B/s").arg(speed, 0, 'f', 0);
}

QString formatEta(qint64 eta)
{
    return eta < 60 ? QStringLiteral("%1초").arg(eta) : QStringLiteral("%1분 %2초").arg(eta / 60).arg(eta % 60);
}

QString findYtDlp()
{
    QString p = QStandardPaths::findExecutable(QStringLiteral("yt-dlp"));
    if (p.isEmpty())
        p = QStandardPaths::findExecutable(QStringLiteral("yt-dlp"), {QDir::homePath() + QStringLiteral("/.local/bin")});
    return p;
}

// ---- ProcessRunner -------------------------------------------------------------------------------

ProcessRunner::ProcessRunner(QObject *parent) : DownloadRunner(parent), m_proc(new QProcess(this))
{
    m_proc->setProcessChannelMode(QProcess::MergedChannels);
    connect(m_proc, &QProcess::readyRead, this, [this] {
        m_buffer += m_proc->readAll();
        int nl;
        while ((nl = m_buffer.indexOf('\n')) >= 0) {
            const QString line = QString::fromUtf8(m_buffer.left(nl)).trimmed();
            m_buffer.remove(0, nl + 1);
            if (!line.isEmpty())
                emit lineReceived(line);
        }
    });
    connect(m_proc, &QProcess::finished, this, [this](int code, QProcess::ExitStatus st) {
        if (!m_buffer.trimmed().isEmpty())
            emit lineReceived(QString::fromUtf8(m_buffer).trimmed());
        m_buffer.clear();
        emit finished(code, st == QProcess::CrashExit);
    });
    connect(m_proc, &QProcess::errorOccurred, this, [this](QProcess::ProcessError e) {
        if (e == QProcess::FailedToStart) {
            emit lineReceived(QStringLiteral("ERROR: yt-dlp 실행 실패: %1").arg(m_proc->errorString()));
            emit finished(-1, true);
        }
    });
}

void ProcessRunner::start(const QString &program, const QStringList &args) { m_proc->start(program, args); }

void ProcessRunner::kill()
{
    if (m_proc->state() != QProcess::NotRunning)
        m_proc->kill();
}

// ---- YouTubeManager -----------------------------------------------------------------------------

const QString YouTubeManager::kCancelledMessage = QStringLiteral("사용자가 다운로드를 취소했습니다.");

YouTubeManager::YouTubeManager(const QString &downloadDir, QObject *parent)
    : QObject(parent), m_downloadDir(downloadDir.isEmpty() ? paths::youtubeDir() : downloadDir), m_program(findYtDlp()),
      m_factory([] { return new ProcessRunner(); })
{
    if (!QDir().mkpath(m_downloadDir))
        qCWarning(lcYoutube) << "⚠️ YouTube 저장 폴더를 만들 수 없습니다:" << m_downloadDir;
    m_current = {{"active", false}, {"title", ""},       {"url", ""},    {"percent", 0.0},    {"speed", ""},
                 {"eta", ""},       {"filepath", QVariant()}, {"error", QVariant()}, {"completed", false}};
}

YouTubeManager::~YouTubeManager()
{
    if (m_runner) {
        m_runner->disconnect(this);
        m_runner->kill();
        delete m_runner;
    }
}

void YouTubeManager::setRunnerFactory(RunnerFactory factory) { m_factory = std::move(factory); }
void YouTubeManager::setProgram(const QString &program) { m_program = program; }

QVariantMap YouTubeManager::status() const
{
    QVariantMap s = m_current;
    QVariantList queue;
    for (const Job &j : m_pending)
        queue.append(QVariantMap{{"url", j.url}, {"quality", j.quality}});
    s.insert("queue", queue);
    return s;
}

QString YouTubeManager::findExistingVideo(const QString &urlOrId) const
{
    if (!QFileInfo(m_downloadDir).isDir())
        return {};
    const bool looksLikeUrl = urlOrId.startsWith(QLatin1String("http")) || urlOrId.contains(QLatin1String("youtube"))
                              || urlOrId.contains(QLatin1String("youtu.be"));
    const QString vid = looksLikeUrl ? extractYoutubeVideoId(urlOrId) : urlOrId;
    if (vid.isEmpty())
        return {};
    const QString pattern = QStringLiteral("[%1].").arg(vid);
    QStringList names = QDir(m_downloadDir).entryList(QDir::Files | QDir::NoDotAndDotDot);
    std::sort(names.begin(), names.end());
    for (const QString &f : names) {
        if (f.contains(pattern) && !f.endsWith(QLatin1String(".part"))) {
            const QFileInfo fi(m_downloadDir + QLatin1Char('/') + f);
            if (fi.isFile() && fi.size() > 512 * 1024)
                return fi.filePath();
        }
    }
    return {};
}

QString YouTubeManager::titleFromFilename(const QString &path)
{
    const QString base = QFileInfo(path).fileName();
    const int dot = base.lastIndexOf('.');
    QString title = dot > 0 ? base.left(dot) : base;
    if (title.contains('[') && title.endsWith(']'))
        title = title.left(title.lastIndexOf('[')).trimmed();
    return title;
}

QStringList YouTubeManager::buildArguments(const QString &url, const QString &quality) const
{
    QStringList args{
        "--ignore-config",   // 파이썬 모듈 API처럼 사용자 설정 파일의 영향을 받지 않게
        "-f", formatForQuality(quality),
        "-o", m_downloadDir + QStringLiteral("/%(title)s [%(id)s].%(ext)s"),
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--force-overwrites",
        "--concurrent-fragments", "4",
        "--remote-components", QStringLiteral("ejs:github"),
        "--no-warnings", "--quiet", "--progress", "--newline",
        "--progress-template",
        "download:" + kProgressTag
            + "%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
              "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(info.title)s",
        "--print", "after_move:" + kFileTag + "%(filepath)s",
        "--print", "after_move:" + kTitleTag + "%(title)s",
    };
    const auto js = jsRuntime();
    if (!js.first.isEmpty())
        args << "--js-runtimes" << js.first + ":" + js.second;
    args << "--" << url;
    return args;
}

QPair<QString, int> YouTubeManager::downloadAsync(const QString &url, const QString &quality)
{
    if (m_program.isEmpty()) {
        QTimer::singleShot(0, this, [this, url] { emit failed(url, QStringLiteral("yt-dlp가 설치되어 있지 않습니다.")); });
        return {QStringLiteral("error"), 0};
    }
    // 1. 이미 받아 둔 파일이 있으면 다운로드를 생략하고 그 파일로 완료
    const QString existing = findExistingVideo(url);
    if (!existing.isEmpty()) {
        const QString title = titleFromFilename(existing);
        QTimer::singleShot(0, this, [this, url, existing, title] { emit finished(url, existing, title); });
        return {QStringLiteral("cached"), 0};
    }
    if (m_current.value("active").toBool()) {
        if (m_current.value("url").toString() == url)
            return {QStringLiteral("downloading"), 0};   // 같은 영상을 이미 받는 중
        auto sameUrl = [&](const Job &j) { return j.url == url; };
        if (std::none_of(m_pending.begin(), m_pending.end(), sameUrl)) {
            m_pending.append({url, quality});
            emit statusChanged();
        }
        const int pos = int(std::find_if(m_pending.begin(), m_pending.end(), sameUrl) - m_pending.begin()) + 1;
        return {QStringLiteral("queued"), pos};
    }
    begin({url, quality});
    return {QStringLiteral("started"), 0};
}

bool YouTubeManager::cancelCurrent()
{
    if (!m_current.value("active").toBool() || !m_runner)
        return false;
    m_cancelRequested = true;
    m_runner->kill();
    return true;
}

bool YouTubeManager::cancelPending(const QString &url)
{
    const auto before = m_pending.size();
    m_pending.erase(std::remove_if(m_pending.begin(), m_pending.end(), [&](const Job &j) { return j.url == url; }),
                    m_pending.end());
    const bool changed = m_pending.size() != before;
    if (changed)
        emit statusChanged();
    return changed;
}

void YouTubeManager::begin(const Job &job)
{
    m_cancelRequested = false;
    m_finalPath.clear();
    m_finalTitle.clear();
    m_lastError.clear();
    m_current.insert("active", true);
    m_current.insert("title", QStringLiteral("정보 확인 중..."));
    m_current.insert("url", job.url);
    m_current.insert("percent", 0.0);
    m_current.insert("speed", "");
    m_current.insert("eta", "");
    m_current.insert("filepath", QVariant());
    m_current.insert("error", QVariant());
    m_current.insert("completed", false);
    m_runner = m_factory();
    connect(m_runner, &DownloadRunner::lineReceived, this, &YouTubeManager::onLine);
    connect(m_runner, &DownloadRunner::finished, this, &YouTubeManager::onFinished);
    emit statusChanged();
    m_runner->start(m_program, buildArguments(job.url, job.quality));
}

void YouTubeManager::onLine(const QString &line)
{
    if (line.startsWith(kProgressTag)) {
        const QStringList f = line.mid(kProgressTag.size()).split('|');
        if (f.size() < 7)
            return;
        const QString title = QStringList(f.mid(6)).join('|');   // 제목에 '|'가 있어도 보존
        if (f[0] == QLatin1String("downloading")) {
            double total = numberOrZero(f[2]);
            if (total <= 0)
                total = numberOrZero(f[3]);
            const double downloaded = numberOrZero(f[1]);
            const double pct = total > 0 ? downloaded / total * 100.0 : 0.0;
            const QString speed = formatSpeed(numberOrZero(f[4]));
            const QString eta = formatEta(qint64(numberOrZero(f[5])));
            const QString t = title.isEmpty() || title == QLatin1String("NA") ? QStringLiteral("YouTube Video") : title;
            m_current.insert("title", t);
            m_current.insert("percent", pct);
            m_current.insert("speed", speed);
            m_current.insert("eta", eta);
            emit progress(m_current.value("url").toString(), pct, speed, eta, t);
            emit statusChanged();
        }
    } else if (line.startsWith(kFileTag)) {
        m_finalPath = line.mid(kFileTag.size());
        m_current.insert("filepath", m_finalPath);
    } else if (line.startsWith(kTitleTag)) {
        m_finalTitle = line.mid(kTitleTag.size());
    } else if (line.startsWith(QLatin1String("ERROR:"))) {
        m_lastError = line;
    }
}

void YouTubeManager::onFinished(int exitCode, bool crashed)
{
    const QString url = m_current.value("url").toString();
    if (m_runner) {
        m_runner->disconnect(this);
        m_runner->deleteLater();
        m_runner = nullptr;
    }
    if (!m_cancelRequested && exitCode == 0 && !crashed) {
        QString path = m_finalPath;
        if (path.isEmpty() || !QFileInfo::exists(path)) {
            const QString found = findExistingVideo(url);
            if (!found.isEmpty())
                path = found;
        }
        // 병합 결과가 mp4로 바뀐 경우 (파이썬 버전과 같은 보정)
        const QString mp4 = QFileInfo(path).path() + QLatin1Char('/') + QFileInfo(path).completeBaseName() + ".mp4";
        if (!path.isEmpty() && !path.endsWith(".mp4") && QFileInfo::exists(mp4))
            path = mp4;
        const QString title = m_finalTitle.isEmpty() ? (path.isEmpty() ? QStringLiteral("YouTube Video")
                                                                        : titleFromFilename(path))
                                                     : m_finalTitle;
        m_current.insert("active", false);
        m_current.insert("percent", 100.0);
        m_current.insert("filepath", path.isEmpty() ? QVariant() : QVariant(path));
        m_current.insert("completed", true);
        emit statusChanged();
        emit finished(url, path, title);
    } else {
        const bool cancelled = m_cancelRequested;
        QString err = cancelled ? kCancelledMessage : m_lastError;
        if (!cancelled && err.isEmpty())
            err = QStringLiteral("yt-dlp 종료 코드 %1").arg(exitCode);
        if (cancelled)
            cleanupPartialFiles(url);
        m_current.insert("active", false);
        m_current.insert("error", err);
        emit statusChanged();
        emit failed(url, err);
    }
    m_cancelRequested = false;
    startNext();
}

void YouTubeManager::startNext()
{
    while (!m_pending.isEmpty()) {
        const Job job = m_pending.takeFirst();
        const QString existing = findExistingVideo(job.url);
        if (!existing.isEmpty()) {
            const QString title = titleFromFilename(existing);
            QTimer::singleShot(0, this, [this, url = job.url, existing, title] { emit finished(url, existing, title); });
            continue;
        }
        begin(job);
        return;
    }
    emit statusChanged();
}

void YouTubeManager::cleanupPartialFiles(const QString &url)
{
    const QString vid = extractYoutubeVideoId(url);
    if (vid.isEmpty())
        return;
    static const QRegularExpression fragment(QStringLiteral(R"(\.f\d+\.)"));
    const QString tag = QStringLiteral("[%1]").arg(vid);
    for (const QString &f : QDir(m_downloadDir).entryList(QDir::Files | QDir::NoDotAndDotDot))
        if (f.contains(tag) && (f.contains(".part") || f.contains(".ytdl") || fragment.match(f).hasMatch()))
            QFile::remove(m_downloadDir + QLatin1Char('/') + f);
}

} // namespace jvp::youtube
