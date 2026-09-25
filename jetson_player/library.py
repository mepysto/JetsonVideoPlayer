"""영상 파일 탐색 유틸리티"""
import os


VIDEO_EXTS = {'.webm', '.mp4', '.mkv', '.mov', '.avi', '.ts', '.m4v'}


def scan_video_files(dir_path):
    """디렉토리(하위 폴더 포함)의 재생 가능한 영상 파일 목록을 정렬하여 반환합니다.
    백업 폴더(unsupported_originals)와 숨김 파일/폴더는 제외합니다."""
    found = []
    for root, dirs, files in os.walk(dir_path, followlinks=True):
        dirs[:] = sorted([d for d in dirs if d != "unsupported_originals" and not d.startswith('.')])
        for fname in sorted(files):
            if fname.startswith('.'):
                continue
            if os.path.splitext(fname)[1].lower() in VIDEO_EXTS:
                full_p = os.path.join(root, fname)
                if os.path.isfile(full_p):
                    found.append(full_p)
    found.sort()
    return found


def sort_video_paths(paths, mode="name"):
    """재생목록 정렬: name(경로 이름순), mtime(최근 수정 먼저), size(큰 파일 먼저)"""
    def stat_or_zero(path, attr):
        try:
            return getattr(os.stat(path), attr)
        except OSError:
            return 0

    if mode == "mtime":
        return sorted(paths, key=lambda p: (-stat_or_zero(p, "st_mtime"), p))
    if mode == "size":
        return sorted(paths, key=lambda p: (-stat_or_zero(p, "st_size"), p))
    return sorted(paths)


def prefer_h265_versions(paths, exists=os.path.exists):
    """같은 폴더에 <이름>_h265.mp4 변환본이 있으면 원본 대신 변환본을 씁니다 (중복·없는 파일 제외, 순서 유지)."""
    result, done = [], set()
    path_set = set(paths)
    for path in paths:
        if path in done or not exists(path):
            continue
        stem, _ext = os.path.splitext(os.path.basename(path))
        final = path
        if not stem.endswith("_h265"):
            h265 = os.path.join(os.path.dirname(path), f"{stem}_h265.mp4")
            if h265 in path_set or exists(h265):
                final = h265
                done.add(path)
        if final not in result:
            result.append(final)
            done.add(final)
    return result


def merge_rescanned(playlist, root, scanned, current=None):
    """폴더를 다시 읽은 결과(scanned, root 아래 영상)로 재생목록을 갱신합니다.

    root 밖에서 추가된 항목(YouTube 받은 영상 등)과 지금 재생 중인 영상은 사라졌어도 남깁니다.
    반환: (새 재생목록, 추가된 경로 목록, 제거된 경로 목록)
    """
    root = os.path.abspath(root)
    inside = lambda p: p == root or p.startswith(root.rstrip(os.sep) + os.sep)  # noqa: E731
    scanned_set = set(scanned)
    kept_outside = [p for p in playlist if not inside(p)]
    new = list(scanned) + [p for p in kept_outside if p not in scanned_set]
    if current and current not in new:
        new.append(current)
    old_set = set(playlist)
    added = [p for p in new if p not in old_set]
    removed = [p for p in playlist if p not in set(new)]
    return new, added, removed

