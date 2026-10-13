"""Corta o trecho longo (5-6 min) em 16:9, sem virar Short: sem crop vertical,
sem legenda queimada e sem musica de fundo (e uma conversa, a voz e o foco).
Mantem a logo como marca d'agua discreta no canto superior direito."""
import os
import subprocess

from cut_shorts import LOGO_PATH, WATERMARK_OPACITY, _seconds_to_ts

LONG_DIR = "long"

# Moldura opcional: PNG com centro transparente em assets/moldura.png.
# Se o arquivo nao existir, o corte sai sem moldura.
FRAME_PATH = os.path.join(os.path.dirname(LOGO_PATH), "moldura.png")
# 1.0 = video em tela cheia e a moldura cobre as bordas dele.
# Menor que 1 (ex: 0.92) = video encolhido e centralizado, para a moldura
# ficar ao redor sem cobrir conteudo (fundo preto). Ajuste conforme a espessura.
FRAME_VIDEO_SCALE = float(os.environ.get("MOLDURA_VIDEO_SCALE", 1.0))
LONG_WATERMARK_WIDTH = 170  # largura da logo (video final tem 1920 de largura)
LONG_WATERMARK_MARGIN = 36


def cut_long_clip(video_path: str, video_id: str, clip: dict) -> str:
    os.makedirs(LONG_DIR, exist_ok=True)
    start, end = clip["start"], clip["end"]
    out_path = os.path.join(LONG_DIR, f"{video_id}.mp4")

    has_frame = os.path.exists(FRAME_PATH)
    has_logo = os.path.exists(LOGO_PATH)

    # Garante 1920x1080 mantendo proporcao (barras pretas se a fonte nao for 16:9)
    if has_frame and FRAME_VIDEO_SCALE < 1.0:
        w = int(1920 * FRAME_VIDEO_SCALE) // 2 * 2
        h = int(1080 * FRAME_VIDEO_SCALE) // 2 * 2
    else:
        w, h = 1920, 1080
    filter_parts = [
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[framed]"
    ]
    video_label = "framed"

    cmd = ["ffmpeg", "-y", "-ss", _seconds_to_ts(start), "-i", video_path]
    next_idx = 1

    if has_frame:
        cmd += ["-loop", "1", "-i", FRAME_PATH]
        filter_parts.append(f"[{next_idx}:v]scale=1920:1080,format=rgba[moldura]")
        filter_parts.append(f"[{video_label}][moldura]overlay=0:0:shortest=1[comframe]")
        video_label = "comframe"
        next_idx += 1

    if has_logo:  # logo por cima da moldura
        cmd += ["-loop", "1", "-i", LOGO_PATH]
        filter_parts.append(
            f"[{next_idx}:v]scale={LONG_WATERMARK_WIDTH}:-1,format=rgba,"
            f"colorchannelmixer=aa={WATERMARK_OPACITY}[logo]"
        )
        filter_parts.append(
            f"[{video_label}][logo]overlay=main_w-overlay_w-{LONG_WATERMARK_MARGIN}:"
            f"{LONG_WATERMARK_MARGIN}:shortest=1[vout]"
        )
        video_label = "vout"
    filter_complex = ";".join(filter_parts)

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
