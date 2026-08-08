"""
Reakcja zabawki na dźwięk.

Tryby:
  playback  — dźwięk z aplikacji (Firefox, gry…) = monitor wyjścia (głośniki)
  microphone — mikrofon / wejście

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


class AudioReactor:
    """Wątek: dźwięk → poziomy Vibrate/Pump."""

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
        self._smooth = 0.0
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
        self._smooth = 0.0
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
        self._smooth = 0.0
        self.last_rms = 0.0
        self.last_vibrate = 0
        self.last_pump = 0
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

    def _map_level(self, rms: float) -> tuple[int, int]:
        gain = max(0.05, float(self.config.audio_gain))
        sens = max(0.05, float(self.config.audio_sensitivity))
        attack = float(self.config.audio_attack)
        release = float(self.config.audio_release)
        boosted = min(2.0, rms * gain)
        if boosted > self._smooth:
            self._smooth = self._smooth * (1 - attack) + boosted * attack
        else:
            self._smooth = self._smooth * (1 - release) + boosted * release

        x = max(0.0, min(1.0, self._smooth * sens))
        thr = float(self.config.audio_threshold)
        if x < thr:
            x = 0.0
        else:
            x = (x - thr) / max(1e-6, 1.0 - thr)
            x = math.pow(x, float(self.config.audio_curve))

        vmax = max(1, min(20, int(self.config.audio_max_vibrate)))
        vibrate = max(0, min(20, int(round(x * vmax))))

        pump = 0
        if self.config.audio_pump_enabled and vibrate > 0:
            pump = max(0, min(3, int(round(x * float(self.config.audio_max_pump)))))
            if vibrate < 4:
                pump = 0
        return vibrate, pump

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
                self.controller.set_levels(
                    vibrate=vibrate,
                    pump=pump if self.config.audio_pump_enabled else self.controller.state.pump,
                    time_sec=0,
                    immediate=True,
                )
            except Exception:
                logger.exception("audio apply levels")

    def _process_pcm_s16(self, raw: bytes, channels: int = 2) -> None:
        if len(raw) < channels * 2:
            return
        arr = np.frombuffer(raw, dtype=np.int16)
        if arr.size == 0:
            return
        f = arr.astype(np.float32) / 32768.0
        if channels > 1 and f.size >= channels:
            usable = (f.size // channels) * channels
            f = f[:usable].reshape(-1, channels)
            # bierzemy max z kanałów (L/R) — LFE bywa ciche
            if f.shape[1] >= 2:
                mono = np.max(np.abs(f[:, : min(2, f.shape[1])]), axis=1)
                # RMS z głośniejszych kanałów stereo
                stereo = f[:, :2].mean(axis=1)
                rms = float(np.sqrt(np.mean(stereo * stereo)))
                peak = float(np.max(mono))
            else:
                mono = f[:, 0]
                rms = float(np.sqrt(np.mean(mono * mono)))
                peak = float(np.max(np.abs(mono)))
        else:
            rms = float(np.sqrt(np.mean(f * f)))
            peak = float(np.max(np.abs(f)))

        mix = 0.65 * rms + 0.35 * peak
        v, p = self._map_level(mix)
        now = time.monotonic()
        if (v, p) != self._last_vp or (now - self._last_send) > 0.15:
            if (v, p) != self._last_vp or v > 0:
                self._apply(v, p, mix)
                self._last_vp = (v, p)
                self._last_send = now

    def _read_loop(self, channels: int, chunk: int) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while not self._stop.is_set():
            proc = self._proc
            if proc is None or proc.stdout is None:
                break
            raw = proc.stdout.read(chunk)
            if not raw:
                break
            self._process_pcm_s16(raw, channels=channels)

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
                self._read_loop(out_ch, chunk)
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
                    self._read_loop(ch_try, chunk)
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
                self._read_loop(out_ch, chunk)
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
