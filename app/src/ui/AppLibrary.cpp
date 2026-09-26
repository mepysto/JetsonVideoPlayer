// 재생목록: 파일·폴더·M3U 열기, 드래그 앤 드롭, 정렬·새로고침·폴더 감시, 최근 기록, 이어보기 카드,
// 네트워크 폴더(SMB/NFS) 연결·재연결, 백그라운드 HW 적합성 검사.
// (파이썬 ui/library.py, playlist.py, watch.py, network.py, layout.py의 이어보기 카드)
#include "AppController.h"

#include "Library.h"
#include "MediaProbe.h"
#include "NetworkMount.h"
#include "NetworkUri.h"
#include "Paths.h"
#include "PlaylistModel.h"
#include "Settings.h"
#include "Storage.h"
#include "SubtitleParse.h"
#include "SystemInfo.h"
#include "YouTubeController.h"

#include <QDir>
#include <QDirIterator>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QThread>
#include <QUrl>
#include <QtConcurrent>

Q_DECLARE_LOGGING_CATEGORY(lcApp)

namespace jvp {

namespace {
constexpr int kMaxWatchedDirs = 300;   // 넘으면 주기적 재검사로 대체 (inotify 감시 수 한도 보호)

bool isRemote(const QString &p)
{
    return p.startsWith(QLatin1String("http://")) || p.startsWith(QLatin1String("https://"));
}

const QHash<QString, QString> &sortLabels()
{
    static const QHash<QString, QString> l{{"name", "이름순"}, {"mtime", "최근 수정순"}, {"size", "크기순"}};
    return l;
}

// 감시할 폴더 목록 (많으면 nullopt)
std::optional<QStringList> watchedDirs(const QString &root)
{
    QStringList dirs{root};
    QDirIterator it(root, QDir::Dirs | QDir::NoDotAndDotDot, QDirIterator::Subdirectories | QDirIterator::FollowSymlinks);
    while (it.hasNext()) {
        const QString d = it.next();
        const QString name = it.fileName();
        if (name.startsWith(QLatin1Char('.')) || d.contains(QLatin1String("/unsupported_originals")))
            continue;
        dirs << d;
        if (dirs.size() > kMaxWatchedDirs)
            return std::nullopt;
    }
    return dirs;
}
} // namespace

// ============================================================================
// 재생목록 구성
// ============================================================================

bool AppController::buildPlaylist(const QString &input, const std::optional<QStringList> &scanned)
{
    const QString abs = library::absPath(input);
    const QFileInfo fi(abs);
    QStringList raw;
    bool single = false;
    bool m3u = false;
    if (fi.isDir()) {
        raw = scanned ? *scanned : library::scanVideoFiles(abs);
        if (raw.isEmpty()) {
            qCWarning(lcApp).noquote() << "❌ 에러: [" << input << "] 폴더 내에 재생 가능한 영상 파일이 없습니다.";
            return false;
        }
    } else if (fi.isFile() && library::isPlaylistFile(abs)) {
        const library::M3uResult r = library::parseM3u(abs);
        if (!r.ok) {
            qCWarning(lcApp).noquote() << "❌ 재생목록 파일을 읽을 수 없습니다:" << abs;
            return false;
        }
        if (r.skipped)
            qCWarning(lcApp).noquote() << "⚠️ 재생목록" << fi.fileName() << ": 없는 파일·온라인 주소" << r.skipped
                                       << "개는 건너뜁니다.";
        if (r.videos.isEmpty()) {
            qCWarning(lcApp).noquote() << "❌ 재생목록" << abs << "에 재생할 수 있는 영상이 없습니다.";
            return false;
        }
        raw = r.videos;
        single = raw.size() == 1;
        m3u = true;
    } else if (fi.isFile()) {
        raw << abs;
        single = true;
    } else {
        qCWarning(lcApp).noquote() << "❌ 에러: [" << input << "] 존재하지 않는 파일이거나 올바르지 않은 경로입니다.";
        return false;
    }
    // 시작 시 모든 파일을 검사하지 않고, 같은 폴더의 _h265.mp4 변환본만 빠르게 우선 매핑합니다.
    QStringList list = library::preferH265Versions(raw);
    if (!m3u)   // M3U는 파일에 적힌 순서대로 재생
        list = library::sortVideoPaths(list, Settings::instance()->stringValue(QStringLiteral("playlist_sort")));
    m_playlist = list;
    m_inputPath = input;
    m_singleFile = single;
    m_fromM3u = m3u;
    m_fromFiles = false;
    m_index = 0;
    m_queue.clear();
    qCInfo(lcApp).noquote() << QStringLiteral("📂 [%1] 총 %2개의 영상을 로드했습니다.")
                                   .arg(single ? QStringLiteral("단일 파일 반복 모드") : QStringLiteral("폴더 순환 모드"))
                                   .arg(list.size());
    return true;
}

void AppController::refreshPlaylistModel()
{
    const QFileInfo root(m_inputPath);
    m_playlistModel->setPlaylist(m_playlist, root.isDir() ? root.absoluteFilePath() : QString(), paths::youtubeDir());
    m_playlistModel->setActiveIndex(m_playlist.isEmpty() ? -1 : m_index);
    m_playlistModel->setQueue(m_queue);
    m_playlistModel->setSortLabel(sortLabels().value(Settings::instance()->stringValue(QStringLiteral("playlist_sort")),
                                                       QStringLiteral("이름순")));
    emit mediaChanged();
}

void AppController::loadPath(const QString &input, const std::optional<QStringList> &scanned)
{
    // 네트워크 폴더는 목록을 읽는 데 오래 걸릴 수 있어 백그라운드에서 읽은 뒤 이어서 진행합니다.
    if (!scanned && network::isGvfsPath(input) && QFileInfo(input).isDir()) {
        scanNetworkFolderThenLoad(input);
        return;
    }
    const QString prevInput = m_inputPath;
    const QStringList prevList = m_playlist;
    const int prevIndex = m_index;
    const bool prevSingle = m_singleFile;
    if (!buildPlaylist(input, scanned)) {
        // 기존 재생목록을 유지합니다.
        m_inputPath = prevInput;
        m_playlist = prevList;
        m_index = prevIndex;
        m_singleFile = prevSingle;
        showOsd(QStringLiteral("⚠️ 재생할 수 있는 영상이 없습니다."), 2500);
        return;
    }
    refreshPlaylistModel();
    startFolderWatch();
    if (!m_playlist.isEmpty()) {
        m_index = 0;
        playCurrent();
    }
    startBackgroundHwChecker();
}

void AppController::loadFiles(const QStringList &files)
{
    QStringList valid;
    for (const QString &f : files)
        if (library::isVideoFile(f))
            valid << library::absPath(f);
    if (valid.isEmpty())
        return;
    m_playlist = library::sortVideoPaths(valid, Settings::instance()->stringValue(QStringLiteral("playlist_sort")));
    m_inputPath = valid.size() > 1 ? QFileInfo(valid.first()).absolutePath() : valid.first();
    m_index = 0;
    m_singleFile = valid.size() == 1;
    m_fromFiles = true;   // 직접 고른 파일 목록: 폴더 감시·새로고침 대상이 아님
    m_fromM3u = false;
    m_queue.clear();
    stopFolderWatch();
    refreshPlaylistModel();
    playCurrent();
}

void AppController::openUrls(const QList<QUrl> &urls)
{
    QStringList files;
    for (const QUrl &u : urls) {
        if (u.isLocalFile()) {
            files << u.toLocalFile();
        } else if (network::isNetworkUri(u.toString())) {
            openNetworkUri(u.toString());
            return;
        }
    }
    if (files.isEmpty())
        return;
    for (const QString &f : files)
        if (library::isPlaylistFile(f)) {
            loadPath(f);
            return;
        }
    if (files.size() == 1 && QFileInfo(files.first()).isDir()) {
        loadPath(files.first());
        return;
    }
    loadFiles(files);
}

void AppController::openPath(const QString &path)
{
    // 최근 기록·이어보기 카드: 연결이 끊긴 네트워크 폴더면 다시 연결한 뒤 엽니다.
    if (!path.isEmpty() && !QFileInfo::exists(path) && network::isGvfsPath(path)) {
        reconnectNetworkPath(path);
        return;
    }
    if (path.isEmpty() || !QFileInfo::exists(path)) {
        showOsd(QStringLiteral("경로가 존재하지 않습니다."));
        return;
    }
    loadPath(library::absPath(path));
}

void AppController::playPathAt(const QString &path, qint64 startNs)
{
    int i = int(m_playlist.indexOf(path));
    if (i < 0) {
        m_playlist << path;
        i = int(m_playlist.size()) - 1;
        m_singleFile = false;
        refreshPlaylistModel();
    }
    cancelAutoplay();
    m_index = i;
    playCurrent(0, startNs);
}

void AppController::appendToPlaylist(const QString &path)
{
    if (m_playlist.contains(path))
        return;
    m_playlist << path;
    m_singleFile = false;
    refreshPlaylistModel();
}

void AppController::addToPlaylistAndPlay(const QString &path)
{
    if (m_playlist.isEmpty()) {
        loadPath(path);
        return;
    }
    playPathAt(path, 0);
}

void AppController::dropUrls(const QList<QUrl> &urls)
{
    // YouTube 링크
    for (const QUrl &u : urls)
        if (YouTubeController::isYoutubeUrl(u.toString())) {
            startYoutube(u.toString(), QStringLiteral("best"));
            return;
        }
    QStringList paths;
    for (const QUrl &u : urls)
        if (u.isLocalFile() && QFileInfo::exists(u.toLocalFile()))
            paths << u.toLocalFile();
    if (paths.isEmpty())
        return;
    const QString first = paths.first();
    // 자막 파일: 지금 영상에 추가
    if (subtitles::kSubtitleExts.contains(library::extensionLower(first))) {
        if (!currentPath().isEmpty()) {
            addExternalSubtitle(first);
            qCInfo(lcApp).noquote() << "💬 드래그로 자막 추가:" << first;
        }
        return;
    }
    if (QFileInfo(first).isDir() || library::isPlaylistFile(first)) {
        loadPath(first);
        return;
    }
    loadFiles(paths);
}

void AppController::dropText(const QString &text)
{
    const QString t = text.trimmed();
    if (YouTubeController::isYoutubeUrl(t))
        startYoutube(t, QStringLiteral("best"));
    else if (network::isNetworkUri(t))
        openNetworkUri(t);
    else if (QFileInfo::exists(t))
        openPath(t);
}

// ============================================================================
// M3U 저장 · 정렬 · 대기열
// ============================================================================

QUrl AppController::suggestedM3uUrl() const
{
    if (m_playlist.isEmpty())
        return {};
    const QFileInfo root(m_inputPath);
    const QString folder = root.isDir() ? root.absoluteFilePath() : QFileInfo(m_playlist.first()).absolutePath();
    QString name = QFileInfo(folder).fileName();
    if (name.isEmpty())
        name = QStringLiteral("재생목록");
    return QUrl::fromLocalFile(folder + QLatin1Char('/') + name + QStringLiteral(".m3u8"));
}

void AppController::saveM3u(const QUrl &url)
{
    if (m_playlist.isEmpty()) {
        showOsd(QStringLiteral("ℹ️ 저장할 재생목록이 없습니다."));
        return;
    }
    QString dest = url.toLocalFile();
    if (dest.isEmpty())
        return;
    if (!library::isPlaylistFile(dest))
        dest += QStringLiteral(".m3u8");
    QStringList local;
    for (const QString &p : std::as_const(m_playlist))
        if (!isRemote(p))
            local << p;
    if (!library::writeM3u(local, dest)) {
        showOsd(QStringLiteral("❌ 저장 실패: %1").arg(dest), 3500);
        return;
    }
    showOsd(QStringLiteral("💾 재생목록 저장: %1 (%2개)").arg(QFileInfo(dest).fileName()).arg(m_playlist.size()), 2500);
    qCInfo(lcApp).noquote() << "💾 [재생목록 저장]" << dest;
}

void AppController::cyclePlaylistSort()
{
    static const QStringList order{"name", "mtime", "size"};
    const QString cur = Settings::instance()->stringValue(QStringLiteral("playlist_sort"));
    const int i = int(order.indexOf(cur));
    const QString mode = i < 0 ? QStringLiteral("name") : order[(i + 1) % order.size()];
    Settings::instance()->setValue(QStringLiteral("playlist_sort"), mode);
    applyPlaylistSort(true);
    showOsd(QStringLiteral("↕ 재생목록 정렬: %1").arg(sortLabels().value(mode)));
}

void AppController::applyPlaylistSort(bool resort)
{
    if (resort && !m_playlist.isEmpty()) {
        const QString current = currentPath();
        m_playlist = library::sortVideoPaths(m_playlist, Settings::instance()->stringValue(QStringLiteral("playlist_sort")));
        const int i = int(m_playlist.indexOf(current));
        if (i >= 0)
            m_index = i;
    }
    refreshPlaylistModel();
}

// ============================================================================
// 폴더 감시 · 새로고침
// ============================================================================

bool AppController::playlistIsFolder() const
{
    return !m_inputPath.isEmpty() && QFileInfo(m_inputPath).isDir() && !m_singleFile && !m_fromFiles && !m_fromM3u;
}

void AppController::startFolderWatch()
{
    stopFolderWatch();
    if (!playlistIsFolder())
        return;
    const QString root = QFileInfo(m_inputPath).absoluteFilePath();
    const std::optional<QStringList> dirs = network::isGvfsPath(root) ? std::nullopt : watchedDirs(root);
    if (!dirs) {
        // 네트워크 폴더는 변경 알림이 오지 않고, 하위 폴더가 아주 많으면 감시 수 한도에 걸립니다.
        m_watchPoll.start();
        qCDebug(lcApp).noquote() << "📂 폴더 감시: 60초마다 다시 읽기 (" << root << ")";
        return;
    }
    m_watcher = new QFileSystemWatcher(this);
    m_watcher->addPaths(*dirs);
    // 복사 중인 파일은 알림이 계속 오므로, 조용해진 뒤 한 번만 다시 읽습니다.
    connect(m_watcher, &QFileSystemWatcher::directoryChanged, this, [this] { m_rescanDebounce.start(); });
    qCDebug(lcApp).noquote() << "📂 폴더 감시:" << dirs->size() << "개 폴더 (" << root << ")";
}

void AppController::stopFolderWatch()
{
    delete m_watcher;
    m_watcher = nullptr;
    m_watchPoll.stop();
    m_rescanDebounce.stop();
}

void AppController::scheduleRescan() { m_rescanDebounce.start(); }

void AppController::rescanPlaylist(bool quiet)
{
    if (!playlistIsFolder()) {
        if (!quiet)
            showOsd(QStringLiteral("ℹ️ 폴더로 연 재생목록만 새로고침할 수 있습니다."));
        return;
    }
    if (m_rescanRunning)
        return;
    m_rescanRunning = true;
    const QString root = m_inputPath;
    QPointer<AppController> self(this);
    QThreadPool::globalInstance()->start([self, root, quiet] {
        const QString abs = library::absPath(root);
        std::optional<QStringList> scanned;
        if (QFileInfo(abs).isDir())
            scanned = library::preferH265Versions(library::scanVideoFiles(abs));
        QMetaObject::invokeMethod(qApp, [self, root, scanned, quiet] {
            if (self)
                self->applyRescan(root, scanned, quiet);
        });
    });
}

void AppController::applyRescan(const QString &root, const std::optional<QStringList> &scanned, bool quiet)
{
    m_rescanRunning = false;
    if (!scanned || root != m_inputPath)
        return;
    const QString current = currentPath();
    const library::MergeResult r = library::mergeRescanned(m_playlist, library::absPath(root), *scanned, current);
    if (r.added.isEmpty() && r.removed.isEmpty()) {
        if (!quiet)
            showOsd(QStringLiteral("🔄 재생목록이 최신 상태입니다."));
        return;
    }
    m_playlist = library::sortVideoPaths(r.playlist, Settings::instance()->stringValue(QStringLiteral("playlist_sort")));
    const int i = int(m_playlist.indexOf(current));
    if (i >= 0)
        m_index = i;
    QStringList queue;
    for (const QString &q : std::as_const(m_queue))
        if (m_playlist.contains(q))
            queue << q;
    m_queue = queue;
    refreshPlaylistModel();
    QStringList parts;
    if (!r.added.isEmpty())
        parts << QStringLiteral("+%1").arg(r.added.size());
    if (!r.removed.isEmpty())
        parts << QStringLiteral("-%1").arg(r.removed.size());
    showOsd(QStringLiteral("🔄 재생목록 갱신 (%1): 총 %2개").arg(parts.join(" / ")).arg(m_playlist.size()), 2500);
    qCInfo(lcApp).noquote() << "🔄 [재생목록 갱신] 추가" << r.added.size() << ", 제거" << r.removed.size() << "→"
                            << m_playlist.size() << "개";
    // 새 하위 폴더가 생겼을 수 있으므로 감시 대상을 다시 잡습니다.
    if (!r.added.isEmpty() && !network::isGvfsPath(root))
        startFolderWatch();
}

// ============================================================================
// 백그라운드 HW 적합성 검사
// ============================================================================

void AppController::startBackgroundHwChecker()
{
    if (m_playlist.isEmpty())
        return;
    const QStringList paths = m_playlist;
    QPointer<AppController> self(this);
    QThreadPool::globalInstance()->start([self, paths] {
        QThread::msleep(1500);   // 첫 영상이 시작되고 UI가 자리 잡을 때까지
        for (const QString &path : paths) {
            if (!self || self->m_shuttingDown)
                return;
            if (isRemote(path) || !QFileInfo::exists(path) || hwCache().get(path))
                continue;
            const probe::HwSupport hw = probe::checkHwSupport(path);
            if (hw.supported == false) {
                // 같은 폴더에 _h265.mp4 변환본이 있으면 그것으로 바꿉니다.
                const QFileInfo fi(path);
                const QString h265 = fi.absolutePath() + QLatin1Char('/') + library::stem(fi.fileName())
                                     + QStringLiteral("_h265.mp4");
                if (QFileInfo::exists(h265))
                    QMetaObject::invokeMethod(qApp, [self, path, h265] {
                        if (!self)
                            return;
                        const int i = int(self->m_playlist.indexOf(path));
                        if (i >= 0 && QFileInfo::exists(h265)) {
                            self->m_playlist[i] = h265;
                            self->refreshPlaylistModel();
                        }
                    });
            }
            QThread::msleep(50);   // 재생 성능에 영향을 주지 않도록
        }
        hwCache().save();
    });
}

// ============================================================================
// 위치 열기 · 기록 · 이어보기 카드
// ============================================================================

void AppController::openLocation(const QString &path)
{
    QString target = path;
    if (target.isEmpty())
        target = currentPath();
    if (target.isEmpty()) {
        if (QFileInfo::exists(paths::youtubeDir())) {
            target = paths::youtubeDir();
        } else {
            showOsd(QStringLiteral("⚠️ 열 위치가 지정되지 않았습니다."));
            return;
        }
    }
    if (SystemInfo::openFileLocation(target)) {
        const QFileInfo fi(target);
        const QString dir = fi.isDir() ? fi.absoluteFilePath() : fi.absolutePath();
        showOsd(QStringLiteral("📂 폴더 열기: %1").arg(QFileInfo(dir).fileName().isEmpty() ? dir : QFileInfo(dir).fileName()), 2000);
        qCInfo(lcApp).noquote() << "📂 [파일 위치 열기]" << target;
    } else {
        showOsd(QStringLiteral("⚠️ 파일 브라우저를 열지 못했습니다."));
    }
}

void AppController::openCurrentLocation() { openLocation(QString()); }

QVariantList AppController::history() const
{
    QVariantList out;
    for (const QVariant &v : historyCache().all()) {
        const QVariantMap m = v.toMap();
        out << QVariantMap{{"path", m.value("path")}, {"title", m.value("title")}, {"isDir", m.value("is_dir")}};
    }
    return out;
}

void AppController::refreshResumeCards()
{
    // 연결이 끊긴 네트워크 폴더의 영상도 보여 주고, 누르면 다시 연결합니다.
    const QVariantList locations = Settings::instance()->listValue(QStringLiteral("network_locations"));
    const auto recent = resumeCache().recentInProgress(4, [&](const QString &p) {
        return QFileInfo(p).isFile() || (network::isGvfsPath(p) && !network::uriForPath(locations, p).isNull());
    });
    m_resumeCards.clear();
    for (const auto &e : recent) {
        const QString dur = e.durationNs > 0 ? QStringLiteral(" / ") + formatTime(e.durationNs / 1e6) : QString();
        m_resumeCards << QVariantMap{
            {"path", e.path},
            {"title", QFileInfo(e.path).fileName()},
            {"fraction", e.durationNs > 0 ? qBound(0.0, double(e.positionNs) / e.durationNs, 1.0) : 0.0},
            {"meta", QStringLiteral("%1%2  ·  📁 %3").arg(formatTime(e.positionNs / 1e6), dur,
                                                         QFileInfo(QFileInfo(e.path).absolutePath()).fileName())},
        };
    }
    emit resumeCardsChanged();
}

// ============================================================================
// 네트워크 폴더
// ============================================================================

QVariantList AppController::networkLocations() const
{
    return network::cleanLocations(Settings::instance()->value(QStringLiteral("network_locations")));
}

void AppController::openNetworkUri(const QString &text)
{
    const QString uri = network::normalizeUri(text);
    if (uri.isEmpty())
        return;
    if (!network::isNetworkUri(uri)) {
        if (QFileInfo(uri).isDir())
            loadPath(uri);
        else
            showOsd(QStringLiteral("⚠️ smb:// 또는 nfs:// 로 시작하는 주소를 입력하세요."), 3000);
        return;
    }
    showOsd(QStringLiteral("🌐 연결 중: %1").arg(network::displayName(uri)), 10000);
    m_network->mount(uri);
}

void AppController::onMountFinished(const QString &uri, const QString &localPath, const QString &error)
{
    if (!error.isEmpty()) {
        showOsd(QStringLiteral("❌ 연결 실패: %1").arg(error.left(60)), 4000);
        return;
    }
    Settings *s = Settings::instance();
    s->setValue(QStringLiteral("network_locations"),
                network::rememberLocation(s->listValue(QStringLiteral("network_locations")), uri, localPath));
    s->save();
    qCInfo(lcApp).noquote() << "🌐 [네트워크 폴더]" << uri << "→" << localPath;
    // 재연결(이어보기 카드 등)이었다면 원래 열려던 파일을 엽니다.
    const QString pending = property("jvpPendingNetworkPath").toString();
    setProperty("jvpPendingNetworkPath", QVariant());
    if (!pending.isEmpty()) {
        if (QFileInfo::exists(pending))
            loadPath(pending);
        else
            showOsd(QStringLiteral("⚠️ 네트워크 폴더에서 파일을 찾을 수 없습니다."), 3000);
        return;
    }
    loadPath(localPath);
}

void AppController::reconnectNetworkPath(const QString &path)
{
    const QString uri = network::uriForPath(Settings::instance()->listValue(QStringLiteral("network_locations")), path);
    if (uri.isEmpty()) {
        showOsd(QStringLiteral("⚠️ 네트워크 폴더가 연결되어 있지 않습니다. ⋯ → 🌐 네트워크 폴더 열기"), 4000);
        return;
    }
    setProperty("jvpPendingNetworkPath", path);
    showOsd(QStringLiteral("🌐 연결 중: %1").arg(network::displayName(uri)), 10000);
    m_network->mount(uri);
}

void AppController::scanNetworkFolderThenLoad(const QString &folder)
{
    showOsd(QStringLiteral("📂 네트워크 폴더 읽는 중: %1").arg(QFileInfo(folder).fileName()), 30000);
    QPointer<AppController> self(this);
    QThreadPool::globalInstance()->start([self, folder] {
        const QStringList files = library::scanVideoFiles(folder);
        QMetaObject::invokeMethod(qApp, [self, folder, files] {
            if (self)
                self->loadPath(folder, files);
        });
    });
}

} // namespace jvp
