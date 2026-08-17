"""Flask: lokalne API gier + zdalny panel sterowania."""

from __future__ import annotations

import logging
import secrets
import threading
from typing import TYPE_CHECKING
from urllib.parse import quote

from flask import Flask, Response, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

if TYPE_CHECKING:
    from max2_controller.controller import Max2Controller
    from max2_controller.config import AppConfig

logger = logging.getLogger(__name__)

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
        html = """<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8"><title>Lovense Controller — Remote</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;background:#0f0f12;color:#f4f4f5;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{background:#1a1a22;padding:2rem;border-radius:16px;max-width:440px;width:92%;box-shadow:0 8px 32px #0008}
h1{font-size:1.35rem;margin:0 0 .5rem}
input,button{width:100%;padding:.8rem;margin:.45rem 0;border-radius:10px;border:1px solid #333;background:#222;color:#fff;font-size:1rem;box-sizing:border-box}
button{background:#e11d48;border:none;cursor:pointer;font-weight:600}
button:hover{background:#be123c}
p{opacity:.8;font-size:.9rem;line-height:1.45}
.hint{font-size:.8rem;opacity:.55;margin-top:1rem}
</style></head><body><div class="card">
<h1>Lovense Controller</h1>
<p>Zdalne sterowanie w przeglądarce. Wklej <b>link z tokenem</b> od partnera albo sam token poniżej.</p>
<input id="tok" type="text" placeholder="Token lub wklej cały link" autocomplete="off" spellcheck="false">
<button onclick="go()">Otwórz panel</button>
<p class="hint">Najwygodniej: otwórz gotowy link (…/r/TOKEN) — bez wpisywania tokenu.</p>
</div>
<script>
function go(){
  let t=document.getElementById('tok').value.trim();
  if(!t) return;
  // jeśli wklejono cały URL z tokenem
  try {
    if(t.includes('://') || t.includes('/r/') || t.includes('token=')) {
      const u = t.includes('://') ? new URL(t) : new URL(t, location.origin);
      const m = u.pathname.match(/\\/r\\/([^/]+)/);
      if(m) { location.href = '/r/' + decodeURIComponent(m[1]); return; }
      const tok = u.searchParams.get('token');
      if(tok) { location.href = '/panel?token=' + encodeURIComponent(tok); return; }
    }
  } catch(e) {}
  location.href = '/r/' + encodeURIComponent(t);
}
document.getElementById('tok').addEventListener('keydown',e=>{if(e.key==='Enter')go();});
</script></body></html>"""
        return Response(html, mimetype="text/html")

    @app.get("/r/<path:token>")
    def panel_short(token: str):
        """Ładny link: http://IP:8787/r/TOKEN — od razu do panelu."""
        from flask import redirect

        tok = _normalize_token(token)
        if not _tokens_equal(tok, str(config.remote_token)):
            return Response(
                "<h1>Nieprawidłowy link</h1><p>Poproś o nowy link od właściciela.</p>"
                "<p>Upewnij się, że skopiowano cały link (token na końcu).</p>"
                "<p><a href='/'>Wróć</a></p>",
                status=401,
                mimetype="text/html",
            )
        # relative redirect — zachowuje host z telefonu (IP LAN / tunnel), nie 127.0.0.1
        return redirect(f"/panel?token={quote(tok, safe='')}")

    @app.get("/panel")
    def panel():
        if not _auth():
            return Response(
                "<h1>Brak dostępu</h1><p>Zły lub brakujący token. "
                "Użyj pełnego linku od właściciela.</p><p><a href='/'>Wróć</a></p>",
                status=401,
                mimetype="text/html",
            )
        return Response(REMOTE_PANEL_HTML, mimetype="text/html")

    @app.get("/share")
    def share_page():
        """Strona do pokazania partnerce (link + QR) — wymaga tokenu."""
        if not _auth():
            return Response("Brak dostępu — dodaj ?token=…", status=401, mimetype="text/plain")
        tok = quote(str(config.remote_token), safe="")
        # ten sam host co w adresie (LAN / tunnel)
        host = request.host_url.rstrip("/")
        link = f"{host}/r/{tok}"
        health = f"{host}/health"
        qr = (
            "https://api.qrserver.com/v1/create-qr-code/?size=240x240&data="
            + quote(link, safe="")
        )
        html = f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link dla partnerki</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0b0b10;color:#fafafa;margin:0;padding:1.25rem;text-align:center}}
