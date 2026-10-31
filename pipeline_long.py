"""Pipeline do corte LONGO (5-6 min, 16:9), 1x por dia.

download -> transcricao -> escolha do trecho (Gemini + verificacao) ->
Telegram: contexto do corte + pedido de AUDIO opcional (comentario introdutorio
que vira uma previa P&B antes da intro) -> pedido da thumbnail -> corte (enquanto
voce prepara a thumbnail) -> espera a thumbnail -> upload + thumbnail.
Sem audio/thumbnail: sobe normalmente (thumbnail = frame do proprio video).

Secrets extras: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
Variaveis opcionais:
  AUDIO_WAIT_MINUTES     quanto esperar pelo audio de comentario (padrao 15)
  THUMB_WAIT_MINUTES     quanto esperar pela thumbnail (padrao 60)
  THUMB_TIMEOUT_ACTION   'publish' (padrao: publica com thumbnail automatica do
                         YouTube) ou 'private' (sobe privado p/ voce ajustar)
  LONG_MIN_SOURCE_SECONDS duracao minima do video de origem (padrao 900 = 15 min)
"""
import argparse
import json
import os
import subprocess

import analyze_highlights
import cut_long
import download
import select_video
import telegram_bot
import transcribe
import upload_long
from allowlist import assert_channel_authorized

PROCESSED_LONG_PATH = "processed_long.json"
MAX_VIDEO_ATTEMPTS = 3
LONG_MIN_SOURCE_SECONDS = int(os.environ.get("LONG_MIN_SOURCE_SECONDS", 900))
AUDIO_WAIT_MINUTES = int(os.environ.get("AUDIO_WAIT_MINUTES", 15))
THUMB_WAIT_MINUTES = int(os.environ.get("THUMB_WAIT_MINUTES", 60))
THUMB_TIMEOUT_ACTION = os.environ.get("THUMB_TIMEOUT_ACTION", "publish").lower()
THUMB_PATH = "thumbnails/long_thumb.jpg"
AUTO_THUMB_PATH = "thumbnails/long_thumb_auto.jpg"
COMMENT_AUDIO_BASE = "thumbnails/comentario"  # extensao vem do Telegram (.ogg, .mp3...)


def _fmt_dur(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}min{s:02d}s"


def _prepare(
    video_id: str, channel_id: str, api_key: str, start: float | None = None, source_title: str = "",
) -> dict:
    """Tudo ate ter o trecho escolhido. Levanta erro se algo falhar (o
    chamador tenta outro video)."""
    assert_channel_authorized(channel_id)
    channel_title = download.get_channel_title(channel_id, api_key)

    print(f"== 1/5 Download: {video_id} ==")
    video_path = download.download_video(video_id)

    print("== 2/5 Transcricao ==")
    transcribe.transcribe(video_path, video_id)
    with open(f"transcripts/{video_id}.json", encoding="utf-8") as f:
        segments = json.load(f)

    print("== 3/5 Escolha do trecho longo (Gemini) ==")
    if start is not None:
        highlights = analyze_highlights.find_clips_from_starts(
            segments, [start], analyze_highlights.LONG_CONFIG)
    else:
        highlights = analyze_highlights.find_long_highlight(segments)
    if not highlights:
        raise RuntimeError(f"Nenhum trecho longo com contexto completo em {video_id}.")
    os.makedirs("highlights", exist_ok=True)
    with open(f"highlights/{video_id}_long.json", "w", encoding="utf-8") as f:
        json.dump(highlights, f, ensure_ascii=False, indent=2)

    return {
        "video_path": video_path,
        "clip": highlights[0],
        "channel_title": channel_title,
        "source_title": source_title,
        "segments": segments,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
    }


def _snippet(text: str, limit: int, from_end: bool = False) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return "..." + text[-limit:] if from_end else text[:limit] + "..."


