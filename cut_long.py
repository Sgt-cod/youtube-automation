"""Corta o trecho longo (5-6 min) em 16:9, sem virar Short: sem crop vertical,
sem legenda queimada e sem musica de fundo (e uma conversa, a voz e o foco).

Arquivos opcionais em assets/ (se nao existir, simplesmente nao e aplicado):
  moldura.png       PNG com centro transparente, por cima do corte
  logo.png          marca d'agua no canto superior direito
  intro.mp4         entra ANTES do corte
  encerramento.mp4  entra DEPOIS do corte
  cta.mp4           sobreposto no canto inferior esquerdo, a partir da METADE
                    do corte (a intro nao conta no calculo da metade)

Ordem das camadas no corte: video -> moldura -> logo -> CTA.

Previa com comentario (opcional, quando voce envia um audio no Telegram):
  [previa P&B com o SEU audio] -> intro -> corte completo -> encerramento
A previa e um trecho do proprio corte (do tamanho do audio), em preto e
branco, com o som original MUDO e o seu audio no lugar. Recebe moldura e logo
(e imagem do conteudo original), nao recebe musica nem CTA.
Intro e encerramento ficam em tela cheia, sem moldura nem logo.

Variaveis de ambiente opcionais:
  MOLDURA_VIDEO_SCALE  1.0 = video em tela cheia (padrao); 0.92 = encolhe o
                       video para a moldura ficar em volta sem cobrir nada
  CTA_WIDTH            largura da CTA em pixels (padrao 480)
  CTA_MARGIN           margem do canto esquerdo/inferior (padrao 60)
  CTA_CHROMAKEY        cor a tornar transparente, ex: 0x00FF00 (fundo verde).
                       MP4 nao guarda transparencia; sem isso a CTA aparece
                       como um retangulo.
  CTA_AUDIO            1 = mistura o som da CTA (padrao 0 = CTA muda)
  LONG_MUSIC           0 = desliga a musica de fundo (padrao 1)
  LONG_MUSIC_VOLUME    volume da musica (padrao = o mesmo dos shorts, 0.06)

  PREVIEW_MAX_SECONDS  duracao maxima da previa/audio (padrao 90)

Musica de fundo: sorteada de assets/musicas/ (mesma pasta dos shorts), em
loop se for menor que o corte. Toca so durante o corte principal, nao sobre a
intro e o encerramento.
"""
import json
import os
import subprocess

from cut_shorts import LOGO_PATH, MUSIC_VOLUME, WATERMARK_OPACITY, _pick_random_music, _seconds_to_ts

LONG_DIR = "long"
ASSETS_DIR = os.path.dirname(LOGO_PATH)
FRAME_PATH = os.path.join(ASSETS_DIR, "moldura.png")
INTRO_PATH = os.path.join(ASSETS_DIR, "intro.mp4")
OUTRO_PATH = os.path.join(ASSETS_DIR, "encerramento.mp4")
CTA_PATH = os.path.join(ASSETS_DIR, "cta.mp4")

LONG_WATERMARK_WIDTH = 170
LONG_WATERMARK_MARGIN = 36

FRAME_VIDEO_SCALE = float(os.environ.get("MOLDURA_VIDEO_SCALE", 1.0))
CTA_WIDTH = int(os.environ.get("CTA_WIDTH", 480))
CTA_MARGIN = int(os.environ.get("CTA_MARGIN", 60))
CTA_CHROMAKEY = os.environ.get("CTA_CHROMAKEY", "").strip()
CTA_AUDIO = os.environ.get("CTA_AUDIO", "0") == "1"
LONG_MUSIC = os.environ.get("LONG_MUSIC", "1") != "0"
LONG_MUSIC_VOLUME = float(os.environ.get("LONG_MUSIC_VOLUME", MUSIC_VOLUME))
PREVIEW_MAX_SECONDS = float(os.environ.get("PREVIEW_MAX_SECONDS", 90))

FPS = 30
FIT_1080 = (
    "scale=1920:1080:force_original_aspect_ratio=decrease,"
    "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
)
STEREO = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def _probe(path: str) -> tuple[float, bool]:
    """(duracao em segundos, tem audio?)"""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", path],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return float(data["format"]["duration"]), has_audio


