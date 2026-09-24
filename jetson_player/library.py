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
