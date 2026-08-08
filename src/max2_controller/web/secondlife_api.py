"""
API pod skrypty Second Life (LSL).

LSL (llHTTPRequest) wygodnie używa:
  - GET z parametrami w URL
  - POST application/x-www-form-urlencoded lub JSON
  - token w query (?token=…) — nie trzeba custom headerów

Endpointy (na serwerze remote, port domyślnie 8787):
  GET  /sl/help
  GET  /sl/status?token=…
  GET|POST /sl/vibrate?token=…&level=10&time=3
  GET|POST /sl/pump?token=…&level=2&time=3
  GET|POST /sl/function?token=…&v=10&p=2&t=2
  GET|POST /sl/stop?token=…
  GET|POST /sl/preset?token=…&name=pulse&time=8
  GET|POST /sl/pattern?token=…&strength=20;0;15&interval=200&time=6
  GET|POST /sl/intensity?token=…&i=0.5&time=2   (i = 0.0–1.0)
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING, Any

from flask import Flask, Response, jsonify, request

if TYPE_CHECKING:
    from max2_controller.config import AppConfig
    from max2_controller.controller import Max2Controller

logger = logging.getLogger(__name__)


def _check_token(expected: str, header_name: str = "X-API-Token") -> bool:
    """Token z headera, query (?token=) lub body JSON/form — pod LSL."""
    if not expected:
        return True
    got = request.headers.get(header_name) or request.args.get("token") or ""
    if request.form and request.form.get("token"):
        got = got or str(request.form.get("token") or "")
    if request.method in ("POST", "PUT", "PATCH") and request.content_length:
        try:
            data = request.get_json(silent=True)
            if isinstance(data, dict) and data.get("token"):
                got = got or str(data.get("token") or "")
        except Exception:
            pass
    try:
        return secrets.compare_digest(str(got), str(expected))
    except Exception:
        return False

HELP_TEXT = """Lovense Controller — Second Life API
=====================================

Base:  http://IP:PORT/sl/...
Auth:  ?token=YOUR_REMOTE_TOKEN  (query, form body, or JSON "token")

Endpoints (GET or POST — LSL-friendly):
  /sl/help                         this text
  /sl/status?token=T
  /sl/vibrate?token=T&level=0-20&time=SEC
  /sl/pump?token=T&level=0-3&time=SEC
  /sl/function?token=T&v=0-20&p=0-3&t=SEC
  /sl/intensity?token=T&i=0.0-1.0&time=SEC
  /sl/stop?token=T
  /sl/preset?token=T&name=pulse&time=SEC
  /sl/pattern?token=T&strength=20;5;0&interval=200&time=SEC

Aliases: vibrate=level=v  pump=p  time=time_sec=t  intensity=i

