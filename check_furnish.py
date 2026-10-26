#!/usr/bin/env python3
"""check_furnish: compare key furnish.js pieces with the DWG furniture they stand for.

Run with the DWG venv: ~/.dwg-tools/bin/python check_furnish.py dwg/kareems-changes.dxf --version kareems-changes

furnish.js runs in node against a stand-in for three.js that only records boxes (p.box), so the
check sees the real placements. Each key item's footprint (the boxes of the listed materials whose
centre falls inside the DWG outline, plus a margin) is compared with the DWG outline or block, in plan
metres (model.js frame). Sizes and centres in cm; a difference over 2 cm is flagged and the exit code is 1.
Appliance blocks (fridge, hob, sink) carry door-swing and symbol lines, so only their width along the run
and centre are checked. Suite items are checked for the version that has them only.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from ezdxf import recover, bbox as ebbox

ROOT = Path(__file__).resolve().parent
ORIGIN = (190.4049651574427, -121.6132067325871)  # model*.js "origin": plan = DWG - origin
TOL = 0.02
# Main on the page loads kareems-changes (2026-10-25), Karim's version karims-version (26 Oct). Each version has its
# own furniture, furnish-<version>.js (26 Oct 2026); the retired pre-25-Oct 'main' (model.js) has none any more.
MODELS = {'naghams-changes': 'model-naghams-changes.js', 'kareems-changes': 'model-kareems-changes.js',
          'karims-version': 'model-karims-version.js'}

# name, versions (None = all), DWG source, axes to check, 3D materials, margin (m, or (x, y)) round the outline.
# Source: ('block', name) or ('outline', seed x, seed y, width cm, depth cm) for a closed 2furni polyline (plan m).
ITEMS = [
    ('kitchen fridge', None, ('block', 'wgsfd'), 'y', {'blackSteel'}, 0.05),
    ('kitchen dishwasher', None, ('block', 'dfs'), 'y', {'whiteLacquer'}, (0.05, -0.005)),  # its tall column's carcass
    ('kitchen hob', None, ('block', 'yrtds'), 'y', {'blackGlass'}, 0.05),
    ('kitchen hood', None, ('block', 'yrtds'), 'y', {'chrome'}, 0.05),
    ('kitchen sink', None, ('block', 'wrewwer'), 'x', {'blackSteel'}, 0.05),
    ('laundry joinery', None, ('outline', 10.63, 7.92, 61.9, 206.9), 'xy', {'oakVeneer'}, 0.0),
    ('laundry washer/dryer', {'main', 'shifted-bedroom', 'naghams-changes', 'karims-version'}, ('outline', 11.835, 8.888, 60.0, 60.0), 'x', {'applianceWhite'}, 0.05),  # 2 cm off the wall
    ('laundry washer/dryer', {'kareems-changes'}, ('outline', 11.675, 8.888, 60.0, 60.0), 'x', {'applianceWhite'}, 0.05),  # Main, 26 Oct: partition 0.202 west
    ('entrance bench', None, ('outline', 8.512, 5.35, 120.0, 40.0), 'xy', {'boucle'}, 0.05),
    ('entrance console', None, ('outline', 10.584, 3.81, 153.0, 42.0), 'xy', {'oakVeneer', 'whiteLacquer*'}, 0.05),  # L: column piece + console
    ('coffee counter', None, ('outline', 20.474, 9.2, 150.0, 60.1), 'xy', {'marbleTop'}, 0.05),
    ('guest WC counter', None, ('outline', 14.367, 8.035, 60.4, 230.4), 'xy', {'stoneTable*', 'oakBattens'}, 0.05),  # wall to wall
    ('living sofa north module', None, ('outline', 3.465, 3.732, 103.0, 97.4), 'xy', {'greige'}, 0.0),
    ('living sofa return', None, ('outline', 4.389, 1.093, 82.6, 102.6), 'x', {'greige'}, 0.0),
    ('living end table', None, ('outline', 3.459, 4.329, 104.3, 22.7), 'xy', {'walnut'}, 0.0),
    ('living coffee table', None, ('outline', 4.645, 2.529, 71.9, 123.4), 'xy', {'stoneTable'}, 0.0),
    ('master bed', {'shifted-bedroom', 'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 3.155, 7.511, 199.1, 210.1), 'xy',
     {'boucle', 'oakVeneer', 'sheet', 'linenSage', 'linenBlush'}, 0.0),
    ('nightstand north', {'shifted-bedroom', 'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 2.418, 8.79, 51.6, 46.5), 'xy', {'walnut'}, 0.0),
    ('nightstand south', {'shifted-bedroom', 'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 2.418, 6.231, 51.6, 46.6), 'xy', {'walnut'}, 0.0),
    ('bathroom-door cupboard', {'shifted-bedroom', 'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 0.863, 5.561, 61.8, 87.2), 'xy',
     {'whiteLacquer', 'bronzeGlass', 'walnut'}, 0.0),
    ('south wardrobe', {'shifted-bedroom', 'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 1.564, 4.857, 189.9, 61.8), 'xy',
     {'whiteLacquer', 'bronzeGlass'}, 0.0),
    ('appliance tower', {'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 8.1166, 5.9604, 90.0, 60.0), 'xy', {'whiteLacquer'}, 0.0),
    ('pantry', {'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 7.0707, 5.9604, 119.2, 60.0), 'xy', {'whiteLacquer'}, 0.0),
    ('master dresser', {'shifted-bedroom', 'naghams-changes', 'kareems-changes', 'karims-version'}, ('outline', 3.517, 4.775, 200.0, 45.0), 'xy', {'walnut'}, 0.0),
    # Kareem's en-suite: vanity wall to partition (its batten panel runs its length; the body is a GLB), and the
    # medicine cabinet over it (dashed outline, 0.30 out from the 2 cm battens)
    ('master vanity', {'kareems-changes', 'karims-version'}, ('outline', 0.856, 6.7276, 60.0, 118.5), 'y', {'oakSlats'}, 0.0),
    ('medicine cabinet', {'kareems-changes', 'karims-version'}, ('outline', 0.726, 6.7276, 30.0, 80.0), 'xy', {'oakVeneer', 'mirror'}, 0.0),
]

# A stand-in for three.js: real transforms and box sizes, everything else a do-nothing proxy.
MOCK = r"""
const P = new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => 0 : k === "then" ? undefined : P,
  set: () => true, apply: () => P, construct: () => P,
});
export class Vector3 {
  constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
  set(a, b, c) { this.x = a; this.y = b; this.z = c; return this; }
  setScalar(s) { return this.set(s, s, s); }
  copy(v) { return this.set(v.x, v.y, v.z); }
  clone() { return new Vector3(this.x, this.y, this.z); }
  lerp(v, t) { return this.set(this.x + (v.x - this.x) * t, this.y + (v.y - this.y) * t, this.z + (v.z - this.z) * t); }
  sub(v) { return this.set(this.x - v.x, this.y - v.y, this.z - v.z); }
  add(v) { return this.set(this.x + v.x, this.y + v.y, this.z + v.z); }
  multiplyScalar(s) { return this.set(this.x * s, this.y * s, this.z * s); }
  normalize() { return this; }
  distanceTo(v) { return Math.hypot(this.x - v.x, this.y - v.y, this.z - v.z); }
}
const vec = (x = 0, y = 0, z = 0) => new Vector3(x, y, z);
export class Object3D {
  constructor() { this.position = vec(); this.rotation = vec(); this.scale = vec(1, 1, 1); this.children = [];
    this.userData = {}; this.quaternion = P; }
  add(...c) { this.children.push(...c); return this; }
  traverse(f) { f(this); for (const c of this.children) c.traverse(f); }
  updateMatrixWorld() {}
}
export class Group extends Object3D {}
export class Mesh extends Object3D { constructor(g, m) { super(); this.geometry = g; this.material = m; this.isMesh = true; } }
export class BoxGeometry { constructor(w, h, d) { this.box = [w, h, d]; this.attributes = { position: { count: 0 } }; }
  setAttribute() {} }
