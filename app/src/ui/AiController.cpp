#include "AiController.h"

#include "AppController.h"
#include "Settings.h"
#include "SubtitleController.h"
#include "Translator.h"
#include "Whisper.h"

#include <QFileInfo>
#include <QLoggingCategory>
#include <QTimer>

Q_LOGGING_CATEGORY(lcAi, "jvp.ai")

namespace jvp {

namespace {
const QString kAiColor = QStringLiteral("#B388FF");

bool isRemote(const QString &p)
{
    return p.startsWith(QLatin1String("http://")) || p.startsWith(QLatin1String("https://"));
}

Settings *settings() { return Settings::instance(); }

ai::Segments toSegments(const SubtitleEvents &events)
{
    ai::Segments out;
    out.reserve(events.size());
    for (const SubtitleEvent &e : events)
        out.append({e.startMs, e.endMs, e.text});
    return out;
}

SubtitleEvents toEvents(const ai::Segments &segments)
{
    SubtitleEvents out;
    out.reserve(segments.size());
    for (const ai::Segment &s : segments)
        out.append({s.startMs, s.endMs, s.text});
    return out;
}
} // namespace

// ============================================================================
// AI 자막
// ============================================================================

AiController::AiController(AppController *app) : QObject(app), m_app(app) {}

AiController::~AiController() { delete m_job.data(); }

bool AiController::running() const { return m_job && m_job->isRunning(); }

QString AiController::menuLabel() const
{
    if (running())
        return QStringLiteral("⏹ AI 자막 생성 취소 %1% (G)").arg(int(m_fraction * 100));
    return QStringLiteral("🤖 AI 자막 생성 (G)");
}

QVariantList AiController::languages() const
{
    static const QList<QPair<const char *, const char *>> list{
        {"auto", "자동 감지"}, {"ko", "한국어"}, {"en", "영어"}, {"ja", "일본어"}, {"zh", "중국어"}};
    QVariantList out;
    for (const auto &l : list)
        out << QVariantMap{{"key", QString::fromLatin1(l.first)}, {"name", QString::fromUtf8(l.second)}};
    return out;
}

QVariantList AiController::models() const
{
    QVariantList out;
    for (const QString &m : ai::listWhisperModels()) {
        const QString note = ai::modelNote(m);
        out << QVariantMap{{"name", m}, {"label", note.isEmpty() ? m : m + QStringLiteral("  —  ") + note}};
    }
    return out;
}

void AiController::cancel()
{
    if (m_job && m_job->isRunning())
        m_job->cancel();
}

void AiController::start()
{
    if (running()) {
        cancel();
        return;
    }
    const QString path = m_app->currentPath();
    if (path.isEmpty()) {
        m_app->showOsd(QStringLiteral("재생 중인 영상이 없습니다."));
        return;
    }
    if (isRemote(path) || !QFileInfo(path).isFile()) {
        m_app->showOsd(QStringLiteral("⚠️ 로컬 영상 파일에서만 AI 자막을 만들 수 있습니다."), 3000);
        return;
    }
    const QString model = settings()->stringValue(QStringLiteral("whisper_model"));
    if (!ai::whisperAvailable(model)) {
        m_app->showOsd(QStringLiteral("⚠️ AI 자막 엔진이 설치되지 않았습니다: ./scripts/setup_whisper.sh 실행"), 5000);
        qCInfo(lcAi) << "ℹ️ AI 자막을 사용하려면 프로젝트 폴더에서 ./scripts/setup_whisper.sh 를 실행하세요.";
        return;
    }
    if (m_app->durationNs() <= 0) {
        m_app->showOsd(QStringLiteral("영상 길이를 확인하는 중입니다. 잠시 후 다시 시도하세요."));
        return;
    }
    const bool translate = settings()->boolValue(QStringLiteral("whisper_translate"));
    SubtitleController *subs = m_app->subtitleController();
    // AI 자막만 표시해 기존 자막과 겹치지 않게 합니다 (자막 설정 창에서 함께 켤 수 있음).
    const int idx = subs->addLive(QStringLiteral("🤖 AI 자막 (생성 중...)"), kAiColor);
    const SubtitleTrackPtr track = subs->entry(idx)->track;
    m_track = track;

    const qint64 posMs = m_app->positionNs() / 1'000'000;
    auto *job = new ai::AiSubtitleJob(path, m_app->durationNs() / 1'000'000, posMs,
                                      settings()->stringValue(QStringLiteral("whisper_language")), translate, model, this);
    m_job = job;
    m_statusText = QStringLiteral("🤖 AI 자막 준비 중...");
    m_fraction = 0;
    connect(job, &ai::AiSubtitleJob::segments, this, [track](const ai::Segments &batch) {
        track->addEvents(toEvents(batch));
    });
    connect(job, &ai::AiSubtitleJob::status, this, [this, job](const QString &text, double fraction) {
        m_statusText = text;
        m_fraction = fraction;
        if (m_job == job)
            m_app->showOsd(text, 1500);
        emit changed();
    });
    connect(job, &ai::AiSubtitleJob::done, this,
            [this, job, track, translate, path](const QString &srtPath, const QString &language, const QString &error) {
                job->deleteLater();
                m_statusText.clear();
                m_fraction = 0;
                SubtitleController *subs = m_app->subtitleController();
                const int i = subs->indexOfTrack(track);
                emit changed();
                if (!error.isEmpty()) {
                    m_app->showOsd(error == QStringLiteral("취소됨") ? QStringLiteral("⏹ AI 자막 생성을 취소했습니다.")
                                                                  : QStringLiteral("❌ AI 자막 실패: %1").arg(error.left(50)),
                                   4000);
                    if (i < 0)
                        return;
                    if (track->size() > 0)
                        // 일부만 인식된 채 멈춤: 표시된 대사는 남기고 이름만 확정 (파일로는 저장하지 않음)
                        subs->updateEntry(i, QString(), QStringLiteral("🤖 AI 자막 (중단, %1문장)").arg(track->size()), QString());
                    else
                        subs->removeEntry(i);
                    return;
                }
                const QString langName = translate ? QStringLiteral("영어 번역")
                                                   : (language.isEmpty() ? QStringLiteral("자동") : ai::languageName(language));
                const QString lang = translate ? QStringLiteral("en") : language;
                if (i >= 0)
                    subs->updateEntry(i, srtPath, QStringLiteral("🤖 AI %1 (%2)").arg(langName, QFileInfo(srtPath).fileName()),
                                      lang);
                m_app->showOsd(QStringLiteral("🤖 AI 자막 완성: %1문장 (다음 재생부터 자동 로드)").arg(track->size()), 4000);
                const QString target = settings()->stringValue(QStringLiteral("translate_target"));
                if (settings()->boolValue(QStringLiteral("whisper_auto_translate")) && !translate && !language.isEmpty()
                    && language != target) {
                    QTimer::singleShot(1500, this, [this, path, track] {
                        if (m_app->currentPath() == path)
                            qobject_cast<TranslationController *>(m_app->translationObject())->start(track);
                    });
                }
            });
    job->start();
    const QString where = posMs >= 30'000 ? QStringLiteral(" (%1부터)").arg(m_app->formatTime(posMs)) : QString();
    m_app->showOsd(QStringLiteral("🤖 AI 자막 생성을 시작합니다%1 — G: 취소").arg(where), 2500);
    emit changed();
}

void AiController::markForAuto(const QString &path)
{
    if (settings()->boolValue(QStringLiteral("youtube_auto_ai_subtitles")))
        m_autoPaths.insert(path);
}

void AiController::maybeAutoStart()
{
    const QString path = m_app->currentPath();
    if (!m_autoPaths.remove(path))
        return;
    if (!m_app->subtitleController()->entries().isEmpty() || running())
        return;   // 자막이 이미 있음 (이전에 만든 AI 자막 포함)
    if (ai::whisperAvailable(settings()->stringValue(QStringLiteral("whisper_model")))) {
        qCInfo(lcAi).noquote() << "🤖 [자동 AI 자막]" << QFileInfo(path).fileName();
        start();
    }
}

QJsonObject AiController::remoteStatus() const
{
    return {{"running", running()}, {"text", m_statusText}, {"fraction", m_fraction},
            {"available", ai::whisperAvailable(settings()->stringValue(QStringLiteral("whisper_model")))}};
}

// ============================================================================
// 자막 번역
// ============================================================================

TranslationController::TranslationController(AppController *app) : QObject(app), m_app(app) {}

TranslationController::~TranslationController() { delete m_job.data(); }

bool TranslationController::running() const { return m_job && m_job->isRunning(); }

QString TranslationController::menuLabel() const
{
    if (running())
        return QStringLiteral("⏹ 자막 번역 취소 %1% (Shift+G)").arg(int(m_fraction * 100));
    const QString target = settings()->stringValue(QStringLiteral("translate_target"));
    return QStringLiteral("🌐 자막을 %1로 번역 (Shift+G)").arg(ai::languageName(target));
}

void TranslationController::cancel()
{
    if (m_job && m_job->isRunning())
        m_job->cancel();
}

QString TranslationController::entryLanguage(int index) const
{
    // AI 자막은 감지된 언어, 외부 자막은 레이블의 언어, 모르면 영어
    const auto entries = m_app->subtitleController()->entries();
    if (index < 0 || index >= entries.size())
        return QStringLiteral("en");
    if (!entries[index].lang.isEmpty())
        return entries[index].lang;
    static const QStringList codes{"ko", "en", "ja", "zh", "es", "fr", "de", "it", "pt", "ru", "vi", "th", "id"};
    for (const QString &c : codes)
        if (entries[index].label.contains(ai::languageName(c)))
            return c;
    return QStringLiteral("en");
}

void TranslationController::start(SubtitleTrackPtr source)
{
    if (running()) {
        cancel();
        return;
    }
    SubtitleController *subs = m_app->subtitleController();
    const auto entries = subs->entries();
    int srcIndex = source ? subs->indexOfTrack(source) : -1;
    if (srcIndex < 0) {
        // 지금 켜져 있는 외부/AI 자막 중 첫 번째 (번역 결과 트랙 제외)
        QList<int> active(subs->activeIndices().begin(), subs->activeIndices().end());
        std::sort(active.begin(), active.end());
        for (int i : active)
            if (i < entries.size() && entries[i].track->size() > 0 && !entries[i].isTranslation) {
                srcIndex = i;
                break;
            }
    }
    if (srcIndex < 0) {
        m_app->showOsd(QStringLiteral("⚠️ 번역할 자막이 없습니다. 자막을 켜거나 🤖 AI 자막을 먼저 만드세요."), 3500);
        return;
    }
    const QString target = settings()->stringValue(QStringLiteral("translate_target"));
    const QString sourceLang = entryLanguage(srcIndex);
    const QString targetName = ai::languageName(target);
    if (sourceLang == target) {
        m_app->showOsd(QStringLiteral("이미 %1 자막입니다.").arg(targetName), 2500);
        return;
    }
    const QString backend = ai::resolveBackend(settings()->stringValue(QStringLiteral("translate_backend")));
    if (backend.isEmpty()) {
        m_app->showOsd(QStringLiteral("⚠️ 번역 엔진이 없습니다: ./scripts/setup_translator.sh 실행 (또는 Claude API 키 설정)"), 5000);
        qCInfo(lcAi) << "ℹ️ 자막 번역을 쓰려면 ./scripts/setup_translator.sh 를 실행하거나 ANTHROPIC_API_KEY를 설정하세요.";
        return;
    }
    const QString video = m_app->currentPath();
    if (video.isEmpty())
        return;
    const SubtitleTrackPtr sourceTrack = entries[srcIndex].track;
    const int idx = subs->addLive(QStringLiteral("🌐 %1 번역 (번역 중...)").arg(targetName), QStringLiteral("#FFFFFF"),
                                  true, target);
    const SubtitleTrackPtr track = subs->entry(idx)->track;
    m_track = track;
    const QString savePath = ai::aiSubtitlePath(video, target);
    auto *job = new ai::TranslationJob(toSegments(sourceTrack->events()), target, ai::makeBackend(backend),
                                       m_app->positionNs() / 1'000'000, sourceLang, true, savePath, this);
    m_job = job;
    m_fraction = 0;
    connect(job, &ai::TranslationJob::segments, this, [track](const ai::Segments &batch) {
        track->addEvents(toEvents(batch));
    });
    connect(job, &ai::TranslationJob::status, this, [this](const QString &text, double fraction) {
        m_fraction = fraction;
        m_app->showOsd(text, 1500);
        emit changed();
    });
    connect(job, &ai::TranslationJob::done, this,
            [this, job, track, sourceTrack, targetName, savePath](const ai::Segments &events, const QString &error) {
                job->deleteLater();
                m_fraction = 0;
                emit changed();
                SubtitleController *subs = m_app->subtitleController();
                const int i = subs->indexOfTrack(track);
                if (!error.isEmpty() && events.isEmpty()) {
                    m_app->showOsd(error == QStringLiteral("취소됨") ? QStringLiteral("⏹ 번역을 취소했습니다.")
                                                                  : QStringLiteral("❌ 번역 실패: %1").arg(error.left(50)),
                                   4000);
                    if (i >= 0) {
                        subs->removeEntry(i);
                        const int src = subs->indexOfTrack(sourceTrack);
                        if (src >= 0)
                            subs->setActiveOnly(src);
                    }
                    return;
                }
                if (!error.isEmpty()) {
                    if (i >= 0)
                        subs->updateEntry(i, QString(), QStringLiteral("🌐 %1 번역 (중단, %2문장)").arg(targetName).arg(events.size()),
                                          QString());
                    m_app->showOsd(QStringLiteral("⏹ 번역 중단 (%1문장까지 표시)").arg(events.size()), 3000);
                    return;
                }
                if (i >= 0)
                    subs->updateEntry(i, savePath, QStringLiteral("🌐 %1 번역 (%2)").arg(targetName, QFileInfo(savePath).fileName()),
                                      QString());
                qCInfo(lcAi).noquote() << "🌐 [자막 번역]" << events.size() << "문장 →" << savePath;
                m_app->showOsd(QStringLiteral("🌐 %1 번역 완성: %2문장 (다음 재생부터 자동 로드)").arg(targetName).arg(events.size()), 4000);
            });
    job->start();
    m_app->showOsd(QStringLiteral("🌐 %1 번역 시작 (%2) — Shift+G: 취소")
                       .arg(targetName, backend == QLatin1String("local") ? QStringLiteral("로컬 번역 모델") : QStringLiteral("Claude API")),
                   2500);
    emit changed();
}

QJsonObject TranslationController::remoteStatus() const
{
    return {{"running", running()}, {"fraction", m_fraction},
            {"available", !ai::resolveBackend(settings()->stringValue(QStringLiteral("translate_backend"))).isEmpty()}};
}

} // namespace jvp
