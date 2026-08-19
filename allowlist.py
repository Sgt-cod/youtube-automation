"""Verifica se um canal esta na allowlist antes de qualquer operacao no pipeline."""
import json
import sys

ALLOWLIST_PATH = "channels_allowlist.json"


def load_allowlist():
    with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {c["channel_id"] for c in data.get("canais_autorizados", [])}


def assert_channel_authorized(channel_id: str):
    allowed = load_allowlist()
    if channel_id not in allowed:
        print(
            f"[BLOQUEADO] Canal {channel_id} nao esta em {ALLOWLIST_PATH}. "
            "Adicione-o (com autorizacao) antes de continuar.",
            file=sys.stderr,
        )
        sys.exit(1)
