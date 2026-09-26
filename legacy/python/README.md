# Jetson Video Player — 이전 Python/GTK 버전 (보관)

C++/Qt 버전(저장소 최상위 `app/`)으로 옮기기 전의 Python 3 + GTK 3 + GStreamer 구현입니다.
**기능 동결** 상태이며 버그 수정만 합니다. 브랜치 `python-legacy`, 태그 `python-final`에도 그대로 보존되어 있습니다.

```bash
./install.sh            # ~/.local/bin/jetson-player-py 로 등록 (C++ 버전의 jetson-player와 함께 쓸 수 있음)
./uninstall.sh
xvfb-run -a python3 -m pytest tests   # 테스트 217개
```

AI 자막·번역 엔진 설치 스크립트는 두 버전이 함께 쓰므로 저장소 최상위 `scripts/`에 있습니다.
설정·이어보기·북마크·썸네일·AI 자막 파일은 C++ 버전과 같은 위치·형식입니다.