def _context_message(ctx: dict, titulo: str, duration: float, moment_url: str) -> str:
    clip = ctx["clip"]
    segs = ctx["segments"]
    s, e = clip.get("start_idx"), clip.get("end_idx")
    inicio = fim = ""
    if s is not None and e is not None:
        inicio = _snippet(" ".join(x["text"] for x in segs[s:s + 8]), 380)
        fim = _snippet(" ".join(x["text"] for x in segs[max(s, e - 4):e + 1]), 260, from_end=True)
    origem = ctx.get("source_title") or ""
    return (
        "🎬 Corte longo do dia escolhido!\n\n"
        f"Título: {titulo}\n"
        f"Duração do corte: {_fmt_dur(duration)}\n"
        f"Canal: {ctx['channel_title']}\n"
        + (f"Vídeo de origem: {origem}\n" if origem else "")
        + f"Momento: {moment_url}\n\n"
        f"📝 {clip.get('motivo', '')}\n\n"
        + (f"▶️ Começa com: \u201c{inicio}\u201d\n\n" if inicio else "")
        + (f"⏹ Termina com: \u201c{fim}\u201d\n\n" if fim else "")
        + "🎙 Quer gravar um COMENTÁRIO INTRODUTÓRIO? Me envie um áudio (mensagem de voz "
        f"ou arquivo) nos próximos {AUDIO_WAIT_MINUTES} min. Ele toca sobre uma prévia em "
        "preto e branco de um trecho do corte, antes da intro do canal.\n"
        "• Opcional: escreva na legenda do áudio o segundo do corte onde a prévia deve "
        "começar (ex: 45). Sem legenda, usa o início do corte.\n"
        "• Se não quiser, ignore ou responda 'pular'."
    )


def _ask_for_comment(ctx: dict, titulo: str, duration: float, moment_url: str):
    """Pergunta pelo audio de comentario. Retorna (caminho_do_audio | None, offset)."""
    telegram_bot.send_message(_context_message(ctx, titulo, duration, moment_url))
    os.makedirs("thumbnails", exist_ok=True)
    status, path, caption = telegram_bot.wait_for_audio(COMMENT_AUDIO_BASE, AUDIO_WAIT_MINUTES)
    print(f"Resultado da espera pelo audio: {status}")
    if status != "audio":
        return None, 0.0

    offset = 0.0
    if caption.strip():
        try:
            offset = analyze_highlights.parse_start_seconds(caption)[0]
        except (ValueError, IndexError):
            telegram_bot.send_message(
                f"⚠️ Não entendi a legenda '{caption}'; vou usar o início do corte.")
    try:
        dur, _ = cut_long._probe(path)
    except Exception as e:  # arquivo ilegivel
        telegram_bot.send_message(f"⚠️ Não consegui ler esse áudio ({e}). Seguindo sem comentário.")
        return None, 0.0
    note = ""
    if dur > cut_long.PREVIEW_MAX_SECONDS:
        note = f" Usei só os primeiros {int(cut_long.PREVIEW_MAX_SECONDS)}s."
    telegram_bot.send_message(f"✅ Áudio recebido ({_fmt_dur(dur)}).{note} Montando a prévia.")
    return path, offset


def _publish(video_id: str, ctx: dict, publish: bool):
    clip = ctx["clip"]
    titulo = clip.get("titulo") or "Corte do dia"
    duration = clip["end"] - clip["start"]
    moment_url = f"{ctx['video_url']}&t={int(clip['start'])}s"

    comment_audio, comment_offset = None, 0.0
    if publish:
        telegram_bot.start_session()  # ignora mensagens antigas
        comment_audio, comment_offset = _ask_for_comment(ctx, titulo, duration, moment_url)
        telegram_bot.send_message(
            "🖼 Agora me envie a THUMBNAIL (foto ou arquivo de imagem, 16:9 de preferência) "
            f"nos próximos {THUMB_WAIT_MINUTES} min.\n"
            "Ou responda 'pular' para usar um frame do próprio vídeo."
        )

    print("== 4/5 Cortando (16:9) ==")
    try:
        clip_path = cut_long.cut_long_clip(
            ctx["video_path"], video_id, clip,
            preview_audio=comment_audio, preview_offset=comment_offset,
        )
    except subprocess.CalledProcessError:
        if not comment_audio:
            raise
        print("[AVISO] Falha montando a previa; refazendo o corte sem ela.")
        telegram_bot.send_message("⚠️ Não consegui montar a prévia com o seu áudio. Vou subir o vídeo sem ela.")
        clip_path = cut_long.cut_long_clip(ctx["video_path"], video_id, clip)

    if not publish:
        print(f"Publicacao pulada (--no-publish). Arquivo: {clip_path}")
        return

    print(f"== 5/5 Aguardando thumbnail no Telegram (ate {THUMB_WAIT_MINUTES} min) ==")
    result = telegram_bot.wait_for_thumbnail(THUMB_PATH, THUMB_WAIT_MINUTES)
    print(f"Resultado da espera: {result}")

    privacy = "public"
    if result == "timeout" and THUMB_TIMEOUT_ACTION == "private":
        privacy = "private"

    description = (
        f"{clip.get('motivo', '')}\n\n"
        f"Vídeo original: {ctx['channel_title']}\n"
        f"Assista na íntegra: {ctx['video_url']}"
    ).strip()
    uploaded_id = upload_long.upload_long(
        clip_path, titulo, description, tags=["cortes", ctx["channel_title"]], privacy=privacy,
    )
    link = f"https://youtu.be/{uploaded_id}"

    thumb_file, thumb_note = None, ""
    if result == "image":
        thumb_file, thumb_note = THUMB_PATH, "Thumbnail personalizada aplicada ✅"
    else:
        # sem thumbnail sua (pular/tempo esgotado): usa um frame do proprio video
        try:
            total, _ = cut_long._probe(clip_path)
            cut_long.extract_frame(clip_path, AUTO_THUMB_PATH, total * 0.35)
            thumb_file = AUTO_THUMB_PATH
            thumb_note = ("Você pediu para pular; usei um frame do vídeo como thumbnail."
                          if result == "skip" else
                          "⏰ Tempo esgotado; usei um frame do vídeo como thumbnail.")
        except Exception as e:
            thumb_note = f"⚠️ Não consegui gerar o frame da thumbnail ({e})."

    if thumb_file:
        try:
            upload_long.set_thumbnail(uploaded_id, thumb_file)
        except Exception as e:
            thumb_note = (
                f"⚠️ Não consegui aplicar a thumbnail ({e}). "
                "Troque manualmente no YouTube Studio."
            )

    preview_note = "\nPrévia com seu comentário incluída 🎙" if comment_audio else ""
    status = "Publicado" if privacy == "public" else "Enviado como PRIVADO (ajuste e publique no Studio)"
    telegram_bot.send_message(f"✅ {status}: {titulo}\n{link}\n{thumb_note}{preview_note}")


