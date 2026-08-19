"""Corta os trechos indicados, converte para 9:16 e queima legenda com ffmpeg."""
import argparse
import json
import os
import subprocess

SHORTS_DIR = "shorts"


def _seconds_to_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _build_srt(segments: list[dict], clip_start: float, clip_end: float, srt_path: str):
    """Gera um .srt so com as falas dentro da janela do clipe, tempo relativo."""
    def fmt(t):
        ms = int((t % 1) * 1000)
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    idx = 1
    for seg in segments:
        if seg["end"] < clip_start or seg["start"] > clip_end:
            continue
        rel_start = max(seg["start"], clip_start) - clip_start
        rel_end = min(seg["end"], clip_end) - clip_start
        lines.append(str(idx))
        lines.append(f"{fmt(rel_start)} --> {fmt(rel_end)}")
        lines.append(seg["text"].strip())
        lines.append("")
        idx += 1

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def cut_clip(video_path: str, video_id: str, clip: dict, index: int, segments: list[dict]) -> str:
    os.makedirs(SHORTS_DIR, exist_ok=True)

    start, end = clip["start"], clip["end"]
    duration = end - start

    srt_path = os.path.join(SHORTS_DIR, f"{video_id}_{index}.srt")
    _build_srt(segments, start, end, srt_path)

    out_path = os.path.join(SHORTS_DIR, f"{video_id}_{index}.mp4")

    # Corta, centraliza/corta para 9:16 (1080x1920) e queima a legenda.
    vf = (
        "crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',"
        "scale=1080:1920,"
        f"subtitles={srt_path}:force_style='Fontsize=20,PrimaryColour=&HFFFFFF&,"
        "OutlineColour=&H000000&,BorderStyle=3'"
    )

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", _seconds_to_ts(start),
            "-i", video_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac",
            out_path,
        ],
        check=True,
    )
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--video-path", required=True)
    args = parser.parse_args()

    with open(f"transcripts/{args.video_id}.json", "r", encoding="utf-8") as f:
        segments = json.load(f)
    with open(f"highlights/{args.video_id}.json", "r", encoding="utf-8") as f:
        highlights = json.load(f)

    outputs = []
    for i, clip in enumerate(highlights):
        path = cut_clip(args.video_path, args.video_id, clip, i, segments)
        outputs.append({"path": path, "titulo": clip.get("titulo", "")})
        print(f"[OK] Clipe {i} gerado em {path}")

    return outputs


if __name__ == "__main__":
    main()
