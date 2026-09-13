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


def test_landing_has_language_selector(remote_server: AppConfig) -> None:
    port = remote_server.remote_port
    code, body = _get(f"http://127.0.0.1:{port}/")
    assert code == 200
    html = str(body)
    assert 'data-lang-select' in html
    assert '"pl"' in html and '"en"' in html and '"de"' in html
    assert '"fr"' in html and '"es"' in html and '"pt"' in html
    assert '"it"' in html and '"ru"' in html
    assert "Polski" in html and "English" in html and "Português" in html
    assert "initI18n" in html


def test_panel_has_i18n(remote_server: AppConfig) -> None:
    port = remote_server.remote_port
    tok = remote_server.remote_token
    code, body = _get(f"http://127.0.0.1:{port}/panel?token={tok}")
    assert code == 200
    html = str(body)
    assert 'data-lang-select' in html
    assert 'data-i18n="nav.power"' in html
    assert "initI18n" in html
    assert "function t(" in html


def test_i18n_packs_complete() -> None:
    from max2_controller.web.i18n import LANG_CODES, STRINGS

    assert LANG_CODES == ["pl", "en", "de", "fr", "es", "pt", "it", "ru"]
    keys = set(STRINGS["pl"])
    assert keys
    for lang in LANG_CODES:
        assert set(STRINGS[lang]) == keys, lang


def test_lsl_and_notecard_are_english() -> None:
    from max2_controller.secondlife import load_lsl_template, notecard_example

    polish = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    script = load_lsl_template(base_url="https://demo.example.com", token="abc")
    note = notecard_example(base_url="https://demo.example.com", token="abc")
    assert 'string  TOKEN    = "abc";' in script
    assert 'string  TOKEN    = "PASTE_TOKEN_FROM_GUI";' not in script
    assert "optional" in note.lower()
    assert "wrzuć" not in note.lower()
    assert "llRequestSecureURL" in script
    assert "PAIR URL" in script
    assert "Lovense" in script
    assert "GiveHud" not in script
    assert "HTTP_PRAGMA," not in script
    assert not (set(script) & polish)
    assert not (set(note) & polish)


def test_lsl_needs_hud_and_persist() -> None:
    from max2_controller.secondlife import NEEDS_TEMPLATE, load_lsl_template

    polish = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    hud = load_lsl_template(name=NEEDS_TEMPLATE)
    body = load_lsl_template(token="abc")
    assert "llLinksetDataWrite" in body
    assert "PulseNeeds" in body
    assert "llResetScript();" not in body.split("on_rez")[1][:200]
    assert "Horny" in hud
    assert "Hygiene" in hud
    assert "llWater" in hud
    assert "InWater" in hud
    assert "washing" in hud
    assert "gHygWash" in hud
    assert "Hugs" in hud
    assert "Social" in hud
    assert "gSocialRange = 20.0" in hud
    assert "gHugRange = 1.5" in hud
    assert "llVecDist(llGetPos(), llDetectedPos(k))" in hud
    assert "llSensorRepeat" in hud
    assert "llLinksetDataWrite" in hud
    assert "GiveHud" not in hud
    assert not (set(hud) & polish)
    assert "NeedsChan" in body
    assert "NeedsChan" in hud
    assert "gShowText = FALSE" in body
    assert "gShow = TRUE" in hud
    assert "llMessageLinked" in body
    assert "NEEDSMENU" in hud
    assert "NEEDSHIDE" in hud
    assert "NEEDSSHOW" in hud
    assert "NEEDSTXT|" in hud
    assert "NEEDSTXT|" in body
    assert "gNeedsTxt" in body
    assert "TIPTXT|" in body
    assert "gTipTxt" in body
    assert "TJ|buzz|" in body
    assert "ApplyBuzz" in body
    assert "Tip jar" in body
    assert "JAR|rez" in body
    assert "llInstantMessage" in body
    assert "LVQ|" in body
    assert "ApplyCmd" in body
    assert "link_message" in body
    assert 'llRegionSayTo(who, 0,' not in body
    assert "PRIM_TYPE_BOX" not in hud


