#pragma once
// 재생목록 전체 자막에서 대사를 찾아 해당 장면으로 이동하기 위한 색인 — jetson_player/subtitles/search.py 이식.
// 영상별 자막 파일의 (경로, 수정 시각)으로 캐시하므로 재생목록이 바뀌어도 바뀐 영상만 다시 읽습니다.
// build()는 백그라운드 스레드에서, search()는 어느 스레드에서든(리모컨 HTTP 스레드 포함) 부를 수 있습니다.

#include "SubtitleParse.h"

#include <QHash>
#include <QList>
#include <QMutex>
#include <QString>
#include <QStringList>
#include <functional>

namespace jvp {

struct SearchHit {
    QString video;
    qint64 startMs = 0;
    QString text;
    QString label;
};

class DialogueIndex
{
public:
    using FindSubtitles = std::function<QStringList(const QString &video)>;
    using ParseSubtitle = std::function<SubtitleEvents(const QString &subtitlePath)>;

    explicit DialogueIndex(FindSubtitles find = subtitles::findAllMatchingSubtitles,
                           ParseSubtitle parse = subtitles::parseSubtitleFileEvents);

    // 대소문자·줄바꿈·연속 공백을 무시하고 비교하기 위한 형태
    static QString normalize(const QString &text);

    // videos(재생목록)의 자막을 색인합니다. 취소되면 false. 더 새로운 build가 시작됐으면 결과를 버립니다.
    bool build(const QStringList &videos, const std::function<bool()> &cancelled = {});
    // 이 영상의 자막이 새로 생겼거나 바뀌었을 때 (다음 build에서 다시 읽음)
    void invalidate(const QString &video);
    // query가 들어 있는 대사. firstVideo(지금 보는 영상)의 결과를 먼저, 이후 재생목록 순서.
    QList<SearchHit> search(const QString &query, int limit = 200, const QString &firstVideo = QString()) const;
    int lineCount() const;

private:
    struct Line {
        qint64 startMs;
        QString norm;
        QString text;
        QString label;
    };
    using Signature = QList<QPair<QString, qint64>>; // (자막 경로, mtime ns)
    struct Entry {
        Signature sig;
        QList<Line> lines;
    };

    FindSubtitles m_find;
    ParseSubtitle m_parse;
    mutable QMutex m_mutex;
    QStringList m_videos;
    quint64 m_generation = 0;
    QHash<QString, Entry> m_entries;
};

} // namespace jvp
