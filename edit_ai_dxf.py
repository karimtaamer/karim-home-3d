#!/usr/bin/env python3
"""Edit AI's hands on a plan DXF (run with a Python that has ezdxf: ~/.dwg-tools/bin/python here, the function's
own on Vercel). edit_ai.py calls it; coordinates in and out are plan metres in model.js's frame (plan = DWG - origin).

    edit_ai_dxf.py query IN.dxf --origin ox,oy --bbox x0,y0,x1,y1 [--layers 1wall,2furni]   -> JSON list of entities
    edit_ai_dxf.py edit  IN.dxf OUT.dxf --origin ox,oy  < ops.json                          -> JSON report

Edit ops (a JSON list), handles as `query` gives them:
    {"op": "move", "handles": [...], "dx": 0.1, "dy": 0}          translate entities (blocks move by their insert)
    {"op": "copy", "handles": [...], "dx": 0.1, "dy": 0}          copies, translated; reports the new handles
    {"op": "delete", "handles": [...]}
    {"op": "add_line", "layer": "1wall", "a": [x, y], "b": [x, y]}
    {"op": "add_polyline", "layer": "2furni", "points": [[x, y], ...], "closed": true}
    {"op": "set_points", "handle": "1A2", "points": [[x, y], ...]}  a LINE's two ends or an LWPOLYLINE's vertices
    {"op": "move_window", "handle": "163A", "dx": 0.7, "dy": 0, "width": 1.2}
    {"op": "move_window", "handle": "163A", "centre_on": "1692"}      or "centre": [3.185, null] (plan metres)
        the whole window (every Windows-layer line joined to that one: both glazing faces, jambs, mullions) slides by
        dx, dy and, with width, is resized about its new centre; the wall face lines it sits in are re-cut so the old
        opening is closed with wall and the new one left open. Reports the window's old and new centre and width.
        Instead of dx, dy: "centre_on" (a handle, or a list of handles, of a piece to centre it on) or "centre"
        ([x, y], either may be null); the window only slides along its own wall towards it.
    {"op": "move_piece", "handle": "1692", "dx": -0.2, "dy": 0}
        a furniture piece on the plan: its outline (a 2furni polyline of 4+ points) and every 2furni bit drawn inside it
        (pillows, sheet fold, basin bowl...), and nothing else - not a nightstand or rug that only overlaps the box.
    {"op": "resize_piece", "handle": "1692", "x_size": 1.8, "y_size": null, "anchor": "N"}
        the same piece scaled to a new extent along plan x and / or y (metres; null keeps it); anchor names the sides
        that stay put ("N" keeps the north edge - a headboard on the north wall; "SW" a corner); default the centre.
    {"op": "move_door", "handle": "16FA", "along": 0.2, "width": 0.8}
        a door drawn loose (its swing ARC is the handle): swing, leaf, jambs and frame bits slide along their wall by
        `along` metres (+ = towards +x / +y; or dx, dy, projected on the wall) and, with width, the leaf (= swing
        radius) is resized, the far jamb moving; the wall faces either side are re-cut to meet the frame again.
Any edit that leaves one window's long lines out of line with each other (one glazing line left behind) is reported
under "warnings".
New entities copy colour and linetype ByLayer. No TEXT is ever added (every TEXT becomes a room label in the 3D).
"""
import argparse, json, math, sys
from collections import Counter

from ezdxf import recover
from shapely.geometry import LineString
from shapely.ops import unary_union

WINDOW_LAYER, WALL_LAYER = "Windows", "1wall"
FURNI = ("2furni", "2 furni")
DOOR_PART_LAYERS = {"1wall", "3door", "_DIM"}

ADD_LAYERS = {"1wall", "Windows", "2furni", "2 furni", "Glass", "3door", "_DIM"}


def r(v):
    return round(v, 4)


