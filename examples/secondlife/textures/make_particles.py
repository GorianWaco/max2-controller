#!/usr/bin/env python3
"""Particle sprites for SL llParticleSystem (white + alpha, script tints them)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent / "particles"
SIZE = 128


def save(name: str, alpha: np.ndarray) -> None:
    a = np.clip(alpha, 0, 1)
    rgb = np.ones((SIZE, SIZE, 3), dtype=np.float64)
    im = np.dstack((rgb, a))
    path = OUT / name
    Image.fromarray((im * 255).astype(np.uint8), "RGBA").save(path)
    print("wrote", path)


def glow() -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    cx = cy = (SIZE - 1) / 2.0
    r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / (SIZE * 0.48)
    return np.exp(-(r**2) * 4.2)


def star() -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    cx = cy = (SIZE - 1) / 2.0
    dx, dy = (x - cx) / (SIZE * 0.5), (y - cy) / (SIZE * 0.5)
    r = np.sqrt(dx * dx + dy * dy) + 1e-6
    ang = np.arctan2(dy, dx)
    spike = np.abs(np.cos(2.0 * ang)) ** 3.5
    core = np.exp(-(r**2) * 18.0)
    arms = np.clip(spike * np.exp(-r * 3.2), 0, 1)
    return np.clip(core * 0.9 + arms * 0.85, 0, 1)


def spark() -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    cx = cy = (SIZE - 1) / 2.0
    dx, dy = (x - cx) / (SIZE * 0.5), (y - cy) / (SIZE * 0.5)
    r = np.sqrt(dx * dx + dy * dy) + 1e-6
    ang = np.arctan2(dy, dx)
    a = np.exp(-(r**2) * 10.0)
    a = np.maximum(a, np.abs(np.cos(ang)) ** 12 * np.exp(-r * 4.5))
    a = np.maximum(a, np.abs(np.sin(ang)) ** 12 * np.exp(-r * 4.5))
    a = np.maximum(a, np.abs(np.cos(2.0 * ang)) ** 8 * np.exp(-r * 5.5) * 0.55)
    return np.clip(a, 0, 1)


def dot() -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    cx = cy = (SIZE - 1) / 2.0
    r = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / (SIZE * 0.5)
    core = np.exp(-(r**2) * 28.0)
    halo = np.exp(-(r**2) * 6.0) * 0.45
    return np.clip(core + halo, 0, 1)


def flake() -> np.ndarray:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    cx = cy = (SIZE - 1) / 2.0
    dx, dy = (x - cx) / (SIZE * 0.5), (y - cy) / (SIZE * 0.5)
    r = np.sqrt(dx * dx + dy * dy) + 1e-6
    ang = np.arctan2(dy, dx)
    hexn = np.abs(np.cos(3.0 * ang)) ** 2.2
    body = np.clip((0.55 - r) / 0.55, 0, 1) ** 1.4
    rays = hexn * np.exp(-r * 3.8)
    core = np.exp(-(r**2) * 22.0)
    return np.clip(body * 0.35 + rays * 0.8 + core, 0, 1)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save("p_glow.png", glow())
    save("p_star.png", star())
    save("p_spark.png", spark())
    save("p_dot.png", dot())
    save("p_flake.png", flake())


if __name__ == "__main__":
    main()
