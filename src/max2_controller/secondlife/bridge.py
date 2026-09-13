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


class SlObjectBridge:
    def __init__(self, controller: "Max2Controller") -> None:
        self.controller = controller
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.url = ""
        self.ok = False
        self.last_error = ""

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

    def _req(self, method: str, body: dict | None = None) -> dict:
        tok = quote(self._token(), safe="")
        url = f"{self.url}/?token={tok}"
        data = None
        headers = {
            "Accept": "application/json",
            "X-API-Token": self._token(),
            "User-Agent": "LovenseController/1.9 (sl-bridge)",
        }
        if body is not None:
            payload = dict(body)
            payload["token"] = self._token()
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

    def _loop(self) -> None:
        self.controller.log("SL: łączę z obiektem (bez tunelu)…")
        while not self._stop.wait(0.45):
            try:
                data = self._req("GET")
                self.ok = True
                self.last_error = ""
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
            except urllib.error.HTTPError as e:
                self.ok = False
                self.last_error = f"HTTP {e.code}"
                if e.code == 404:
                    self.controller.log("SL: URL wygasł — załóż obiekt ponownie i wklej nowy PAIR URL")
                    return
            except Exception as e:
                self.ok = False
                self.last_error = str(e)
        self.ok = False