def describe(e, ox, oy):
    t = e.dxftype()
    d = {"handle": e.dxf.handle, "type": t, "layer": e.dxf.layer}
    P = lambda p: [r(p[0] - ox), r(p[1] - oy)]
    if t == "LINE":
        d["points"] = [P(e.dxf.start), P(e.dxf.end)]
    elif t == "LWPOLYLINE":
        d["points"] = [P(p) for p in e.get_points("xy")]
        d["closed"] = bool(e.closed)
        if len(d["points"]) >= 4:  # an outline (bed, table, rug): its centre, so nobody has to do the sum
            xs, ys = [q[0] for q in d["points"]], [q[1] for q in d["points"]]
            d["centre"] = [r((min(xs) + max(xs)) / 2), r((min(ys) + max(ys)) / 2)]
    elif t in ("ARC", "CIRCLE"):
        d["centre"], d["radius"] = P(e.dxf.center), r(e.dxf.radius)
        if t == "ARC":
            d["angles"] = [r(e.dxf.start_angle), r(e.dxf.end_angle)]
    elif t == "INSERT":
        d["block"], d["insert"], d["rotation"] = e.dxf.name, P(e.dxf.insert), r(e.dxf.get("rotation", 0))
    elif t in ("TEXT", "MTEXT"):
        d["insert"] = P(e.dxf.insert)
        d["text"] = e.dxf.text if t == "TEXT" else e.text
    else:
        return None
    return d


def pts(d):
    if "points" in d:
        return d["points"]
    if "centre" in d:
        (x, y), rad = d["centre"], d["radius"]
        return [[x - rad, y - rad], [x + rad, y + rad]]
    return [d["insert"]]


def in_box(d, b):
    p = pts(d)
    xs, ys = [q[0] for q in p], [q[1] for q in p]
    return not (max(xs) < b[0] or min(xs) > b[2] or max(ys) < b[1] or min(ys) > b[3])


def query(a):
    doc, _ = recover.readfile(a.src)
    ox, oy = map(float, a.origin.split(","))
    b = list(map(float, a.bbox.split(",")))
    b = [min(b[0], b[2]), min(b[1], b[3]), max(b[0], b[2]), max(b[1], b[3])]
    layers = set(a.layers.split(",")) if a.layers else None
    out = []
    for e in doc.modelspace():
        if layers and e.dxf.layer not in layers:
            continue
        d = describe(e, ox, oy)
        if d and in_box(d, b):
            if len(d.get("points", [])) > 8:  # curves drawn as many short segments: their extent is enough to pick them
                ps = d.pop("points")
                d["bbox"] = [min(q[0] for q in ps), min(q[1] for q in ps), max(q[0] for q in ps), max(q[1] for q in ps)]
                d["n_points"] = len(ps)
            out.append(d)
    # Piece outlines first (they're what an edit is usually about), tiny bits last, so a cut-off list keeps them.
    size = lambda d: (lambda p: (max(q[0] for q in p) - min(q[0] for q in p)) * (max(q[1] for q in p) - min(q[1] for q in p)))(
        d.get("points") or [d["bbox"][:2], d["bbox"][2:]] if ("points" in d or "bbox" in d) else [[0, 0], [0, 0]])
    out.sort(key=lambda d: (d["layer"], "centre" not in d or d["type"] != "LWPOLYLINE", -size(d) if "centre" in d else 0, d["type"]))
    print(json.dumps({"count": len(out), "entities": out[:int(a.limit)], "truncated": len(out) > int(a.limit)}))


def segs_of(e):
    t = e.dxftype()
    if t == "LINE":
        return [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))]
    if t == "LWPOLYLINE":
        p = [(q[0], q[1]) for q in e.get_points("xy")]
        if e.closed and len(p) > 2:
            p.append(p[0])
        return list(zip(p, p[1:]))
    return []


def window_cluster(msp, seed):
    """Every Windows-layer LINE / LWPOLYLINE joined (within 3 cm) to the seed entity: one window."""
    cands = [e for e in msp if e.dxf.layer == WINDOW_LAYER and segs_of(e)]
    geo = {e.dxf.handle: unary_union([LineString(s) for s in segs_of(e)]) for e in cands}
    group, grown = {seed.dxf.handle}, True
    while grown:
        grown = False
        g = unary_union([geo[h] for h in group]).buffer(0.03)
        for e in cands:
            h = e.dxf.handle
            if h not in group and g.intersects(geo[h]):
                group.add(h)
                grown = True
    return [e for e in cands if e.dxf.handle in group]


