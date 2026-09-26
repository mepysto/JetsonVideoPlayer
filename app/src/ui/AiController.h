#pragma once
// AI 자막(whisper.cpp)과 자막 번역(NLLB / Claude API) 작업을 시작·취소하고,
// 만들어지는 대사를 실시간으로 자막 트랙에 넣습니다. (파이썬 ui/ai.py)

#include "SubtitleTrack.h"

#include <QJsonObject>
#include <QObject>
#include <QtQml/qqmlregistration.h>
#include <QPointer>
#include <QSet>
#include <QVariantList>

namespace jvp {

class AppController;
namespace ai {
class AiSubtitleJob;
class TranslationJob;
}

class AiController : public QObject {
    Q_OBJECT
    QML_ANONYMOUS
    Q_PROPERTY(QString menuLabel READ menuLabel NOTIFY changed)
    Q_PROPERTY(bool running READ running NOTIFY changed)
public:
    explicit AiController(AppController *app);
    ~AiController() override;

    QString menuLabel() const;
    bool running() const;
    Q_INVOKABLE QVariantList languages() const;   // [{key, name}]
    Q_INVOKABLE QVariantList models() const;      // [{name, label}] 설치된 모델

    void start();            // G: 시작 (진행 중이면 취소)
    void cancel();
    void markForAuto(const QString &path);   // YouTube로 받은 영상: 재생되면 자동 생성
    void maybeAutoStart();   // 영상 길이가 처음 확인될 때
    QJsonObject remoteStatus() const;

signals:
    void changed();

private:
    AppController *m_app;
    QPointer<ai::AiSubtitleJob> m_job;
    SubtitleTrackPtr m_track;      // 만들고 있는 트랙
    QString m_statusText;
    double m_fraction = 0;
    QSet<QString> m_autoPaths;
};

class TranslationController : public QObject {
    Q_OBJECT
    QML_ANONYMOUS
    Q_PROPERTY(QString menuLabel READ menuLabel NOTIFY changed)
    Q_PROPERTY(bool running READ running NOTIFY changed)
public:
    explicit TranslationController(AppController *app);
    ~TranslationController() override;

    QString menuLabel() const;
    bool running() const;
    void start(SubtitleTrackPtr source = nullptr);   // Shift+G (진행 중이면 취소)
    void cancel();
    QJsonObject remoteStatus() const;

signals:
    void changed();

private:
    QString entryLanguage(int index) const;

    AppController *m_app;
    QPointer<ai::TranslationJob> m_job;
    SubtitleTrackPtr m_track;
    double m_fraction = 0;
};

} // namespace jvp
