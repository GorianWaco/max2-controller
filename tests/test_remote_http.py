"""Testy panelu remote / API Second Life (bez GUI, bez BLE)."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest

from max2_controller.config import AppConfig
from max2_controller.models import CommandResult
from max2_controller.remote_links import (
    is_private_or_local_url,
    is_public_https_url,
    pick_sl_base_url,
)
from max2_controller.remote_sessions import RemoteSessionManager
from max2_controller.web.servers import create_remote_app, run_flask_in_thread, stop_server


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


@dataclass
class _State:
    connected: bool = False
    connected_count: int = 0
    control_all: bool = True
    vibrate: int = 0
    pump: int = 0
    time_sec: float = 0.0
    last_message: str = "idle"
    last_ok: bool = True
    backend_name: str = "ble"
    remote_active: bool = True
    game_api_active: bool = False
    auto_mode: str = "none"
    toys: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.toys is None:
            self.toys = []


class FakeController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = _State()
        self.remote_sessions = RemoteSessionManager()
        self._lock = threading.RLock()

    def log(self, msg: str) -> None:
        pass

    def snapshot(self) -> dict:
        return {
            "connected": self.state.connected,
            "connected_count": self.state.connected_count,
            "control_all": True,
            "backend": "ble",
            "vibrate": self.state.vibrate,
            "pump": self.state.pump,
            "time_sec": 0,
            "selected_toy_id": None,
            "last_message": self.state.last_message,
            "last_ok": True,
            "remote_active": True,
            "game_api_active": False,
            "auto_mode": "none",
            "audio_enabled": False,
            "audio_mode": "playback",
            "audio_sensitivity": 1.4,
            "audio_gain": 10.0,
            "audio_threshold": 0.015,
            "remote_sessions": {"online_count": 0},
            "toys": [],
        }

    def connected_toy_ids(self) -> list[str]:
        return []

    def stop(self, toy=None) -> CommandResult:
        return CommandResult(ok=True, message="stop")

    def stop_auto_modes(self) -> None:
        return None

    def stop_multi(self, ids=None) -> CommandResult:
        return CommandResult(ok=True, message="stop")

    def set_levels(self, **kwargs) -> CommandResult:
        return CommandResult(ok=True, message="ok")

    def set_levels_multi(self, *a, **k) -> CommandResult:
        return CommandResult(ok=True, message="ok")

    def preset(self, name, time_sec=None, toy=None) -> CommandResult:
        return CommandResult(ok=True, message=str(name))

    def preset_multi(self, *a, **k) -> CommandResult:
        return CommandResult(ok=True, message="ok")

    def pattern(self, *a, **k) -> CommandResult:
        return CommandResult(ok=True, message="ok")

    def audio_react_enabled(self) -> bool:
        return False

    def set_audio_react(self, on) -> CommandResult:
        return CommandResult(ok=True, message="ok")

    def set_audio_params(self, **k) -> CommandResult:
        return CommandResult(ok=True, message="ok")


def test_private_url_helpers() -> None:
    assert is_private_or_local_url("http://127.0.0.1:8787")
    assert is_private_or_local_url("http://192.168.1.50:8787")
    assert is_private_or_local_url("http://10.0.0.2:8787")
    assert is_private_or_local_url("http://localhost:8787")
    assert not is_public_https_url("http://192.168.1.50:8787")
    assert is_public_https_url("https://abc.trycloudflare.com")
    assert is_public_https_url("https://foo.ngrok-free.app")
    base, pub = pick_sl_base_url(
        "http://192.168.1.10:8787",
        "https://alive.example.com/r/TOKEN",
        lan_fallback="http://192.168.1.10:8787",
    )
    assert pub is True
    assert base == "https://alive.example.com"


def _get(url: str, headers: dict | None = None) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw = resp.read().decode("utf-8")
            code = int(getattr(resp, "status", 200) or 200)
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        code = int(e.code)
        hdrs = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
    try:
        data = json.loads(raw)
    except Exception:
        data = raw
    if isinstance(data, dict):
        data["_hdrs"] = hdrs
    return code, data


@pytest.fixture()
def remote_server():
    cfg = AppConfig()
    cfg.remote_enabled = True
    cfg.remote_token = "test-token-123"
    cfg.remote_port = _free_port()
    cfg.remote_host = "127.0.0.1"
    ctl = FakeController(cfg)
    app = create_remote_app(ctl, cfg)
    handle = run_flask_in_thread(app, "127.0.0.1", cfg.remote_port, "test-remote")
    assert handle.running, handle.error
    try:
        yield cfg
    finally:
        stop_server(handle)


def test_health_and_sl_ping(remote_server: AppConfig) -> None:
    port = remote_server.remote_port
    code, data = _get(f"http://127.0.0.1:{port}/health")
    assert code == 200
    assert data["ok"] is True
    code, body = _get(f"http://127.0.0.1:{port}/sl/ping")
    assert code == 200
    assert "lovense-sl" in str(body)


def test_sl_status_token(remote_server: AppConfig) -> None:
    port = remote_server.remote_port
    tok = remote_server.remote_token
    code, data = _get(f"http://127.0.0.1:{port}/sl/status?token={tok}")
    assert code == 200
    assert data["ok"] is True
    assert data["service"] == "lovense-sl"
    code, data = _get(f"http://127.0.0.1:{port}/sl/status?token=bad")
    assert code == 401


def test_tunnel_host_header_accepted(remote_server: AppConfig) -> None:
    port = remote_server.remote_port
    code, data = _get(
        f"http://127.0.0.1:{port}/health",
        headers={"Host": "wma-component-susan-nearby.trycloudflare.com"},
    )
    assert code == 200
    assert data["ok"] is True


def test_proxy_fix_https_scheme(remote_server: AppConfig) -> None:
    port = remote_server.remote_port
    code, data = _get(
        f"http://127.0.0.1:{port}/diag",
        headers={
            "Host": "demo.trycloudflare.com",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "demo.trycloudflare.com",
        },
    )
    assert code == 200
    assert data["scheme"] == "https"
    assert "demo.trycloudflare.com" in data["host"]


def test_cors_allows_session_header(remote_server: AppConfig) -> None:
    port = remote_server.remote_port
    code, data = _get(f"http://127.0.0.1:{port}/health")
    assert code == 200
    allow = data["_hdrs"].get("access-control-allow-headers", "")
    assert "X-Session-Id" in allow or "x-session-id" in allow.lower()