def frame(ents):
    """The window's long axis u, normal n, centre and extents: (c, u, n, t0, t1, n0, n1) in DWG units."""
    g = unary_union([LineString(s) for e in ents for s in segs_of(e)])
    r = list(g.minimum_rotated_rectangle.exterior.coords) if g.length else []
    a, b = max(((r[0], r[1]), (r[1], r[2])), key=lambda ed: math.dist(*ed))
    L = math.dist(a, b)
    u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    if abs(u[0]) >= abs(u[1]) and u[0] < 0 or abs(u[1]) > abs(u[0]) and u[1] < 0:
        u = (-u[0], -u[1])
    n = (-u[1], u[0])
    c = g.minimum_rotated_rectangle.centroid
    pts = [p for e in ents for s in segs_of(e) for p in s]
    ts = [(p[0] - c.x) * u[0] + (p[1] - c.y) * u[1] for p in pts]
    ns = [(p[0] - c.x) * n[0] + (p[1] - c.y) * n[1] for p in pts]
    return (c.x, c.y), u, n, min(ts), max(ts), min(ns), max(ns)


def misaligned(ents):
    """Long lines of one window that don't share its ends (a glazing line left behind by a partial move)."""
    if len(ents) < 2:
        return None
    (cx, cy), u, n, t0, t1, *_ = frame(ents)
    bad = []
    for e in ents:
        for s in segs_of(e):
            d = math.dist(*s)
            if d < 0.3 or abs((s[1][0] - s[0][0]) * u[0] + (s[1][1] - s[0][1]) * u[1]) / d < 0.98:
                continue  # jambs and short bits
            ts = sorted((p[0] - cx) * u[0] + (p[1] - cy) * u[1] for p in s)
            if abs(ts[0] - t0) > 0.02 or abs(ts[1] - t1) > 0.02:
                bad.append(e.dxf.handle)
                break
    return bad or None


def recut_walls(msp, c, u, n, t0, t1, n0, n1, c2, w2):
    """Wall face lines along the window: close the old opening [t0, t1] and open the new one (centre c2, width w2).
    A face line that already ran on across the old opening (an inner face drawn through) is left alone."""
    T = lambda p: (p[0] - c[0]) * u[0] + (p[1] - c[1]) * u[1]
    N = lambda p: (p[0] - c[0]) * n[0] + (p[1] - c[1]) * n[1]
    a2 = T(c2) - w2 / 2
    b2 = a2 + w2
    lo, hi = min(t0, a2) - 0.05, max(t1, b2) + 0.05
    faces = {}
    for e in msp.query(f'LINE[layer=="{WALL_LAYER}"]'):
        s = segs_of(e)[0]
        d = math.dist(*s)
        if d < 1e-4 or abs((s[1][0] - s[0][0]) * u[0] + (s[1][1] - s[0][1]) * u[1]) / d < 0.999:
            continue
        nn = (N(s[0]) + N(s[1])) / 2
        if not (n0 - 0.03 <= nn <= n1 + 0.03):
            continue
        ta, tb = sorted((T(s[0]), T(s[1])))
        if tb < lo or ta > hi:
            continue
        faces.setdefault(round(nn / 0.005), []).append((e, ta, tb, nn))
    log = []
    for segs in faces.values():
        cover = sum(max(0, min(tb, t1) - max(ta, t0)) for _, ta, tb, _ in segs)
        if cover > 0.9 * (t1 - t0):
            continue  # this face runs through the window already
        nn = sum(x[3] for x in segs) / len(segs)
        iv = sorted([(ta, tb) for _, ta, tb, _ in segs] + [(t0, t1)])
        merged = []
        for a, b in iv:
            if merged and a <= merged[-1][1] + 0.002:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        keep = []
        for a, b in merged:
            for x, y in ((a, min(b, a2)), (max(a, b2), b)):
                if y - x > 0.002:
                    keep.append((x, y))
        attrs = {k: segs[0][0].dxf.get(k) for k in ("layer", "linetype", "color") if segs[0][0].dxf.hasattr(k)}
        ends = [(T(q), (q[0], q[1])) for e, *_ in segs for q in segs_of(e)[0]]

        def P(t):  # an existing end stays exactly where it was (its junction holds); a new one sits on the face
            hit = min(ends, key=lambda x: abs(x[0] - t))
            if abs(hit[0] - t) < 0.002:
                return hit[1]
            return (c[0] + u[0] * t + n[0] * nn, c[1] + u[1] * t + n[1] * nn)
        for e, *_ in segs:
            msp.delete_entity(e)
        for a, b in keep:
            msp.add_line(P(a), P(b), dxfattribs=attrs)
        log.append(f"wall face {round(nn, 3)}: {len(segs)} line(s) -> {len(keep)}")
    return log


