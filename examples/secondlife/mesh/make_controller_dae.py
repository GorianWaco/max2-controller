#!/usr/bin/env python3
"""Organic glass-blob orb for Second Life (COLLADA 1.4.1).

Overlapping translucent cyan / magenta lobes — molten-glass sculpture, no metal.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

OUT_DAE = Path(__file__).with_name("LovenseController.dae")
OUT_PREVIEW = Path(__file__).with_name("LovenseController_preview.png")


def _n(v: np.ndarray) -> np.ndarray:
    l = np.linalg.norm(v, axis=-1, keepdims=True)
    l = np.maximum(l, 1e-9)
    return v / l


class Mesh:
    def __init__(self, name: str, material: str) -> None:
        self.name = name
        self.material = material
        self.pos: list[list[float]] = []
        self.uv: list[list[float]] = []
        self.tris: list[tuple[int, int, int]] = []

    def add(self, p: np.ndarray, uv: np.ndarray) -> int:
        i = len(self.pos)
        self.pos.append([float(p[0]), float(p[1]), float(p[2])])
        self.uv.append([float(uv[0]), float(uv[1])])
        return i

    def add_grid(self, pts: np.ndarray, uvs: np.ndarray, flip: bool = False) -> None:
        nu, nv = pts.shape[:2]
        base = len(self.pos)
        for j in range(nu):
            for i in range(nv):
                self.add(pts[j, i], uvs[j, i])
        for j in range(nu - 1):
            for i in range(nv - 1):
                a = base + j * nv + i
                b = a + 1
                c = a + nv + 1
                d = a + nv
                if flip:
                    self.tris.append((a, d, c))
                    self.tris.append((a, c, b))
                else:
                    self.tris.append((a, b, c))
                    self.tris.append((a, c, d))

    def transform(self, mat: np.ndarray) -> None:
        p = np.array(self.pos, dtype=np.float64)
        h = np.c_[p, np.ones(len(p))]
        self.pos = (h @ mat.T)[:, :3].tolist()

    def append(self, other: "Mesh") -> None:
        off = len(self.pos)
        self.pos.extend(other.pos)
        self.uv.extend(other.uv)
        self.tris.extend((a + off, b + off, c + off) for a, b, c in other.tris)

    def normals(self) -> np.ndarray:
        p = np.array(self.pos, dtype=np.float64)
        n = np.zeros_like(p)
        for a, b, c in self.tris:
            cr = np.cross(p[b] - p[a], p[c] - p[a])
            n[a] += cr
            n[b] += cr
            n[c] += cr
        return _n(n)

    @property
    def nverts(self) -> int:
        return len(self.pos)

    @property
    def ntris(self) -> int:
        return len(self.tris)


def rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return m


def rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[0, 0], m[0, 2] = c, s
    m[2, 0], m[2, 2] = -s, c
    return m


def rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4)
    m[1, 1], m[1, 2] = c, -s
    m[2, 1], m[2, 2] = s, c
    return m


def tr(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[0, 3], m[1, 3], m[2, 3] = x, y, z
    return m


def scale(sx: float, sy: float, sz: float) -> np.ndarray:
    m = np.eye(4)
    m[0, 0], m[1, 1], m[2, 2] = sx, sy, sz
    return m


# each ball: center (3,), radius, strength
Ball = tuple[np.ndarray, float, float]


def field_many(p: np.ndarray, balls: list[Ball]) -> np.ndarray:
    v = np.zeros(len(p), dtype=np.float64)
    for c, R, s in balls:
        d = p - c
        d2 = np.einsum("ij,ij->i", d, d)
        r2 = d2 / (R * R)
        m = r2 < 1.0
        t = 1.0 - r2[m]
        v[m] += s * t * t * t
    return v


def iso_sphere(balls: list[Ball], level: float, material: str, name: str,
               nu: int = 56, nv: int = 40, rmax: float = 0.09,
               ripple: float = 0.0) -> Mesh:
    us = np.linspace(0.0, 1.0, nu + 1)
    vs = np.linspace(0.0, 1.0, nv + 1)
    U, V = np.meshgrid(us, vs, indexing="ij")
    th = 2.0 * np.pi * U
    ph = np.pi * V
    dirs = np.stack(
        (np.sin(ph) * np.cos(th), np.sin(ph) * np.sin(th), np.cos(ph)),
        axis=-1,
    )
    flat = dirs.reshape(-1, 3)
    lo = np.zeros(len(flat))
    hi = np.full(len(flat), rmax)
    for _ in range(22):
        mid = 0.5 * (lo + hi)
        hit = field_many(flat * mid[:, None], balls) >= level
        lo = np.where(hit, mid, lo)
        hi = np.where(hit, hi, mid)
    r = 0.5 * (lo + hi)
    if ripple:
        r = r * (
            1.0
            + ripple * 0.55 * np.sin(5.0 * th.ravel() + 2.2 * ph.ravel())
            + ripple * 0.35 * np.cos(3.0 * th.ravel() - 4.0 * ph.ravel())
            + ripple * 0.25 * np.sin(7.0 * ph.ravel() + 1.1)
        )
    miss = r < 1e-4
    r[miss] = 0.008
    pts = (flat * r[:, None]).reshape(nu + 1, nv + 1, 3)
    uvs = np.stack((U, 1.0 - V), axis=-1)
    m = Mesh(name, material)
    m.add_grid(pts, uvs)
    return m


def organic_ellipsoid(
    rx: float, ry: float, rz: float,
    slices: int, stacks: int,
    material: str, name: str,
    amp: float = 0.08, k: float = 0.0,
) -> Mesh:
    """Smooth sphere with gentle flowing displacement — glass lobe."""
    us = np.linspace(0.0, 1.0, slices + 1)
    vs = np.linspace(0.0, 1.0, stacks + 1)
    U, V = np.meshgrid(us, vs, indexing="ij")
    th = 2.0 * np.pi * U
    ph = np.pi * V
    # envelope → 0 at the poles so the UV-sphere doesn't pinch
    s = np.sin(ph) ** 2
    w = (
        1.0
        + s * amp * 0.60 * np.sin(3.0 * th + k)
        + s * amp * 0.38 * np.cos(2.0 * ph + 0.6 * k)
        + s * amp * 0.28 * np.sin(4.0 * th - 2.0 * ph + k)
        + s * amp * 0.16 * np.cos(5.0 * ph + 1.3 * k)
    )
    x = rx * w * np.sin(ph) * np.cos(th)
    y = ry * w * np.sin(ph) * np.sin(th)
    z = rz * w * np.cos(ph)
    pts = np.stack((x, y, z), axis=-1)
    uvs = np.stack((U, 1.0 - V), axis=-1)
    m = Mesh(name, material)
    m.add_grid(pts, uvs)
    return m


def B(x: float, y: float, z: float, R: float, s: float = 1.0) -> Ball:
    return (np.array([x, y, z], dtype=np.float64), R, s)


def build_orb() -> list[Mesh]:
    """Overlapping glass bubbles: clear membranes + pink / cyan cores.

    Same idea as the reference — fused soap-film lobes, not a metal cage.
    """
    glass = Mesh("glass", "Glass")
    pink = Mesh("pink", "Pink")
    cyan = Mesh("cyan", "Cyan")

    # overlapping clear membranes — no single enclosing sphere
    membranes = [
        (0.030, 0.029, 0.028, 0.11, 0.0, 0.007, 0.005, 0.004, 0.20, 0.15),
        (0.029, 0.028, 0.027, 0.12, 0.9, -0.007, 0.006, 0.003, 0.55, 0.40),
        (0.028, 0.027, 0.026, 0.10, 1.7, 0.005, -0.007, -0.005, -0.60, 0.70),
        (0.027, 0.026, 0.025, 0.13, 2.4, -0.006, -0.008, 0.006, 0.80, -0.45),
        (0.020, 0.019, 0.018, 0.09, 3.2, -0.016, -0.014, -0.007, 0.25, 0.20),
    ]
    for i, (rx, ry, rz, amp, k, x, y, z, yaw, pit) in enumerate(membranes):
        lobe = organic_ellipsoid(rx, ry, rz, 56, 40, "Glass", f"mem{i}", amp=amp, k=k)
        lobe.transform(tr(x, y, z) @ rot_z(yaw) @ rot_y(pit))
        glass.append(lobe)

    p1 = organic_ellipsoid(0.020, 0.018, 0.017, 48, 32, "Pink", "p1", amp=0.12, k=0.4)
    p1.transform(tr(0.007, 0.006, 0.007))
    pink.append(p1)
    p2 = organic_ellipsoid(0.014, 0.013, 0.012, 36, 26, "Pink", "p2", amp=0.12, k=1.8)
    p2.transform(tr(0.012, -0.002, 0.000) @ rot_y(0.35))
    pink.append(p2)

    c1 = organic_ellipsoid(0.021, 0.019, 0.018, 48, 32, "Cyan", "c1", amp=0.11, k=2.2)
    c1.transform(tr(-0.007, 0.001, 0.003))
    cyan.append(c1)
    c2 = organic_ellipsoid(0.013, 0.012, 0.011, 36, 26, "Cyan", "c2", amp=0.11, k=0.9)
    c2.transform(tr(-0.010, -0.010, -0.004))
    cyan.append(c2)
    bub = organic_ellipsoid(0.009, 0.0085, 0.0085, 32, 22, "Cyan", "bub", amp=0.07, k=3.0)
    bub.transform(tr(-0.020, -0.015, -0.007))
    cyan.append(bub)

    core = organic_ellipsoid(0.010, 0.009, 0.009, 32, 22, "Core", "core", amp=0.07, k=0.2)
    core.transform(tr(0.001, 0.001, 0.002))

    # face a 3/4 view when worn (pink to +X)
    face = rot_y(0.35) @ rot_z(-0.15)
    for m in (glass, pink, cyan, core):
        m.transform(face)

    glass.name, glass.material = "Glass", "Glass"
    pink.name, pink.material = "Pink", "Pink"
    cyan.name, cyan.material = "Cyan", "Cyan"
    core.name, core.material = "Core", "Core"
    # Glass first so Firestorm linkset upload uses it as root
    return [glass, pink, cyan, core]


def _fmt(vals) -> str:
    return " ".join(f"{float(v):.6f}" for v in vals)


def geom_xml(m: Mesh) -> str:
    p = np.array(m.pos, dtype=np.float64)
    nrm = m.normals()
    uv = np.array(m.uv, dtype=np.float64)
    n = m.nverts
    idx = []
    for a, b, c in m.tris:
        idx.extend((a, a, a, b, b, b, c, c, c))
    return f"""    <geometry id="{m.name}-mesh" name="{m.name}">
      <mesh>
        <source id="{m.name}-pos">
          <float_array id="{m.name}-pos-array" count="{n * 3}">{_fmt(p.ravel())}</float_array>
          <technique_common>
            <accessor source="#{m.name}-pos-array" count="{n}" stride="3">
              <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <source id="{m.name}-norm">
          <float_array id="{m.name}-norm-array" count="{n * 3}">{_fmt(nrm.ravel())}</float_array>
          <technique_common>
            <accessor source="#{m.name}-norm-array" count="{n}" stride="3">
              <param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <source id="{m.name}-uv">
          <float_array id="{m.name}-uv-array" count="{n * 2}">{_fmt(uv.ravel())}</float_array>
          <technique_common>
            <accessor source="#{m.name}-uv-array" count="{n}" stride="2">
              <param name="S" type="float"/><param name="T" type="float"/>
            </accessor>
          </technique_common>
        </source>
        <vertices id="{m.name}-vtx"><input semantic="POSITION" source="#{m.name}-pos"/></vertices>
        <triangles material="{m.material}" count="{m.ntris}">
          <input semantic="VERTEX" source="#{m.name}-vtx" offset="0"/>
          <input semantic="NORMAL" source="#{m.name}-norm" offset="1"/>
          <input semantic="TEXCOORD" source="#{m.name}-uv" offset="2" set="0"/>
          <p>{" ".join(str(i) for i in idx)}</p>
        </triangles>
      </mesh>
    </geometry>
