#!/usr/bin/env python3
"""Seamless equirectangular glass textures for the organic orb mesh.

Sphere-sampled 3D noise → no U-seam, no pole pinch. 1024×512, RGBA.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
W, H = 1024, 512


def fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def hash3(ix: np.ndarray, iy: np.ndarray, iz: np.ndarray) -> np.ndarray:
    n = (
        ix.astype(np.uint64) * np.uint64(374761393)
        + iy.astype(np.uint64) * np.uint64(668265263)
        + iz.astype(np.uint64) * np.uint64(1274126177)
    )
    n ^= n >> np.uint64(13)
    n *= np.uint64(1274126177)
    return (n & np.uint64(0xFFFFFFFF)).astype(np.float64) / 4294967295.0


def value_noise3(p: np.ndarray) -> np.ndarray:
    i0 = np.floor(p)
    f = p - i0
    u = fade(f)

    def corner(dx: int, dy: int, dz: int) -> np.ndarray:
        return hash3(i0[..., 0] + dx, i0[..., 1] + dy, i0[..., 2] + dz)

    n000 = corner(0, 0, 0)
    n100 = corner(1, 0, 0)
    n010 = corner(0, 1, 0)
    n110 = corner(1, 1, 0)
    n001 = corner(0, 0, 1)
    n101 = corner(1, 0, 1)
    n011 = corner(0, 1, 1)
    n111 = corner(1, 1, 1)
    nx00 = n000 * (1 - u[..., 0]) + n100 * u[..., 0]
    nx10 = n010 * (1 - u[..., 0]) + n110 * u[..., 0]
    nx01 = n001 * (1 - u[..., 0]) + n101 * u[..., 0]
    nx11 = n011 * (1 - u[..., 0]) + n111 * u[..., 0]
    nxy0 = nx00 * (1 - u[..., 1]) + nx10 * u[..., 1]
    nxy1 = nx01 * (1 - u[..., 1]) + nx11 * u[..., 1]
    return nxy0 * (1 - u[..., 2]) + nxy1 * u[..., 2]


def fbm(p: np.ndarray, octaves: int = 5, lac: float = 2.05, gain: float = 0.52) -> np.ndarray:
    v = np.zeros(p.shape[:-1], dtype=np.float64)
    a = 0.5
    f = 1.0
    s = 0.0
    for _ in range(octaves):
        v += a * value_noise3(p * f)
        s += a
        a *= gain
        f *= lac
    return v / max(s, 1e-6)


def sphere_dirs(w: int, h: int) -> np.ndarray:
    x = (np.arange(w) + 0.5) / w
    y = (np.arange(h) + 0.5) / h
    lon = x * 2.0 * np.pi
    lat = (0.5 - y[:, None]) * np.pi
    Lon = lon[None, :]
    cl, sl = np.cos(lat), np.sin(lat)
    dx = cl * np.cos(Lon)
    dy = cl * np.sin(Lon)
    dz = sl * np.ones_like(Lon)
    return np.stack((dx, dy, dz), axis=-1)


def iridescence(thick: np.ndarray) -> np.ndarray:
    """Thin-film-ish RGB from optical thickness."""
    phase = thick * 11.5
    r = 0.5 + 0.5 * np.sin(phase)
    g = 0.5 + 0.5 * np.sin(phase + 2.1)
    b = 0.5 + 0.5 * np.sin(phase + 4.2)
    return np.stack((r, g, b), axis=-1)


def save_rgba(path: Path, rgb: np.ndarray, alpha: np.ndarray) -> None:
    rgb = np.clip(rgb, 0, 1)
    a = np.clip(alpha, 0, 1)
    im = np.dstack((rgb, a))
    Image.fromarray((im * 255).astype(np.uint8), "RGBA").save(path)
    print("wrote", path, rgb.shape[1], "x", rgb.shape[0])


def tex_glass(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n1 = fbm(d * 1.15 + 0.2, 4)
    n2 = fbm(d * 2.2 + 4.1, 4)
    warp = d + np.stack((n1, n2, n1 * 0.35), axis=-1) * 0.45
    flow = fbm(warp * 1.05, 4)
    n3 = fbm(d * 4.0 + 9.0, 3)

    pink = np.array([0.92, 0.20, 0.48])
    mag = np.array([0.70, 0.08, 0.34])
    cyan = np.array([0.06, 0.58, 0.92])
    aqua = np.array([0.40, 0.88, 0.96])
    clear = np.array([0.78, 0.90, 0.96])

    pk = np.clip((flow - 0.42) * 2.8, 0, 1) ** 1.15
    cy = np.clip((0.55 - flow) * 2.6, 0, 1) ** 1.15
    cl = np.clip(0.55 - 0.35 * (pk + cy), 0, 1)
    s = pk + cy + cl + 1e-6
    pk, cy, cl = pk / s, cy / s, cl / s
    rgb = (
        pk[..., None] * (pink * 0.45 + mag * 0.55)
        + cy[..., None] * (cyan * 0.60 + aqua * 0.40)
        + cl[..., None] * clear
    )
    # soft inner glow blobs (not contour lines)
    glow = np.clip(n2 - 0.52, 0, 1) ** 1.4
    rgb = rgb + glow[..., None] * (pk[..., None] * pink + cy[..., None] * aqua) * 0.35
    thick = 0.30 + 0.70 * n1
    ir = iridescence(thick)
    film = 0.10 + 0.16 * n3 + 0.12 * (1.0 - np.abs(d[..., 2]))
    rgb = rgb * (1.0 - film[..., None] * 0.35) + ir * film[..., None] * 0.40
    spec = np.clip(d[..., 0] * 0.30 + d[..., 2] * 0.50 + 0.38, 0, 1) ** 9
    rgb = rgb + spec[..., None] * np.array([0.95, 0.98, 1.0]) * 0.38
    rgb = np.clip(rgb, 0, 1)
    alpha = 0.48 + 0.22 * (pk + cy) + 0.14 * glow + 0.10 * spec
    return rgb, alpha


def tex_mass(d: np.ndarray, kind: str) -> tuple[np.ndarray, np.ndarray]:
    n1 = fbm(d * 1.6 + (2.0 if kind == "pink" else 7.0), 5)
    n2 = fbm(d * 3.4 + 3.5, 4)
    n3 = fbm(d * 8.0 + 1.2, 3)
    if kind == "pink":
        deep = np.array([0.72, 0.08, 0.32])
        mid = np.array([0.95, 0.28, 0.52])
        hi = np.array([1.00, 0.62, 0.78])
    else:
        deep = np.array([0.04, 0.32, 0.62])
        mid = np.array([0.10, 0.62, 0.94])
        hi = np.array([0.55, 0.92, 1.00])
    t = np.clip(n1 * 1.12, 0, 1)
    rgb = (1 - t)[..., None] * deep + t[..., None] * mid
    glow = np.clip((n2 - 0.48) * 1.8, 0, 1) ** 1.6
    rgb = rgb * (1.0 - 0.20 * glow[..., None]) + hi * glow[..., None] * 0.50
    spec = np.clip(0.4 + 0.6 * d[..., 2], 0, 1) ** 10
    rgb = rgb + spec[..., None] * 0.28
    rgb += (n3 - 0.5)[..., None] * 0.04
    rgb = np.clip(rgb, 0, 1)
    alpha = 0.90 + 0.08 * glow
    return rgb, alpha


def tex_core(d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n1 = fbm(d * 2.2, 4)
    r = np.clip(1.0 - 0.35 * (1.0 - abs(d[..., 2])), 0, 1)
    deep = np.array([0.95, 0.35, 0.55])
    hot = np.array([1.00, 0.82, 0.90])
    t = np.clip(0.35 + 0.65 * n1, 0, 1) * r
    rgb = (1 - t)[..., None] * deep + t[..., None] * hot
    spec = np.clip(0.5 + 0.5 * d[..., 2], 0, 1) ** 8
    rgb = rgb + spec[..., None] * 0.5
    return rgb, np.ones(d.shape[:2])


def wrap_preview(rgb: np.ndarray, size: int = 640) -> np.ndarray:
    """Orthographic sphere with the equirect texture."""
    img = np.full((size, size, 3), 0.10)
    yy, xx = np.mgrid[0:size, 0:size]
    u = (xx + 0.5) / size * 2.0 - 1.0
    v = 1.0 - (yy + 0.5) / size * 2.0
    r2 = u * u + v * v
    hit = r2 <= 1.0
    z = np.zeros_like(u)
    z[hit] = np.sqrt(1.0 - r2[hit])
    # u=right, v=up, z=toward camera. Rotate around up so the U-seam is visible.
    ang = 0.40
    c, s = math.cos(ang), math.sin(ang)
    xr = u * c + z * s
    zr = -u * s + z * c
    # texture dirs: dx, dy equatorial; dz up
    lon = np.mod(np.arctan2(zr, xr) + 2.0 * np.pi, 2.0 * np.pi)
    lat = np.arcsin(np.clip(v, -1.0, 1.0))
    tx = (lon / (2.0 * np.pi) * (rgb.shape[1] - 1)).astype(np.int32)
    ty = ((0.5 - lat / np.pi) * (rgb.shape[0] - 1)).astype(np.int32)
    tx = np.clip(tx, 0, rgb.shape[1] - 1)
    ty = np.clip(ty, 0, rgb.shape[0] - 1)
    sampled = rgb[ty, tx]
    light = np.clip(-0.25 * xr + 0.20 * v + 0.72 * zr, 0, 1)
    shaded = sampled * (0.32 + 0.68 * light[..., None])
    spec = light ** 18
    shaded = np.clip(shaded + spec[..., None] * 0.42, 0, 1)
    img[hit] = shaded[hit]
    return img


def seam_strip(rgb: np.ndarray, band: int = 80) -> np.ndarray:
    """Left|right join, to see if U wraps."""
    left = rgb[:, :band]
    right = rgb[:, -band:]
    return np.concatenate((right, left), axis=1)


def main() -> None:
    d = sphere_dirs(W, H)
    jobs = [
        ("orb_glass.png", *tex_glass(d)),
        ("orb_pink.png", *tex_mass(d, "pink")),
        ("orb_cyan.png", *tex_mass(d, "cyan")),
        ("orb_core.png", *tex_core(d)),
    ]
    previews = []
    for name, rgb, alpha in jobs:
        rgb = np.clip(rgb, 0, 1)
        print(f"  {name} rgb {rgb.min():.3f}..{rgb.max():.3f}  a {alpha.min():.3f}..{alpha.max():.3f}")
        # RGB for SL (face alpha slider). RGBA also written with _a suffix.
        Image.fromarray((rgb * 255).astype(np.uint8), "RGB").save(HERE / name)
        print("wrote", HERE / name)
        previews.append(wrap_preview(rgb))

    # 2×2 wrap preview
    size = previews[0].shape[0]
    sheet = np.full((size * 2 + 24, size * 2 + 24, 3), 0.08)
    for i, p in enumerate(previews):
        r, c = divmod(i, 2)
        y, x = 8 + r * (size + 8), 8 + c * (size + 8)
        sheet[y : y + size, x : x + size] = p
    Image.fromarray((np.clip(sheet, 0, 1) * 255).astype(np.uint8), "RGB").save(
        HERE / "orb_textures_preview.png"
    )
    print("wrote", HERE / "orb_textures_preview.png")




if __name__ == "__main__":
    main()
