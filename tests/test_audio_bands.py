"""FFT bass/treble — kick vs hi-hat bez GStreamera."""

from __future__ import annotations

import math
import struct

import numpy as np

from max2_controller.audio_react import (
    AudioReactor,
    band_metrics,
    mix_level,
    pcm_to_mono,
)
from max2_controller.config import AppConfig
from max2_controller.models import CommandResult


RATE = 48000
N = 1920  # 40 ms jak pętla audio


def _sine(freq: float, n: int = N, rate: int = RATE, amp: float = 0.8) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / float(rate)
    return (amp * np.sin(2.0 * np.pi * float(freq) * t)).astype(np.float32)


def test_pcm_to_mono_stereo_mean() -> None:
    # L=1000, R=-1000 → mono 0
    frames = []
    for _ in range(8):
        frames.append(struct.pack("<hh", 1000, -1000))
    mono = pcm_to_mono(b"".join(frames), channels=2)
    assert mono.size == 8
    assert float(np.max(np.abs(mono))) < 1e-4


def test_kick_is_bass_not_treble() -> None:
    kick = _sine(80.0, n=RATE // 5)  # 200 ms, IIR zdąży ustać
    b_rms, _, _, _ = band_metrics(kick, RATE, 20.0, 250.0)
    t_rms, _, _, _ = band_metrics(kick, RATE, 2000.0, RATE * 0.5)
    assert b_rms > 0.2
    assert b_rms > t_rms * 8


def test_hat_is_treble_not_bass() -> None:
    hat = _sine(6000.0, n=RATE // 5)
    b_rms, _, _, _ = band_metrics(hat, RATE, 20.0, 250.0)
    t_rms, _, _, _ = band_metrics(hat, RATE, 2000.0, RATE * 0.5)
    assert t_rms > 0.2
    assert t_rms > b_rms * 8


def test_mid_is_weaker_than_true_bands() -> None:
    mid = _sine(1000.0, n=RATE // 5)
    hat = _sine(6000.0, n=RATE // 5)
    kick = _sine(80.0, n=RATE // 5)
    b_mid, _, _, _ = band_metrics(mid, RATE, 20.0, 250.0)
    t_mid, _, _, _ = band_metrics(mid, RATE, 2000.0, RATE * 0.5)
    b_kick, _, _, _ = band_metrics(kick, RATE, 20.0, 250.0)
    t_hat, _, _, _ = band_metrics(hat, RATE, 2000.0, RATE * 0.5)
    assert b_mid < b_kick * 0.25
    assert t_mid < t_hat * 0.5


class _DummyCtrl:
    def __init__(self) -> None:
        self.state = type("S", (), {"pump": 0, "vibrate": 0})()
        self.applied: list[dict] = []

    def log(self, msg: str) -> None:
        pass

    def set_levels(self, **kwargs) -> CommandResult:
        self.applied.append(kwargs)
        return CommandResult(ok=True, message="ok")


def _reactor(bands: bool = True) -> tuple[AudioReactor, _DummyCtrl]:
    cfg = AppConfig()
    cfg.audio_bands_enabled = bands
    cfg.audio_gain = 8.0
    cfg.audio_sensitivity = 1.4
    cfg.audio_threshold = 0.01
    cfg.audio_curve = 0.65
    cfg.audio_attack = 1.0  # bez envelope — łatwiejsze asercje
    cfg.audio_release = 1.0
    cfg.audio_max_vibrate = 20
    cfg.audio_max_pump = 3
    cfg.audio_pump_enabled = True
    cfg.audio_bass_gain = 1.0
    cfg.audio_treble_gain = 1.8
    ctrl = _DummyCtrl()
    ar = AudioReactor(ctrl, cfg)
    return ar, ctrl


def _s16_stereo(mono: np.ndarray) -> bytes:
    x = np.clip(mono, -1.0, 1.0)
    s = (x * 32767.0).astype(np.int16)
    stereo = np.empty((s.size, 2), dtype=np.int16)
    stereo[:, 0] = s
    stereo[:, 1] = s
    return stereo.tobytes()


def _feed_sine(ar: AudioReactor, freq: float, amp: float = 0.9, chunks: int = 8) -> None:
    """Ciągły sinus (faza przez chunki) — IIR i envelope jak na żywo."""
    t = np.arange(chunks * N, dtype=np.float32) / float(RATE)
    mono = (amp * np.sin(2.0 * np.pi * float(freq) * t)).astype(np.float32)
    raw = _s16_stereo(mono)
    frame = N * 4  # stereo s16
    for i in range(chunks):
        ar._process_pcm_s16(raw[i * frame : (i + 1) * frame], channels=2, rate=RATE)


def test_kick_drives_vibrate_not_pump() -> None:
    ar, ctrl = _reactor(bands=True)
    _feed_sine(ar, 80.0)
    assert ar.last_vibrate >= 8
    assert ar.last_pump == 0
    assert ar.last_bass > ar.last_treble
    assert ctrl.applied
    assert int(ctrl.applied[-1]["vibrate"]) == ar.last_vibrate


def test_hat_drives_pump_not_vibrate() -> None:
    ar, ctrl = _reactor(bands=True)
    _feed_sine(ar, 6000.0)
    assert ar.last_pump >= 1
    assert ar.last_vibrate == 0
    assert ar.last_treble > ar.last_bass
    assert int(ctrl.applied[-1]["pump"]) == ar.last_pump


def test_kick_can_drive_pump_instead_of_vibrate() -> None:
    ar, _ctrl = _reactor(bands=True)
    ar.config.audio_bass_to_vibrate = False
    ar.config.audio_bass_to_pump = True
    ar.config.audio_treble_to_vibrate = False
    ar.config.audio_treble_to_pump = False
    _feed_sine(ar, 80.0)
    assert ar.last_pump >= 1
    assert ar.last_vibrate == 0


def test_hat_can_drive_vibrate_instead_of_pump() -> None:
    ar, _ctrl = _reactor(bands=True)
    ar.config.audio_bass_to_vibrate = False
    ar.config.audio_bass_to_pump = False
    ar.config.audio_treble_to_vibrate = True
    ar.config.audio_treble_to_pump = False
    _feed_sine(ar, 6000.0)
    assert ar.last_vibrate >= 8
    assert ar.last_pump == 0


def test_kick_can_drive_both_when_both_routes_on() -> None:
    ar, _ctrl = _reactor(bands=True)
    ar.config.audio_bass_to_vibrate = True
    ar.config.audio_bass_to_pump = True
    ar.config.audio_treble_to_vibrate = False
    ar.config.audio_treble_to_pump = False
    _feed_sine(ar, 80.0)
    assert ar.last_vibrate >= 8
    assert ar.last_pump >= 1


def test_bands_off_uses_full_level_for_both() -> None:
    ar, _ctrl = _reactor(bands=False)
    _feed_sine(ar, 80.0, chunks=3)
    # bez podziału: głośny kick podnosi i V, i (przy V>=4) pump
    assert ar.last_vibrate >= 8
    assert ar.last_pump >= 1


def test_mix_level_between_rms_and_peak() -> None:
    m = mix_level(0.2, 1.0)
    assert math.isclose(m, 0.65 * 0.2 + 0.35 * 1.0)