def ext_of(e):
    from ezdxf import bbox as _bbox
    x = _bbox.extents([e])
    if not x.has_data:
        return None
    return (x.extmin.x, x.extmin.y, x.extmax.x, x.extmax.y)


def piece_members(msp, outline, m=0.08):
    """The outline plus every furniture entity inside it whose smallest enclosing outline is this one."""
    if outline.dxf.layer not in FURNI or outline.dxftype() != "LWPOLYLINE" or len(outline) < 4:
        raise ValueError(f"{outline.dxf.handle} is not a furniture outline (a {outline.dxf.layer} {outline.dxftype()}); "
                         "pick the piece's outline polyline (4+ points) from dxf_query")
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    inside = lambda a, b: a[0] >= b[0] - m and a[1] >= b[1] - m and a[2] <= b[2] + m and a[3] <= b[3] + m
    furni = [(e, ext_of(e)) for e in msp if e.dxf.layer in FURNI]
    furni = [(e, b) for e, b in furni if b]
    outlines = [(e, b) for e, b in furni if e.dxftype() == "LWPOLYLINE" and len(e) >= 4 and area(b) >= 0.04]
    ob = ext_of(outline)
    out = [outline]
    for e, b in furni:
        if e is outline or not inside(b, ob):
            continue
        owners = [(area(b2), o) for o, b2 in outlines if o is not e and inside(b, b2) and area(b2) >= area(b) * 1.05]
        if owners and min(owners, key=lambda x: x[0])[1] is outline:
            out.append(e)
    return out, ob


def scale_entity(e, a, kx, ky):
    """Scale e about point a by kx along x and ky along y."""
    f = lambda p: (a[0] + (p[0] - a[0]) * kx, a[1] + (p[1] - a[1]) * ky)
    t = e.dxftype()
    if t == "LINE":
        e.dxf.start, e.dxf.end = (*f(e.dxf.start), 0), (*f(e.dxf.end), 0)
    elif t == "LWPOLYLINE":
        e.set_points([(*f(q[:2]), *q[2:]) for q in e.get_points("xyseb")], format="xyseb")
    elif t in ("ARC", "CIRCLE"):
        c = f(e.dxf.center)
        e.dxf.center = (c[0], c[1], e.dxf.center[2])
        e.dxf.radius *= min(kx, ky)
    elif t == "INSERT":
        e.dxf.insert = (*f(e.dxf.insert), 0)
        if abs(e.dxf.get("rotation", 0)) % 180 < 1:
            e.dxf.xscale, e.dxf.yscale = e.dxf.get("xscale", 1) * kx, e.dxf.get("yscale", 1) * ky
        else:
            e.dxf.xscale, e.dxf.yscale = e.dxf.get("xscale", 1) * ky, e.dxf.get("yscale", 1) * kx
    else:
        from ezdxf.math import Matrix44
        e.transform(Matrix44.translate(-a[0], -a[1], 0) @ Matrix44.scale(kx, ky, 1) @ Matrix44.translate(a[0], a[1], 0))


