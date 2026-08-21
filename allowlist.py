"""Verifica se um canal esta na allowlist antes de qualquer operacao no pipeline."""
import json
import sys

ALLOWLIST_PATH = "channels_allowlist.json"


def _load_raw() -> dict:
    with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_allowlist() -> set:
    data = _load_raw()
    return {c["channel_id"] for c in data.get("canais_autorizados", [])}


def get_channel_info(channel_id: str) -> dict:
    """Retorna a entrada completa do canal na allowlist (inclui campos
    extras como 'split_screen', se configurados). Se o canal nao tiver
    campos extras cadastrados, retorna um dict minimo com valores padrao."""
    data = _load_raw()
    for c in data.get("canais_autorizados", []):
        if c.get("channel_id") == channel_id:
            return c
    return {"channel_id": channel_id}


def assert_channel_authorized(channel_id: str):
    allowed = load_allowlist()
    if channel_id not in allowed:
        print(
            f"[BLOQUEADO] Canal {channel_id} nao esta em {ALLOWLIST_PATH}. "
            "Adicione-o (com autorizacao) antes de continuar.",
            file=sys.stderr,
        )
        sys.exit(1)
