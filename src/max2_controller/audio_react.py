"""
Reakcja zabawki na dźwięk.

Tryby:
  playback  — dźwięk z aplikacji (Firefox, gry…) = monitor wyjścia (głośniki)
  microphone — mikrofon / wejście

Pasma (domyślnie WŁ): IIR — bas (kick) → Vibrate, treble (hi-hat) → 2. funkcja.

Na PipeWire + Focusrite: pw-record/parec często dają ciszę na monitorze.
GStreamer `pulsesrc device=<sink>.monitor` działa poprawnie — używamy go jako domyślnego.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Callable

import numpy as np

if TYPE_CHECKING:
    from max2_controller.config import AppConfig
    from max2_controller.controller import Max2Controller

logger = logging.getLogger(__name__)

LevelCallback = Callable[[float, int, int], None]


def default_sink_name() -> str | None:
    try:
        out = subprocess.check_output(["pactl", "get-default-sink"], text=True, timeout=2)
        return out.strip() or None
    except Exception:
        return None


def default_source_name() -> str | None:
    try:
        out = subprocess.check_output(["pactl", "get-default-source"], text=True, timeout=2)
        return out.strip() or None
    except Exception:
        return None


def list_playback_sinks() -> list[str]:
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True, timeout=3)
        sinks = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                sinks.append(parts[1])
        return sinks
    except Exception:
        return []


def list_input_sources() -> list[str]:
    """Źródła wejściowe (bez .monitor — te to echo głośników)."""
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True, timeout=3)
        srcs = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            name = parts[1]
            if name.endswith(".monitor"):
                continue
            srcs.append(name)
        return srcs
    except Exception:
        return []


def sink_channels(sink: str) -> int:
    """Liczba kanałów sinka (Focusrite surround 2.1 = 3)."""
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
        return mon, ch, f"aplikacje/głośniki: {mon} ({ch} ch)"

    def start(self) -> tuple[bool, str]:
        if self.running:
            return True, "Audio react już działa"
        if not shutil.which("gst-launch-1.0") and not shutil.which("parec") and not shutil.which(
            "pw-record"
        ):
            return False, "Zainstaluj: gstreamer + gst-plugins-good (gst-launch-1.0) lub pipewire-tools"

        try:
            dev, ch, desc = self._resolve_device()
        except Exception as e:
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
