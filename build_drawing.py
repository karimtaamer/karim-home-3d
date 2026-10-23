#!/usr/bin/env python3
"""Flatten a DXF floor plan into drawing.json (linework, fills, text, snap points) for the 2D drawing view.

Coordinates are plan metres relative to model.js's origin, so the drawing lines up with the 3D model.

Usage: ~/.dwg-tools/bin/python build_drawing.py <plan.dxf> [--model model.js] [--out drawing.json]
(another plan version pairs its own files, e.g. --model model-bigger-bedroom.js --out drawing-bigger-bedroom.json)
"""
import json
import math
import sys
from pathlib import Path

from ezdxf import colors, recover
from ezdxf import path as ezpath
from ezdxf.render import hatching

HERE = Path(__file__).parent
MARGIN = 1.0  # drawing kept this far past the model's bounds (m)
FLATTEN = 0.003  # curve tolerance (m)
CURVES = ("ARC", "CIRCLE", "ELLIPSE", "SPLINE")
DOOR_LAYER = "3door"


def arg(k, default):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else default


def load_model():
    s = (HERE / arg("--model", "model.js")).read_text()
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


def main():
    doc, _ = recover.readfile(Path(sys.argv[1]))
    M = load_model()
    ox, oy = M["origin"]
    W, D = M["bounds"]
    x0, y0, x1, y1 = ox - MARGIN, oy - MARGIN, ox + W + MARGIN, oy + D + MARGIN
    inside = lambda pts: any(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pts)
    P = lambda x, y: (round(x - ox, 4), round(y - oy, 4))

    def rgb(e, layer, parent_rgb):
        if e.dxf.hasattr("true_color"):
            return "#%02x%02x%02x" % colors.int2rgb(e.dxf.true_color)
        aci = e.dxf.get("color", 256)
        if aci == 0:
            return parent_rgb
        if aci == 256:
            l = doc.layers.get(layer)
            aci = abs(l.dxf.color) if l else 7
        return "#%02x%02x%02x" % colors.aci2rgb(aci) if aci != 7 else "#ffffff"

    strokes, fills, texts, snaps = {}, {}, [], set()

    def stroke(col, pts):
        if len(pts) > 1 and inside(pts):
            strokes.setdefault(col, []).append([c for p in pts for c in P(*p)])
            return True

    def snap(x, y, kind):  # kind: 0 endpoint, 1 midpoint, 2 centre
        if x0 <= x <= x1 and y0 <= y <= y1:
            snaps.add((*P(x, y), kind))

    # Dynamic door blocks carry every leaf size at once; draw only the live one, which is the swing
    # build_geometry.py picked for that door (its arc, plus the open leaf from the hinge).
    swings = [((s["hinge"][0] + ox, s["hinge"][1] + oy), s["r"], (s["closed"][0] + ox, s["closed"][1] + oy))
              for s in M.get("swings", [])]

    def arcs_in(entities, depth=0):
        for e in entities:
            if e.dxftype() == "INSERT" and depth < 6:
                yield from arcs_in(e.virtual_entities(), depth + 1)
            elif e.dxftype() == "ARC":
                yield e

    def door(e, layer, col):
        at = (e.dxf.insert.x, e.dxf.insert.y)
        s = next((s for s in swings if math.dist(s[0], at) < 0.3), None)
        if s is None:
            return False
        _, r, closed = s
        fits = [a for a in arcs_in(e.virtual_entities()) if abs(a.dxf.radius - r) < 0.02]
        if not fits:
            return False
        ends = lambda a: [(a.start_point.x, a.start_point.y), (a.end_point.x, a.end_point.y)]
        arc = min(fits, key=lambda a: min(math.dist(p, closed) for p in ends(a)))
        pts = [(v.x, v.y) for v in ezpath.make_path(arc).flattening(FLATTEN)]
        c = arc.ocs().to_wcs(arc.dxf.center)
        leaf = max(ends(arc), key=lambda p: math.dist(p, closed))
        col = rgb(arc, layer if arc.dxf.layer == "0" else arc.dxf.layer, col)
        stroke(col, pts)
        stroke(col, [(c.x, c.y), leaf])
        for x, y in [(c.x, c.y), *ends(arc)]:
            snap(x, y, 0)
        return True

    def walk(entities, parent_layer="0", parent_rgb="#ffffff", depth=0):
        for e in entities:
            t = e.dxftype()
            layer = e.dxf.get("layer", "0")
            if layer == "0":  # block content on layer 0 takes the insert's layer
                layer = parent_layer
            l = doc.layers.get(layer)
            if l and (l.is_off() or l.is_frozen()):
                continue
            col = rgb(e, layer, parent_rgb)
            try:
                if t == "INSERT" and layer == DOOR_LAYER and door(e, layer, col):
                    continue
                if t in ("INSERT", "DIMENSION") and depth < 6:
                    walk(e.virtual_entities(), layer, col, depth + 1)
                elif t == "HATCH":
                    loops = [[(v.x, v.y) for v in p.flattening(FLATTEN)] for p in ezpath.from_hatch(e)]
                    if not any(inside(lp) for lp in loops):
                        continue
                    if e.dxf.solid_fill:
                        fills.setdefault(col, []).append([[c for p in lp for c in P(*p)] for lp in loops])
                    else:
                        for lp in loops:
                            stroke(col, lp)
                        for a, b in hatching.hatch_entity(e):
                            stroke(col, [(a.x, a.y), (b.x, b.y)])
                elif t in ("SOLID", "TRACE"):
                    v = [e.dxf.get(k) for k in ("vtx0", "vtx1", "vtx3", "vtx2")]
                    pts = [(p.x, p.y) for p in v if p is not None]
                    if inside(pts):
                        fills.setdefault(col, []).append([[c for p in pts for c in P(*p)]])
                elif t in ("TEXT", "MTEXT", "ATTRIB"):
                    if t == "MTEXT":
                        s, at, h = e.plain_text(), e.dxf.insert, e.dxf.char_height
                        rot = math.radians(e.get_rotation())
                        align = (e.dxf.get("attachment_point", 1) - 1) % 3  # 0 left, 1 centre, 2 right
                        base = "top" if e.dxf.get("attachment_point", 1) <= 3 else "middle"
                    else:
                        s, h, rot = e.dxf.text, e.dxf.height, math.radians(e.dxf.get("rotation", 0))
                        halign = e.dxf.get("halign", 0)
                        at = e.dxf.align_point if halign and e.dxf.hasattr("align_point") else e.dxf.insert
                        align, base = min(halign, 2), "alphabetic"
                    at = e.ocs().to_wcs(at) if t != "MTEXT" else at
                    if s.strip() and x0 <= at.x <= x1 and y0 <= at.y <= y1:
                        texts.append({"t": s, "x": P(at.x, at.y)[0], "y": P(at.x, at.y)[1], "h": round(h, 4),
                                      "r": round(rot, 4), "a": align, "b": base, "c": col})
                else:
                    p = ezpath.make_path(e)
                    pts = [(v.x, v.y) for v in p.flattening(FLATTEN)]
                    if not stroke(col, pts):
                        continue
                    if t in CURVES:
                        if t in ("ARC", "CIRCLE"):
                            c = e.ocs().to_wcs(e.dxf.center)
                            snap(c.x, c.y, 2)
                        if t != "CIRCLE":
                            snap(*pts[0], 0)
                            snap(*pts[-1], 0)
                        continue
                    # Straight-edged paths: every corner is an endpoint, every straight edge has a midpoint.
                    corners = [(v.x, v.y) for v in p.control_vertices()] if not p.has_curves else pts[:1] + pts[-1:]
                    for x, y in corners:
                        snap(x, y, 0)
                    for (ax, ay), (bx, by) in zip(corners, corners[1:]):
                        if not p.has_curves and math.hypot(bx - ax, by - ay) > 0.02:
                            snap((ax + bx) / 2, (ay + by) / 2, 1)
            except (TypeError, ValueError, AttributeError):
                continue  # entity types the path builder can't read (images, proxies...)

    walk(doc.modelspace())
    out = HERE / arg("--out", "drawing.json")
    out.write_text(json.dumps({
        "bounds": [round(W, 4), round(D, 4)],
        "strokes": strokes, "fills": fills, "texts": texts,
        "snaps": [c for s in sorted(snaps) for c in s],
    }, separators=(",", ":")))
    n = sum(len(v) for v in strokes.values())
    print(f"{out.name}: {n} polylines, {sum(len(v) for v in fills.values())} fills, {len(texts)} texts, "
          f"{len(snaps)} snap points, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
