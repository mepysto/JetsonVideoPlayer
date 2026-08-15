# JetsonVideoPlayer

NVIDIA Jetson의 하드웨어 가속을 사용하는 GTK/GStreamer 영상 플레이어입니다.

지원 코덱은 현재 장치의 `nvv4l2decoder` 기능을 기준으로 판정하고 NVIDIA 하드웨어
디코더를 우선 사용합니다. 하드웨어 디코딩이 불가능한 코덱이나 프로파일만 H.265로
변환하며, 원본은 `unsupported_originals` 폴더에 보관합니다. 10-bit/HDR 입력은
Main10 10-bit로 보존합니다.

## UI 기능

- 폴더 내 영상 재생목록과 현재 재생 항목 표시
- 재생/일시정지, 이전/다음 영상
- 10초 전/후 탐색과 클릭 가능한 진행바
- 현재 시간/전체 재생 시간 표시
- 음량 조절
- 재생목록 열기/닫기와 모든 UI를 숨기는 영상 전용 전체화면
- 영상 종료 시 다음 항목 자동 재생
- 실제 선택 디코더와 프레임 드롭 통계 로그

## 설치 (어디서든 실행하기)

프로젝트 디렉토리에서 설치 스크립트를 실행하면 `~/.local/bin`에 등록되어 터미널 어디서든 명령어로 바로 실행할 수 있습니다:

```bash
./install.sh
```

*(시스템 전체 설치를 원할 경우 `sudo ./install.sh --system`)*

제거하려면:
```bash
./uninstall.sh
```

## 실행

설치 후 터미널 어디서든 `jetson-player` (또는 `jetson_player`) 명령어로 실행할 수 있습니다:

```bash
# 디렉토리 내 모든 동영상 연속 재생
jetson-player /path/to/video-directory

# 단일 동영상 파일 재생
jetson-player /path/to/video.mp4
```

Python 스크립트로 직접 실행할 수도 있습니다:
```bash
python3 jetson_player.py /path/to/video-directory
```

## 키보드 단축키

| 키 | 동작 |
| --- | --- |
| `Space` | 재생/일시정지 |
| `Left` / `Right` | 10초 이전/다음 |
| `P` / `N` | 이전/다음 영상 |
| `F` | 영상 전용 전체화면 전환 |
| `Esc` | 영상 전체화면 해제, 일반 화면에서는 종료 |
| `Q` | 종료 |