.card{{max-width:420px;margin:0 auto;background:#16161f;border:1px solid #2a2a36;border-radius:16px;padding:1.25rem}}
a{{color:#f472b6;word-break:break-all}}
img{{background:#fff;border-radius:12px;padding:8px;margin:1rem 0}}
code{{display:block;background:#0f0f14;padding:.75rem;border-radius:10px;font-size:.78rem;word-break:break-all;margin:.5rem 0}}
.hint{{color:#a1a1aa;font-size:.85rem;line-height:1.45;text-align:left}}
</style></head><body><div class="card">
<h1>Panel partnerski</h1>
<p class="hint">Ta sama sieć Wi‑Fi co PC z zabawką. Nie używaj danych komórkowych.</p>
<img src="{qr}" width="240" height="240" alt="QR">
<code>{link}</code>
<p><a href="{link}">Otwórz panel</a> · <a href="{health}">Test /health</a></p>
<p class="hint">Jeśli nie ładuje: ten sam Wi‑Fi, wyłącz VPN na telefonie, na PC włącz panel w Lovense Controller → Zdalne sterowanie.</p>
</div></body></html>"""
        return Response(html, mimetype="text/html")

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
                    result = controller.set_audio_params(
                        sensitivity=float(sens) if sens is not None else None,
                        gain=float(gain) if gain is not None else None,
                        threshold=float(thr) if thr is not None else None,
                    )
                    return jsonify(
                        {
                            "ok": result.ok,
                            "message": result.message,
                            "audio_sensitivity": float(config.audio_sensitivity),
                            "audio_gain": float(config.audio_gain),
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
<title>Panel partnerki · Lovense</title>
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
</style>
</head>
<body>
<div class="app">
  <!-- LEWY PASEK: kategorie -->
  <aside class="side" aria-label="Kategorie">
    <div class="brand" title="Lovense">💜</div>
    <nav class="nav" role="tablist">
      <button type="button" class="tab on" data-tab="sila" role="tab" aria-selected="true">
        <span class="ico">⚡</span>Siła
      </button>
      <button type="button" class="tab" data-tab="wzorce" role="tab" aria-selected="false">
        <span class="ico">🌊</span>Wzorce
      </button>
      <button type="button" class="tab" data-tab="opcje" role="tab" aria-selected="false">
        <span class="ico">⚙️</span>Opcje
      </button>
    </nav>
    <div class="side-foot">
      <div id="connPill" class="pill off">off</div>
    </div>
  </aside>

  <header class="top">
    <div>
      <h1 id="panelTitle">Siła</h1>
      <p class="sub">Panel partnerski</p>
    </div>
    <div class="meter" title="Siła wibracji"><i id="meterBar"></i></div>
  </header>

  <main class="main">
    <div class="status-bar">
      <div class="toys" id="toys">Łączenie…</div>
      <label class="row" style="margin:.35rem 0 0;font-size:.78rem">Cel (zabawka)
        <select id="toySelect" style="max-width:58%;background:#0f0f14;color:#fff;border:1px solid var(--line);border-radius:8px;padding:.25rem .4rem;font-size:.75rem">
          <option value="">Wszystkie dozwolone</option>
        </select>
      </label>
      <div class="status-msg" id="status">—</div>
    </div>
    <div id="joinOverlay" style="display:none;position:fixed;inset:0;z-index:200;background:#0b0b10ee;align-items:center;justify-content:center;padding:1rem">
      <div style="background:var(--card);border:1px solid var(--line);border-radius:16px;padding:1.25rem;max-width:360px;width:100%">
        <h2 style="margin:0 0 .5rem;font-size:1.1rem">Jak masz na imię?</h2>
        <p style="color:var(--muted);font-size:.8rem;margin:0 0 .75rem">Host zobaczy Twoją nazwę i będzie mógł nadać uprawnienia do zabawek.</p>
        <input id="joinName" type="text" maxlength="40" placeholder="np. Ania" style="width:100%;padding:.7rem;border-radius:10px;border:1px solid var(--line);background:#0f0f14;color:#fff;font-size:1rem;box-sizing:border-box;margin-bottom:.6rem">
        <button type="button" class="violet" id="joinBtn" style="width:100%">Dołącz do panelu</button>
        <p id="joinErr" class="hint" style="color:#fca5a5"></p>
      </div>
    </div>

    <div class="panels">
      <!-- ===== SIŁA ===== -->
      <div class="panel on" id="panel-sila" role="tabpanel">
        <div class="subtabs" data-group="sila">
          <button type="button" class="subtab on" data-sub="quick">Poziomy</button>
          <button type="button" class="subtab" data-sub="sliders">Suwaki</button>
          <button type="button" class="subtab" data-sub="boost">Boost</button>
        </div>
        <div class="card">
          <div class="subpane on" data-subpane="quick" data-group="sila">
            <div class="subhead">Szybkie poziomy <span class="tag">0–9</span></div>
            <div class="grid" id="quickLevels"></div>
            <p class="hint">0 = stop. Jedno kliknięcie ustawia wibracje.</p>
          </div>
          <div class="subpane" data-subpane="sliders" data-group="sila">
            <div class="subhead">Precyzyjnie <span class="tag">suwaki</span></div>
            <label class="row">Wibracje <span class="value" id="vLabel">0</span></label>
            <input type="range" id="vibrate" min="0" max="20" value="0" step="1">
            <label class="row">Pump / 2. funkcja <span class="value" id="pLabel">0</span></label>
            <input type="range" id="pump" min="0" max="3" value="0" step="1">
            <p class="hint">Live i czas impulsu — w Opcjach.</p>
          </div>
          <div class="subpane" data-subpane="boost" data-group="sila">
            <div class="subhead">Boost <span class="tag">krótki zastrzyk</span></div>
            <div class="grid3">
              <button type="button" class="soft" data-boost="8">Lekki 3s</button>
              <button type="button" class="soft" data-boost="14">Mocny 3s</button>
              <button type="button" class="soft" data-boost="20">Max 2s</button>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== WZORCE ===== -->
      <div class="panel" id="panel-wzorce" role="tabpanel">
        <div class="subtabs" data-group="wzorce">
          <button type="button" class="subtab on" data-sub="classic">Klasyczne</button>
          <button type="button" class="subtab" data-sub="special">Specjalne</button>
          <button type="button" class="subtab" data-sub="long">Długie</button>
          <button type="button" class="subtab" data-sub="rhythm">Rytm</button>
          <button type="button" class="subtab" data-sub="time">Czas</button>
        </div>
        <div class="card">
          <div class="subpane on" data-subpane="classic" data-group="wzorce">
            <div class="subhead">Presety klasyczne <span class="tag">API</span></div>
            <div class="grid2">
              <button type="button" class="violet preset-btn" data-preset="pulse" data-sec="10"><b>Pulse</b><span>pulsowanie · 10s</span></button>
              <button type="button" class="violet preset-btn" data-preset="wave" data-sec="12"><b>Wave</b><span>fala · 12s</span></button>
              <button type="button" class="violet preset-btn" data-preset="fireworks" data-sec="10"><b>Fireworks</b><span>wybuchy · 10s</span></button>
              <button type="button" class="violet preset-btn" data-preset="earthquake" data-sec="12"><b>Earthquake</b><span>trzęsienie · 12s</span></button>
            </div>
          </div>
          <div class="subpane" data-subpane="special" data-group="wzorce">
            <div class="subhead">Presety specjalne <span class="tag">+ nowe</span></div>
            <div class="grid2">
              <button type="button" class="rose preset-btn" data-preset="tease" data-sec="15"><b>Tease</b><span>drażnienie · 15s</span></button>
              <button type="button" class="rose preset-btn" data-preset="climb" data-sec="12"><b>Climb</b><span>wspinaczka · 12s</span></button>
              <button type="button" class="rose preset-btn" data-preset="edge" data-sec="14"><b>Edge</b><span>na krawędzi · 14s</span></button>
              <button type="button" class="rose preset-btn" data-preset="throb" data-sec="10"><b>Throb</b><span>bicie · 10s</span></button>
              <button type="button" class="rose preset-btn" data-preset="heartbeat" data-sec="16"><b>Heartbeat</b><span>serce · 16s</span></button>
              <button type="button" class="rose preset-btn" data-preset="ripple" data-sec="14"><b>Ripple</b><span>małe fale · 14s</span></button>
              <button type="button" class="rose preset-btn" data-preset="stutter" data-sec="12"><b>Stutter</b><span>przerywane · 12s</span></button>
              <button type="button" class="rose preset-btn" data-preset="bounce" data-sec="12"><b>Bounce</b><span>odbicia · 12s</span></button>
              <button type="button" class="rose preset-btn" data-preset="cascade" data-sec="15"><b>Cascade</b><span>kaskada · 15s</span></button>
              <button type="button" class="rose preset-btn" data-preset="breath" data-sec="20"><b>Breath</b><span>oddech · 20s</span></button>
              <button type="button" class="rose preset-btn" data-preset="ocean" data-sec="25"><b>Ocean</b><span>morze · 25s</span></button>
              <button type="button" class="rose preset-btn" data-preset="spark" data-sec="10"><b>Spark</b><span>iskry · 10s</span></button>
            </div>
          </div>
          <div class="subpane" data-subpane="long" data-group="wzorce">
            <div class="subhead">Długie sekwencje <span class="tag">35–60 s</span></div>
            <div class="grid2">
              <button type="button" class="violet preset-btn" data-preset="slowburn" data-sec="45"><b>Slow burn</b><span>wolny wzrost · 45s</span></button>
              <button type="button" class="violet preset-btn" data-preset="marathon" data-sec="60"><b>Maraton</b><span>długa jazda · 60s</span></button>
              <button type="button" class="violet preset-btn" data-preset="teaselong" data-sec="40"><b>Tease long</b><span>długie drażnienie · 40s</span></button>
              <button type="button" class="violet preset-btn" data-preset="edgelong" data-sec="45"><b>Edge long</b><span>długa krawędź · 45s</span></button>
              <button type="button" class="violet preset-btn" data-preset="waveslow" data-sec="50"><b>Wave slow</b><span>wolna fala · 50s</span></button>
              <button type="button" class="violet preset-btn" data-preset="deepwave" data-sec="55"><b>Deep wave</b><span>głęboka fala · 55s</span></button>
              <button type="button" class="violet preset-btn" data-preset="crescendo" data-sec="40"><b>Crescendo</b><span>narastanie · 40s</span></button>
              <button type="button" class="violet preset-btn" data-preset="afterglow" data-sec="35"><b>Afterglow</b><span>wyciszanie · 35s</span></button>
            </div>
            <p class="hint">Czas z przycisku ma pierwszeństwo; zakładka „Czas” zmienia domyślny dla krótkich wzorców.</p>
          </div>
          <div class="subpane" data-subpane="rhythm" data-group="wzorce">
            <div class="subhead">Wzorce rytmiczne <span class="tag">pattern</span></div>
            <div class="pat">
              <button type="button" data-pattern="0;8;16;20;16;8;0" data-int="180" data-sec="12"><b>Fala</b><span>miękko góra–dół</span></button>
              <button type="button" data-pattern="20;0;20;0;20;0" data-int="200" data-sec="10"><b>Strobe</b><span>ostre impulsy</span></button>
              <button type="button" data-pattern="4;8;12;16;20;16;12;8" data-int="120" data-sec="12"><b>Budowa</b><span>rosnąco</span></button>
              <button type="button" data-pattern="20;15;10;5;10;15;20" data-int="150" data-sec="12"><b>Huśtawka</b><span>góra i dół</span></button>
              <button type="button" data-pattern="0;0;18;18;0;0;12;12" data-int="160" data-sec="12"><b>Telegraf</b><span>krótko–długo</span></button>
              <button type="button" data-pattern="10;12;14;16;18;20;18;16" data-int="100" data-sec="10"><b>Wibro</b><span>szybkie zmiany</span></button>
              <button type="button" data-pattern="0;10;0;14;0;18;0;20;0;10" data-int="200" data-sec="14"><b>Pukanie</b><span>rytm serca</span></button>
              <button type="button" data-pattern="5;10;15;20;15;10;5;10;15;10;5" data-int="220" data-sec="16"><b>Sinus</b><span>gładka fala</span></button>
              <button type="button" data-pattern="2;4;6;8;10;12;14;16;18;20;18;16;14;12;10;8;6;4;2" data-int="300" data-sec="30"><b>Długa rampa</b><span>~30 s w górę/dół</span></button>
              <button type="button" data-pattern="8;8;8;16;16;16;8;8;20;20;4;4;12;12" data-int="250" data-sec="20"><b>Bloki</b><span>płaskie odcinki</span></button>
              <button type="button" data-pattern="0;5;0;10;0;15;0;20;0;15;0;10;0;5;0" data-int="280" data-sec="25"><b>Iskry long</b><span>przerywane 25s</span></button>
              <button type="button" data-pattern="12;14;16;18;20;18;16;14;12;10;8;10;12;14;16;18;16;14;12" data-int="350" data-sec="40"><b>Maraton rytm</b><span>wolno ~40s</span></button>
            </div>
          </div>
          <div class="subpane" data-subpane="time" data-group="wzorce">
            <div class="subhead">Czas trwania <span class="tag">preset / pattern</span></div>
            <div class="grid4" id="durGrid"></div>
            <p class="hint">Domyślny czas, gdy przycisk nie ma własnego. STOP zawsze od razu.</p>
          </div>
        </div>
      </div>

      <!-- ===== OPCJE ===== -->
      <div class="panel" id="panel-opcje" role="tabpanel">
        <div class="card">
          <div class="subblock">
            <div class="subhead">Audio → zabawka <span class="tag">u hosta</span></div>
            <div class="live">
              <span id="audioLbl">Reakcja na dźwięk (wył.)</span>
              <label class="toggle"><input type="checkbox" id="audioReact"><span class="slider"></span></label>
            </div>
            <div class="grid2" style="margin-top:.5rem">
              <button type="button" class="soft" id="audioOn">Włącz audio</button>
              <button type="button" class="soft" id="audioOff">Wyłącz audio</button>
            </div>
            <label class="row" style="margin-top:.65rem">Czułość <span class="value" id="sensLabel">1.4</span></label>
            <input type="range" id="audioSens" min="0.3" max="3.0" value="1.4" step="0.1">
            <label class="row">Wzmocnienie (gain) <span class="value" id="gainLabel">10</span></label>
            <input type="range" id="audioGain" min="1" max="30" value="10" step="0.5">
            <p class="hint" id="audioHint">Dźwięk u partnera (PC) → wibracje. Czułość/gain działają od razu gdy audio WŁ.</p>
          </div>
          <div class="subblock">
            <div class="subhead">Tryb live <span class="tag">suwaki</span></div>
            <div class="live">
              <span>Suwaki od razu wysyłają</span>
              <label class="toggle"><input type="checkbox" id="live" checked><span class="slider"></span></label>
            </div>
            <p class="hint">Wyłącz → ustaw poziomy, potem „Wyślij”.</p>
          </div>
          <div class="subblock">
            <div class="subhead">Czas impulsu <span class="tag">function</span></div>
            <label class="row">Sekundy <span class="value" id="tLabel">0</span></label>
            <input type="range" id="time" min="0" max="30" value="0" step="1">
            <p class="hint">0 = bez limitu (do STOP). &gt;0 = krótki impuls.</p>
          </div>
          <div class="subblock">
            <div class="subhead">Bezpieczeństwo</div>
            <p class="hint" style="margin-top:0">STOP zawsze na dole · szanuj granice · link z tokenem jest prywatny.</p>
          </div>
        </div>
      </div>
    </div>
  </main>

  <div class="dock">
    <button type="button" class="stop" id="btnStop">STOP</button>
    <button type="button" class="send" id="btnApply">Wyślij</button>
  </div>
</div>
<div class="toast" id="toast"></div>

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
const sensLabel = $('sensLabel');
const gainLabel = $('gainLabel');
let audioAllowed = true;
let audioParamsAllowed = true;
let audioSyncing = false;
let audioParamTimer = null;

const TITLES = { sila: 'Siła', wzorce: 'Wzorce', opcje: 'Opcje' };
const SS_KEY = 'lc_session_' + (TOKEN || '').slice(0, 12);
const NAME_KEY = 'lc_name';

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
  panelTitle.textContent = TITLES[id] || id;
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
    toast('Czas: ' + d + 's');
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
      showJoin(data.message || (err === 'banned' ? 'IP zablokowane przez hosta' : 'Wyrzucono — dołącz ponownie'));
    }
    if(err === 'no_session'){
      SESSION_ID = '';
      localStorage.removeItem(SS_KEY);
      showJoin('Sesja wygasła — dołącz ponownie');
    }
    const e = new Error(data.message || err);
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
    toast('Połączono jako ' + DISPLAY_NAME);
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
    showJoin('Najpierw dołącz');
    return;
  }
  const act = (body.action || '').toLowerCase();
  const isAudio = act === 'audio' || act === 'audio_toggle' || act === 'audio_on' || act === 'audio_off' || act === 'audio_react';
  if(!canControl && act !== 'stop' && !isAudio){
    statusEl.textContent = 'Host wyłączył Ci sterowanie';
    statusEl.className = 'status-msg msg-err';
    toast('Brak uprawnień');
    return;
  }
  // audio: host może wyłączyć „can_control” ale audio nadal przez allow_audio
  if(isAudio && !canControl && !audioAllowed){
    toast('Brak uprawnień do audio');
    return;
  }
  try{
    const toy = selectedToy();
    if(toy) body = Object.assign({}, body, { toy });
    const data = await api('/api/control', {method:'POST', body: JSON.stringify(body)});
    lastOk = !!data.ok;
    statusEl.textContent = data.message || 'OK';
    statusEl.className = 'status-msg ' + (lastOk ? 'msg-ok' : 'msg-err');
    if(body.action === 'stop') toast('STOP');
    return data;
  }catch(e){
    lastOk = false;
    statusEl.textContent = 'Błąd: ' + e.message;
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

$('btnApply').onclick = () => { buzz(8); sendNow(); toast('Wysłano'); };
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
    toast('Preset: ' + btn.dataset.preset + ' · ' + sec + 's');
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
    toast('Wzorzec · ' + sec + 's');
  };
});
document.querySelectorAll('[data-boost]').forEach(btn => {
  btn.onclick = () => {
    buzz(15);
    const v = +btn.dataset.boost;
    const sec = v >= 20 ? 2 : 3;
    setLevels(v, Math.min(+pump.max, v >= 15 ? 2 : 1), false);
    sendControl({ action:'function', vibrate:v, pump:+pump.value, time_sec: sec });
    toast('Boost ' + sec + 's');
  };
});

function fillToySelect(toys){
  if(!toySelect) return;
  const prev = toySelect.value;
  const opts = ['<option value="">Wszystkie dozwolone</option>'];
  (toys||[]).filter(t => t.connected).forEach(t => {
    const id = t.id;
    const lab = (t.display_name||t.name||id).replace(/</g,'');
    opts.push(`<option value="${id}">${lab}</option>`);
  });
  toySelect.innerHTML = opts.join('');
  if(prev && [...toySelect.options].some(o => o.value === prev)) toySelect.value = prev;
}

function setAudioUi(enabled, mode, allowed, paramsAllowed, sens, gain){
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
      ? ('Reakcja na dźwięk (WŁ) · ' + (mode || 'playback'))
      : 'Reakcja na dźwięk (wył.)';
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
  if(audioSens) audioSens.disabled = !audioParamsAllowed;
  if(audioGain) audioGain.disabled = !audioParamsAllowed;
  if(audioHint){
    if(!audioAllowed) audioHint.textContent = 'Host zablokował zdalne sterowanie audio.';
    else if(!audioParamsAllowed) audioHint.textContent = 'Audio ON/OFF OK · host zablokował czułość/gain.';
    else audioHint.textContent = 'Włącz audio i ustaw czułość/gain — działa od razu u partnera (PC).';
  }
  const onB = $('audioOn'), offB = $('audioOff');
  if(onB) onB.disabled = !audioAllowed;
  if(offB) offB.disabled = !audioAllowed;
}

async function setAudioRemote(enabled){
  if(!audioAllowed){ toast('Audio zablokowane przez hosta'); return; }
  try{
    const data = await sendControl({ action: 'audio', enabled: !!enabled });
    if(data){
      setAudioUi(!!data.audio_enabled, null, audioAllowed, audioParamsAllowed,
        audioSens ? +audioSens.value : null, audioGain ? +audioGain.value : null);
      toast(data.audio_enabled ? 'Audio WŁĄCZONE' : 'Audio WYŁĄCZONE');
    }
  }catch(e){
    toast('Audio: ' + (e.message || e));
  }
}

function scheduleAudioParams(){
  if(audioSyncing || !audioParamsAllowed) return;
  if(sensLabel && audioSens) sensLabel.textContent = (+audioSens.value).toFixed(1);
  if(gainLabel && audioGain) gainLabel.textContent = (+audioGain.value).toFixed(1);
  clearTimeout(audioParamTimer);
  audioParamTimer = setTimeout(async () => {
    try{
      const data = await sendControl({
        action: 'audio_params',
        sensitivity: audioSens ? +audioSens.value : undefined,
        gain: audioGain ? +audioGain.value : undefined
      });
      if(data && data.message) statusEl.textContent = data.message;
    }catch(e){
      toast('Czułość: ' + (e.message || e));
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
      s.audio_gain
    );
    const n = s.connected_count || (s.toys||[]).length || 0;
    connPill.textContent = s.connected ? ('on·' + (n || 1)) : 'off';
    connPill.className = 'pill ' + (s.connected ? 'on' : 'off');
    if(s.session && s.session.display_name){
      connPill.title = s.session.display_name + (canControl ? '' : ' (bez sterowania)');
    } else {
      connPill.title = s.connected ? ('online · ' + n) : 'host bez zabawki';
    }

    const list = (s.toys||[]).map(t => {
      const on = t.connected;
      const bat = t.battery != null ? t.battery + '%' : '—';
      return `<div class="toy"><span class="dot ${on?'':'off'}"></span><span>${t.display_name||t.name||t.id}</span><span class="bat">🔋 ${bat}</span></div>`;
    }).join('') || '<div class="toy"><span class="dot off"></span><span>Brak zabawek (lub brak uprawnień)</span></div>';
    toysEl.innerHTML = list;
    fillToySelect(s.toys||[]);

    if(!canControl){
      statusEl.textContent = 'Host wyłączył Ci sterowanie — możesz tylko oglądać';
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
    toysEl.innerHTML = '<div class="toy"><span class="dot off"></span><span>Brak łącza z hostem</span></div>';
    statusEl.textContent = 'Offline: ta sama Wi‑Fi / tunnel? Panel włączony? Test: /health';
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
