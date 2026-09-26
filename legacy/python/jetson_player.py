#!/usr/bin/env python3
"""호환용 실행 진입점 (bin/jetson-player, install.sh가 이 파일을 실행합니다).

실제 구현은 jetson_player/ 패키지에 있습니다. `python3 -m jetson_player`로도 실행할 수 있습니다.
"""
from jetson_player.app import main

if __name__ == "__main__":
    main()
