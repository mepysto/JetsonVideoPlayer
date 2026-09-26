// 서비스: 스마트폰 웹 리모컨(상태 방송·원격 명령), MPRIS(미디어 키), 대사 검색, 미디어 정보 HUD, YouTube 진입점.
// (파이썬 ui/remote.py, search.py, features.py의 HUD, mpris.py 연결부)
#include "AppController.h"

#include "AiController.h"
#include "DialogueIndex.h"
#include "EventBroker.h"
#include "Mpris.h"
#include "Paths.h"
#include "RemoteAuth.h"
#include "RemoteInfo.h"
#include "RemoteServer.h"
#include "Settings.h"
#include "Storage.h"
#include "SubtitleController.h"
#include "SystemInfo.h"
#include "Thumbnails.h"
#include "YouTubeController.h"

#include <QClipboard>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonObject>
#include <QLoggingCategory>
#include <QQuickWindow>
#include <QThreadPool>
#include <QUrl>

Q_DECLARE_LOGGING_CATEGORY(lcApp)

namespace jvp {

namespace {
constexpr qint64 kSec = 1'000'000'000;
constexpr int kMaxResults = 200;

double round2(double v) { return qRound(v * 100) / 100.0; }

QString formatMs(qint64 ms)
{
    const qint64 s = ms / 1000, h = s / 3600, m = s % 3600 / 60, sec = s % 60;
    return h ? QStringLiteral("%1:%2:%3").arg(h).arg(m, 2, 10, QLatin1Char('0')).arg(sec, 2, 10, QLatin1Char('0'))
             : QStringLiteral("%1:%2").arg(m, 2, 10, QLatin1Char('0')).arg(sec, 2, 10, QLatin1Char('0'));
}

// 검색어 부분을 강조한 HTML (대소문자 무시, 공백은 원문 그대로)
QString highlight(const QString &text, const QString &query)
{
    const QString one = text.simplified();
    const QString q = DialogueIndex::normalize(query);
    const int pos = q.isEmpty() ? -1 : int(one.toCaseFolded().indexOf(q));
    if (pos < 0)
        return one.toHtmlEscaped();
    return one.left(pos).toHtmlEscaped() + QStringLiteral("<b><font color='#e9ff5b'>")
           + one.mid(pos, q.size()).toHtmlEscaped() + QStringLiteral("</font></b>") + one.mid(pos + q.size()).toHtmlEscaped();
}

bool isRemote(const QString &p)
{
    return p.startsWith(QLatin1String("http://")) || p.startsWith(QLatin1String("https://"));
}
} // namespace

// ============================================================================
// RemoteInfo
// ============================================================================

void RemoteInfo::attach(RemoteServer *server, RemoteAuth *auth)
{
    m_server = server;
    m_auth = auth;
    emit changed();
}

QString RemoteInfo::url() const
{
    return m_server && m_server->isListening() ? m_server->url() : QStringLiteral("리모컨 서버를 시작하지 못했습니다");
}

QString RemoteInfo::loginUrl() const { return m_server && m_server->isListening() ? m_server->loginUrl() : QString(); }
QString RemoteInfo::pin() const { return m_auth ? m_auth->pin() : QString(); }
bool RemoteInfo::running() const { return m_server && m_server->isListening(); }

void RemoteInfo::regeneratePin()
{
    if (!m_auth)
        return;
    const QString pin = RemoteAuth::generatePin();
    Settings::instance()->setValue(QStringLiteral("remote_pin"), pin);
    Settings::instance()->save();
    m_auth->reset(pin);
    emit changed();
    if (auto *app = AppController::instance())
        app->showOsd(QStringLiteral("🔐 새 리모컨 PIN: %1 (기존 연결 해제)").arg(pin), 3000);
}

// ============================================================================
// 시작 · 종료
// ============================================================================

void AppController::startServices()
{
    Settings *s = Settings::instance();
    QString pin = s->stringValue(QStringLiteral("remote_pin"));
    static const QRegularExpression fourDigits(QStringLiteral("^\\d{4}$"));
    if (!fourDigits.match(pin).hasMatch()) {
        pin = RemoteAuth::generatePin();
        s->setValue(QStringLiteral("remote_pin"), pin);
        s->save();
    }
    m_remoteAuth = new RemoteAuth(pin, RemoteAuth::defaultTokenFile());
    m_broker = new EventBroker(this);
    m_remoteServer = new RemoteServer(this, m_remoteAuth, m_broker, this);
    m_remoteServer->setLanOnly(s->boolValue(QStringLiteral("remote_lan_only")));
    if (m_remoteServer->start())
        qCInfo(lcApp).noquote() << "📱 [웹 리모컨 서버 활성화] 스마트폰 접속 주소:" << m_remoteServer->url()
                                << QStringLiteral("(PIN %1)").arg(pin);
    else
        qCWarning(lcApp) << "⚠️ 웹 리모컨 서버를 시작하지 못했습니다 (포트 사용 중)";
    m_remoteInfo->attach(m_remoteServer, m_remoteAuth);

    // 키보드 미디어 키 / 시스템 미디어 컨트롤 (MPRIS2)
    m_mpris = new MprisService(this, this);
    if (!m_mpris->start())
        qCInfo(lcApp) << "ℹ️ MPRIS를 시작하지 않았습니다 (세션 버스 없음 또는 이미 실행 중)";

    publishRemoteStatus();
    m_remoteTimer.setInterval(500);
    connect(&m_remoteTimer, &QTimer::timeout, this, &AppController::publishRemoteStatus, Qt::UniqueConnection);
    m_remoteTimer.start();
}

void AppController::stopServices()
{
    m_remoteTimer.stop();
    if (m_broker)
        m_broker->close();
    if (m_remoteServer)
        m_remoteServer->stop();
    if (m_mpris)
        m_mpris->stop();
    m_remoteInfo->attach(nullptr, nullptr);
    delete m_remoteServer;
    m_remoteServer = nullptr;
    delete m_remoteAuth;
    m_remoteAuth = nullptr;
}

QString AppController::remoteUrl() const
{
    return m_remoteServer && m_remoteServer->isListening() ? m_remoteServer->url() : QString();
}

// ============================================================================
// 상태 스냅샷 · 방송
// ============================================================================

void AppController::publishRemoteStatus()
{
    if (m_shuttingDown)
        return;
    if (m_mpris)
        m_mpris->update();
    if (!m_broker)
        return;
    // 방송하는 상태에는 재생목록을 빼고 따로 보냅니다 (위치가 바뀔 때마다 큰 목록을 다시 보내지 않게).
    QJsonObject status = remoteStatus();
    status.remove(QStringLiteral("playlist_groups"));
    m_broker->publish(QStringLiteral("status"), status);
    m_broker->publish(QStringLiteral("playlist"), remotePlaylistGroups());
    QJsonArray positions;
    if (m_thumbIndex)
        for (qint64 p : m_thumbIndex->positions)
            positions.append(round2(double(p) / kSec));
    m_broker->publish(QStringLiteral("thumbs"), QJsonObject{{"positions", positions}, {"video", m_index}});
}

QJsonObject AppController::remoteStatus()
{
    const QString path = currentPath();
    const qint64 pos = m_engine->isOpen() ? qMax<qint64>(0, m_engine->position()) : 0;
    const qint64 dur = m_engine->isOpen() ? qMax<qint64>(0, m_engine->duration()) : 0;

    QJsonArray tracks;
    const auto entries = m_subs->entries();
    const auto active = m_subs->activeIndices();
    for (int i = 0; i < entries.size(); ++i)
        tracks.append(QJsonObject{{"index", i}, {"label", entries[i].label}, {"color", entries[i].color},
                                  {"active", m_subs->enabled() && active.contains(i)}});
    QJsonArray chapterArr;
    for (const auto &c : chapters())
        chapterArr.append(QJsonObject{{"sec", round2(double(c.first) / kSec)}, {"title", c.second}});
    QJsonArray bookmarks;
    if (!path.isEmpty())
        for (const QVariant &v : bookmarkCache().get(path)) {
            const QVariantMap m = v.toMap();
            bookmarks.append(QJsonObject{{"sec", round2(m.value("position_ns").toDouble() / kSec)},
                                         {"label", m.value("label").toString()}});
        }
    const QString chapter = chapters().isEmpty() ? QString() : chapterAt(pos / 1e6);
    const int sleepRemaining = sleepRemainingSec();
    Settings *s = Settings::instance();
    return QJsonObject{
        {"title", path.isEmpty() ? QString() : QFileInfo(path).fileName()},
        {"is_playing", m_playing},
        {"position_sec", round2(double(pos) / kSec)},
        {"duration_sec", round2(double(dur) / kSec)},
        {"volume", m_volume},
        {"is_muted", m_muted},
        {"speed", m_rate},
        {"subtitles_enabled", m_subs->enabled()},
        {"subtitle_offset_ms", m_subs->offsetMs()},
        {"subtitle_tracks", tracks},
        {"embedded_subtitles", m_subs->embeddedCount()},
        {"is_fullscreen", m_fullscreen},
        {"repeat_mode", m_repeatMode},
        {"total_videos", int(m_playlist.size())},
        {"current_index", m_index},
        {"chapter", chapter.isEmpty() ? QJsonValue() : QJsonValue(chapter)},
        {"chapters", chapterArr},
        {"bookmarks", bookmarks},
        {"ab", QJsonObject{{"a", m_abA >= 0 ? QJsonValue(double(m_abA) / kSec) : QJsonValue()},
                           {"b", m_abB >= 0 ? QJsonValue(double(m_abB) / kSec) : QJsonValue()},
                           {"active", m_abActive}}},
        {"audio", QJsonObject{{"current", m_audioTrack + 1}, {"total", m_audioTracks}}},
        {"ai", m_ai->remoteStatus()},
        {"translate", m_translation->remoteStatus()},
        {"sleep", QJsonObject{{"minutes", m_sleepMinutes},
                              {"remaining", sleepRemaining >= 0 ? QJsonValue(sleepRemaining) : QJsonValue()}}},
        {"night_mode", s->boolValue(QStringLiteral("night_mode"))},
        {"loudness", QJsonObject{{"on", s->boolValue(QStringLiteral("loudness_normalize"))},
                                 {"lufs", m_loudnessLufs ? QJsonValue(*m_loudnessLufs) : QJsonValue()},
                                 {"gain_db", qRound(m_loudnessCurrentDb * 10) / 10.0}}},
        {"eq_preset", s->stringValue(QStringLiteral("eq_preset"))},
        {"rotation", m_rotation},
        {"yt_download", m_youtube->remoteStatus()},
        {"playlist_groups", remotePlaylistGroups()},
    };
}

QJsonArray AppController::remotePlaylistGroups()
{
    // 폴더별 재생목록 (재생목록/현재 항목이 바뀔 때만 다시 계산)
    const QString key = m_playlist.join(QLatin1Char('\n')) + QLatin1Char('|') + QString::number(m_index)
                        + QLatin1Char('|') + m_inputPath;
    if (key == m_remoteGroupsKey)
        return m_remoteGroupsCache;
    const QFileInfo root(m_inputPath);
    const QString absRoot = root.isDir() ? root.absoluteFilePath() : QString();
    QStringList order;
    QHash<QString, QJsonArray> groups;
    for (int i = 0; i < m_playlist.size(); ++i) {
        const QString &p = m_playlist[i];
        QString folder;
        if (!absRoot.isEmpty()) {
            const QString rel = QDir(absRoot).relativeFilePath(QFileInfo(p).absolutePath());
            folder = rel == QLatin1String(".") ? QStringLiteral("📁 루트 폴더") : QStringLiteral("📁 ") + rel;
        } else {
            const QString dir = QFileInfo(QFileInfo(p).absolutePath()).fileName();
            folder = dir.isEmpty() ? QStringLiteral("📁 동영상 목록") : QStringLiteral("📁 ") + dir;
        }
        const QString thumbDir = thumbnailCacheDir(p);
        const bool hasThumb = QFileInfo::exists(thumbDir + QStringLiteral("/index.json"));
        if (!groups.contains(folder))
            order << folder;
        groups[folder].append(QJsonObject{{"index", i}, {"name", QFileInfo(p).fileName()}, {"active", i == m_index},
                                          {"watched", resumeCache().progress(p).watched},
                                          {"thumb", hasThumb ? QFileInfo(thumbDir).fileName().left(8) : QString()}});
    }
    QJsonArray out;
    for (const QString &folder : std::as_const(order)) {
        const QJsonArray items = groups.value(folder);
        bool hasActive = false;
        for (const QJsonValue &it : items)
            hasActive |= it.toObject().value("active").toBool();
        out.append(QJsonObject{{"folder", folder}, {"has_active", hasActive}, {"count", items.size()}, {"items", items}});
    }
    m_remoteGroupsKey = key;
    m_remoteGroupsCache = out;
    return out;
}

QString AppController::remoteThumbnailPath(int i)
{
    if (m_thumbIndex && i >= 0 && i < m_thumbIndex->files.size())
        return m_thumbIndex->filePath(i);
    return {};
}

QString AppController::remotePlaylistThumbnailPath(int index)
{
    if (index < 0 || index >= m_playlist.size())
        return {};
    const auto idx = loadThumbnailIndex(m_playlist[index]);
    if (!idx || idx->files.isEmpty())
        return {};
    return idx->filePath(qMin(int(idx->files.size()) - 1, int(idx->files.size()) / 5));
}

QJsonObject AppController::remoteSearch(const QString &query)
{
    // 색인이 오래됐으면 갱신을 시작하고 지금 색인으로 답합니다.
    bool indexing = !m_dialogueIndex || m_indexRunning;
    if (!m_dialogueIndex || m_remoteSearchIndexedFor != m_playlist) {
        m_remoteSearchIndexedFor = m_playlist;
        refreshDialogueIndex();
        indexing = true;
    }
    QJsonArray results;
    if (m_dialogueIndex) {
        const QString current = currentPath();
        for (const SearchHit &h : m_dialogueIndex->search(query, 100, current)) {
            const int i = int(m_playlist.indexOf(h.video));
            if (i < 0)
                continue;
            results.append(QJsonObject{{"index", i}, {"sec", round2(h.startMs / 1000.0)},
                                       {"name", QFileInfo(h.video).fileName()}, {"text", h.text.simplified()},
                                       {"label", h.label}, {"current", h.video == current}});
        }
    }
    return {{"indexing", indexing}, {"results", results}};
}

void AppController::handleRemoteCommand(const QVariantMap &p)
{
    const QString action = p.value("action").toString();
    auto num = [&](const char *k, bool *ok) { return p.value(k).toString().toDouble(ok); };
    bool ok = false;
    // 인자 없는 명령
    static const QHash<QString, void (AppController::*)()> simple{
        {"play_pause", &AppController::togglePlayPause}, {"next", &AppController::playNext},
        {"prev", &AppController::playPrevious}, {"mute", &AppController::toggleMute},
        {"fullscreen", &AppController::toggleFullscreen}, {"subtitles", &AppController::toggleSubtitles},
        {"repeat", &AppController::cycleRepeatMode}, {"screenshot", &AppController::captureScreenshot},
        {"speed_reset", &AppController::resetRate}, {"ab_a", &AppController::setAbRepeatA},
        {"ab_b", &AppController::setAbRepeatB}, {"ab_clear", &AppController::clearAbRepeat},
        {"bookmark_add", &AppController::addBookmark}, {"audio_cycle", &AppController::cycleAudioTrack},
        {"ai_subtitles", &AppController::startAiSubtitles}, {"translate", &AppController::startTranslation},
        {"night", &AppController::toggleNightMode}, {"rotate", &AppController::cycleRotation},
        {"loudness", &AppController::toggleLoudness}, {"yt_cancel", &AppController::cancelYoutube},
    };
    if (auto fn = simple.value(action)) {
        (this->*fn)();
    } else if (action == QLatin1String("sub_sync_reset")) {
        m_subs->resetSync();
    } else if (action == QLatin1String("speed")) {
        const double v = num("val", &ok);
        if (ok) setRate(v);
    } else if (action == QLatin1String("speed_step")) {
        const double v = num("delta", &ok);
        if (ok) stepRate(v);
    } else if (action == QLatin1String("seek")) {
        const double v = num("delta", &ok);
        if (ok) seekRelative(v);
    } else if (action == QLatin1String("seek_to")) {
        const double v = num("percent", &ok);
        if (ok) seekToPercent(v);
    } else if (action == QLatin1String("seek_abs")) {
        const double v = num("sec", &ok);
        if (ok) seekTo(qint64(qMax(0.0, v) * kSec), SeekMode::Accurate);
    } else if (action == QLatin1String("volume")) {
        const double v = num("val", &ok);
        if (ok) setVolume(v);
    } else if (action == QLatin1String("eq")) {
        setEqPreset(p.value("val").toString());
    } else if (action == QLatin1String("play_at")) {
        bool ok2 = false;
        const int i = int(num("index", &ok));
        const double sec = num("sec", &ok2);
        if (ok && ok2 && i >= 0 && i < m_playlist.size())
            jumpToDialogue(m_playlist[i], qMax(0.0, sec) * 1000);
    } else if (action == QLatin1String("play_index")) {
        const int i = int(num("index", &ok));
        if (ok) playIndex(i);
    } else if (action == QLatin1String("queue_next")) {
        const int i = int(num("index", &ok));
        if (ok && i >= 0 && i < m_playlist.size())
            queueNext(m_playlist[i]);
    } else if (action == QLatin1String("sub_toggle_track")) {
        const int i = int(num("index", &ok));
        if (ok && i >= 0 && i < m_subs->entries().size()) {
            m_subs->toggleTrack(i);
            const bool on = m_subs->enabled() && m_subs->activeIndices().contains(i);
            showOsd(QStringLiteral("💬 %1 %2").arg(m_subs->entries()[i].label.left(30), on ? "ON" : "OFF"));
        }
    } else if (action == QLatin1String("sub_sync")) {
        const int d = int(num("delta", &ok));
        if (ok) m_subs->adjustSync(d);
    } else if (action == QLatin1String("sleep")) {
        const int m = int(num("minutes", &ok));
        if (ok) setSleepTimer(m);
    } else if (action == QLatin1String("yt") || action == QLatin1String("yt_download") || action == QLatin1String("yt_stream")) {
        const QString url = p.value("url").toString();
        if (!url.isEmpty())
            startYoutube(url, p.value("quality").toString().isEmpty() ? QStringLiteral("best") : p.value("quality").toString());
    } else if (action == QLatin1String("yt_remove")) {
        const QString url = p.value("url").toString();
        if (!url.isEmpty())
            m_youtube->cancelPending(url);
    } else if (action == QLatin1String("open_location")) {
        const int i = int(num("index", &ok));
        openLocation(ok && i >= 0 && i < m_playlist.size() ? m_playlist[i] : QString());
    }
    publishRemoteStatus();
}

// ============================================================================
// MPRIS
// ============================================================================

bool AppController::mprisHasMedia() const { return !m_playlist.isEmpty() && m_engine->isOpen(); }

QString AppController::mprisArtPath() const
{
    if (!m_thumbIndex || m_thumbIndex->files.isEmpty())
        return {};
    return m_thumbIndex->filePath(qMin(int(m_thumbIndex->files.size()) - 1, int(m_thumbIndex->files.size()) / 5));
}

void AppController::mprisRaise()
{
    if (m_window) {
        m_window->show();
        m_window->raise();
        m_window->requestActivate();
    }
}

// ============================================================================
// 대사 검색
// ============================================================================

void AppController::refreshDialogueIndex()
{
    // 현재 재생목록으로 색인을 백그라운드에서 갱신합니다 (바뀐 자막만 다시 읽음).
    if (!m_dialogueIndex)
        m_dialogueIndex = std::make_unique<DialogueIndex>();
    if (m_indexRunning) {
        m_indexAgain = true;
        return;
    }
    QStringList videos;
    for (const QString &p : std::as_const(m_playlist))
        if (!isRemote(p))
            videos << p;
    m_indexRunning = true;
    m_indexAgain = false;
    DialogueIndex *index = m_dialogueIndex.get();
    QPointer<AppController> self(this);
    QThreadPool::globalInstance()->start([self, index, videos] {
        index->build(videos, [self] { return !self || self->m_shuttingDown; });
        QMetaObject::invokeMethod(qApp, [self] {
            if (!self)
                return;
            self->m_indexRunning = false;
            if (self->m_indexAgain) {
                self->refreshDialogueIndex();
                return;
            }
            emit self->dialogueIndexReady();
        });
    });
}

QVariantList AppController::searchDialogue(const QString &query)
{
    QVariantList out;
    if (!m_dialogueIndex || DialogueIndex::normalize(query).isEmpty())
        return out;
    const QString current = currentPath();
    for (const SearchHit &h : m_dialogueIndex->search(query, kMaxResults, current))
        out << QVariantMap{{"video", h.video}, {"startMs", double(h.startMs)}, {"time", formatMs(h.startMs)},
                           {"name", QFileInfo(h.video).fileName().toHtmlEscaped()}, {"current", h.video == current},
                           {"html", highlight(h.text, query)}, {"label", h.label}};
    return out;
}

QString AppController::dialogueSearchStatus(const QString &query, int count) const
{
    if (m_indexRunning && !m_dialogueIndex)
        return QStringLiteral("🔎 자막 색인 중...");
    const int lines = m_dialogueIndex ? m_dialogueIndex->lineCount() : 0;
    if (DialogueIndex::normalize(query).isEmpty()) {
        if (m_indexRunning && lines == 0)
            return QStringLiteral("🔎 자막 색인 중...");
        return lines ? QStringLiteral("영상 %1개 · 대사 %2줄 색인됨").arg(m_playlist.size()).arg(lines)
                     : QStringLiteral("자막이 있는 영상이 없습니다.");
    }
    if (count == 0)
        return QStringLiteral("찾은 대사가 없습니다.");
    return QStringLiteral("%1%2개 찾음").arg(count).arg(count >= kMaxResults ? "+" : "");
}

void AppController::jumpToDialogue(const QString &video, double startMs)
{
    // 대사 0.5초 전부터: 같은 영상이면 탐색, 다른 영상이면 그 위치부터 재생
    const qint64 target = qMax<qint64>(0, qint64(startMs) - 500) * 1'000'000;
    if (video == currentPath() && m_engine->isOpen()) {
        seekTo(target, SeekMode::Accurate);
        if (!m_playing)
            togglePlayPause();
    } else if (m_playlist.contains(video)) {
        cancelAutoplay();
        m_index = int(m_playlist.indexOf(video));
        playCurrent(0, target);
    } else {
        showOsd(QStringLiteral("⚠️ 재생목록에 없는 영상입니다."));
        return;
    }
    showOsd(QStringLiteral("🔎 %1 · %2").arg(QFileInfo(video).fileName().left(40), formatMs(qint64(startMs))));
}

// ============================================================================
// HUD
// ============================================================================

void AppController::updateHud()
{
    const QString path = currentPath();
    const QString decoder = m_engine->activeVideoDecoder();
    const QString hw = decoder.isEmpty() ? QString()
                       : decoder.contains(QLatin1String("nvv4l2")) ? QStringLiteral("⚡ NVDEC 하드웨어 가속")
                                                                   : QStringLiteral("💻 소프트웨어 디코딩");
    const auto entries = m_subs->entries();
    const QString subInfo = entries.isEmpty() ? QStringLiteral("없음")
                            : QStringLiteral("%1/%2개 활성").arg(m_subs->activeIndices().size()).arg(entries.size());
    const QSize vs = m_engine->videoSize();
    QStringList lines{
        QStringLiteral("<b>[Jetson 미디어 및 시스템 모니터링]</b>"),
        QStringLiteral("📁 <b>파일:</b> %1").arg((path.isEmpty() ? QStringLiteral("없음") : QFileInfo(path).fileName()).toHtmlEscaped()),
        QStringLiteral("🚀 <b>디코더:</b> %1 (%2)").arg(decoder.isEmpty() ? QStringLiteral("감지 중...") : decoder, hw),
        QStringLiteral("🖼️ <b>해상도:</b> %1×%2 · %3").arg(vs.width()).arg(vs.height())
            .arg(m_engine->usingHwOutput() ? QStringLiteral("NVMM 직접 출력 (복사 없음)") : QStringLiteral("시스템 메모리 업로드")),
        QStringLiteral("⏱️ <b>재생:</b> %1 / %2 (속도: %3x)").arg(positionText(), durationText()).arg(m_rate, 0, 'f', 2),
        QStringLiteral("📊 <b>렌더링 프레임:</b> %1").arg(m_engine->frameBridge()->renderedFrames()),
        QStringLiteral("💬 <b>자막:</b> %1").arg(subInfo),
        QStringLiteral("🎵 <b>오디오:</b> 트랙 %1/%2").arg(m_audioTrack + 1).arg(qMax(1, m_audioTracks)),
    };
    if (!m_hdrTransfer.isEmpty())
        lines << QStringLiteral("🌈 <b>HDR:</b> %1 — %2")
                     .arg(m_hdrTransfer == QLatin1String("pq") ? QStringLiteral("HDR10 (PQ)") : QStringLiteral("HLG"),
                          m_hdrMode.isEmpty() ? QStringLiteral("톤매핑 꺼짐") : QStringLiteral("톤매핑 중"));
    const QVariantMap st = SystemInfo::hwStats();
    if (st.contains("cpu_temp") || st.contains("gpu_temp")) {
        QString t;
        if (st.contains("cpu_temp"))
            t += QStringLiteral("CPU %1°C  ").arg(st.value("cpu_temp").toDouble(), 0, 'f', 1);
        if (st.contains("gpu_temp"))
            t += QStringLiteral("GPU %1°C").arg(st.value("gpu_temp").toDouble(), 0, 'f', 1);
        lines << QStringLiteral("🌡️ <b>SoC 온도:</b> %1").arg(t.trimmed());
    }
    if (st.contains("gpu_load"))
        lines << QStringLiteral("⚡ <b>GPU 로드:</b> %1%").arg(st.value("gpu_load").toDouble(), 0, 'f', 1);
    if (st.contains("ram_used_gb"))
        lines << QStringLiteral("💾 <b>시스템 RAM:</b> %1GB / %2GB (%3%)")
                     .arg(st.value("ram_used_gb").toDouble(), 0, 'f', 1)
                     .arg(st.value("ram_total_gb").toDouble(), 0, 'f', 1)
                     .arg(qRound(st.value("ram_percent").toDouble()));
    if (!remoteUrl().isEmpty())
        lines << QStringLiteral("📱 <b>웹 리모컨:</b> %1").arg(remoteUrl());
    m_hudText = lines.join(QStringLiteral("<br>"));
    emit hudChanged();
}

// ============================================================================
// YouTube (자세한 동작은 YouTubeController)
// ============================================================================

QString AppController::clipboardYoutubeUrl() const
{
    const QString t = QGuiApplication::clipboard()->text().trimmed();
    return YouTubeController::isYoutubeUrl(t) ? t : QString();
}

void AppController::startYoutube(const QString &url, const QString &quality)
{
    if (!YouTubeController::isYoutubeUrl(url)) {
        showOsd(QStringLiteral("⚠️ YouTube 주소가 아닙니다."));
        return;
    }
    m_youtube->start(url, quality);
}

void AppController::cancelYoutube() { m_youtube->cancelCurrent(); }

bool AppController::youtubeLoading() const { return m_youtube->loading(); }

QVariantMap AppController::youtubeState() const { return m_youtube->state(); }

} // namespace jvp
