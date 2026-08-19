"""Escolhe automaticamente um video recente de um canal aleatorio da allowlist."""
import os
import random
import json

from googleapiclient.discovery import build

from allowlist import load_allowlist

PROCESSED_PATH = "processed_videos.json"


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


def _get_recent_video_ids(youtube, uploads_playlist_id: str, max_results: int = 10) -> list:
    resp = youtube.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=max_results,
    ).execute()
    return [item["contentDetails"]["videoId"] for item in resp.get("items", [])]


def pick_video(api_key: str, max_attempts: int = 10) -> tuple:
    """Sorteia um canal da allowlist e retorna (video_id, channel_id) de um
    video recente ainda nao processado. Levanta RuntimeError se nao achar
    nenhum candidato depois de `max_attempts` tentativas."""
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
        candidates = [v for v in recent_ids if v not in processed]
        if not candidates:
            continue

        video_id = random.choice(candidates)
        return video_id, channel_id

    raise RuntimeError(
        "Nao foi possivel achar um video novo em nenhum canal da allowlist "
        f"(tentativas: {attempts})."
    )
