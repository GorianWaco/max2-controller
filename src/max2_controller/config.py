"""Konfiguracja domyślna i wczytywanie z pliku JSON."""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from max2_controller.hotkey_defs import (
    LEGACY_CHORD_FIELDS,
    default_chord_map,
    default_game_map,
)

CONFIG_DIR = Path.home() / ".config" / "max2-controller"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class SavedPattern:
    name: str
    strength: str
    interval_ms: int = 200

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "strength": self.strength, "interval_ms": self.interval_ms}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SavedPattern":
        return cls(
            name=str(data.get("name") or "pattern"),
            strength=str(data.get("strength") or "10;0"),
            interval_ms=int(data.get("interval_ms") or 200),
        )


@dataclass
class AppConfig:
    # "ble" = Bluetooth bezpośrednio z PC (bez telefonu) — domyślne
    # "lovense_local" = Lovense Connect / Remote (telefon lub Connect)
    backend: str = "ble"

    # Lovense Local API — Connect (HTTP) lub Remote PC (HTTPS)
    lovense_url: str = "http://127.0.0.1:20010/command"
    lovense_verify_ssl: bool = False
    app_name: str = "Max2Controller"

    # Debounce suwaków (ms) — nie zalej API
    slider_debounce_ms: int = 80

    # Lokalne API do gier (tylko localhost domyślnie)
    game_api_host: str = "127.0.0.1"
    game_api_port: int = 8765
    game_api_enabled: bool = True
    game_api_token: str = field(default_factory=lambda: secrets.token_urlsafe(16))

    # Zdalne sterowanie (web panel dla innych osób)
    remote_enabled: bool = False
    remote_host: str = "0.0.0.0"
    remote_port: int = 8787
    remote_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    remote_allow_stop: bool = True
    remote_allow_audio: bool = True  # partnerka może włączać/wyłączać audio react
    remote_allow_audio_params: bool = True  # partnerka: czułość / gain
    remote_max_vibrate: int = 20
    remote_max_pump: int = 3

    # Cloudflare Tunnel — udostępnianie przez internet
    # quick = losowy trycloudflare (zmienia się); named = stały hostname; token = token z Zero Trust
    tunnel_mode: str = "quick"  # quick | named | token
    tunnel_name: str = "lovense-controller"
    tunnel_hostname: str = ""  # np. lovense.twojadomena.com (named)
    tunnel_token: str = ""  # token z Cloudflare Zero Trust (token mode)
    tunnel_public_url: str = ""  # zapisany stały https://… (do kopiowania)
    tunnel_id: str = ""  # UUID named tunnel (po create)
    tunnel_auto_start: bool = False  # start tunnel przy włączaniu panelu remote

    # Hotkeys
    hotkeys_enabled: bool = True
    # Proste klawisze globalnie (0-9, spacja, …) — wygodne w grze, ostrożnie w pracy
    hotkeys_game_mode: bool = True
    # action_id → chord pynput ("<ctrl>+<shift>+s")
    hotkeys_chord: dict[str, str] = field(default_factory=default_chord_map)
    # action_id → pojedynczy klawisz trybu gry ("space", "1", "up")
    hotkeys_game: dict[str, str] = field(default_factory=default_game_map)

    # Sterowanie — limity i kroki
    control_max_vibrate: int = 20  # miękki limit 1–20
    control_max_pump: int = 3  # dla Max 2; Gemini/Nora i tak skaluje backend
    control_step_vibrate: int = 1
    control_step_vibrate_fast: int = 2
    control_step_pump: int = 1
    control_auto_pump_with_level: bool = True  # poziomy 0–9 też ruszają pump
    control_boost_level: int = 20  # siła boosta
    control_oscillate_min: int = 4
    control_oscillate_max: int = 18
    control_oscillate_interval_ms: int = 350
    control_random_min: int = 2
    control_random_max: int = 18
    control_random_interval_ms: int = 500
    control_ramp_seconds: float = 8.0
    # Mapowanie poziomów 0–9 → siła wibracji (0–20)
    control_level_map: list[int] = field(
        default_factory=lambda: [0, 2, 4, 7, 9, 11, 13, 15, 17, 20]
    )

    # Zapisane własne wzorce
    saved_patterns: list[dict[str, Any]] = field(default_factory=list)

    # Audio react
    audio_mode: str = "playback"
    audio_sink: str = ""
    audio_source: str = ""
    audio_gain: float = 10.0
    audio_sensitivity: float = 1.4
    audio_threshold: float = 0.015
    audio_curve: float = 0.65
    audio_attack: float = 0.45
    audio_release: float = 0.12
    audio_max_vibrate: int = 20
    audio_max_pump: int = 2
    audio_pump_enabled: bool = True

    # Polling baterii (s)
    battery_poll_sec: float = 15.0

    def chord_for(self, action_id: str) -> str:
        return (self.hotkeys_chord or {}).get(action_id, "") or ""

    def game_key_for(self, action_id: str) -> str:
        return (self.hotkeys_game or {}).get(action_id, "") or ""

    def set_chord(self, action_id: str, chord: str) -> None:
        if self.hotkeys_chord is None:
            self.hotkeys_chord = {}
        if chord:
            self.hotkeys_chord[action_id] = chord
        else:
            self.hotkeys_chord.pop(action_id, None)

    def set_game_key(self, action_id: str, key: str) -> None:
        if self.hotkeys_game is None:
            self.hotkeys_game = {}
        if key:
            self.hotkeys_game[action_id] = key.lower()
        else:
            self.hotkeys_game.pop(action_id, None)

    def level_value(self, index: int) -> int:
        """Siła wibracji dla klawisza poziomu 0–9, z limitem soft."""
        m = self.control_level_map or [0, 2, 4, 7, 9, 11, 13, 15, 17, 20]
        if index < 0:
            index = 0
        if index >= len(m):
            index = len(m) - 1
        raw = int(m[index])
        cap = max(0, min(20, int(self.control_max_vibrate)))
        return max(0, min(cap, raw))

    def clamp_vibrate(self, v: int) -> int:
        cap = max(0, min(20, int(self.control_max_vibrate)))
        return max(0, min(cap, int(v)))

    def clamp_pump(self, p: int, hard_max: int = 20) -> int:
        cap = max(0, min(hard_max, int(self.control_max_pump)))
        return max(0, min(cap, int(p)))

    def get_saved_patterns(self) -> list[SavedPattern]:
        out: list[SavedPattern] = []
        for item in self.saved_patterns or []:
            if isinstance(item, dict):
                out.append(SavedPattern.from_dict(item))
        return out

    def save_pattern(self, name: str, strength: str, interval_ms: int = 200) -> None:
        name = (name or "").strip() or "Wzorzec"
        strength = (strength or "").strip()
        if not strength:
            return
        patterns = self.get_saved_patterns()
        # nadpisz o tej samej nazwie
        patterns = [p for p in patterns if p.name.lower() != name.lower()]
        patterns.append(SavedPattern(name=name, strength=strength, interval_ms=int(interval_ms)))
        self.saved_patterns = [p.to_dict() for p in patterns]

    def delete_pattern(self, name: str) -> None:
        patterns = [p for p in self.get_saved_patterns() if p.name.lower() != name.lower()]
        self.saved_patterns = [p.to_dict() for p in patterns]

    def reset_hotkeys_to_defaults(self) -> None:
        self.hotkeys_chord = default_chord_map()
        self.hotkeys_game = default_game_map()

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or CONFIG_PATH
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}

        # Migracja starych hotkey_* → hotkeys_chord
        chord = dict(filtered.get("hotkeys_chord") or default_chord_map())
        for legacy, action_id in LEGACY_CHORD_FIELDS.items():
            if legacy in data and data[legacy] and action_id not in (filtered.get("hotkeys_chord") or {}):
                # tylko gdy nowy dict nie ma jeszcze tej akcji z pliku użytkownika
                if "hotkeys_chord" not in data:
                    chord[action_id] = str(data[legacy])
        if "hotkeys_chord" not in data:
            # w pełni z legacy lub default
            for legacy, action_id in LEGACY_CHORD_FIELDS.items():
                if legacy in data and data[legacy]:
                    chord[action_id] = str(data[legacy])
            # dopełnij brakujące domyślne
            for k, v in default_chord_map().items():
                chord.setdefault(k, v)
        else:
            # dopełnij nowe akcje domyślnymi jeśli brak w zapisie
            for k, v in default_chord_map().items():
                chord.setdefault(k, v)
        filtered["hotkeys_chord"] = chord

        game = dict(filtered.get("hotkeys_game") or {})
        if not game:
            game = default_game_map()
        else:
            for k, v in default_game_map().items():
                game.setdefault(k, v)
        filtered["hotkeys_game"] = game

        # Usuń stare pola jeśli wcisnęły się przez pomyłkę (nie są w dataclass)
        # clamp sensownych wartości
        cfg = cls(**{k: v for k, v in filtered.items() if k in known})
        cfg.control_max_vibrate = max(1, min(20, int(cfg.control_max_vibrate)))
        cfg.control_max_pump = max(0, min(20, int(cfg.control_max_pump)))
        cfg.control_step_vibrate = max(1, min(10, int(cfg.control_step_vibrate)))
        cfg.control_step_vibrate_fast = max(1, min(10, int(cfg.control_step_vibrate_fast)))
        cfg.control_step_pump = max(1, min(5, int(cfg.control_step_pump)))
        if not cfg.control_level_map or len(cfg.control_level_map) < 10:
            base = [0, 2, 4, 7, 9, 11, 13, 15, 17, 20]
            lm = list(cfg.control_level_map or [])
            while len(lm) < 10:
                lm.append(base[len(lm)])
            cfg.control_level_map = [max(0, min(20, int(x))) for x in lm[:10]]
        return cfg
