"""Upload de video longo (nao-Short) no YouTube. Reaproveita as credenciais e a
funcao de thumbnail do upload_short.py."""
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from upload_short import get_credentials, set_thumbnail  # noqa: F401 (re-exportado)


def upload_long(
    video_path: str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    privacy: str = "public",
) -> str:
    """privacy: 'public' | 'private' | 'unlisted'. Retorna o video_id."""
    youtube = build("youtube", "v3", credentials=get_credentials())
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": tags or [],
            "categoryId": "24",
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(video_path, chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress:
            print(f"Upload {int(progress.progress() * 100)}%")
    video_id = response["id"]
    print(f"[OK] Enviado ({privacy}): https://youtu.be/{video_id}")
    return video_id
