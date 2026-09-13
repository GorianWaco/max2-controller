"""Kolejka wibracji, gdy zabawka nie jest podłączona — odtwarzanie po kolei."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from max2_controller.config import CONFIG_DIR

logger = logging.getLogger(__name__)

BANK_PATH = CONFIG_DIR / "charge_bank.json"
MAX_ITEMS = 24
MAX_ENERGY = 100


def item_duration(pend: dict[str, Any]) -> float:
    try:
        t = float(pend.get("time") or 4)
    except (TypeError, ValueError):
        t = 4.0
    return max(0.4, min(t, 120.0))


def item_energy(pend: dict[str, Any]) -> int:
    action = str(pend.get("action") or "").lower()
    t = min(item_duration(pend), 30.0)
    if action == "vibrate":
        try:
            level = int(pend.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        return max(1, int(round((max(0, min(20, level)) / 20.0) * t * 1.4)))
    if action == "intensity":
        try:
            x = float(pend.get("i") or 0)
        except (TypeError, ValueError):
            x = 0.0
        x = max(0.0, min(1.0, x))
        return max(1, int(round(x * t * 1.4)))
    return max(1, int(min(t, 16.0)))


def apply_action(controller: Any, pend: dict[str, Any]) -> None:
    """Wykonaj akcję SL na zabawce (bez bankowania)."""
    action = str(pend.get("action") or "").lower()
    if action == "stop":
        controller.stop()
        controller.stop_auto_modes()
        return
    if action == "vibrate":
        level = int(pend.get("level") or 0)
        t = float(pend.get("time") or 0)
        controller.set_levels(vibrate=level, time_sec=t, immediate=True)
        return
    if action == "intensity":
        x = max(0.0, min(1.0, float(pend.get("i") or 0)))
        t = float(pend.get("time") or 0)
        vmax = float(controller.config.remote_max_vibrate)
        pmax = float(controller.config.remote_max_pump)
        controller.set_levels(
            vibrate=int(round(x * vmax)),
            pump=int(round(x * pmax)),
            time_sec=t,
            immediate=True,
        )
        return
    if action == "preset":
        controller.preset(str(pend.get("name") or "pulse"), time_sec=float(pend.get("time") or 8))
        return
    if action == "pattern":
        controller.pattern(
            str(pend.get("strength") or "10;0"),
            time_sec=float(pend.get("time") or 8),
            interval_ms=int(pend.get("interval") or 200),
        )


class ChargeBank:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or BANK_PATH
        self._items: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.playing = False

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def energy(self) -> int:
        with self._lock:
            return min(MAX_ENERGY, sum(item_energy(p) for p in self._items))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            n = len(self._items)
            e = min(MAX_ENERGY, sum(item_energy(p) for p in self._items))
            return {"bank": n, "energy": e, "playing": self.playing}

    def enqueue(self, pend: dict[str, Any]) -> int:
        action = str(pend.get("action") or "").lower()
        if not action or action in ("stop", "replay", "clearbank", "bank"):
            return self.count
        item = dict(pend)
        item["action"] = action
        with self._lock:
            self._items.append(item)
            overflow = len(self._items) - MAX_ITEMS
            if overflow > 0:
                del self._items[0:overflow]
            n = len(self._items)
        self.save()
        return n

    def ingest_packed(self, packed: str) -> int:
        """Rekordy z LSL: i|0.5|4^v|10|6^p|pulse|8^r|10;0|200|8"""
        n = 0
        for rec in (packed or "").split("^"):
            rec = rec.strip()
            if not rec:
                continue
            parts = rec.split("|")
            k = parts[0] if parts else ""
            pend: dict[str, Any] | None = None
            if k == "v" and len(parts) >= 3:
                pend = {"action": "vibrate", "level": int(float(parts[1])), "time": float(parts[2])}
            elif k == "i" and len(parts) >= 3:
                pend = {"action": "intensity", "i": float(parts[1]), "time": float(parts[2])}
            elif k == "p" and len(parts) >= 3:
                pend = {"action": "preset", "name": parts[1], "time": float(parts[2])}
            elif k == "r" and len(parts) >= 4:
                pend = {
                    "action": "pattern",
                    "strength": parts[1],
                    "interval": int(float(parts[2])),
                    "time": float(parts[3]),
                }
            if pend:
                self.enqueue(pend)
                n += 1
        return n

    def clear(self) -> None:
        self.stop_replay()
        with self._lock:
            self._items.clear()
        self.save()

    def pop_first(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._items:
                return None
            item = self._items.pop(0)
        self.save()
        return item

    def start_replay(self, apply_item: Callable[[dict[str, Any]], None], connected: Callable[[], bool]) -> str:
        if self.playing:
            return "już odtwarzam kolejkę"
        if not connected():
            return "podłącz zabawkę, żeby odtworzyć energię"
        n = self.count
        if n < 1:
            return "kolejka pusta — nie ma zapisanych wibracji"
        self._stop.clear()
        self.playing = True

        def _run() -> None:
            try:
                while not self._stop.is_set():
                    if not connected():
                        logger.info("charge bank: toy gone, pause replay")
                        break
                    item = self.pop_first()
                    if item is None:
                        break
                    try:
                        apply_item(item)
                    except Exception:
                        logger.exception("charge bank item failed")
                    self._stop.wait(item_duration(item) + 0.25)
            finally:
                self.playing = False
                self.save()

        self._thread = threading.Thread(target=_run, name="charge-bank-replay", daemon=True)
        self._thread.start()
        return f"odtwarzam {n} zapisanych wibracji"

    def stop_replay(self) -> None:
        self._stop.set()
        self.playing = False

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {"items": list(self._items)}
            self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("charge bank save failed")

    def load(self) -> None:
        try:
            if not self.path.is_file():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                return
            clean: list[dict[str, Any]] = []
            for it in items:
                if isinstance(it, dict) and it.get("action"):
                    clean.append(dict(it))
            with self._lock:
                self._items = clean[:MAX_ITEMS]
        except Exception:
            logger.exception("charge bank load failed")
