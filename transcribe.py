"""Transcreve o video localmente com faster-whisper (sem custo, sem API)."""
import argparse
import json
import os

from faster_whisper import WhisperModel

TRANSCRIPTS_DIR = "transcripts"

# Modelos disponiveis (do menor/rapido ao maior/preciso):
# tiny, base, small, medium, large-v3
MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")


def transcribe(video_path: str, video_id: str) -> str:
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    model = WhisperModel(MODEL_SIZE, device="auto", compute_type="int8")
    segments, _info = model.transcribe(video_path, language="pt", vad_filter=True)

    result = []
    for seg in segments:
        result.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })

    out_path = os.path.join(TRANSCRIPTS_DIR, f"{video_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--video-path", required=True)
    args = parser.parse_args()

    out_path = transcribe(args.video_path, args.video_id)
    print(f"[OK] Transcricao salva em {out_path}")
    return out_path


if __name__ == "__main__":
    main()
