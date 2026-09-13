"""Warstwa aplikacji: stan, debounce, callbacki dla GUI / API / hotkeys."""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from max2_controller.charge_bank import ChargeBank, apply_action
from max2_controller.backends.ble_lovense import TOY_ALL, LovenseBleBackend
from max2_controller.backends.lovense_local import LovenseLocalBackend
from max2_controller.config import AppConfig
from max2_controller.models import (
    PRESET_ALIASES,
    PRESET_DEFAULT_SEC,
    PRESETS,
    CommandResult,
    ToyInfo,
)
from max2_controller.remote_sessions import RemoteSessionManager

logger = logging.getLogger(__name__)

LogCallback = Callable[[str], None]
StateCallback = Callable[[], None]

BACKEND_BLE = "ble"
BACKEND_LOCAL = "lovense_local"

AutoMode = Literal["none", "oscillate", "random", "ramp"]


@dataclass
class ControllerState:
    toys: list[ToyInfo] = field(default_factory=list)
    selected_toy_id: str | None = None
    # True = suwaki/hotkeys idą do WSZYSTKICH połączonych zabawek
    control_all: bool = True
    vibrate: int = 0
    pump: int = 0
    time_sec: float = 0.0
    last_message: str = ""
    last_ok: bool = True
    connected: bool = False
    connected_count: int = 0
    backend_name: str = BACKEND_BLE
    remote_active: bool = False
    game_api_active: bool = False
    remote_session_count: int = 0
    auto_mode: AutoMode = "none"


