#!/usr/bin/env python3
"""Equirectangular orb textures for an SL PRIM_TYPE_SPHERE."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def make_orb(
    path: Path,
    albedo: tuple[float, float, float],
    dark: tuple[float, float, float],
    light: tuple[float, float, float],
) -> None:
    w, h = 1024, 512
    im = Image.new("RGB", (w, h))
    px = im.load()
    # light from upper-left-front
    lx, ly, lz = -0.45, 0.72, 0.53
    ln = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / ln, ly / ln, lz / ln
    for y in range(h):
        lat = (0.5 - (y + 0.5) / h) * math.pi
        cl, sl = math.cos(lat), math.sin(lat)
        for x in range(w):
            lon = ((x + 0.5) / w) * 2.0 * math.pi
            nx = cl * math.cos(lon)
            ny = sl
            nz = cl * math.sin(lon)
            ndot = _clamp(nx * lx + ny * ly + nz * lz)
            wrap = _clamp(ndot * 0.55 + 0.45)
            spec = ndot**18
            r = dark[0] + (albedo[0] - dark[0]) * wrap + light[0] * spec
            g = dark[1] + (albedo[1] - dark[1]) * wrap + light[1] * spec
            b = dark[2] + (albedo[2] - dark[2]) * wrap + light[2] * spec
            # faint equator sheen
            eq = math.exp(-((lat * 2.2) ** 2)) * 0.08
            r += eq
            g += eq * 0.6
            b += eq * 0.7
            px[x, y] = (
                int(255 * _clamp(r)),
                int(255 * _clamp(g)),
                int(255 * _clamp(b)),
            )
    im.save(path, "PNG")
    print("wrote", path)


def main() -> None:
    here = Path(__file__).resolve().parent
    make_orb(
        here / "lovense_offline.png",
        albedo=(0.32, 0.28, 0.34),
        dark=(0.10, 0.09, 0.12),
        light=(0.70, 0.68, 0.74),
    )
    make_orb(
        here / "lovense_online.png",
        albedo=(0.90, 0.28, 0.52),
        dark=(0.38, 0.05, 0.18),
        light=(1.0, 0.92, 0.96),
    )
    make_orb(
        here / "lovense_active.png",
        albedo=(1.00, 0.18, 0.42),
        dark=(0.48, 0.02, 0.14),
        light=(1.0, 1.0, 1.0),
    )


if __name__ == "__main__":
    main()