"""


def node_xml(m: Mesh) -> str:
    return f"""      <node id="{m.name}" name="{m.name}" type="NODE">
        <instance_geometry url="#{m.name}-mesh">
          <bind_material><technique_common>
            <instance_material symbol="{m.material}" target="#{m.material}">
              <bind_vertex_input semantic="UVSET0" input_semantic="TEXCOORD" input_set="0"/>
            </instance_material>
          </technique_common></bind_material>
        </instance_geometry>
      </node>
"""


def effect_xml(name: str, col: tuple[float, float, float]) -> str:
    r, g, b = col
    emit = {
        "Glass": "0.08 0.10 0.12 1",
        "Pink": "0.28 0.06 0.12 1",
        "Cyan": "0.04 0.14 0.24 1",
        "Core": "0.35 0.16 0.22 1",
    }[name]
    return f"""    <effect id="{name}-fx">
      <profile_COMMON><technique sid="common"><lambert>
        <emission><color>{emit}</color></emission>
        <diffuse><color>{r:.3f} {g:.3f} {b:.3f} 1</color></diffuse>
      </lambert></technique></profile_COMMON>
    </effect>
"""


def write_dae(meshes: list[Mesh], materials: list[tuple[str, tuple[float, float, float]]]) -> str:
    effects = "".join(effect_xml(n, c) for n, c in materials)
    mats = "".join(
        f'    <material id="{n}" name="{n}"><instance_effect url="#{n}-fx"/></material>\n'
        for n, _ in materials
    )
    geoms = "".join(geom_xml(m) for m in meshes)
    nodes = "".join(node_xml(m) for m in meshes)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset>
    <contributor><author>Lovense Controller</author><authoring_tool>make_controller_dae.py</authoring_tool></contributor>
    <unit name="meter" meter="1"/>
    <up_axis>Z_UP</up_axis>
  </asset>
  <library_effects>
{effects}  </library_effects>
  <library_materials>
{mats}  </library_materials>
  <library_geometries>
{geoms}  </library_geometries>
  <library_visual_scenes>
    <visual_scene id="Scene" name="Scene">
{nodes}    </visual_scene>
  </library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
"""


