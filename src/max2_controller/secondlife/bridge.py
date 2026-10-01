"""PC → obiekt SL (HTTP-in). Bez tunelu: aplikacja odpytuje URL z grida."""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING
from urllib.parse import quote

from max2_controller.charge_bank import apply_action

if TYPE_CHECKING:
    from max2_controller.controller import Max2Controller

logger = logging.getLogger(__name__)


def normalize_sl_url(raw: str) -> str:
    u = (raw or "").strip().strip("<>").rstrip("/")
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    # Czat SL często psuje :port na spację: "….secondlife.io 12043/cap/…"
    u = re.sub(
        r"(secondlife\.io|lindenlab\.com)\s+(\d+/)",
        r"\1:\2",
        u,
        flags=re.IGNORECASE,
    )
    u = re.sub(r"(secondlife\.io|lindenlab\.com):\s+(\d+)", r"\1:\2", u, flags=re.IGNORECASE)
    return u.rstrip("/")


class CapGone(Exception):
    """The capability URL itself is dead (region change, script reset)."""


def sl_object_request_url(base: str, token: str) -> str:
    """Path + query. Kept for callers; the bridge tries several shapes."""
    targets = sl_request_targets(base, token, post=False)
    for url in targets:
        if "/t/" in url and "token=" in url:
            return url
    return targets[0] if targets else ""


def sl_request_targets(base: str, token: str, *, post: bool) -> list[str]:
    """
    Cloud sims drop query strings, custom headers, or extra path — not always
    the same one. Try each shape. POST prefers the cap root because the token
    rides in the JSON body (that part is not stripped).
    A query string must sit behind a slash or SL returns HTTP 500.
    """
    base = normalize_sl_url(base)
    if not base:
        return []
    tok = quote(token or "", safe="")
    root = base + "/"
    if not tok:
        return [root]
    path = f"{base}/t/{tok}"
    query = f"{base}/?token={tok}"
    both = f"{path}?token={tok}"
    ordered = [root, path, both, query] if post else [path, query, both, root]
    out: list[str] = []
    for url in ordered:
        if url not in out:
            out.append(url)
    return out


def _is_cap_root(base: str, url: str) -> bool:
    root = normalize_sl_url(base).rstrip("/")
    path = url.split("?", 1)[0].rstrip("/")
    return bool(root) and path == root


