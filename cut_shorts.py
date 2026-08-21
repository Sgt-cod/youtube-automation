"""Corta os trechos indicados, converte para 9:16, aplica marca d'agua e
musica de fundo, e queima legenda com ffmpeg."""
import argparse
import glob
import json
import os
import random
import subprocess

SHORTS_DIR = "shorts"
ASSETS_DIR = "assets"
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
MUSIC_DIR = os.path.join(ASSETS_DIR, "musicas")

MUSIC_VOLUME = 0.06        # 6% do volume original da musica de fundo
WATERMARK_OPACITY = 0.35   # 0 a 1 - quanto menor, mais transparente a logo
WATERMARK_WIDTH = 220      # largura da logo em pixels (video final tem 1080 de largura)


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


def _pick_random_music() -> str | None:
    if not os.path.isdir(MUSIC_DIR):
        return None
    files = [f for f in glob.glob(os.path.join(MUSIC_DIR, "*")) if os.path.isfile(f)]
    return random.choice(files) if files else None


def cut_clip(
    video_path: str,
    video_id: str,
    clip: dict,
    index: int,
    segments: list[dict],
    split_screen: bool = False,
) -> str:
    os.makedirs(SHORTS_DIR, exist_ok=True)
    start, end = clip["start"], clip["end"]
    duration = end - start

    srt_path = os.path.join(SHORTS_DIR, f"{video_id}_{index}.srt")
    _build_srt(segments, start, end, srt_path)
    out_path = os.path.join(SHORTS_DIR, f"{video_id}_{index}.mp4")

    # Legenda menor e centralizada verticalmente (Alignment=5 = meio-centro
    # no padrao ASS/libass, em vez do padrao "colado embaixo").
    subtitle_style = (
        "Fontsize=14,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,"
        "BorderStyle=3,Alignment=5,MarginV=0"
    )

    filter_parts = []

    if split_screen:
        # Video em tela dividida (2 pessoas lado a lado): cortar so uma
        # faixa central mostraria a linha de divisao sem os rostos. Em vez
        # disso, pega metade esquerda e metade direita inteiras e empilha
        # uma em cima da outra, preenchendo o formato 9:16.
        filter_parts.append("[0:v]split=2[left_in][right_in]")
        filter_parts.append("[left_in]crop=iw/2:ih:0:0,scale=1080:960[left_half]")
        filter_parts.append("[right_in]crop=iw/2:ih:iw/2:0,scale=1080:960[right_half]")
        filter_parts.append("[left_half][right_half]vstack=inputs=2[framed]")
    else:
        filter_parts.append(
            "[0:v]crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',scale=1080:1920[framed]"
        )

    filter_parts.append(f"[framed]subtitles={srt_path}:force_style='{subtitle_style}'[vid]")
    video_label = "vid"

    has_logo = os.path.exists(LOGO_PATH)
    music_path = _pick_random_music()

    cmd = ["ffmpeg", "-y", "-ss", _seconds_to_ts(start), "-i", video_path]
    next_input_idx = 1
    logo_idx = None
    music_idx = None

    if has_logo:
        # -loop 1 faz o ffmpeg tratar a imagem estatica como um "video"
        # continuo, necessario para o overlay durar o clipe inteiro.
        cmd += ["-loop", "1", "-i", LOGO_PATH]
        logo_idx = next_input_idx
        next_input_idx += 1

    if music_path:
        # -stream_loop -1 repete a musica indefinidamente, caso ela seja
        # mais curta que o clipe; o -t no final corta no tamanho certo.
        cmd += ["-stream_loop", "-1", "-i", music_path]
        music_idx = next_input_idx
        next_input_idx += 1

    if has_logo:
        filter_parts.append(
            f"[{logo_idx}:v]scale={WATERMARK_WIDTH}:-1,format=rgba,"
            f"colorchannelmixer=aa={WATERMARK_OPACITY}[logo]"
        )
        # centralizada horizontalmente, um pouco abaixo do centro do video
        # (onde fica a legenda, que agora esta centralizada verticalmente)
        filter_parts.append(
            f"[{video_label}][logo]overlay=(main_w-overlay_w)/2:(main_h/2)+200[vout]"
        )
        video_label = "vout"

    if music_path:
        filter_parts.append(f"[{music_idx}:a]volume={MUSIC_VOLUME}[bg_music]")
        filter_parts.append(
            "[0:a][bg_music]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_map = "0:a"

    filter_complex = ";".join(filter_parts)

    cmd += [
        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", f"[{video_label}]",
        "-map", audio_map,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac",
        out_path,
    ]

    subprocess.run(cmd, check=True)
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--video-path", required=True)
    parser.add_argument(
        "--split-screen", action="store_true",
        help="Use se o video de origem tem 2 pessoas lado a lado.",
    )
    args = parser.parse_args()
    with open(f"transcripts/{args.video_id}.json", "r", encoding="utf-8") as f:
        segments = json.load(f)
    with open(f"highlights/{args.video_id}.json", "r", encoding="utf-8") as f:
        highlights = json.load(f)
    outputs = []
    for i, clip in enumerate(highlights):
        path = cut_clip(
            args.video_path, args.video_id, clip, i, segments,
            split_screen=args.split_screen,
        )
        outputs.append({"path": path, "titulo": clip.get("titulo", "")})
        print(f"[OK] Clipe {i} gerado em {path}")
    return outputs


if __name__ == "__main__":
    main()
