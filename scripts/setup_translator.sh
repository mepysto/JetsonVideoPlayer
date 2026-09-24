#!/usr/bin/env bash
# ==============================================================================
# AI 자막 번역 엔진 설치 스크립트 — 선택 설치
#   사용법: ./scripts/setup_translator.sh
#   설치 위치: ~/.local/share/jetson_video_player/nllb   (약 650MB)
#
# Meta NLLB-200 (distilled 600M) 번역 전용 모델을 CTranslate2(CPU int8)로 실행합니다 (네트워크 불필요).
#   - 모델 라이선스: CC-BY-NC 4.0 (비상업적 이용만 허용)
#   - 파이썬 패키지는 전용 폴더에 의존성 없이 설치하여 시스템 패키지(numpy 등)를 바꾸지 않습니다.
# ==============================================================================
set -euo pipefail

PREFIX="${JVP_NLLB_DIR:-$HOME/.local/share/jetson_video_player/nllb}"
MODEL_REPO="JustFrederik/nllb-200-distilled-600M-ct2-int8"
MODEL_FILES="config.json model.bin sentencepiece.bpe.model shared_vocabulary.txt special_tokens_map.json tokenizer_config.json"

echo "📦 번역 엔진 설치 위치: $PREFIX"
mkdir -p "$PREFIX/pylib" "$PREFIX/model"

echo "🐍 CTranslate2 / SentencePiece 설치 (전용 폴더, 의존성 없이)"
python3 -m pip install --quiet --no-deps --upgrade --target "$PREFIX/pylib" ctranslate2 sentencepiece

for f in $MODEL_FILES; do
    if [ ! -s "$PREFIX/model/$f" ]; then
        echo "⬇️ 모델 파일: $f"
        curl -L --fail -o "$PREFIX/model/$f.part" "https://huggingface.co/$MODEL_REPO/resolve/main/$f"
        mv "$PREFIX/model/$f.part" "$PREFIX/model/$f"
    fi
done

echo "🧪 동작 확인"
PYTHONPATH="$PREFIX/pylib" python3 - "$PREFIX/model" <<'PY'
import sys, os
import ctranslate2, sentencepiece
model = sys.argv[1]
tr = ctranslate2.Translator(model, device="cpu", compute_type="int8")
sp = sentencepiece.SentencePieceProcessor(model_file=os.path.join(model, "sentencepiece.bpe.model"))
r = tr.translate_batch([sp.encode("Welcome to my channel.", out_type=str) + ["</s>", "eng_Latn"]], target_prefix=[["kor_Hang"]])
print("   Welcome to my channel. →", sp.decode(r[0].hypotheses[0][1:]))
PY

echo "✅ 설치 완료 — 플레이어에서 자막을 켜고 Shift+G 로 번역하세요."
echo "   (모델 라이선스: CC-BY-NC 4.0, 비상업적 이용)"
