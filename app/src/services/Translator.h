#pragma once
// AI 자막 번역: 자막 트랙을 다른 언어(기본 한국어)로 번역합니다. (파이썬 jetson_player/ai/translate.py 이식)
//
// 번역 엔진
//   - local  : Meta NLLB-200 (CTranslate2 int8, CPU). C++용 CTranslate2가 없어 app/tools/nllb_worker.py 사이드카를
//              QProcess로 띄우고 JSON 줄로 주고받습니다. 설치 위치는 파이썬 버전과 같음($JVP_NLLB_DIR).
//   - claude : Claude API (claude-opus-5) — ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN이 있을 때만
//   - auto   : local이 설치되어 있으면 local, 아니면 claude
// 음성 인식 자막은 문장 중간에서 줄이 끊기므로 먼저 실제 문장 단위로 다시 나눈 뒤 번역하고,
// 지금 보고 있는 위치 근처부터 번역해 끝나면 SRT로 저장합니다.

#include "Whisper.h"   // ai::Segment, formatSrt

#include <QJsonObject>
#include <QObject>
#include <QPair>
#include <QString>
#include <QStringList>

#include <atomic>
#include <functional>
#include <memory>
#include <optional>
#include <stdexcept>

class QNetworkAccessManager;
class QProcess;
class QThread;

namespace jvp::ai {

inline constexpr char kClaudeModel[] = "claude-opus-5";
constexpr int kBatchSize = 20;
constexpr int kContextLines = 3;

QString nllbHome();                         // $JVP_NLLB_DIR 또는 ~/.local/share/jetson_video_player/nllb
QPair<QString, QString> nllbPaths();         // (pylib, model)
QString nllbCode(const QString &lang);       // "ko" → "kor_Hang" (없으면 빈 문자열)
QList<QPair<QString, QString>> targetLanguages();   // [("ko", "Korean (한국어)"), ...] 순서 유지
QString targetLanguageName(const QString &code);
bool localAvailable();
bool claudeAvailable();
QString resolveBackend(const QString &preference);  // "auto"/"local"/"claude" → "local"/"claude"/빈 문자열
QString nllbWorkerScript();                  // 사이드카 스크립트 위치 (없으면 빈 문자열)

Segments resegmentSentences(const Segments &events, int maxChars = 120, qint64 maxGapMs = 1500);
QJsonObject translationSchema(int count);
QString systemPrompt(const QString &targetCode);
QString buildUserMessage(const QStringList &lines, const QStringList &context);
std::optional<QStringList> parseTranslations(const QString &text, int expected);   // 개수가 다르면 nullopt
QList<QPair<int, int>> planBatches(const Segments &events, qint64 positionMs, int size = kBatchSize, int firstSize = 6);

// 엔진 오류 (작업은 이 문구를 error로 끝냅니다)
struct TranslationError : std::runtime_error {
    using std::runtime_error::runtime_error;
    explicit TranslationError(const QString &msg) : std::runtime_error(msg.toStdString()) {}
};

// 번역 엔진. start/translate/stop은 모두 TranslationJob의 작업 스레드에서 호출됩니다.
class TranslationBackend {
public:
    virtual ~TranslationBackend() = default;
    virtual void start(const std::function<bool()> &cancelled) = 0;
    // 줄 수가 맞지 않거나 거절되면 nullopt (작업이 묶음을 나눠 재시도). 실패는 TranslationError.
    virtual std::optional<QStringList> translate(const QStringList &lines, const QStringList &context,
                                                 const QString &target, const QString &source) = 0;
    virtual void stop() = 0;
};

class NllbBackend : public TranslationBackend {
public:
    explicit NllbBackend(int threads = 4);
    ~NllbBackend() override;
    void start(const std::function<bool()> &cancelled) override;
    std::optional<QStringList> translate(const QStringList &lines, const QStringList &context, const QString &target,
                                         const QString &source) override;
    void stop() override;

private:
    QJsonObject readMessage(int timeoutMs);
    int m_threads;
    std::unique_ptr<QProcess> m_proc;
    QByteArray m_buffer;
    std::function<bool()> m_cancelled;
    int m_nextId = 1;
};

class ClaudeBackend : public TranslationBackend {
public:
    ClaudeBackend();
    ~ClaudeBackend() override;
    void start(const std::function<bool()> &cancelled) override;
    std::optional<QStringList> translate(const QStringList &lines, const QStringList &context, const QString &target,
                                         const QString &source) override;
    void stop() override;
    static QJsonObject buildRequest(const QStringList &lines, const QStringList &context, const QString &target);
    static QString apiBaseUrl();   // $ANTHROPIC_BASE_URL 또는 https://api.anthropic.com

private:
    std::unique_ptr<QNetworkAccessManager> m_nam;
    std::function<bool()> m_cancelled;
};

std::unique_ptr<TranslationBackend> makeBackend(const QString &name);   // "local" → NLLB, 그 외 Claude

// 번역 작업. 신호는 모두 소유 스레드에서 발생합니다.
class TranslationJob : public QObject {
    Q_OBJECT
public:
    TranslationJob(const Segments &events, const QString &target, std::unique_ptr<TranslationBackend> backend,
                   qint64 positionMs = 0, const QString &source = QStringLiteral("en"), bool resegment = true,
                   const QString &savePath = QString(), QObject *parent = nullptr);
    ~TranslationJob() override;   // 취소 후 작업 스레드가 끝날 때까지 기다립니다

    void start();
    void cancel();
    bool isRunning() const;
    const Segments &events() const { return m_events; }   // 번역할 (재분할된) 원문

signals:
    void segments(const jvp::ai::Segments &batch);
    void status(const QString &text, double fraction);
    // 번역된 줄(시간순)과 오류 문구("취소됨" 포함). 끝까지 번역되면 작업 스레드에서 이미 저장됨.
    void done(const jvp::ai::Segments &events, const QString &error);

private:
    void run();
    QStringList translateRange(int a, int b);

    Segments m_events;
    QString m_target, m_source, m_savePath;
    std::unique_ptr<TranslationBackend> m_backend;
    qint64 m_positionMs;
    QThread *m_thread = nullptr;
    std::atomic<bool> m_cancelled{false};
};

} // namespace jvp::ai
