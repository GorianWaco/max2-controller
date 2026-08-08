"""Globalne skróty klawiszowe (pynput) — sterowanie z klawiatury, w pełni konfigurowalne."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

from max2_controller.hotkey_defs import HOTKEY_ACTIONS

if TYPE_CHECKING:
    from max2_controller.config import AppConfig
    from max2_controller.controller import Max2Controller

logger = logging.getLogger(__name__)


class HotkeyManager:
    """
    Dwa zestawy (oba z configu):
    - chord: Ctrl+Shift+… (GlobalHotKeys)
    - game mode: proste klawisze (Listener) gdy hotkeys_game_mode
    """

    def __init__(self, controller: "Max2Controller", config: "AppConfig") -> None:
        self.controller = controller
        self.config = config
        self._listener = None
        self._press_listener = None
        self._lock = threading.Lock()
        self._boost_prev: tuple[int, int] | None = None

    def start(self) -> bool:
        if not self.config.hotkeys_enabled:
            return False
        try:
            from pynput import keyboard
        except ImportError:
            logger.warning("pynput niedostępny — hotkeys wyłączone")
            return False

        mapping: dict[str, Callable[[], None]] = {}
        for action in HOTKEY_ACTIONS:
            chord = self.config.chord_for(action.id)
            if not chord:
                continue
            fn = self._action_fn(action.id)
            if fn is None:
                continue
            # uniknij duplikatów chord — ostatni wygrywa, log ostrzeżenie
            if chord in mapping:
                logger.warning("Duplikat chord %s dla %s — nadpisany", chord, action.id)
            mapping[chord] = fn

        try:
            if mapping:
                self._listener = keyboard.GlobalHotKeys(mapping)
                self._listener.start()
                logger.info("Hotkeys (chord): %s", list(mapping.keys()))
        except Exception:
            logger.exception("GlobalHotKeys failed")
            self._listener = None

        if self.config.hotkeys_game_mode:
            try:
                self._press_listener = keyboard.Listener(
                    on_press=self._on_press,
                    on_release=self._on_release,
                )
                self._press_listener.start()
                logger.info(
                    "Hotkeys GAME MODE: %s",
                    {a.id: self.config.game_key_for(a.id) for a in HOTKEY_ACTIONS if self.config.game_key_for(a.id)},
                )
            except Exception:
                logger.exception("game mode listener failed")

        return self._listener is not None or self._press_listener is not None

    def stop(self) -> None:
        for lst in (self._listener, self._press_listener):
            if lst is not None:
                try:
                    lst.stop()
                except Exception:
                    pass
        self._listener = None
        self._press_listener = None
        self._boost_prev = None

    def restart(self) -> bool:
        self.stop()
        return self.start()

    # --- dispatch ---
    def _action_fn(self, action_id: str) -> Callable[[], None] | None:
        table: dict[str, Callable[[], None]] = {
            "stop": self._stop,
            "stop_alt": self._stop,
            "vibrate_up": lambda: self._vib(+self.config.control_step_vibrate),
            "vibrate_down": lambda: self._vib(-self.config.control_step_vibrate),
            "vibrate_up_fast": lambda: self._vib(+self.config.control_step_vibrate_fast),
            "vibrate_down_fast": lambda: self._vib(-self.config.control_step_vibrate_fast),
            "pump_up": lambda: self._pump(+self.config.control_step_pump),
            "pump_down": lambda: self._pump(-self.config.control_step_pump),
            "pump_up_alt": lambda: self._pump(+self.config.control_step_pump),
            "pump_down_alt": lambda: self._pump(-self.config.control_step_pump),
            "audio_toggle": self._toggle_audio_flag,
            "boost": self._boost_pulse,
            "mode_oscillate": lambda: self.controller.toggle_mode("oscillate"),
            "mode_random": lambda: self.controller.toggle_mode("random"),
            "mode_ramp_up": lambda: self.controller.start_ramp(up=True),
            "mode_ramp_down": lambda: self.controller.start_ramp(up=False),
            "mode_stop": self.controller.stop_auto_modes,
        }
        if action_id.startswith("level_"):
            try:
                n = int(action_id.split("_", 1)[1])
            except ValueError:
                return None
            return lambda idx=n: self._level_index(idx)
        if action_id.startswith("preset_"):
            name = action_id[len("preset_") :]
            return lambda n=name: self._preset(n)
        return table.get(action_id)

    def _stop(self) -> None:
        self.controller.stop_auto_modes()
        self.controller.stop()

    def _vib(self, delta: int) -> None:
        self.controller.vibrate_delta(delta)

    def _pump(self, delta: int) -> None:
        self.controller.pump_delta(delta)

    def _preset(self, name: str) -> None:
        self.controller.preset(name, time_sec=8)

    def _level_index(self, index: int) -> None:
        vibrate = self.config.level_value(index)
        pump = 0
        if self.config.control_auto_pump_with_level and vibrate > 0:
            if vibrate >= 15:
                pump = min(3, self.config.control_max_pump)
            elif vibrate >= 10:
                pump = min(2, self.config.control_max_pump)
            elif vibrate >= 5:
                pump = min(1, self.config.control_max_pump)
        self.controller.set_levels(vibrate=vibrate, pump=pump, time_sec=0, immediate=True)

    def _boost_pulse(self) -> None:
        """Natychmiastowy boost do control_boost_level (toggle off = przywróć)."""
        with self._lock:
            if self._boost_prev is not None:
                v, p = self._boost_prev
                self._boost_prev = None
                self.controller.set_levels(vibrate=v, pump=p, immediate=True)
                return
            st = self.controller.state
            self._boost_prev = (st.vibrate, st.pump)
            boost = self.config.clamp_vibrate(self.config.control_boost_level)
            self.controller.set_levels(vibrate=boost, immediate=True)

    def _toggle_audio_flag(self) -> None:
        fn = getattr(self.controller, "toggle_audio_react", None)
        if callable(fn):
            fn()
        else:
            self.controller.log("Audio react: przełącz w oknie GTK")

    def _normalize_game_key(self, key) -> str | None:  # noqa: ANN001
        try:
            from pynput.keyboard import Key, KeyCode
        except ImportError:
            return None

        special = {
            Key.space: "space",
            Key.up: "up",
            Key.down: "down",
            Key.left: "left",
            Key.right: "right",
            Key.esc: "esc",
            Key.enter: "enter",
            Key.tab: "tab",
            Key.backspace: "backspace",
        }
        if key in special:
            return special[key]
        if isinstance(key, KeyCode):
            if key.char:
                ch = key.char
                # pynput bywa z shift: '=' vs '+'
                if ch in ("+", "="):
                    # rozróżnij: mapujemy oba na to co w configu
                    return ch
                if ch in ("-", "_"):
                    return ch
                return ch.lower()
            # numpad / vk
            if key.vk is not None:
                # często cyfry na numpadzie
                pass
        return None

    def _game_key_matches(self, pressed: str, configured: str) -> bool:
        if not configured or not pressed:
            return False
        c = configured.lower()
        p = pressed.lower()
        if p == c:
            return True
        # aliasy
        aliases = {
            "+": {"+", "="},
            "=": {"+", "="},
            "-": {"-", "_"},
            "_": {"-", "_"},
            "space": {"space"},
            "esc": {"esc", "escape"},
            "escape": {"esc", "escape"},
            "enter": {"enter", "return"},
            "return": {"enter", "return"},
        }
        if c in aliases and p in aliases[c]:
            return True
        return False

    def _on_press(self, key) -> None:  # noqa: ANN001
        pressed = self._normalize_game_key(key)
        if pressed is None:
            return

        # preferencja: dłuższe/konkretne akcje — idziemy po liście
        for action in HOTKEY_ACTIONS:
            gkey = self.config.game_key_for(action.id)
            if not gkey:
                continue
            if self._game_key_matches(pressed, gkey):
                fn = self._action_fn(action.id)
                if fn:
                    try:
                        fn()
                    except Exception:
                        logger.exception("game hotkey %s", action.id)
                return  # jeden skrót na naciśnięcie

    def _on_release(self, key) -> None:  # noqa: ANN001
        pass


# --- konwersja GTK / EventKey → format pynput (do edytora w GUI) ---

_MOD_ORDER = ("ctrl", "alt", "shift", "super")


def gtk_key_to_chord(keyval: int, state: int) -> str | None:
    """
    Zdarzenie GTK (keyval + Gdk.Modifier) → string pynput chord.
    Zwraca None jeśli sam modyfikator.
    """
    try:
        from gi.repository import Gdk
    except Exception:
        return None

    name = Gdk.keyval_name(keyval)
    if not name:
        return None
    name_l = name.lower()
    if name_l in (
        "control_l",
        "control_r",
        "shift_l",
        "shift_r",
        "alt_l",
        "alt_r",
        "meta_l",
        "meta_r",
        "super_l",
        "super_r",
        "iso_level3_shift",
        "caps_lock",
        "num_lock",
    ):
        return None

    mods: list[str] = []
    # Gdk.Modifier_type flags
    if state & Gdk.ModifierType.CONTROL_MASK:
        mods.append("ctrl")
    if state & Gdk.ModifierType.ALT_MASK:
        mods.append("alt")
    if state & Gdk.ModifierType.SHIFT_MASK:
        # shift+cyfra bywa jako nazwa symbolu — zostaw shift jeśli nie litera ASCII
        mods.append("shift")
    if state & Gdk.ModifierType.SUPER_MASK:
        mods.append("super")

    key_part = _gdk_name_to_pynput_key(name_l)
    if not key_part:
        return None

    # same litery ze shiftem → zwykle nie trzymamy shift w chord (Ctrl+Shift+S osobno)
    parts = [f"<{m}>" for m in _MOD_ORDER if m in mods]
    if key_part.startswith("<"):
        parts.append(key_part)
    else:
        parts.append(key_part)
    return "+".join(parts)


def gtk_key_to_game(keyval: int, state: int) -> str | None:
    """Pojedynczy klawisz trybu gry (bez wymaganych modyfikatorów; ignorujemy same mody)."""
    try:
        from gi.repository import Gdk
    except Exception:
        return None
    name = Gdk.keyval_name(keyval)
    if not name:
        return None
    name_l = name.lower()
    if name_l in (
        "control_l",
        "control_r",
        "shift_l",
        "shift_r",
        "alt_l",
        "alt_r",
        "meta_l",
        "meta_r",
        "super_l",
        "super_r",
        "iso_level3_shift",
        "caps_lock",
        "num_lock",
    ):
        return None
    return _gdk_name_to_game_key(name_l)


def _gdk_name_to_pynput_key(name_l: str) -> str | None:
    special = {
        "up": "<up>",
        "down": "<down>",
        "left": "<left>",
        "right": "<right>",
        "space": "<space>",
        "return": "<enter>",
        "kp_enter": "<enter>",
        "escape": "<esc>",
        "tab": "<tab>",
        "backspace": "<backspace>",
        "plus": "equal",  # często + bez shift to equal
        "equal": "equal",
        "minus": "minus",
        "underscore": "minus",
        "bracketleft": "[",
        "bracketright": "]",
    }
    if name_l in special:
        return special[name_l]
    # kp_0 .. kp_9
    if name_l.startswith("kp_") and len(name_l) == 4 and name_l[3].isdigit():
        return name_l[3]
    if len(name_l) == 1:
        return name_l.lower()
    # F1..F12
    if name_l.startswith("f") and name_l[1:].isdigit():
        return f"<{name_l}>"
    return name_l


def _gdk_name_to_game_key(name_l: str) -> str | None:
    special = {
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
        "space": "space",
        "return": "enter",
        "kp_enter": "enter",
        "escape": "esc",
        "tab": "tab",
        "backspace": "backspace",
        "plus": "+",
        "equal": "=",
        "minus": "-",
        "underscore": "_",
        "bracketleft": "[",
        "bracketright": "]",
    }
    if name_l in special:
        return special[name_l]
    if name_l.startswith("kp_") and len(name_l) == 4 and name_l[3].isdigit():
        return name_l[3]
    if len(name_l) == 1:
        return name_l.lower()
    return name_l
