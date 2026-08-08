"""Tryb bez Tk: panel w przeglądarce (gdy brak libtk / python-tk)."""

from __future__ import annotations

import logging
import socket
import time
import webbrowser
from typing import TYPE_CHECKING

from max2_controller.web.servers import (
    create_game_app,
    create_remote_app,
    run_flask_in_thread,
    stop_server,
)

if TYPE_CHECKING:
    from max2_controller.config import AppConfig
    from max2_controller.controller import Max2Controller
    from max2_controller.hotkeys import HotkeyManager

logger = logging.getLogger(__name__)


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def run_web_mode(
    controller: "Max2Controller",
    config: "AppConfig",
    hotkeys: "HotkeyManager | None" = None,
) -> None:
    """Uruchamia API gier + panel remote i czeka na Ctrl+C."""
    config.remote_enabled = True
    config.game_api_enabled = True

    game_app = create_game_app(controller, config)
    remote_app = create_remote_app(controller, config)

    game_handle = run_flask_in_thread(
        game_app, config.game_api_host, config.game_api_port, "game-api"
    )
    remote_handle = run_flask_in_thread(
        remote_app, config.remote_host, config.remote_port, "remote"
    )
    controller.state.game_api_active = True
    controller.state.remote_active = True
    controller.start_battery_poll()

    # pierwsza próba GetToys
    try:
        controller.refresh_toys()
    except Exception:
        logger.exception("refresh_toys")

    from max2_controller.remote_links import build_remote_links

    links = build_remote_links(config)

    print()
    print("=" * 60)
    print("  Lovense Controller — tryb WEB")
    print("=" * 60)
    print()
    print(f"  Backend: {controller.state.backend_name}")
    if controller.state.backend_name == "ble":
        print("  Bluetooth BLE — BEZ telefonu.")
        print(f"    curl -X POST -H 'X-API-Token: {config.game_api_token}' \\")
        print(f"      http://127.0.0.1:{config.game_api_port}/ble/scan")
    print()
    print("  ═══ LINK ZDALNY (przeglądarka) ═══")
    print(f"  Ten PC:     {links.local}")
    print(f"  Wi‑Fi/LAN:  {links.lan}")
    print(f"  Internet:   cloudflared tunnel --url http://127.0.0.1:{links.port}")
    print(f"              potem doklej: {links.path_short}")
    print()
    print("  API do gier:")
    print(f"    http://{config.game_api_host}:{config.game_api_port}")
    print(f"    token: {config.game_api_token}")
    print()
    print("  STOP: Ctrl+C w tym terminalu")
    print("=" * 60)
    print()

    try:
        webbrowser.open(links.local)
    except Exception:
        pass

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nZamykanie…")
    finally:
        if hotkeys:
            hotkeys.stop()
        stop_server(game_handle)
        stop_server(remote_handle)
        try:
            controller.shutdown()
        except Exception:
            pass