def run(video_id: str = None, publish: bool = True, start: float | None = None):
    api_key = os.environ["YOUTUBE_API_KEY"]
    if start is not None and not video_id:
        raise ValueError("Informar o segundo de inicio exige tambem o ID do video.")
    if publish:
        for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            if not os.environ.get(var):
                raise RuntimeError(f"Secret {var} nao configurado.")

    if video_id:
        details = download.get_video_details(video_id, api_key)
        ctx = _prepare(video_id, details["channel_id"], api_key, start, details.get("title", ""))
        _publish(video_id, ctx, publish)
        select_video.mark_processed(video_id, PROCESSED_LONG_PATH)
        return

    last_error = None
    ctx = chosen_id = None
    for attempt in range(1, MAX_VIDEO_ATTEMPTS + 1):
        print(f"== 0/5 Escolhendo video (tentativa {attempt}/{MAX_VIDEO_ATTEMPTS}) ==")
        chosen_id, channel_id, title = select_video.pick_video(
            api_key, processed_path=PROCESSED_LONG_PATH, min_duration=LONG_MIN_SOURCE_SECONDS,
        )
        print(f"Selecionado: {chosen_id} (canal {channel_id}) - {title}")
        try:
            ctx = _prepare(chosen_id, channel_id, api_key, source_title=title)
            break
        except Exception as e:
            last_error = e
            print(f"[AVISO] Falha preparando {chosen_id}: {e}")
            select_video.mark_processed(chosen_id, PROCESSED_LONG_PATH)
            ctx = None
    if ctx is None:
        raise RuntimeError(
            f"Falhou em {MAX_VIDEO_ATTEMPTS} videos consecutivos. Ultimo erro: {last_error}"
        ) from last_error

    # Publicacao fora do loop de retry: se o upload falhar, nao queremos
    # cortar e anunciar OUTRO video no Telegram.
    _publish(chosen_id, ctx, publish)
    select_video.mark_processed(chosen_id, PROCESSED_LONG_PATH)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", default=None, help="ID do video (opcional)")
    parser.add_argument("--start", default=None, help="segundo em que o corte deve comecar (exige --video-id), ex: 345 ou 5:45")
    parser.add_argument("--no-publish", action="store_true", help="gera o corte mas nao usa Telegram/YouTube")
    args = parser.parse_args()
    start = None
    if args.start:
        values = analyze_highlights.parse_start_seconds(args.start)
        if len(values) != 1:
            raise ValueError("No corte longo informe apenas UM segundo de inicio.")
        start = values[0]
    run(args.video_id, publish=not args.no_publish, start=start)


if __name__ == "__main__":
    main()