def cut_long_clip(
    video_path: str,
    video_id: str,
    clip: dict,
    preview_audio: str | None = None,
    preview_offset: float = 0.0,
) -> str:
    """preview_audio: audio do comentario introdutorio (opcional).
    preview_offset: segundo DENTRO do corte onde a previa comeca (padrao 0)."""
    os.makedirs(LONG_DIR, exist_ok=True)
    start, end = clip["start"], clip["end"]
    main_dur = end - start
    out_path = os.path.join(LONG_DIR, f"{video_id}.mp4")

    cmd = ["ffmpeg", "-y"]
    parts: list[str] = []
    n_inputs = 0

    def add_input(*args) -> int:
        nonlocal n_inputs
        cmd.extend(args)
        n_inputs += 1
        return n_inputs - 1

    has_intro = os.path.exists(INTRO_PATH)
    has_outro = os.path.exists(OUTRO_PATH)
    has_frame = os.path.exists(FRAME_PATH)
    has_logo = os.path.exists(LOGO_PATH)
    has_cta = os.path.exists(CTA_PATH)

    intro = add_input("-i", INTRO_PATH) if has_intro else None
    main = add_input("-ss", _seconds_to_ts(start), "-t", f"{main_dur:.3f}", "-i", video_path)
    outro = add_input("-i", OUTRO_PATH) if has_outro else None
    frame = add_input("-loop", "1", "-i", FRAME_PATH) if has_frame else None
    logo = add_input("-loop", "1", "-i", LOGO_PATH) if has_logo else None
    cta = add_input("-i", CTA_PATH) if has_cta else None
    music_path = _pick_random_music() if LONG_MUSIC else None
    # -stream_loop -1: repete a musica ate o fim do corte se ela for mais curta
    music = add_input("-stream_loop", "-1", "-i", music_path) if music_path else None

    # previa: trecho do proprio corte, do tamanho do audio enviado
    pv = pa = pframe = plogo = None
    if preview_audio:
        adur, _ = _probe(preview_audio)
        adur = min(adur, PREVIEW_MAX_SECONDS, main_dur)
        off = max(0.0, min(float(preview_offset), main_dur - adur))
        print(f"Previa: {adur:.1f}s do corte, a partir de {off:.1f}s dentro dele")
        pv = add_input("-ss", _seconds_to_ts(start + off), "-t", f"{adur:.3f}", "-i", video_path)
        pa = add_input("-t", f"{adur:.3f}", "-i", preview_audio)
        pframe = add_input("-loop", "1", "-i", FRAME_PATH) if has_frame else None
        plogo = add_input("-loop", "1", "-i", LOGO_PATH) if has_logo else None

    # ---------------- corte principal (video)
    if has_frame and FRAME_VIDEO_SCALE < 1.0:
        w = int(1920 * FRAME_VIDEO_SCALE) // 2 * 2
        h = int(1080 * FRAME_VIDEO_SCALE) // 2 * 2
        fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
               "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1")
    else:
        fit = FIT_1080
    parts.append(f"[{main}:v]{fit},fps={FPS}[v0]")
    label = "v0"

    if has_frame:
        parts.append(f"[{frame}:v]scale=1920:1080,format=rgba[moldura]")
        parts.append(f"[{label}][moldura]overlay=0:0:shortest=1[v1]")
        label = "v1"

    if has_logo:
        parts.append(
            f"[{logo}:v]scale={LONG_WATERMARK_WIDTH}:-1,format=rgba,"
            f"colorchannelmixer=aa={WATERMARK_OPACITY}[logo]"
        )
        parts.append(
            f"[{label}][logo]overlay=main_w-overlay_w-{LONG_WATERMARK_MARGIN}:"
            f"{LONG_WATERMARK_MARGIN}:shortest=1[v2]"
        )
        label = "v2"

    # ---------------- audio do corte principal
    parts.append(f"[{main}:a]{STEREO}[a0]")
    audio_label = "a0"

    if music_path:
        print(f"Musica de fundo: {os.path.basename(music_path)} (volume {LONG_MUSIC_VOLUME})")
        parts.append(f"[{music}:a]{STEREO},volume={LONG_MUSIC_VOLUME}[bg]")
        parts.append(
            f"[{audio_label}][bg]amix=inputs=2:duration=first:"
            "dropout_transition=0:normalize=0[a_music]"
        )
        audio_label = "a_music"

    # ---------------- CTA no meio do corte
    if has_cta:
        cta_dur, cta_has_audio = _probe(CTA_PATH)
        mid = main_dur / 2
        key = f"colorkey={CTA_CHROMAKEY}:0.3:0.1," if CTA_CHROMAKEY else ""
        parts.append(
            f"[{cta}:v]scale={CTA_WIDTH}:-2,{key}format=rgba,"
            f"setpts=PTS-STARTPTS+{mid:.3f}/TB[ctav]"
        )
        parts.append(
            f"[{label}][ctav]overlay=x={CTA_MARGIN}:y=main_h-overlay_h-{CTA_MARGIN}:"
            f"eof_action=pass:enable='between(t,{mid:.3f},{mid + cta_dur:.3f})'[v3]"
        )
        label = "v3"
        if CTA_AUDIO and cta_has_audio:
            ms = int(mid * 1000)
            parts.append(f"[{cta}:a]{STEREO},adelay={ms}|{ms}[ctaa]")
            parts.append(
                f"[{audio_label}][ctaa]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0[a1]"
            )
            audio_label = "a1"

    parts.append(f"[{label}]format=yuv420p[vmain]")

    # ---------------- intro / encerramento + concatenacao
    segments = []  # (video_label, audio_label) na ordem final

    if preview_audio:
        # video em preto e branco; audio original descartado (nem e mapeado)
        parts.append(f"[{pv}:v]{fit},fps={FPS},hue=s=0[pv0]")
        plabel = "pv0"
        if has_frame:
            parts.append(f"[{pframe}:v]scale=1920:1080,format=rgba[pmoldura]")
            parts.append(f"[{plabel}][pmoldura]overlay=0:0:shortest=1[pv1]")
            plabel = "pv1"
        if has_logo:
            parts.append(
                f"[{plogo}:v]scale={LONG_WATERMARK_WIDTH}:-1,format=rgba,"
                f"colorchannelmixer=aa={WATERMARK_OPACITY}[plogo]"
            )
            parts.append(
                f"[{plabel}][plogo]overlay=main_w-overlay_w-{LONG_WATERMARK_MARGIN}:"
                f"{LONG_WATERMARK_MARGIN}:shortest=1[pv2]"
            )
            plabel = "pv2"
        parts.append(f"[{plabel}]format=yuv420p[vpreview]")
        # loudnorm iguala o volume da sua voz ao do corte; apad/atrim travam a duracao
        parts.append(
            f"[{pa}:a]{STEREO},loudnorm=I=-16:TP=-1.5:LRA=11,{STEREO},"
            f"apad=whole_dur={adur:.3f},atrim=duration={adur:.3f},asetpts=N/SR/TB[apreview]"
        )
        segments.append(("vpreview", "apreview"))

    def add_bumper(idx: int, path: str, name: str):
        dur, has_audio = _probe(path)
        parts.append(f"[{idx}:v]{FIT_1080},fps={FPS},format=yuv420p[v_{name}]")
        if has_audio:
            parts.append(f"[{idx}:a]{STEREO}[a_{name}]")
        else:  # bumper sem audio: gera silencio para manter a sincronia
            parts.append(
                f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.3f},"
                f"asetpts=N/SR/TB[a_{name}]"
            )
        segments.append((f"v_{name}", f"a_{name}"))

    if has_intro:
        add_bumper(intro, INTRO_PATH, "intro")
    segments.append(("vmain", audio_label))
    if has_outro:
        add_bumper(outro, OUTRO_PATH, "outro")

    if len(segments) == 1:
        vout, aout = segments[0]
    else:
        chain = "".join(f"[{v}][{a}]" for v, a in segments)
        parts.append(f"{chain}concat=n={len(segments)}:v=1:a=1[vout][aout]")
        vout, aout = "vout", "aout"

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", f"[{vout}]", "-map", f"[{aout}]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def extract_frame(video_path: str, out_path: str, at_seconds: float) -> str:
    """Extrai 1 frame (1280x720, JPEG) para usar de thumbnail automatica."""
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{at_seconds:.2f}", "-i", video_path,
         "-frames:v", "1", "-vf", "scale=1280:720", "-q:v", "2", out_path],
        check=True, capture_output=True,
    )
    return out_path
