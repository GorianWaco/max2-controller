#!/usr/bin/env python3
"""Ground tip-jar vessel for Second Life (COLLADA 1.4.1).

Molten-glass offering bowl: clear overlapping lobes, magenta/cyan nectar
pooled in the well, glowing pearl. Sits on the floor (origin at the foot).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

from make_controller_dae import (  # noqa: E402
    MAT_ALPHA,
    MAT_COL,
    MAT_EMIT,
    Mesh,
    _n,
    organic_ellipsoid,
    rot_x,
    rot_y,
    rot_z,
    tr,
    write_dae,
)

OUT_DAE = Path(__file__).with_name("LovenseTipJar.dae")
OUT_PREVIEW = Path(__file__).with_name("LovenseTipJar_preview.png")


def resample_poly(pts: np.ndarray, n: int) -> np.ndarray:
    d = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(d)])
    total = float(s[-1])
    if total < 1e-9:
        return np.repeat(pts[:1], n, axis=0)
    s = s / total
    t = np.linspace(0.0, 1.0, n)
    out = np.empty((n, 2), dtype=np.float64)
    out[:, 0] = np.interp(t, s, pts[:, 0])
    out[:, 1] = np.interp(t, s, pts[:, 1])
    return out


def smoothstep(lo: float, hi: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lathe(
    profile_rz: np.ndarray,
    nu: int,
    material: str,
    name: str,
    warp: float = 0.0,
    k: float = 0.0,
) -> Mesh:
    """Solid of revolution. profile_rz: (nv, 2) as (radius, z). Origin at foot."""
    nv = len(profile_rz)
    us = np.linspace(0.0, 1.0, nu + 1)
    vs = np.linspace(0.0, 1.0, nv)
    U, V = np.meshgrid(us, vs, indexing="ij")
    th = 2.0 * np.pi * U
    r0 = np.interp(V.ravel(), vs, profile_rz[:, 0]).reshape(U.shape)
    z0 = np.interp(V.ravel(), vs, profile_rz[:, 1]).reshape(U.shape)
    # Handmade glass: warp walls and rim, keep the foot sitting flat.
    s = smoothstep(0.045, 0.16, z0)
    w = (
        1.0
        + s * warp * 0.62 * np.sin(3.0 * th + k + 2.4 * z0)
        + s * warp * 0.38 * np.cos(5.0 * th - 1.6 * z0 + 0.4 * k)
        + s * warp * 0.22 * np.sin(2.0 * th + 4.1 * z0)
        + s * warp * 0.14 * np.cos(7.0 * th + 0.8 * k)
    )
    r = r0 * w
    z = z0 + s * warp * 0.016 * np.sin(4.0 * th + 3.0 * z0 + k)
    z = np.maximum(z, 0.0)
    x = r * np.cos(th)
    y = r * np.sin(th)
    pts = np.stack((x, y, z), axis=-1)
    uvs = np.stack((U, 1.0 - V), axis=-1)
    m = Mesh(name, material)
    m.add_grid(pts, uvs)
    return m


def meniscus(
    radius: float,
    z: float,
    dish: float,
    slices: int,
    rings: int,
    material: str,
    name: str,
    amp: float = 0.04,
    k: float = 0.0,
) -> Mesh:
    """Shallow liquid surface sitting in the well."""
    us = np.linspace(0.0, 1.0, slices + 1)
    vs = np.linspace(0.0, 1.0, rings + 1)
    U, V = np.meshgrid(us, vs, indexing="ij")
    th = 2.0 * np.pi * U
    rr = V * radius
    w = 1.0 + amp * V * np.sin(3.0 * th + k) * 0.5
    rr = rr * w
    zz = z - dish * (V * V)
    x = rr * np.cos(th)
    y = rr * np.sin(th)
    pts = np.stack((x, y, zz), axis=-1)
    uvs = np.stack((U, 1.0 - V), axis=-1)
    m = Mesh(name, material)
    m.add_grid(pts, uvs)
    return m


def vessel_profile() -> np.ndarray:
    """Cross-section (r, z) from foot centre, out, up, over the rim, down the well."""
    pts = np.array(
        [
            (0.000, 0.000),
            (0.035, 0.000),
            (0.078, 0.001),
            (0.112, 0.006),
            (0.128, 0.018),
            (0.124, 0.032),
            (0.102, 0.046),
            (0.072, 0.060),
            (0.054, 0.078),
            (0.046, 0.100),
            (0.048, 0.122),
            (0.062, 0.142),
            (0.090, 0.164),
            (0.124, 0.188),
            (0.158, 0.214),
            (0.186, 0.242),
            (0.206, 0.272),
            (0.216, 0.300),
            (0.214, 0.322),
            (0.200, 0.340),
            (0.184, 0.350),
            (0.168, 0.354),  # rim crest
            (0.154, 0.348),
            (0.146, 0.332),
            (0.138, 0.305),
            (0.122, 0.268),
            (0.100, 0.230),
            (0.076, 0.198),
            (0.054, 0.172),
            (0.038, 0.156),
            (0.018, 0.148),
            (0.000, 0.146),
        ],
        dtype=np.float64,
    )
    return resample_poly(pts, 64)


def build_jar() -> list[Mesh]:
    glass = Mesh("glass", "Glass")
    pink = Mesh("pink", "Pink")
    cyan = Mesh("cyan", "Cyan")
    core = Mesh("core", "Core")

    cup = lathe(vessel_profile(), nu=80, material="Glass", name="cup", warp=0.10, k=0.35)
    glass.append(cup)

    # Puddle foot — fused glass so the bowl sits, not a machine-cut disc.
    foot = organic_ellipsoid(0.118, 0.112, 0.028, 48, 28, "Glass", "foot", amp=0.10, k=1.1)
    foot.transform(tr(0.0, 0.0, 0.022))
    glass.append(foot)

    # Overlapping molten lobes around the bowl (same language as the worn orb).
    petals = [
        (0.078, 0.062, 0.095, 0.13, 0.2, 0.13, 0.02, 0.21, 0.0, 0.55),
        (0.074, 0.058, 0.090, 0.12, 1.1, 0.08, 0.11, 0.20, 1.05, 0.50),
        (0.076, 0.060, 0.092, 0.14, 2.0, -0.07, 0.12, 0.22, 2.15, 0.58),
        (0.072, 0.056, 0.088, 0.11, 2.8, -0.13, -0.03, 0.19, 3.20, 0.48),
        (0.070, 0.055, 0.086, 0.12, 3.6, -0.04, -0.13, 0.21, 4.30, 0.52),
        (0.068, 0.054, 0.082, 0.10, 4.4, 0.10, -0.10, 0.18, 5.40, 0.46),
    ]
    for i, (rx, ry, rz, amp, k, x, y, z, yaw, pit) in enumerate(petals):
        lobe = organic_ellipsoid(rx, ry, rz, 40, 28, "Glass", f"petal{i}", amp=amp, k=k)
        lobe.transform(tr(x, y, z) @ rot_z(yaw) @ rot_y(pit))
        glass.append(lobe)

    # Nectar pooled in the well.
    pink.append(
        meniscus(0.078, 0.168, 0.012, 48, 16, "Pink", "pool_p", amp=0.06, k=0.4)
    )
    p1 = organic_ellipsoid(0.050, 0.046, 0.018, 40, 26, "Pink", "nectar_p", amp=0.16, k=0.6)
    p1.transform(tr(0.012, 0.006, 0.162))
    pink.append(p1)
    p2 = organic_ellipsoid(0.028, 0.026, 0.014, 32, 22, "Pink", "drop_p", amp=0.14, k=1.7)
    p2.transform(tr(0.030, -0.016, 0.170) @ rot_z(0.4))
    pink.append(p2)

    cyan.append(
        meniscus(0.062, 0.174, 0.010, 40, 14, "Cyan", "pool_c", amp=0.05, k=2.1)
    )
    c1 = organic_ellipsoid(0.044, 0.040, 0.016, 40, 26, "Cyan", "nectar_c", amp=0.15, k=2.2)
    c1.transform(tr(-0.014, 0.004, 0.166))
    cyan.append(c1)
    c2 = organic_ellipsoid(0.024, 0.022, 0.012, 32, 22, "Cyan", "drop_c", amp=0.13, k=0.9)
    c2.transform(tr(-0.028, -0.018, 0.172))
    cyan.append(c2)

    # Glowing pearl + a few "tip" droplets resting on the nectar.
    pearl = organic_ellipsoid(0.018, 0.017, 0.016, 32, 22, "Core", "pearl", amp=0.08, k=0.3)
    pearl.transform(tr(0.002, 0.001, 0.184))
    core.append(pearl)
    coins = [
        (0.012, 0.011, 0.005, 0.036, 0.022, 0.178, 0.6, 0.4),
        (0.011, 0.010, 0.0045, -0.030, 0.028, 0.176, 1.9, 0.9),
        (0.010, 0.009, 0.004, 0.018, -0.034, 0.175, 2.8, 0.2),
        (0.009, 0.0085, 0.004, -0.022, -0.024, 0.177, 4.1, 1.4),
        (0.008, 0.0075, 0.0035, 0.040, -0.008, 0.174, 5.2, 0.7),
    ]
    for i, (rx, ry, rz, x, y, z, yaw, pit) in enumerate(coins):
        mat = "Core" if i % 2 == 0 else "Pink"
        dest = core if mat == "Core" else pink
        c = organic_ellipsoid(rx, ry, rz, 24, 16, mat, f"coin{i}", amp=0.10, k=i * 0.7)
        c.transform(tr(x, y, z) @ rot_z(yaw) @ rot_x(pit))
        dest.append(c)

    glass.name, glass.material = "Glass", "Glass"
    pink.name, pink.material = "Pink", "Pink"
    cyan.name, cyan.material = "Cyan", "Cyan"
    core.name, core.material = "Core", "Core"
    return [glass, pink, cyan, core]


def render_preview(meshes: list[Mesh], path: Path, size: int = 880) -> None:
    """Elevated 3/4 view looking into the well, vessel sitting on a studio floor."""
    eye = np.array([0.52, 0.40, 0.42], dtype=np.float64)
    target = np.array([0.0, 0.0, 0.15], dtype=np.float64)
    up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    f = _n((target - eye).reshape(1, 3))[0]
    rgt = _n(np.cross(f, up).reshape(1, 3))[0]
    upv = np.cross(rgt, f)
    light = _n(np.array([[-0.40, 0.38, 0.84]]))[0]
    fill = _n(np.array([[0.58, -0.22, 0.28]]))[0]
    scale_v = 0.30
    img = np.zeros((size, size, 3), dtype=np.float64)
    zbuf = np.full((size, size), 1e9)
    yy, xx = np.mgrid[0:size, 0:size]
    gy = yy / size
    gx = xx / size
    img[:, :] = np.array([0.76, 0.78, 0.82]) * (1.0 - 0.20 * gy)[:, :, None]
    img += 0.045 * (1.0 - ((gx - 0.5) ** 2 + (gy - 0.46) ** 2) * 2.0).clip(0, 1)[:, :, None]

    def project(p):
        q = p - eye
        x = np.dot(q, rgt)
        y = np.dot(q, upv)
        z = np.dot(q, f)
        px = int((x / scale_v * 0.5 + 0.5) * (size - 1))
        py = int((0.5 - y / scale_v * 0.5) * (size - 1))
        return px, py, z

    def draw_mesh(m: Mesh, alpha: float, ztest: bool) -> None:
        col = np.array(MAT_COL[m.material])
        emit = MAT_EMIT[m.material]
        p = np.array(m.pos, dtype=np.float64)
        nrm = m.normals()
        for a, b, c in m.tris:
            pts = (p[a], p[b], p[c])
            ns = (nrm[a], nrm[b], nrm[c])
            pr = [project(x) for x in pts]
            xs, ys, zs = zip(*pr)
            minx, maxx = max(min(xs), 0), min(max(xs), size - 1)
            miny, maxy = max(min(ys), 0), min(max(ys), size - 1)
            if minx > maxx or miny > maxy:
                continue
            area = (xs[1] - xs[0]) * (ys[2] - ys[0]) - (xs[2] - xs[0]) * (ys[1] - ys[0])
            if abs(area) < 1e-3:
                continue
            if area < 0:
                area_s = -area
                n0, n1, n2 = -ns[0], -ns[1], -ns[2]
            else:
                area_s = area
                n0, n1, n2 = ns[0], ns[1], ns[2]
            for py in range(miny, maxy + 1):
                for px in range(minx, maxx + 1):
                    w0 = (xs[1] - xs[0]) * (py - ys[0]) - (ys[1] - ys[0]) * (px - xs[0])
                    w1 = (xs[2] - xs[1]) * (py - ys[1]) - (ys[2] - ys[1]) * (px - xs[1])
                    w2 = (xs[0] - xs[2]) * (py - ys[2]) - (ys[0] - ys[2]) * (px - xs[2])
                    if area < 0:
                        w0, w1, w2 = -w0, -w1, -w2
                    if w0 < 0 or w1 < 0 or w2 < 0:
                        continue
                    z = (w0 * zs[2] + w1 * zs[0] + w2 * zs[1]) / area_s
                    if ztest and z >= zbuf[py, px]:
                        continue
                    if ztest:
                        zbuf[py, px] = z
                    nn = w0 * n2 + w1 * n0 + w2 * n1
                    ln = float(np.linalg.norm(nn)) or 1.0
                    nn = nn / ln
                    nd = float(np.clip(np.dot(nn, light), 0, 1))
                    fd = float(np.clip(np.dot(nn, fill), 0, 1))
                    ndv = float(np.clip(abs(np.dot(nn, -f)), 0, 1))
                    fres = (1.0 - ndv) ** 2
                    wrap = 0.20 + 0.64 * nd + 0.22 * fd
                    spec = nd ** 32
                    rgb = np.clip(
                        col * wrap
                        + spec * np.array([0.96, 0.98, 1.0]) * 0.90
                        + fres * np.array([0.60, 0.78, 0.90]) * 0.50
                        + emit * col,
                        0,
                        1,
                    )
                    a_use = alpha
                    if m.material == "Glass":
                        a_use = float(np.clip(0.12 + 0.50 * fres + 0.22 * spec, 0.10, 0.62))
                    img[py, px] = img[py, px] * (1.0 - a_use) + rgb * a_use

    cx, cy = int(0.50 * size), int(0.70 * size)
    sx, sy = 0.22 * size, 0.055 * size
    sh = np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2))
    img -= 0.16 * sh[:, :, None]
    img = np.clip(img, 0, 1)

    solid = [m for m in meshes if m.material != "Glass"]
    glass = [m for m in meshes if m.material == "Glass"]
    for m in solid:
        draw_mesh(m, MAT_ALPHA[m.material], ztest=True)
    for m in glass:
        draw_mesh(m, MAT_ALPHA[m.material], ztest=True)

    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "RGB").save(path)


def main() -> None:
    meshes = build_jar()
    mats = [(n, MAT_COL[n]) for n in ("Glass", "Pink", "Cyan", "Core")]
    OUT_DAE.write_text(write_dae(meshes, mats), encoding="utf-8")
    tris = sum(m.ntris for m in meshes)
    verts = sum(m.nverts for m in meshes)
    print(f"wrote {OUT_DAE}  verts={verts}  tris={tris}  bytes={OUT_DAE.stat().st_size}")
    for m in meshes:
        print(f"  {m.material:8s}  verts={m.nverts:5d}  tris={m.ntris:5d}")
        piece = OUT_DAE.with_name(f"LovenseTipJar_{m.material}.dae")
        piece.write_text(write_dae([m], [(m.material, MAT_COL[m.material])]), encoding="utf-8")
        print(f"wrote {piece}")
    render_preview(meshes, OUT_PREVIEW)
    print(f"wrote {OUT_PREVIEW}")


if __name__ == "__main__":
    main()
