"""Integracja Second Life — szablon skryptu LSL i helpery."""

from __future__ import annotations

from pathlib import Path


def lsl_template_path() -> Path:
    return Path(__file__).resolve().parent / "LovenseController.lsl"


def load_lsl_template(*, base_url: str = "", token: str = "") -> str:
    """Wczytaj skrypt LSL; opcjonalnie podstaw BASE_URL i TOKEN."""
    text = lsl_template_path().read_text(encoding="utf-8")
    if base_url:
        bu = base_url.rstrip("/").replace('"', '\\"')
        text = text.replace(
            'string  BASE_URL = "http://192.168.1.10:8787";',
            f'string  BASE_URL = "{bu}";',
        )
    if token:
        tok = token.replace("\\", "\\\\").replace('"', '\\"')
        text = text.replace(
            'string  TOKEN    = "WKLEJ_TOKEN_Z_GUI";',
            f'string  TOKEN    = "{tok}";',
        )
    return text


def notecard_example(*, base_url: str = "", token: str = "") -> str:
    """Treść notecard lovense.cfg do wrzucenia w obiekt SL."""
    bu = (base_url or "https://xxxx.trycloudflare.com").rstrip("/")
    tok = token or "WKLEJ_TOKEN_Z_GUI"
    return (
        "# lovense.cfg — konfiguracja mostka SL (bez edycji skryptu)\n"
        f"BASE_URL={bu}\n"
        f"TOKEN={tok}\n"
        "CHANNEL=7\n"
        "DEFAULT_TIME=4\n"
    )
