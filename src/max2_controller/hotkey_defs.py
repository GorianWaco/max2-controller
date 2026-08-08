"""Rejestr akcji skrótów klawiszowych — etykiety, domyślne chord i tryb gry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HotkeyAction:
    """Jedna akcja sterowania przypisywalna do skrótu."""

    id: str
    label: str
    group: str  # "basic" | "level" | "preset" | "mode"
    default_chord: str  # format pynput GlobalHotKeys, np. <ctrl>+<shift>+s
    default_game: str  # pojedynczy klawisz trybu gry: "s", "space", "up", "1", "+"


# Kolejność = kolejność w GUI
HOTKEY_ACTIONS: tuple[HotkeyAction, ...] = (
    HotkeyAction("stop", "STOP (panic)", "basic", "<ctrl>+<shift>+s", "space"),
    HotkeyAction("stop_alt", "STOP (alternatywny)", "basic", "", "s"),
    HotkeyAction("vibrate_up", "Wibracja +", "basic", "<ctrl>+<shift>+<up>", "up"),
    HotkeyAction("vibrate_down", "Wibracja −", "basic", "<ctrl>+<shift>+<down>", "down"),
    HotkeyAction("vibrate_up_fast", "Wibracja ++ (szybko)", "basic", "<ctrl>+<shift>+period", "+"),
    HotkeyAction("vibrate_down_fast", "Wibracja −− (szybko)", "basic", "<ctrl>+<shift>+comma", "-"),
    HotkeyAction("pump_up", "2. funkcja +", "basic", "<ctrl>+<shift>+<right>", "right"),
    HotkeyAction("pump_down", "2. funkcja −", "basic", "<ctrl>+<shift>+<left>", "left"),
    HotkeyAction("pump_up_alt", "2. funkcja + (alt)", "basic", "", "]"),
    HotkeyAction("pump_down_alt", "2. funkcja − (alt)", "basic", "", "["),
    HotkeyAction("audio_toggle", "Audio react on/off", "basic", "<ctrl>+<shift>+a", "a"),
    HotkeyAction("boost", "Boost (max na chwilę)", "basic", "<ctrl>+<shift>+b", "b"),
    # Poziomy 0–9
    HotkeyAction("level_0", "Poziom 0 (stop)", "level", "<ctrl>+<shift>+0", "0"),
    HotkeyAction("level_1", "Poziom 1", "level", "<ctrl>+<alt>+1", "1"),
    HotkeyAction("level_2", "Poziom 2", "level", "<ctrl>+<alt>+2", "2"),
    HotkeyAction("level_3", "Poziom 3", "level", "<ctrl>+<alt>+3", "3"),
    HotkeyAction("level_4", "Poziom 4", "level", "<ctrl>+<alt>+4", "4"),
    HotkeyAction("level_5", "Poziom 5", "level", "<ctrl>+<alt>+5", "5"),
    HotkeyAction("level_6", "Poziom 6", "level", "<ctrl>+<alt>+6", "6"),
    HotkeyAction("level_7", "Poziom 7", "level", "<ctrl>+<alt>+7", "7"),
    HotkeyAction("level_8", "Poziom 8", "level", "<ctrl>+<alt>+8", "8"),
    HotkeyAction("level_9", "Poziom 9 (max)", "level", "<ctrl>+<alt>+9", "9"),
    # Presety
    HotkeyAction("preset_pulse", "Preset: pulse", "preset", "<ctrl>+<shift>+1", "q"),
    HotkeyAction("preset_wave", "Preset: wave", "preset", "<ctrl>+<shift>+2", "w"),
    HotkeyAction("preset_fireworks", "Preset: fireworks", "preset", "<ctrl>+<shift>+3", "e"),
    HotkeyAction("preset_earthquake", "Preset: earthquake", "preset", "<ctrl>+<shift>+4", "r"),
    HotkeyAction("preset_tease", "Preset: tease", "preset", "<ctrl>+<shift>+5", "t"),
    HotkeyAction("preset_climb", "Preset: climb", "preset", "<ctrl>+<shift>+6", "y"),
    HotkeyAction("preset_edge", "Preset: edge", "preset", "<ctrl>+<shift>+7", "u"),
    HotkeyAction("preset_throb", "Preset: throb", "preset", "<ctrl>+<shift>+8", "i"),
    HotkeyAction("preset_heartbeat", "Preset: heartbeat", "preset", "", "j"),
    HotkeyAction("preset_ocean", "Preset: ocean", "preset", "", "k"),
    HotkeyAction("preset_slowburn", "Preset: slowburn (długi)", "preset", "", ""),
    HotkeyAction("preset_marathon", "Preset: marathon (długi)", "preset", "", ""),
    HotkeyAction("preset_waveslow", "Preset: waveslow (długi)", "preset", "", ""),
    HotkeyAction("preset_crescendo", "Preset: crescendo (długi)", "preset", "", ""),
    # Tryby automatyczne
    HotkeyAction("mode_oscillate", "Tryb: oscylacja", "mode", "<ctrl>+<shift>+o", "o"),
    HotkeyAction("mode_random", "Tryb: losowy", "mode", "<ctrl>+<shift>+x", "x"),
    HotkeyAction("mode_ramp_up", "Tryb: ramp w górę", "mode", "<ctrl>+<shift>+u", ""),
    HotkeyAction("mode_ramp_down", "Tryb: ramp w dół", "mode", "<ctrl>+<shift>+d", ""),
    HotkeyAction("mode_stop", "Zatrzymaj tryb auto", "mode", "<ctrl>+<shift>+z", "z"),
)

HOTKEY_BY_ID: dict[str, HotkeyAction] = {a.id: a for a in HOTKEY_ACTIONS}

GROUP_LABELS = {
    "basic": "Podstawowe",
    "level": "Poziomy 0–9",
    "preset": "Presety",
    "mode": "Tryby automatyczne",
}

# Mapowanie starych pól config → id akcji (migracja z config.json)
LEGACY_CHORD_FIELDS: dict[str, str] = {
    "hotkey_stop": "stop",
    "hotkey_vibrate_up": "vibrate_up",
    "hotkey_vibrate_down": "vibrate_down",
    "hotkey_pump_up": "pump_up",
    "hotkey_pump_down": "pump_down",
    "hotkey_preset_pulse": "preset_pulse",
    "hotkey_preset_wave": "preset_wave",
    "hotkey_preset_fireworks": "preset_fireworks",
    "hotkey_preset_earthquake": "preset_earthquake",
    "hotkey_level_0": "level_0",
    "hotkey_level_1": "level_1",
    "hotkey_level_2": "level_2",
    "hotkey_level_3": "level_3",
    "hotkey_level_4": "level_4",
    "hotkey_level_5": "level_5",
    "hotkey_level_6": "level_6",
    "hotkey_level_7": "level_7",
    "hotkey_level_8": "level_8",
    "hotkey_level_9": "level_9",
    "hotkey_audio_toggle": "audio_toggle",
}


def default_chord_map() -> dict[str, str]:
    return {a.id: a.default_chord for a in HOTKEY_ACTIONS if a.default_chord}


def default_game_map() -> dict[str, str]:
    return {a.id: a.default_game for a in HOTKEY_ACTIONS if a.default_game}


def format_chord_display(chord: str) -> str:
    """Czytelny opis skrótu chord (pynput) dla UI."""
    if not chord:
        return "—"
    parts = []
    for p in chord.lower().split("+"):
        p = p.strip().strip("<>")
        names = {
            "ctrl": "Ctrl",
            "control": "Ctrl",
            "alt": "Alt",
            "shift": "Shift",
            "cmd": "Super",
            "super": "Super",
            "up": "↑",
            "down": "↓",
            "left": "←",
            "right": "→",
            "space": "Spacja",
            "esc": "Esc",
            "escape": "Esc",
            "enter": "Enter",
            "return": "Enter",
            "tab": "Tab",
            "backspace": "Backspace",
            "equal": "=",
            "minus": "−",
        }
        parts.append(names.get(p, p.upper() if len(p) == 1 else p.capitalize()))
    return "+".join(parts)


def format_game_display(key: str) -> str:
    if not key:
        return "—"
    names = {
        "space": "Spacja",
        "up": "↑",
        "down": "↓",
        "left": "←",
        "right": "→",
        "esc": "Esc",
        "escape": "Esc",
        "enter": "Enter",
        "return": "Enter",
        "tab": "Tab",
        "equal": "=",
        "minus": "−",
        "+": "+",
        "-": "−",
        "[": "[",
        "]": "]",
    }
    k = key.lower()
    return names.get(k, key.upper() if len(key) == 1 else key)
