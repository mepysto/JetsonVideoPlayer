#pragma once
// 자막 트랙의 시간 조회: 재생 위치(ms)에 표시할 대사를 빠르게 찾습니다 — jetson_player/subtitles/timeline.py 이식.
// 화면 위 오버레이가 직접 그리므로 싱크/크기/트랙 선택이 바뀌어도 파이프라인을 다시 만들 필요가 없고,
// AI 자막처럼 이벤트가 백그라운드에서 계속 추가되는 트랙도 지원합니다 (모든 메서드는 스레드 안전).

#include "SubtitleParse.h"

#include <QList>
#include <QMutex>
#include <QString>
#include <memory>
#include <optional>
#include <set>
#include <tuple>

namespace jvp {

class AssRenderer;

// 자막 레이블에서 짧은 언어 뱃지("[KR] ", "[EN] " …, 없으면 빈 문자열)
QString shortBadge(const QString &label);

class SubtitleTrack
{
public:
    SubtitleTrack(const QString &label, const QString &color, const SubtitleEvents &events = {},
                  std::shared_ptr<AssRenderer> ass = nullptr);

    QString label() const
    {
        QMutexLocker lock(&m_mutex);
        return m_label;
    }
    void setLabel(const QString &label)   // AI 자막 완성·번역 중단 등 (트랙은 그대로 두고 이름만)
    {
        QMutexLocker lock(&m_mutex);
        m_label = label;
    }
    QString color() const { return m_color; }

    // ASS 원래 스타일·위치로 그리는 트랙이면 libass 렌더러 (없으면 통일된 자막 모양으로 activeLines가 그림)
    std::shared_ptr<AssRenderer> assRenderer() const;
    void setAssRenderer(std::shared_ptr<AssRenderer> ass);

    // 이벤트 추가 — 길이 0·빈 글자는 버리고, 이미 있는 (시작, 끝, 글자)는 한 번만 (탐색 후 내장 자막이 다시 옴)
    void addEvents(const SubtitleEvents &events);
    int size() const;
    SubtitleEvents events() const;

    // t 시점에 표시 중인 대사들 (시작 순, 끝 시각은 포함하지 않음)
    QStringList activeAt(qint64 tMs) const;
    // t 이후 처음으로 표시 내용이 바뀔 수 있는 시각 — 다시 그릴 시점 계산용
    std::optional<qint64> nextChangeAfter(qint64 tMs) const;

private:
    QString m_label;
    const QString m_color;
    mutable QMutex m_mutex;
    std::shared_ptr<AssRenderer> m_ass;
    SubtitleEvents m_events;   // (시작, 끝) 순
    QList<qint64> m_starts;
    qint64 m_maxDuration = 0;  // 이 길이 안쪽만 거슬러 올라가 보면 됨
    std::set<std::tuple<qint64, qint64, QString>> m_seen;
};

using SubtitleTrackPtr = std::shared_ptr<SubtitleTrack>;

struct SubtitleLine {
    QString text;
    QString color;
    bool operator==(const SubtitleLine &o) const { return text == o.text && color == o.color; }
};

// 여러 트랙에서 지금 표시할 줄 목록. offsetMs > 0이면 자막이 늦게 표시됩니다.
// 트랙이 둘 이상이면 각 대사 첫 줄에 언어 뱃지를 붙이고, ASS 렌더러가 붙은 트랙은 건너뜁니다 (따로 그림).
QList<SubtitleLine> activeLines(const QList<SubtitleTrackPtr> &tracks, qint64 positionMs, qint64 offsetMs = 0);

} // namespace jvp