MAT_COL = {
    "Glass": (0.72, 0.86, 0.94),
    "Pink": (0.92, 0.30, 0.50),
    "Cyan": (0.16, 0.58, 0.90),
    "Core": (0.95, 0.55, 0.70),
}

MAT_ALPHA = {"Glass": 0.38, "Pink": 0.72, "Cyan": 0.72, "Core": 1.0}
MAT_EMIT = {"Glass": 0.12, "Pink": 0.28, "Cyan": 0.22, "Core": 0.45}


def render_preview(meshes: list[Mesh], path: Path, size: int = 900) -> None:
    """Studio 3/4 view, glass drawn last with fresnel."""
    eye = np.array([0.14, 0.11, 0.07], dtype=np.float64)
    target = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    f = _n((target - eye).reshape(1, 3))[0]
    rgt = _n(np.cross(f, up).reshape(1, 3))[0]
    upv = np.cross(rgt, f)
    light = _n(np.array([[-0.45, 0.35, 0.82]]))[0]
    fill = _n(np.array([[0.55, -0.25, 0.25]]))[0]
    scale_v = 0.072
    img = np.zeros((size, size, 3), dtype=np.float64)
    zbuf = np.full((size, size), 1e9)
    yy, xx = np.mgrid[0:size, 0:size]
    # studio backdrop
    gy = yy / size
    gx = xx / size
    img[:, :] = np.array([0.78, 0.80, 0.83]) * (1.0 - 0.18 * gy)[:, :, None]
    img += 0.04 * (1.0 - ((gx - 0.5) ** 2 + (gy - 0.42) ** 2) * 2.2).clip(0, 1)[:, :, None]

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
                        a_use = float(np.clip(0.10 + 0.52 * fres + 0.20 * spec, 0.08, 0.58))
                    img[py, px] = img[py, px] * (1.0 - a_use) + rgb * a_use

    # soft contact shadow
    cx, cy = int(0.50 * size), int(0.62 * size)
    sx, sy = 0.16 * size, 0.045 * size
    sh = np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2))
    img -= 0.14 * sh[:, :, None]
    img = np.clip(img, 0, 1)

    solid = [m for m in meshes if m.material != "Glass"]
    glass = [m for m in meshes if m.material == "Glass"]
    for m in solid:
        draw_mesh(m, MAT_ALPHA[m.material], ztest=True)
    for m in glass:
        draw_mesh(m, MAT_ALPHA[m.material], ztest=True)

    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "RGB").save(path)


def main() -> None:
    meshes = build_orb()
    mats = [(n, MAT_COL[n]) for n in ("Glass", "Pink", "Cyan", "Core")]
    OUT_DAE.write_text(write_dae(meshes, mats), encoding="utf-8")
    tris = sum(m.ntris for m in meshes)
    verts = sum(m.nverts for m in meshes)
    print(f"wrote {OUT_DAE}  verts={verts}  tris={tris}  bytes={OUT_DAE.stat().st_size}")
    for m in meshes:
        print(f"  {m.material:8s}  verts={m.nverts:5d}  tris={m.ntris:5d}")
        piece = OUT_DAE.with_name(f"LovenseOrb_{m.material}.dae")
        piece.write_text(write_dae([m], [(m.material, MAT_COL[m.material])]), encoding="utf-8")
        print(f"wrote {piece}")
    render_preview(meshes, OUT_PREVIEW)
    print(f"wrote {OUT_PREVIEW}")


if __name__ == "__main__":
    main()