class Max2Controller:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.load()
        self.state = ControllerState(backend_name=self.config.backend)
        self._lock = threading.RLock()
        self._log_cbs: list[LogCallback] = []
        self._state_cbs: list[StateCallback] = []
        self._debounce_timer: threading.Timer | None = None
        self._action_end_timer: threading.Timer | None = None
        self._battery_stop = threading.Event()
        self._battery_thread: threading.Thread | None = None
        self._ble: LovenseBleBackend | None = None
        self._local: LovenseLocalBackend | None = None
        self.backend: Any = self._make_backend(self.config.backend)
        self.audio_reactor = None  # ustawiane z app.py (AudioReactor)
        self._audio_toggle_cbs: list[Callable[[], None]] = []
        # tryby automatyczne (oscylacja / random / ramp)
        self._auto_stop = threading.Event()
        self._auto_thread: threading.Thread | None = None
        # sesje panelu partnerskiego (kto online, kick, uprawnienia do zabawek)
        self.remote_sessions = RemoteSessionManager()
        self.charge_bank = ChargeBank()
        self.charge_bank.load()

    def _make_backend(self, name: str) -> Any:
        name = (name or BACKEND_BLE).strip().lower()
        if name in ("ble", "bluetooth", "direct"):
            if self._ble is None:
                self._ble = LovenseBleBackend()
            self.state.backend_name = BACKEND_BLE
            return self._ble
        if self._local is None:
            self._local = LovenseLocalBackend(
                url=self.config.lovense_url,
                app_name=self.config.app_name,
                verify_ssl=self.config.lovense_verify_ssl,
            )
        else:
            self._local.url = self.config.lovense_url
            if not self._local.url.endswith("/command"):
                # LovenseLocalBackend normalizes in __init__ only — recreate
                self._local = LovenseLocalBackend(
                    url=self.config.lovense_url,
                    app_name=self.config.app_name,
                    verify_ssl=self.config.lovense_verify_ssl,
                )
        self.state.backend_name = BACKEND_LOCAL
        return self._local

    def set_backend(self, name: str) -> CommandResult:
        with self._lock:
            try:
                self.backend = self._make_backend(name)
                self.config.backend = self.state.backend_name
                self.config.save()
                self.state.toys = []
                self.state.selected_toy_id = None
                self.state.connected = False
                msg = (
                    "Backend: Bluetooth BLE (bez telefonu)"
                    if self.state.backend_name == BACKEND_BLE
                    else "Backend: Lovense Connect/Remote (HTTP)"
                )
                return self._apply_result(CommandResult(ok=True, message=msg))
            except Exception as e:
                return self._apply_result(CommandResult(ok=False, message=str(e)))

    # --- events ---
    def on_log(self, cb: LogCallback) -> None:
        self._log_cbs.append(cb)

    def on_state(self, cb: StateCallback) -> None:
        self._state_cbs.append(cb)

    def on_audio_toggle(self, cb: Callable[[], None]) -> None:
        self._audio_toggle_cbs.append(cb)

    def toggle_audio_react(self) -> None:
        """Wywołane z hotkey — GUI podpina realny start/stop (fallback: bezpośredni)."""
        if self._audio_toggle_cbs:
            for cb in list(self._audio_toggle_cbs):
                try:
                    cb()
                except Exception:
                    logger.exception("audio toggle cb")
            return
        # bez GUI (np. --web)
        ar = self.audio_reactor
        if ar is None:
            return
        self.set_audio_react(not bool(ar.running or ar.enabled))

    def audio_react_enabled(self) -> bool:
        ar = self.audio_reactor
        return bool(ar and (ar.running or ar.enabled))

    def set_audio_react(self, enabled: bool) -> CommandResult:
        """Włącz/wyłącz reakcję na dźwięk (host, remote, API)."""
        ar = self.audio_reactor
        if ar is None:
            return self._apply_result(
                CommandResult(ok=False, message="Audio react niedostępny (brak silnika audio)")
            )
        want = bool(enabled)
        if want:
            if ar.running:
                return self._apply_result(CommandResult(ok=True, message="Audio react już włączony"))
            ok, msg = ar.start()
            self._notify()
            return self._apply_result(CommandResult(ok=ok, message=msg))
        # wyłącz
        was = ar.running or ar.enabled
        ar.stop(send_zero=True)
        self._notify()
        if was:
            return self._apply_result(CommandResult(ok=True, message="Audio react WYŁĄCZONY"))
        return self._apply_result(CommandResult(ok=True, message="Audio react już wyłączony"))

    def set_audio_params(
        self,
        sensitivity: float | None = None,
        gain: float | None = None,
        threshold: float | None = None,
        bands: bool | None = None,
        bass_gain: float | None = None,
        treble_gain: float | None = None,
        bass_hz: float | None = None,
        treble_hz: float | None = None,
        bass_to_vibrate: bool | None = None,
        bass_to_pump: bool | None = None,
        treble_to_vibrate: bool | None = None,
        treble_to_pump: bool | None = None,
    ) -> CommandResult:
        """Czułość / wzmocnienie / pasma audio (działa od razu — pętla czyta config na żywo)."""
        parts: list[str] = []
        if sensitivity is not None:
            self.config.audio_sensitivity = max(0.3, min(3.0, float(sensitivity)))
            parts.append(f"czułość={self.config.audio_sensitivity:.2f}")
        if gain is not None:
            self.config.audio_gain = max(1.0, min(30.0, float(gain)))
            parts.append(f"gain={self.config.audio_gain:.1f}")
        if threshold is not None:
            self.config.audio_threshold = max(0.001, min(0.2, float(threshold)))
            parts.append(f"próg={self.config.audio_threshold:.3f}")
        if bands is not None:
            self.config.audio_bands_enabled = bool(bands)
            parts.append("bas/treble=" + ("WŁ" if self.config.audio_bands_enabled else "WYŁ"))
        if bass_gain is not None:
            self.config.audio_bass_gain = max(0.2, min(4.0, float(bass_gain)))
            parts.append(f"bas×{self.config.audio_bass_gain:.1f}")
        if treble_gain is not None:
            self.config.audio_treble_gain = max(0.2, min(6.0, float(treble_gain)))
            parts.append(f"treble×{self.config.audio_treble_gain:.1f}")
        if bass_hz is not None:
            self.config.audio_bass_hz = max(40.0, min(600.0, float(bass_hz)))
            parts.append(f"bas<{self.config.audio_bass_hz:.0f}Hz")
        if treble_hz is not None:
            self.config.audio_treble_hz = max(800.0, min(12000.0, float(treble_hz)))
            parts.append(f"treble>{self.config.audio_treble_hz:.0f}Hz")
        if bass_to_vibrate is not None:
            self.config.audio_bass_to_vibrate = bool(bass_to_vibrate)
            parts.append("bas→V=" + ("WŁ" if self.config.audio_bass_to_vibrate else "WYŁ"))
        if bass_to_pump is not None:
            self.config.audio_bass_to_pump = bool(bass_to_pump)
            parts.append("bas→P=" + ("WŁ" if self.config.audio_bass_to_pump else "WYŁ"))
        if treble_to_vibrate is not None:
            self.config.audio_treble_to_vibrate = bool(treble_to_vibrate)
            parts.append("treble→V=" + ("WŁ" if self.config.audio_treble_to_vibrate else "WYŁ"))
        if treble_to_pump is not None:
            self.config.audio_treble_to_pump = bool(treble_to_pump)
            parts.append("treble→P=" + ("WŁ" if self.config.audio_treble_to_pump else "WYŁ"))
        if self.config.audio_treble_hz < self.config.audio_bass_hz + 200.0:
            self.config.audio_treble_hz = self.config.audio_bass_hz + 400.0
        if not parts:
            return self._apply_result(CommandResult(ok=False, message="Brak parametrów audio"))
        try:
            self.config.save()
        except Exception:
            pass
        self._notify()
        return self._apply_result(CommandResult(ok=True, message="Audio: " + ", ".join(parts)))

    def log(self, msg: str) -> None:
        logger.info(msg)
        self.state.last_message = msg
        for cb in list(self._log_cbs):
            try:
                cb(msg)
            except Exception:
                logger.exception("log callback")

    def _notify(self) -> None:
        for cb in list(self._state_cbs):
            try:
                cb()
            except Exception:
                logger.exception("state callback")

    def _apply_result(self, result: CommandResult, ok_msg: str | None = None) -> CommandResult:
        self.state.last_ok = result.ok
        if result.ok:
            self.log(ok_msg or result.message or "OK")
        else:
            self.log(f"Błąd: {result.message}")
        self._notify()
        return result

    # --- BLE helpers ---
    def ble_scan(self, timeout: float = 6.0) -> list[ToyInfo]:
        """Skan BLE — NIE trzyma locka podczas I/O (żeby GUI nie wisiało)."""
        if self.state.backend_name != BACKEND_BLE:
            self.set_backend(BACKEND_BLE)
        assert isinstance(self.backend, LovenseBleBackend)
        # I/O poza lockiem
        toys, result = self.backend.scan(timeout=timeout)
        with self._lock:
            self.state.toys = toys
            self.state.connected = self.backend.is_connected()
            self.state.connected_count = self.backend.connected_count()
            if toys and not self.state.selected_toy_id:
                free = [t for t in toys if not t.app_connected]
                self.state.selected_toy_id = (free[0] if free else toys[0]).id
        self._apply_result(result)
        return toys

    def ble_connect(self, address: str | None = None) -> CommandResult:
        """Dodaje zabawkę (nie rozłącza już połączonych)."""
        if self.state.backend_name != BACKEND_BLE:
            self.set_backend(BACKEND_BLE)
        assert isinstance(self.backend, LovenseBleBackend)
        addr = address or self.state.selected_toy_id
        if not addr or addr == TOY_ALL:
            return self._apply_result(
                CommandResult(ok=False, message="Wybierz zabawkę z listy skanu i kliknij Połącz")
            )
        name = ""
        for t in list(self.state.toys):
            if t.id.upper() == addr.upper():
                name = t.name
                break
        # I/O poza lockiem — krytyczne przy 2. urządzeniu + GTK
        result = self.backend.connect(addr, name=name)
        with self._lock:
            toys, _ = self.backend.get_toys()
            self.state.toys = toys
            if result.ok:
                self.state.selected_toy_id = addr
                self.state.connected = True
                self.state.connected_count = self.backend.connected_count()
                n = self.state.connected_count
                if n >= 2:
                    result = CommandResult(
                        ok=True,
                        message=(
                            f"{result.message} — masz {n} urządzeń. "
                            "Lista „Połączone teraz” pokazuje obie."
                        ),
                        raw=result.raw,
                    )
            else:
                self.state.connected = self.backend.is_connected()
                self.state.connected_count = self.backend.connected_count()
        return self._apply_result(result)

    def ble_disconnect(self, address: str | None = None) -> CommandResult:
        """Rozłącz jedną albo wszystkie."""
        if not isinstance(self.backend, LovenseBleBackend):
            return self._apply_result(CommandResult(ok=False, message="Nie jesteś w trybie BLE"))
        if address is None:
            if self.state.control_all:
                address = TOY_ALL
            else:
                address = self.state.selected_toy_id
        result = self.backend.disconnect(address)
        with self._lock:
            self.state.connected = self.backend.is_connected()
            self.state.connected_count = self.backend.connected_count()
            toys, _ = self.backend.get_toys()
            self.state.toys = toys
        return self._apply_result(result)

    def set_control_all(self, enabled: bool) -> None:
        with self._lock:
            self.state.control_all = bool(enabled)
            self.log("Sterowanie: " + ("WSZYSTKIE połączone" if self.state.control_all else "tylko wybrana"))
            self._notify()

    def _target_toy_id(self, toy: str | None = None) -> str | None:
        """Które zabawki dostać komendę."""
        if toy is not None:
            return toy
        if self.state.backend_name == BACKEND_BLE and self.state.control_all:
            return TOY_ALL
        return self.state.selected_toy_id

    # --- toys ---
    def refresh_toys(self) -> list[ToyInfo]:
        if self.state.backend_name == BACKEND_BLE and isinstance(self.backend, LovenseBleBackend):
            # zawsze szybki skan + merge z połączonymi (nie blokuj GUI lockiem)
            return self.ble_scan(timeout=5.0)
        toys, result = self.backend.get_toys()
        with self._lock:
            self.state.toys = toys
            self.state.connected = result.ok and any(t.connected for t in toys) if toys else result.ok
            self.state.connected_count = sum(1 for t in toys if t.connected)
            if result.ok:
                if not self.state.selected_toy_id and toys:
                    self.state.selected_toy_id = toys[0].id
                elif self.state.selected_toy_id and not any(
                    t.id.upper() == self.state.selected_toy_id.upper() for t in toys
                ):
                    connected = [t for t in toys if t.connected]
                    self.state.selected_toy_id = (
                        (connected[0].id if connected else toys[0].id) if toys else None
                    )
        if result.ok:
            self._apply_result(
                result,
                f"{len(toys)} widocznych, {self.state.connected_count} połączonych",
            )
        else:
            self._apply_result(result)
        return toys

    def select_toy(self, toy_id: str | None) -> None:
        with self._lock:
            self.state.selected_toy_id = toy_id
            self._notify()

    def selected_toy(self) -> ToyInfo | None:
        tid = self.state.selected_toy_id
        if not tid:
            return None
        for t in self.state.toys:
            if t.id == tid:
                return t
        return None

    # --- control ---
    def set_levels(
        self,
        vibrate: int | None = None,
        pump: int | None = None,
        time_sec: float | None = None,
        immediate: bool = False,
        toy: str | None = None,
        *,
        from_auto: bool = False,
    ) -> CommandResult | None:
        with self._lock:
            if vibrate is not None:
                self.state.vibrate = self.config.clamp_vibrate(vibrate)
            if pump is not None:
                # max 20 — Gemini/Nora; clamp_pump używa control_max_pump
                hard = 20
                toy_info = self.selected_toy()
                if toy_info and toy_info.secondary == "pump":
                    hard = 3
                self.state.pump = self.config.clamp_pump(pump, hard_max=hard)
            if time_sec is not None:
                self.state.time_sec = max(0.0, float(time_sec))

            if immediate:
                result = self._send_levels(toy=toy)
                self._arm_action_end(self.state.time_sec)
                return result

            if self._debounce_timer:
                self._debounce_timer.cancel()
            delay = max(0.02, self.config.slider_debounce_ms / 1000.0)
            self._debounce_timer = threading.Timer(delay, self._flush_debounce)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()
            self._notify()
            return None

    def _cancel_action_end(self) -> None:
        t = self._action_end_timer
        self._action_end_timer = None
        if t is not None:
            t.cancel()

    def _arm_action_end(self, time_sec: float) -> None:
        self._cancel_action_end()
        dur = float(time_sec or 0.0)
        if dur <= 0:
            return
        timer = threading.Timer(dur + 0.08, self._on_action_end)
        timer.daemon = True
        self._action_end_timer = timer
        timer.start()

    def _on_action_end(self) -> None:
        self._action_end_timer = None
        self.stop()

    def _flush_debounce(self) -> None:
        with self._lock:
            self._send_levels()
            self._arm_action_end(self.state.time_sec)

    def _send_levels(self, toy: str | None = None) -> CommandResult:
        toy_id = self._target_toy_id(toy)
        v, p, t = self.state.vibrate, self.state.pump, self.state.time_sec
        if v == 0 and p == 0:
            result = self.backend.stop(toy=toy_id)
            return self._apply_result(result, "STOP")
        result = self.backend.set_both(v, p, time_sec=t, toy=toy_id)
        target = "ALL" if toy_id == TOY_ALL else (toy_id or "?")[:12]
        return self._apply_result(result, f"[{target}] Vibrate:{v} Pump:{p} time={t}s")

    def apply_now(self) -> CommandResult:
        with self._lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
            result = self._send_levels()
            self._arm_action_end(self.state.time_sec)
            return result

    def replay_charge(self) -> CommandResult:
        msg = self.charge_bank.start_replay(
            lambda pend: apply_action(self, pend),
            lambda: bool(self.state.connected),
        )
        ok = not msg.startswith("podłącz") and "pusta" not in msg and "już" not in msg
        self.log("Energia: " + msg)
        return self._apply_result(CommandResult(ok=ok, message=msg))

    def clear_charge(self) -> CommandResult:
        self.charge_bank.clear()
        self.log("Energia: kolejka wyczyszczona")
        self._notify()
        return self._apply_result(CommandResult(ok=True, message="Kolejka energii wyczyszczona"))

    def bank_sl_action(self, pend: dict) -> int:
        n = self.charge_bank.enqueue(pend)
        e = self.charge_bank.energy
        self.log(f"Energia: zapisano wibrację ({n} w kolejce, {e}%)")
        self._notify()
        return n

    def stop(self, toy: str | None = None) -> CommandResult:
        self.charge_bank.stop_replay()
        with self._lock:
            if self._debounce_timer:
                self._debounce_timer.cancel()
            self._cancel_action_end()
            self.state.vibrate = 0
            self.state.pump = 0
            self.state.time_sec = 0.0
            toy_id = self._target_toy_id(toy)
            result = self.backend.stop(toy=toy_id)
            return self._apply_result(result, "STOP")

    def preset(self, name: str, time_sec: float | None = None, toy: str | None = None) -> CommandResult:
        name = name.lower().strip()
        name = PRESET_ALIASES.get(name, name)
        if name not in PRESETS:
            return self._apply_result(CommandResult(ok=False, message=f"Nieznany preset: {name}"))
        self.stop_auto_modes()
        with self._lock:
            t = self.state.time_sec if time_sec is None else float(time_sec)
            if t <= 0:
                t = float(PRESET_DEFAULT_SEC.get(name, 10.0))
            toy_id = self._target_toy_id(toy)
            result = self.backend.preset(name, time_sec=t, toy=toy_id)
            self._arm_action_end(t)
            return self._apply_result(result, f"Preset: {name} ({t:.0f}s)")

    # --- tryby automatyczne ---
    def stop_auto_modes(self) -> None:
        self._auto_stop.set()
        th = self._auto_thread
        if th and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=1.5)
        self._auto_thread = None
        with self._lock:
            if self.state.auto_mode != "none":
                self.state.auto_mode = "none"
                self.log("Tryb auto: wyłączony")
                self._notify()

    def toggle_mode(self, mode: AutoMode) -> None:
        if mode in ("none",):
            self.stop_auto_modes()
            return
        with self._lock:
            current = self.state.auto_mode
        if current == mode:
            self.stop_auto_modes()
            return
        if mode == "oscillate":
            self.start_oscillate()
        elif mode == "random":
            self.start_random()
        elif mode == "ramp":
            self.start_ramp(up=True)

    def start_oscillate(self) -> None:
        self.stop_auto_modes()
        self._auto_stop.clear()
        lo = self.config.clamp_vibrate(self.config.control_oscillate_min)
        hi = self.config.clamp_vibrate(self.config.control_oscillate_max)
        if hi < lo:
            lo, hi = hi, lo
        interval = max(0.08, self.config.control_oscillate_interval_ms / 1000.0)

        def loop() -> None:
            direction = 1
            level = lo
            with self._lock:
                self.state.auto_mode = "oscillate"
            self.log(f"Tryb: oscylacja {lo}↔{hi}")
            self._notify()
            while not self._auto_stop.is_set():
                self.set_levels(vibrate=level, immediate=True, from_auto=True)
                level += direction
                if level >= hi:
                    level = hi
                    direction = -1
                elif level <= lo:
                    level = lo
                    direction = 1
                if self._auto_stop.wait(interval):
                    break
            with self._lock:
                if self.state.auto_mode == "oscillate":
                    self.state.auto_mode = "none"
            self._notify()

        self._auto_thread = threading.Thread(target=loop, daemon=True, name="auto-oscillate")
        self._auto_thread.start()

    def start_random(self) -> None:
        self.stop_auto_modes()
        self._auto_stop.clear()
        lo = self.config.clamp_vibrate(self.config.control_random_min)
        hi = self.config.clamp_vibrate(self.config.control_random_max)
        if hi < lo:
            lo, hi = hi, lo
        interval = max(0.1, self.config.control_random_interval_ms / 1000.0)

        def loop() -> None:
            with self._lock:
                self.state.auto_mode = "random"
            self.log(f"Tryb: losowy {lo}–{hi}")
            self._notify()
            while not self._auto_stop.is_set():
                level = random.randint(lo, hi) if hi > lo else lo
                self.set_levels(vibrate=level, immediate=True, from_auto=True)
                if self._auto_stop.wait(interval):
                    break
            with self._lock:
                if self.state.auto_mode == "random":
                    self.state.auto_mode = "none"
            self._notify()

        self._auto_thread = threading.Thread(target=loop, daemon=True, name="auto-random")
        self._auto_thread.start()

    def start_ramp(self, up: bool = True) -> None:
        self.stop_auto_modes()
        self._auto_stop.clear()
        seconds = max(1.0, float(self.config.control_ramp_seconds))
        cap = self.config.clamp_vibrate(self.config.control_max_vibrate)
        start = 0 if up else cap
        end = cap if up else 0
        steps = max(1, int(seconds * 4))  # ~4 Hz
        step_sleep = seconds / steps

        def loop() -> None:
            with self._lock:
                self.state.auto_mode = "ramp"
            self.log(f"Tryb: ramp {'↑' if up else '↓'} ({seconds:.0f}s → {end})")
            self._notify()
            for i in range(steps + 1):
                if self._auto_stop.is_set():
                    break
                t = i / steps
                level = int(round(start + (end - start) * t))
                self.set_levels(vibrate=level, immediate=True, from_auto=True)
                if i < steps and self._auto_stop.wait(step_sleep):
                    break
            with self._lock:
                if self.state.auto_mode == "ramp":
                    self.state.auto_mode = "none"
            self.log("Ramp zakończony")
            self._notify()

        self._auto_thread = threading.Thread(target=loop, daemon=True, name="auto-ramp")
        self._auto_thread.start()

    def set_quick_percent(self, percent: int) -> None:
        """Ustaw siłę jako % miękkiego limitu (0, 25, 50, 75, 100)."""
        percent = max(0, min(100, int(percent)))
        cap = self.config.clamp_vibrate(self.config.control_max_vibrate)
        v = int(round(cap * percent / 100.0))
        pump = 0
        if self.config.control_auto_pump_with_level and v > 0:
            if percent >= 75:
                pump = min(3, self.config.control_max_pump)
            elif percent >= 50:
                pump = min(2, self.config.control_max_pump)
            elif percent >= 25:
                pump = min(1, self.config.control_max_pump)
        self.set_levels(vibrate=v, pump=pump, immediate=True)

    def pattern(
        self,
        strength: str,
        time_sec: float | None = None,
        interval_ms: int = 200,
        features: str = "v,p",
        toy: str | None = None,
    ) -> CommandResult:
        with self._lock:
            t = self.state.time_sec if time_sec is None else float(time_sec)
            if t <= 0:
                t = 10.0
            toy_id = self._target_toy_id(toy)
            parts = [p.strip() for p in strength.replace(",", ";").split(";") if p.strip()]
            if not parts:
                return self._apply_result(CommandResult(ok=False, message="Pusty wzorzec"))
            if len(parts) > 50:
                parts = parts[:50]
            cleaned: list[str] = []
            for p in parts:
                try:
                    val = max(0, min(20, int(float(p))))
                    cleaned.append(str(val))
                except ValueError:
                    return self._apply_result(CommandResult(ok=False, message=f"Zła wartość w pattern: {p}"))
            strength_str = ";".join(cleaned)
            result = self.backend.pattern(
                strength=strength_str,
                time_sec=t,
                toy=toy_id,
                interval_ms=interval_ms,
                features=features,
            )
            self._arm_action_end(t)
            return self._apply_result(result, f"Pattern [{interval_ms}ms]: {strength_str} ({t}s)")

    def refresh_battery(self) -> int | None:
        with self._lock:
            toy_id = self.state.selected_toy_id if not self.state.control_all else self.state.selected_toy_id
            level, result = self.backend.get_battery(toy_id)
            if level is not None:
                for t in self.state.toys:
                    if t.id == toy_id or (self.state.backend_name == BACKEND_BLE and t.status == "1"):
                        t.battery = level
                self.log(f"Bateria: {level}%")
                self._notify()
            elif not result.ok and self.state.backend_name == BACKEND_LOCAL:
                toys, _ = self.backend.get_toys()
                for t in toys:
                    if t.id == toy_id and t.battery is not None:
                        for local in self.state.toys:
                            if local.id == toy_id:
                                local.battery = t.battery
                        self._notify()
                        return t.battery
            return level

    def start_battery_poll(self) -> None:
        if self._battery_thread and self._battery_thread.is_alive():
            return
        self._battery_stop.clear()

        def loop() -> None:
            while not self._battery_stop.wait(self.config.battery_poll_sec):
                try:
                    if self.state.connected:
                        self.refresh_battery()
                except Exception:
                    logger.exception("battery poll")

        self._battery_thread = threading.Thread(target=loop, daemon=True, name="battery-poll")
        self._battery_thread.start()

    def stop_battery_poll(self) -> None:
        self._battery_stop.set()

    def vibrate_delta(self, delta: int) -> None:
        with self._lock:
            self.set_levels(vibrate=self.state.vibrate + int(delta), immediate=True)

    def pump_delta(self, delta: int) -> None:
        with self._lock:
            self.set_levels(pump=self.state.pump + int(delta), immediate=True)

    def update_lovense_url(self, url: str) -> None:
        self.config.lovense_url = url.strip()
        self.config.save()
        if self.state.backend_name == BACKEND_LOCAL:
            self.backend = self._make_backend(BACKEND_LOCAL)
        self.log(f"URL Lovense: {self.config.lovense_url}")
        if self.state.backend_name == BACKEND_LOCAL:
            self.refresh_toys()

    def shutdown(self) -> None:
        self.stop_auto_modes()
        self.stop_battery_poll()
        try:
            self.stop()
        except Exception:
            pass
        if self._ble:
            try:
                self._ble.close()
            except Exception:
                pass

    def connected_toy_ids(self) -> list[str]:
        with self._lock:
            return [t.id for t in self.state.toys if t.connected]

    def set_levels_multi(
        self,
        toy_ids: list[str],
        vibrate: int | None = None,
        pump: int | None = None,
        time_sec: float | None = None,
    ) -> CommandResult:
        """Ustaw poziomy na liście zabawek (remote z uprawnieniami)."""
        if not toy_ids:
            # pusta lista przy allow-all bez znanych id → klasyczne ALL
            return self.set_levels(
                vibrate=vibrate, pump=pump, time_sec=time_sec, immediate=True, toy=None
            ) or CommandResult(ok=True, message="OK")
        if len(toy_ids) == 1:
            return self.set_levels(
                vibrate=vibrate, pump=pump, time_sec=time_sec, immediate=True, toy=toy_ids[0]
            ) or CommandResult(ok=True, message="OK")
        last = CommandResult(ok=True, message="OK")
        for tid in toy_ids:
            last = self.set_levels(
                vibrate=vibrate, pump=pump, time_sec=time_sec, immediate=True, toy=tid
            ) or last
        return last

    def stop_multi(self, toy_ids: list[str] | None = None) -> CommandResult:
        if not toy_ids:
            return self.stop()
        if len(toy_ids) == 1:
            return self.stop(toy=toy_ids[0])
        last = CommandResult(ok=True, message="STOP")
        for tid in toy_ids:
            last = self.stop(toy=tid)
        return last

    def preset_multi(
        self, name: str, toy_ids: list[str] | None = None, time_sec: float | None = None
    ) -> CommandResult:
        if not toy_ids:
            return self.preset(name, time_sec=time_sec)
        if len(toy_ids) == 1:
            return self.preset(name, time_sec=time_sec, toy=toy_ids[0])
        last = CommandResult(ok=True, message=f"Preset: {name}")
        for tid in toy_ids:
            last = self.preset(name, time_sec=time_sec, toy=tid)
        return last

    def snapshot(self) -> dict:
        with self._lock:
            rs = self.remote_sessions.snapshot()
            self.state.remote_session_count = int(rs.get("online_count") or 0)
            return {
                "connected": self.state.connected,
                "connected_count": self.state.connected_count,
                "control_all": self.state.control_all,
                "backend": self.state.backend_name,
                "vibrate": self.state.vibrate,
                "pump": self.state.pump,
                "time_sec": self.state.time_sec,
                "selected_toy_id": self.state.selected_toy_id,
                "last_message": self.state.last_message,
                "last_ok": self.state.last_ok,
                "remote_active": self.state.remote_active,
                "game_api_active": self.state.game_api_active,
                "auto_mode": self.state.auto_mode,
                "control_max_vibrate": self.config.control_max_vibrate,
                "audio_enabled": self.audio_react_enabled(),
                "audio_mode": getattr(self.config, "audio_mode", "playback"),
                "audio_sensitivity": float(getattr(self.config, "audio_sensitivity", 1.4)),
                "audio_gain": float(getattr(self.config, "audio_gain", 10.0)),
                "audio_threshold": float(getattr(self.config, "audio_threshold", 0.015)),
                "audio_bands_enabled": bool(getattr(self.config, "audio_bands_enabled", True)),
                "audio_bass_gain": float(getattr(self.config, "audio_bass_gain", 1.0)),
                "audio_treble_gain": float(getattr(self.config, "audio_treble_gain", 1.8)),
                "audio_bass_hz": float(getattr(self.config, "audio_bass_hz", 250.0)),
                "audio_treble_hz": float(getattr(self.config, "audio_treble_hz", 2000.0)),
                "audio_bass_to_vibrate": bool(getattr(self.config, "audio_bass_to_vibrate", True)),
                "audio_bass_to_pump": bool(getattr(self.config, "audio_bass_to_pump", False)),
                "audio_treble_to_vibrate": bool(
                    getattr(self.config, "audio_treble_to_vibrate", False)
                ),
                "audio_treble_to_pump": bool(getattr(self.config, "audio_treble_to_pump", True)),
                "remote_sessions": rs,
                "energy": self.charge_bank.energy,
                "bank": self.charge_bank.count,
                "energy_playing": self.charge_bank.playing,
                "toys": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "nick_name": t.nick_name,
                        "display_name": t.display_name,
                        "status": t.status,
                        "connected": t.connected,
                        "battery": t.battery,
                        "functions": t.full_functions,
                    }
                    for t in self.state.toys
                ],
            }
