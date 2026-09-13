"""Flask: lokalne API gier + zdalny panel sterowania."""

from __future__ import annotations

import logging
import secrets
import threading
from typing import TYPE_CHECKING
from urllib.parse import quote

from flask import Flask, Response, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

from max2_controller.web.i18n import i18n_boot_script, lang_select_html

if TYPE_CHECKING:
    from max2_controller.controller import Max2Controller
    from max2_controller.config import AppConfig

logger = logging.getLogger(__name__)


def _web_shell(body: str, *, title_key: str, extra_css: str = "") -> str:
    """Prosta strona z wyborem języka (landing / błędy)."""
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title data-i18n="{title_key}">Lovense Controller</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0f0f12;color:#f4f4f5;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}}
.card{{background:#1a1a22;padding:2rem;border-radius:16px;max-width:440px;width:92%;box-shadow:0 8px 32px #0008;position:relative}}
h1{{font-size:1.35rem;margin:0 0 .5rem}}
p{{opacity:.8;font-size:.9rem;line-height:1.45}}
a{{color:#f472b6}}
input,button{{width:100%;padding:.8rem;margin:.45rem 0;border-radius:10px;border:1px solid #333;background:#222;color:#fff;font-size:1rem;box-sizing:border-box}}
button{{background:#e11d48;border:none;cursor:pointer;font-weight:600}}
button:hover{{background:#be123c}}
.hint{{font-size:.8rem;opacity:.55;margin-top:1rem}}
.lang-wrap{{display:flex;align-items:center;justify-content:space-between;gap:.6rem;margin:0 0 1rem}}
.lang-lab{{font-size:.8rem;opacity:.7}}
.lang-select{{flex:1;max-width:12rem;padding:.45rem .5rem;border-radius:10px;border:1px solid #333;background:#222;color:#fff;font-size:.9rem}}
{extra_css}
</style></head><body>
{body}
{i18n_boot_script()}
<script>initI18n();</script>
</body></html>"""


def remote_panel_html() -> str:
    html = REMOTE_PANEL_HTML
    html = html.replace("<!--I18N_BOOT-->", i18n_boot_script())
    html = html.replace("<!--LANG_SELECT_SIDE-->", lang_select_html(compact=True))
    html = html.replace("<!--LANG_SELECT_JOIN-->", lang_select_html())
    return html

# katalog z remote.html — ustawiany przy starcie
STATIC_DIR: str | None = None


def _normalize_token(raw: str) -> str:
    """Token z URL / czatu — bez spacji i „ozdobników” z komunikatorów."""
    t = (raw or "").strip()
    # WhatsApp / Messenger czasem doklejają znaki na końcu
    while t and t[-1] in ".,;:!?)》」'\"…":
        t = t[:-1]
    return t.strip()


def _tokens_equal(got: str, expected: str) -> bool:
    a = _normalize_token(got)
    b = _normalize_token(expected)
    if not b:
        return True
    if not a or len(a) != len(b):
        return False
    try:
        return secrets.compare_digest(a, b)
    except Exception:
        return False


def _check_token(expected: str, header_name: str = "X-API-Token") -> bool:
    if not expected:
        return True
    got = request.headers.get(header_name) or request.args.get("token") or ""
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        got = got or auth[7:]
    # Nie wołaj request.json na GET — przy Content-Type: application/json
    # puste body potrafi dać HTTP 400 w Flask/Werkzeug.
    if request.method in ("POST", "PUT", "PATCH") and request.content_length:
        try:
            data = request.get_json(silent=True)
            if isinstance(data, dict) and data.get("token"):
                got = got or str(data.get("token") or "")
        except Exception:
            pass
    return _tokens_equal(str(got), str(expected))


def create_game_app(controller: "Max2Controller", config: "AppConfig") -> Flask:
    app = Flask("max2-game-api")
    app.config["JSON_SORT_KEYS"] = False

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "service": "max2-game-api"})

    @app.get("/toys")
    def toys():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        controller.refresh_toys()
        return jsonify({"ok": True, **controller.snapshot()})

    @app.get("/status")
    def status():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return jsonify({"ok": True, **controller.snapshot()})

    @app.post("/function")
    def function():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        v = int(data.get("vibrate", controller.state.vibrate))
        p = int(data.get("pump", controller.state.pump))
        t = float(data.get("time_sec", data.get("timeSec", 0)))
        toy = data.get("toy")
        if toy:
            controller.select_toy(str(toy))
        result = controller.set_levels(vibrate=v, pump=p, time_sec=t, immediate=True, toy=toy)
        return jsonify({"ok": result.ok if result else True, "message": controller.state.last_message, "state": controller.snapshot()})

    @app.post("/vibrate")
    def vibrate():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        level = int(data.get("level", data.get("vibrate", 10)))
        t = float(data.get("time_sec", data.get("timeSec", 0)))
        toy = data.get("toy")
        result = controller.set_levels(vibrate=level, time_sec=t, immediate=True, toy=toy)
        return jsonify({"ok": bool(result and result.ok), "message": controller.state.last_message})

    @app.post("/pump")
    def pump():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        level = int(data.get("level", data.get("pump", 1)))
        t = float(data.get("time_sec", data.get("timeSec", 0)))
        toy = data.get("toy")
        result = controller.set_levels(pump=level, time_sec=t, immediate=True, toy=toy)
        return jsonify({"ok": bool(result and result.ok), "message": controller.state.last_message})

    @app.post("/stop")
    def stop():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        result = controller.stop(toy=data.get("toy"))
        return jsonify({"ok": result.ok, "message": result.message})

    @app.post("/preset")
    def preset():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        name = str(data.get("name", "pulse"))
        t = data.get("time_sec", data.get("timeSec"))
        result = controller.preset(name, time_sec=float(t) if t is not None else None, toy=data.get("toy"))
        return jsonify({"ok": result.ok, "message": result.message})

    @app.post("/pattern")
    def pattern():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        strength = str(data.get("strength", "10;20;5;15;0"))
        interval = int(data.get("interval_ms", data.get("intervalMs", 200)))
        t = data.get("time_sec", data.get("timeSec"))
        features = str(data.get("features", "v,p"))
        result = controller.pattern(
            strength=strength,
            time_sec=float(t) if t is not None else None,
            interval_ms=interval,
            features=features,
            toy=data.get("toy"),
        )
        return jsonify({"ok": result.ok, "message": result.message})

    @app.get("/battery")
    def battery():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        level = controller.refresh_battery()
        return jsonify({"ok": True, "battery": level, "state": controller.snapshot()})

    @app.post("/backend")
    def set_backend():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        name = str(data.get("backend", data.get("name", "ble")))
        result = controller.set_backend(name)
        return jsonify({"ok": result.ok, "message": result.message, "state": controller.snapshot()})

    @app.post("/ble/scan")
    def ble_scan():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        timeout = float(data.get("timeout", 8))
        toys = controller.ble_scan(timeout=timeout)
        return jsonify({"ok": True, "toys": [t.id for t in toys], "state": controller.snapshot()})

    @app.post("/ble/connect")
    def ble_connect():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        result = controller.ble_connect(address=data.get("address") or data.get("toy"))
        return jsonify({"ok": result.ok, "message": result.message, "state": controller.snapshot()})

    @app.post("/ble/disconnect")
    def ble_disconnect():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        result = controller.ble_disconnect(address=data.get("address") or data.get("toy"))
        return jsonify({"ok": result.ok, "message": result.message, "state": controller.snapshot()})

    @app.post("/control_all")
    def control_all():
        if not _check_token(config.game_api_token):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        enabled = bool(data.get("enabled", data.get("all", True)))
        controller.set_control_all(enabled)
        return jsonify({"ok": True, "control_all": enabled, "state": controller.snapshot()})

    return app


def create_remote_app(controller: "Max2Controller", config: "AppConfig") -> Flask:
    app = Flask("max2-remote")
    app.config["JSON_SORT_KEYS"] = False
    app.config["TRUSTED_HOSTS"] = None
    # cloudflared / ngrok kończą TLS i wołają nas po HTTP — bez tego
    # request.host_url jest http:// mimo publicznego https://
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    sessions = controller.remote_sessions

    def _auth() -> bool:
        return _check_token(config.remote_token)

    def _client_ip() -> str:
        # cloudflared / proxy
        xff = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For") or ""
        if xff:
            return xff.split(",")[0].strip()
        return (request.remote_addr or "").strip()

    def _session_id() -> str:
        return (
            request.headers.get("X-Session-Id")
            or request.args.get("session")
            or ""
        ).strip()

    def _clamp_remote(v: int, p: int) -> tuple[int, int]:
        return (
            max(0, min(int(config.remote_max_vibrate), int(v))),
            max(0, min(int(config.remote_max_pump), int(p))),
        )

    def _connected_ids() -> list[str]:
        try:
            return controller.connected_toy_ids()
        except Exception:
            snap = controller.snapshot()
            return [t["id"] for t in snap.get("toys") or [] if t.get("connected")]

    def _session_toys_or_error(req_toy: str | None = None):
        """Zwraca (session, toy_ids, error_response|None)."""
        sid = _session_id()
        sess, err = sessions.check_control(sid)
        if err == "missing":
            return None, None, (jsonify({"ok": False, "error": "no_session", "message": "Dołącz ponownie (brak sesji)"}), 401)
        if err == "kicked":
            return None, None, (jsonify({"ok": False, "error": "kicked", "message": "Wyrzucono z panelu"}), 403)
        if err == "banned":
            return None, None, (jsonify({"ok": False, "error": "banned", "message": "IP zablokowane przez hosta"}), 403)
        if err == "no_control":
            return None, None, (jsonify({"ok": False, "error": "no_control", "message": "Host wyłączył Ci sterowanie"}), 403)
        assert sess is not None
        toys, terr = sessions.resolve_target_toys(sess, req_toy, _connected_ids())
        if terr == "toy_not_allowed":
            return sess, None, (jsonify({"ok": False, "error": terr, "message": "Brak uprawnień do tej zabawki"}), 403)
        if terr == "toy_offline":
            return sess, None, (jsonify({"ok": False, "error": terr, "message": "Zabawka offline"}), 403)
        if terr == "no_toys_allowed" or (toys is not None and len(toys) == 0 and sess.allowed_toy_ids is not None):
            return sess, None, (jsonify({"ok": False, "error": "no_toys_allowed", "message": "Host nie dał Ci żadnej zabawki"}), 403)
        return sess, toys, None

    @app.after_request
    def _cors(resp: Response):
        # panel i API z tego samego origin — CORS na wypadek proxy / tunnel
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, X-API-Token, Authorization, X-Session-Id"
        )
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/control", methods=["OPTIONS"])
    @app.route("/api/status", methods=["OPTIONS"])
    @app.route("/api/session/join", methods=["OPTIONS"])
    @app.route("/api/session/leave", methods=["OPTIONS"])
    @app.route("/sl/status", methods=["OPTIONS"])
    def _cors_preflight():
        return Response(status=204)

    @app.post("/api/session/join")
    def api_session_join():
        if not _auth():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        name = str(data.get("name") or data.get("display_name") or "Partner")
        sid_in = str(data.get("session_id") or _session_id() or "")
        sess, err = sessions.join(
            display_name=name,
            remote_addr=_client_ip(),
            user_agent=request.headers.get("User-Agent") or "",
            session_id=sid_in or None,
        )
        if err == "banned":
            return jsonify({"ok": False, "error": "banned", "message": "IP zablokowane przez hosta"}), 403
        if err == "kicked":
            return jsonify({"ok": False, "error": "kicked", "message": "Ta sesja została wyrzucona — odśwież i dołącz jako nowa"}), 403
        if not sess:
            return jsonify({"ok": False, "error": "join_failed"}), 400
        controller.log(f"Remote: dołączył „{sess.display_name}” ({sess.remote_addr})")
        return jsonify({"ok": True, "session": sess.to_dict()})

    @app.post("/api/session/leave")
    def api_session_leave():
        if not _auth():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        sid = _session_id()
        s = sessions.get(sid)
        if s:
            name = s.display_name
            sessions.remove(sid)
            controller.log(f"Remote: wyszedł „{name}”")
        return jsonify({"ok": True})

    @app.get("/health")
    def health_public():
        """Bez tokenu — szybki test: czy telefon w ogóle dosięga PC."""
        return jsonify(
            {
                "ok": True,
                "service": "lovense-remote",
                "remote_enabled": bool(
                    config.remote_enabled or getattr(controller.state, "remote_active", False)
                ),
                "port": int(config.remote_port),
            }
        )

    @app.get("/diag")
    def diag_public():
        """Diagnostyka tunelu: jaki Host/scheme widzi serwer (bez tokenu)."""
        return jsonify(
            {
                "ok": True,
                "service": "lovense-remote",
                "host": request.host,
                "scheme": request.scheme,
                "url": request.url,
                "forwarded_proto": request.headers.get("X-Forwarded-Proto") or "",
                "forwarded_host": request.headers.get("X-Forwarded-Host") or "",
                "remote_enabled": bool(
                    config.remote_enabled or getattr(controller.state, "remote_active", False)
                ),
            }
        )

    @app.get("/")
    def index():
        body = f"""<div class="card">
{lang_select_html()}
<h1 data-i18n="landing.h1">Lovense Controller</h1>
<p data-i18n-html="landing.intro">Zdalne sterowanie w przeglądarce. Wklej <b>link z tokenem</b> od partnera albo sam token poniżej.</p>
<input id="tok" type="text" data-i18n-placeholder="landing.placeholder" placeholder="Token lub wklej cały link" autocomplete="off" spellcheck="false">
<button onclick="go()" data-i18n="landing.open">Otwórz panel</button>
<p class="hint" data-i18n="landing.hint">Najwygodniej: otwórz gotowy link (…/r/TOKEN) — bez wpisywania tokenu.</p>
</div>
<script>
function go(){{
  let t=document.getElementById('tok').value.trim();
  if(!t) return;
  try {{
    if(t.includes('://') || t.includes('/r/') || t.includes('token=')) {{
      const u = t.includes('://') ? new URL(t) : new URL(t, location.origin);
      const m = u.pathname.match(/\\/r\\/([^/]+)/);
      if(m) {{ location.href = '/r/' + decodeURIComponent(m[1]); return; }}
      const tok = u.searchParams.get('token');
      if(tok) {{ location.href = '/panel?token=' + encodeURIComponent(tok); return; }}
    }}
  }} catch(e) {{}}
  location.href = '/r/' + encodeURIComponent(t);
}}
document.getElementById('tok').addEventListener('keydown',e=>{{if(e.key==='Enter')go();}});
</script>"""
        return Response(_web_shell(body, title_key="landing.title"), mimetype="text/html")

    @app.get("/r/<path:token>")
    def panel_short(token: str):
        """Ładny link: http://IP:8787/r/TOKEN — od razu do panelu."""
        from flask import redirect

        tok = _normalize_token(token)
        if not _tokens_equal(tok, str(config.remote_token)):
            body = f"""<div class="card">
{lang_select_html()}
<h1 data-i18n="err.bad_link_title">Nieprawidłowy link</h1>
<p data-i18n="err.bad_link_p1">Poproś o nowy link od właściciela.</p>
<p data-i18n="err.bad_link_p2">Upewnij się, że skopiowano cały link (token na końcu).</p>
<p><a href="/" data-i18n="err.back">Wróć</a></p>
</div>"""
            return Response(
                _web_shell(body, title_key="err.bad_link_title"),
                status=401,
                mimetype="text/html",
            )
        # relative redirect — zachowuje host z telefonu (IP LAN / tunnel), nie 127.0.0.1
        return redirect(f"/panel?token={quote(tok, safe='')}")

    @app.get("/panel")
    def panel():
        if not _auth():
            body = f"""<div class="card">
{lang_select_html()}
<h1 data-i18n="err.denied_title">Brak dostępu</h1>
<p data-i18n="err.denied_p">Zły lub brakujący token. Użyj pełnego linku od właściciela.</p>
<p><a href="/" data-i18n="err.back">Wróć</a></p>
</div>"""
            return Response(
                _web_shell(body, title_key="err.denied_title"),
                status=401,
                mimetype="text/html",
            )
        return Response(remote_panel_html(), mimetype="text/html")

    @app.get("/share")
    def share_page():
        """Strona do pokazania partnerce (link + QR) — wymaga tokenu."""
        if not _auth():
            body = f"""<div class="card">
{lang_select_html()}
<h1 data-i18n="err.denied_title">Brak dostępu</h1>
<p data-i18n="err.share_denied">Brak dostępu — dodaj ?token=…</p>
<p><a href="/" data-i18n="err.back">Wróć</a></p>
</div>"""
            return Response(
                _web_shell(body, title_key="err.denied_title"),
                status=401,
                mimetype="text/html",
            )
        tok = quote(str(config.remote_token), safe="")
        # ten sam host co w adresie (LAN / tunnel)
        host = request.host_url.rstrip("/")
        link = f"{host}/r/{tok}"
        health = f"{host}/health"
        qr = (
            "https://api.qrserver.com/v1/create-qr-code/?size=240x240&data="
            + quote(link, safe="")
        )
        extra = """
body{text-align:center;align-items:flex-start;padding:1.25rem}
.card{max-width:420px;margin:0 auto;background:#16161f;border:1px solid #2a2a36}
a{word-break:break-all}
img{background:#fff;border-radius:12px;padding:8px;margin:1rem 0}
code{display:block;background:#0f0f14;padding:.75rem;border-radius:10px;font-size:.78rem;word-break:break-all;margin:.5rem 0}
.hint{color:#a1a1aa;font-size:.85rem;line-height:1.45;text-align:left}
"""
        body = f"""<div class="card">
{lang_select_html()}
<h1 data-i18n="share.h1">Panel partnerski</h1>
<p class="hint" data-i18n="share.wifi">Ta sama sieć Wi‑Fi co PC z zabawką. Nie używaj danych komórkowych.</p>
<img src="{qr}" width="240" height="240" alt="QR">
<code>{link}</code>
<p><a href="{link}" data-i18n="share.open">Otwórz panel</a> · <a href="{health}" data-i18n="share.health">Test /health</a></p>
<p class="hint" data-i18n="share.hint">Jeśli nie ładuje: ten sam Wi‑Fi, wyłącz VPN na telefonie, na PC włącz panel w Lovense Controller → Zdalne sterowanie.</p>
</div>"""
        return Response(_web_shell(body, title_key="share.title", extra_css=extra), mimetype="text/html")

    @app.get("/api/status")
    def api_status():
        if not _auth():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        sid = _session_id()
        sess = sessions.heartbeat(sid, remote_addr=_client_ip()) if sid else None
        if sid and sess is None:
            # sesja wygasła / wyrzucona
            s2 = sessions.get(sid)
            if s2 and s2.kicked:
                return jsonify({"ok": False, "error": "kicked", "message": "Wyrzucono z panelu"}), 403
            if sessions.is_ip_banned(_client_ip()):
                return jsonify({"ok": False, "error": "banned", "message": "IP zablokowane"}), 403
            return jsonify({"ok": False, "error": "no_session", "message": "Dołącz ponownie"}), 401

        snap = controller.snapshot()
        all_toys = [
            {
                "id": t["id"],
                "display_name": t["display_name"],
                "name": t.get("name"),
                "battery": t["battery"],
                "connected": t["connected"],
            }
            for t in snap["toys"]
        ]
        # filtruj zabawki widoczne dla sesji
        if sess is not None and sess.allowed_toy_ids is not None:
            allow = {a.upper() for a in sess.allowed_toy_ids}
            toys_out = [t for t in all_toys if t["id"].upper() in allow]
        else:
            toys_out = all_toys

        return jsonify(
            {
                "ok": True,
                "vibrate": snap["vibrate"],
                "pump": snap["pump"],
                "connected": snap["connected"],
                "connected_count": snap.get("connected_count", 0),
                "control_all": snap.get("control_all", True),
                "backend": snap.get("backend", ""),
                "toys": toys_out,
                "max_vibrate": config.remote_max_vibrate,
                "max_pump": config.remote_max_pump,
                "allow_stop": config.remote_allow_stop,
                "allow_audio": bool(getattr(config, "remote_allow_audio", True)),
                "allow_audio_params": bool(getattr(config, "remote_allow_audio_params", True)),
                "audio_enabled": bool(snap.get("audio_enabled")),
                "audio_mode": snap.get("audio_mode") or "playback",
                "audio_sensitivity": float(snap.get("audio_sensitivity") or 1.4),
                "audio_gain": float(snap.get("audio_gain") or 10.0),
                "audio_bands_enabled": bool(snap.get("audio_bands_enabled", True)),
                "audio_bass_gain": float(snap.get("audio_bass_gain") or 1.0),
                "audio_treble_gain": float(snap.get("audio_treble_gain") or 1.8),
                "audio_bass_to_vibrate": bool(snap.get("audio_bass_to_vibrate", True)),
                "audio_bass_to_pump": bool(snap.get("audio_bass_to_pump", False)),
                "audio_treble_to_vibrate": bool(snap.get("audio_treble_to_vibrate", False)),
                "audio_treble_to_pump": bool(snap.get("audio_treble_to_pump", True)),
                "message": snap["last_message"],
                "last_ok": snap.get("last_ok", True),
                "host_name": config.app_name or "Lovense Controller",
                "session": sess.to_dict() if sess else None,
                "can_control": bool(sess.can_control) if sess else True,
            }
        )

    @app.post("/api/control")
    def api_control():
        if not _auth():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        data = request.get_json(force=True, silent=True) or {}
        action = str(data.get("action", "function")).lower()
        req_toy = data.get("toy")
        req_toy_s = str(req_toy) if req_toy else None

        try:
            # Audio nie wymaga zabawek — tylko ważnej sesji
            if action in (
                "audio",
                "audio_react",
                "audio_toggle",
                "audio_on",
                "audio_off",
                "audio_params",
                "audio_sensitivity",
            ):
                sid = _session_id()
                sess = sessions.heartbeat(sid, remote_addr=_client_ip()) if sid else None
                if not sess:
                    s2 = sessions.get(sid) if sid else None
                    if s2 and s2.kicked:
                        return jsonify({"ok": False, "error": "kicked", "message": "Wyrzucono z panelu"}), 403
                    if sessions.is_ip_banned(_client_ip()):
                        return jsonify({"ok": False, "error": "banned", "message": "IP zablokowane"}), 403
                    return jsonify({"ok": False, "error": "no_session", "message": "Dołącz ponownie"}), 401

                if action in ("audio_params", "audio_sensitivity"):
                    if not getattr(config, "remote_allow_audio_params", True):
                        return jsonify(
                            {
                                "ok": False,
                                "error": "audio params not allowed",
                                "message": "Host zablokował regulację czułości",
                            }
                        ), 403
                    sens = data.get("sensitivity", data.get("audio_sensitivity"))
                    gain = data.get("gain", data.get("audio_gain"))
                    thr = data.get("threshold", data.get("audio_threshold"))
                    bands = data.get("bands", data.get("audio_bands_enabled"))
                    bass_g = data.get("bass_gain", data.get("audio_bass_gain"))
                    treble_g = data.get("treble_gain", data.get("audio_treble_gain"))
                    b2v = data.get("bass_to_vibrate", data.get("audio_bass_to_vibrate"))
                    b2p = data.get("bass_to_pump", data.get("audio_bass_to_pump"))
                    t2v = data.get("treble_to_vibrate", data.get("audio_treble_to_vibrate"))
                    t2p = data.get("treble_to_pump", data.get("audio_treble_to_pump"))
                    result = controller.set_audio_params(
                        sensitivity=float(sens) if sens is not None else None,
                        gain=float(gain) if gain is not None else None,
                        threshold=float(thr) if thr is not None else None,
                        bands=bool(bands) if bands is not None else None,
                        bass_gain=float(bass_g) if bass_g is not None else None,
                        treble_gain=float(treble_g) if treble_g is not None else None,
                        bass_to_vibrate=bool(b2v) if b2v is not None else None,
                        bass_to_pump=bool(b2p) if b2p is not None else None,
                        treble_to_vibrate=bool(t2v) if t2v is not None else None,
                        treble_to_pump=bool(t2p) if t2p is not None else None,
                    )
                    return jsonify(
                        {
                            "ok": result.ok,
                            "message": result.message,
                            "audio_sensitivity": float(config.audio_sensitivity),
                            "audio_gain": float(config.audio_gain),
                            "audio_bands_enabled": bool(config.audio_bands_enabled),
                            "audio_bass_gain": float(config.audio_bass_gain),
                            "audio_treble_gain": float(config.audio_treble_gain),
                            "audio_bass_to_vibrate": bool(config.audio_bass_to_vibrate),
                            "audio_bass_to_pump": bool(config.audio_bass_to_pump),
                            "audio_treble_to_vibrate": bool(config.audio_treble_to_vibrate),
                            "audio_treble_to_pump": bool(config.audio_treble_to_pump),
                            "audio_enabled": controller.audio_react_enabled(),
                        }
                    )

                if not getattr(config, "remote_allow_audio", True):
                    return jsonify(
                        {
                            "ok": False,
                            "error": "audio not allowed",
                            "message": "Host zablokował audio remote",
                        }
                    ), 403
                if action == "audio_toggle":
                    want = not controller.audio_react_enabled()
                elif action == "audio_on":
                    want = True
                elif action == "audio_off":
                    want = False
                else:
                    if "enabled" in data:
                        want = bool(data.get("enabled"))
                    elif "on" in data:
                        want = bool(data.get("on"))
                    elif "value" in data:
                        want = bool(data.get("value"))
                    else:
                        want = not controller.audio_react_enabled()
                result = controller.set_audio_react(want)
                return jsonify(
                    {
                        "ok": result.ok,
                        "message": result.message,
                        "audio_enabled": controller.audio_react_enabled(),
                    }
                )

            sess, toy_ids, err_resp = _session_toys_or_error(req_toy_s)
            if err_resp is not None:
                return err_resp

            if action == "stop":
                if not config.remote_allow_stop:
                    return jsonify({"ok": False, "error": "stop not allowed"}), 403
                result = controller.stop_multi(toy_ids if toy_ids else None)
                return jsonify({"ok": result.ok, "message": result.message})

            if action == "preset":
                name = str(data.get("name", "pulse"))
                t = float(data.get("time_sec", 8))
                result = controller.preset_multi(name, toy_ids=toy_ids if toy_ids else None, time_sec=t)
                return jsonify({"ok": result.ok, "message": result.message})

            if action == "pattern":
                strength = str(data.get("strength", "10;20;5;0"))
                interval = int(data.get("interval_ms", 250))
                t = float(data.get("time_sec", 8))
                toy_one = (toy_ids[0] if toy_ids else None) or None
                result = controller.pattern(strength, time_sec=t, interval_ms=interval, toy=toy_one)
                return jsonify({"ok": result.ok, "message": result.message})

            # function
            v = int(data.get("vibrate", 0))
            p = int(data.get("pump", 0))
            t = float(data.get("time_sec", 0))
            v, p = _clamp_remote(v, p)
            result = controller.set_levels_multi(
                toy_ids if toy_ids is not None else [],
                vibrate=v,
                pump=p,
                time_sec=t,
            )
            return jsonify(
                {
                    "ok": bool(result and result.ok),
                    "message": controller.state.last_message,
                    "vibrate": v,
                    "pump": p,
                    "toys": toy_ids,
                }
            )
        except Exception as e:
            logger.exception("remote control failed")
            return jsonify({"ok": False, "error": "control failed", "message": str(e)}), 500

    # Second Life (LSL) — GET/POST z tokenem w query
    from max2_controller.web.secondlife_api import register_secondlife_routes

    register_secondlife_routes(app, controller, config, token_attr="remote_token", require_remote_on=False)

    return app


class ServerHandle:
    def __init__(self, name: str) -> None:
        self.name = name
        self.thread: threading.Thread | None = None
        self._server = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive() and self._server is not None


def run_flask_in_thread(app: Flask, host: str, port: int, name: str) -> ServerHandle:
    handle = ServerHandle(name)
    ready = threading.Event()

    def target() -> None:
        # werkzeug bez reloadera
        from werkzeug.serving import make_server

        try:
            httpd = make_server(host, port, app, threaded=True)
            handle._server = httpd
            logger.info("%s listening on %s:%s", name, host, port)
            ready.set()
            httpd.serve_forever()
        except OSError as e:
            handle.error = f"Port {port} zajęty lub brak uprawnień: {e}"
            logger.exception("%s failed to bind %s:%s", name, host, port)
            ready.set()
        except Exception as e:
            handle.error = str(e)
            logger.exception("%s failed", name)
            ready.set()

    handle.thread = threading.Thread(target=target, daemon=True, name=name)
    handle.thread.start()
    # poczekaj chwilę na bind (żeby UI mogło od razu sprawdzić błąd)
    ready.wait(timeout=2.5)
    return handle


def stop_server(handle: ServerHandle | None) -> None:
    if handle and handle._server is not None:
        try:
            handle._server.shutdown()
        except Exception:
            logger.exception("shutdown %s", handle.name)


REMOTE_PANEL_HTML = r"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,maximum-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0f0f12">
<title data-i18n="panel.doc_title">Panel partnerki · Lovense</title>
<style>
:root{
  --bg:#0b0b10; --card:#16161f; --card2:#1e1e2a; --accent:#e11d48; --accent2:#a855f7;
  --ok:#22c55e; --bad:#ef4444; --text:#fafafa; --muted:#a1a1aa; --line:#2a2a36;
  --side:4.6rem; --dock:calc(4.1rem + env(safe-area-inset-bottom));
  --header:3.4rem;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);
  font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
/* ===== shell: lewy nav + treść, bez scrolla całej strony ===== */
.app{
  display:grid;
  grid-template-columns:var(--side) 1fr;
  grid-template-rows:var(--header) 1fr var(--dock);
  height:100dvh;height:100vh;
  max-width:720px;margin:0 auto;
}
.side{
  grid-row:1 / -1;
  grid-column:1;
  background:#101018;
  border-right:1px solid var(--line);
  display:flex;flex-direction:column;align-items:stretch;
  padding:calc(.55rem + env(safe-area-inset-top)) .35rem calc(.55rem + env(safe-area-inset-bottom));
  gap:.35rem;z-index:20;
}
.brand{
  text-align:center;font-size:1.15rem;line-height:1;padding:.35rem 0 .55rem;
  user-select:none;
}
.nav{display:flex;flex-direction:column;gap:.3rem;flex:1}
.tab{
  border:1px solid transparent;border-radius:12px;
  background:transparent;color:var(--muted);
  padding:.55rem .2rem;min-height:3.35rem;
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.2rem;
  cursor:pointer;font-weight:700;font-size:.68rem;letter-spacing:.02em;
}
.tab .ico{font-size:1.15rem;line-height:1;opacity:.9}
.tab:active{transform:scale(.96)}
.tab.on{
  background:#3f0d1a;border-color:var(--accent);color:#fecdd3;
}
.side-foot{margin-top:auto;display:flex;flex-direction:column;align-items:center;gap:.35rem}
.pill{
  font-size:.55rem;padding:.2rem .3rem;border-radius:999px;
  background:var(--card2);color:var(--muted);border:1px solid var(--line);
  text-align:center;max-width:100%;line-height:1.2;word-break:break-word;
}
.pill.on{color:var(--ok);border-color:#14532d;background:#052e16}
.pill.off{color:var(--bad);border-color:#7f1d1d;background:#450a0a}

.top{
  grid-column:2;grid-row:1;
  display:flex;align-items:center;justify-content:space-between;gap:.6rem;
  padding:.55rem .85rem 0;border-bottom:1px solid transparent;
}
.top h1{font-size:1.05rem;margin:0;letter-spacing:-.02em}
.top .sub{display:none}
.meter{
  height:5px;background:#0f0f14;border-radius:99px;overflow:hidden;
  border:1px solid var(--line);width:min(140px,28vw);flex-shrink:0;
}
.meter>i{display:block;height:100%;width:0%;background:linear-gradient(90deg,var(--accent2),var(--accent));transition:width .15s ease}

.main{
  grid-column:2;grid-row:2;
  overflow:hidden;display:flex;flex-direction:column;
  padding:.55rem .75rem 0;
  min-height:0;
}
/* status pasek pod nagłówkiem */
.status-bar{
  flex-shrink:0;
  background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:.45rem .7rem;margin-bottom:.55rem;
  font-size:.78rem;color:var(--muted);
  max-height:4.2rem;overflow:auto;
}
.toys{line-height:1.4}
.toy{display:flex;align-items:center;gap:.4rem;padding:.1rem 0;font-size:.8rem;color:var(--text)}
.dot{width:.5rem;height:.5rem;border-radius:50%;background:var(--ok);flex-shrink:0}
.dot.off{background:#52525b}
.bat{margin-left:auto;font-size:.72rem;color:var(--muted);font-variant-numeric:tabular-nums}
.status-msg{font-size:.72rem;margin-top:.2rem;word-break:break-word}
.msg-ok{color:#86efac}.msg-err{color:#fca5a5}

/* treść aktywnej kategorii — scroll TYLKO tutaj gdy trzeba */
.panels{flex:1;min-height:0;position:relative}
.panel{
  display:none;height:100%;overflow:auto;
  -webkit-overflow-scrolling:touch;padding-bottom:.4rem;
}
.panel.on{display:block}
.card{
  background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:.75rem .8rem;
}
.subhead{
  font-size:.65rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
  font-weight:650;margin:0 0 .45rem;
  display:flex;align-items:center;gap:.35rem;flex-wrap:wrap;
}
.subhead .tag{
  font-size:.58rem;letter-spacing:.03em;text-transform:none;font-weight:600;
  color:var(--accent2);background:#2a1a3a;border:1px solid #4c1d6e;
  padding:.1rem .35rem;border-radius:999px;
}
.subblock{margin-bottom:.8rem}
.subblock:last-child{margin-bottom:0}

/* pod-zakładki wewnątrz kategorii (jeszcze mniej scrolla) */
.subtabs{
  display:flex;gap:.3rem;margin-bottom:.6rem;flex-wrap:wrap;
}
.subtab{
  border:1px solid var(--line);border-radius:999px;
  background:var(--card2);color:var(--muted);
  padding:.35rem .7rem;font-size:.72rem;font-weight:650;
  min-height:2rem;cursor:pointer;
}
.subtab.on{border-color:var(--accent);background:#3f0d1a;color:#fecdd3}
.subpane{display:none}
.subpane.on{display:block}

label.row{display:flex;justify-content:space-between;align-items:baseline;font-size:.85rem;margin:0 0 .25rem}
.value{font-variant-numeric:tabular-nums;font-weight:700;color:var(--accent);font-size:1rem}
input[type=range]{width:100%;height:1.9rem;accent-color:var(--accent);margin:0 0 .55rem}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:.35rem}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:.35rem}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:.35rem}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:.4rem}
button{
  border:none;border-radius:11px;padding:.55rem .35rem;font-weight:650;cursor:pointer;
  background:var(--card2);color:var(--text);font-size:.78rem;border:1px solid var(--line);
  min-height:2.45rem;
}
button:active{transform:scale(.97);filter:brightness(1.08)}
button.active{border-color:var(--accent);background:#3f0d1a;color:#fecdd3}
button.violet{background:var(--accent2);border-color:transparent;color:#fff}
button.soft{background:#27272a}
button.rose{background:#3f0d1a;border-color:#7f1d1d;color:#fecdd3}
.chip{font-size:.72rem;padding:.45rem .25rem}
.live{display:flex;align-items:center;justify-content:space-between;gap:.6rem;font-size:.82rem}
.toggle{position:relative;width:46px;height:26px;flex-shrink:0}
.toggle input{opacity:0;width:0;height:0}
.slider{position:absolute;inset:0;background:#3f3f46;border-radius:999px;cursor:pointer;transition:.2s}
.slider:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
.toggle input:checked+.slider{background:var(--accent)}
.toggle input:checked+.slider:before{transform:translateX(20px)}
.hint{font-size:.68rem;color:var(--muted);margin:.35rem 0 0;line-height:1.35}
.pat{display:grid;grid-template-columns:1fr 1fr;gap:.35rem}
.pat button{text-align:left;padding:.55rem .65rem}
.pat b{display:block;font-size:.82rem;margin-bottom:.1rem}
.pat span{display:block;font-size:.65rem;color:var(--muted);font-weight:500}
.preset-btn{display:flex;flex-direction:column;align-items:flex-start;text-align:left;padding:.55rem .65rem;gap:.08rem}
.preset-btn b{font-size:.82rem;font-weight:700}
.preset-btn span{font-size:.64rem;color:var(--muted);font-weight:500}

.dock{
  grid-column:2;grid-row:3;
  display:flex;align-items:center;gap:.45rem;
  padding:.45rem .75rem calc(.45rem + env(safe-area-inset-bottom));
  background:linear-gradient(180deg,transparent 0%,#0b0b10 35%);
  border-top:1px solid var(--line);
}
.dock .stop{
  flex:1.25;background:var(--bad);border:none;color:#fff;
  font-size:.95rem;min-height:3rem;border-radius:12px;font-weight:800;letter-spacing:.04em;
}
.dock .send{
  flex:1;background:var(--accent);border:none;color:#fff;
  min-height:3rem;border-radius:12px;font-weight:700;font-size:.9rem;
}
.toast{position:fixed;top:max(10px,env(safe-area-inset-top));left:50%;transform:translateX(-50%);
  background:#18181b;border:1px solid var(--line);padding:.5rem .9rem;border-radius:999px;font-size:.78rem;
  opacity:0;pointer-events:none;transition:opacity .2s;z-index:100;max-width:85%}
.toast.show{opacity:1}

/* szerszy ekran: szerszy lewy pasek z pełnymi etykietami */
@media (min-width:480px){
  :root{--side:6.5rem}
  .tab{font-size:.78rem;padding:.65rem .3rem}
  .tab .ico{font-size:1.25rem}
  .top .sub{display:block;color:var(--muted);font-size:.72rem;margin:.15rem 0 0}
  .top h1{font-size:1.15rem}
}
@media (min-width:640px){
  :root{--side:8rem}
  .app{max-width:820px}
  .tab{flex-direction:row;justify-content:flex-start;gap:.45rem;padding:.7rem .65rem;font-size:.85rem}
}
.lang-wrap{display:flex;flex-direction:column;align-items:stretch;gap:.12rem;width:100%;margin:0 0 .3rem}
.lang-lab{font-size:.5rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);text-align:center}
.lang-select{width:100%;font-size:.55rem;padding:.18rem .08rem;border-radius:8px;border:1px solid var(--line);background:var(--card2);color:var(--text)}
#joinOverlay .lang-wrap,.panel .lang-wrap{flex-direction:row;align-items:center;justify-content:space-between;margin:0 0 .75rem}
#joinOverlay .lang-lab,.panel .lang-lab{font-size:.75rem;text-align:left;text-transform:none;letter-spacing:0}
#joinOverlay .lang-select,.panel .lang-select{width:auto;min-width:9rem;font-size:.85rem;padding:.35rem .5rem}
@media (min-width:640px){
  .lang-lab{font-size:.62rem;text-align:left}
  .lang-select{font-size:.72rem;padding:.3rem .35rem}
}
</style>
</head>
<body>
<div class="app">
  <!-- LEWY PASEK: kategorie -->
  <aside class="side" data-i18n-aria="nav.aria" aria-label="Kategorie">
    <div class="brand" title="Lovense">💜</div>
    <nav class="nav" role="tablist">
      <button type="button" class="tab on" data-tab="sila" role="tab" aria-selected="true">
        <span class="ico">⚡</span><span data-i18n="nav.power">Siła</span>
      </button>
      <button type="button" class="tab" data-tab="wzorce" role="tab" aria-selected="false">
        <span class="ico">🌊</span><span data-i18n="nav.patterns">Wzorce</span>
      </button>
      <button type="button" class="tab" data-tab="opcje" role="tab" aria-selected="false">
        <span class="ico">⚙️</span><span data-i18n="nav.options">Opcje</span>
      </button>
    </nav>
    <div class="side-foot">
      <!--LANG_SELECT_SIDE-->
      <div id="connPill" class="pill off">off</div>
    </div>
  </aside>

  <header class="top">
    <div>
      <h1 id="panelTitle" data-i18n="nav.power">Siła</h1>
      <p class="sub" data-i18n="panel.subtitle">Panel partnerski</p>
    </div>
    <div class="meter" data-i18n-title="panel.meter" title="Siła wibracji"><i id="meterBar"></i></div>
  </header>

  <main class="main">
    <div class="status-bar">
      <div class="toys" id="toys" data-i18n="panel.connecting">Łączenie…</div>
      <label class="row" style="margin:.35rem 0 0;font-size:.78rem"><span data-i18n="panel.target">Cel (zabawka)</span>
        <select id="toySelect" style="max-width:58%;background:#0f0f14;color:#fff;border:1px solid var(--line);border-radius:8px;padding:.25rem .4rem;font-size:.75rem">
          <option value="" data-i18n="panel.all_toys">Wszystkie dozwolone</option>
        </select>
      </label>
      <div class="status-msg" id="status">—</div>
    </div>
    <div id="joinOverlay" style="display:none;position:fixed;inset:0;z-index:200;background:#0b0b10ee;align-items:center;justify-content:center;padding:1rem">
      <div style="background:var(--card);border:1px solid var(--line);border-radius:16px;padding:1.25rem;max-width:360px;width:100%">
        <!--LANG_SELECT_JOIN-->
        <h2 style="margin:0 0 .5rem;font-size:1.1rem" data-i18n="join.title">Jak masz na imię?</h2>
        <p style="color:var(--muted);font-size:.8rem;margin:0 0 .75rem" data-i18n="join.hint">Host zobaczy Twoją nazwę i będzie mógł nadać uprawnienia do zabawek.</p>
        <input id="joinName" type="text" maxlength="40" data-i18n-placeholder="join.placeholder" placeholder="np. Ania" style="width:100%;padding:.7rem;border-radius:10px;border:1px solid var(--line);background:#0f0f14;color:#fff;font-size:1rem;box-sizing:border-box;margin-bottom:.6rem">
        <button type="button" class="violet" id="joinBtn" style="width:100%" data-i18n="join.button">Dołącz do panelu</button>
        <p id="joinErr" class="hint" style="color:#fca5a5"></p>
      </div>
    </div>

    <div class="panels">
      <!-- ===== SIŁA ===== -->
      <div class="panel on" id="panel-sila" role="tabpanel">
        <div class="subtabs" data-group="sila">
          <button type="button" class="subtab on" data-sub="quick" data-i18n="sub.quick">Poziomy</button>
          <button type="button" class="subtab" data-sub="sliders" data-i18n="sub.sliders">Suwaki</button>
          <button type="button" class="subtab" data-sub="boost" data-i18n="sub.boost">Boost</button>
        </div>
        <div class="card">
          <div class="subpane on" data-subpane="quick" data-group="sila">
            <div class="subhead"><span data-i18n="quick.head">Szybkie poziomy</span> <span class="tag">0–9</span></div>
            <div class="grid" id="quickLevels"></div>
            <p class="hint" data-i18n="quick.hint">0 = stop. Jedno kliknięcie ustawia wibracje.</p>
          </div>
          <div class="subpane" data-subpane="sliders" data-group="sila">
            <div class="subhead"><span data-i18n="sliders.head">Precyzyjnie</span> <span class="tag" data-i18n="sliders.tag">suwaki</span></div>
            <label class="row"><span data-i18n="vibrate">Wibracje</span> <span class="value" id="vLabel">0</span></label>
            <input type="range" id="vibrate" min="0" max="20" value="0" step="1">
            <label class="row"><span data-i18n="pump">Pump / 2. funkcja</span> <span class="value" id="pLabel">0</span></label>
            <input type="range" id="pump" min="0" max="3" value="0" step="1">
            <p class="hint" data-i18n="sliders.hint">Live i czas impulsu — w Opcjach.</p>
          </div>
          <div class="subpane" data-subpane="boost" data-group="sila">
            <div class="subhead"><span data-i18n="boost.head">Boost</span> <span class="tag" data-i18n="boost.tag">krótki zastrzyk</span></div>
            <div class="grid3">
              <button type="button" class="soft" data-boost="8" data-i18n="boost.light">Lekki 3s</button>
              <button type="button" class="soft" data-boost="14" data-i18n="boost.strong">Mocny 3s</button>
              <button type="button" class="soft" data-boost="20" data-i18n="boost.max">Max 2s</button>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== WZORCE ===== -->
      <div class="panel" id="panel-wzorce" role="tabpanel">
        <div class="subtabs" data-group="wzorce">
          <button type="button" class="subtab on" data-sub="classic" data-i18n="sub.classic">Klasyczne</button>
          <button type="button" class="subtab" data-sub="special" data-i18n="sub.special">Specjalne</button>
          <button type="button" class="subtab" data-sub="long" data-i18n="sub.long">Długie</button>
          <button type="button" class="subtab" data-sub="rhythm" data-i18n="sub.rhythm">Rytm</button>
          <button type="button" class="subtab" data-sub="time" data-i18n="sub.time">Czas</button>
        </div>
        <div class="card">
          <div class="subpane on" data-subpane="classic" data-group="wzorce">
            <div class="subhead"><span data-i18n="classic.head">Presety klasyczne</span> <span class="tag">API</span></div>
            <div class="grid2">
              <button type="button" class="violet preset-btn" data-preset="pulse" data-sec="10"><b>Pulse</b><span data-i18n="preset.pulse">pulsowanie · 10s</span></button>
              <button type="button" class="violet preset-btn" data-preset="wave" data-sec="12"><b>Wave</b><span data-i18n="preset.wave">fala · 12s</span></button>
              <button type="button" class="violet preset-btn" data-preset="fireworks" data-sec="10"><b>Fireworks</b><span data-i18n="preset.fireworks">wybuchy · 10s</span></button>
              <button type="button" class="violet preset-btn" data-preset="earthquake" data-sec="12"><b>Earthquake</b><span data-i18n="preset.earthquake">trzęsienie · 12s</span></button>
            </div>
          </div>
          <div class="subpane" data-subpane="special" data-group="wzorce">
            <div class="subhead"><span data-i18n="special.head">Presety specjalne</span> <span class="tag" data-i18n="special.tag">+ nowe</span></div>
            <div class="grid2">
              <button type="button" class="rose preset-btn" data-preset="tease" data-sec="15"><b>Tease</b><span data-i18n="preset.tease">drażnienie · 15s</span></button>
              <button type="button" class="rose preset-btn" data-preset="climb" data-sec="12"><b>Climb</b><span data-i18n="preset.climb">wspinaczka · 12s</span></button>
              <button type="button" class="rose preset-btn" data-preset="edge" data-sec="14"><b>Edge</b><span data-i18n="preset.edge">na krawędzi · 14s</span></button>
              <button type="button" class="rose preset-btn" data-preset="throb" data-sec="10"><b>Throb</b><span data-i18n="preset.throb">bicie · 10s</span></button>
              <button type="button" class="rose preset-btn" data-preset="heartbeat" data-sec="16"><b>Heartbeat</b><span data-i18n="preset.heartbeat">serce · 16s</span></button>
              <button type="button" class="rose preset-btn" data-preset="ripple" data-sec="14"><b>Ripple</b><span data-i18n="preset.ripple">małe fale · 14s</span></button>
              <button type="button" class="rose preset-btn" data-preset="stutter" data-sec="12"><b>Stutter</b><span data-i18n="preset.stutter">przerywane · 12s</span></button>
              <button type="button" class="rose preset-btn" data-preset="bounce" data-sec="12"><b>Bounce</b><span data-i18n="preset.bounce">odbicia · 12s</span></button>
              <button type="button" class="rose preset-btn" data-preset="cascade" data-sec="15"><b>Cascade</b><span data-i18n="preset.cascade">kaskada · 15s</span></button>
              <button type="button" class="rose preset-btn" data-preset="breath" data-sec="20"><b>Breath</b><span data-i18n="preset.breath">oddech · 20s</span></button>
              <button type="button" class="rose preset-btn" data-preset="ocean" data-sec="25"><b>Ocean</b><span data-i18n="preset.ocean">morze · 25s</span></button>
              <button type="button" class="rose preset-btn" data-preset="spark" data-sec="10"><b>Spark</b><span data-i18n="preset.spark">iskry · 10s</span></button>
            </div>
          </div>
          <div class="subpane" data-subpane="long" data-group="wzorce">
            <div class="subhead"><span data-i18n="long.head">Długie sekwencje</span> <span class="tag">35–60 s</span></div>
            <div class="grid2">
              <button type="button" class="violet preset-btn" data-preset="slowburn" data-sec="45"><b>Slow burn</b><span data-i18n="preset.slowburn">wolny wzrost · 45s</span></button>
              <button type="button" class="violet preset-btn" data-preset="marathon" data-sec="60"><b>Maraton</b><span data-i18n="preset.marathon">długa jazda · 60s</span></button>
              <button type="button" class="violet preset-btn" data-preset="teaselong" data-sec="40"><b>Tease long</b><span data-i18n="preset.teaselong">długie drażnienie · 40s</span></button>
              <button type="button" class="violet preset-btn" data-preset="edgelong" data-sec="45"><b>Edge long</b><span data-i18n="preset.edgelong">długa krawędź · 45s</span></button>
              <button type="button" class="violet preset-btn" data-preset="waveslow" data-sec="50"><b>Wave slow</b><span data-i18n="preset.waveslow">wolna fala · 50s</span></button>
              <button type="button" class="violet preset-btn" data-preset="deepwave" data-sec="55"><b>Deep wave</b><span data-i18n="preset.deepwave">głęboka fala · 55s</span></button>
              <button type="button" class="violet preset-btn" data-preset="crescendo" data-sec="40"><b>Crescendo</b><span data-i18n="preset.crescendo">narastanie · 40s</span></button>
              <button type="button" class="violet preset-btn" data-preset="afterglow" data-sec="35"><b>Afterglow</b><span data-i18n="preset.afterglow">wyciszanie · 35s</span></button>
            </div>
            <p class="hint" data-i18n="long.hint">Czas z przycisku ma pierwszeństwo; zakładka „Czas” zmienia domyślny dla krótkich wzorców.</p>
          </div>
          <div class="subpane" data-subpane="rhythm" data-group="wzorce">
            <div class="subhead"><span data-i18n="rhythm.head">Wzorce rytmiczne</span> <span class="tag">pattern</span></div>
            <div class="pat">
              <button type="button" data-pattern="0;8;16;20;16;8;0" data-int="180" data-sec="12"><b data-i18n="pat.wave">Fala</b><span data-i18n="pat.wave.d">miękko góra–dół</span></button>
              <button type="button" data-pattern="20;0;20;0;20;0" data-int="200" data-sec="10"><b data-i18n="pat.strobe">Strobe</b><span data-i18n="pat.strobe.d">ostre impulsy</span></button>
              <button type="button" data-pattern="4;8;12;16;20;16;12;8" data-int="120" data-sec="12"><b data-i18n="pat.build">Budowa</b><span data-i18n="pat.build.d">rosnąco</span></button>
              <button type="button" data-pattern="20;15;10;5;10;15;20" data-int="150" data-sec="12"><b data-i18n="pat.swing">Huśtawka</b><span data-i18n="pat.swing.d">góra i dół</span></button>
              <button type="button" data-pattern="0;0;18;18;0;0;12;12" data-int="160" data-sec="12"><b data-i18n="pat.telegraph">Telegraf</b><span data-i18n="pat.telegraph.d">krótko–długo</span></button>
              <button type="button" data-pattern="10;12;14;16;18;20;18;16" data-int="100" data-sec="10"><b data-i18n="pat.vibro">Wibro</b><span data-i18n="pat.vibro.d">szybkie zmiany</span></button>
              <button type="button" data-pattern="0;10;0;14;0;18;0;20;0;10" data-int="200" data-sec="14"><b data-i18n="pat.knock">Pukanie</b><span data-i18n="pat.knock.d">rytm serca</span></button>
              <button type="button" data-pattern="5;10;15;20;15;10;5;10;15;10;5" data-int="220" data-sec="16"><b data-i18n="pat.sine">Sinus</b><span data-i18n="pat.sine.d">gładka fala</span></button>
              <button type="button" data-pattern="2;4;6;8;10;12;14;16;18;20;18;16;14;12;10;8;6;4;2" data-int="300" data-sec="30"><b data-i18n="pat.ramp">Długa rampa</b><span data-i18n="pat.ramp.d">~30 s w górę/dół</span></button>
              <button type="button" data-pattern="8;8;8;16;16;16;8;8;20;20;4;4;12;12" data-int="250" data-sec="20"><b data-i18n="pat.blocks">Bloki</b><span data-i18n="pat.blocks.d">płaskie odcinki</span></button>
              <button type="button" data-pattern="0;5;0;10;0;15;0;20;0;15;0;10;0;5;0" data-int="280" data-sec="25"><b data-i18n="pat.sparks">Iskry long</b><span data-i18n="pat.sparks.d">przerywane 25s</span></button>
              <button type="button" data-pattern="12;14;16;18;20;18;16;14;12;10;8;10;12;14;16;18;16;14;12" data-int="350" data-sec="40"><b data-i18n="pat.marathon">Maraton rytm</b><span data-i18n="pat.marathon.d">wolno ~40s</span></button>
            </div>
          </div>
          <div class="subpane" data-subpane="time" data-group="wzorce">
            <div class="subhead"><span data-i18n="time.head">Czas trwania</span> <span class="tag">preset / pattern</span></div>
            <div class="grid4" id="durGrid"></div>
            <p class="hint" data-i18n="time.hint">Domyślny czas, gdy przycisk nie ma własnego. STOP zawsze od razu.</p>
          </div>
        </div>
      </div>

      <!-- ===== OPCJE ===== -->
      <div class="panel" id="panel-opcje" role="tabpanel">
        <div class="card">
          <div class="subblock">
            <div class="subhead" data-i18n="lang.label">Język</div>
            <!--LANG_SELECT_JOIN-->
          </div>
          <div class="subblock">
            <div class="subhead"><span data-i18n="audio.head">Audio → zabawka</span> <span class="tag" data-i18n="audio.tag">u hosta</span></div>
            <div class="live">
              <span id="audioLbl" data-i18n="audio.off">Reakcja na dźwięk (wył.)</span>
              <label class="toggle"><input type="checkbox" id="audioReact"><span class="slider"></span></label>
            </div>
            <div class="grid2" style="margin-top:.5rem">
              <button type="button" class="soft" id="audioOn" data-i18n="audio.enable">Włącz audio</button>
              <button type="button" class="soft" id="audioOff" data-i18n="audio.disable">Wyłącz audio</button>
            </div>
            <label class="row" style="margin-top:.65rem"><span data-i18n="audio.sens">Czułość</span> <span class="value" id="sensLabel">1.4</span></label>
            <input type="range" id="audioSens" min="0.3" max="3.0" value="1.4" step="0.1">
            <label class="row"><span data-i18n="audio.gain">Wzmocnienie (gain)</span> <span class="value" id="gainLabel">10</span></label>
            <input type="range" id="audioGain" min="1" max="30" value="10" step="0.5">
            <div class="live" style="margin-top:.5rem">
              <span data-i18n="audio.bands">Bas → wibracje, treble → 2. funkcja</span>
              <label class="toggle"><input type="checkbox" id="audioBands" checked><span class="slider"></span></label>
            </div>
            <div id="audioBandsBox">
              <div class="live"><span data-i18n="audio.bass_vib">Wibracje od basu</span>
                <label class="toggle"><input type="checkbox" id="audioBassVib" checked><span class="slider"></span></label></div>
              <div class="live"><span data-i18n="audio.bass_pump">Pump od basu</span>
                <label class="toggle"><input type="checkbox" id="audioBassPump"><span class="slider"></span></label></div>
              <div class="live"><span data-i18n="audio.treble_vib">Wibracje od treble</span>
                <label class="toggle"><input type="checkbox" id="audioTrebleVib"><span class="slider"></span></label></div>
              <div class="live"><span data-i18n="audio.treble_pump">Pump od treble</span>
                <label class="toggle"><input type="checkbox" id="audioTreblePump" checked><span class="slider"></span></label></div>
              <label class="row"><span data-i18n="audio.bass">Wzmocnienie basu</span> <span class="value" id="bassGainLabel">1.0</span></label>
              <input type="range" id="audioBassGain" min="0.2" max="4" value="1" step="0.1">
              <label class="row"><span data-i18n="audio.treble">Wzmocnienie treble</span> <span class="value" id="trebleGainLabel">1.8</span></label>
              <input type="range" id="audioTrebleGain" min="0.2" max="6" value="1.8" step="0.1">
            </div>
            <p class="hint" id="audioHint" data-i18n="audio.hint">Dźwięk u partnera (PC) → wibracje. Czułość/gain działają od razu gdy audio WŁ.</p>
          </div>
          <div class="subblock">
            <div class="subhead"><span data-i18n="live.head">Tryb live</span> <span class="tag" data-i18n="live.tag">suwaki</span></div>
            <div class="live">
              <span data-i18n="live.label">Suwaki od razu wysyłają</span>
              <label class="toggle"><input type="checkbox" id="live" checked><span class="slider"></span></label>
            </div>
            <p class="hint" data-i18n="live.hint">Wyłącz → ustaw poziomy, potem „Wyślij”.</p>
          </div>
          <div class="subblock">
            <div class="subhead"><span data-i18n="impulse.head">Czas impulsu</span> <span class="tag">function</span></div>
            <label class="row"><span data-i18n="impulse.sec">Sekundy</span> <span class="value" id="tLabel">0</span></label>
            <input type="range" id="time" min="0" max="30" value="0" step="1">
            <p class="hint" data-i18n="impulse.hint">0 = bez limitu (do STOP). &gt;0 = krótki impuls.</p>
          </div>
          <div class="subblock">
            <div class="subhead" data-i18n="safety.head">Bezpieczeństwo</div>
            <p class="hint" style="margin-top:0" data-i18n="safety.hint">STOP zawsze na dole · szanuj granice · link z tokenem jest prywatny.</p>
          </div>
        </div>
      </div>
    </div>
  </main>

  <div class="dock">
    <button type="button" class="stop" id="btnStop" data-i18n="dock.stop">STOP</button>
    <button type="button" class="send" id="btnApply" data-i18n="dock.send">Wyślij</button>
  </div>
</div>
<div class="toast" id="toast"></div>
<!--I18N_BOOT-->
<script>
const params = new URLSearchParams(location.search);
let TOKEN = params.get('token') || '';
if(!TOKEN){
  const m = location.pathname.match(/\/r\/([^/]+)/);
  if(m) TOKEN = decodeURIComponent(m[1]);
}

const $ = (id) => document.getElementById(id);
const vibrate = $('vibrate'), pump = $('pump'), time = $('time');
const vLabel = $('vLabel'), pLabel = $('pLabel'), tLabel = $('tLabel');
const statusEl = $('status'), toysEl = $('toys'), meterBar = $('meterBar');
const connPill = $('connPill'), liveEl = $('live'), toastEl = $('toast');
const panelTitle = $('panelTitle');
const toySelect = $('toySelect');
const joinOverlay = $('joinOverlay');
const audioReactEl = $('audioReact');
const audioLbl = $('audioLbl');
const audioHint = $('audioHint');
const audioSens = $('audioSens');
const audioGain = $('audioGain');
const audioBands = $('audioBands');
const audioBandsBox = $('audioBandsBox');
const audioBassGain = $('audioBassGain');
const audioTrebleGain = $('audioTrebleGain');
const bassGainLabel = $('bassGainLabel');
const trebleGainLabel = $('trebleGainLabel');
const audioBassVib = $('audioBassVib');
const audioBassPump = $('audioBassPump');
const audioTrebleVib = $('audioTrebleVib');
const audioTreblePump = $('audioTreblePump');
const sensLabel = $('sensLabel');
const gainLabel = $('gainLabel');
let audioAllowed = true;
let audioParamsAllowed = true;
let audioSyncing = false;
let audioParamTimer = null;

const TAB_KEYS = { sila: 'nav.power', wzorce: 'nav.patterns', opcje: 'nav.options' };
const SS_KEY = 'lc_session_' + (TOKEN || '').slice(0, 12);
const NAME_KEY = 'lc_name';
function tabTitle(id){ return t(TAB_KEYS[id] || id); }
function errText(code, fallback){
  const key = 'err.' + code;
  const s = t(key);
  return (s && s !== key) ? s : (fallback || s);
}

let patternDuration = 10;
let dragging = false;
let lastOk = true;
let SESSION_ID = localStorage.getItem(SS_KEY) || '';
let DISPLAY_NAME = localStorage.getItem(NAME_KEY) || '';
let canControl = true;
let joined = false;

function selectedToy(){
  return (toySelect && toySelect.value) ? toySelect.value : null;
}

function showJoin(err){
  joined = false;
  joinOverlay.style.display = 'flex';
  $('joinName').value = DISPLAY_NAME || '';
  $('joinErr').textContent = err || '';
}
function hideJoin(){
  joinOverlay.style.display = 'none';
  joined = true;
}

// --- lewy pasek: kategorie ---
function switchTab(id){
  document.querySelectorAll('.tab').forEach(t => {
    const on = t.dataset.tab === id;
    t.classList.toggle('on', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('on', p.id === 'panel-' + id);
  });
  panelTitle.textContent = tabTitle(id);
  panelTitle.removeAttribute('data-i18n');
  try{ history.replaceState(null, '', '#' + id); }catch(e){}
}
document.querySelectorAll('.tab').forEach(tab => {
  tab.onclick = () => switchTab(tab.dataset.tab);
});
(function restoreTab(){
  const h = (location.hash || '').replace('#','').toLowerCase();
  if(['sila','wzorce','opcje'].includes(h)) switchTab(h);
})();

// --- pod-zakładki w kategorii ---
document.querySelectorAll('.subtabs').forEach(bar => {
  const group = bar.dataset.group;
  bar.querySelectorAll('.subtab').forEach(btn => {
    btn.onclick = () => {
      bar.querySelectorAll('.subtab').forEach(b => b.classList.toggle('on', b === btn));
      document.querySelectorAll('.subpane[data-group="'+group+'"]').forEach(pane => {
        pane.classList.toggle('on', pane.dataset.subpane === btn.dataset.sub);
      });
    };
  });
});

function toast(msg){
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => toastEl.classList.remove('show'), 1600);
}
function buzz(ms=12){
  try{ if(navigator.vibrate) navigator.vibrate(ms); }catch(e){}
}
function syncLabels(){
  vLabel.textContent = vibrate.value;
  pLabel.textContent = pump.value;
  tLabel.textContent = time.value === '0' ? '∞' : time.value;
  meterBar.style.width = (100 * (+vibrate.value / (+vibrate.max || 20))) + '%';
  document.querySelectorAll('#quickLevels button').forEach(b => {
    b.classList.toggle('active', +b.dataset.level === +vibrate.value);
  });
}
function setLevels(v, p, send=true){
  if(v != null) vibrate.value = Math.max(0, Math.min(+vibrate.max, v));
  if(p != null) pump.value = Math.max(0, Math.min(+pump.max, p));
  syncLabels();
  if(send && liveEl.checked) liveSend();
}

const qg = $('quickLevels');
for(let i=0;i<=9;i++){
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'chip';
  b.dataset.level = i === 0 ? 0 : Math.round(i * 20 / 9);
  b.textContent = i === 0 ? '0' : String(i);
  b.onclick = () => { buzz(); setLevels(+b.dataset.level, null, true); if(!liveEl.checked) sendNow(); };
  qg.appendChild(b);
}

const durs = [5, 10, 15, 20, 30, 45, 60];
const dg = $('durGrid');
durs.forEach((d) => {
  const b = document.createElement('button');
  b.type = 'button';
  b.textContent = d + 's';
  if(d === 10) b.classList.add('active');
  b.onclick = () => {
    patternDuration = d;
    dg.querySelectorAll('button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    toast(t('toast.time', {n: d}));
  };
  dg.appendChild(b);
});

let debounceTimer = null;
function liveSend(){
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => sendControl({
    action: 'function',
    vibrate: +vibrate.value,
    pump: +pump.value,
    time_sec: +time.value
  }), 90);
}

['vibrate','pump','time'].forEach(id => {
  const el = $(id);
  el.addEventListener('pointerdown', () => { dragging = true; });
  el.addEventListener('pointerup', () => { dragging = false; if(liveEl.checked) liveSend(); });
  el.addEventListener('input', () => { syncLabels(); if(liveEl.checked) liveSend(); });
  el.addEventListener('change', () => { if(liveEl.checked) liveSend(); });
});

async function api(path, opts={}){
  const method = (opts.method || 'GET').toUpperCase();
  const headers = Object.assign({'X-API-Token': TOKEN}, opts.headers||{});
  if (SESSION_ID) headers['X-Session-Id'] = SESSION_ID;
  if (method !== 'GET' && method !== 'HEAD') headers['Content-Type'] = 'application/json';
  const sep = path.includes('?') ? '&' : '?';
  let url = path + sep + 'token=' + encodeURIComponent(TOKEN);
  if (SESSION_ID) url += '&session=' + encodeURIComponent(SESSION_ID);
  const res = await fetch(url, { ...opts, method, headers });
  const data = await res.json().catch(() => ({}));
  if(!res.ok){
    const err = data.error || res.statusText;
    if(err === 'kicked' || err === 'banned'){
      SESSION_ID = '';
      localStorage.removeItem(SS_KEY);
      showJoin(errText(err === 'banned' ? 'banned' : 'kicked_rejoin', data.message));
    }
    if(err === 'no_session'){
      SESSION_ID = '';
      localStorage.removeItem(SS_KEY);
      showJoin(errText('no_session', data.message));
    }
    const e = new Error(errText(err, data.message || err));
    e.code = err;
    throw e;
  }
  return data;
}

async function joinSession(name){
  DISPLAY_NAME = (name || DISPLAY_NAME || 'Partner').trim().slice(0,40) || 'Partner';
  localStorage.setItem(NAME_KEY, DISPLAY_NAME);
  const data = await api('/api/session/join', {
    method:'POST',
    body: JSON.stringify({ name: DISPLAY_NAME, session_id: SESSION_ID || undefined })
  });
  if(data.session && data.session.id){
    SESSION_ID = data.session.id;
    localStorage.setItem(SS_KEY, SESSION_ID);
    canControl = !!data.session.can_control;
    hideJoin();
    toast(t('toast.joined', {name: DISPLAY_NAME}));
  }
  return data;
}

$('joinBtn').onclick = async () => {
  try{
    $('joinErr').textContent = '';
    await joinSession($('joinName').value);
    refresh();
  }catch(e){
    $('joinErr').textContent = e.message || String(e);
  }
};
$('joinName').addEventListener('keydown', e => { if(e.key==='Enter') $('joinBtn').click(); });

async function sendControl(body){
  if(!joined || !SESSION_ID){
    showJoin(t('toast.join_first'));
    return;
  }
  const act = (body.action || '').toLowerCase();
  const isAudio = act === 'audio' || act === 'audio_toggle' || act === 'audio_on' || act === 'audio_off' || act === 'audio_react';
  if(!canControl && act !== 'stop' && !isAudio){
    statusEl.textContent = t('status.no_control');
    statusEl.className = 'status-msg msg-err';
    toast(t('toast.no_perm'));
    return;
  }
  // audio: host może wyłączyć „can_control” ale audio nadal przez allow_audio
  if(isAudio && !canControl && !audioAllowed){
    toast(t('toast.no_audio'));
    return;
  }
  try{
    const toy = selectedToy();
    if(toy) body = Object.assign({}, body, { toy });
    const data = await api('/api/control', {method:'POST', body: JSON.stringify(body)});
    lastOk = !!data.ok;
    statusEl.textContent = data.message || 'OK';
    statusEl.className = 'status-msg ' + (lastOk ? 'msg-ok' : 'msg-err');
    if(body.action === 'stop') toast(t('toast.stop'));
    return data;
  }catch(e){
    lastOk = false;
    statusEl.textContent = t('status.error', {msg: e.message});
    statusEl.className = 'status-msg msg-err';
    if(e.code !== 'kicked' && e.code !== 'banned' && e.code !== 'no_session'){
      connPill.textContent = 'off';
      connPill.className = 'pill off';
    }
    throw e;
  }
}

function sendNow(){
  return sendControl({
    action:'function', vibrate:+vibrate.value, pump:+pump.value, time_sec:+time.value
  });
}

$('btnApply').onclick = () => { buzz(8); sendNow(); toast(t('toast.sent')); };
$('btnStop').onclick = () => {
  buzz(25);
  setLevels(0, 0, false);
  sendControl({action:'stop'});
};

document.querySelectorAll('[data-preset]').forEach(btn => {
  btn.onclick = () => {
    buzz();
    const sec = btn.dataset.sec ? +btn.dataset.sec : patternDuration;
    sendControl({action:'preset', name: btn.dataset.preset, time_sec: sec});
    toast(t('toast.preset', {name: btn.dataset.preset, n: sec}));
  };
});
document.querySelectorAll('[data-pattern]').forEach(btn => {
  btn.onclick = () => {
    buzz();
    const sec = btn.dataset.sec ? +btn.dataset.sec : patternDuration;
    sendControl({
      action: 'pattern',
      strength: btn.dataset.pattern,
      interval_ms: +btn.dataset.int || 180,
      time_sec: sec
    });
    toast(t('toast.pattern', {n: sec}));
  };
});
document.querySelectorAll('[data-boost]').forEach(btn => {
  btn.onclick = () => {
    buzz(15);
    const v = +btn.dataset.boost;
    const sec = v >= 20 ? 2 : 3;
    setLevels(v, Math.min(+pump.max, v >= 15 ? 2 : 1), false);
    sendControl({ action:'function', vibrate:v, pump:+pump.value, time_sec: sec });
    toast(t('toast.boost', {n: sec}));
  };
});

function fillToySelect(toys){
  if(!toySelect) return;
  const prev = toySelect.value;
  const opts = ['<option value="">' + t('panel.all_toys') + '</option>'];
  (toys||[]).filter(t => t.connected).forEach(t => {
    const id = t.id;
    const lab = (t.display_name||t.name||id).replace(/</g,'');
    opts.push(`<option value="${id}">${lab}</option>`);
  });
  toySelect.innerHTML = opts.join('');
  if(prev && [...toySelect.options].some(o => o.value === prev)) toySelect.value = prev;
}

function setChk(el, val){
  if(!el || val == null) return;
  audioSyncing = true;
  el.checked = !!val;
  audioSyncing = false;
}

function setAudioUi(enabled, mode, allowed, paramsAllowed, sens, gain, bands, bassGain, trebleGain, routes){
  audioAllowed = allowed !== false;
  audioParamsAllowed = paramsAllowed !== false;
  if(audioReactEl){
    audioSyncing = true;
    audioReactEl.checked = !!enabled;
    audioReactEl.disabled = !audioAllowed;
    audioSyncing = false;
  }
  if(audioLbl){
    audioLbl.textContent = enabled
      ? t('audio.on', {mode: mode || 'playback'})
      : t('audio.off');
    audioLbl.removeAttribute('data-i18n');
  }
  if(audioSens && sens != null && document.activeElement !== audioSens){
    audioSyncing = true;
    audioSens.value = sens;
    if(sensLabel) sensLabel.textContent = (+sens).toFixed(1);
    audioSyncing = false;
  }
  if(audioGain && gain != null && document.activeElement !== audioGain){
    audioSyncing = true;
    audioGain.value = gain;
    if(gainLabel) gainLabel.textContent = (+gain).toFixed(1);
    audioSyncing = false;
  }
  if(audioBands && bands != null){
    audioSyncing = true;
    audioBands.checked = !!bands;
    audioSyncing = false;
  }
  if(audioBassGain && bassGain != null && document.activeElement !== audioBassGain){
    audioSyncing = true;
    audioBassGain.value = bassGain;
    if(bassGainLabel) bassGainLabel.textContent = (+bassGain).toFixed(1);
    audioSyncing = false;
  }
  if(audioTrebleGain && trebleGain != null && document.activeElement !== audioTrebleGain){
    audioSyncing = true;
    audioTrebleGain.value = trebleGain;
    if(trebleGainLabel) trebleGainLabel.textContent = (+trebleGain).toFixed(1);
    audioSyncing = false;
  }
  const r = routes || {};
  setChk(audioBassVib, r.bass_to_vibrate);
  setChk(audioBassPump, r.bass_to_pump);
  setChk(audioTrebleVib, r.treble_to_vibrate);
  setChk(audioTreblePump, r.treble_to_pump);
  if(audioBandsBox) audioBandsBox.style.display = (audioBands && audioBands.checked) ? '' : 'none';
  if(audioSens) audioSens.disabled = !audioParamsAllowed;
  if(audioGain) audioGain.disabled = !audioParamsAllowed;
  if(audioBands) audioBands.disabled = !audioParamsAllowed;
  if(audioBassGain) audioBassGain.disabled = !audioParamsAllowed;
  if(audioTrebleGain) audioTrebleGain.disabled = !audioParamsAllowed;
  [audioBassVib, audioBassPump, audioTrebleVib, audioTreblePump].forEach(el => {
    if(el) el.disabled = !audioParamsAllowed;
  });
  if(audioHint){
    if(!audioAllowed) audioHint.textContent = t('audio.blocked');
    else if(!audioParamsAllowed) audioHint.textContent = t('audio.params_blocked');
    else audioHint.textContent = t('audio.hint_bands');
    audioHint.removeAttribute('data-i18n');
  }
  const onB = $('audioOn'), offB = $('audioOff');
  if(onB) onB.disabled = !audioAllowed;
  if(offB) offB.disabled = !audioAllowed;
}

async function setAudioRemote(enabled){
  if(!audioAllowed){ toast(t('toast.audio_blocked')); return; }
  try{
    const data = await sendControl({ action: 'audio', enabled: !!enabled });
    if(data){
      setAudioUi(!!data.audio_enabled, null, audioAllowed, audioParamsAllowed,
        audioSens ? +audioSens.value : null, audioGain ? +audioGain.value : null);
      toast(data.audio_enabled ? t('toast.audio_on') : t('toast.audio_off'));
    }
  }catch(e){
    toast(t('toast.audio_err', {msg: e.message || e}));
  }
}

function scheduleAudioParams(){
  if(audioSyncing || !audioParamsAllowed) return;
  if(sensLabel && audioSens) sensLabel.textContent = (+audioSens.value).toFixed(1);
  if(gainLabel && audioGain) gainLabel.textContent = (+audioGain.value).toFixed(1);
  if(bassGainLabel && audioBassGain) bassGainLabel.textContent = (+audioBassGain.value).toFixed(1);
  if(trebleGainLabel && audioTrebleGain) trebleGainLabel.textContent = (+audioTrebleGain.value).toFixed(1);
  if(audioBandsBox) audioBandsBox.style.display = (audioBands && audioBands.checked) ? '' : 'none';
  clearTimeout(audioParamTimer);
  audioParamTimer = setTimeout(async () => {
    try{
      const data = await sendControl({
        action: 'audio_params',
        sensitivity: audioSens ? +audioSens.value : undefined,
        gain: audioGain ? +audioGain.value : undefined,
        bands: audioBands ? !!audioBands.checked : undefined,
        bass_gain: audioBassGain ? +audioBassGain.value : undefined,
        treble_gain: audioTrebleGain ? +audioTrebleGain.value : undefined,
        bass_to_vibrate: audioBassVib ? !!audioBassVib.checked : undefined,
        bass_to_pump: audioBassPump ? !!audioBassPump.checked : undefined,
        treble_to_vibrate: audioTrebleVib ? !!audioTrebleVib.checked : undefined,
        treble_to_pump: audioTreblePump ? !!audioTreblePump.checked : undefined
      });
      if(data && data.message) statusEl.textContent = data.message;
    }catch(e){
      toast(t('toast.sens_err', {msg: e.message || e}));
    }
  }, 180);
}

if(audioReactEl){
  audioReactEl.addEventListener('change', () => {
    if(audioSyncing) return;
    setAudioRemote(audioReactEl.checked);
  });
}
if($('audioOn')) $('audioOn').onclick = () => setAudioRemote(true);
if($('audioOff')) $('audioOff').onclick = () => setAudioRemote(false);
if(audioSens) audioSens.addEventListener('input', scheduleAudioParams);
if(audioGain) audioGain.addEventListener('input', scheduleAudioParams);
if(audioBands) audioBands.addEventListener('change', scheduleAudioParams);
if(audioBassGain) audioBassGain.addEventListener('input', scheduleAudioParams);
if(audioTrebleGain) audioTrebleGain.addEventListener('input', scheduleAudioParams);
if(audioBassVib) audioBassVib.addEventListener('change', scheduleAudioParams);
if(audioBassPump) audioBassPump.addEventListener('change', scheduleAudioParams);
if(audioTrebleVib) audioTrebleVib.addEventListener('change', scheduleAudioParams);
if(audioTreblePump) audioTreblePump.addEventListener('change', scheduleAudioParams);

async function refresh(){
  if(!joined || !SESSION_ID){
    if(SESSION_ID || DISPLAY_NAME){
      try{
        await joinSession(DISPLAY_NAME || 'Partner');
      }catch(e){
        if(!joined) showJoin(e.message || '');
        return;
      }
    } else {
      showJoin();
      return;
    }
  }
  try{
    const s = await api('/api/status');
    vibrate.max = s.max_vibrate ?? 20;
    pump.max = s.max_pump ?? 3;
    canControl = s.can_control !== false;
    setAudioUi(
      !!s.audio_enabled,
      s.audio_mode,
      s.allow_audio !== false,
      s.allow_audio_params !== false,
      s.audio_sensitivity,
      s.audio_gain,
      s.audio_bands_enabled,
      s.audio_bass_gain,
      s.audio_treble_gain,
      {
        bass_to_vibrate: s.audio_bass_to_vibrate,
        bass_to_pump: s.audio_bass_to_pump,
        treble_to_vibrate: s.audio_treble_to_vibrate,
        treble_to_pump: s.audio_treble_to_pump
      }
    );
    const n = s.connected_count || (s.toys||[]).length || 0;
    connPill.textContent = s.connected ? ('on·' + (n || 1)) : 'off';
    connPill.className = 'pill ' + (s.connected ? 'on' : 'off');
    if(s.session && s.session.display_name){
      connPill.title = s.session.display_name + (canControl ? '' : t('status.watching'));
    } else {
      connPill.title = s.connected ? ('online · ' + n) : t('status.host_no_toy');
    }

    const list = (s.toys||[]).map(toy => {
      const on = toy.connected;
      const bat = toy.battery != null ? toy.battery + '%' : '—';
      return `<div class="toy"><span class="dot ${on?'':'off'}"></span><span>${toy.display_name||toy.name||toy.id}</span><span class="bat">🔋 ${bat}</span></div>`;
    }).join('') || '<div class="toy"><span class="dot off"></span><span>' + t('status.no_toys') + '</span></div>';
    toysEl.innerHTML = list;
    toysEl.removeAttribute('data-i18n');
    fillToySelect(s.toys||[]);

    if(!canControl){
      statusEl.textContent = t('status.no_control_watch');
      statusEl.className = 'status-msg msg-err';
    } else if(s.message){
      statusEl.textContent = s.message;
      statusEl.className = 'status-msg ' + (s.last_ok === false ? 'msg-err' : 'msg-ok');
    }
    document.querySelectorAll('#quickLevels button').forEach(b => {
      const i = b.textContent === '0' ? 0 : +b.textContent;
      b.dataset.level = i === 0 ? 0 : Math.round(i * (+vibrate.max) / 9);
    });
  }catch(e){
    if(e.code === 'kicked' || e.code === 'banned' || e.code === 'no_session') return;
    toysEl.innerHTML = '<div class="toy"><span class="dot off"></span><span>' + t('status.no_link') + '</span></div>';
    toysEl.removeAttribute('data-i18n');
    statusEl.textContent = t('status.offline');
    statusEl.className = 'status-msg msg-err';
    connPill.textContent = 'off';
    connPill.className = 'pill off';
  }
}

window.addEventListener('keydown', (e) => {
  if(e.target.matches('input,textarea')) return;
  if(e.key === ' ' || e.key === 's' || e.key === 'S'){ e.preventDefault(); $('btnStop').click(); }
  if(e.key >= '0' && e.key <= '9' && !e.altKey){
    const i = +e.key;
    const level = i === 0 ? 0 : Math.round(i * (+vibrate.max) / 9);
    setLevels(level, null, true);
    if(!liveEl.checked) sendNow();
  }
  if(e.altKey && e.key === '1') switchTab('sila');
  if(e.altKey && e.key === '2') switchTab('wzorce');
  if(e.altKey && e.key === '3') switchTab('opcje');
});

initI18n();
document.addEventListener('lc-lang', () => {
  const onTab = document.querySelector('.tab.on');
  if (onTab && panelTitle) {
    panelTitle.textContent = tabTitle(onTab.dataset.tab);
    panelTitle.removeAttribute('data-i18n');
  }
  if (joined) refresh();
});
syncLabels();
// start: join overlay jeśli brak sesji
if(!SESSION_ID && !DISPLAY_NAME){
  showJoin();
} else {
  joinOverlay.style.display = 'none';
}
refresh();
setInterval(refresh, 3000);
window.addEventListener('beforeunload', () => {
  if(!SESSION_ID || !TOKEN) return;
  try{
    const body = JSON.stringify({});
    navigator.sendBeacon && navigator.sendBeacon(
      '/api/session/leave?token=' + encodeURIComponent(TOKEN) + '&session=' + encodeURIComponent(SESSION_ID),
      new Blob([body], {type:'application/json'})
    );
  }catch(e){}
});
</script>
</body>
</html>
"""
