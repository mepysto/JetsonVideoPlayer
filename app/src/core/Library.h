#pragma once
// 영상 파일 탐색·재생목록 유틸리티 (파이썬 library.py 이식). GUI 없이 순수 파일 작업만 합니다.

#include <QString>
#include <QStringList>
#include <functional>

namespace jvp::library {

// 파이썬 os.path 대응 도우미 — 저장 파일의 경로 문자열이 파이썬 버전과 똑같아야 이어보기 등이 이어집니다.
QString absPath(const QString &path);          // os.path.abspath (심볼릭 링크는 풀지 않음)
QString extensionLower(const QString &path);   // os.path.splitext(path)[1].lower() — ".mkv"
QString stem(const QString &fileName);         // os.path.splitext(basename)[0]
bool pathExists(const QString &path);          // os.path.exists (파일·폴더)
bool isFile(const QString &path);              // os.path.isfile (링크를 따라감)

const QStringList &videoExts();                // .webm .mp4 .mkv .mov .avi .ts .m4v
bool isVideoFile(const QString &path);         // 확장자만 봅니다

// 폴더(하위 포함)의 영상 파일 목록 (정렬). 숨김 항목과 unsupported_originals 폴더는 제외, 링크는 따라감
QStringList scanVideoFiles(const QString &dirPath);

// name(경로 이름순), mtime(최근 수정 먼저), size(큰 파일 먼저)
QStringList sortVideoPaths(const QStringList &paths, const QString &mode = QStringLiteral("name"));

// 같은 폴더에 <이름>_h265.mp4 변환본이 있으면 원본 대신 씁니다 (중복·없는 파일 제외, 순서 유지)
QStringList preferH265Versions(const QStringList &paths,
                               const std::function<bool(const QString &)> &exists = pathExists);

struct MergeResult {
    QStringList playlist;   // 새 재생목록
    QStringList added;
    QStringList removed;
};
// 폴더를 다시 읽은 결과로 재생목록 갱신. root 밖의 항목과 재생 중인 영상은 사라졌어도 남깁니다.
MergeResult mergeRescanned(const QStringList &playlist, const QString &root, const QStringList &scanned,
                           const QString &current = QString());

const QStringList &playlistExts();             // .m3u .m3u8
bool isPlaylistFile(const QString &path);

struct M3uResult {
    bool ok = false;        // 파일을 읽을 수 있었는지
    QStringList videos;     // 있는 로컬 영상 (중복 제거, 순서 유지)
    int skipped = 0;        // URL·없는 파일·영상이 아닌 항목 수
};
// UTF-8(BOM 허용) → CP949 → Latin-1 순으로 해석. 상대 경로는 재생목록 파일 기준
M3uResult parseM3u(const QString &path);

// M3U8(UTF-8)로 저장. 저장 위치 아래면 상대 경로, 밖이면 절대 경로
bool writeM3u(const QStringList &paths, const QString &dest);

} // namespace jvp::library
