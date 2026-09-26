#pragma once
// AI 자막 생성: whisper.cpp(CUDA)로 영상 음성을 인식해 자막을 만듭니다. (파이썬 jetson_player/ai/whisper.py 이식)
//   1) GStreamer로 음성을 16kHz 모노 WAV로 추출
//   2) whisper-cli 실행 — 지금 보고 있는 위치부터 먼저 인식한 뒤 앞부분을 이어서 인식
//   3) 인식된 문장을 즉시 신호로 전달(화면에 실시간 표시), 끝나면 영상 옆에 .ai.<언어>.srt 저장
// 설치 위치: $JVP_WHISPER_DIR 또는 ~/.local/share/jetson_video_player/whisper.cpp (실행 파일은 $JVP_WHISPER_BIN 우선)

#include <QList>
#include <QMetaType>
#include <QObject>
#include <QPair>
#include <QString>
#include <QStringList>

#include <atomic>
#include <functional>
#include <optional>

class QThread;

namespace jvp::ai {

// 시각이 붙은 자막 한 줄 (ms)
struct Segment {
    qint64 startMs = 0;
    qint64 endMs = 0;
    QString text;
    bool operator==(const Segment &o) const { return startMs == o.startMs && endMs == o.endMs && text == o.text; }
    bool operator<(const Segment &o) const   // 파이썬 튜플 정렬과 같은 순서
    {
        if (startMs != o.startMs)
            return startMs < o.startMs;
        if (endMs != o.endMs)
            return endMs < o.endMs;
        return text < o.text;
    }
};
using Segments = QList<Segment>;

QString whisperHome();
QString findWhisperBinary();                                     // 없으면 빈 문자열
QStringList listWhisperModels();                                 // 설치된 모델 이름 (ggml-<이름>.bin, 테스트용 더미 제외)
QString findWhisperModel(const QString &modelName = QStringLiteral("small-q5_1"));   // 없으면 설치된 아무 모델
bool whisperAvailable(const QString &modelName = QStringLiteral("small-q5_1"));
QString modelNote(const QString &modelName);                     // 알려진 모델 설명 (없으면 빈 문자열)
QString languageName(const QString &code);                       // "ko" → "한국어"

// '[00:00:01.000 --> 00:00:04.500]   text' → 세그먼트 (효과음 표시·빈 줄은 nullopt)
std::optional<Segment> parseWhisperLine(const QString &line);
// "auto-detected language: en" 줄에서 언어 코드
QString parseDetectedLanguage(const QString &line);

// 인식 순서: 현재 위치 → 끝, 그다음 처음 → 현재 위치. 반환: [(offset_ms, length_ms)]
QList<QPair<qint64, qint64>> planPasses(qint64 durationMs, qint64 startMs, qint64 firstChunkMs = 60000,
                                        qint64 chunkMs = 300000);

QString formatSrt(Segments events);   // 시간순 정렬 후 SRT

// os.path.splitext(basename)의 앞부분
QString fileStem(const QString &path);
// 캐시 폴더용 이름: <영상 이름>.<폴더 경로 sha1 앞 8자> — 다른 폴더의 같은 이름 영상과 섞이지 않게
QString cachedAiSubtitleStem(const QString &videoPath);
// 영상 옆 <이름>.ai.<언어>.srt (폴더에 쓸 수 없으면 paths::aiSubtitleCacheDir()/<캐시 이름>.ai.<언어>.srt)
QString aiSubtitlePath(const QString &videoPath, const QString &language, bool translate = false);
QString aiSubtitlePathFor(const QString &videoPath, const QString &language, bool translate, bool folderWritable);

// 음성을 16kHz 모노 16bit WAV로 추출합니다 (호출 스레드를 막음). 실패 시 오류 문구, 취소 시 "취소됨"
QString extractAudioWav(const QString &videoPath, const QString &wavPath, const std::function<bool()> &cancelled = {});

// 백그라운드 AI 자막 생성 작업. 신호는 모두 소유 스레드에서 발생합니다.
class AiSubtitleJob : public QObject {
    Q_OBJECT
public:
    AiSubtitleJob(const QString &videoPath, qint64 durationMs, qint64 startMs = 0,
                  const QString &language = QStringLiteral("auto"), bool translate = false,
                  const QString &modelName = QStringLiteral("small-q5_1"), QObject *parent = nullptr);
    ~AiSubtitleJob() override;   // 취소 후 작업 스레드가 끝날 때까지 기다립니다

    void start();
    void cancel();
    bool isRunning() const;
    QString detectedLanguage() const;

signals:
    void segments(const jvp::ai::Segments &batch);           // 인식된 문장 (0.5초마다 모아서)
    void status(const QString &text, double fraction);
    void done(const QString &srtPath, const QString &language, const QString &error);   // error "취소됨" 가능

private:
    void run();
    QString transcribe(const QString &binary, const QString &model, const QString &wav, qint64 offsetMs,
                       qint64 lengthMs);
    void flush(Segments &batch);

    QString m_videoPath;
    qint64 m_durationMs;
    qint64 m_startMs;
    QString m_language;
    bool m_translate;
    QString m_modelName;
    QThread *m_thread = nullptr;
    std::atomic<bool> m_cancelled{false};
    QString m_detected;          // 작업 스레드 전용
    QString m_detectedForOwner;  // 소유 스레드용 사본 (done 때 갱신)
    Segments m_events;
};

} // namespace jvp::ai

Q_DECLARE_METATYPE(jvp::ai::Segment)
Q_DECLARE_METATYPE(jvp::ai::Segments)
