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
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")  # deve conter Bangers-Regular.ttf

MUSIC_VOLUME = 0.06        # 6% do volume original da musica de fundo
WATERMARK_OPACITY = 0.60   # 0 a 1 - quanto menor, mais transparente a logo
WATERMARK_WIDTH = 220      # largura da logo em pixels (video final tem 1080 de largura)

WORDS_PER_CAPTION = 4       # no maximo N palavras exibidas por vez (estilo karaoke)
SUBTITLE_FONT_NAME = "Bangers"
SUBTITLE_FONT_SIZE = 20     # relativo a original_size=1080x1920 (ver nota abaixo)


def _seconds_to_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _fmt_srt_time(t: float) -> str:
    t = max(t, 0)
    ms = int(round((t % 1) * 1000))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _collect_words(segments: list[dict], clip_start: float, clip_end: float) -> list[dict]:
    """Junta as palavras (com timestamp) de todos os segmentos que caem
    dentro da janela do clipe, com tempo relativo ao inicio do clipe.
    Se um segmento nao tiver timestamps por palavra (ex: transcricao
    antiga), distribui o texto uniformemente dentro da janela dele."""
    words = []
    for seg in segments:
        if seg["end"] < clip_start or seg["start"] > clip_end:
            continue
        seg_words = seg.get("words") or []
        if seg_words:
            for w in seg_words:
                if w["end"] < clip_start or w["start"] > clip_end:
                    continue
                words.append({
                    "start": max(w["start"], clip_start) - clip_start,
                    "end": min(w["end"], clip_end) - clip_start,
                    "text": w["word"].strip(),
                })
        else:
            seg_start = max(seg["start"], clip_start)
            seg_end = min(seg["end"], clip_end)
            text_words = seg["text"].strip().split()
            if not text_words:
                continue
            step = max(seg_end - seg_start, 0.01) / len(text_words)
            for i, tw in enumerate(text_words):
                words.append({
                    "start": (seg_start + i * step) - clip_start,
                    "end": (seg_start + (i + 1) * step) - clip_start,
                    "text": tw,
                })
    words.sort(key=lambda w: w["start"])
    return words


def _build_srt(segments: list[dict], clip_start: float, clip_end: float, srt_path: str):
    """Gera um .srt em blocos de poucas palavras (estilo karaoke/legenda
    dinamica), em vez da frase inteira de uma vez."""
    words = _collect_words(segments, clip_start, clip_end)

    lines = []
    idx = 1
    for i in range(0, len(words), WORDS_PER_CAPTION):
        chunk = [w for w in words[i:i + WORDS_PER_CAPTION] if w["text"]]
        if not chunk:
            continue
        chunk_start = chunk[0]["start"]
        chunk_end = max(chunk[-1]["end"], chunk_start + 0.2)
        text = " ".join(w["text"] for w in chunk)
        lines.append(str(idx))
        lines.append(f"{_fmt_srt_time(chunk_start)} --> {_fmt_srt_time(chunk_end)}")
        lines.append(text)
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

    # Notas sobre o estilo da legenda (pegadinhas do filtro "subtitles" do ffmpeg):
    # - "original_size" precisa ser informado explicitamente com a resolucao
    #   final (1080x1920), senao o filtro assume por padrao uma resolucao
    #   antiga (384x288) e o Fontsize sai desproporcional/gigante.
    # - Para centralizar verticalmente, o valor correto e Alignment=10
    #   (nao 5 - a numeracao usada aqui e a antiga do SSA, nao a de teclado
    #   numerico do ASS: 5/6/7 = topo, 9/10/11 = meio, 1/2/3 = base).
    subtitle_style = (
        f"FontName={SUBTITLE_FONT_NAME},Fontsize={SUBTITLE_FONT_SIZE},Bold=1,"
        "PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,"
        "BorderStyle=1,Outline=3,Shadow=0,Alignment=10,MarginV=0"
    )
    subtitles_filter = (
        f"subtitles={srt_path}:original_size=1080x1920:"
        f"fontsdir={FONTS_DIR}:force_style='{subtitle_style}'"
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

    filter_parts.append(f"[framed]{subtitles_filter}[vid]")
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
