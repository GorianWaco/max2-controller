"""Modele danych — Lovense: Lush 3, Nora, Max 2, Gemini i inne."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# DeviceType; → litera:model (protokół BLE Lovense + heurystyki nazw)
# https://buttplug.io/stpihkal/protocols/lovense/
MODEL_BY_LETTER: dict[str, str] = {
    "A": "Nora",
    "B": "Max 2",
    "C": "Nora",
    "L": "Ambi",
    "S": "Lush",
    "Z": "Hush",
    "W": "Domi",
    "P": "Edge",
    "O": "Osci",
    "H": "Solace",
    "G": "Gush",
    "Q": "Diamo",
    "V": "Mission",
    "X": "Ferri",
    "Y": "Gravity",
    # warianty / nowsze kody (gdy firmware zwraca inny prefix)
    "T": "Gemini",
    "M": "Gemini",
    "LB": "Lush",
    "B1": "Max 2",
}

# Modele priorytetowe w UI / dokumentacji
FEATURED_MODELS = ("Lush 3", "Nora", "Max 2", "Gemini")

SecondaryKind = Literal["none", "pump", "rotate", "vibrate2"]


@dataclass
class ToyInfo:
    id: str
    name: str
    nick_name: str = ""
    status: str = "0"  # "1" = połączona w aplikacji
    battery: int | None = None
    full_functions: list[str] = field(default_factory=list)
    short_functions: list[str] = field(default_factory=list)
    model_letter: str = ""
    model_name: str = ""
    secondary: SecondaryKind = "none"
    # True = trzymana przez nasz backend BLE (nie tylko BlueZ/system)
    app_connected: bool = False

    @property
    def display_name(self) -> str:
        base = self.nick_name or self.name or self.id
        if self.model_name and self.model_name.lower() not in base.lower():
            base = f"{base} · {self.model_name}"
        return f"{base} ({self.id[:8]})" if self.id else base

    @property
    def short_label(self) -> str:
        """Krótka etykieta do listy połączonych."""
        model = self.model_name or self.name or "Lovense"
        bat = f" · {self.battery}%" if self.battery is not None else ""
        return f"{model}{bat} · {self.id[:8]}"

    @property
    def connected(self) -> bool:
        return self.app_connected or str(self.status) in ("1", "true", "True")

    def supports_pump(self) -> bool:
        return self.secondary == "pump" or "max" in (self.model_name or self.name or "").lower()

    def supports_rotate(self) -> bool:
        return self.secondary == "rotate" or "nora" in (self.model_name or self.name or "").lower()

    def supports_vibrate2(self) -> bool:
        return self.secondary == "vibrate2"

    def is_dual_motor(self) -> bool:
        return self.secondary == "vibrate2"

    def secondary_label(self) -> str:
        if self.secondary == "pump":
            return "Pump / powietrze (0–3) · Max 2"
        if self.secondary == "rotate":
            return "Rotate (0–20) · Nora"
        if self.secondary == "vibrate2":
            return "Silnik 2 (0–20) · Gemini / Edge"
        return "Druga funkcja (brak — np. Lush 3)"

    def secondary_max(self) -> int:
        if self.secondary == "pump":
            return 3
        if self.secondary in ("rotate", "vibrate2"):
            return 20
        return 0

    def primary_label(self) -> str:
        if self.is_dual_motor():
            return "Silnik 1 / Vibrate (0–20)"
        return "Vibrate (0–20)"

    @classmethod
    def from_device_type(
        cls,
        toy_id: str,
        name: str,
        device_type_reply: str,
        battery: int | None = None,
    ) -> "ToyInfo":
        """
        device_type_reply np. 'B:335:38398F406B99;' lub 'S:11:...'
        Nazwa BLE (LVS-Lush3…) też pomaga rozpoznać model.
        """
        letter = ""
        raw = (device_type_reply or "").strip().rstrip(";")
        if raw:
            letter = raw.split(":")[0].strip().upper()

        model = MODEL_BY_LETTER.get(letter, "")
        model = refine_model_from_name(model, name, letter)
        secondary = secondary_for_model(model, letter, name)

        functions = ["Vibrate"]
        if secondary == "pump":
            functions.append("Pump")
        elif secondary == "rotate":
            functions.append("Rotate")
        elif secondary == "vibrate2":
            functions.extend(["Vibrate1", "Vibrate2"])

        display = name or model or "Lovense"
        return cls(
            id=toy_id,
            name=display,
            nick_name=display,
            status="1",
            battery=battery,
            full_functions=functions,
            model_letter=letter,
            model_name=model or "Lovense",
            secondary=secondary,
            app_connected=True,
        )

    @classmethod
    def from_lovense_dict(cls, toy_id: str, data: dict[str, Any]) -> "ToyInfo":
        name = str(data.get("name") or "unknown")
        full = list(data.get("fullFunctionNames") or [])
        short = list(data.get("shortFunctionNames") or [])
        model = refine_model_from_name(name, name, "")
        secondary = secondary_from_functions(full, short, name)
        return cls(
            id=str(data.get("id") or toy_id),
            name=name,
            nick_name=str(data.get("nickName") or data.get("nickname") or ""),
            status=str(data.get("status", "0")),
            battery=_as_int_or_none(data.get("battery")),
            full_functions=full,
            short_functions=short,
            model_name=model,
            secondary=secondary,
            app_connected=str(data.get("status", "0")) in ("1", "true", "True"),
        )


def refine_model_from_name(model: str, name: str, letter: str) -> str:
    """Doprecyzuj model po nazwie reklamowanej (LVS-Lush3, Gemini, Max…)."""
    n = f"{name} {model}".lower().replace("-", " ").replace("_", " ")
    # Max 2
    if "max" in n or letter == "B":
        if "max 2" in n or "max2" in n or letter == "B":
            return "Max 2"
        return model or "Max"
    # Nora
    if "nora" in n or letter in ("A", "C"):
        return "Nora"
    # Gemini (dwa silniki)
    if "gemini" in n or letter in ("T", "M"):
        return "Gemini"
    # Lush 3 / Lush
    if "lush" in n or letter == "S":
        if "lush 3" in n or "lush3" in n or "lvs-s" in n:
            return "Lush 3"
        if "lush 2" in n or "lush2" in n:
            return "Lush 2"
        return model if model.startswith("Lush") else "Lush"
    # Edge
    if "edge" in n or letter == "P":
        return "Edge"
    if model:
        return model
    if letter:
        return f"Lovense ({letter})"
    return "Lovense"


def secondary_for_model(model: str, letter: str, name: str) -> SecondaryKind:
    blob = f"{model} {name} {letter}".lower()
    if "max" in blob or letter == "B":
        return "pump"
    if "nora" in blob or letter in ("A", "C"):
        return "rotate"
    if any(x in blob for x in ("gemini", "edge", "dolce", "exomoon")) or letter in (
        "P",
        "T",
        "M",
    ):
        return "vibrate2"
    # Lush 3 — tylko wibracje
    return "none"


def secondary_from_functions(full: list[str], short: list[str], name: str) -> SecondaryKind:
    names = {f.lower() for f in full} | {f.lower() for f in short}
    n = name.lower()
    if "pump" in names or "p" in names or "max" in n:
        return "pump"
    if "rotate" in names or "r" in names or "nora" in n:
        return "rotate"
    if "vibrate2" in names or "v2" in names or "gemini" in n or "edge" in n:
        return "vibrate2"
    return "none"


def _as_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class CommandResult:
    ok: bool
    code: int | str | None = None
    message: str = ""
    raw: Any = None

    @classmethod
    def from_response(cls, data: dict[str, Any] | None, http_status: int = 200) -> "CommandResult":
        if data is None:
            return cls(ok=False, code=http_status, message="Brak odpowiedzi JSON")
        code = data.get("code", http_status)
        ok = code in (200, "200", 0, "0") or str(data.get("type", "")).lower() in ("ok", "success")
        msg = str(data.get("message") or data.get("type") or ("OK" if ok else "Błąd"))
        return cls(ok=ok, code=code, message=msg, raw=data)


PRESETS = (
    # klasyczne (Lovense API + emulowane)
    "pulse",
    "wave",
    "fireworks",
    "earthquake",
    "tease",
    "climb",
    "edge",
    "throb",
    # nowe — krótkie / średnie
    "heartbeat",
    "ripple",
    "stutter",
    "bounce",
    "cascade",
    "breath",
    "ocean",
    "spark",
    # dłuższe sekwencje (wolniejszy interwał / więcej kroków)
    "slowburn",
    "marathon",
    "teaselong",
    "edgelong",
    "waveslow",
    "deepwave",
    "crescendo",
    "afterglow",
    # fun / pop culture (haptic rhythm, not audio)
    "imperial",
)

# Aliasy nazw → kanoniczny klucz w PRESET_PATTERNS
PRESET_ALIASES: dict[str, str] = {
    "imperialmarch": "imperial",
    "imperial_march": "imperial",
    "vader": "imperial",
    "darth": "imperial",
    "starwars": "imperial",
    "star_wars": "imperial",
}

# Domyślny czas (s) gdy wywołanie bez time_sec / time_sec=0
PRESET_DEFAULT_SEC: dict[str, float] = {
    "pulse": 10,
    "wave": 12,
    "fireworks": 10,
    "earthquake": 12,
    "tease": 15,
    "climb": 12,
    "edge": 14,
    "throb": 10,
    "heartbeat": 16,
    "ripple": 14,
    "stutter": 12,
    "bounce": 12,
    "cascade": 15,
    "breath": 20,
    "ocean": 25,
    "spark": 10,
    "slowburn": 45,
    "marathon": 60,
    "teaselong": 40,
    "edgelong": 45,
    "waveslow": 50,
    "deepwave": 55,
    "crescendo": 40,
    "afterglow": 35,
    "imperial": 24,
}

# strength levels + interval_ms — używane przez BLE i local backend
# max ~50 kroków (limit API pattern)
PRESET_PATTERNS: dict[str, tuple[list[int], int]] = {
    "pulse": ([0, 20, 0, 20, 0, 20], 250),
    "wave": ([2, 6, 10, 14, 18, 14, 10, 6], 200),
    "fireworks": ([20, 0, 15, 0, 20, 5, 0], 150),
    "earthquake": ([12, 16, 20, 16, 12, 8, 12], 120),
    "tease": ([0, 4, 0, 8, 0, 12, 0, 6], 300),
    "climb": ([2, 4, 6, 8, 10, 12, 14, 16, 18, 20], 400),
    "edge": ([10, 12, 14, 16, 18, 20, 18, 16, 8, 4], 280),
    "throb": ([8, 16, 8, 18, 8, 20, 8], 180),
    # krótkie / średnie
    "heartbeat": ([0, 14, 0, 18, 0, 0, 12, 0], 220),
    "ripple": ([4, 8, 12, 16, 12, 8, 4, 8, 12, 8], 160),
    "stutter": ([16, 0, 16, 0, 8, 0, 20, 0, 12, 0], 120),
    "bounce": ([6, 14, 8, 18, 10, 20, 8, 16], 170),
    "cascade": ([20, 16, 12, 8, 4, 0, 4, 8, 12, 16, 20], 190),
    "breath": ([2, 4, 6, 8, 10, 12, 14, 12, 10, 8, 6, 4], 350),
    "ocean": ([3, 6, 9, 12, 15, 18, 15, 12, 9, 6, 3, 6, 10, 14, 10, 6], 280),
    "spark": ([0, 20, 0, 0, 15, 0, 0, 20, 0], 140),
    # dłuższe (więcej kroków + wolniej)
    "slowburn": (
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 18, 16, 14, 12],
        500,
    ),
    "marathon": (
        [4, 8, 12, 16, 12, 8, 4, 8, 12, 16, 20, 16, 12, 8, 4, 6, 10, 14, 18, 14, 10, 6, 4, 8, 12, 8, 4],
        400,
    ),
    "teaselong": (
        [0, 3, 0, 5, 0, 8, 0, 4, 0, 12, 0, 6, 0, 15, 0, 8, 0, 10, 0, 4, 0, 18, 0, 6],
        320,
    ),
    "edgelong": (
        [8, 10, 12, 14, 16, 18, 20, 18, 16, 14, 12, 10, 8, 12, 16, 20, 16, 10, 6, 4, 8, 14, 18, 12, 6],
        350,
    ),
    "waveslow": (
        [2, 4, 6, 8, 10, 12, 14, 16, 18, 16, 14, 12, 10, 8, 6, 4, 2, 4, 8, 12, 16, 12, 8, 4],
        450,
    ),
    "deepwave": (
        [1, 3, 5, 8, 11, 14, 17, 20, 17, 14, 11, 8, 5, 3, 1, 4, 8, 12, 16, 20, 16, 12, 8, 4, 2, 6, 10, 6, 2],
        380,
    ),
    "crescendo": (
        [2, 2, 4, 4, 6, 6, 8, 8, 10, 10, 12, 12, 14, 14, 16, 16, 18, 18, 20, 20, 18, 14, 10, 6],
        420,
    ),
    "afterglow": (
        [16, 14, 12, 10, 8, 6, 8, 10, 8, 6, 4, 6, 4, 2, 4, 2, 1, 2, 1, 0, 1, 0, 0, 1],
        400,
    ),
    # Imperial March (Star Wars) — rytm „dum dum dum da-da…” w wibracjach
    # ~50 kroków × 160 ms ≈ 8 s na pętlę; powtarza się przez time_sec
    "imperial": (
        [
            # phrase 1: G G G | Eb Bb | G | Eb Bb G
            18, 1, 0, 18, 1, 0, 18, 1, 0,
            10, 10, 11, 14, 0,
            18, 1, 0,
            10, 0, 14, 0, 18, 1, 0, 0,
            # phrase 2: głośniej / „higher”
            20, 1, 0, 20, 1, 0, 20, 1, 0,
            12, 12, 13, 16, 0,
            20, 1, 0,
            12, 0, 16, 0, 20, 1, 0, 0,
        ],
        160,
    ),
}

# etykiety PL do UI (opcjonalne)
PRESET_LABELS_PL: dict[str, str] = {
    "pulse": "Pulsowanie",
    "wave": "Fala",
    "fireworks": "Fajerwerki",
    "earthquake": "Trzęsienie",
    "tease": "Drażnienie",
    "climb": "Wspinaczka",
    "edge": "Na krawędzi",
    "throb": "Bicie",
    "heartbeat": "Heartbeat",
    "ripple": "Fale małe",
    "stutter": "Stutter",
    "bounce": "Odbicia",
    "cascade": "Kaskada",
    "breath": "Oddech",
    "ocean": "Ocean",
    "spark": "Iskry",
    "slowburn": "Slow burn (długi)",
    "marathon": "Maraton (długi)",
    "teaselong": "Tease long",
    "edgelong": "Edge long",
    "waveslow": "Wolna fala",
    "deepwave": "Głęboka fala",
    "crescendo": "Crescendo",
    "afterglow": "Afterglow",
    "imperial": "Imperial March (SW)",
}

SUPPORTED_MODELS_HELP = """
Wspierane m.in.:
  • Lush 3 — wibracje
  • Nora — wibracje + rotacja
  • Max 2 — wibracje + powietrze (pump)
  • Gemini — dwa silniki wibracji
  • oraz inne Lovense BLE (Edge, Domi, Hush…)
Można trzymać kilka zabawek naraz (lista połączonych).
""".strip()
