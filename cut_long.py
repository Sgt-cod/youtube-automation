"""Corta o trecho longo (5-6 min) em 16:9, sem virar Short: sem crop vertical,
sem legenda queimada e sem musica de fundo (e uma conversa, a voz e o foco).
Mantem a logo como marca d'agua discreta no canto superior direito."""
import os
import subprocess

from cut_shorts import LOGO_PATH, WATERMARK_OPACITY, _seconds_to_ts

LONG_DIR = "long"
LONG_WATERMARK_WIDTH = 170  # largura da logo (video final tem 1920 de largura)
LONG_WATERMARK_MARGIN = 36


def cut_long_clip(video_path: str, video_id: str, clip: dict) -> str:
    os.makedirs(LONG_DIR, exist_ok=True)
    start, end = clip["start"], clip["end"]
    out_path = os.path.join(LONG_DIR, f"{video_id}.mp4")

    # Garante 1920x1080 mantendo proporcao (barras pretas se a fonte nao for 16:9)
    framed = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[framed]"
    )
    cmd = ["ffmpeg", "-y", "-ss", _seconds_to_ts(start), "-i", video_path]

    if os.path.exists(LOGO_PATH):
        cmd += ["-loop", "1", "-i", LOGO_PATH]
        filter_complex = ";".join([
            framed,
            f"[1:v]scale={LONG_WATERMARK_WIDTH}:-1,format=rgba,"
            f"colorchannelmixer=aa={WATERMARK_OPACITY}[logo]",
            f"[framed][logo]overlay=main_w-overlay_w-{LONG_WATERMARK_MARGIN}:"
            f"{LONG_WATERMARK_MARGIN}:shortest=1[vout]",
        ])
        video_label = "vout"
    else:
        filter_complex = framed
        video_label = "framed"

    cmd += [
        "-t", str(end - start),
        "-filter_complex", filter_complex,
        "-map", f"[{video_label}]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path
