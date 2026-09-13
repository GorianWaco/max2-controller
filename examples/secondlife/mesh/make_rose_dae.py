#!/usr/bin/env python3
"""Ornate rose-pendant mesh for Second Life (COLLADA 1.4.1).

Not a sphere. Layered curled petals, calyx, leaves, trefoil bail.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image

OUT_DAE = Path(__file__).with_name("LovenseRose.dae")
OUT_PREVIEW = Path(__file__).with_name("LovenseRose_preview.png")


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
        """pts, uvs: (nu, nv, 3/2)."""
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

    def add_solid_grid(self, pts: np.ndarray, uvs: np.ndarray, thick: float) -> None:
        """Shell a surface grid into a thin solid (front, back, rim)."""
        nu, nv = pts.shape[:2]
        du = np.gradient(pts, axis=0)
        dv = np.gradient(pts, axis=1)
        nrm = _n(np.cross(du, dv))
        front = pts + nrm * (thick * 0.5)
        back = pts - nrm * (thick * 0.5)
        self.add_grid(front, uvs, flip=False)
        self.add_grid(back, uvs, flip=True)
        # rim along the four edges
        def strip(a: np.ndarray, b: np.ndarray, ua: np.ndarray, ub: np.ndarray) -> None:
            k = a.shape[0]
            base = len(self.pos)
            for i in range(k):
                self.add(a[i], ua[i])
            for i in range(k):
                self.add(b[i], ub[i])
            for i in range(k - 1):
                a0, a1 = base + i, base + i + 1
                b0, b1 = base + k + i, base + k + i + 1
                self.tris.append((a0, a1, b1))
                self.tris.append((a0, b1, b0))

        strip(front[0], back[0], uvs[0], uvs[0])
        strip(front[-1], back[-1], uvs[-1], uvs[-1])
        strip(front[:, 0], back[:, 0], uvs[:, 0], uvs[:, 0])
        strip(front[:, -1], back[:, -1], uvs[:, -1], uvs[:, -1])

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
            e1 = p[b] - p[a]
            e2 = p[c] - p[a]
            cr = np.cross(e1, e2)
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


def petal(length: float, width: float, curl: float, cup: float, ruffle: float, nu: int = 12, nv: int = 9, thick: float = 0.0011) -> Mesh:
    us = np.linspace(0.0, 1.0, nu)
    vs = np.linspace(-1.0, 1.0, nv)
    U, V = np.meshgrid(us, vs, indexing="ij")
    # rounded teardrop: fat mid, soft tip (not a spike)
    env = np.sin(np.pi * np.clip(U ** 0.88, 0.0, 1.0)) ** 0.55
    env *= 0.55 + 0.45 * (1.0 - U) ** 0.45
    env = np.maximum(env, 0.08 * (1.0 - U))
    x = U * length
    y = V * width * env
    y += ruffle * np.sin(U * 5.5 * np.pi) * (np.abs(V) ** 1.6) * env
    y += 0.4 * ruffle * np.sin(U * 9.0 * np.pi + 1.2 * V) * (np.abs(V) ** 1.2) * U
    z = cup * (V * V) * (0.15 + 0.85 * U ** 0.7) * width
    z -= 0.10 * width * np.exp(-((V * 3.4) ** 2)) * np.sin(np.pi * U)
    ang = curl * (U ** 1.55)
    ca, sa = np.cos(ang), np.sin(ang)
    xp = x * ca - z * sa
    zp = x * sa + z * ca
    pts = np.stack((xp, y, zp), axis=-1)
    uvs = np.stack((U, (V + 1.0) * 0.5), axis=-1)
    m = Mesh("petal", "Petal")
    m.add_solid_grid(pts, uvs, thick)
    return m


def leaf(length: float, width: float, nu: int = 16, nv: int = 10) -> Mesh:
    us = np.linspace(0.0, 1.0, nu)
    vs = np.linspace(-1.0, 1.0, nv)
    U, V = np.meshgrid(us, vs, indexing="ij")
    env = np.sin(np.pi * U) ** 0.9 * (1.0 - 0.15 * U)
    serr = 1.0 + 0.08 * np.sin(U * 16.0 * np.pi) * np.abs(V)
    x = U * length
    y = V * width * env * serr
    z = 0.18 * width * (V * V) * U
    z -= 0.07 * width * np.exp(-((V * 2.8) ** 2))
    pts = np.stack((x, y, z), axis=-1)
    uvs = np.stack((U, (V + 1.0) * 0.5), axis=-1)
    m = Mesh("leaf", "Leaf")
    m.add_solid_grid(pts, uvs, 0.0010)
    return m


def sepal(length: float, width: float, nu: int = 12, nv: int = 8) -> Mesh:
    us = np.linspace(0.0, 1.0, nu)
    vs = np.linspace(-1.0, 1.0, nv)
    U, V = np.meshgrid(us, vs, indexing="ij")
    env = (1.0 - U) ** 0.35 * np.sin(np.pi * np.clip(U * 1.05, 0, 1)) ** 0.5
    x = U * length
    y = V * width * env * (1.0 - 0.5 * U)
    z = 0.22 * width * (V * V) * (1.0 - U)
    pts = np.stack((x, y, z), axis=-1)
    uvs = np.stack((U, (V + 1.0) * 0.5), axis=-1)
    m = Mesh("sepal", "Leaf")
    m.add_solid_grid(pts, uvs, 0.0009)
    return m


def ellipsoid(rx: float, ry: float, rz: float, slices: int, stacks: int, material: str, name: str) -> Mesh:
    us = np.linspace(0.0, 1.0, slices + 1)
    vs = np.linspace(0.0, 1.0, stacks + 1)
    U, V = np.meshgrid(us, vs, indexing="ij")
    th = 2.0 * np.pi * U
    ph = np.pi * V
    x = rx * np.sin(ph) * np.cos(th)
    y = ry * np.sin(ph) * np.sin(th)
    z = rz * np.cos(ph)
    pts = np.stack((x, y, z), axis=-1)
    uvs = np.stack((U, 1.0 - V), axis=-1)
    m = Mesh(name, material)
    m.add_grid(pts, uvs)
    return m


def tube_along(path: np.ndarray, radius: float, segs: int, material: str, name: str, closed: bool = True) -> Mesh:
    n = len(path)
    tang = np.gradient(path, axis=0)
    tang = _n(tang)
    # parallel transport
    up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(tang[0], up)) > 0.9:
        up = np.array([0.0, 1.0, 0.0])
    nors = []
    n0 = _n(np.cross(tang[0], up).reshape(1, 3))[0]
    b0 = _n(np.cross(tang[0], n0).reshape(1, 3))[0]
    nrm, binm = n0, b0
    for i in range(n):
        if i:
            k = np.cross(tang[i - 1], tang[i])
            kl = np.linalg.norm(k)
            if kl > 1e-8:
                k = k / kl
                a = math.acos(float(np.clip(np.dot(tang[i - 1], tang[i]), -1, 1)))
                c, s = math.cos(a), math.sin(a)
                # Rodrigues
                def rod(v):
                    return v * c + np.cross(k, v) * s + k * np.dot(k, v) * (1 - c)

                nrm, binm = rod(nrm), rod(binm)
        nors.append((nrm.copy(), binm.copy()))
    ring = np.linspace(0.0, 2.0 * np.pi, segs, endpoint=False)
    pts = np.zeros((n + (1 if closed else 0), segs + 1, 3))
    uvs = np.zeros((n + (1 if closed else 0), segs + 1, 2))
    rows = n + (1 if closed else 0)
    for i in range(rows):
        pi = path[i % n]
        nn, bb = nors[i % n]
        vcoord = i / max(n, 1)
        for j, ang in enumerate(list(ring) + [0.0]):
            c, s = math.cos(ang), math.sin(ang)
            pts[i, j] = pi + radius * (c * nn + s * bb)
            uvs[i, j] = (j / segs, vcoord)
    m = Mesh(name, material)
    m.add_grid(pts, uvs)
    return m


def trefoil(samples: int, R: float, r: float, s: float) -> np.ndarray:
    t = np.linspace(0.0, 2.0 * np.pi, samples, endpoint=False)
    x = s * (R + r * np.cos(3 * t)) * np.cos(2 * t)
    y = s * (R + r * np.cos(3 * t)) * np.sin(2 * t)
    z = s * r * np.sin(3 * t)
    return np.stack((x, y, z), axis=1)


def capsule(p0: np.ndarray, p1: np.ndarray, radius: float, slices: int, material: str, name: str) -> Mesh:
    axis = p1 - p0
    length = float(np.linalg.norm(axis)) or 1e-6
    d = axis / length
    path = np.linspace(p0, p1, 8)
    return tube_along(path, radius, slices, material, name, closed=False)


def atlas_uv(m: Mesh, col: int, row: int, cols: int, rows: int, pad: float = 0.01) -> None:
    u0 = col / cols + pad
    v0 = row / rows + pad
    us = 1.0 / cols - 2 * pad
    vs = 1.0 / rows - 2 * pad
    for uv in m.uv:
        uv[0] = u0 + uv[0] * us
        uv[1] = v0 + uv[1] * vs


def build_rose() -> list[Mesh]:
    petals = Mesh("body", "Petal")
    layers = [
        # n, length, width, curl, cup, ruffle, tilt (from +Z), z, scale
        (6, 0.026, 0.015, 1.70, 0.62, 0.0010, 0.18, 0.014, 0.88),
        (6, 0.034, 0.020, 1.48, 0.55, 0.0018, 0.38, 0.010, 0.96),
        (8, 0.046, 0.026, 1.22, 0.46, 0.0030, 0.62, 0.004, 1.02),
        (9, 0.058, 0.032, 1.08, 0.38, 0.0042, 0.88, -0.003, 1.08),
        (10, 0.072, 0.037, 0.90, 0.30, 0.0058, 1.14, -0.012, 1.14),
    ]
    pi = 0
    for li, (n, length, width, curl, cup, ruffle, tilt, z, sc) in enumerate(layers):
        off = (0.38 * li) * (2 * math.pi / n)
        for k in range(n):
            p = petal(length, width, curl, cup, ruffle)
            yaw = off + k * 2 * math.pi / n
            yaw += 0.035 * math.sin(k * 2.7 + li)
            tilt_k = tilt + 0.05 * math.sin(k * 1.9 + li)
            mat = tr(0, 0, z) @ rot_z(yaw) @ rot_y(tilt_k) @ scale(sc, 0.92 + 0.08 * math.sin(k), sc)
            p.transform(mat)
            atlas_uv(p, (pi % 8), min(pi // 8, 7), 8, 8)
            petals.append(p)
            pi += 1

    # closed inner bud — overlapping, almost vertical
    for k in range(8):
        p = petal(0.022, 0.012, 1.85, 0.75, 0.0006, nu=10, nv=8, thick=0.0010)
        p.transform(
            tr(0, 0, 0.016)
            @ rot_z(k * math.pi / 4 + 0.12)
            @ rot_y(0.10)
            @ scale(0.90, 0.90, 0.90)
        )
        atlas_uv(p, k, 7, 8, 8)
        petals.append(p)

    center = Mesh("gem", "Gem")
    heart = ellipsoid(0.018, 0.018, 0.015, 14, 10, "Gem", "core")
    heart.transform(tr(0, 0, 0.011))
    center.append(heart)
    ht = np.linspace(0.0, 6.0 * math.pi, 80)
    hx = (0.004 + 0.010 * ht / ht[-1]) * np.cos(ht)
    hy = (0.004 + 0.010 * ht / ht[-1]) * np.sin(ht)
    hz = 0.012 + 0.018 * (ht / ht[-1])
    helix = np.stack((hx, hy, hz), axis=1)
    center.append(tube_along(helix, 0.0026, 8, "Gem", "helix", closed=False))
    for i in range(12):
        ang = i * math.pi / 6
        rad = 0.008
        bead = ellipsoid(0.0040, 0.0040, 0.0048, 8, 6, "Gem", "bead")
        bead.transform(tr(rad * math.cos(ang), rad * math.sin(ang), 0.020))
        center.append(bead)

    foliage = Mesh("band", "Leaf")
    for k in range(5):
        s = sepal(0.038, 0.016)
        s.transform(tr(0, 0, -0.012) @ rot_z(k * 2 * math.pi / 5 + 0.2) @ rot_y(1.25) @ rot_x(0.08))
        atlas_uv(s, k, 0, 5, 2)
        foliage.append(s)
    for k, yaw in enumerate((-0.7, 0.85, 3.3)):
        lf = leaf(0.055, 0.022)
        lf.transform(
            tr(0.01 * math.cos(yaw), 0.01 * math.sin(yaw), -0.018)
            @ rot_z(yaw)
            @ rot_y(1.05 + 0.1 * k)
            @ rot_x((-1) ** k * 0.18)
        )
        atlas_uv(lf, k, 1, 5, 2)
        foliage.append(lf)

    # short thorny stem
    stem_path = np.array(
        [[0.0, 0.0, -0.012], [0.004, 0.0, -0.028], [0.006, 0.002, -0.048], [0.005, 0.003, -0.066]]
    )
    stem = tube_along(stem_path, 0.0042, 10, "Leaf", "stem", closed=False)
    foliage.append(stem)
    for t in (0.35, 0.62):
        i = int(t * (len(stem_path) - 1))
        p0 = stem_path[i]
        dirv = np.array([0.012, 0.006 * ((-1) ** int(t * 10)), -0.004])
        thorn = capsule(p0, p0 + dirv, 0.0014, 6, "Leaf", "thorn")
        foliage.append(thorn)

    # trefoil bail on top (original -X becomes world +Z after rot_y(pi/2))
    knot = trefoil(140, 1.0, 0.42, 0.013)
    knot[:, 0] -= 0.050
    knot[:, 2] += 0.002
    bail = tube_along(knot, 0.0022, 9, "Metal", "bail", closed=True)
    metal = Mesh("metal", "Metal")
    metal.append(bail)
    ring_t = np.linspace(0, 2 * math.pi, 48, endpoint=False)
    ring = np.stack(
        (
            np.full_like(ring_t, -0.064),
            0.009 * np.cos(ring_t),
            0.009 * np.sin(ring_t),
        ),
        1,
    )
    metal.append(tube_along(ring, 0.0017, 8, "Metal", "ring", closed=True))

    # face the bloom +X (out from chest in SL attachments)
    face = rot_y(0.5 * math.pi)
    for m in (petals, center, foliage, metal):
        m.transform(face)
    petals.name, petals.material = "body", "Petal"
    center.name, center.material = "gem", "Gem"
    foliage.name, foliage.material = "band", "Leaf"
    metal.name, metal.material = "metal", "Metal"
    return [petals, center, foliage, metal]


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
    return f"""    <effect id="{name}-fx">
      <profile_COMMON><technique sid="common"><lambert>
        <emission><color>0 0 0 1</color></emission>
        <diffuse><color>{r:.3f} {g:.3f} {b:.3f} 1</color></diffuse>
      </lambert></technique></profile_COMMON>
    </effect>
