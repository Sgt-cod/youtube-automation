"""Baixa um video do YouTube, mas so se o canal estiver na allowlist."""
import argparse
import os
import subprocess
from dotenv import load_dotenv
from googleapiclient.discovery import build
from allowlist import assert_channel_authorized

load_dotenv()

OUTPUT_DIR = "downloads"
COOKIES_PATH = "cookies.txt"


def get_video_channel_id(video_id: str, api_key: str) -> str:
    youtube = build("youtube", "v3", developerKey=api_key)
    resp = youtube.videos().list(part="snippet", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Video {video_id} nao encontrado.")
    return items[0]["snippet"]["channelId"]


def get_video_details(video_id: str, api_key: str) -> dict:
    """Retorna {'channel_id': ..., 'title': ...} numa unica chamada -
    usado no fluxo manual (--video-id), onde ainda nao sabemos o canal
    nem o titulo do video."""
    youtube = build("youtube", "v3", developerKey=api_key)
    resp = youtube.videos().list(part="snippet", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Video {video_id} nao encontrado.")
    snippet = items[0]["snippet"]
    return {"channel_id": snippet["channelId"], "title": snippet.get("title", "")}


def get_channel_title(channel_id: str, api_key: str) -> str:
    """Nome atual do canal, usado para credito na descricao do short."""
    youtube = build("youtube", "v3", developerKey=api_key)
    resp = youtube.channels().list(part="snippet", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        return channel_id
    return items[0]["snippet"]["title"]


def download_video(video_id: str) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_template = os.path.join(OUTPUT_DIR, f"{video_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"

    cmd = [
        "yt-dlp",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]",
        "--merge-output-format", "mp4",
        "--remote-components", "ejs:github",
        "--force-ipv4",
        "-o", out_template,
    ]

    # Se houver cookies.txt (gerado a partir do secret YOUTUBE_COOKIES_TXT),
    # usa para evitar o bloqueio "Sign in to confirm you're not a bot"
    # que o YouTube costuma aplicar em IPs de datacenter (ex: GitHub Actions).
    if os.path.exists(COOKIES_PATH):
        cmd += ["--cookies", COOKIES_PATH]

    cmd.append(url)

    subprocess.run(cmd, check=True)
    expected_path = os.path.join(OUTPUT_DIR, f"{video_id}.mp4")
    return expected_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    args = parser.parse_args()
    api_key = os.environ["YOUTUBE_API_KEY"]
    channel_id = get_video_channel_id(args.video_id, api_key)
    assert_channel_authorized(channel_id)
    path = download_video(args.video_id)
    print(f"[OK] Video baixado em {path}")
    return path


if __name__ == "__main__":
    main()
