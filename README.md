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

## 실행

```bash
python3 jetson_player.py /path/to/video-directory
python3 jetson_player.py /path/to/video.mp4
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
