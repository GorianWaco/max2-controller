"""Punkt startowy aplikacji — domyślnie GTK 4."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Umożliw import przy uruchomieniu z katalogu projektu
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from max2_controller.config import AppConfig
from max2_controller.controller import Max2Controller
from max2_controller.hotkeys import HotkeyManager


def _gtk_available() -> tuple[bool, str]:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401

        return True, ""
    except Exception as e:
        return False, str(e)


def _print_gtk_help(err: str) -> None:
    print(
        f"""
┌─────────────────────────────────────────────────────────────┐
│  Brak GTK 4 / PyGObject — nie da się otworzyć okna.         │
├─────────────────────────────────────────────────────────────┤
│  {err[:56]:<56} │
│                                                             │
│  Na CachyOS / Arch:                                         │
│      sudo pacman -S python-gobject gtk4 libadwaita          │
│                                                             │
│  venv MUSI widzieć pakiety systemowe:                       │
│      python3 -m venv --system-site-packages .venv           │
│                                                             │
│  Albo tryb przeglądarki:  ./run.sh --web                    │
└─────────────────────────────────────────────────────────────┘
""".strip()
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Max 2 Controller (GTK)")
    parser.add_argument("--web", action="store_true", help="Panel w przeglądarce")
    parser.add_argument("--gtk", action="store_true", help="Wymuś okno GTK (domyślne)")
    args = parser.parse_args(argv)

    config = AppConfig.load()
    controller = Max2Controller(config)
    hotkeys = HotkeyManager(controller, config)
    if config.hotkeys_enabled:
        hotkeys.start()

    if args.web:
        from max2_controller.web_mode import run_web_mode

        run_web_mode(controller, config, hotkeys=hotkeys)
        return

    ok, err = _gtk_available()
    if not ok:
        _print_gtk_help(err)
        print("\nFallback: tryb WEB (Ctrl+C aby anulować, start za 2 s)…\n")
        try:
            import time

            time.sleep(2)
        except KeyboardInterrupt:
            print("Anulowano.")
            return
        from max2_controller.web_mode import run_web_mode

        run_web_mode(controller, config, hotkeys=hotkeys)
        return

    from max2_controller.gui.gtk_window import run_gtk

    run_gtk(controller, config, hotkeys=hotkeys)


if __name__ == "__main__":
    main()
