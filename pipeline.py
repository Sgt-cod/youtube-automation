"""Roda o pipeline completo para um video: download -> transcricao ->
highlights -> cortes -> upload."""
import argparse

import analyze_highlights
import cut_shorts
import download
import transcribe
import upload_short


def run(video_id: str, publish: bool = True):
    print(f"== 1/5 Download: {video_id} ==")
    video_path = download.download_video(video_id)
    # nota: download.main() ja checa a allowlist antes de chegar aqui

    print("== 2/5 Transcricao ==")
    transcribe.transcribe(video_path, video_id)

    print("== 3/5 Analise de highlights (Gemini) ==")
    import json, os
    with open(f"transcripts/{video_id}.json", encoding="utf-8") as f:
        segments = json.load(f)
    highlights = analyze_highlights.find_highlights_gemini(segments)
    os.makedirs("highlights", exist_ok=True)
    with open(f"highlights/{video_id}.json", "w", encoding="utf-8") as f:
        json.dump(highlights, f, ensure_ascii=False, indent=2)

    print("== 4/5 Cortando clipes ==")
    for i, clip in enumerate(highlights):
        cut_shorts.cut_clip(video_path, video_id, clip, i, segments)

    if publish:
        print("== 5/5 Publicando no YouTube ==")
        for i, clip in enumerate(highlights):
            clip_path = f"shorts/{video_id}_{i}.mp4"
            upload_short.upload_short(
                clip_path,
                clip.get("titulo", f"Corte {i+1}"),
                clip.get("motivo", ""),
                tags=["shorts"],
            )
    else:
        print("Publicacao pulada (--no-publish). Confira a pasta shorts/ antes de subir.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--no-publish", action="store_true", help="gera os clipes mas nao publica")
    args = parser.parse_args()
    run(args.video_id, publish=not args.no_publish)


if __name__ == "__main__":
    main()
