"""
Interacao com o Telegram para o corte longo: o pipeline avisa que o video esta
pronto e ESPERA voce mandar a thumbnail (foto ou arquivo de imagem).

Variaveis de ambiente (secrets do GitHub):
  TELEGRAM_BOT_TOKEN  token do bot (BotFather)
  TELEGRAM_CHAT_ID    seu chat id (so mensagens desse chat sao aceitas)

Usa long polling (getUpdates), entao o bot NAO pode ter webhook configurado.
Use um bot dedicado a este pipeline.
"""
import argparse
import os
import time

import requests
from PIL import Image

API = "https://api.telegram.org"
YOUTUBE_THUMB_MAX_BYTES = 2 * 1024 * 1024  # limite do YouTube: 2 MB
SKIP_WORDS = {"pular", "skip", "/pular", "/skip", "sem", "sem thumb"}


def _token() -> str:
    return os.environ["TELEGRAM_BOT_TOKEN"]


def _chat_id() -> str:
    return str(os.environ["TELEGRAM_CHAT_ID"]).strip()


def _call(method: str, timeout: int = 30, **params) -> dict:
    resp = requests.post(f"{API}/bot{_token()}/{method}", json=params, timeout=timeout)
    if resp.status_code == 409:
        raise RuntimeError(
            "Telegram retornou 409: o bot tem um webhook ativo (ou outro processo "
            "esta lendo as mensagens). Use um bot dedicado ou remova o webhook "
            f"({API}/bot<TOKEN>/deleteWebhook)."
        )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} falhou: {data}")
    return data["result"]


def send_message(text: str) -> int:
    """Envia texto para o seu chat. Retorna o message_id."""
    result = _call("sendMessage", chat_id=_chat_id(), text=text, disable_web_page_preview=True)
    return result["message_id"]


def _flush_updates() -> int:
    """Descarta mensagens antigas (ex: uma imagem mandada ontem) e retorna o
    offset a partir do qual vamos ler."""
    updates = _call("getUpdates", offset=-1, limit=1, timeout=0)
    return updates[-1]["update_id"] + 1 if updates else 0


def _extract_image_file_id(msg: dict) -> str | None:
    if msg.get("photo"):
        return max(msg["photo"], key=lambda p: p.get("file_size", 0) or p["width"] * p["height"])["file_id"]
    doc = msg.get("document")
    if doc and str(doc.get("mime_type", "")).startswith("image/"):
        return doc["file_id"]
    return None


def _download_file(file_id: str, out_path: str):
    info = _call("getFile", file_id=file_id)
    url = f"{API}/file/bot{_token()}/{info['file_path']}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)


def normalize_thumbnail(path: str) -> str:
    """Converte para JPEG e reduz ate caber nos 2 MB do YouTube. Retorna o
    caminho final (.jpg). Avisa (print) se nao for 16:9."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if abs(w / h - 16 / 9) > 0.03:
        print(f"[AVISO] Thumbnail {w}x{h} nao e 16:9; o YouTube pode cortar/ajustar as bordas.")
    if w > 1920:  # nao precisa de mais que isso
        img = img.resize((1920, round(h * 1920 / w)), Image.LANCZOS)
    out = os.path.splitext(path)[0] + "_final.jpg"
    for quality in (95, 90, 85, 80, 70, 60):
        img.save(out, "JPEG", quality=quality, optimize=True)
        if os.path.getsize(out) <= YOUTUBE_THUMB_MAX_BYTES:
            return out
    img = img.resize((1280, round(img.height * 1280 / img.width)), Image.LANCZOS)
    img.save(out, "JPEG", quality=80, optimize=True)
    return out


def wait_for_thumbnail(out_path: str, timeout_minutes: int, offset: int | None = None) -> str:
    """Espera ate `timeout_minutes` por uma imagem do seu chat.
    Retorna:
      'image'   -> imagem baixada e normalizada (caminho em out_path)
      'skip'    -> voce mandou 'pular' (publicar sem thumbnail personalizada)
      'timeout' -> ninguem respondeu a tempo
    Passe o `offset` obtido de start_session() para ignorar mensagens antigas."""
    if offset is None:
        offset = _flush_updates()
    chat = _chat_id()
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        wait = int(min(25, max(1, deadline - time.time())))
        updates = _get_updates(offset, wait)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != chat:
                continue  # ignora qualquer outra pessoa
            file_id = _extract_image_file_id(msg)
            if file_id:
                raw = out_path + ".raw"
                _download_file(file_id, raw)
                final = normalize_thumbnail(raw)
                os.replace(final, out_path)
                os.remove(raw)
                return "image"
            if str(msg.get("text", "")).strip().lower() in SKIP_WORDS:
                return "skip"
    return "timeout"


def _get_updates(offset: int, wait: int) -> list:
    resp = requests.post(
        f"{API}/bot{_token()}/getUpdates",
        json={"offset": offset, "timeout": wait, "allowed_updates": ["message"]},
        timeout=wait + 15,
    )
    if resp.status_code == 409:
        raise RuntimeError("Telegram 409: bot com webhook ativo. Use um bot dedicado ou chame deleteWebhook.")
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getUpdates falhou: {data}")
    return data["result"]


def start_session() -> int:
    """Chame ANTES de enviar o aviso; devolve o offset para wait_for_thumbnail."""
    return _flush_updates()


def main():
    parser = argparse.ArgumentParser(description="Utilitario: envia uma mensagem de texto.")
    parser.add_argument("--notify", required=True)
    args = parser.parse_args()
    send_message(args.notify)


if __name__ == "__main__":
    main()
