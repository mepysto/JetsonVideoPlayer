#!/usr/bin/env python3
"""NLLB-200 번역 사이드카 — C++ 앱(TranslationJob의 local 엔진)이 QProcess로 실행합니다.

C++용 CTranslate2 패키지가 없어, setup_translator.sh가 설치한 파이썬 라이브러리(ctranslate2, sentencepiece)를
그대로 씁니다. 설치 위치는 파이썬 버전(jetson_player/ai/translate.py)과 같습니다:
  $JVP_NLLB_DIR (기본 ~/.local/share/jetson_video_player/nllb) / pylib, model

프로토콜 (한 줄에 JSON 하나, UTF-8):
  시작 후  → {"ready": true}  또는  {"error": "..."} (그리고 종료)
  요청     ← {"id": 1, "lines": ["..."], "source": "en", "target": "ko"}
  응답     → {"id": 1, "translations": ["..."]}  또는  {"id": 1, "error": "..."}
stdin이 닫히면 종료합니다 (모델 메모리 약 1.2GB를 바로 돌려줌).
"""
import argparse
import json
import os
import sys

NLLB_HOME = os.environ.get("JVP_NLLB_DIR", os.path.expanduser("~/.local/share/jetson_video_player/nllb"))
NLLB_CODES = {"ko": "kor_Hang", "en": "eng_Latn", "ja": "jpn_Jpan", "zh": "zho_Hans",
              "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "ru": "rus_Cyrl"}


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    pylib, model = os.path.join(NLLB_HOME, "pylib"), os.path.join(NLLB_HOME, "model")
    if pylib not in sys.path:
        sys.path.append(pylib)   # 시스템 파이썬 패키지(numpy 등)를 건드리지 않는 전용 설치 폴더
    try:
        import ctranslate2
        import sentencepiece
        translator = ctranslate2.Translator(model, device="cpu", compute_type="int8", intra_threads=args.threads)
        sp = sentencepiece.SentencePieceProcessor(model_file=os.path.join(model, "sentencepiece.bpe.model"))
    except Exception as e:   # noqa: BLE001 — 어떤 실패든 C++ 쪽에 문구로 전달
        send({"error": f"번역 엔진을 불러오지 못했습니다: {e}"})
        return 1
    send({"ready": True})

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        req_id = None
        try:
            req = json.loads(raw)
            req_id = req.get("id")
            lines = [str(x) for x in req.get("lines", [])]
            src = NLLB_CODES.get(req.get("source") or "en", "eng_Latn")
            tgt = NLLB_CODES[req.get("target") or "ko"]
            tokens = [sp.encode(line, out_type=str) + ["</s>", src] for line in lines]
            results = translator.translate_batch(tokens, target_prefix=[[tgt]] * len(lines), beam_size=2,
                                                 max_batch_size=16) if lines else []
            out = []
            for r in results:
                text = sp.decode(r.hypotheses[0][1:]).replace("⁇", "")
                out.append(" ".join(text.split()))
            send({"id": req_id, "translations": out})
        except Exception as e:   # noqa: BLE001
            send({"id": req_id, "error": str(e)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
