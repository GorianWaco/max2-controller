"""
Reakcja zabawki na dźwięk.

Tryby:
  playback    — całe wyjście (wszystkie aplikacje na głośnikach)
  application — jedna grająca aplikacja (PipeWire stream)
  microphone  — mikrofon / wejście

Pasma (domyślnie WŁ): IIR — bas (kick) → Vibrate, treble (hi-hat) → 2. funkcja.

Na PipeWire + Focusrite: pw-record/parec często dają ciszę na monitorze.
GStreamer `pulsesrc device=<sink>.monitor` działa poprawnie — używamy go jako domyślnego.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import numpy as np

if TYPE_CHECKING:
    from max2_controller.config import AppConfig
    from max2_controller.controller import Max2Controller

logger = logging.getLogger(__name__)

LevelCallback = Callable[[float, int, int], None]

# name → channels, filled by the last successful device scan (sinks and their .monitor)
_CHANNEL_BY_NAME: dict[str, int] = {}


@dataclass(frozen=True)
class AudioEndpoint:
    """Jedno wyjście albo wejście, które da się podać do pulsesrc/parec."""

    name: str
    description: str
    channels: int
    kind: str  # "sink" | "source"


@dataclass(frozen=True)
class AudioApp:
    """Aplikacja do podsłuchu: albo żywy strumień, albo włączony program bez dźwięku."""

    name: str  # klucz: „Tytuł<TAB>media” albo „proc<TAB>binary”
    description: str
    channels: int
    serial: int  # 0 = program jest włączony, ale jeszcze nic nie odtwarza
    binary: str = ""


@dataclass(frozen=True)
class AudioScan:
    sinks: list[AudioEndpoint]
    sources: list[AudioEndpoint]
    default_sink: str
    default_source: str
    apps: list[AudioApp]


def endpoint_labels(eps: list[AudioEndpoint], default_name: str = "") -> list[str]:
    """Nazwy jak w ustawieniach dźwięku, nie alsa_output.usb-…"""
    descriptions = [e.description for e in eps]
    labels: list[str] = []
    for ep in eps:
        lab = (ep.description or "").strip() or ep.name
        virtual = not ep.name.startswith("alsa_")
        if descriptions.count(ep.description) > 1 or (virtual and ep.name not in lab):
            lab = f"{lab} ({ep.name})"
        if default_name and ep.name == default_name:
            lab += " · domyślne"
        labels.append(lab)
    return labels


def _remember_channels(eps: list[AudioEndpoint]) -> None:
    for ep in eps:
        _CHANNEL_BY_NAME[ep.name] = ep.channels
        if ep.kind == "sink":
            _CHANNEL_BY_NAME[f"{ep.name}.monitor"] = ep.channels


def endpoints_from_pw_dump(data: object, kind: str) -> list[AudioEndpoint]:
    """PipeWire JSON (pw-dump). Monitory głośników nie są osobnymi źródłami."""
    if not isinstance(data, list):
        return []
    want = "Audio/Sink" if kind == "sink" else "Audio/Source"
    out: list[AudioEndpoint] = []
    seen: set[str] = set()
    for node in data:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "PipeWire:Interface:Node":
            continue
        info = node.get("info")
        props = info.get("props") if isinstance(info, dict) else None
        if not isinstance(props, dict):
            continue
        if props.get("media.class") != want:
            continue
        name = str(props.get("node.name") or "").strip()
        if not name or name in seen or name.endswith(".monitor"):
            continue
        seen.add(name)
        desc = str(props.get("node.description") or name).strip() or name
        raw_ch = props.get("audio.channels") or 2
        try:
            channels = max(1, int(raw_ch))
        except (TypeError, ValueError):
            channels = 2
        out.append(AudioEndpoint(name=name, description=desc, channels=channels, kind=kind))
    return out


def defaults_from_pw_dump(data: object) -> tuple[str, str]:
    sink = ""
    source = ""
    if not isinstance(data, list):
        return sink, source
    for node in data:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "PipeWire:Interface:Metadata":
            continue
        meta = node.get("metadata")
        if not isinstance(meta, list):
            continue
        for item in meta:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            value = item.get("value")
            name = ""
            if isinstance(value, dict):
                name = str(value.get("name") or "").strip()
            elif isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    name = str(parsed.get("name") or "").strip()
            if key == "default.audio.sink" and name:
                sink = name
            elif key == "default.audio.source" and name:
                source = name
    return sink, source


def endpoints_from_pactl_blocks(text: str, kind: str) -> list[AudioEndpoint]:
    marker = "Sink #" if kind == "sink" else "Source #"
    out: list[AudioEndpoint] = []
    seen: set[str] = set()
    for block in text.split(marker)[1:]:
        name_m = re.search(r"Name:\s*(\S+)", block)
        if not name_m:
            continue
        name = name_m.group(1).strip()
        if not name or name in seen:
            continue
        if kind == "source" and name.endswith(".monitor"):
            continue
        seen.add(name)
        desc_m = re.search(r"Description:\s*(.+)", block)
        desc = desc_m.group(1).strip() if desc_m else name
        ch_m = re.search(r"Sample Specification:\s*\S+\s+(\d+)ch", block)
        channels = max(1, int(ch_m.group(1))) if ch_m else 2
        out.append(AudioEndpoint(name=name, description=desc or name, channels=channels, kind=kind))
    return out


_OWN_TAP_BINARIES = {"pw-record", "gst-launch-1.0", "pw-cat"}


def _decorate_apps(raw: list[tuple[str, str, str, int, int, str]]) -> list[AudioApp]:
    """raw = (tytuł, media, node_name, serial, channels, binary)."""
    titles = [title or "aplikacja" for title, _media, _node, _serial, _ch, _bin in raw]
    counts: dict[str, int] = {}
    for title in titles:
        counts[title] = counts.get(title, 0) + 1
    out: list[AudioApp] = []
    seen: set[str] = set()
    for (title, media, node, serial, channels, binary), shown in zip(raw, titles, strict=True):
        media_l = (media or "").strip()
        if counts[shown] > 1 and media_l:
            label = f"{shown} — {media_l}"
        else:
            label = shown
        key = f"{shown}\t{media_l}"
        if key in seen:
            key = f"{key}\t{node}"
        seen.add(key)
        out.append(
            AudioApp(
                name=key,
                description=label,
                channels=max(1, int(channels or 2)),
                serial=int(serial),
                binary=(binary or "").strip(),
            )
        )
    return out


def apps_from_pw_dump(data: object) -> list[AudioApp]:
    """Strumienie odtwarzania (Firefox, gry). Monitory i nasz własny podsłuch odpadają."""
    if not isinstance(data, list):
        return []
    raw: list[tuple[str, str, str, int, int, str]] = []
    seen_serial: set[int] = set()
    for node in data:
        if not isinstance(node, dict) or node.get("type") != "PipeWire:Interface:Node":
            continue
        info = node.get("info")
        props = info.get("props") if isinstance(info, dict) else None
        if not isinstance(props, dict):
            continue
        if props.get("media.class") != "Stream/Output/Audio":
            continue
        binary = str(props.get("application.process.binary") or "").strip()
        node_name = str(props.get("node.name") or "").strip()
        if binary in _OWN_TAP_BINARIES or node_name == "lovense-audio-tap":
            continue
        application = str(props.get("application.name") or "").strip()
        media = str(props.get("media.name") or "").strip()
        title = application or binary or node_name
        if not title:
            continue
        try:
            serial = int(props.get("object.serial") or node.get("id") or 0)
        except (TypeError, ValueError):
            serial = 0
        if serial <= 0 or serial in seen_serial:
            continue
        seen_serial.add(serial)
        try:
            channels = max(1, int(props.get("audio.channels") or 2))
        except (TypeError, ValueError):
            channels = 2
        raw.append((title, media, node_name, serial, channels, binary))
    raw.sort(key=lambda item: item[0].lower())
    return _decorate_apps(raw)


def apps_from_pactl_sink_inputs(text: str) -> list[AudioApp]:
    raw: list[tuple[str, str, str, int, int, str]] = []
    seen_serial: set[int] = set()
    for block in re.split(r"\n(?=Sink Input #)", text):
        if "Sink Input #" not in block:
            continue
        props: dict[str, str] = {}
        for line in block.splitlines():
            if " = " not in line:
                continue
            key, value = line.split(" = ", 1)
            props[key.strip()] = value.strip().strip('"')
        binary = props.get("application.process.binary", "")
        node_name = props.get("node.name", "")
        if binary in _OWN_TAP_BINARIES or node_name == "lovense-audio-tap":
            continue
        title = props.get("application.name") or binary or node_name
        if not title:
            continue
        try:
            serial = int(props.get("object.serial") or 0)
        except ValueError:
            serial = 0
        if serial <= 0 or serial in seen_serial:
            continue
        seen_serial.add(serial)
        raw.append((title, props.get("media.name", ""), node_name, serial, 2, binary))
    raw.sort(key=lambda item: item[0].lower())
    return _decorate_apps(raw)


_DESKTOP_CATEGORIES = {"AudioVideo", "Audio", "Video", "Player", "Game", "WebBrowser"}
_DESKTOP_DIRS = (
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
)
_desktop_cache: tuple[float, dict[str, str]] | None = None


def exec_basename(exec_line: str) -> str:
    try:
        parts = shlex.split(exec_line, posix=True)
    except ValueError:
        parts = exec_line.split()
    if not parts:
        return ""
    idx = 0
    if parts[0] == "env":
        idx = 1
        while idx < len(parts) and "=" in parts[idx] and not parts[idx].startswith("-"):
            idx += 1
    if idx >= len(parts):
        return ""
    token = parts[idx]
    if token.startswith("%"):
        return ""
    return os.path.basename(token)


def binary_from_desktop(text: str) -> tuple[str, str, int] | None:
    """Główna grupa [Desktop Entry]: (binary, nazwa, ocena). Pomija akcje New Window."""
    group = ""
    name = ""
    name_pl = ""
    exe = ""
    exec_raw = ""
    nodisplay = False
    categories = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if group == "Desktop Entry":
                break
            group = stripped[1:-1]
            continue
        if group != "Desktop Entry" or "=" not in stripped or stripped.startswith("#"):
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "Name":
            name = value
        elif key == "Name[pl]":
            name_pl = value
        elif key == "Exec" and not exe:
            exec_raw = value
            exe = exec_basename(value)
        elif key == "NoDisplay" and value.lower() == "true":
            nodisplay = True
        elif key == "Categories":
            categories = value
    if nodisplay or not exe:
        return None
    cats = {part for part in categories.split(";") if part}
    if not (cats & _DESKTOP_CATEGORIES):
        return None
    title = name_pl or name or exe
    score = 0
    if title.lower().replace(" ", "") == exe.lower():
        score += 5
    if exe.lower() in title.lower():
        score += 3
    # steam steam://rungameid/… to skrót gry, nie nazwa programu steam
    if "://" in exec_raw:
        score -= 5
    return exe, title, score


def prefer_desktop_names(entries: list[tuple[str, str, int]]) -> dict[str, str]:
    """Gdy kilka .desktop ma ten sam binary, zostaw najlepiej pasującą nazwę."""
    best: dict[str, tuple[int, str]] = {}
    for binary, title, score in entries:
        prev = best.get(binary)
        if prev is None or score > prev[0]:
            best[binary] = (score, title)
    return {binary: title for binary, (score, title) in best.items()}


def desktop_binary_names() -> dict[str, str]:
    """binary → nazwa z pliku .desktop (przeglądarki, gry, odtwarzacze)."""
    global _desktop_cache
    now = time.monotonic()
    if _desktop_cache is not None and (now - _desktop_cache[0]) < 60:
        return _desktop_cache[1]
    entries: list[tuple[str, str, int]] = []
    for directory in _DESKTOP_DIRS:
        if not directory.is_dir():
            continue
        for path in directory.glob("*.desktop"):
            try:
                parsed = binary_from_desktop(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if parsed is not None:
                entries.append(parsed)
    found = prefer_desktop_names(entries)
    _desktop_cache = (now, found)
    return found


def running_user_exes() -> set[str]:
    uid = os.getuid()
    found: set[str] = set()
    try:
        entries = os.scandir("/proc")
    except OSError:
        return found
    with entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid != uid:
                    continue
                exe = os.path.basename(os.readlink(entry.path + "/exe"))
            except OSError:
                continue
            if exe.endswith(" (deleted)"):
                exe = exe[: -len(" (deleted)")]
            if exe:
                found.add(exe)
    return found


def idle_apps_from_binaries(
    desktop: dict[str, str],
    running: set[str],
    streams: list[AudioApp],
) -> list[AudioApp]:
    """Programy włączone, które jeszcze nie mają strumienia (Firefox bez filmu)."""
    live_bins = {app.binary for app in streams if app.binary}
    out: list[AudioApp] = []
    for binary in sorted(running, key=lambda name: desktop.get(name, name).lower()):
        if binary not in desktop or binary in live_bins:
            continue
        if binary in _OWN_TAP_BINARIES or binary in {"lovense-controller", "python", "python3"}:
            continue
        title = desktop[binary]
        out.append(
            AudioApp(
                name=f"proc\t{binary}",
                description=f"{title} · czeka na dźwięk",
                channels=2,
                serial=0,
                binary=binary,
            )
        )
    return out


def attach_running_apps(apps: list[AudioApp]) -> list[AudioApp]:
    try:
        extra = idle_apps_from_binaries(desktop_binary_names(), running_user_exes(), apps)
    except Exception:
        logger.exception("running apps")
        return apps
    if not extra:
        return apps
    merged = list(apps) + extra
    merged.sort(key=lambda app: app.description.lower())
    return merged


def match_audio_app(apps: list[AudioApp], key: str) -> AudioApp | None:
    """Dopasuj zapisany wybór. proc<TAB>firefox łapie strumień, gdy Firefox zacznie grać."""
    wanted = (key or "").strip()
    if not wanted:
        return None
    exact = next((app for app in apps if app.name == wanted), None)
    if wanted.startswith("proc\t"):
        binary = wanted.split("\t", 1)[1]
        live = [app for app in apps if app.binary == binary and app.serial > 0]
        if len(live) == 1:
            return live[0]
        if len(live) > 1:
            return live[0]
        return exact
    if exact is not None and exact.serial > 0:
        return exact
    title = wanted.split("\t", 1)[0]
    same = [app for app in apps if app.serial > 0 and app.name.split("\t", 1)[0] == title]
    if len(same) == 1:
        return same[0]
    return exact


def _pactl_defaults() -> tuple[str, str]:
    sink = ""
    source = ""
    try:
        out = subprocess.check_output(["pactl", "get-default-sink"], text=True, timeout=2)
        sink = out.strip()
    except Exception:
        sink = ""
    try:
        out = subprocess.check_output(["pactl", "get-default-source"], text=True, timeout=2)
        source = out.strip()
    except Exception:
        source = ""
    return sink, source


def _scan_via_pactl() -> AudioScan:
    sinks: list[AudioEndpoint] = []
    sources: list[AudioEndpoint] = []
    try:
        sinks = endpoints_from_pactl_blocks(
            subprocess.check_output(["pactl", "list", "sinks"], text=True, timeout=5),
            "sink",
        )
    except Exception:
        logger.exception("pactl list sinks")
    try:
        sources = endpoints_from_pactl_blocks(
            subprocess.check_output(["pactl", "list", "sources"], text=True, timeout=5),
            "source",
        )
    except Exception:
        logger.exception("pactl list sources")
    default_sink, default_source = _pactl_defaults()
    apps: list[AudioApp] = []
    try:
        apps = apps_from_pactl_sink_inputs(
            subprocess.check_output(["pactl", "list", "sink-inputs"], text=True, timeout=4)
        )
    except Exception:
        logger.exception("pactl list sink-inputs")
    return AudioScan(sinks, sources, default_sink, default_source, attach_running_apps(apps))


_scan_cache: tuple[float, AudioScan] | None = None


def scan_audio_devices(*, force: bool = False) -> AudioScan:
    """Rozpoznaj wyjścia i wejścia. Najpierw PipeWire (pw-dump), potem pactl."""
    global _scan_cache
    now = time.monotonic()
    if not force and _scan_cache is not None and (now - _scan_cache[0]) < 1.5:
        return _scan_cache[1]
    scan = _scan_audio_devices_uncached()
    _scan_cache = (now, scan)
    return scan


def _scan_audio_devices_uncached() -> AudioScan:
    if shutil.which("pw-dump"):
        try:
            raw = subprocess.check_output(["pw-dump"], text=True, timeout=4)
            data = json.loads(raw)
            sinks = endpoints_from_pw_dump(data, "sink")
            sources = endpoints_from_pw_dump(data, "source")
            apps = apps_from_pw_dump(data)
            if sinks or sources or apps:
                default_sink, default_source = defaults_from_pw_dump(data)
                if not default_sink or not default_source:
                    ps, pr = _pactl_defaults()
                    default_sink = default_sink or ps
                    default_source = default_source or pr
                _remember_channels(sinks + sources)
                return AudioScan(sinks, sources, default_sink, default_source, attach_running_apps(apps))
        except Exception:
            logger.exception("pw-dump")
    scan = _scan_via_pactl()
    _remember_channels(scan.sinks + scan.sources)
    return scan


def default_sink_name() -> str | None:
    name = scan_audio_devices().default_sink
    return name or None


def default_source_name() -> str | None:
    name = scan_audio_devices().default_source
    return name or None


def list_playback_sinks() -> list[str]:
    return [ep.name for ep in scan_audio_devices().sinks]


def list_input_sources() -> list[str]:
    """Źródła wejściowe (bez .monitor — te to echo głośników)."""
    return [ep.name for ep in scan_audio_devices().sources]


def sink_channels(sink: str) -> int:
    """Liczba kanałów sinka (Focusrite surround 2.1 = 3)."""
    cached = _CHANNEL_BY_NAME.get(sink)
    if cached:
        return cached
    try:
        out = subprocess.check_output(["pactl", "list", "sinks"], text=True, timeout=5)
        blocks = out.split("Sink #")
        for block in blocks:
            if f"Name: {sink}" not in block:
                continue
            m = re.search(r"Sample Specification:\s*\S+\s+(\d+)ch", block)
            if m:
                return max(1, int(m.group(1)))
    except Exception:
        logger.exception("sink_channels")
    return 2


def source_channels(source: str) -> int:
    cached = _CHANNEL_BY_NAME.get(source)
    if cached:
        return cached
    try:
        out = subprocess.check_output(["pactl", "list", "sources"], text=True, timeout=5)
        blocks = out.split("Source #")
        for block in blocks:
            if f"Name: {source}" not in block:
                continue
            m = re.search(r"Sample Specification:\s*\S+\s+(\d+)ch", block)
            if m:
                return max(1, int(m.group(1)))
    except Exception:
        logger.exception("source_channels")
    return 2


def monitor_of_sink(sink: str) -> str:
    sink = sink.strip()
    if sink.endswith(".monitor"):
        return sink
    return f"{sink}.monitor"


BiquadZi = tuple[float, float, float, float]  # x1, x2, y1, y2
BiquadCoeffs = tuple[float, float, float, float, float]  # b0, b1, b2, a1, a2


def pcm_to_mono(raw: bytes, channels: int = 2) -> np.ndarray:
    """S16LE interleaved → float32 mono w zakresie ok. [-1, 1]."""
    if len(raw) < max(1, channels) * 2:
        return np.zeros(0, dtype=np.float32)
    arr = np.frombuffer(raw, dtype=np.int16)
    if arr.size == 0:
        return np.zeros(0, dtype=np.float32)
    f = arr.astype(np.float32) / 32768.0
    ch = max(1, int(channels))
    if ch > 1 and f.size >= ch:
        usable = (f.size // ch) * ch
        frames = f[:usable].reshape(-1, ch)
        use = min(2, frames.shape[1])
        return frames[:, :use].mean(axis=1)
    return f


def _rbj_lowpass(fc: float, fs: float, q: float = 0.70710678) -> BiquadCoeffs:
    w0 = 2.0 * math.pi * fc / fs
    cw = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    b0 = (1.0 - cw) * 0.5
    b1 = 1.0 - cw
    b2 = (1.0 - cw) * 0.5
    a0 = 1.0 + alpha
    a1 = -2.0 * cw
    a2 = 1.0 - alpha
    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def _rbj_highpass(fc: float, fs: float, q: float = 0.70710678) -> BiquadCoeffs:
    w0 = 2.0 * math.pi * fc / fs
    cw = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    b0 = (1.0 + cw) * 0.5
    b1 = -(1.0 + cw)
    b2 = (1.0 + cw) * 0.5
    a0 = 1.0 + alpha
    a1 = -2.0 * cw
    a2 = 1.0 - alpha
    return (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)


def biquad_process(
    mono: np.ndarray,
    coeffs: BiquadCoeffs,
    zi: BiquadZi | None = None,
) -> tuple[np.ndarray, BiquadZi]:
    """Jedno biquad RBJ. zi = stan między chunkami (kick nie ginie na granicy 40 ms)."""
    b0, b1, b2, a1, a2 = coeffs
    x1, x2, y1, y2 = zi if zi is not None else (0.0, 0.0, 0.0, 0.0)
    n = int(mono.size)
    out = np.empty(n, dtype=np.float32)
    src = mono.astype(np.float32, copy=False)
    for i in range(n):
        xv = float(src[i])
        yn = b0 * xv + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[i] = yn
        x2, x1 = x1, xv
        y2, y1 = y1, yn
    return out, (x1, x2, y1, y2)


def band_filter(
    mono: np.ndarray,
    rate: int,
    lo_hz: float,
    hi_hz: float,
    zi_hp: BiquadZi | None = None,
    zi_lp: BiquadZi | None = None,
) -> tuple[np.ndarray, BiquadZi | None, BiquadZi | None]:
    """
    Butterworth 2. rzędu: lowpass gdy lo≈0, highpass gdy hi≈Nyquist, inaczej kaskada.
    FFT w 40 ms wycieka kicka do treble — IIR tego nie robi.
    """
    n = int(mono.size)
    if n < 8 or rate <= 0:
        return np.zeros(0, dtype=np.float32), zi_hp, zi_lp
    nyq = float(rate) * 0.49
    lo = max(0.0, float(lo_hz))
    hi = min(nyq, max(lo + 1.0, float(hi_hz)))
    y = mono.astype(np.float32, copy=False)
    out_hp, out_lp = zi_hp, zi_lp
    if lo >= 30.0:
        y, out_hp = biquad_process(y, _rbj_highpass(min(lo, nyq - 1.0), float(rate)), zi_hp)
    if hi < nyq * 0.95:
        y, out_lp = biquad_process(y, _rbj_lowpass(max(20.0, hi), float(rate)), zi_lp)
    return y, out_hp, out_lp


def band_metrics(
    mono: np.ndarray,
    rate: int,
    lo_hz: float,
    hi_hz: float,
    zi_hp: BiquadZi | None = None,
    zi_lp: BiquadZi | None = None,
) -> tuple[float, float, BiquadZi | None, BiquadZi | None]:
    """RMS i peak pasma — ta sama skala co pełny sygnał (~0–1)."""
    filtered, zi_hp, zi_lp = band_filter(mono, rate, lo_hz, hi_hz, zi_hp=zi_hp, zi_lp=zi_lp)
    if filtered.size == 0:
        return 0.0, 0.0, zi_hp, zi_lp
    rms = float(np.sqrt(np.mean(filtered * filtered)))
    peak = float(np.max(np.abs(filtered)))
    if not math.isfinite(rms):
        rms = 0.0
    if not math.isfinite(peak):
        peak = 0.0
    return rms, peak, zi_hp, zi_lp


def mix_level(rms: float, peak: float) -> float:
    """Jak dawny detektor: trochę RMS, trochę peak (kick/hi-hat)."""
    return 0.65 * float(rms) + 0.35 * float(peak)


class AudioReactor:
    """Wątek: dźwięk → poziomy Vibrate/Pump (opcjonalnie bas/treble)."""

    def __init__(self, controller: "Max2Controller", config: "AppConfig") -> None:
        self.controller = controller
        self.config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self.enabled = False
        self.last_rms = 0.0
        self.last_vibrate = 0
        self.last_pump = 0
        self.last_bass = 0.0  # 0–1 po krzywej (pasmo bas)
        self.last_treble = 0.0
        self.last_bass_rms = 0.0
        self.last_treble_rms = 0.0
        self._smooth: dict[str, float] = {"level": 0.0, "bass": 0.0, "treble": 0.0}
        self._lp_zi: BiquadZi | None = None  # bas (lowpass)
        self._hp_zi: BiquadZi | None = None  # treble (highpass)
        self._on_level: list[LevelCallback] = []
        self._lock = threading.Lock()
        self._last_send = 0.0
        self._last_vp = (-1, -1)
        self.capture_device = ""
        self.capture_backend = ""

    def on_level(self, cb: LevelCallback) -> None:
        self._on_level.append(cb)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _resolve_device(self) -> tuple[str, int, str]:
        """
        Zwraca (pulse_device, channels, opis).
        playback → <sink>.monitor
        microphone → source (nie monitor)
        """
        mode = (self.config.audio_mode or "playback").lower().strip()
        if mode in ("app", "application", "aplikacja"):
            key = str(getattr(self.config, "audio_app", "") or "").strip()
            if not key:
                raise RuntimeError("Wybierz aplikację z listy")
            match = match_audio_app(scan_audio_devices(force=True).apps, key)
            if match is None:
                title = key.split("\t", 1)[-1] if key.startswith("proc\t") else key.split("\t", 1)[0]
                raise RuntimeError(
                    f"Nie słychać „{title}”. Włącz w niej dźwięk i naciśnij Odśwież."
                )
            if match.serial <= 0:
                title = match.description.split(" · ", 1)[0]
                raise RuntimeError(f"„{title}” jest włączony, ale jeszcze nic nie odtwarza.")
            return str(match.serial), 2, f"aplikacja: {match.description}"
        if mode in ("mic", "microphone", "input"):
            src = self.config.audio_source or default_source_name()
            if not src:
                raise RuntimeError("Brak domyślnego mikrofonu (pactl get-default-source)")
            ch = source_channels(src)
            # nie używaj .monitor jako „mikrofonu”
            if src.endswith(".monitor"):
                raise RuntimeError(f"Wybrano monitor głośników jako mic: {src}")
            return src, ch, f"mikrofon: {src} ({ch} ch)"

        # playback — monitor wyjścia
        sink = self.config.audio_sink or default_sink_name()
        if not sink:
            raise RuntimeError("Brak domyślnego wyjścia audio (pactl get-default-sink)")
        # jeśli user wkleił już .monitor — OK
        if sink.endswith(".monitor"):
            mon = sink
            # spróbuj odczytać kanały z monitor source
            ch = source_channels(mon) or 2
        else:
            mon = monitor_of_sink(sink)
            ch = sink_channels(sink)
        return mon, ch, f"całe wyjście: {mon} ({ch} ch)"

    def start(self) -> tuple[bool, str]:
        if self.running:
            return True, "Audio react już działa"
        mode = (self.config.audio_mode or "playback").lower().strip()
        app_mode = mode in ("app", "application", "aplikacja")
        if app_mode and not shutil.which("pw-record"):
            return False, "Jedna aplikacja wymaga pw-record (pakiet pipewire)."
        if not app_mode and not shutil.which("gst-launch-1.0") and not shutil.which(
            "parec"
        ) and not shutil.which("pw-record"):
            return False, "Zainstaluj: gstreamer + gst-plugins-good (gst-launch-1.0) lub pipewire-tools"

        if app_mode and not str(getattr(self.config, "audio_app", "") or "").strip():
            return False, "Wybierz aplikację z listy. Musi akurat grać — potem Odśwież."

        try:
            dev, ch, desc = self._resolve_device()
        except Exception as e:
            if app_mode:
                # Aplikacja może zacząć grać za chwilę — wątek poczeka.
                dev, ch, desc = "", 2, "aplikacja: czekam aż zacznie grać"
            else:
                return False, str(e)

        self.capture_device = dev
        self._stop.clear()
        self.enabled = True
        self._smooth = {"level": 0.0, "bass": 0.0, "treble": 0.0}
        self._lp_zi = None
        self._hp_zi = None
        self.last_bass = 0.0
        self.last_treble = 0.0
        self.last_bass_rms = 0.0
        self.last_treble_rms = 0.0
        self._last_vp = (-1, -1)
        self._thread = threading.Thread(target=self._run, daemon=True, name="audio-react")
        self._thread.start()
        mode = self.config.audio_mode or "playback"
        msg = f"Audio react WŁĄCZONY [{mode}] → {desc}"
        self.controller.log(msg)
        return True, msg

    def stop(self, send_zero: bool = True) -> None:
        self.enabled = False
        self._stop.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            self._proc = None
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.5)
        self._thread = None
        self._smooth = {"level": 0.0, "bass": 0.0, "treble": 0.0}
        self._lp_zi = None
        self._hp_zi = None
        self.last_rms = 0.0
        self.last_vibrate = 0
        self.last_pump = 0
        self.last_bass = 0.0
        self.last_treble = 0.0
        self.last_bass_rms = 0.0
        self.last_treble_rms = 0.0
        if send_zero:
            try:
                self.controller.set_levels(vibrate=0, pump=0, immediate=True)
            except Exception:
                pass
        self.controller.log("Audio react wyłączony")

    def _run(self) -> None:
        try:
            mode = (self.config.audio_mode or "playback").lower().strip()
            if mode in ("app", "application", "aplikacja"):
                self.capture_backend = "pw-record"
                self._run_app()
                return
            # Kolejność: GStreamer (najpewniejszy monitor) → parec → pw-record
            if shutil.which("gst-launch-1.0"):
                self.capture_backend = "gstreamer"
                self._run_gstreamer()
            elif shutil.which("parec"):
                self.capture_backend = "parec"
                self._run_parec()
            elif shutil.which("pw-record"):
                self.capture_backend = "pw-record"
                self._run_pw_record()
            else:
                self.controller.log("Audio: brak narzędzia do przechwycenia dźwięku")
        except Exception:
            logger.exception("audio react crashed")
            self.controller.log("Audio react: błąd — zobacz log terminala")
        finally:
            self.enabled = False

    def _shape(self, rms: float, key: str, extra_gain: float = 1.0) -> float:
        """RMS/mix → 0..1 po gain, envelope, progu i krzywej."""
        gain = max(0.05, float(self.config.audio_gain)) * max(0.05, float(extra_gain))
        sens = max(0.05, float(self.config.audio_sensitivity))
        attack = float(self.config.audio_attack)
        release = float(self.config.audio_release)
        prev = float(self._smooth.get(key, 0.0))
        boosted = min(2.0, float(rms) * gain)
        if boosted > prev:
            smooth = prev * (1 - attack) + boosted * attack
        else:
            smooth = prev * (1 - release) + boosted * release
        self._smooth[key] = smooth

        x = max(0.0, min(1.0, smooth * sens))
        thr = float(self.config.audio_threshold)
        if x < thr:
            return 0.0
        x = (x - thr) / max(1e-6, 1.0 - thr)
        return float(math.pow(x, float(self.config.audio_curve)))

    def _to_vibrate(self, x: float) -> int:
        vmax = max(1, min(20, int(self.config.audio_max_vibrate)))
        return max(0, min(20, int(round(float(x) * vmax))))

    def _to_pump(self, x: float) -> int:
        pmax = max(0, min(20, int(self.config.audio_max_pump)))
        return max(0, min(pmax, int(round(float(x) * pmax))))

    def _map_level(self, rms: float) -> tuple[int, int]:
        """Cały sygnał (bez podziału pasm) — dawne zachowanie."""
        x = self._shape(rms, "level")
        vibrate = self._to_vibrate(x)
        pump = 0
        if self.config.audio_pump_enabled and vibrate > 0:
            pump = self._to_pump(x)
            if vibrate < 4:
                pump = 0
        return vibrate, pump

    def _route_on(self, attr: str, default: bool) -> bool:
        return bool(getattr(self.config, attr, default))

    def _map_bands(self, bass_mix: float, treble_mix: float) -> tuple[int, int, float, float]:
        """Pasma → wibracje / pump wg włączników (max, gdy oba pasma na ten sam suwak)."""
        bass_g = float(getattr(self.config, "audio_bass_gain", 1.0) or 1.0)
        treble_g = float(getattr(self.config, "audio_treble_gain", 1.8) or 1.8)
        bx = self._shape(bass_mix, "bass", extra_gain=bass_g)
        tx = self._shape(treble_mix, "treble", extra_gain=treble_g)
        bass_v = self._route_on("audio_bass_to_vibrate", True)
        bass_p = self._route_on("audio_bass_to_pump", False)
        treble_v = self._route_on("audio_treble_to_vibrate", False)
        treble_p = self._route_on("audio_treble_to_pump", True)
        vx = 0.0
        if bass_v:
            vx = max(vx, bx)
        if treble_v:
            vx = max(vx, tx)
        px = 0.0
        if bass_p:
            px = max(px, bx)
        if treble_p:
            px = max(px, tx)
        if bass_v or treble_v:
            vibrate = self._to_vibrate(vx)
        else:
            vibrate = int(getattr(self.controller.state, "vibrate", 0) or 0)
        pump_ok = bool(self.config.audio_pump_enabled) and (bass_p or treble_p)
        if pump_ok:
            pump = self._to_pump(px)
        else:
            pump = int(getattr(self.controller.state, "pump", 0) or 0)
        return vibrate, pump, bx, tx

    def _apply(self, vibrate: int, pump: int, rms: float) -> None:
        self.last_rms = rms
        self.last_vibrate = vibrate
        self.last_pump = pump
        for cb in list(self._on_level):
            try:
                cb(rms, vibrate, pump)
            except Exception:
                pass
        with self._lock:
            try:
                set_v = True
                set_p = bool(self.config.audio_pump_enabled)
                if bool(getattr(self.config, "audio_bands_enabled", False)):
                    set_v = self._route_on("audio_bass_to_vibrate", True) or self._route_on(
                        "audio_treble_to_vibrate", False
                    )
                    set_p = bool(self.config.audio_pump_enabled) and (
                        self._route_on("audio_bass_to_pump", False)
                        or self._route_on("audio_treble_to_pump", True)
                    )
                self.controller.set_levels(
                    vibrate=vibrate if set_v else self.controller.state.vibrate,
                    pump=pump if set_p else self.controller.state.pump,
                    time_sec=0,
                    immediate=True,
                )
            except Exception:
                logger.exception("audio apply levels")

    def _process_pcm_s16(self, raw: bytes, channels: int = 2, rate: int = 48000) -> None:
        mono = pcm_to_mono(raw, channels=channels)
        if mono.size < 16:
            return
        rms = float(np.sqrt(np.mean(mono * mono)))
        peak = float(np.max(np.abs(mono)))
        mix = mix_level(rms, peak)

        bands_on = bool(getattr(self.config, "audio_bands_enabled", True))
        if bands_on:
            bass_hz = float(getattr(self.config, "audio_bass_hz", 250.0) or 250.0)
            treble_hz = float(getattr(self.config, "audio_treble_hz", 2000.0) or 2000.0)
            bass_hz = max(40.0, min(600.0, bass_hz))
            treble_hz = max(bass_hz + 200.0, min(12000.0, treble_hz))
            b_rms, b_peak, _, self._lp_zi = band_metrics(
                mono, rate, 20.0, bass_hz, zi_hp=None, zi_lp=self._lp_zi
            )
            t_rms, t_peak, self._hp_zi, _ = band_metrics(
                mono, rate, treble_hz, float(rate) * 0.5, zi_hp=self._hp_zi, zi_lp=None
            )
            bass_mix = mix_level(b_rms, b_peak)
            treble_mix = mix_level(t_rms, t_peak)
            self.last_bass_rms = bass_mix
            self.last_treble_rms = treble_mix
            v, p, bx, tx = self._map_bands(bass_mix, treble_mix)
            self.last_bass = bx
            self.last_treble = tx
        else:
            self.last_bass_rms = 0.0
            self.last_treble_rms = 0.0
            self.last_bass = 0.0
            self.last_treble = 0.0
            v, p = self._map_level(mix)

        now = time.monotonic()
        if (v, p) != self._last_vp or (now - self._last_send) > 0.15:
            if (v, p) != self._last_vp or v > 0 or p > 0:
                self._apply(v, p, mix)
                self._last_vp = (v, p)
                self._last_send = now

    def _read_loop(self, channels: int, chunk: int, rate: int = 48000) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while not self._stop.is_set():
            proc = self._proc
            if proc is None or proc.stdout is None:
                break
            raw = proc.stdout.read(chunk)
            if not raw:
                break
            self._process_pcm_s16(raw, channels=channels, rate=rate)

    def _run_gstreamer(self) -> None:
        """pulsesrc na .monitor — działa z dźwiękiem Firefox/gier na Focusrite."""
        rate = 48000
        while not self._stop.is_set():
            try:
                dev, channels, desc = self._resolve_device()
            except Exception as e:
                self.controller.log(f"Audio: {e}")
                return

            # Zawsze downmix do stereo S16LE — stabilne i wystarczające do poziomu
            out_ch = 2
            chunk = int(rate * out_ch * 2 * 0.04)  # 40 ms
            # pulsesrc + audioconvert radzi sobie z 3ch monitor → 2ch
            pipeline = (
                f"pulsesrc device={dev} "
                f"! audioconvert ! audioresample "
                f"! audio/x-raw,format=S16LE,channels={out_ch},rate={rate} "
                f"! appsink name=sink sync=false emit-signals=false "
            )
            # fdsink prostszy przez gst-launch
            cmd = [
                "gst-launch-1.0",
                "-q",
                "pulsesrc",
                f"device={dev}",
                "!",
                "audioconvert",
                "!",
                "audioresample",
                "!",
                f"audio/x-raw,format=S16LE,channels={out_ch},rate={rate}",
                "!",
                "fdsink",
                "fd=1",
            ]
            self.controller.log(f"Audio: GStreamer → {desc}")
            self.capture_device = dev
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=chunk * 8,
                )
                # wątek diagnostyki stderr
                def _drain_err():
                    try:
                        if self._proc and self._proc.stderr:
                            err = self._proc.stderr.read()
                            if err and not self._stop.is_set():
                                text = err.decode("utf-8", errors="replace")[:300]
                                if text.strip():
                                    logger.warning("gst stderr: %s", text)
                                    self.controller.log(f"Audio gst: {text.strip()[:120]}")
                    except Exception:
                        pass

                threading.Thread(target=_drain_err, daemon=True).start()
                self._read_loop(out_ch, chunk, rate=rate)
            finally:
                proc = self._proc
                self._proc = None
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=1)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            if self._stop.is_set():
                break
            time.sleep(0.4)

    def _run_parec(self) -> None:
        rate = 48000
        while not self._stop.is_set():
            try:
                dev, channels, desc = self._resolve_device()
            except Exception as e:
                self.controller.log(f"Audio: {e}")
                return
            # downmix: prosimy o 2 ch jeśli się da, inaczej natywne
            for ch_try in (2, channels):
                chunk = int(rate * ch_try * 2 * 0.04)
                cmd = [
                    "parec",
                    f"--device={dev}",
                    "--format=s16le",
                    f"--rate={rate}",
                    f"--channels={ch_try}",
                    "--latency-msec=40",
                    "--raw",
                ]
                self.controller.log(f"Audio: parec → {desc} (ch={ch_try})")
                try:
                    self._proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=chunk * 8
                    )
                    self._read_loop(ch_try, chunk, rate=rate)
                finally:
                    proc = self._proc
                    self._proc = None
                    if proc is not None:
                        try:
                            proc.terminate()
                        except Exception:
                            pass
                if self._stop.is_set():
                    return
            time.sleep(0.5)

    def _run_app(self) -> None:
        """Podsłuch jednego strumienia. Gra idzie dalej na głośniki."""
        rate = 48000
        out_ch = 2
        chunk = int(rate * out_ch * 2 * 0.04)
        announced = ""
        while not self._stop.is_set():
            try:
                serial, _channels, desc = self._resolve_device()
            except Exception as e:
                if announced != str(e):
                    announced = str(e)
                    self.controller.log(f"Audio: {e}")
                if self._stop.wait(1.0):
                    break
                continue
            if announced != desc:
                announced = desc
                self.controller.log(f"Audio: {desc} — reszta dźwięku nie rusza zabawki")
            cmd = [
                "pw-record",
                "-a",
                "--target",
                str(serial),
                "--rate",
                str(rate),
                "--channels",
                str(out_ch),
                "--format",
                "s16",
                "--latency",
                "40ms",
                "-",
            ]
            self.capture_device = str(serial)
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=chunk * 8,
                )
                self._read_loop(out_ch, chunk, rate=rate)
            finally:
                proc = self._proc
                self._proc = None
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            if self._stop.is_set():
                break
            time.sleep(0.4)

    def _run_pw_record(self) -> None:
        """Fallback — na niektórych kartach (Focusrite) bywa prawie cichy."""
        rate = 48000
        while not self._stop.is_set():
            try:
                dev, channels, desc = self._resolve_device()
            except Exception as e:
                self.controller.log(f"Audio: {e}")
                return
            # pw-record lubi nazwę sinka bez .monitor albo z
            target = dev
            if target.endswith(".monitor"):
                target = target[: -len(".monitor")]
            out_ch = min(channels, 2) if channels else 2
            chunk = int(rate * out_ch * 2 * 0.04)
            cmd = [
                "pw-record",
                "-a",
                "--target",
                target,
                "--rate",
                str(rate),
                "--channels",
                str(out_ch),
                "--format",
                "s16",
                "--latency",
                "40ms",
                "-",
            ]
            self.controller.log(f"Audio: pw-record → {desc} (może być słabe na Focusrite)")
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=chunk * 8
                )
                self._read_loop(out_ch, chunk, rate=rate)
            finally:
                proc = self._proc
                self._proc = None
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            if self._stop.is_set():
                break
            time.sleep(0.5)
