#pragma once
// 자막 상태: 외부/AI/온라인 자막 트랙 목록과 선택, 내장 자막, 크기·싱크.
// 화면에 그리는 일은 SubtitleOverlay가 이 객체의 activeTracks()/positionMs()를 읽어 맡습니다.

#include "SubtitleTrack.h"

#include <QObject>
#include <QtQml/qqmlregistration.h>
#include <QSet>
#include <QStringList>
#include <QVariantList>
#include <functional>
#include <memory>

namespace jvp {

class AssRenderer;

class SubtitleController : public QObject {
    Q_OBJECT
    QML_ANONYMOUS
    Q_PROPERTY(QVariantList tracks READ tracksForQml NOTIFY changed)
    Q_PROPERTY(bool enabled READ enabled NOTIFY changed)
    Q_PROPERTY(int embeddedCount READ embeddedCount NOTIFY changed)
    Q_PROPERTY(bool embeddedEnabled READ embeddedEnabled NOTIFY changed)
    Q_PROPERTY(QString embeddedLabel READ embeddedLabel NOTIFY changed)
    Q_PROPERTY(double fontScale READ fontScale NOTIFY changed)
    Q_PROPERTY(int offsetMs READ offsetMs NOTIFY changed)
    Q_PROPERTY(QString buttonText READ buttonText NOTIFY changed)

public:
    struct Entry {
        QString path;          // 파일이 없으면 빈 문자열 (생성 중인 AI 자막)
        QString label;
        QString color;
        SubtitleTrackPtr track;
        QString lang;          // AI 자막 언어 (번역 원본 판단용)
        bool isTranslation = false;   // 번역 결과 트랙 (다시 번역할 원본으로 고르지 않음)
    };

    explicit SubtitleController(QObject *parent = nullptr);

    // 재생 위치(ms) 공급자 — 오버레이가 이 값으로 표시할 대사를 고릅니다.
    void setPositionProvider(std::function<qint64()> provider) { m_position = std::move(provider); }
    qint64 positionMs() const { return m_position ? m_position() : -1; }

    // 새 영상: 옆의 자막 파일을 찾아 읽고 기본 트랙을 켭니다.
    void loadForVideo(const QString &videoPath);
    void clear();

    // 트랙 추가 (드래그 앤 드롭, 온라인 자막, AI 자막). 인덱스 반환
    int addFile(const QString &path, bool activate = true);
    int addLive(const QString &label, const QString &color, bool isTranslation = false,
                const QString &lang = QString());   // 비어 있는 트랙 (AI 생성·번역 중)
    Entry *entry(int index);
    int indexOfTrack(const SubtitleTrackPtr &track) const;
    void removeEntry(int index);
    void updateEntry(int index, const QString &path, const QString &label, const QString &lang);
    QList<Entry> entries() const { return m_entries; }
    QSet<int> activeIndices() const { return m_active; }
    void setActiveOnly(int index);
    void notifyChanged() { emit changed(); }

    // 내장 자막 (playbin 텍스트 스트림)
    // languages: 트랙마다 언어 코드 (없으면 빈 문자열) — 개수가 곧 내장 자막 트랙 수
    void resetEmbedded(const QStringList &languages, int current);
    void setEmbeddedTracks(const QStringList &languages, int current);
    void addEmbeddedText(qint64 startMs, qint64 endMs, const QString &text);
    void addEmbeddedAss(const QString &header, qint64 startMs, qint64 endMs, const QString &block);
    SubtitleTrackPtr embeddedTrack() const { return m_embedded; }

    // 오버레이가 그릴 트랙 (켜진 외부 자막, 없으면 내장 자막)
    QList<SubtitleTrackPtr> activeTracks() const;

    bool enabled() const { return m_enabled; }
    int embeddedCount() const { return int(m_embeddedLangs.size()); }
    bool embeddedEnabled() const { return m_embeddedEnabled; }
    void setEmbeddedEnabled(bool on);
    QString embeddedLabel() const;             // "내장 자막 1/2 (eng)"
    int embeddedIndex() const { return m_embeddedIndex; }
    double fontScale() const { return m_fontScale; }
    int offsetMs() const { return m_offsetMs; }
    QString buttonText() const;
    QVariantList tracksForQml() const;

    Q_INVOKABLE void toggle();                 // S
    Q_INVOKABLE void buttonClicked();          // 자막 버튼: 하나면 켜기/끄기, 여럿이면 팝업(QML), 내장뿐이면 트랙 순환
    Q_INVOKABLE void toggleTrack(int index);
    Q_INVOKABLE void toggleEmbedded();
    Q_INVOKABLE void cycleEmbeddedTrack();
    Q_INVOKABLE void adjustScale(double delta);
    Q_INVOKABLE void resetScale();
    Q_INVOKABLE void adjustSync(int deltaMs);
    Q_INVOKABLE void resetSync();
    void setFontScale(double s);
    void setAssStyles(bool on);                // ASS 원래 스타일 사용 여부 (외부 파일은 즉시 반영)

signals:
    void changed();
    void osd(const QString &text);
    void popupRequested();                     // 자막이 여럿: 선택 팝업을 열어 달라
    void embeddedTrackRequested(int index);    // 다음 내장 트랙으로 (엔진에 전달)
    void fontScaleChanged(double scale);       // 설정에 저장

private:
    std::shared_ptr<AssRenderer> assFor(const QString &path) const;

    std::function<qint64()> m_position;
    QList<Entry> m_entries;
    QSet<int> m_active;
    bool m_enabled = true;
    bool m_assStyles = true;
    SubtitleTrackPtr m_embedded;
    std::shared_ptr<AssRenderer> m_embeddedAss;
    QStringList m_embeddedLangs;
    int m_embeddedIndex = 0;
    bool m_embeddedEnabled = true;
    double m_fontScale = 1.0;
    int m_offsetMs = 0;
};

} // namespace jvp
