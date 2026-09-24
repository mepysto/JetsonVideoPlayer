#!/usr/bin/env bash
# ==============================================================================
# AI 자막 번역 엔진(llama.cpp, CUDA) 설치 스크립트 — 선택 설치
#   사용법: ./scripts/setup_translator.sh [모델]
#   모델 기본값: qwen2.5-1.5b   (qwen2.5-3b: 품질이 더 좋지만 메모리 약 2GB 필요)
#   설치 위치: ~/.local/share/jetson_video_player/llama.cpp
#
# Whisper가 인식한 자막을 로컬 LLM으로 한국어 등으로 번역합니다 (네트워크 불필요).
# ==============================================================================
set -euo pipefail

MODEL="${1:-qwen2.5-1.5b}"
PREFIX="${JVP_LLAMA_DIR:-$HOME/.local/share/jetson_video_player/llama.cpp}"
NVCC="${NVCC:-/usr/local/cuda/bin/nvcc}"
JOBS="${JOBS:-2}"

case "$MODEL" in
    qwen2.5-1.5b) URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf" ;;
    qwen2.5-3b)   URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf" ;;
    *) echo "알 수 없는 모델: $MODEL (qwen2.5-1.5b | qwen2.5-3b)"; exit 1 ;;
esac

echo "📦 llama.cpp 설치 위치: $PREFIX"
if [ ! -d "$PREFIX/.git" ]; then
    git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$PREFIX"
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

cmake -S "$PREFIX" -B "$PREFIX/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF "${CUDA_FLAGS[@]}"
cmake --build "$PREFIX/build" --config Release -j "$JOBS" --target llama-server

MODEL_DIR="$PREFIX/models"
MODEL_FILE="$MODEL_DIR/$(basename "$URL")"
mkdir -p "$MODEL_DIR"
if [ ! -s "$MODEL_FILE" ]; then
    echo "⬇️ 모델 다운로드: $(basename "$URL")"
    curl -L --fail -o "$MODEL_FILE.part" "$URL"
    mv "$MODEL_FILE.part" "$MODEL_FILE"
fi

echo "✅ 설치 완료"
echo "   실행 파일: $PREFIX/build/bin/llama-server"
echo "   모델:      $MODEL_FILE"