export class RoundedBoxGeometry extends BoxGeometry {}
export class Vector2 { constructor(x = 0, y = 0) { this.x = x; this.y = y; } }
export class GLTFLoader { loadAsync() { return new Promise(() => {}); } }
export const mergeGeometries = () => P;
export const Float32BufferAttribute = P, Shape = P, Path = P, ExtrudeGeometry = P, ShapeGeometry = P,
  CylinderGeometry = P, CircleGeometry = P, PlaneGeometry = P, SphereGeometry = P, TorusGeometry = P, CapsuleGeometry = P,
  CatmullRomCurve3 = P, Box3 = P, CanvasTexture = P, Color = P;
"""

RUN = r"""
import { readFileSync } from "fs";
import * as THREE from "./three.mjs";
import { furnish } from "./furnish.mjs";
const [, , modelPath, version] = process.argv;
const window = {};
new Function("window", readFileSync(modelPath, "utf8"))(window);
const mats = new Map();
const material = name => ({ name, transparent: false, opacity: 1, userData: {}, color: { setRGB() {} },
  clone() { return material(name + "*"); } });
const mat = new Proxy({}, { get: (t, k) => {
  if (k === "art") return [material("art")];
  if (!mats.has(k)) mats.set(k, material(k));
  return mats.get(k);
} });
const scene = new THREE.Group();
furnish(scene, window.MODEL, mat, version);
// local to parent: T * Rx * Ry * Rz (three's default XYZ Euler order) * S, applied to box corners
const rot = (p, r) => {
  let [x, y, z] = p;
  [x, y] = [x * Math.cos(r.z) - y * Math.sin(r.z), x * Math.sin(r.z) + y * Math.cos(r.z)];
  [x, z] = [x * Math.cos(r.y) + z * Math.sin(r.y), -x * Math.sin(r.y) + z * Math.cos(r.y)];
  [y, z] = [y * Math.cos(r.x) - z * Math.sin(r.x), y * Math.sin(r.x) + z * Math.cos(r.x)];
  return [x, y, z];
};
const place = (p, o) => {
  const s = [p[0] * o.scale.x, p[1] * o.scale.y, p[2] * o.scale.z];
  const [x, y, z] = rot(s, o.rotation);
  return [x + o.position.x, y + o.position.y, z + o.position.z];
};
const out = [];
const walk = (o, chain) => {
  const c = [...chain, o];
  if (o.isMesh && o.geometry && o.geometry.box) {
    const [w, h, d] = o.geometry.box, pts = [];
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
      let p = [sx * w / 2, sy * h / 2, sz * d / 2];
      for (let k = c.length - 1; k >= 0; k--) p = place(p, c[k]);
      pts.push(p);
    }
    const xs = pts.map(p => p[0]), ys = pts.map(p => -p[2]), hs = pts.map(p => p[1]);
    out.push([o.material.name, Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys), Math.min(...hs), Math.max(...hs)]);
  }
  for (const k of o.children) walk(k, c);
};
walk(scene, []);
console.log(JSON.stringify(out));
"""


def boxes_3d(version):
    """Every box furnish.js builds for this version: (material, x0, x1, y0, y1, h0, h1), plan metres."""
    src = (ROOT / f'furnish-{version}.js').read_text()
    src = re.sub(r'from "three[^"]*"', 'from "./three.mjs"', src)
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'three.mjs').write_text(MOCK)
        Path(d, 'furnish.mjs').write_text(src)
        Path(d, 'run.mjs').write_text(RUN)
        r = subprocess.run(['node', str(Path(d, 'run.mjs')), str(ROOT / MODELS[version]), version],
                           capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'furnish-{version}.js failed under node:\n{r.stderr}')
    return [b for b in json.loads(r.stdout) if None not in b]  # NaN (sizes from stand-in values) -> null


def plan_box(e):
    b = ebbox.extents([e])
    return b.extmin.x - ORIGIN[0], b.extmax.x - ORIGIN[0], b.extmin.y - ORIGIN[1], b.extmax.y - ORIGIN[1]


def dwg_box(msp, src):
    if src[0] == 'block':
        e = msp.query(f'INSERT[name=="{src[1]}"]')
        return plan_box(e[0]) if e else None
    _, sx, sy, w, d = src
    best = None
    for e in msp.query('LWPOLYLINE[layer=="2furni"]'):
        if not e.closed and len(e) < 4:
            continue
        b = plan_box(e)
        cx, cy = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2
        err = abs((b[1] - b[0]) * 100 - w) + abs((b[3] - b[2]) * 100 - d) + 100 * (abs(cx - sx) + abs(cy - sy))
        if err < 30 and (best is None or err < best[0]):
            best = (err, b)
    return best and best[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dxf')
    ap.add_argument('--version', required=True, choices=sorted(MODELS))
    a = ap.parse_args()
    msp = recover.readfile(a.dxf)[0].modelspace()
    boxes = boxes_3d(a.version)
    flags = 0
    print(f'{a.dxf} / furnish-{a.version}.js, cm: DWG size @ centre vs 3D size @ centre')
    for name, versions, src, axes, mats, margin in ITEMS:
        if versions and a.version not in versions:
            continue
        b = dwg_box(msp, src)
        if b is None:
            print(f'  FLAG {name}: not found in the DWG')
            flags += 1
            continue
        mx, my = margin if isinstance(margin, tuple) else (margin, margin)
        sel = [x for x in boxes if x[0] in mats and b[0] - mx <= (x[1] + x[2]) / 2 <= b[1] + mx
               and b[2] - my <= (x[3] + x[4]) / 2 <= b[3] + my]
        if not sel:
            print(f'  FLAG {name}: no 3D boxes of {sorted(mats)} inside the DWG outline')
            flags += 1
            continue
        t = (min(x[1] for x in sel), max(x[2] for x in sel), min(x[3] for x in sel), max(x[4] for x in sel))
        parts = []
        bad = False
        for ax in axes:
            i = 0 if ax == 'x' else 2
            ds, dc = b[i + 1] - b[i], (b[i] + b[i + 1]) / 2
            ts, tc = t[i + 1] - t[i], (t[i] + t[i + 1]) / 2
            off = abs(ts - ds) > TOL or abs(tc - dc) > TOL
            bad |= off
            parts.append(f'{ax}: {ds * 100:6.1f} @ {dc * 100:7.1f} vs {ts * 100:6.1f} @ {tc * 100:7.1f}{" <" if off else ""}')
        flags += bad
        print(f'  {"FLAG" if bad else "ok  "} {name:24s} ' + '   '.join(parts))
    print('all key items within 2 cm' if not flags else f'{flags} item(s) off by more than 2 cm')
    return 1 if flags else 0


if __name__ == '__main__':
    sys.exit(main())