def test_lsl_wearable_is_public_control() -> None:
    from max2_controller.secondlife import METER_TEMPLATE, load_lsl_template
    from max2_controller.secondlife.bridge import normalize_sl_url

    polish = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    script = load_lsl_template(
        base_url="https://demo.example.com",
        token="abc",
        name=METER_TEMPLATE,
    )
    assert 'string  TOKEN    = "abc";' in script
    assert "PRIM_TYPE_SPHERE" not in script
    assert "llParticleSystem" not in script
    assert "PRIM_CLICK_ACTION" in script
    assert "OrbitStep" not in script
    assert "LOOK|fx|" in script
    assert "(string)gAim" in script
    assert "LOOK|orbit|" in script
    assert "PulseLook" in script
    assert "TokenLooksOk" in script
    assert "lv.tok" in script
    assert "LoadCfg();" in script
    assert "llGetLinkNumber() > 1" in script
    assert "llSetClickAction" in script
    assert "CLICK_ACTION_TOUCH" in script
    assert "CLICK_ACTION_PAY" not in script
    assert "gPayClick" not in script
    assert "llRezAtRoot" not in script
    assert "CmdChan" not in script
    assert "Rez jar" in script
    assert "JAR|rez" in script
    assert "JAR|menu" in script
    assert "JAR|reset" in script
    assert "Clear uses" in script
    assert "Clear tips" in script
    assert "Clear all" in script
    assert "MenuStats" in script
    assert "BankAdd" not in script
    assert "TEXT_COLOR" not in script
    assert "EN|add|" in script
    assert "ENERTXT|" in script
    assert "Replay" in script
    assert "Clear E" in script
    assert 'gPend == "replay"' in script
    assert "llGetPos().z" not in script
    assert "llRequestSecureURL" in script
    assert "GiveHud" not in script
    assert "http_request" in script
    granted = script.split("URL_REQUEST_GRANTED", 1)[1].split("URL_REQUEST_DENIED", 1)[0]
    assert "SayPair" not in granted
    assert 'if (msg == "URL")' in script
    assert not (set(script) & polish)
    assert normalize_sl_url("  https://sim.agni.lindenlab.com/cap/abc  ") == (
        "https://sim.agni.lindenlab.com/cap/abc"
    )
    assert normalize_sl_url(
        "https://simhost-abc.agni.secondlife.io 12043/cap/37502878-2956-22fb-2d6b-94bc33e4fe80"
    ) == "https://simhost-abc.agni.secondlife.io:12043/cap/37502878-2956-22fb-2d6b-94bc33e4fe80"


def test_lsl_look_is_separate() -> None:
    from max2_controller.secondlife import LOOK_TEMPLATE, load_lsl_template

    polish = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    look = load_lsl_template(name=LOOK_TEMPLATE)
    assert "llParticleSystem" in look
    assert "PSYS_SRC_TEXTURE" in look
    assert "PickTex" in look
    assert "PSYS_SRC_TARGET_KEY" in look
    assert "PSYS_PART_TARGET_POS_MASK" in look
    assert "gAim" in look
    assert "p_" in look
    assert "PRIM_TYPE_SPHERE" in look
    assert "OrbitStep" in look
    assert "HEARTBEAT_SPEED" in look
    assert "LIST_BEAT_MODIFIERS" in look
    assert "SURFACE_SPEED" in look
    assert "llSetLinkPrimitiveParamsFast" in look
    assert "LOOK|fx|" in look or 'k == "fx"' in look
    assert "llRequestSecureURL" not in look
    assert "llDialog" not in look
    assert not (set(look) & polish)


def test_lsl_tipjar_ground_vessel() -> None:
    from max2_controller.secondlife import TIPJAR_TEMPLATE, load_lsl_template, notecard_tipjar_example

    polish = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    script = load_lsl_template(name=TIPJAR_TEMPLATE)
    note = notecard_tipjar_example()
    assert "money(" in script
    assert "llSetPayPrice" in script
    assert "LVQ|" in script
    assert "CmdChan" in script
    assert "OnGround" in script
    assert "gHosted" not in script
    assert "MODE_WEAR" not in script
    assert "llRequestSecureURL" not in script
    assert "tipjar.cfg" in script
    assert "PRICE_A" in script
    assert "Test 50" in script
    assert "CLICK_ACTION_PAY" in script
    assert "llRegionSay" in script
    assert "TJ|hello" in script
    assert "TJ|pong" in script
    assert "TIPTXT|" in script
    assert "PushTip" in script
    assert "TJ|buzz|" in script
    assert "TJ|die" in script
    assert "llDie" in script
    assert "/77 jar" in script
    assert "PRIM_TYPE" not in script
    assert "PRIM_CLICK_ACTION" in script
    assert "llSetPrimitiveParams" not in script
    assert not (set(script) & polish)
    assert "PRICE_D=250" in note
    assert "MODE=auto" not in note
    assert not (set(note) & polish)


def test_lsl_jar_host_rezzes_from_orb() -> None:
    from max2_controller.secondlife import JARHOST_TEMPLATE, load_lsl_template

    polish = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    script = load_lsl_template(name=JARHOST_TEMPLATE)
    assert "llRezAtRoot" in script
    assert "JAR_OBJECT" in script
    assert "CmdChan" in script
    assert "TJ|pong" in script
    assert "TJ|hello" in script
    assert "TJ|die" in script
    assert "JAR|rez" in script
    assert "JAR|menu" in script
    assert "JAR|reset" in script
    assert "llRequestSecureURL" not in script
    assert "llGetPos().z" not in script
    assert "PRIM_TYPE_SPHERE" not in script
    assert "llGetLinkNumber() > 1" in script
    assert not (set(script) & polish)


def test_lsl_energy_bank_and_color() -> None:
    from max2_controller.secondlife import ENERGY_TEMPLATE, load_lsl_template

    polish = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
    script = load_lsl_template(name=ENERGY_TEMPLATE)
    assert "BankAdd" in script
    assert "TEXT_COLOR" in script
    assert "EN|add|" in script
    assert "ENERTXT|" in script
    assert "llRequestSecureURL" not in script
    assert "llGetPos().z" not in script
    assert "llGetLinkNumber() > 1" in script
    assert not (set(script) & polish)