Limits: remote_max_vibrate / remote_max_pump from controller config.
Script template: see GUI → Second Life → „Kopiuj skrypt LSL”
"""


def _param_dict() -> dict[str, Any]:
    """Scal query + form + JSON (LSL często miesza źródła)."""
    out: dict[str, Any] = {}
    out.update(request.args.to_dict(flat=True))
    if request.form:
        out.update(request.form.to_dict(flat=True))
    if request.method in ("POST", "PUT", "PATCH") and request.content_length:
        data = request.get_json(force=True, silent=True)
        if isinstance(data, dict):
            out.update(data)
    return out


def _f(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in data and data[k] is not None and str(data[k]) != "":
            return data[k]
    return default


def _as_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _as_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def register_secondlife_routes(
    app: Flask,
    controller: "Max2Controller",
    config: "AppConfig",
    *,
    token_attr: str = "remote_token",
    require_remote_on: bool = True,
) -> None:
    """Podłącz /sl/* do istniejącej aplikacji Flask (zwykle remote)."""

    def _token_ok() -> bool:
        expected = getattr(config, token_attr, "") or ""
        return _check_token(str(expected))

    def _remote_active() -> bool:
        if not require_remote_on:
            return True
        return bool(config.remote_enabled or controller.state.remote_active)

    def _clamp(v: int, p: int) -> tuple[int, int]:
        return (
            max(0, min(int(config.remote_max_vibrate), int(v))),
            max(0, min(int(config.remote_max_pump), int(p))),
        )

    def _deny_auth():
        return jsonify({"ok": False, "error": "unauthorized", "hint": "token?"}), 401

    def _deny_off():
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "remote disabled",
                    "hint": "Włącz panel zdalny w Lovense Controller (GUI)",
                }
            ),
            403,
        )

    @app.route("/sl", methods=["GET", "POST"])
    @app.route("/sl/", methods=["GET", "POST"])
    def sl_root():
        return Response(HELP_TEXT, mimetype="text/plain; charset=utf-8")

    @app.route("/sl/help", methods=["GET", "POST"])
    def sl_help():
        return Response(HELP_TEXT, mimetype="text/plain; charset=utf-8")

    @app.route("/sl/status", methods=["GET", "POST"])
    def sl_status():
        if not _token_ok():
            return _deny_auth()
        snap = controller.snapshot()
        # English line for LSL HUD (avoid Polish GUI last_message like "Bateria: …")
        if snap.get("connected"):
            bat = None
            for t in snap.get("toys") or []:
                if t.get("battery") is not None:
                    bat = t.get("battery")
                    break
            if bat is not None:
                msg = f"Battery: {bat}%"
            else:
                msg = "Connected"
            n = int(snap.get("connected_count") or 0)
            if n > 1:
                msg = f"{msg} · {n} toys"
        else:
            msg = "No toy connected"
        return jsonify(
            {
                "ok": True,
                "connected": snap.get("connected"),
                "vibrate": snap.get("vibrate"),
                "pump": snap.get("pump"),
                "connected_count": snap.get("connected_count", 0),
                "message": msg,
                "max_vibrate": config.remote_max_vibrate,
                "max_pump": config.remote_max_pump,
                "service": "lovense-sl",
            }
        )

    @app.route("/sl/stop", methods=["GET", "POST"])
    def sl_stop():
        if not _token_ok():
            return _deny_auth()
        if not _remote_active():
            return _deny_off()
        if not config.remote_allow_stop:
            return jsonify({"ok": False, "error": "stop not allowed"}), 403
        result = controller.stop()
        controller.stop_auto_modes()
        return jsonify({"ok": result.ok, "message": result.message, "vibrate": 0, "pump": 0})

    @app.route("/sl/vibrate", methods=["GET", "POST"])
    def sl_vibrate():
        if not _token_ok():
            return _deny_auth()
        if not _remote_active():
            return _deny_off()
        data = _param_dict()
        level = _as_int(_f(data, "level", "vibrate", "v", default=10), 10)
        t = _as_float(_f(data, "time", "time_sec", "timeSec", "t", default=0), 0.0)
        level, _ = _clamp(level, 0)
        result = controller.set_levels(vibrate=level, time_sec=t, immediate=True)
        return jsonify(
            {
                "ok": bool(result and result.ok),
                "message": controller.state.last_message,
                "vibrate": level,
                "time_sec": t,
            }
        )

    @app.route("/sl/pump", methods=["GET", "POST"])
    def sl_pump():
        if not _token_ok():
            return _deny_auth()
        if not _remote_active():
            return _deny_off()
        data = _param_dict()
        level = _as_int(_f(data, "level", "pump", "p", default=1), 1)
        t = _as_float(_f(data, "time", "time_sec", "timeSec", "t", default=0), 0.0)
        _, level = _clamp(0, level)
        result = controller.set_levels(pump=level, time_sec=t, immediate=True)
        return jsonify(
            {
                "ok": bool(result and result.ok),
                "message": controller.state.last_message,
                "pump": level,
                "time_sec": t,
            }
        )

    @app.route("/sl/function", methods=["GET", "POST"])
    def sl_function():
        if not _token_ok():
            return _deny_auth()
        if not _remote_active():
            return _deny_off()
        data = _param_dict()
        v = _as_int(_f(data, "v", "vibrate", "level", default=0), 0)
        p = _as_int(_f(data, "p", "pump", default=0), 0)
        t = _as_float(_f(data, "t", "time", "time_sec", "timeSec", default=0), 0.0)
        # intensity 0–1 override
        intensity = _f(data, "i", "intensity", default=None)
        if intensity is not None:
            x = max(0.0, min(1.0, _as_float(intensity, 0.0)))
            v = int(round(x * float(config.remote_max_vibrate)))
            p = int(round(x * float(config.remote_max_pump)))
        v, p = _clamp(v, p)
        result = controller.set_levels(vibrate=v, pump=p, time_sec=t, immediate=True)
        return jsonify(
            {
                "ok": bool(result and result.ok),
                "message": controller.state.last_message,
                "vibrate": v,
                "pump": p,
                "time_sec": t,
            }
        )

    @app.route("/sl/intensity", methods=["GET", "POST"])
    def sl_intensity():
        """i=0.0–1.0 → wibracja + pump proporcjonalnie do limitów remote."""
        if not _token_ok():
            return _deny_auth()
        if not _remote_active():
            return _deny_off()
        data = _param_dict()
        x = max(0.0, min(1.0, _as_float(_f(data, "i", "intensity", "level", default=0.5), 0.5)))
        t = _as_float(_f(data, "t", "time", "time_sec", "timeSec", default=0), 0.0)
        v = int(round(x * float(config.remote_max_vibrate)))
        p = int(round(x * float(config.remote_max_pump)))
        v, p = _clamp(v, p)
        result = controller.set_levels(vibrate=v, pump=p, time_sec=t, immediate=True)
        return jsonify(
            {
                "ok": bool(result and result.ok),
                "message": controller.state.last_message,
                "intensity": x,
                "vibrate": v,
                "pump": p,
                "time_sec": t,
            }
        )

    @app.route("/sl/preset", methods=["GET", "POST"])
    def sl_preset():
        if not _token_ok():
            return _deny_auth()
        if not _remote_active():
            return _deny_off()
        data = _param_dict()
        name = str(_f(data, "name", "preset", default="pulse") or "pulse")
        t = _as_float(_f(data, "t", "time", "time_sec", "timeSec", default=8), 8.0)
        result = controller.preset(name, time_sec=t)
        return jsonify({"ok": result.ok, "message": result.message, "preset": name, "time_sec": t})

    @app.route("/sl/pattern", methods=["GET", "POST"])
    def sl_pattern():
        if not _token_ok():
            return _deny_auth()
        if not _remote_active():
            return _deny_off()
        data = _param_dict()
        strength = str(_f(data, "strength", "pattern", "s", default="10;20;5;0") or "10;20;5;0")
        interval = _as_int(_f(data, "interval", "interval_ms", "intervalMs", default=200), 200)
        t = _as_float(_f(data, "t", "time", "time_sec", "timeSec", default=8), 8.0)
        result = controller.pattern(strength, time_sec=t, interval_ms=interval)
        return jsonify(
            {
                "ok": result.ok,
                "message": result.message,
                "strength": strength,
                "interval_ms": interval,
                "time_sec": t,
            }
        )

    logger.info("Second Life /sl/* routes registered")
