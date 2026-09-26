#pragma once
// 자막 파일(SMI/SRT/VTT/ASS) 탐색·파싱과 언어 감지 — jetson_player/subtitles/parse.py 이식.
// ASS의 스타일·위치 그리기는 AssRenderer(libass)가 맡고, 여기서는 글자만 뽑습니다 (검색·번역·일반 자막 표시용).

#include <QList>
#include <QString>
#include <QStringList>

namespace jvp {

struct SubtitleEvent {
    qint64 startMs = 0;
    qint64 endMs = 0;
    QString text;
    bool operator==(const SubtitleEvent &o) const
    {
        return startMs == o.startMs && endMs == o.endMs && text == o.text;
    }
};
using SubtitleEvents = QList<SubtitleEvent>;

namespace subtitles {

extern const QStringList kSubtitleExts;   // .srt .smi .vtt .ass .ssa .sub
extern const QStringList kVideoExts;      // library.VIDEO_EXTS와 같은 목록 (자막 주인 판정용)
extern const QString kAiSubtitleColor;
extern const QStringList kFallbackPalette;
// 언어 코드(ko/en/zh/ja/es/fr/de/ru) → 색. 없는 코드면 빈 문자열.
QString languageColor(const QString &code);

// ---- 시간 ----
QString msToSrtTime(qint64 ms);
qint64 srtTimeToMs(const QString &time);   // 해석 실패 시 0
qint64 assTimeToMs(const QString &time);   // H:MM:SS.cc (실패 시 0)

// ---- 파일 읽기 ----
struct SubtitleText {
    QString content;     // 줄바꿈은 \n으로 통일 (파이썬 텍스트 모드와 같게)
    QString encoding;    // "utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16", "latin-1"
    bool ok = false;     // 파일을 열지 못하면 false
};
SubtitleText readSubtitleText(const QString &filePath);
SubtitleText decodeSubtitleBytes(const QByteArray &raw);

// ---- 포맷별 파싱 ----
SubtitleEvents parseSmiToEvents(const QString &content);
SubtitleEvents parseSrtOrVttToEvents(const QString &content);
SubtitleEvents parseAssToEvents(const QString &content);     // 스타일은 버리고 글자만 (시작 순)
// ASS 대사 텍스트({\태그}, \N, \h, 그리기 \p1 포함) → 순수 텍스트 (앞뒤 공백 제거)
QString assTextToPlain(const QString &assText);
// MKV 내장 ASS 블록 "ReadOrder,Layer,Style,Name,MarginL,MarginR,MarginV,Effect,Text" → 순수 텍스트
QString assBlockToPlain(const QString &payload);
SubtitleEvents parseSubtitleFileEvents(const QString &filePath);

// ---- 이름·언어 ----
bool isAiSubtitle(const QString &filePath);
QString subtitleLabel(const QString &filePath);
QString subtitleColor(const QString &filePath, int index = 0);
QString stripMarkup(const QString &text);

// ---- 탐색 ----
QString cachedAiSubtitleStem(const QString &videoPath);
QStringList findCachedAiSubtitles(const QString &videoPath, const QString &cacheDir = QString());
QStringList findAllMatchingSubtitles(const QString &videoPath);

} // namespace subtitles
} // namespace jvp
