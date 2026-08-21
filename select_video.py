"""Escolhe automaticamente um video recente de um canal aleatorio da allowlist."""
import json
import os
import random
import re

from googleapiclient.discovery import build

from allowlist import load_allowlist

PROCESSED_PATH = "processed_videos.json"

# Shorts do YouTube podem durar ate 3 minutos. Exigir bem mais que isso
# garante que so peguemos videos longos (entrevistas, podcasts etc), nunca
# um Short que o proprio canal ja publicou.
MIN_SOURCE_DURATION_SECONDS = 240  # 4 minutos

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


def _get_recent_video_ids(youtube, uploads_playlist_id: str, max_results: int = 20) -> list:
    resp = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=max_results,
    ).execute()
    return [item["contentDetails"]["videoId"] for item in resp.get("items", [])]


def _get_video_durations(youtube, video_ids: list) -> dict:
    """Retorna {video_id: duracao_em_segundos}. A API do YouTube nao
    diferencia 'Short' de 'video normal' diretamente - a duracao e o jeito
    confiavel de filtrar Shorts (que vao ate 3 minutos)."""
    durations = {}
    for i in range(0, len(video_ids), 50):  # videos.list aceita ate 50 ids por chamada
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(part="contentDetails", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            durations[item["id"]] = _parse_iso8601_duration(item["contentDetails"]["duration"])
    return durations


def pick_video(api_key: str, max_attempts: int = 10) -> tuple:
    """Sorteia um canal da allowlist e retorna (video_id, channel_id) de um
    video LONGO recente ainda nao processado (Shorts sao descartados).
    Levanta RuntimeError se nao achar nenhum candidato depois de
    `max_attempts` tentativas."""
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

        uploads_id = _get_uploads_playlist_id(youtube, channel_id)
        if not uploads_id:
            continue

        recent_ids = _get_recent_video_ids(youtube, uploads_id)
        not_processed = [v for v in recent_ids if v not in processed]
        if not not_processed:
            continue

        durations = _get_video_durations(youtube, not_processed)
        candidates = [
            v for v in not_processed
            if durations.get(v, 0) >= MIN_SOURCE_DURATION_SECONDS
        ]
        if not candidates:
            continue

        video_id = random.choice(candidates)
        return video_id, channel_id

    raise RuntimeError(
        "Nao foi possivel achar um video longo novo em nenhum canal da "
        f"allowlist (tentativas: {attempts})."
    )
