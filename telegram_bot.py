"""
Interacao com o Telegram para o corte longo: o pipeline avisa o contexto do
corte e ESPERA voce mandar (1) um audio de comentario introdutorio, opcional, e
(2) a thumbnail (foto ou arquivo de imagem).

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


def _call(method: str, _http_timeout: int = 30, **params) -> dict:
    # "timeout" em **params e parametro da API do Telegram (long polling),
    # diferente do timeout HTTP do requests (_http_timeout).
    resp = requests.post(f"{API}/bot{_token()}/{method}", json=params, timeout=_http_timeout)
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


# Estado da sessao: offset de leitura + midias que chegaram "adiantadas"
# (ex: voce mandou a thumbnail enquanto o bot ainda esperava o audio).
_state = {"offset": None, "stash": {}}


def start_session() -> int:
    """Chame ANTES de enviar a primeira mensagem do bot."""
    _state["offset"] = _flush_updates()
    _state["stash"] = {}
    return _state["offset"]


def _classify(msg: dict):
    """Retorna (tipo, file_id, extensao) ou None. tipo: 'image' | 'audio'."""
    if msg.get("photo"):
        best = max(msg["photo"], key=lambda p: p.get("file_size", 0) or p["width"] * p["height"])
        return "image", best["file_id"], ".jpg"
    if msg.get("voice"):
        return "audio", msg["voice"]["file_id"], ".ogg"
    if msg.get("audio"):
        name = msg["audio"].get("file_name") or ""
        return "audio", msg["audio"]["file_id"], os.path.splitext(name)[1] or ".mp3"
    doc = msg.get("document")
    if doc:
        mime = str(doc.get("mime_type", ""))
        ext = os.path.splitext(doc.get("file_name") or "")[1]
        if mime.startswith("image/"):
            return "image", doc["file_id"], ext or ".jpg"
        if mime.startswith("audio/"):
            return "audio", doc["file_id"], ext or ".mp3"
    return None


def _download_file(file_id: str, out_path: str):
    info = _call("getFile", file_id=file_id)
    url = f"{API}/file/bot{_token()}/{info['file_path']}"
    resp = requests.get(url, timeout=120)
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


def _wait_media(want: str, timeout_minutes: float):
    """Espera uma midia do tipo `want` ('image' ou 'audio') vinda do SEU chat.
    Retorna ('media', (file_id, ext, legenda)) | ('skip', None) | ('timeout', None).
    Midia do outro tipo que chegar nesse meio tempo fica guardada para a
    proxima espera."""
    stash = _state["stash"]
    if want in stash:
        return "media", stash.pop(want)
    if _state["offset"] is None:
        start_session()
    chat = _chat_id()
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        wait = int(min(25, max(1, deadline - time.time())))
        for upd in _get_updates(_state["offset"], wait):
            _state["offset"] = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != chat:
                continue  # ignora qualquer outra pessoa
            media = _classify(msg)
            if media:
                kind, file_id, ext = media
                item = (file_id, ext, msg.get("caption", "") or "")
                if kind == want:
                    return "media", item
                stash[kind] = item
            elif str(msg.get("text", "")).strip().lower() in SKIP_WORDS:
                return "skip", None
    return "timeout", None


def wait_for_audio(out_base: str, timeout_minutes: float):
    """Espera o audio do comentario introdutorio (mensagem de voz, audio ou
    arquivo de audio). Retorna (status, caminho_do_arquivo, legenda), com
    status 'audio' | 'skip' | 'timeout'."""
    status, item = _wait_media("audio", timeout_minutes)
    if status != "media":
        return status, None, ""
    file_id, ext, caption = item
    path = out_base + ext
    _download_file(file_id, path)
    return "audio", path, caption


def wait_for_thumbnail(out_path: str, timeout_minutes: float, offset: int | None = None) -> str:
    """Espera ate `timeout_minutes` por uma imagem do seu chat.
    Retorna 'image' (salva e normalizada em out_path) | 'skip' | 'timeout'."""
    if offset is not None:
        _state["offset"] = offset
    status, item = _wait_media("image", timeout_minutes)
    if status != "media":
        return status
    file_id, _ext, _caption = item
    raw = out_path + ".raw"
    _download_file(file_id, raw)
    final = normalize_thumbnail(raw)
    os.replace(final, out_path)
    os.remove(raw)
    return "image"


def main():
    parser = argparse.ArgumentParser(description="Utilitario: envia uma mensagem de texto.")
    parser.add_argument("--notify", required=True)
    args = parser.parse_args()
    send_message(args.notify)


if __name__ == "__main__":
    main()
