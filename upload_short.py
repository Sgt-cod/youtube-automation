"""
Publica o Short no YouTube.
Reaproveita o padrao ja usado no seu outro projeto: a variavel de ambiente
YOUTUBE_CREDENTIALS contem o JSON completo gerado por Credentials.to_json()
(token, refresh_token, client_id, client_secret, scopes tudo junto). Nao
precisa de fluxo interativo de navegador nem de client_secrets.json - o
refresh_token ja permite renovar o access token sozinho, inclusive rodando
no GitHub Actions sem interacao humana.
"""
import argparse
import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def get_credentials() -> Credentials:
    creds_dict = json.loads(os.environ["YOUTUBE_CREDENTIALS"])
    creds = Credentials.from_authorized_user_info(creds_dict)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def upload_short(
    video_path: str,
    title: str,
    description: str,
    tags: list[str] | None = None,
    publish_at: str | None = None,
):
    """Se publish_at for informado (string ISO 8601 UTC, ex:
    '2026-08-20T13:00:00Z'), o video sobe como privado e o YouTube
    publica ele automaticamente nesse horario. Se for None, publica
    imediatamente como publico."""
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    status = {"selfDeclaredMadeForKids": False}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    else:
        status["privacyStatus"] = "public"

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or [],
            "categoryId": "24",  # Entretenimento; ajuste se quiser
        },
        "status": status,
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status_progress, response = request.next_chunk()
        if status_progress:
            print(f"Upload {int(status_progress.progress() * 100)}%")
    video_id = response["id"]
    if publish_at:
        print(f"[OK] Programado para {publish_at}: https://youtube.com/shorts/{video_id}")
    else:
        print(f"[OK] Publicado: https://youtube.com/shorts/{video_id}")
    return video_id


def set_thumbnail(video_id: str, thumbnail_path: str):
    """Define uma thumbnail customizada para o video. Requer que o canal
    esteja verificado (telefone) no YouTube, senao a API retorna 403."""
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    print(f"[OK] Thumbnail definida para {video_id}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True, help="ID do video original (para achar os clipes gerados)")
    args = parser.parse_args()
    with open(f"highlights/{args.video_id}.json", "r", encoding="utf-8") as f:
        highlights = json.load(f)
    for i, clip in enumerate(highlights):
        clip_path = f"shorts/{args.video_id}_{i}.mp4"
        titulo = clip.get("titulo", f"Corte {i+1}")
        descricao = clip.get("motivo", "")
        upload_short(clip_path, titulo, descricao, tags=["shorts"])


if __name__ == "__main__":
    main()