class SlObjectBridge:
    def __init__(self, controller: "Max2Controller") -> None:
        self.controller = controller
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.url = ""
        self.ok = False
        self.last_error = ""
        self._auth_fail = 0
        self._preferred_url = ""
        self._poll_via_post = False
        self._old_script = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, url: str) -> bool:
        url = normalize_sl_url(url)
        if not url.lower().startswith("http"):
            self.last_error = "wklej URL z obiektu SL"
            return False
        self.stop()
        self.url = url
        self.ok = False
        self.last_error = ""
        self._auth_fail = 0
        self._preferred_url = ""
        self._poll_via_post = False
        self._old_script = False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sl-object-bridge", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        self._thread = None
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)

    def _token(self) -> str:
        return str(getattr(self.controller.config, "remote_token", "") or "")

    def _targets(self, method: str) -> list[str]:
        post = method.upper() == "POST"
        targets = sl_request_targets(self.url, self._token(), post=post)
        pref = self._preferred_url
        if pref and pref in targets:
            targets = [pref] + [u for u in targets if u != pref]
        elif pref:
            targets = [pref] + targets
        return targets

    def _http(self, method: str, url: str, body: dict | None) -> dict:
        tok = self._token()
        data = None
        headers = {
            "Accept": "application/json",
            "X-API-Token": tok,
            "User-Agent": "LovenseController/1.9 (sl-bridge)",
        }
        # GET must not have a body: SL HTTP-in may then treat it as POST and skip pending.
        if body is not None:
            payload = dict(body)
            payload["token"] = tok
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            out = json.loads(raw)
        except Exception:
            out = {"ok": False, "raw": raw[:200]}
        if not isinstance(out, dict):
            return {"ok": False, "error": "bad json"}
        return out

    def _req(self, method: str, body: dict | None = None) -> dict:
        """Try each URL shape. 404 on the cap root means the object URL died."""
        last: urllib.error.HTTPError | None = None
        saw_auth = False
        for url in self._targets(method):
            try:
                data = self._http(method, url, body)
            except urllib.error.HTTPError as e:
                if e.code == 404 and _is_cap_root(self.url, url):
                    raise CapGone(url) from e
                if e.code == 404:
                    if self._preferred_url == url:
                        self._preferred_url = ""
                    continue
                if e.code == 401:
                    saw_auth = True
                    last = e
                    continue
                if e.code in (405, 500, 502, 503):
                    last = e
                    continue
                raise
            self._preferred_url = url
            return data
        if saw_auth and last is not None:
            raise last
        if last is not None:
            raise last
        raise urllib.error.URLError("SL: obiekt nie odpowiedział")

    def _apply_pending(self, pend: dict) -> None:
        action = str(pend.get("action") or "").lower()
        if not action:
            return
        ctl = self.controller
        if action == "stop":
            ctl.stop()
            ctl.stop_auto_modes()
            ctl.log("SL: STOP")
            return
        if action == "replay":
            ctl.replay_charge()
            return
        if action == "clearbank":
            ctl.clear_charge()
            return
        if action == "bank":
            n = ctl.charge_bank.ingest_packed(str(pend.get("q") or ""))
            ctl.log(f"SL: przyjęto {n} zapisanych wibracji (energia {ctl.charge_bank.energy}%)")
            ctl._notify()
            return
        snap = ctl.snapshot()
        toys = snap.get("toys") or []
        n = int(snap.get("connected_count") or 0)
        any_toy = any(isinstance(t, dict) and t.get("connected") for t in toys)
        connected = bool(snap.get("connected") or n > 0 or any_toy)
        if not connected:
            ctl.bank_sl_action(pend)
            return
        apply_action(ctl, pend)
        if action == "vibrate":
            ctl.log(f"SL: vibrate {pend.get('level')} ({pend.get('time')}s)")
        elif action == "intensity":
            ctl.log(f"SL: intensity {pend.get('i')} ({pend.get('time')}s)")
        elif action == "preset":
            ctl.log(f"SL: preset {pend.get('name')} ({pend.get('time')}s)")
        elif action == "pattern":
            ctl.log(f"SL: pattern ({pend.get('time')}s)")

    def _push_state(self) -> None:
        snap = self.controller.snapshot()
        toys = snap.get("toys") or []
        n = int(snap.get("connected_count") or 0)
        any_toy = any(isinstance(t, dict) and t.get("connected") for t in toys)
        connected = bool(snap.get("connected") or n > 0 or any_toy)
        self._req(
            "POST",
            {
                "connected": 1 if connected else 0,
                "connected_count": n if n else (1 if connected else 0),
                "vibrate": int(snap.get("vibrate") or 0),
                "pump": int(snap.get("pump") or 0),
                "max_vibrate": int(self.controller.config.remote_max_vibrate),
                "message": str(snap.get("last_message") or ""),
                "energy": int(snap.get("energy") or 0),
                "bank": int(snap.get("bank") or 0),
            },
        )

    def _poll(self) -> dict:
        """
        GET carries the token in the path or ?token=.
        If every GET is 401, POST {"op":"poll"} — the body survives when the
        sim strips the query string and custom headers.
        """
        if self._poll_via_post:
            data = self._req("POST", {"op": "poll"})
            if "pending" not in data:
                self._poll_via_post = False
                raise RuntimeError(
                    "SL: kula ma stary skrypt (nie oddaje komend). "
                    "Zdalne → Kopiuj skrypt SL, wklej do kuli, klik URL, Połącz."
                )
            return data
        try:
            return self._req("GET", None)
        except urllib.error.HTTPError as e:
            if e.code != 401 or self._old_script:
                raise
            data = self._req("POST", {"op": "poll"})
            if "pending" not in data:
                self._old_script = True
                raise RuntimeError(
                    "SL: kula ma stary skrypt (nie oddaje komend). "
                    "Zdalne → Kopiuj skrypt SL, wklej do kuli, klik URL, Połącz."
                )
            self._poll_via_post = True
            self.controller.log("SL: token idzie w treści POST (sim ucina query/nagłówki)")
            return data

    def _loop(self) -> None:
        self.controller.log("SL: łączę z obiektem (bez tunelu)…")
        while not self._stop.wait(0.45):
            try:
                data = self._poll()
                self.ok = True
                self.last_error = ""
                self._auth_fail = 0
                pend = data.get("pending")
                if isinstance(pend, dict) and pend.get("action"):
                    try:
                        self._apply_pending(pend)
                    except Exception:
                        logger.exception("SL pending failed")
                try:
                    self._push_state()
                except Exception:
                    logger.exception("SL push state failed")
            except CapGone:
                self.ok = False
                self.last_error = (
                    "URL wygasł — klik kuli → URL, wklej nowy PAIR URL i Połącz"
                )
                self.controller.log("SL: " + self.last_error)
                return
            except urllib.error.HTTPError as e:
                self.ok = False
                self.last_error = f"HTTP {e.code}"
                if e.code == 401:
                    self._auth_fail += 1
                    if self._auth_fail in (1, 6, 20):
                        self.controller.log(
                            "SL: HTTP 401 (stary token w kuli). "
                            "Klik kuli → URL, wklej PAIR URL, Połącz. "
                            "Albo Zdalne → Kopiuj skrypt SL i wklej do kuli raz."
                        )
            except Exception as e:
                self.ok = False
                self.last_error = str(e)
        self.ok = False
