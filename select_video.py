"""Escolhe automaticamente um video recente de um canal aleatorio da allowlist."""
import json
import os
import random
import re

from googleapiclient.discovery import build

from allowlist import get_channel_info, load_allowlist

PROCESSED_PATH = "processed_videos.json"

# Shorts do YouTube podem durar ate 3 minutos. Exigir bem mais que isso
# garante que so peguemos videos longos (entrevistas, podcasts etc), nunca
# um Short que o proprio canal ja publicou.
MIN_SOURCE_DURATION_SECONDS = 240  # 4 minutos

PLAYLIST_PAGE_SIZE = 50
MAX_PLAYLIST_PAGES = 4  # ate 200 videos de profundidade por canal, se precisar

_ISO8601_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def _parse_iso8601_duration(duration: str) -> int:
    """Converte 'PT4M13S' (formato da API do YouTube) para segundos."""
    match = _ISO8601_DURATION_RE.match(duration or "")
    if not match:
        return 0
    parts = match.groupdict()
    days = int(parts["days"] or 0)
    hours = int(parts["hours"] or 0)
    minutes = int(parts["minutes"] or 0)
    seconds = int(parts["seconds"] or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _load_processed() -> set:
    """IDs de videos ja cortados antes, para nao repetir."""
    if not os.path.exists(PROCESSED_PATH):
        return set()
    with open(PROCESSED_PATH, "r", encoding="utf-8") as f:
        return set(json.load(f))


def mark_processed(video_id: str):
    processed = _load_processed()
    processed.add(video_id)
    with open(PROCESSED_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(processed), f, ensure_ascii=False, indent=2)


def _get_uploads_playlist_id(youtube, channel_id: str) -> str:
    resp = youtube.channels().list(part="contentDetails", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _iter_playlist_pages(youtube, playlist_id: str, max_pages: int = MAX_PLAYLIST_PAGES):
    """Gera paginas de video_ids na ordem retornada pela API (para a
    playlist de uploads, isso e do mais recente para o mais antigo)."""
    page_token = None
    for _ in range(max_pages):
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=PLAYLIST_PAGE_SIZE,
            pageToken=page_token,
        ).execute()
        video_ids = [item["contentDetails"]["videoId"] for item in resp.get("items", [])]
        yield video_ids
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def _get_video_details_batch(youtube, video_ids: list) -> dict:
    """Retorna {video_id: {"duration": segundos, "title": str}}."""
    details = {}
    for i in range(0, len(video_ids), 50):  # videos.list aceita ate 50 ids por chamada
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="contentDetails,snippet", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            details[item["id"]] = {
                "duration": _parse_iso8601_duration(item["contentDetails"]["duration"]),
                "title": item["snippet"].get("title", ""),
            }
    return details


def _find_candidate_in_channel(youtube, channel_id: str, processed: set):
    """Procura, na playlist configurada do canal (ou nos uploads gerais se
    nenhuma playlist especifica foi definida), o primeiro video que ainda
    nao foi processado e que nao e um Short. Prioriza os mais recentes -
    so vai mais fundo na playlist se os recentes ja tiverem sido usados."""
    channel_info = get_channel_info(channel_id)
    playlist_id = channel_info.get("playlist_id") or _get_uploads_playlist_id(youtube, channel_id)
    if not playlist_id:
        return None

    for page_ids in _iter_playlist_pages(youtube, playlist_id):
        if not page_ids:
            continue
        pending_ids = [v for v in page_ids if v not in processed]
        if not pending_ids:
            continue
        details = _get_video_details_batch(youtube, pending_ids)
        # mantem a ordem original da pagina (preferencia pelos mais recentes)
        for video_id in page_ids:
            if video_id not in pending_ids:
                continue
            info = details.get(video_id)
            if not info or info["duration"] < MIN_SOURCE_DURATION_SECONDS:
                continue
            return video_id, info["title"]

    return None


def pick_video(api_key: str, max_attempts: int = 10) -> tuple:
    """Sorteia um canal da allowlist e retorna (video_id, channel_id,
    video_title) de um video LONGO ainda nao processado, dando preferencia
    aos mais recentes da playlist configurada para o canal (ou dos uploads
    gerais, se nenhuma playlist especifica estiver configurada). Levanta
    RuntimeError se nao achar nenhum candidato depois de `max_attempts`."""
    channel_ids = list(load_allowlist())
    if not channel_ids:
        raise RuntimeError("Allowlist vazia, adicione canais em channels_allowlist.json")

    random.shuffle(channel_ids)
    youtube = build("youtube", "v3", developerKey=api_key)
    processed = _load_processed()

    attempts = 0
    for channel_id in channel_ids:
        if attempts >= max_attempts:
            break
        attempts += 1

        found = _find_candidate_in_channel(youtube, channel_id, processed)
        if found:
            video_id, title = found
            return video_id, channel_id, title

    raise RuntimeError(
        "Nao foi possivel achar um video longo novo em nenhum canal da "
        f"allowlist (tentativas: {attempts})."
    )
