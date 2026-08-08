"""Klient lokalnego API Lovense (Connect / Remote Game Mode)."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
import urllib3

from max2_controller.models import CommandResult, ToyInfo

logger = logging.getLogger(__name__)

# Self-signed cert na *.lovense.club
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LovenseLocalBackend:
    """Sterowanie przez lokalne HTTP(S) API aplikacji Lovense."""

    def __init__(
        self,
        url: str = "http://127.0.0.1:20010/command",
        app_name: str = "Max2Controller",
        verify_ssl: bool = False,
        timeout: float = 5.0,
    ) -> None:
        self.url = url.rstrip("/")
        if not self.url.endswith("/command"):
            # pozwól podać bazę host:port
            if self.url.endswith("/"):
                self.url = self.url + "command"
            else:
                self.url = self.url + "/command"
        self.app_name = app_name
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Content-Type": "application/json",
                "X-platform": app_name,
            }
        )

    def _post(self, body: dict[str, Any]) -> CommandResult:
        try:
            resp = self._session.post(
                self.url,
                json=body,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            try:
                data = resp.json()
            except Exception:
                data = None
            if resp.status_code >= 400 and data is None:
                return CommandResult(
                    ok=False,
                    code=resp.status_code,
                    message=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    raw=resp.text,
                )
            result = CommandResult.from_response(data, resp.status_code)
            if not result.ok:
                logger.warning("Lovense command failed: %s body=%s", result, body)
            return result
        except requests.exceptions.ConnectionError as e:
            return CommandResult(
                ok=False,
                message=(
                    "Brak połączenia z Lovense Connect/Remote. "
                    "Uruchom aplikację i podłącz zabawkę. "
                    f"URL: {self.url} ({e})"
                ),
            )
        except requests.exceptions.Timeout:
            return CommandResult(ok=False, message=f"Timeout ({self.timeout}s) → {self.url}")
        except Exception as e:
            logger.exception("Lovense request error")
            return CommandResult(ok=False, message=str(e))

    def get_toys(self) -> tuple[list[ToyInfo], CommandResult]:
        result = self._post({"command": "GetToys"})
        toys: list[ToyInfo] = []
        if not result.ok or not isinstance(result.raw, dict):
            return toys, result

        data = result.raw.get("data") or {}
        raw_toys = data.get("toys", {})
        if isinstance(raw_toys, str):
            try:
                raw_toys = json.loads(raw_toys)
            except json.JSONDecodeError:
                raw_toys = {}
        if isinstance(raw_toys, dict):
            for toy_id, info in raw_toys.items():
                if isinstance(info, dict):
                    toys.append(ToyInfo.from_lovense_dict(str(toy_id), info))
        return toys, result

    def function(
        self,
        action: str,
        time_sec: float = 0,
        toy: str | list[str] | None = None,
        stop_previous: int = 1,
        loop_running_sec: float | None = None,
        loop_pause_sec: float | None = None,
    ) -> CommandResult:
        body: dict[str, Any] = {
            "command": "Function",
            "action": action,
            "timeSec": float(time_sec),
            "apiVer": 1,
            "stopPrevious": int(stop_previous),
        }
        if toy:
            body["toy"] = toy
        if loop_running_sec is not None:
            body["loopRunningSec"] = float(loop_running_sec)
        if loop_pause_sec is not None:
            body["loopPauseSec"] = float(loop_pause_sec)
        return self._post(body)

    def set_vibrate(
        self,
        level: int,
        time_sec: float = 0,
        toy: str | None = None,
        stop_previous: int = 1,
    ) -> CommandResult:
        level = max(0, min(20, int(level)))
        return self.function(f"Vibrate:{level}", time_sec=time_sec, toy=toy, stop_previous=stop_previous)

    def set_pump(
        self,
        level: int,
        time_sec: float = 0,
        toy: str | None = None,
        stop_previous: int = 1,
    ) -> CommandResult:
        level = max(0, min(3, int(level)))
        return self.function(f"Pump:{level}", time_sec=time_sec, toy=toy, stop_previous=stop_previous)

    def set_both(
        self,
        vibrate: int,
        pump: int,
        time_sec: float = 0,
        toy: str | None = None,
        stop_previous: int = 1,
    ) -> CommandResult:
        v = max(0, min(20, int(vibrate)))
        p = max(0, min(3, int(pump)))
        return self.function(
            f"Vibrate:{v},Pump:{p}",
            time_sec=time_sec,
            toy=toy,
            stop_previous=stop_previous,
        )

    def stop(self, toy: str | None = None) -> CommandResult:
        return self.function("Stop", time_sec=0, toy=toy, stop_previous=1)

    def preset(
        self,
        name: str,
        time_sec: float = 0,
        toy: str | None = None,
    ) -> CommandResult:
        name = name.lower().strip()
        from max2_controller.models import PRESET_ALIASES, PRESET_PATTERNS

        name = PRESET_ALIASES.get(name, name)
        # Oficjalne API Lovense: tylko 4 presety; resztę emulujemy patternem
        official = ("pulse", "wave", "fireworks", "earthquake")
        if name not in official:
            if name not in PRESET_PATTERNS:
                return CommandResult(ok=False, message=f"Nieznany preset: {name}")
            seq, interval = PRESET_PATTERNS[name]
            strength = ";".join(str(x) for x in seq)
            return self.pattern(
                strength=strength,
                time_sec=time_sec or 10,
                toy=toy,
                interval_ms=interval,
            )
        body: dict[str, Any] = {
            "command": "Preset",
            "name": name,
            "timeSec": float(time_sec),
            "apiVer": 1,
        }
        if toy:
            body["toy"] = toy
        return self._post(body)

    def pattern(
        self,
        strength: str,
        time_sec: float = 0,
        toy: str | None = None,
        interval_ms: int = 200,
        features: str = "v,p",
    ) -> CommandResult:
        """
        Własny wzorzec.
        strength: np. "20;5;15;0;20" (0-20, max 50 kroków)
        features: v=vibrate, p=pump (siła p mapuje się z v w API)
        """
        rule = f"V:1;F:{features};S:{max(100, int(interval_ms))}#"
        body: dict[str, Any] = {
            "command": "Pattern",
            "rule": rule,
            "strength": strength,
            "timeSec": float(time_sec),
            "apiVer": 2,
        }
        if toy:
            body["toy"] = toy
        return self._post(body)

    def get_battery(self, toy: str | None = None) -> tuple[int | None, CommandResult]:
        body: dict[str, Any] = {"command": "GetBattery", "apiVer": 1}
        if toy:
            body["toy"] = toy
        result = self._post(body)
        if not result.ok or not isinstance(result.raw, dict):
            return None, result
        data = result.raw.get("data")
        # Różne formaty odpowiedzi w zależności od wersji aplikacji
        if isinstance(data, (int, float)):
            return int(data), result
        if isinstance(data, str) and data.isdigit():
            return int(data), result
        if isinstance(data, dict):
            if toy and toy in data:
                try:
                    return int(data[toy]), result
                except (TypeError, ValueError):
                    pass
            for key in ("battery", "value", "level"):
                if key in data:
                    try:
                        return int(data[key]), result
                    except (TypeError, ValueError):
                        pass
            # {toyId: battery}
            for val in data.values():
                try:
                    return int(val), result
                except (TypeError, ValueError):
                    continue
        return None, result

    def ping(self) -> CommandResult:
        toys, result = self.get_toys()
        if result.ok:
            result.message = f"OK — {len(toys)} zabawka(ek)"
        return result
