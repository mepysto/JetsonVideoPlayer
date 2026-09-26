// 재생 정책: 영상 열기(이어보기·HW 경로 판별), 오류 시 재시도/폴백, 끝났을 때 다음 영상, 진행 표시,
// A-B 구간 반복, 북마크, 챕터·썸네일·장면 분석, 수면 타이머, 자동 재생 카운트다운, 회전, HDR, 오디오 효과.
// (파이썬 ui/playback.py, controls.py, features.py, viewing.py, timeline.py, audio.py)
#include "AppController.h"

#include "AiController.h"
#include "Loudness.h"
#include "MediaProbe.h"
#include "PlaylistModel.h"
#include "Settings.h"
#include "Storage.h"
#include "SubtitleController.h"
#include "SubtitleParse.h"

#include <QDir>
#include <QFileInfo>
#include <QLoggingCategory>
#include <QRandomGenerator>
#include <QUrl>

Q_DECLARE_LOGGING_CATEGORY(lcApp)

namespace jvp {

namespace {
constexpr qint64 kMs = 1'000'000;
constexpr qint64 kSec = 1'000'000'000;
constexpr int kSleepFadeSec = 20;

bool isRemote(const QString &p)
{
    return p.startsWith(QLatin1String("http://")) || p.startsWith(QLatin1String("https://"));
}

struct EqPreset { const char *key; const char *name; QList<double> gains; };
const QList<EqPreset> &eqPresetTable()
{
    // equalizer-10bands 대역: 29, 59, 119, 237, 474, 947, 1889, 3770, 7523, 15011 Hz (dB)
    static const QList<EqPreset> t{
        {"flat", "기본", {0, 0, 0, 0, 0, 0, 0, 0, 0, 0}},
        {"dialogue", "대사 강조", {-6, -5, -3, -1, 1, 3, 4, 3, 0, -2}},
        {"bass", "저음 강화", {6, 5, 4, 2, 0, 0, 0, 0, 0, 0}},
        {"treble", "고음 강화", {0, 0, 0, 0, 0, 1, 2, 4, 5, 6}},
        {"quiet", "작은 볼륨 청취", {-8, -6, -3, 0, 1, 2, 2, 1, 0, -2}},
    };
    return t;
}
const EqPreset &eqPreset(const QString &key)
{
    for (const EqPreset &p : eqPresetTable())
        if (key == QLatin1String(p.key))
            return p;
    return eqPresetTable().first();
}

const QList<QPair<QString, QString>> &rotations()
{
    static const QList<QPair<QString, QString>> r{
        {"identity", "원래대로"}, {"90r", "시계 방향 90°"}, {"180", "180°"},
        {"90l", "반시계 방향 90°"}, {"horiz", "좌우 반전"}, {"vert", "상하 반전"}};
    return r;
}

const QList<QPair<int, QString>> &sleepChoices()
{
    static const QList<QPair<int, QString>> c{
        {0, "끄기"}, {15, "15분 후"}, {30, "30분 후"}, {60, "60분 후"}, {-1, "현재 영상이 끝나면"}};
    return c;
}
} // namespace

// ============================================================================
// 영상 열기
// ============================================================================

void AppController::playCurrent(qint64 startNs, std::optional<qint64> openAtNs)
{
    if (m_playlist.isEmpty() || m_index < 0 || m_index >= m_playlist.size())
        return;
    QString path = m_playlist[m_index];

    // 삭제/이동된 파일은 건너뛰고, 있는 다음 영상을 재생합니다.
    if (!isRemote(path) && !QFileInfo::exists(path)) {
        qCWarning(lcApp).noquote() << "⚠️ 파일을 찾을 수 없습니다:" << path;
        const int n = int(m_playlist.size());
        for (int step = 1; step < n; ++step) {
            const int cand = (m_index + step) % n;
            if (QFileInfo::exists(m_playlist[cand])) {
                showOsd(QStringLiteral("⚠️ 파일이 없어 건너뜁니다: %1").arg(QFileInfo(path).fileName().left(40)), 3000);
                m_index = cand;
                playCurrent();
                return;
            }
        }
        showOsd(QStringLiteral("❌ 재생목록의 파일을 찾을 수 없습니다."), 4000);
        return;
    }

    historyCache().add(path);
    const bool newVideo = startNs == 0;
    if (newVideo)
        resetAbRepeat(false);

    // NVDEC 가능 여부를 미리 판별: 불가능한 형식은 처음부터 소프트웨어 경로로 (첫 프레임 실패 후 재시작 끊김 방지)
    m_hwExpected.reset();
    if (!isRemote(path)) {
        const probe::HwSupport hw = probe::checkHwSupport(path);
        m_hwExpected = hw.supported;
        if (hw.supported == false)
            qCInfo(lcApp).noquote() << "ℹ️ [코덱 상태]" << QFileInfo(path).fileName() << ":" << hw.reason
                                    << "→ 소프트웨어 디코딩으로 재생합니다";
    }

    if (newVideo) {
        const auto [savedPos, savedDur] = resumeCache().get(path);
        Q_UNUSED(savedDur)
        if (openAtNs) {
            startNs = qMax<qint64>(0, *openAtNs);
        } else if (savedPos > 0) {
            startNs = savedPos;
            showOsd(QStringLiteral("⏱️ 이어서 재생: %1").arg(formatTime(savedPos / 1e6)));
            qCInfo(lcApp).noquote() << "⏱️ [이어보기]" << formatTime(savedPos / 1e6) << "지점부터 재생합니다.";
        }
        qCInfo(lcApp).noquote() << QStringLiteral("▶ [%1/%2] 재생 중:").arg(m_index + 1).arg(m_playlist.size())
                                << (isRemote(path) ? QStringLiteral("▶ YouTube / 온라인 스트림") : QFileInfo(path).fileName());
        m_durationNs = 0;
        m_lastUiSecond = -1;
        m_tocChapters.clear();
        startThumbnails(path);
        startLoudnessFor(path);
        m_ai->cancel();
        m_translation->cancel();
        cancelAutoplay();
        m_rotation = QStringLiteral("identity");
        m_subs->loadForVideo(isRemote(path) ? QString() : path);
        m_playlistModel->setActiveIndex(m_index);
        m_playlistModel->refreshProgress();
        refreshTimelineMarks();
        emit chaptersChanged();
    }

    m_pendingStartNs = startNs;
    // 이전 영상의 위치가 남아 있으면 HW 경로 실패 시 엉뚱한 위치에서 다시 시작합니다.
    m_lastPosNs = startNs;
    m_restartScheduled = false;
    m_subs->resetEmbedded({}, 0);
    m_hdrTransfer.clear();
    m_hdrMode.clear();

    PlayerEngine::OpenOptions opt;
    opt.hwOutput = !m_hwOutputDisabled.contains(path) && m_hwExpected != false
                   && qEnvironmentVariable("JVP_HW_VIDEO", "1") != QLatin1String("0");
    opt.startNs = startNs;
    opt.passthrough = usePassthroughFor(path);
    if (opt.passthrough && !qFuzzyCompare(m_rate, 1.0)) {
        m_rate = 1.0;
        emit playbackChanged();
    }
    opt.rate = m_rate;
    opt.keepAssRaw = Settings::instance()->boolValue(QStringLiteral("subtitle_ass_styles"));
    opt.avOffsetMs = m_avOffsetMs;
    const QString uri = isRemote(path) ? path : QUrl::fromLocalFile(QFileInfo(path).absoluteFilePath()).toString();
    if (!m_engine->open(uri, opt))
        qCWarning(lcApp).noquote() << "❌ 파이프라인을 만들지 못했습니다:" << path;
    applyVolumeToEngine();
    // 효과 요소는 파이프라인마다 새로 만들어지므로 현재 값을 다시 넣습니다.
    applyEqPreset();
    m_engine->setNightMode(Settings::instance()->boolValue(QStringLiteral("night_mode")));
    m_engine->setLoudnessGainDb(m_loudnessCurrentDb);
    m_playing = true;
    emit mediaChanged();
    emit playbackChanged();
    emit positionChanged();
    emit viewChanged();
}

void AppController::schedulePlayCurrent(int delayMs)
{
    QTimer::singleShot(delayMs, this, [this] { playCurrent(); });
}

void AppController::restartCurrent(qint64 atNs, int delayMs)
{
    m_restartScheduled = true;
    QTimer::singleShot(delayMs, this, [this, atNs] { playCurrent(atNs); });
}

bool AppController::seekTo(qint64 ns, SeekMode mode)
{
    // 배속을 유지한 채 이동합니다 (seek_simple은 배속을 1.0으로 되돌리므로 모든 탐색은 이 함수를 거칩니다).
    if (!m_engine->isOpen() || ns < 0)
        return false;
    m_lastPosNs = ns;
    const bool ok = m_engine->seek(ns, mode);
    emit positionChanged();
    return ok;
}

// ============================================================================
// 엔진 이벤트
// ============================================================================

void AppController::onEngineAsyncDone()
{
    m_pendingStartNs = 0;
    onStreamsChanged();
    updateHdr();
    if (m_durationNs <= 0) {
        const qint64 d = m_engine->duration();
        if (d > 0) {
            m_durationNs = d;
            refreshTimelineMarks();
            emit positionChanged();
        }
    }
}

void AppController::onStreamsChanged()
{
    m_audioTracks = m_engine->audioTrackCount();
    m_audioTrack = qMax(0, m_engine->currentAudioTrack());
    const int nText = m_engine->textTrackCount();
    if (nText != m_subs->embeddedCount()) {
        QStringList langs;
        for (int i = 0; i < nText; ++i)
            langs << m_engine->textTrackLanguage(i);
        m_subs->setEmbeddedTracks(langs, qMax(0, m_engine->currentTextTrack()));
    }
}

void AppController::onChaptersFound(const QVariantList &chapters)
{
    QList<QPair<qint64, QString>> found;
    for (const QVariant &v : chapters) {
        const QVariantMap m = v.toMap();
        found.append({m.value("ns").toLongLong(), m.value("title").toString()});
    }
    std::sort(found.begin(), found.end(), [](const auto &a, const auto &b) { return a.first < b.first; });
    m_tocChapters = found;
    qCInfo(lcApp) << "📑 [챕터]" << found.size() << "개 (컨테이너 TOC)";
    refreshTimelineMarks();
    emit chaptersChanged();
}

void AppController::onEnginePlayingChanged(bool playing)
{
    m_playing = playing;
    if (playing && m_eosAt.isValid()) {
        qCInfo(lcApp) << "⏭ [전환 시간] 앞 영상 끝 → 다음 영상 재생" << m_eosAt.elapsed() << "ms";
        m_eosAt.invalidate();
    }
    emit playbackChanged();
}

void AppController::onEngineEos()
{
    m_eosAt.start();
    const QString path = currentPath();
    if (path.isEmpty())
        return;
    m_retryCounts.remove(path);
    // 재생 완료: 이어보기 위치를 지우고 시청 완료(✓)로 표시
    resumeCache().markCompleted(path, m_durationNs);
    resumeCache().save();
    m_playlistModel->refreshProgress();

    if (m_sleepMinutes == -1) {   // "현재 영상이 끝나면" 수면 타이머
        m_sleepMinutes = 0;
        sleepNow();
        return;
    }
    int next = popQueuedIndex();   // "다음에 재생" 대기열이 반복 모드보다 우선
    if (next < 0) {
        if (m_repeatMode == QLatin1String("one") || m_singleFile) {
            qCInfo(lcApp) << "🔄 1곡 반복: 처음부터 다시 재생합니다.";
            QTimer::singleShot(10, this, [this] { playCurrent(); });
            return;
        }
        if (m_repeatMode == QLatin1String("shuffle") && m_playlist.size() > 1) {
            next = randomOtherIndex();
        } else if (m_repeatMode == QLatin1String("none")) {
            if (m_index + 1 >= m_playlist.size()) {
                qCInfo(lcApp) << "⏹ 모든 영상 재생 완료 (순차 재생 정지).";
                m_engine->pause();
                return;
            }
            next = m_index + 1;
        } else {
            next = (m_index + 1) % int(m_playlist.size());
        }
    }
    startAutoplayCountdown(next);
}

void AppController::onEngineError(const QString &message, const QString &debug, bool fromPassthrough)
{
    qCWarning(lcApp).noquote() << "❌ 재생 중 에러 발생:" << message;
    if (!debug.isEmpty())
        qCWarning(lcApp).noquote() << "   GStreamer:" << debug;
    const QString path = currentPath();
    if (path.isEmpty() || m_restartScheduled)
        return;   // 같은 파이프라인이 연달아 내는 후속 오류 (이미 다시 시작 예약됨)
    const QString name = QFileInfo(path).fileName().left(40);
    const qint64 restartNs = m_pendingStartNs > 0 ? m_pendingStartNs : m_lastPosNs;
    if ((fromPassthrough || m_engine->passthroughActive()) && !m_passthroughFailed.contains(path)) {
        // 사운드 서버/수신기가 원음을 받지 못함 → 이 파일은 일반(디코딩) 경로로 다시 재생
        qCInfo(lcApp) << "↩️ HDMI 패스스루 실패 — 디코딩해서 다시 재생합니다.";
        m_passthroughFailed.insert(path);
        restartCurrent(restartNs, 100);
        return;
    }
    if (m_engine->usingHwOutput() && !m_hwOutputDisabled.contains(path)) {
        // HW 출력 경로(nvvidconv NVMM)가 이 영상을 처리하지 못함 → 호환(소프트웨어) 경로로 즉시 재시도
        qCInfo(lcApp) << "↩️ HW 영상 출력 경로 실패 — 호환 경로로 다시 재생합니다.";
        m_hwOutputDisabled.insert(path);
        restartCurrent(restartNs, 100);
        return;
    }
    const int retries = m_retryCounts.value(path);
    if (retries < kMaxRetries) {
        m_retryCounts[path] = retries + 1;
        qCInfo(lcApp) << "🔄 재생 파이프라인 재시도" << retries + 1 << "/" << kMaxRetries;
        showOsd(QStringLiteral("⚠️ 재생 오류 — 다시 시도 중 (%1/%2)").arg(retries + 1).arg(kMaxRetries), 2500);
        m_restartScheduled = true;
        QTimer::singleShot(250, this, [this] { playCurrent(); });
    } else if (m_singleFile || m_playlist.size() <= 1) {
        qCInfo(lcApp) << "⏹ 반복 오류로 재생을 중단합니다. 원본과 디코더 로그를 확인하세요.";
        showOsd(QStringLiteral("❌ 재생할 수 없는 영상입니다: %1").arg(name), 5000);
        m_engine->pause();
    } else {
        qCInfo(lcApp) << "⏭ 반복 오류 항목을 건너뜁니다.";
        showOsd(QStringLiteral("⏭ 재생 실패로 건너뜁니다: %1").arg(name), 3500);
        playNext();
    }
}

void AppController::onPositionTick()
{
    if (!m_engine->isOpen())
        return;
    const qint64 pos = m_engine->position();
    if (pos > 0) {
        m_lastPosNs = pos;
        // A-B 구간 반복
        if (m_abActive && m_abA >= 0 && m_abB >= 0 && pos >= m_abB) {
            seekTo(m_abA, SeekMode::Accurate);
            return;
        }
        if (!currentPath().isEmpty())
            resumeCache().set(currentPath(), pos, m_durationNs);
    }
    if (m_durationNs <= 0) {
        const qint64 d = m_engine->duration();
        if (d > 0) {
            m_durationNs = d;
            refreshTimelineMarks();
            m_ai->maybeAutoStart();
        }
    }
    emit positionChanged();
    applySleepFade();
    if (m_hudVisible && m_ticks % 4 == 0)
        updateHud();
    ++m_ticks;
}

// ============================================================================
// 기본 조작
// ============================================================================

void AppController::togglePlayPause()
{
    if (!m_engine->isOpen())
        return;
    if (m_playing) {
        m_engine->pause();
        m_playing = false;
        showOsd(QStringLiteral("⏸ 일시 정지"));
    } else {
        m_engine->play();
        m_playing = true;
        showOsd(QStringLiteral("▶ 재생"));
    }
    emit playbackChanged();
}

void AppController::seekRelative(double seconds)
{
    if (!m_engine->isOpen())
        return;
    qint64 pos = m_engine->position();
    if (pos < 0) {
        qCWarning(lcApp) << "⚠️ 현재 재생 위치를 확인할 수 없어 탐색에 실패했습니다.";
        return;
    }
    qint64 target = qMax<qint64>(0, pos + qint64(seconds * kSec));
    if (m_durationNs > 0)
        target = qMin(target, m_durationNs);
    if (!seekTo(target, SeekMode::Accurate)) {
        qCWarning(lcApp) << "⚠️ 탐색 실패로 파이프라인을 재구축합니다.";
        playCurrent(target);
        return;
    }
    const QString dur = m_durationNs > 0 ? QStringLiteral(" / ") + formatTime(m_durationNs / 1e6) : QString();
    showOsd(QStringLiteral("%1%2초 (%3%4)").arg(seconds > 0 ? "⏩ +" : "⏪ -").arg(qAbs(seconds)).arg(formatTime(target / 1e6), dur));
}

void AppController::scrubTo(double ratio)
{
    if (m_durationNs <= 0)
        return;
    m_scrubTarget = qint64(m_durationNs * qBound(0.0, ratio, 1.0));
    m_lastPosNs = m_scrubTarget;
    if (!m_scrubTimer.isActive())
        m_scrubTimer.start();
    emit positionChanged();
}

void AppController::seekToRatio(double ratio)
{
    m_scrubTimer.stop();
    m_scrubTarget = m_scrubLast = -1;
    if (!m_engine->isOpen() || m_durationNs <= 0)
        return;
    const qint64 target = qint64(m_durationNs * qBound(0.0, ratio, 1.0));
    seekTo(target, SeekMode::Accurate);
    showOsd(QStringLiteral("⏱️ %1 / %2").arg(formatTime(target / 1e6), formatTime(m_durationNs / 1e6)));
}

void AppController::seekToPercent(double pct)
{
    const qint64 d = m_engine->duration();
    if (d > 0)
        seekTo(qint64(d * qBound(0.0, pct, 100.0) / 100.0), SeekMode::Accurate);
}

void AppController::jumpToMs(double ms)
{
    seekTo(qint64(ms * kMs), SeekMode::Accurate);
}

void AppController::frameStep(int direction)
{
    if (!m_engine->isOpen())
        return;
    if (m_playing)
        togglePlayPause();
    m_engine->stepFrame(direction);
    showOsd(direction > 0 ? QStringLiteral("⏵ 다음 프레임") : QStringLiteral("⏴ 이전 프레임"), 600);
}

void AppController::setRate(double rate)
{
    if (m_engine->passthroughActive() && qRound(rate * 100) != 100) {
        showOsd(QStringLiteral("🔈 HDMI 패스스루 중에는 재생 속도를 바꿀 수 없습니다"));
        return;
    }
    m_rate = qRound(qBound(0.25, rate, 3.0) * 100) / 100.0;
    if (m_engine->isOpen() && !m_engine->setRate(m_rate))
        qCWarning(lcApp) << "⚠️ 재생 속도" << m_rate << "x 설정 실패";
    emit playbackChanged();
    showOsd(QStringLiteral("⚡ 속도: %1x").arg(m_rate, 0, 'f', 2));
}

void AppController::stepRate(double delta) { setRate(m_rate + delta); }

void AppController::applyVolumeToEngine()
{
    double v = m_muted ? 0.0 : m_volume / 100.0;
    if (m_sleepFading && !m_muted) {
        const int remaining = sleepRemainingSec();
        v = m_sleepFadeBase * qMax(0.0, remaining / double(kSleepFadeSec));
    }
    m_engine->setVolume(v);
}

void AppController::setVolume(double percent)
{
    m_volume = qBound(0, int(qRound(percent)), 200);
    if (m_muted && m_volume > 0)
        m_muted = false;
    applyVolumeToEngine();
    emit playbackChanged();
    if (!m_muted)
        showOsd(QStringLiteral("🔊 볼륨: %1%%2").arg(m_volume).arg(m_volume > 100 ? QStringLiteral(" (부스트)") : QString()));
}

void AppController::stepVolume(int delta) { setVolume(m_volume + delta); }

void AppController::toggleMute()
{
    if (!m_muted) {
        m_preMuteVolume = m_volume;
        m_muted = true;
        applyVolumeToEngine();
        emit playbackChanged();
        showOsd(QStringLiteral("🔇 음소거"));
    } else {
        m_muted = false;
        setVolume(m_preMuteVolume > 0 ? m_preMuteVolume : 50);
    }
}

int AppController::randomOtherIndex() const
{
    const int n = int(m_playlist.size());
    int i = m_index;
    while (n > 1 && i == m_index)
        i = QRandomGenerator::global()->bounded(n);
    return i;
}

int AppController::popQueuedIndex()
{
    while (!m_queue.isEmpty()) {
        const QString p = m_queue.takeFirst();
        const int i = int(m_playlist.indexOf(p));
        if (i >= 0) {
            m_playlistModel->setQueue(m_queue);
            return i;
        }
    }
    m_playlistModel->setQueue(m_queue);
    return -1;
}

void AppController::playNext()
{
    if (m_playlist.isEmpty())
        return;
    cancelAutoplay();
    const int queued = popQueuedIndex();
    if (queued >= 0) {
        m_index = queued;
        qCInfo(lcApp) << "⏭ 대기열의 다음 영상을 재생합니다.";
    } else if (m_singleFile) {
        // 그대로 처음부터
    } else if (m_repeatMode == QLatin1String("shuffle") && m_playlist.size() > 1) {
        m_index = randomOtherIndex();
    } else {
        m_index = (m_index + 1) % int(m_playlist.size());
        qCInfo(lcApp) << "⏭ 다음 영상으로 넘어갑니다.";
    }
    schedulePlayCurrent(m_singleFile ? 10 : 50);
}

void AppController::playPrevious()
{
    if (m_playlist.isEmpty())
        return;
    cancelAutoplay();
    if (m_singleFile) {
    } else if (m_repeatMode == QLatin1String("shuffle") && m_playlist.size() > 1) {
        m_index = randomOtherIndex();
    } else {
        m_index = (m_index - 1 + int(m_playlist.size())) % int(m_playlist.size());
        qCInfo(lcApp) << "⏮ 이전 영상으로 넘어갑니다.";
    }
    schedulePlayCurrent(m_singleFile ? 10 : 50);
}

void AppController::playIndex(int index)
{
    if (index < 0 || index >= m_playlist.size())
        return;
    cancelAutoplay();
    m_index = index;
    playCurrent();
}

void AppController::queueNext(const QString &path)
{
    if (m_queue.contains(path))
        return;
    m_queue << path;
    m_playlistModel->setQueue(m_queue);
    showOsd(QStringLiteral("⏭ 다음에 재생 (%1번째): %2").arg(m_queue.size()).arg(QFileInfo(path).fileName().left(30)));
}

void AppController::unqueue(const QString &path)
{
    if (m_queue.removeAll(path)) {
        m_playlistModel->setQueue(m_queue);
        showOsd(QStringLiteral("대기열에서 제거했습니다."));
    }
}

void AppController::cycleRepeatMode()
{
    static const QStringList modes{"all", "one", "none", "shuffle"};
    const int i = int(modes.indexOf(m_repeatMode));
    setRepeatMode(modes[(i + 1) % modes.size()]);
}

void AppController::setRepeatMode(const QString &mode)
{
    static const QStringList modes{"all", "one", "none", "shuffle"};
    m_repeatMode = modes.contains(mode) ? mode : QStringLiteral("all");
    emit playbackChanged();
    showOsd(repeatModeLabel());
}

void AppController::cycleAudioTrack()
{
    if (!m_engine->isOpen())
        return;
    m_audioTracks = m_engine->audioTrackCount();
    if (m_audioTracks <= 1) {
        showOsd(QStringLiteral("🎵 오디오 트랙: 단일 트랙"));
        return;
    }
    setAudioTrack((qMax(0, m_engine->currentAudioTrack()) + 1) % m_audioTracks);
}

void AppController::setAudioTrack(int index)
{
    if (!m_engine->isOpen())
        return;
    m_engine->setAudioTrack(index);
    m_audioTrack = index;
    showOsd(QStringLiteral("🎵 오디오 트랙 %1/%2").arg(index + 1).arg(qMax(1, m_audioTracks)));
    qCInfo(lcApp) << "🎵 [오디오 트랙 변경] 트랙" << index + 1 << "/" << qMax(1, m_audioTracks);
}

void AppController::adjustAvSync(int deltaMs)
{
    m_avOffsetMs += deltaMs;
    m_engine->setAvOffsetMs(m_avOffsetMs);
    showOsd(QStringLiteral("🔊 AV 싱크: %1%2ms").arg(m_avOffsetMs > 0 ? "+" : "").arg(m_avOffsetMs));
}

void AppController::resetAvSync()
{
    m_avOffsetMs = 0;
    m_engine->setAvOffsetMs(0);
    showOsd(QStringLiteral("🔊 AV 싱크 초기화: 0ms"));
}

// ============================================================================
// A-B · 북마크 · 진행바 눈금
// ============================================================================

QString AppController::abLabel() const
{
    if (m_abActive)
        return QStringLiteral("🔁 %1 ~ %2 ✕").arg(formatTime(m_abA / 1e6), formatTime(m_abB / 1e6));
    if (m_abA >= 0)
        return QStringLiteral("🔁 A %1 ~ …").arg(formatTime(m_abA / 1e6));
    return {};
}

void AppController::setAbRepeatA()
{
    const qint64 pos = m_engine->position();
    if (!m_engine->isOpen() || pos < 0)
        return;
    m_abA = pos;
    m_abB = -1;
    m_abActive = false;
    showOsd(QStringLiteral("🔁 구간 반복 [A] 설정: %1").arg(formatTime(pos / 1e6)));
    qCInfo(lcApp).noquote() << "🔁 [구간 반복] A 지점 설정:" << formatTime(pos / 1e6);
    refreshTimelineMarks();
}

void AppController::setAbRepeatB()
{
    const qint64 pos = m_engine->position();
    if (!m_engine->isOpen() || pos < 0)
        return;
    if (m_abA < 0)
        m_abA = 0;
    if (pos <= m_abA) {
        showOsd(QStringLiteral("⚠️ B 지점은 A 지점보다 뒤여야 합니다."));
        return;
    }
    m_abB = pos;
    m_abActive = true;
    const QString a = formatTime(m_abA / 1e6), b = formatTime(m_abB / 1e6);
    showOsd(QStringLiteral("🔁 [A-B] 구간 반복 활성화: %1 ~ %2").arg(a, b));
    qCInfo(lcApp).noquote() << "🔁 [구간 반복] 활성화:" << a << "~" << b;
    refreshTimelineMarks();
}

void AppController::resetAbRepeat(bool announce)
{
    if (m_abA < 0 && m_abB < 0 && !m_abActive)
        return;
    m_abA = m_abB = -1;
    m_abActive = false;
    if (announce) {
        showOsd(QStringLiteral("🔁 A-B 구간 반복 해제"));
        qCInfo(lcApp) << "🔁 [구간 반복] 해제";
    }
    refreshTimelineMarks();
}

void AppController::clearAbRepeat() { resetAbRepeat(true); }

void AppController::addBookmark()
{
    const QString path = currentPath();
    const qint64 pos = m_engine->position();
    if (!m_engine->isOpen() || path.isEmpty() || pos < 0)
        return;
    const auto [ok, res] = bookmarkCache().add(path, pos);
    if (ok) {
        showOsd(QStringLiteral("🔖 북마크 추가: %1").arg(res));
        qCInfo(lcApp).noquote() << "🔖 [북마크 추가]" << QFileInfo(path).fileName() << "@" << res;
        refreshTimelineMarks();
    } else {
        showOsd(QStringLiteral("🔖 %1").arg(res));
    }
}

void AppController::removeBookmark(int index)
{
    if (bookmarkCache().remove(currentPath(), index))
        refreshTimelineMarks();
}

QVariantList AppController::bookmarkList() const
{
    QVariantList out;
    const QString path = currentPath();
    if (path.isEmpty())
        return out;
    for (const QVariant &v : bookmarkCache().get(path)) {
        const QVariantMap m = v.toMap();
        out << QVariantMap{{"label", m.value("label")}, {"ms", m.value("position_ns").toLongLong() / 1e6}};
    }
    return out;
}

void AppController::refreshTimelineMarks()
{
    m_timelineMarks.clear();
    if (m_durationNs > 0 && !currentPath().isEmpty()) {
        QList<qint64> positions;
        for (const QVariant &v : bookmarkCache().get(currentPath()))
            positions << v.toMap().value("position_ns").toLongLong();
        for (const auto &c : chapters())
            if (c.first > 0)
                positions << c.first;
        if (m_abA >= 0)
            positions << m_abA;
        if (m_abB >= 0)
            positions << m_abB;
        for (qint64 p : positions)
            m_timelineMarks << qMin(1.0, double(p) / m_durationNs);
    }
    emit marksChanged();
}

// ============================================================================
// 챕터 · 썸네일 · 장면 분석
// ============================================================================

QList<QPair<qint64, QString>> AppController::chapters() const
{
    return m_tocChapters.isEmpty() ? m_sceneChapters : m_tocChapters;
}

QString AppController::chapterAt(double ms) const
{
    const qint64 ns = qint64(ms * kMs);
    QString title;
    for (const auto &c : chapters()) {
        if (c.first > ns)
            break;
        title = c.second;
    }
    return title;
}

int AppController::currentChapterIndex() const
{
    int idx = -1;
    const auto list = chapters();
    for (int i = 0; i < list.size(); ++i)
        if (list[i].first <= m_lastPosNs)
            idx = i;
    return idx;
}

QVariantList AppController::chapterList() const
{
    QVariantList out;
    const auto list = chapters();
    const int current = currentChapterIndex();
    for (int i = 0; i < list.size(); ++i) {
        QString thumb;
        if (m_thumbIndex) {
            const int t = nearestThumbnail(*m_thumbIndex, list[i].first, true);
            if (t >= 0)
                thumb = QUrl::fromLocalFile(m_thumbIndex->filePath(t)).toString();
        }
        out << QVariantMap{{"ms", list[i].first / 1e6}, {"time", formatTime(list[i].first / 1e6)},
                           {"title", list[i].second}, {"current", i == current}, {"thumb", thumb}};
    }
    return out;
}

void AppController::jumpToChapter(double ms)
{
    jumpToMs(ms);
    showOsd(QStringLiteral("📑 %1").arg(formatTime(ms)));
}

QString AppController::chaptersTitle() const
{
    const auto list = chapters();
    if (list.isEmpty())
        return QStringLiteral("📑 챕터 / 장면");
    return QStringLiteral("📑 %1 (%2)").arg(m_tocChapters.isEmpty() ? QStringLiteral("자동 장면 분석") : QStringLiteral("챕터"))
        .arg(list.size());
}

QString AppController::chaptersEmptyText() const
{
    return m_thumbJob && m_thumbJob->isRunning() ? QStringLiteral("장면 분석 중...") : QStringLiteral("챕터 정보가 없습니다");
}

QString AppController::sceneAnalysisLabel() const
{
    if (m_sceneJob && m_sceneJob->isRunning())
        return QStringLiteral("⏹ 장면 분석 취소 (%1%)").arg(int(m_sceneProgress * 100));
    const bool precise = m_thumbIndex && m_thumbIndex->scenesPrecise.has_value();
    return precise ? QStringLiteral("🔍 정밀 장면 분석 다시 실행") : QStringLiteral("🔍 정밀 장면 분석");
}

bool AppController::sceneAnalysisAvailable() const
{
    if (m_sceneJob && m_sceneJob->isRunning())
        return true;
    return m_tocChapters.isEmpty() && !m_playlist.isEmpty() && !isRemote(currentPath());
}

QString AppController::thumbnailUrl(double ms) const
{
    if (!m_thumbIndex || !m_thumbIndex->isValid())
        return {};
    const int i = nearestThumbnail(*m_thumbIndex, qint64(ms * kMs));
    return i >= 0 ? QUrl::fromLocalFile(m_thumbIndex->filePath(i)).toString() : QString();
}

void AppController::startThumbnails(const QString &path)
{
    delete m_thumbJob.data();
    delete m_sceneJob.data();
    m_thumbIndex.reset();
    m_sceneChapters.clear();
    if (path.isEmpty() || isRemote(path) || !QFileInfo(path).isFile())
        return;
    // 재생이 자리 잡은 뒤 (2초 후) 시작합니다.
    QTimer::singleShot(2000, this, [this, path] {
        if (currentPath() != path || m_thumbJob)
            return;
        auto *job = new ThumbnailJob(path, this);
        m_thumbJob = job;
        auto apply = [this, job](const ThumbnailIndex &index) {
            if (m_thumbJob != job)
                return;
            m_thumbIndex = index;
            setSceneChapters(index.scenesPrecise.value_or(index.scenes));
            emit chaptersChanged();
        };
        connect(job, &ThumbnailJob::progress, this, apply);
        connect(job, &ThumbnailJob::done, this, apply);
        job->start();
    });
}

void AppController::setSceneChapters(const QList<qint64> &scenes)
{
    if (scenes.isEmpty())
        return;
    m_sceneChapters = {{0, QStringLiteral("시작")}};
    for (int n = 0; n < scenes.size(); ++n)
        m_sceneChapters.append({scenes[n], QStringLiteral("장면 %1").arg(n + 1)});
    refreshTimelineMarks();
}

void AppController::toggleSceneAnalysis()
{
    if (m_sceneJob && m_sceneJob->isRunning()) {
        m_sceneJob->cancel();
        return;
    }
    const QString path = currentPath();
    if (path.isEmpty() || isRemote(path))
        return;
    auto *job = new SceneAnalysisJob(path, this);
    m_sceneJob = job;
    m_sceneProgress = 0;
    connect(job, &SceneAnalysisJob::progress, this, [this](double p) {
        m_sceneProgress = p;
        showOsd(QStringLiteral("🔍 장면 분석 중 %1%").arg(int(p * 100)), 1500);
        emit chaptersChanged();
    });
    connect(job, &SceneAnalysisJob::done, this, [this, job, path](const QList<qint64> &scenes, bool ok) {
        job->deleteLater();
        if (!ok) {
            showOsd(QStringLiteral("🔍 장면 분석을 취소했습니다."));
            emit chaptersChanged();
            return;
        }
        if (currentPath() != path)
            return;
        m_sceneChapters.clear();
        if (m_thumbIndex)
            m_thumbIndex->scenesPrecise = scenes;   // 파일에는 작업이 저장, 메모리 사본도 맞춤
        setSceneChapters(scenes);
        emit chaptersChanged();
        showOsd(QStringLiteral("🔍 장면 분석 완료: %1곳 (K로 목록 보기)").arg(scenes.size()), 3000);
    });
    job->start();
    showOsd(QStringLiteral("🔍 정밀 장면 분석을 시작합니다 (백그라운드)"), 2000);
    emit chaptersChanged();
}

// ============================================================================
// 자막 · AI (자세한 동작은 SubtitleController / AiController)
// ============================================================================

void AppController::toggleSubtitles() { m_subs->toggle(); }

void AppController::startAiSubtitles() { m_ai->start(); }

void AppController::startTranslation() { m_translation->start(); }

void AppController::toggleAssStyles()
{
    const bool on = !Settings::instance()->boolValue(QStringLiteral("subtitle_ass_styles"));
    Settings::instance()->setValue(QStringLiteral("subtitle_ass_styles"), on);
    m_subs->setAssStyles(on);
    showOsd(on ? QStringLiteral("🎨 ASS 자막: 원래 스타일") : QStringLiteral("🎨 ASS 자막: 통일된 자막 모양"));
}

void AppController::addExternalSubtitle(const QString &path)
{
    const int idx = m_subs->addFile(path, true);
    if (idx < 0) {
        showOsd(QStringLiteral("⚠️ 자막을 읽을 수 없습니다."));
        return;
    }
    showOsd(QStringLiteral("💬 자막 추가됨: %1").arg(m_subs->entries().value(idx).label));
}

void AppController::refreshSubtitleUi() { emit subtitlesChanged(); }

// ============================================================================
// 회전 · HDR
// ============================================================================

void AppController::setRotation(const QString &method)
{
    QString name = method;
    for (const auto &r : rotations())
        if (r.first == method)
            name = r.second;
    m_rotation = method;
    emit viewChanged();
    showOsd(QStringLiteral("🔄 화면 회전: %1").arg(name));
}

void AppController::cycleRotation()
{
    int i = 0;
    for (int k = 0; k < rotations().size(); ++k)
        if (rotations()[k].first == m_rotation)
            i = k;
    setRotation(rotations()[(i + 1) % rotations().size()].first);
}

void AppController::updateHdr()
{
    // 디코딩된 영상의 전달 특성(PQ/HLG)에 맞춰 톤매핑 셰이더를 고릅니다 (preroll 때).
    m_hdrTransfer = m_engine->videoTransfer();
    const QString mode = Settings::instance()->boolValue(QStringLiteral("hdr_tonemap")) ? m_hdrTransfer : QString();
    // HW(NVMM) 경로는 VIC가 BT.709 행렬로 RGB를 만들므로 BT.2020 행렬로 다시 맞춥니다.
    const bool fix = m_engine->usingHwOutput();
    if (mode == m_hdrMode && fix == m_hdrMatrixFix)
        return;
    m_hdrMode = mode;
    m_hdrMatrixFix = fix;
    emit viewChanged();
    if (!mode.isEmpty()) {
        const QString name = mode == QLatin1String("pq") ? QStringLiteral("HDR10 (PQ)") : QStringLiteral("HLG");
        showOsd(QStringLiteral("🌈 %1 영상 — SDR 화면에 맞게 톤매핑합니다").arg(name), 2500);
        qCInfo(lcApp).noquote() << "🌈 [HDR 톤매핑]" << name << (fix ? "HW" : "SW") << "경로";
    }
}

void AppController::toggleHdrTonemap()
{
    const bool on = !Settings::instance()->boolValue(QStringLiteral("hdr_tonemap"));
    Settings::instance()->setValue(QStringLiteral("hdr_tonemap"), on);
    m_hdrMode = on ? m_hdrTransfer : QString();
    emit viewChanged();
    showOsd(on ? QStringLiteral("🌈 HDR 톤매핑 ON") : QStringLiteral("🌈 HDR 톤매핑 OFF (HDR 원본 값 그대로)"));
}

// ============================================================================
// 오디오 효과: 야간 모드 · 음량 평준화 · EQ · HDMI 패스스루
// ============================================================================

bool AppController::nightMode() const { return Settings::instance()->boolValue(QStringLiteral("night_mode")); }

void AppController::toggleNightMode()
{
    const bool on = !nightMode();
    Settings::instance()->setValue(QStringLiteral("night_mode"), on);
    m_engine->setNightMode(on);
    showOsd(on ? QStringLiteral("🌙 야간 모드 ON — 큰 소리는 줄이고 대사는 키웁니다") : QStringLiteral("🌙 야간 모드 OFF"));
}

QVariantList AppController::eqPresets() const
{
    QVariantList out;
    for (const EqPreset &p : eqPresetTable())
        out << QVariantMap{{"key", QString::fromLatin1(p.key)}, {"name", QString::fromUtf8(p.name)}};
    return out;
}

QString AppController::eqPresetName() const
{
    return QString::fromUtf8(eqPreset(Settings::instance()->stringValue(QStringLiteral("eq_preset"))).name);
}

void AppController::applyEqPreset()
{
    m_engine->setEqualizer(eqPreset(Settings::instance()->stringValue(QStringLiteral("eq_preset"))).gains);
}

void AppController::setEqPreset(const QString &key)
{
    bool known = false;
    for (const EqPreset &p : eqPresetTable())
        known |= key == QLatin1String(p.key);
    if (!known)
        return;
    Settings::instance()->setValue(QStringLiteral("eq_preset"), key);
    applyEqPreset();
    showOsd(QStringLiteral("🎚️ EQ: %1").arg(eqPresetName()));
}

QString AppController::loudnessMenuLabel() const
{
    QString detail;
    if (Settings::instance()->boolValue(QStringLiteral("loudness_normalize")) && m_loudnessLufs)
        detail = QStringLiteral(" — %1 LUFS → %2%3dB").arg(qRound(*m_loudnessLufs))
                     .arg(m_loudnessCurrentDb >= 0 ? "+" : "").arg(qRound(m_loudnessCurrentDb));
    return QStringLiteral("🔊 음량 평준화 (영상마다 음량 맞추기)") + detail;
}

void AppController::startLoudnessFor(const QString &path)
{
    delete m_loudnessJob.data();
    m_loudnessPath = path;
    m_loudnessLufs.reset();
    setLoudnessGain(0.0, false);
    if (!Settings::instance()->boolValue(QStringLiteral("loudness_normalize")) || path.isEmpty() || isRemote(path)
        || !QFileInfo(path).isFile())
        return;
    const auto [known, lufs] = loudnessCache().lookup(path);
    if (known) {
        applyMeasuredLoudness(path, lufs);
        return;
    }
    auto *job = new LoudnessJob(path, this);
    m_loudnessJob = job;
    connect(job, &LoudnessJob::done, this, [this, job, path](const QVariant &value, const QString &error) {
        job->deleteLater();
        if (!error.isEmpty()) {
            // 측정 실패는 저장하지 않습니다 (다음 재생 때 다시 측정). 이번에는 이득 없이 재생.
            qCInfo(lcApp).noquote() << "🔊 [음량 평준화] 측정 실패 (" << QFileInfo(path).fileName() << "):" << error;
            return;
        }
        const std::optional<double> lufs = value.isValid() && !value.isNull() ? std::optional<double>(value.toDouble())
                                                                              : std::nullopt;
        loudnessCache().store(path, lufs);
        applyMeasuredLoudness(path, lufs);
    });
    job->start();
}

void AppController::applyMeasuredLoudness(const QString &path, std::optional<double> lufs)
{
    if (path != m_loudnessPath || !Settings::instance()->boolValue(QStringLiteral("loudness_normalize")))
        return;
    const double gain = loudness::gainFor(lufs);
    m_loudnessLufs = lufs;
    qCInfo(lcApp).noquote() << "🔊 [음량 평준화]" << QFileInfo(path).fileName() << ":"
                            << (lufs ? QStringLiteral("%1 LUFS → %2 dB").arg(*lufs, 0, 'f', 1).arg(gain, 0, 'f', 1)
                                     : QStringLiteral("오디오 없음"));
    setLoudnessGain(gain, true);
    emit stateChanged();
}

void AppController::setLoudnessGain(double db, bool ramp)
{
    // ramp: 1초에 걸쳐 서서히 (갑자기 커지거나 작아지지 않게)
    m_loudnessTargetDb = db;
    m_loudnessRamp.stop();
    if (!ramp || qAbs(db - m_loudnessCurrentDb) < 0.05) {
        m_loudnessCurrentDb = db;
        m_engine->setLoudnessGainDb(db);
        return;
    }
    m_loudnessRampFrom = m_loudnessCurrentDb;
    m_loudnessRampStep = 0;
    m_loudnessRamp.start();
}

void AppController::toggleLoudness()
{
    const bool on = !Settings::instance()->boolValue(QStringLiteral("loudness_normalize"));
    Settings::instance()->setValue(QStringLiteral("loudness_normalize"), on);
    if (on)
        startLoudnessFor(currentPath());
    else
        setLoudnessGain(0.0, true);
    showOsd(on ? QStringLiteral("🔊 음량 평준화 ON") : QStringLiteral("🔊 음량 평준화 OFF"));
}

bool AppController::usePassthroughFor(const QString &path)
{
    if (!Settings::instance()->boolValue(QStringLiteral("audio_passthrough")) || path.isEmpty()
        || !QFileInfo(path).isFile() || m_passthroughFailed.contains(path))
        return false;
    const QString codec = probe::audioCodec(path);
    if (!probe::passthroughCaps().contains(codec))
        return false;
    const QSet<QString> supported = probe::sinkPassthroughFormats();
    if (!supported.contains(codec)) {
        if (!m_passthroughHintShown) {
            m_passthroughHintShown = true;
            showOsd(QStringLiteral("🔈 HDMI 패스스루: 사운드 설정에서 HDMI 출력의 AC3/DTS 패스스루를 켜야 합니다 (지금은 디코딩)"), 4000);
        }
        qCInfo(lcApp).noquote() << "🔈 [HDMI 패스스루] 출력 장치가" << codec << "을(를) 받지 않아 디코딩합니다";
        return false;
    }
    showOsd(QStringLiteral("🔈 HDMI 패스스루: %1 원음 출력 (볼륨·효과·배속 끔)").arg(codec.section('-', -1).toUpper()), 3000);
    qCInfo(lcApp).noquote() << "🔈 [HDMI 패스스루]" << QFileInfo(path).fileName() << ":" << codec;
    return true;
}

void AppController::togglePassthrough()
{
    const bool on = !Settings::instance()->boolValue(QStringLiteral("audio_passthrough"));
    Settings::instance()->setValue(QStringLiteral("audio_passthrough"), on);
    m_passthroughHintShown = false;
    showOsd(on ? QStringLiteral("🔈 HDMI 패스스루 ON (다음 영상부터, AC3/E-AC3/DTS 파일)")
               : QStringLiteral("🔈 HDMI 패스스루 OFF (다음 영상부터)"), 2500);
}

// ============================================================================
// 다음 영상 자동 재생 카운트다운
// ============================================================================

QVariantMap AppController::autoplay() const
{
    const bool visible = m_autoplayIndex >= 0;
    const double elapsed = visible ? m_autoplayClock.elapsed() / 1000.0 : 0;
    return {{"visible", visible}, {"title", m_autoplayTitle},
            {"remaining", qMax(0, int(qRound(5.0 - elapsed)))}, {"fraction", qMin(1.0, elapsed / 5.0)}};
}

void AppController::startAutoplayCountdown(int nextIndex)
{
    if (!Settings::instance()->boolValue(QStringLiteral("autoplay_countdown"))) {
        playIndex(nextIndex);
        return;
    }
    m_autoplayIndex = nextIndex;
    m_autoplayTitle = QStringLiteral("다음: %1").arg(QFileInfo(m_playlist.value(nextIndex)).fileName());
    m_autoplayClock.start();
    m_autoplayTimer.start();
    emit autoplayChanged();
}

void AppController::finishAutoplay(bool run)
{
    m_autoplayTimer.stop();
    const int next = m_autoplayIndex;
    m_autoplayIndex = -1;
    emit autoplayChanged();
    if (run && next >= 0)
        playIndex(next);
    else if (!run && next >= 0)
        showOsd(QStringLiteral("⏹ 자동 재생을 취소했습니다."));
}

void AppController::cancelAutoplay()
{
    // 사용자가 직접 다른 조작(다음/이전/목록 선택)을 하면 카드를 조용히 닫습니다.
    if (m_autoplayIndex < 0)
        return;
    m_autoplayTimer.stop();
    m_autoplayIndex = -1;
    emit autoplayChanged();
}

void AppController::autoplayNow() { finishAutoplay(true); }

// ============================================================================
// 수면 타이머
// ============================================================================

QString AppController::sleepMenuLabel() const
{
    const int remaining = sleepRemainingSec();
    QString label = QStringLiteral("⏾ 수면 타이머 (H)");
    if (remaining > 0)
        label += QStringLiteral(" — %1분 %2초 남음").arg(remaining / 60).arg(remaining % 60);
    else if (m_sleepMinutes == -1)
        label += QStringLiteral(" — 영상 끝나면");
    return label;
}

int AppController::sleepRemainingSec() const
{
    if (m_sleepDeadlineMs < 0)
        return -1;
    return int(qMax<qint64>(0, (m_sleepDeadlineMs - m_sleepClock.elapsed()) / 1000));
}

void AppController::setSleepTimer(int minutes)
{
    cancelSleepFade();
    m_sleepMinutes = minutes;
    if (minutes > 0) {
        m_sleepClock.start();
        m_sleepDeadlineMs = qint64(minutes) * 60'000;
        m_sleepTimer.start();
    } else {
        m_sleepDeadlineMs = -1;
        m_sleepTimer.stop();
    }
    QString label = QStringLiteral("%1분 후").arg(minutes);
    for (const auto &c : sleepChoices())
        if (c.first == minutes)
            label = c.second;
    showOsd(minutes == 0 ? QStringLiteral("⏾ 수면 타이머 끔") : QStringLiteral("⏾ 수면 타이머: %1 정지").arg(label));
    emit stateChanged();
}

void AppController::cycleSleepTimer()
{
    int i = -1;
    for (int k = 0; k < sleepChoices().size(); ++k)
        if (sleepChoices()[k].first == m_sleepMinutes)
            i = k;
    setSleepTimer(i < 0 ? 0 : sleepChoices()[(i + 1) % sleepChoices().size()].first);
}

void AppController::onSleepTick()
{
    const int remaining = sleepRemainingSec();
    if (remaining < 0) {
        m_sleepTimer.stop();
        return;
    }
    if (remaining == 60 || remaining == 30)
        showOsd(QStringLiteral("⏾ %1초 후 재생을 멈춥니다 (H: 타이머 변경)").arg(remaining), 3000);
    if (remaining <= kSleepFadeSec && !m_sleepFading) {
        // 남은 시간 동안 볼륨을 서서히 줄입니다 (설정된 볼륨 값은 바꾸지 않음)
        m_sleepFading = true;
        m_sleepFadeBase = m_volume / 100.0;
    }
    if (remaining <= 0) {
        m_sleepTimer.stop();
        sleepNow();
    }
    emit stateChanged();
}

void AppController::sleepNow()
{
    m_sleepMinutes = 0;
    m_sleepDeadlineMs = -1;
    if (m_playing)
        togglePlayPause();
    cancelSleepFade();
    showOsd(QStringLiteral("⏾ 수면 타이머: 재생을 멈췄습니다. 편안한 밤 되세요."), 5000);
    qCInfo(lcApp) << "⏾ [수면 타이머] 재생 정지";
    emit stateChanged();
}

void AppController::cancelSleepFade()
{
    if (!m_sleepFading)
        return;
    m_sleepFading = false;
    applyVolumeToEngine();
}

void AppController::applySleepFade()
{
    if (m_sleepFading && !m_muted)
        applyVolumeToEngine();
}

} // namespace jvp
