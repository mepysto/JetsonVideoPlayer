#!/usr/bin/env bash
# ==============================================================================
# AI 자막 생성 엔진(whisper.cpp, CUDA) 설치 스크립트 — 선택 설치
#   사용법: ./scripts/setup_whisper.sh [모델명]
#   모델명 기본값: small-q5_1   (더 정확한 모델: large-v3-turbo-q5_0 — 약 1.4배 느리고 메모리 +0.4GB)
#   여러 모델을 설치하면 플레이어의 ⋯ 메뉴 → "AI 인식 모델"에서 고를 수 있습니다.
#   설치 위치: ~/.local/share/jetson_video_player/whisper.cpp
# ==============================================================================
set -euo pipefail

MODEL="${1:-small-q5_1}"
PREFIX="${JVP_WHISPER_DIR:-$HOME/.local/share/jetson_video_player/whisper.cpp}"
NVCC="${NVCC:-/usr/local/cuda/bin/nvcc}"
JOBS="${JOBS:-2}"   # CUDA 커널 컴파일은 메모리를 많이 사용하므로 8GB Jetson에서는 2 권장

echo "📦 whisper.cpp 설치 위치: $PREFIX"
if [ ! -d "$PREFIX/.git" ]; then
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$PREFIX"
else
    git -C "$PREFIX" pull --ff-only || true
fi

CUDA_FLAGS=()
if [ -x "$NVCC" ]; then
    echo "⚡ CUDA 빌드 (nvcc: $NVCC)"
    CUDA_FLAGS=(-DGGML_CUDA=ON -DCMAKE_CUDA_COMPILER="$NVCC" -DCMAKE_CUDA_ARCHITECTURES=87)
else
    echo "⚠️ nvcc를 찾지 못해 CPU 빌드로 진행합니다 (느림)."
fi

cmake -S "$PREFIX" -B "$PREFIX/build" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF "${CUDA_FLAGS[@]}"
cmake --build "$PREFIX/build" --config Release -j "$JOBS" --target whisper-cli

MODEL_DIR="$PREFIX/models"
MODEL_FILE="$MODEL_DIR/ggml-$MODEL.bin"
mkdir -p "$MODEL_DIR"
if [ ! -s "$MODEL_FILE" ]; then
    echo "⬇️ 모델 다운로드: ggml-$MODEL.bin"
    curl -L --fail -o "$MODEL_FILE.part" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$MODEL.bin"
    mv "$MODEL_FILE.part" "$MODEL_FILE"
fi

echo "✅ 설치 완료"
echo "   실행 파일: $PREFIX/build/bin/whisper-cli"
echo "   모델:      $MODEL_FILE"
