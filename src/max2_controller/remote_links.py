"""Generowanie linków do panelu zdalnego (przeglądarka)."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from max2_controller.config import AppConfig


def local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@dataclass
class RemoteLinks:
    """Linki gotowe do wklejenia w przeglądarce / wysłania partnerce."""

    local: str  # ten komputer
    lan: str  # telefon / PC w tej samej Wi‑Fi
    path_short: str  # /r/<token>
    token: str
    port: int
    host_ip: str
    # Second Life — baza bez /r/ (skrypty wołają /sl/...)
    sl_base_local: str = ""
    sl_base_lan: str = ""
    sl_example: str = ""

    def as_text(self) -> str:
        return (
            f"Twój komputer:\n  {self.local}\n\n"
            f"Telefon / inna osoba w Wi‑Fi (LAN):\n  {self.lan}\n\n"
            f"Second Life (skrypt LSL) — baza URL:\n"
            f"  LAN:  {self.sl_base_lan}\n"
            f"  test: {self.sl_base_local}\n"
            f"  przykład: {self.sl_example}\n\n"
            f"Przez internet (spoza domu / z gridu SL):\n"
            f"  1) W terminalu:  cloudflared tunnel --url http://127.0.0.1:{self.port}\n"
            f"     albo:        ngrok http {self.port}\n"
            f"  2) Do https://… doklej:  /r/{self.token}  (panel)\n"
            f"     albo baza SL:         https://….trycloudflare.com\n"
            f"     skrypt: /sl/vibrate?token=…&level=10\n"
        )


def build_remote_links(config: "AppConfig") -> RemoteLinks:
    token = config.remote_token
    port = int(config.remote_port)
    ip = local_ip()
    # ładniejsza ścieżka /r/TOKEN (działa w create_remote_app)
    path = f"/r/{quote(token, safe='')}"
    tok_q = quote(token, safe="")
    sl_local = f"http://127.0.0.1:{port}"
    sl_lan = f"http://{ip}:{port}"
    return RemoteLinks(
        local=f"http://127.0.0.1:{port}{path}",
        lan=f"http://{ip}:{port}{path}",
        path_short=path,
        token=token,
        port=port,
        host_ip=ip,
        sl_base_local=sl_local,
        sl_base_lan=sl_lan,
        sl_example=f"{sl_lan}/sl/vibrate?token={tok_q}&level=8&time=3",
    )
