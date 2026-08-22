"""Roda o pipeline completo para um video: download -> transcricao ->
highlights -> cortes -> upload."""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import analyze_highlights
import cut_shorts
import download
import select_video
import thumbnail
import transcribe
import upload_short
from allowlist import assert_channel_authorized, get_channel_info

# 1o short publica na hora; os demais sao programados com esses offsets.
SCHEDULE_OFFSETS_HOURS = [0, 2, 4]


def _schedule_time(base_time: datetime, index: int) -> str | None:
    """None = publica imediatamente. Caso contrario, retorna o horario
    (ISO 8601 UTC) em que o YouTube deve publicar automaticamente."""
    if index == 0:
        return None
    if index < len(SCHEDULE_OFFSETS_HOURS):
        offset = SCHEDULE_OFFSETS_HOURS[index]
    else:
        # fallback caso um dia existam mais de 3 clipes: continua +2h a cada um
        offset = SCHEDULE_OFFSETS_HOURS[-1] + 2 * (index - len(SCHEDULE_OFFSETS_HOURS) + 1)
    return (base_time + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(video_id: str = None, publish: bool = True):
    api_key = os.environ["YOUTUBE_API_KEY"]

    if video_id:
        # video-id veio manual (workflow_dispatch): ainda precisa validar o canal
        details = download.get_video_details(video_id, api_key)
        channel_id = details["channel_id"]
        video_title = details["title"]
    else:
        print("== 0/5 Escolhendo video automaticamente ==")
        video_id, channel_id, video_title = select_video.pick_video(api_key)
        print(f"Selecionado: {video_id} (canal {channel_id}) - {video_title}")

    assert_channel_authorized(channel_id)

    channel_info = get_channel_info(channel_id)
    # split_screen pode ser fixo pro canal inteiro (campo "split_screen": true)
    # ou condicional a palavras no titulo do video (campo "split_screen_keywords":
    # ["DEBATE", ...]), util para canais que misturam formatos diferentes.
    keywords = [k.lower() for k in channel_info.get("split_screen_keywords", [])]
    title_matches_keyword = any(k in video_title.lower() for k in keywords)
    split_screen = bool(channel_info.get("split_screen", False)) or title_matches_keyword

    channel_title = download.get_channel_title(channel_id, api_key)
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    print(f"== 1/5 Download: {video_id} ==")
    video_path = download.download_video(video_id)

    print("== 2/5 Transcricao ==")
    transcribe.transcribe(video_path, video_id)

    print("== 3/5 Analise de highlights (Gemini) ==")
    with open(f"transcripts/{video_id}.json", encoding="utf-8") as f:
        segments = json.load(f)
    highlights = analyze_highlights.find_highlights_gemini(segments)
    os.makedirs("highlights", exist_ok=True)
    with open(f"highlights/{video_id}.json", "w", encoding="utf-8") as f:
        json.dump(highlights, f, ensure_ascii=False, indent=2)

    print("== 4/5 Cortando clipes ==")
    for i, clip in enumerate(highlights):
        cut_shorts.cut_clip(video_path, video_id, clip, i, segments, split_screen=split_screen)

    if publish:
        print("== 5/5 Publicando no YouTube ==")
        base_time = datetime.now(timezone.utc)
        for i, clip in enumerate(highlights):
            clip_path = f"shorts/{video_id}_{i}.mp4"
            motivo = clip.get("motivo", "")
            description = (
                f"{motivo}\n\n"
                f"Video original: {channel_title}\n"
                f"Assista na integra: {video_url}"
            ).strip()
            publish_at = _schedule_time(base_time, i)
            titulo = clip.get("titulo", f"Corte {i+1}")
            uploaded_id = upload_short.upload_short(
                clip_path,
                titulo,
                description,
                tags=["shorts"],
                publish_at=publish_at,
            )

            thumb_path = f"thumbnails/{video_id}_{i}.jpg"
            thumbnail.generate_thumbnail(clip_path, titulo, thumb_path)
            try:
                upload_short.set_thumbnail(uploaded_id, thumb_path)
            except Exception as e:
                # Nao derruba o pipeline se so a thumbnail falhar (ex: canal
                # ainda nao verificado no YouTube) - o video ja foi publicado.
                print(f"[AVISO] Falha ao definir thumbnail de {uploaded_id}: {e}")
    else:
        print("Publicacao pulada (--no-publish). Confira a pasta shorts/ antes de subir.")

    select_video.mark_processed(video_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--video-id",
        required=False,
        default=None,
        help="ID do video (opcional). Se omitido, escolhe automaticamente um "
        "video recente de um canal aleatorio da allowlist.",
    )
    parser.add_argument("--no-publish", action="store_true", help="gera os clipes mas nao publica")
    args = parser.parse_args()
    run(args.video_id, publish=not args.no_publish)


if __name__ == "__main__":
    main()