"""


def write_dae(meshes: list[Mesh], materials: list[tuple[str, tuple[float, float, float]]]) -> str:
    effects = "".join(effect_xml(n, c) for n, c in materials)
    mats = "".join(f'    <material id="{n}" name="{n}"><instance_effect url="#{n}-fx"/></material>\n' for n, _ in materials)
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
    "Petal": (0.95, 0.32, 0.52),
    "Gem": (1.00, 0.82, 0.35),
    "Leaf": (0.22, 0.42, 0.28),
    "Metal": (0.92, 0.78, 0.42),
}


def render_preview(meshes: list[Mesh], path: Path, size: int = 720) -> None:
    """Simple orthographic z-buffer, 3/4 view."""
    # bloom faces +X after rot_y(-pi/2)
    eye = np.array([0.20, 0.09, 0.07], dtype=np.float64)
    target = np.array([0.02, 0.0, 0.0], dtype=np.float64)
    up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    f = _n((target - eye).reshape(1, 3))[0]
    rgt = _n(np.cross(f, up).reshape(1, 3))[0]
    upv = np.cross(rgt, f)
    light = _n(np.array([[-0.4, 0.55, 0.75]]))[0]
    scale_v = 0.13
    img = np.zeros((size, size, 3), dtype=np.float64)
    zbuf = np.full((size, size), 1e9)
    bg = np.array([0.09, 0.07, 0.09])
    img[:, :] = bg

    def project(p):
        q = p - eye
        x = np.dot(q, rgt)
        y = np.dot(q, upv)
        z = np.dot(q, f)
        px = int((x / scale_v * 0.5 + 0.5) * (size - 1))
        py = int((0.5 - y / scale_v * 0.5) * (size - 1))
        return px, py, z

    for m in meshes:
        col = np.array(MAT_COL[m.material])
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
            nn = _n((ns[0] + ns[1] + ns[2]).reshape(1, 3))[0]
            nd = float(np.clip(np.dot(nn, light), 0, 1))
            wrap = 0.22 + 0.78 * nd
            spec = nd ** 24
            rgb = np.clip(col * wrap + spec * np.array([1.0, 0.95, 0.92]) * 0.45, 0, 1)
            # barycentric fill
            for py in range(miny, maxy + 1):
                for px in range(minx, maxx + 1):
                    w0 = (xs[1] - xs[0]) * (py - ys[0]) - (ys[1] - ys[0]) * (px - xs[0])
                    w1 = (xs[2] - xs[1]) * (py - ys[1]) - (ys[2] - ys[1]) * (px - xs[1])
                    w2 = (xs[0] - xs[2]) * (py - ys[2]) - (ys[0] - ys[2]) * (px - xs[2])
                    if area < 0:
                        w0, w1, w2, area_s = -w0, -w1, -w2, -area
                    else:
                        area_s = area
                    if w0 < 0 or w1 < 0 or w2 < 0:
                        continue
                    z = (w0 * zs[2] + w1 * zs[0] + w2 * zs[1]) / area_s
                    if z < zbuf[py, px]:
                        zbuf[py, px] = z
                        img[py, px] = rgb

    # vignette
    yy, xx = np.mgrid[0:size, 0:size]
    rr = np.sqrt(((xx - size / 2) / size) ** 2 + ((yy - size / 2) / size) ** 2)
    img *= (1.0 - 0.25 * np.clip(rr * 1.4, 0, 1))[:, :, None]
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "RGB").save(path)


def main() -> None:
    meshes = build_rose()
    mats = [
        ("Petal", MAT_COL["Petal"]),
        ("Gem", MAT_COL["Gem"]),
        ("Leaf", MAT_COL["Leaf"]),
        ("Metal", MAT_COL["Metal"]),
    ]
    OUT_DAE.write_text(write_dae(meshes, mats), encoding="utf-8")
    tris = sum(m.ntris for m in meshes)
    verts = sum(m.nverts for m in meshes)
    print(f"wrote {OUT_DAE}  verts={verts}  tris={tris}  bytes={OUT_DAE.stat().st_size}")
    for m in meshes:
        print(f"  {m.material:8s}  verts={m.nverts:5d}  tris={m.ntris:5d}")
    render_preview(meshes, OUT_PREVIEW)
    print(f"wrote {OUT_PREVIEW}")


if __name__ == "__main__":
    main()
