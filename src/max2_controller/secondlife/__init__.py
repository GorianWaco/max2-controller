"""Integracja Second Life — szablon skryptu LSL i helpery."""

from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent

HUD_TEMPLATE = "LovenseController.lsl"
METER_TEMPLATE = "LovenseController.lsl"  # ten sam obiekt na awatarze
NEEDS_TEMPLATE = "LovenseNeedsHUD.lsl"
TIPJAR_TEMPLATE = "LovenseTipJar.lsl"
LOOK_TEMPLATE = "LovenseLook.lsl"
JARHOST_TEMPLATE = "LovenseJarHost.lsl"
ENERGY_TEMPLATE = "LovenseEnergy.lsl"


def lsl_template_path(name: str = HUD_TEMPLATE) -> Path:
    safe = Path(name).name
    if safe == "LovenseMeter.lsl":
        safe = HUD_TEMPLATE
    path = _DIR / safe
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_lsl_template(*, base_url: str = "", token: str = "", name: str = HUD_TEMPLATE) -> str:
    """Wczytaj skrypt LSL (obiekt na awatarze); opcjonalnie podstaw BASE_URL i TOKEN."""
    text = lsl_template_path(name).read_text(encoding="utf-8")
    if base_url:
        bu = base_url.rstrip("/").replace('"', '\\"')
        text = text.replace(
            'string  BASE_URL = "http://192.168.1.10:8787";',
            f'string  BASE_URL = "{bu}";',
        )
    if token:
        tok = token.replace("\\", "\\\\").replace('"', '\\"')
        for old in ("PASTE_TOKEN_FROM_GUI", "WKLEJ_TOKEN_Z_GUI"):
            text = text.replace(
                f'string  TOKEN    = "{old}";',
                f'string  TOKEN    = "{tok}";',
            )
    return text


def notecard_example(*, base_url: str = "", token: str = "", panel_url: str = "") -> str:
    """Notecard lovense.cfg for the wearable (English)."""
    bu = (base_url or "https://xxxx.trycloudflare.com").rstrip("/")
    tok = token or "PASTE_TOKEN_FROM_GUI"
    panel = (panel_url or "").strip()
    extra = f"# PANEL={panel}\n" if panel else ""
    return (
        "# lovense.cfg — optional (this exact name)\n"
        f"{extra}"
        f"TOKEN={tok}\n"
        "DEFAULT_TIME=4\n"
        "ATTACH=2\n"
        "PUBLIC=1\n"
        "HOVER=✦  Lovense\n"
        "COLOR=1.00 0.82 0.90\n"
    )


def notecard_tipjar_example() -> str:
    """Notecard tipjar.cfg for the ground tip-jar vessel."""
    return (
        "# tipjar.cfg — optional (this exact name)\n"
        "# Rez the vessel on the floor. Wear is not supported.\n"
        "TITLE=Tip jar\n"
        "THANKS=Thanks {name}! L${amount} -> {time}s\n"
        "OPEN=1\n"
        "SHOW=1\n"
        "PRICE_A=10\n"
        "PRICE_B=50\n"
        "PRICE_C=100\n"
        "PRICE_D=250\n"
        "PRICE_OTHER=25\n"
    )