def door_frame(msp, arc):
    """A loose door from its swing arc: hinge c, wall axis u, normal n, gap [t0, t1] along u (from c), wall faces
    n0..n1, the side s (+1 / -1) the closed leaf runs to, and every entity that belongs to the door."""
    c = (arc.dxf.center.x, arc.dxf.center.y)
    rad = arc.dxf.radius
    walls = []
    for e in msp.query(f'LINE[layer=="{WALL_LAYER}"]'):
        s_ = segs_of(e)[0]
        if math.dist(*s_) > 0.03:
            walls.append((e, s_))
    near = [(min(math.dist(c, p) for p in s_), e, s_) for e, s_ in walls]
    near = [x for x in near if x[0] < 0.25]
    if not near:
        raise ValueError("no wall face ends near this swing's hinge; is it a door swing ARC?")
    _, _, s_ = min(near, key=lambda x: x[0])
    L = math.dist(*s_)
    u = ((s_[1][0] - s_[0][0]) / L, (s_[1][1] - s_[0][1]) / L)
    if abs(u[0]) >= abs(u[1]) and u[0] < 0 or abs(u[1]) > abs(u[0]) and u[1] < 0:
        u = (-u[0], -u[1])
    n = (-u[1], u[0])
    T = lambda p: (p[0] - c[0]) * u[0] + (p[1] - c[1]) * u[1]
    N = lambda p: (p[0] - c[0]) * n[0] + (p[1] - c[1]) * n[1]
    ends = [(arc.start_point.x, arc.start_point.y), (arc.end_point.x, arc.end_point.y)]
    closed = min(ends, key=lambda p: abs(N(p)))  # the closed leaf lies along the wall
    s = 1 if T(closed) > 0 else -1
    faces = {}
    for e, s2 in walls:
        d = math.dist(*s2)
        if abs((s2[1][0] - s2[0][0]) * u[0] + (s2[1][1] - s2[0][1]) * u[1]) / d < 0.999:
            continue
        nn = (N(s2[0]) + N(s2[1])) / 2
        ta, tb = sorted((T(s2[0]), T(s2[1])))
        if abs(nn) < 0.4 and tb > -rad - 1.0 and ta < rad + 1.0:
            faces.setdefault(round(nn / 0.005), []).append((ta, tb, nn))
    mid = s * rad / 2
    t0s, t1s, nns = [], [], []
    for segs in faces.values():
        if any(ta <= mid <= tb for ta, tb, _ in segs):
            continue  # this face runs across the opening (not one of its faces)
        lo = [tb for ta, tb, _ in segs if tb <= mid]
        hi = [ta for ta, tb, _ in segs if ta >= mid]
        if lo and hi:
            t0s.append(max(lo)); t1s.append(min(hi)); nns.append(segs[0][2])
    if not nns:
        raise ValueError("couldn't find the wall faces either side of this door")
    t0, t1 = min(t0s), max(t1s)
    n0, n1 = min(nns), max(nns)
    sw_lo, sw_hi = min(n0, min(N(p) for p in ends + [c])), max(n1, max(N(p) for p in ends + [c]))
    parts = []
    for e in msp:
        if e.dxf.layer not in DOOR_PART_LAYERS and e.dxftype() != "HATCH":
            continue
        b = ext_of(e)
        if not b:
            continue
        corners = [(b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])]
        ts, ns = [T(p) for p in corners], [N(p) for p in corners]
        if min(ts) >= t0 - 0.02 and max(ts) <= t1 + 0.02 and min(ns) >= sw_lo - 0.05 and max(ns) <= sw_hi + 0.05:
            parts.append(e)
    opened = max(ends, key=lambda p: abs(N(p)))
    return c, rad, u, n, t0, t1, n0, n1, s, parts, opened


