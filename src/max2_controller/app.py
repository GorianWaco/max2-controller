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
│      ./install.sh                                           │
│      albo:  lovense-controller --setup                      │
│                                                             │
│  venv MUSI widzieć pakiety systemowe:                       │
│      python3 -m venv --system-site-packages .venv           │
│                                                             │
│  Albo tryb przeglądarki:  ./run.sh --web                    │
└─────────────────────────────────────────────────────────────┘
""".strip()
    )


def _print_import_help(exc: BaseException) -> None:
    print(f"Brak biblioteki: {exc}")
    print("Doinstaluj:  lovense-controller --setup")
    print("albo:        ./install.sh")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Max 2 Controller (GTK)")
    parser.add_argument("--web", action="store_true", help="Panel w przeglądarce")
    parser.add_argument("--gtk", action="store_true", help="Wymuś okno GTK (domyślne)")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Sprawdź zależności i doinstaluj braki",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Nie sprawdzaj zależności przy starcie",
    )
    args = parser.parse_args(argv)

    if not args.skip_setup:
        from max2_controller.setup_check import ensure_ready

        if ensure_ready(force=args.setup) == "exit":
            return

    from max2_controller.config import AppConfig
    from max2_controller.hotkeys import HotkeyManager

    try:
        from max2_controller.controller import Max2Controller
    except ImportError as exc:
        _print_import_help(exc)
        return

    config = AppConfig.load()
    controller = Max2Controller(config)
    hotkeys = HotkeyManager(controller, config)
    if config.hotkeys_enabled:
        hotkeys.start()

    if args.web:
        try:
            from max2_controller.web_mode import run_web_mode
        except ImportError as exc:
            _print_import_help(exc)
            return
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
        try:
            from max2_controller.web_mode import run_web_mode
        except ImportError as exc:
            _print_import_help(exc)
            return
        run_web_mode(controller, config, hotkeys=hotkeys)
        return

    try:
        from max2_controller.gui.gtk_window import run_gtk
    except ImportError as exc:
        _print_import_help(exc)
        return

    run_gtk(controller, config, hotkeys=hotkeys)


if __name__ == "__main__":
    main()
