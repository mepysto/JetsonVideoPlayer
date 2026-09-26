#pragma once
// libass로 ASS/SSA 자막을 원래 스타일·위치·효과 그대로 그립니다.
// 파이썬 버전은 Cairo로 ASS를 직접 흉내 냈지만(정적인 모양만), libass는 \t \fad \move \k 등까지 명세대로 처리합니다.
//
// 스레드: 인스턴스마다 ASS_Library/ASS_Renderer를 따로 두고, 모든 공개 메서드는 내부 뮤텍스로 직렬화됩니다.
// 그래서 GStreamer 스트리밍 스레드의 addChunk()와 렌더 스레드의 render()가 겹쳐도 안전하지만,
// 한 번에 한 스레드만 libass 안에 들어가므로 render()를 여러 스레드에서 동시에 부르는 것은 이득이 없습니다.

#include "SubtitleParse.h"

#include <QByteArray>
#include <QImage>
#include <QMutex>
#include <QSize>
#include <QString>

struct ass_library;
struct ass_renderer;
struct ass_track;

namespace jvp {

class AssRenderer
{
public:
    AssRenderer();
    ~AssRenderer();
    AssRenderer(const AssRenderer &) = delete;
    AssRenderer &operator=(const AssRenderer &) = delete;

    // 파일 전체 읽기 (인코딩은 readSubtitleText와 같게 자동 감지 → UTF-8로 libass에 넘김)
    bool loadFile(const QString &path);
    bool loadData(const QString &content);
    // MKV 내장 ASS: CodecPrivate(스크립트 헤더 + 스타일) → 이후 블록을 addChunk로 조금씩
    bool loadEmbeddedHeader(const QByteArray &codecPrivate);
    // Matroska 블록 "ReadOrder,Layer,Style,Name,MarginL,MarginR,MarginV,Effect,Text".
    // 탐색 후 같은 블록이 다시 와도 libass가 ReadOrder로 걸러냅니다.
    void addChunk(const QByteArray &data, qint64 startMs, qint64 durationMs);
    // MKV 첨부 글꼴 (스크립트가 요구하는 글꼴이 파일에 들어 있을 때)
    void addFont(const QString &name, const QByteArray &data);

    bool hasTrack() const;
    int eventCount() const;
    QSize playRes() const;
    // 검색·번역용 순수 텍스트 대사 (시작 순)
    SubtitleEvents plainEvents() const;

    // 원본 영상 크기 (화면비 보정용). 설정하지 않으면 libass가 프레임 크기를 기준으로 삼습니다.
    void setStorageSize(const QSize &size);

    // timeMs에 보이는 자막을 frameSize(출력 픽셀) 기준으로 그립니다. fontScale은 사용자 글자 크기 배율
    // (libass는 \pos 등으로 위치를 박은 간판에는 배율을 적용하지 않아 화면 구성이 깨지지 않습니다).
    // 결과는 ARGB32 premultiplied, 내용이 있는 영역만 잘라 돌려주며 image.offset()이 프레임 안 위치입니다.
    // 보일 것이 없으면 null QImage. *changed: 직전 호출과 결과가 달라졌는지 (같으면 다시 그릴 필요 없음).
    QImage render(qint64 timeMs, const QSize &frameSize, qreal fontScale = 1.0, bool *changed = nullptr);

private:
    void resetTrack();
    bool configure(const QSize &frameSize, qreal fontScale);

    mutable QMutex m_mutex;
    ass_library *m_library = nullptr;
    ass_renderer *m_renderer = nullptr;
    ass_track *m_track = nullptr;
    QSize m_frameSize;
    QSize m_storageSize;
    qreal m_fontScale = 1.0;
    bool m_fontsReady = false;
    bool m_dirty = true;      // 설정·트랙이 바뀌어 다음 결과를 "바뀜"으로 보고해야 함
    QImage m_last;
};

} // namespace jvp