def edit(a):
    doc, _ = recover.readfile(a.src)
    msp = doc.modelspace()
    ox, oy = map(float, a.origin.split(","))
    W = lambda p: (float(p[0]) + ox, float(p[1]) + oy)
    before = Counter(e.dxf.layer for e in msp)
    ops = json.load(sys.stdin)
    log, new, touched, moved = [], [], set(), []

    layers_hit = set()

    pieces0 = {}  # furniture outlines touched: their extent before

    def get(h):
        touched.add(h)
        e = doc.entitydb.get(h)
        if e is None or not e.is_alive or e.get_layout() is None or e.get_layout().name != msp.name:
            raise ValueError(f"no model-space entity with handle {h}")
        layers_hit.add(e.dxf.layer)
        if h not in pieces0 and e.dxf.layer in FURNI and e.dxftype() == "LWPOLYLINE" and len(e) >= 4:
            pieces0[h] = ext_of(e)
        return e

    def attrs(layer):
        if layer not in ADD_LAYERS:
            raise ValueError(f"layer {layer!r} is not one Edit AI may draw on ({', '.join(sorted(ADD_LAYERS))})")
        layers_hit.add(layer)
        if layer not in doc.layers:
            doc.layers.add(layer)
        return {"layer": layer}

    for o in ops:
        k = o.get("op")
        if k == "move":
            for h in o["handles"]:
                get(h).translate(float(o["dx"]), float(o["dy"]), 0)
            log.append(f"moved {len(o['handles'])} by ({o['dx']}, {o['dy']})")
        elif k == "copy":
            for h in o["handles"]:
                c = get(h).copy()
                msp.add_entity(c)
                c.translate(float(o["dx"]), float(o["dy"]), 0)
                new.append(c.dxf.handle)
            log.append(f"copied {len(o['handles'])} by ({o['dx']}, {o['dy']})")
        elif k == "delete":
            for h in o["handles"]:
                msp.delete_entity(get(h))
            log.append(f"deleted {len(o['handles'])}")
        elif k == "add_line":
            e = msp.add_line(W(o["a"]), W(o["b"]), dxfattribs=attrs(o["layer"]))
            new.append(e.dxf.handle)
            log.append(f"line {e.dxf.handle} on {o['layer']}")
        elif k == "add_polyline":
            e = msp.add_lwpolyline([W(p) for p in o["points"]], close=bool(o.get("closed")), dxfattribs=attrs(o["layer"]))
            new.append(e.dxf.handle)
            log.append(f"polyline {e.dxf.handle} on {o['layer']}")
        elif k == "set_points":
            e = get(o["handle"])
            p = [W(q) for q in o["points"]]
            if e.dxftype() == "LINE":
                if len(p) != 2:
                    raise ValueError("a LINE takes exactly two points")
                e.dxf.start, e.dxf.end = (*p[0], 0), (*p[1], 0)
            elif e.dxftype() == "LWPOLYLINE":
                e.set_points(p, format="xy")
            else:
                raise ValueError(f"set_points works on LINE / LWPOLYLINE, not {e.dxftype()}")
            log.append(f"reshaped {o['handle']}")
        elif k == "move_window":
            seed = get(o["handle"])
            if seed.dxf.layer != WINDOW_LAYER:
                raise ValueError(f"{o['handle']} is on {seed.dxf.layer}, not the Windows layer")
            ents = window_cluster(msp, seed)
            c, u, n, t0, t1, n0, n1 = frame(ents)
            w = t1 - t0
            dx, dy = float(o.get("dx", 0)), float(o.get("dy", 0))
            w2 = float(o["width"]) if o.get("width") else w
            mid = (t0 + t1) / 2
            c_old = (c[0] + u[0] * mid, c[1] + u[1] * mid)
            target = None
            if o.get("centre_on"):  # centre it on a piece (its outline's or block's extent), along the wall only
                from ezdxf import bbox as _bbox
                ext = _bbox.extents([get(h) for h in ([o["centre_on"]] if isinstance(o["centre_on"], str) else o["centre_on"])])
                target = ((ext.extmin.x + ext.extmax.x) / 2, (ext.extmin.y + ext.extmax.y) / 2)
            elif o.get("centre") is not None:  # plan metres; a null coordinate keeps the window's own
                cx, cy = o["centre"]
                target = (c_old[0] if cx is None else float(cx) + ox, c_old[1] if cy is None else float(cy) + oy)
            if target is not None:
                s_ = (target[0] - c_old[0]) * u[0] + (target[1] - c_old[1]) * u[1]
                dx, dy = u[0] * s_, u[1] * s_
            c_new = (c_old[0] + dx, c_old[1] + dy)
            walls = recut_walls(msp, c, u, n, t0, t1, n0, n1, c_new, w2)
            k_ = w2 / w
            for e in ents:
                touched.add(e.dxf.handle)
                def f(p):
                    t = (p[0] - c_old[0]) * u[0] + (p[1] - c_old[1]) * u[1]
                    q = (p[0] - u[0] * t, p[1] - u[1] * t)  # foot on the window's centre line
                    return (q[0] + u[0] * t * k_ + dx, q[1] + u[1] * t * k_ + dy)
                if e.dxftype() == "LINE":
                    a_, b_ = f(e.dxf.start), f(e.dxf.end)
                    e.dxf.start, e.dxf.end = (*a_, 0), (*b_, 0)
                else:
                    e.set_points([f(q) for q in e.get_points("xy")], format="xy")
            P = lambda q: [r(q[0] - ox), r(q[1] - oy)]
            moved.append({"window": [e.dxf.handle for e in ents], "old_centre": P(c_old), "new_centre": P(c_new),
                          "old_width": r(w), "new_width": r(w2), "walls": walls})
            e0, e1 = P((c_new[0] - u[0] * w2 / 2, c_new[1] - u[1] * w2 / 2)), P((c_new[0] + u[0] * w2 / 2, c_new[1] + u[1] * w2 / 2))
            moved[-1]["new_ends"] = [e0, e1]
            log.append(f"window of {len(ents)} lines moved by ({r(dx)}, {r(dy)}), width {r(w)} -> {r(w2)}; "
                       f"it now runs {e0} to {e1}, centre {P(c_new)}")
        elif k == "move_piece":
            ents, _ = piece_members(msp, get(o["handle"]))
            dx, dy = float(o.get("dx", 0)), float(o.get("dy", 0))
            for e in ents:
                touched.add(e.dxf.handle)
                e.translate(dx, dy, 0)
            b = ext_of(ents[0])
            log.append(f"piece {o['handle']} ({len(ents)} entities: {[e.dxf.handle for e in ents]}) moved by ({dx}, {dy}); "
                       f"outline now x {r(b[0] - ox)}..{r(b[2] - ox)}, y {r(b[1] - oy)}..{r(b[3] - oy)}")
        elif k == "resize_piece":
            ents, b = piece_members(msp, get(o["handle"]))
            w, h = b[2] - b[0], b[3] - b[1]
            kx = float(o["x_size"]) / w if o.get("x_size") else 1
            ky = float(o["y_size"]) / h if o.get("y_size") else 1
            an = (o.get("anchor") or "").upper()
            ax = b[0] if "W" in an else b[2] if "E" in an else (b[0] + b[2]) / 2
            ay = b[1] if "S" in an else b[3] if "N" in an else (b[1] + b[3]) / 2
            for e in ents:
                touched.add(e.dxf.handle)
                scale_entity(e, (ax, ay), kx, ky)
            b = ext_of(ents[0])
            log.append(f"piece {o['handle']} ({len(ents)} entities) resized {r(w)} x {r(h)} -> {r(b[2] - b[0])} x "
                       f"{r(b[3] - b[1])}; outline now x {r(b[0] - ox)}..{r(b[2] - ox)}, y {r(b[1] - oy)}..{r(b[3] - oy)}")
        elif k == "move_door":
            arc = get(o["handle"])
            if arc.dxftype() != "ARC":
                raise ValueError(f"{o['handle']} is a {arc.dxftype()}; give the door's swing ARC. A door drawn as a "
                                 "block (INSERT) can't be moved or resized here: tell the user it needs the engineer")
            c, rad, u, n, t0, t1, n0, n1, s, parts, opened = door_frame(msp, arc)
            if o.get("along") is not None:
                sh = float(o["along"])
            else:
                sh = float(o.get("dx", 0)) * u[0] + float(o.get("dy", 0)) * u[1]
            r2 = float(o["width"]) if o.get("width") else rad
            if not 0.5 <= r2 <= 1.3:
                raise ValueError("a door leaf is 0.5 to 1.3 m wide")
            dw = r2 - rad
            midt = (t0 + t1) / 2
            leaf, far, near_ = [], [], []
            for e in parts:
                touched.add(e.dxf.handle)
                if e is arc:
                    continue
                b = ext_of(e)
                big = max(b[2] - b[0], b[3] - b[1]) >= 0.5 * rad
                if big and e.dxftype() != "HATCH":
                    leaf.append(e)
                elif ((b[0] + b[2]) / 2 - c[0]) * u[0] * s + ((b[1] + b[3]) / 2 - c[1]) * u[1] * s > midt * s:
                    far.append(e)
                else:
                    near_.append(e)
            if dw:
                arc.dxf.radius = r2
                kk = r2 / rad
                d = math.dist(opened, c) or 1
                L = ((opened[0] - c[0]) / d, (opened[1] - c[1]) / d)  # the leaf as drawn: hinge to the swing's open end
                for e in leaf:  # stretch the leaf along its own length, from the hinge
                    def f(p):
                        a_ = (p[0] - c[0]) * L[0] + (p[1] - c[1]) * L[1]
                        return (p[0] + L[0] * a_ * (kk - 1), p[1] + L[1] * a_ * (kk - 1))
                    if e.dxftype() == "LINE":
                        e.dxf.start, e.dxf.end = (*f(e.dxf.start), 0), (*f(e.dxf.end), 0)
                    elif e.dxftype() == "LWPOLYLINE":
                        e.set_points([f(q) for q in e.get_points("xy")], format="xy")
                    else:
                        e.translate(L[0] * dw, L[1] * dw, 0)
                for e in far:
                    e.translate(u[0] * s * dw, u[1] * s * dw, 0)
            a2, b2 = (t0, t1 + dw) if s > 0 else (t0 - dw, t1)
            a2, b2 = a2 + sh, b2 + sh
            c2 = (c[0] + u[0] * (a2 + b2) / 2, c[1] + u[1] * (a2 + b2) / 2)
            walls = recut_walls(msp, c, u, n, t0, t1, n0, n1, c2, b2 - a2)
            for e in parts:
                e.translate(u[0] * sh, u[1] * sh, 0)
            P = lambda t: [r(c[0] + u[0] * t - ox), r(c[1] + u[1] * t - oy)]
            moved.append({"door": [e.dxf.handle for e in parts], "old_opening": [P(t0), P(t1)],
                          "new_opening": [P(a2), P(b2)], "leaf": [r(rad), r(r2)], "walls": walls})
            log.append(f"door of {len(parts)} entities: opening {P(t0)}..{P(t1)} ({r(t1 - t0)} m) -> {P(a2)}..{P(b2)} "
                       f"({r(b2 - a2)} m), leaf {r(rad)} -> {r(r2)} m")
        else:
            raise ValueError(f"unknown op {k!r}")
    # No zero-length lines left behind.
    zero = [e.dxf.handle for e in msp.query("LINE")
            if e.dxf.handle in touched | set(new) and (e.dxf.start - e.dxf.end).magnitude < 1e-4]
    for h in zero:
        msp.delete_entity(doc.entitydb.get(h))
    warnings, seen = [], set()
    for h in sorted(touched | set(new)):
        e = doc.entitydb.get(h)
        if e is None or not e.is_alive or e.dxf.layer != WINDOW_LAYER or h in seen or not segs_of(e):
            continue
        ents = window_cluster(msp, e)
        seen |= {x.dxf.handle for x in ents}
        if bad := misaligned(ents):
            warnings.append(f"window {sorted(seen & {x.dxf.handle for x in ents})}: lines {bad} don't line up with the "
                            "rest of the window (left behind?). Move a window with move_window, which takes all its lines.")
    pieces = []
    for h, b0 in pieces0.items():
        e = doc.entitydb.get(h)
        b1 = ext_of(e) if e is not None and e.is_alive else None
        if b0 and b1 != b0:
            B = lambda b: b and [r(b[0] - ox), r(b[1] - oy), r(b[2] - ox), r(b[3] - oy)]
            pieces.append({"handle": h, "old": B(b0), "new": B(b1)})
    auditor = doc.audit()
    doc.saveas(a.out)
    after = Counter(e.dxf.layer for e in msp)
    delta = {k: after[k] - before[k] for k in set(before) | set(after) if after[k] != before[k]}
    print(json.dumps({"log": log, "new_handles": new, "layer_count_change": delta,
                      "removed_zero_length": zero, "audit_errors": len(auditor.errors),
                      "furniture_changed": bool(layers_hit & set(FURNI)),
                      **({"pieces_changed": pieces} if pieces else {}),
                      **({"windows_moved": moved} if moved else {}), **({"warnings": warnings} if warnings else {})}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("query"); q.add_argument("src"); q.add_argument("--origin", required=True)
    q.add_argument("--bbox", required=True); q.add_argument("--layers"); q.add_argument("--limit", default="150")
    e = sub.add_parser("edit"); e.add_argument("src"); e.add_argument("out"); e.add_argument("--origin", required=True)
    a = p.parse_args()
    try:
        query(a) if a.cmd == "query" else edit(a)
    except Exception as ex:
        print(json.dumps({"error": f"{type(ex).__name__}: {ex}"}))
        sys.exit(1)
