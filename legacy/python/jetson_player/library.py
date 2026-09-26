"""영상 파일 탐색 유틸리티"""
import os
from urllib.parse import unquote, urlsplit


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


PLAYLIST_EXTS = {'.m3u', '.m3u8'}


def is_playlist_file(path):
    return os.path.splitext(path or "")[1].lower() in PLAYLIST_EXTS


def parse_m3u(path):
    """M3U/M3U8 재생목록의 로컬 영상 경로 목록 (상대 경로는 재생목록 파일 기준, 없는 파일·URL은 제외).

    반환: (영상 경로 목록, 건너뛴 항목 수)
    """
    base = os.path.dirname(os.path.abspath(path))
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "cp949", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    videos, skipped = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("file://"):
            line = unquote(urlsplit(line).path)
        elif "://" in line:
            skipped += 1          # 온라인 주소는 지원하지 않음
            continue
        full = os.path.normpath(line if os.path.isabs(line) else os.path.join(base, line))
        if os.path.isfile(full) and os.path.splitext(full)[1].lower() in VIDEO_EXTS:
            if full not in videos:
                videos.append(full)
        else:
            skipped += 1
    return videos, skipped


def write_m3u(paths, dest):
    """재생목록을 M3U8(UTF-8)로 저장합니다. 저장 위치 기준 상대 경로로 쓸 수 있으면 상대 경로로 씁니다."""
    base = os.path.dirname(os.path.abspath(dest))
    lines = ["#EXTM3U"]
    for p in paths:
        p = os.path.abspath(p)
        rel = os.path.relpath(p, base)
        lines.append(f"#EXTINF:-1,{os.path.splitext(os.path.basename(p))[0]}")
        lines.append(p if rel.startswith("..") else rel)
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

