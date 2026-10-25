#!/usr/bin/env python3
"""Edit AI's hands on a plan DXF (run with a Python that has ezdxf: ~/.dwg-tools/bin/python here, the function's
own on Vercel). edit_ai.py calls it; coordinates in and out are plan metres in model.js's frame (plan = DWG - origin).

    edit_ai_dxf.py query IN.dxf --origin ox,oy --bbox x0,y0,x1,y1 [--layers 1wall,2furni]   -> JSON list of entities
    edit_ai_dxf.py edit  IN.dxf OUT.dxf --origin ox,oy  < ops.json                          -> JSON report

`query` also lists what furniture blocks hold (not door blocks): handle "INSERT/ENTITY", "inside_block": its name,
layer the entity's own. An edit op given such a handle explodes that INSERT into model space first (once per call) and
works on the new entity; the report's "handles_remapped" gives virtual -> new handles.

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
    {"op": "resize_piece", "handle": "16B8", "grow": {"W": 0.2, "E": 0.2, "S": 0.2}}
        or grow / shrink given sides by metres (negative shrinks; missing sides stay put): no arithmetic needed.
After any edit, each piece moved, resized or added is checked against the walls and the other outlines: overlaps are
listed under "clashes" (a rug may sit under things; given as --soft boxes).
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

WINDOW_LAYER, WALL_LAYER, DOOR_LAYER = "Windows", "1wall", "3door"
FURNI = ("2furni", "2 furni")
DOOR_PART_LAYERS = {"1wall", "3door", "_DIM"}

ADD_LAYERS = {"1wall", "Windows", "2furni", "2 furni", "Glass", "3door", "_DIM"}


def r(v):
    return round(v, 4)


def block_children(ins):
    """(source handle, entity in model-space coordinates) for each entity of an INSERT's block."""
    m = ins.matrix44()
    for src in ins.doc.blocks[ins.dxf.name]:
        if src.dxftype() in ("ATTDEF", "ATTRIB"):
            continue
        try:
            v = src.copy()
            v.transform(m)
        except Exception:
            continue
        yield src.dxf.handle, v


def walk_msp(msp, depth=3):
    """Model space plus what furniture blocks hold: (entity, handle, layer, block name). An entity inside a block gets
    a virtual handle "INSERT/ENTITY" (nested: "A/B/C") and its own layer (layer 0 takes the insert's, as drawn).
    Door blocks (3door) are left whole: move_door refuses them anyway."""
    def walk(ents, prefix, parent_layer, block, d):
        for h, e in ents:
            layer = e.dxf.get("layer", "0")
            if layer == "0" and parent_layer:
                layer = parent_layer
            vh = f"{prefix}/{h}" if prefix else h
            yield e, vh, layer, block
            if e.dxftype() == "INSERT" and d < depth and layer != DOOR_LAYER:
                yield from walk(block_children(e), vh, layer if layer != "0" else None, e.dxf.name, d + 1)
    yield from walk(((e.dxf.handle, e) for e in msp), "", None, None, 0)


def describe(e, ox, oy, handle=None, layer=None, block=None):
    t = e.dxftype()
    d = {"handle": handle or e.dxf.handle, "type": t, "layer": layer or e.dxf.layer}
    if block:
        d["inside_block"] = block
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
    for e, h, layer, block in walk_msp(doc.modelspace()):
        if layers and layer not in layers:
            continue
        d = describe(e, ox, oy, h, layer, block)
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
    from ezdxf import bbox as _bbox, path as _path
    if e.dxftype() == "LWPOLYLINE" and len(e):  # its drawn line, not widened by a polyline width (sizes come out exact)
        ps = list(_path.make_path(e).flattening(0.001)) or [e.get_points("xy")[0]]
        return (min(p[0] for p in ps), min(p[1] for p in ps), max(p[0] for p in ps), max(p[1] for p in ps))
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
    def clips(a_, c_):  # piece a_ only pushes into the edge of c_ (a table run into the bed), not nested / standing on it
        ov = max(0, min(a_[2], c_[2]) - max(a_[0], c_[0])) * max(0, min(a_[3], c_[3]) - max(a_[1], c_[1]))
        return area(a_) < area(c_) and 0 < ov < 0.5 * area(a_) and not inside(a_, c_) and not inside(c_, a_)
    for e, b in furni:
        if e is outline or not inside(b, ob):
            continue
        owners = [(area(b2), o, b2) for o, b2 in outlines if o is not e and inside(b, b2) and area(b2) >= area(b) * 1.05]
        # A line inside both a piece and one that clips its edge is the first piece's (the bed's pillow line, not the table's).
        keep = [w for w in owners if not any(w is not w2 and clips(w[2], w2[2]) for w2 in owners)] or owners
        if keep and min(keep, key=lambda x: x[0])[1] is outline:
            out.append(e)
    return out, ob


def free_span(msp, h, b, walls, top, mine, is_soft, inside):
    """Free span around box b: [x0, x1], [y0, y1] (absolute; None = open), bounded by wall faces and the
    other top-level pieces beside / before it."""
    x0, y0, x1, y1 = b[0] + 0.025, b[1] + 0.025, b[2] - 0.025, b[3] - 0.025
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    lo_x, hi_x, lo_y, hi_y = [], [], [], []
    for w in walls:
        (ax, ay), (bx, by) = (w.dxf.start.x, w.dxf.start.y), (w.dxf.end.x, w.dxf.end.y)
        if abs(ax - bx) < 0.005 and min(ay, by) < y1 and max(ay, by) > y0:
            (lo_x if ax <= cx else hi_x).append(ax)
        if abs(ay - by) < 0.005 and min(ax, bx) < x1 and max(ax, bx) > x0:
            (lo_y if ay <= cy else hi_y).append(ay)
    for o, b2 in top:
        if o.dxf.handle in mine or is_soft(b2) or inside(b2, b) or inside(b, b2):
            continue
        oy_, ox_ = min(y1, b2[3]) - max(y0, b2[1]), min(x1, b2[2]) - max(x0, b2[0])
        if oy_ > 0 and oy_ >= ox_:  # beside it: limits x
            (lo_x.append(b2[2]) if (b2[0] + b2[2]) / 2 <= cx else hi_x.append(b2[0]))
        elif ox_ > 0:  # before / behind it: limits y
            (lo_y.append(b2[3]) if (b2[1] + b2[3]) / 2 <= cy else hi_y.append(b2[1]))
    return [max(lo_x) if lo_x else None, min(hi_x) if hi_x else None], [max(lo_y) if lo_y else None, min(hi_y) if hi_y else None]


def room_around(msp, doc, h, soft_b):
    """free_span for piece h as it stands now, with the same rules as clashes()."""
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    near = lambda b, t: all(abs(b[i] - t[i]) < 0.06 for i in range(4))
    inside = lambda a_, b_: a_[0] >= b_[0] - 0.08 and a_[1] >= b_[1] - 0.08 and a_[2] <= b_[2] + 0.08 and a_[3] <= b_[3] + 0.08
    is_soft = lambda b: any(near(b, t) for t in soft_b)
    outl = [(e, ext_of(e)) for e in msp if e.dxf.layer in FURNI and e.dxftype() == "LWPOLYLINE" and len(e) >= 4]
    outl = [(e, b) for e, b in outl if b and area(b) >= 0.04]
    top = [(e, b) for e, b in outl if not any(o is not e and area(b2) > area(b) * 1.05 and inside(b, b2) and not is_soft(b2)
                                              for o, b2 in outl)]
    e = doc.entitydb.get(h)
    b = ext_of(e)
    mine = {x.dxf.handle for x in piece_members(msp, e)[0]}
    walls = [w for w in msp.query("LINE") if w.dxf.layer == "1wall"]
    return free_span(msp, h, b, walls, [] if is_soft(b) else top, mine, is_soft, inside)


def clashes(msp, doc, handles, soft, ox, oy, soft_h=(), m=0.025):
    """Each listed outline against the wall faces and the other top-level furniture outlines (rugs in `soft` may
    overlap things). Returns [{"piece", "with", "overlap": plan box}]."""
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    near = lambda b, t: all(abs(b[i] - t[i]) < 0.06 for i in range(4))
    is_soft0 = lambda b: any(near(b, t) for t in soft)
    inside = lambda a_, b_: a_[0] >= b_[0] - 0.08 and a_[1] >= b_[1] - 0.08 and a_[2] <= b_[2] + 0.08 and a_[3] <= b_[3] + 0.08
    outl = [(e, ext_of(e)) for e in msp if e.dxf.layer in FURNI and e.dxftype() == "LWPOLYLINE" and len(e) >= 4]
    outl = [(e, b) for e, b in outl if b and area(b) >= 0.04]
    soft_h = set(soft_h) | {e.dxf.handle for e, b in outl if is_soft0(b)}
    soft_b = [b for e, b in outl if e.dxf.handle in soft_h]
    is_soft = lambda b: any(near(b, t) for t in soft_b)
    top = [(e, b) for e, b in outl if not any(o is not e and area(b2) > area(b) * 1.05 and inside(b, b2) and not is_soft(b2)
                                              for o, b2 in outl)]
    walls = [e for e in msp.query("LINE") if e.dxf.layer == "1wall"]
    R = lambda v: round(v, 3)
    out = []
    for h in handles:
        e = doc.entitydb.get(h)
        if e is None or not e.is_alive:
            continue
        b = ext_of(e)
        mine = {x.dxf.handle for x in piece_members(msp, e)[0]}
        x0, y0, x1, y1 = b[0] + m, b[1] + m, b[2] - m, b[3] - m
        if x1 <= x0 or y1 <= y0:
            continue
        for w in walls:
            (ax, ay), (bx, by) = (w.dxf.start.x, w.dxf.start.y), (w.dxf.end.x, w.dxf.end.y)
            seg = LineString([(ax, ay), (bx, by)])
            from shapely.geometry import box as _box
            cut = seg.intersection(_box(x0, y0, x1, y1))
            if not cut.is_empty and cut.length > 0.02:
                c = cut.bounds
                out.append({"piece": h, "with": f"wall {w.dxf.handle}",
                            "overlap": [R(c[0] - ox), R(c[1] - oy), R(c[2] - ox), R(c[3] - oy)]})
        if h in soft_h:
            continue  # a rug only clashes with walls
        for o, b2 in top:
            if o.dxf.handle in mine or is_soft(b2) or inside(b2, b) or inside(b, b2):
                continue
            ix0, iy0, ix1, iy1 = max(x0, b2[0]), max(y0, b2[1]), min(x1, b2[2]), min(y1, b2[3])
            if ix1 - ix0 > 0.005 and iy1 - iy0 > 0.005:
                out.append({"piece": h, "with": f"outline {o.dxf.handle} (x {R(b2[0] - ox)}..{R(b2[2] - ox)}, "
                                                f"y {R(b2[1] - oy)}..{R(b2[3] - oy)})",
                            "overlap": [R(ix0 - ox), R(iy0 - oy), R(ix1 - ox), R(iy1 - oy)]})
        if any(c["piece"] == h for c in out):  # how much room there is, so the fix isn't trial and error
            fx, fy = free_span(msp, h, b, walls, [] if h in soft_h else top, mine, is_soft, inside)
            sp = lambda f, o_: (f"{R(f[0] - o_)}..{R(f[1] - o_)} ({round((f[1] - f[0]) * 100)} cm)" if None not in f else "open")
            out.append({"piece": h, "with": "(free space)", "free": f"free span around it: x {sp(fx, ox)}, y {sp(fy, oy)}",
                        "overlap": [0, 0, 0, 0]})
    return out


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
    details_cut = []  # detail lines deleted out of a piece that stays (a divider of a dressing table, not a piece)

    layers_hit = set()

    soft = [tuple(float(v) for v in t.split(",")) for t in (a.soft or "").split(";") if t.strip()]
    soft = [(t[0] + ox, t[1] + oy, t[2] + ox, t[3] + oy) for t in soft]
    pieces0 = {}  # furniture outlines touched: their extent before

    vmap = {}  # virtual handle "INSERT/ENTITY" -> the real one, once that block is exploded

    def real(h):
        """A handle as query gave it; one inside a block explodes that INSERT into model space (once) first."""
        if not isinstance(h, str) or "/" not in h:
            return h
        if h in vmap:
            return vmap[h]
        parent = h.rpartition("/")[0]
        ins = doc.entitydb.get(real(parent))
        if ins is None or not ins.is_alive or ins.dxftype() != "INSERT":
            raise ValueError(f"no block {parent} for handle {h} (exploded by an earlier edit? dxf_query again for its "
                             "model-space handle)")
        if ins.dxf.layer == DOOR_LAYER:
            raise ValueError(f"{h} is inside a door block (INSERT): it can't be moved or resized here: tell the user it "
                             "needs the engineer")
        kids = [(f"{parent}/{sh}", v.dxftype(), ext_of(v)) for sh, v in block_children(ins)]
        layer, name = ins.dxf.layer, ins.dxf.name
        got = []
        for e in ins.explode():
            if e.dxf.get("layer", "0") == "0" and layer != "0":
                e.dxf.layer = layer  # as it was drawn: block content on layer 0 takes the insert's layer
            b = ext_of(e)
            best = min((k for k in kids if k[1] == e.dxftype() and k[0] not in vmap),
                       key=lambda k: max(abs(k[2][i] - b[i]) for i in range(4)) if k[2] and b else 9e9, default=None)
            if best is not None:
                vmap[best[0]] = e.dxf.handle
                got.append(e.dxf.handle)
        log.append(f"block {name} ({parent}) exploded into {len(got)} model-space entities; use the new handles from now "
                   f"on (handles_remapped)")
        if h not in vmap:
            raise ValueError(f"no entity {h} in block {name}")
        return vmap[h]

    def get(h):
        h = real(h)
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
        for key in ("handle", "centre_on"):  # virtual handles -> real ones up front, so every op and log line uses those
            if o.get(key):
                o[key] = [real(h) for h in o[key]] if isinstance(o[key], list) else real(o[key])
        if o.get("handles"):
            o["handles"] = [real(h) for h in o["handles"]]
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
            area_ = lambda b: (b[2] - b[0]) * (b[3] - b[1])
            outl_ = [(e2, ext_of(e2)) for e2 in msp if e2.dxf.layer in FURNI and e2.dxftype() == "LWPOLYLINE" and len(e2) >= 4]
            outl_ = [(e2, b2) for e2, b2 in outl_ if b2 and area_(b2) >= 0.04]
            gone_ = {real(h) for h in o["handles"]}
            for h in o["handles"]:
                e = get(h)
                b = ext_of(e) if e.dxf.layer in FURNI else None
                if b and not (e.dxftype() == "LWPOLYLINE" and len(e) >= 4 and area_(b) >= 0.04):
                    own = [(area_(b2), e2.dxf.handle, b2) for e2, b2 in outl_ if e2.dxf.handle not in gone_
                           and b2[0] - 0.01 <= b[0] and b[2] <= b2[2] + 0.01 and b2[1] - 0.01 <= b[1] and b[3] <= b2[3] + 0.01]
                    if own:
                        _, oh, ob_ = min(own)
                        details_cut.append(f"{e.dxf.handle} (a {e.dxftype()} drawn inside piece {oh}, x {r(ob_[0] - ox)}..{r(ob_[2] - ox)}, "
                                           f"y {r(ob_[1] - oy)}..{r(ob_[3] - oy)}, which stays)")
                msp.delete_entity(e)
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
            h_ = ents[0].dxf.handle
            hit0 = {c["with"] for c in clashes(msp, doc, [h_], soft, 0, 0, m=0.003) if not c.get("free")}
            for e in ents:
                touched.add(e.dxf.handle)
                e.translate(dx, dy, 0)
            # A move along one axis that runs the piece into a wall / piece it was clear of stops at it (a real
            # piece can't go through its neighbour); a jump right past it, to the far side, is left as asked.
            note = ""
            if bool(dx) != bool(dy) and not o.get("allow_overlap"):
                ai = 0 if dx else 1
                d = dx if dx else dy
                new_hits = [c for c in clashes(msp, doc, [h_], soft, 0, 0, m=0.003) if not c.get("free") and c["with"] not in hit0]
                if new_hits:
                    nb_ = ext_of(ents[0])  # how far its leading edge went past each thing it now runs into
                    back = max(((nb_[ai + 2] - 0.003) - c["overlap"][ai]) if d > 0 else (c["overlap"][ai + 2] - (nb_[ai] + 0.003))
                               for c in new_hits) + 0.001
                    if back < abs(d) + 0.003:
                        back = abs(d) if abs(d) - back < 0.01 else back  # already touching: it stays put
                        s_ = -1 if d > 0 else 1
                        for e in ents:
                            e.translate(s_ * back if ai == 0 else 0, s_ * back if ai == 1 else 0, 0)
                        got = abs(d) - back
                        what = new_hits[0]["with"].split(" (")[0]
                        note = (f" [ONLY {round(got * 100)} cm FREE that way (asked {round(abs(d) * 100)} cm): it now touches "
                                f"{what}" + (" - it was ALREADY touching it, so it did not move" if got < 0.005 else "")
                                + ". Give furnish.js exactly this move and TELL THE USER it only went that far and why]")
                        if ai == 0:
                            dx = r(dx + s_ * back)
                        else:
                            dy = r(dy + s_ * back)
            b = ext_of(ents[0])
            log.append(f"piece {o['handle']} ({len(ents)} entities: {[e.dxf.handle for e in ents]}) moved by ({dx}, {dy}); "
                       f"outline now x {r(b[0] - ox)}..{r(b[2] - ox)}, y {r(b[1] - oy)}..{r(b[3] - oy)}" + note)
        elif k == "resize_piece":
            ents, b = piece_members(msp, get(o["handle"]))
            w, h = b[2] - b[0], b[3] - b[1]
            g = {str(k2).upper(): float(v2 or 0) for k2, v2 in (o.get("grow") or {}).items()}
            if g:
                nb = [b[0] - g.get("W", 0), b[1] - g.get("S", 0), b[2] + g.get("E", 0), b[3] + g.get("N", 0)]
            else:
                nw = float(o["x_size"]) if o.get("x_size") else w
                nh = float(o["y_size"]) if o.get("y_size") else h
                an = (o.get("anchor") or "").upper()
                ax = b[0] if "W" in an else b[2] if "E" in an else (b[0] + b[2]) / 2
                ay = b[1] if "S" in an else b[3] if "N" in an else (b[1] + b[3]) / 2
                kx_, ky_ = nw / w, nh / h
                nb = [ax + (b[0] - ax) * kx_, ay + (b[1] - ay) * ky_, ax + (b[2] - ax) * kx_, ay + (b[3] - ay) * ky_]
            if nb[2] - nb[0] <= 0.05 * w or nb[3] - nb[1] <= 0.05 * h:
                raise ValueError("that would shrink the piece to nothing")
            # Growing: keep it inside the room it has (walls, the pieces beside it). Too big for the span ->
            # it fills the span exactly; it fits but was pushed out of it (wrong anchor) -> slide it back in.
            fits = []
            try:
                spans = room_around(msp, doc, o["handle"], soft)
            except Exception:
                spans = ([None, None], [None, None])
            for ai, (lo, hi) in enumerate(spans):
                i0, i1, old_sz = ai, ai + 2, (w if ai == 0 else h)
                new_sz = nb[i1] - nb[i0]
                if new_sz <= old_sz + 0.002:
                    continue
                if (lo is not None and b[i0] < lo - 0.01) or (hi is not None and b[i1] > hi + 0.01):
                    continue  # already overlapping something: leave it to the clash check
                axis = "xy"[ai]
                if lo is not None and hi is not None and new_sz > hi - lo + 0.005:
                    if hi - lo <= old_sz + 0.005:
                        nb[i0], nb[i1] = b[i0], b[i1]
                        fits.append(f"NO ROOM to make it bigger along {axis}: it already fills its free span "
                                    f"{r(lo - (ox if ai == 0 else oy))}..{r(hi - (ox if ai == 0 else oy))} ({round((hi - lo) * 100)} cm, "
                                    f"between walls / the pieces beside it), so its {axis} size stays {round(old_sz * 100)} cm")
                    else:
                        nb[i0], nb[i1] = lo, hi
                        fits.append(f"ONLY {round((hi - lo) * 100)} cm FITS along {axis} (asked {round(new_sz * 100)} cm): "
                                    f"it now exactly fills its free span {r(lo - (ox if ai == 0 else oy))}..{r(hi - (ox if ai == 0 else oy))}")
                    continue
                if g:  # explicit edges: an edge that would cross stops at the span end (no sliding)
                    for ii, lim, bad in ((i0, lo, lambda v, L: v < L - 0.005), (i1, hi, lambda v, L: v > L + 0.005)):
                        if lim is not None and bad(nb[ii], lim):
                            side = ("W", "S", "E", "N")[ii]
                            want = abs(nb[ii] - b[ii])
                            nb[ii] = lim if (lim - b[ii]) * (nb[ii] - b[ii]) > 0 else b[ii]
                            got = abs(nb[ii] - b[ii])
                            jj = i1 if ii == i0 else i0  # the opposite edge: room left there for the shortfall
                            lim2 = hi if ii == i0 else lo
                            room = (abs(lim2 - nb[jj]) if lim2 is not None else 9.0)
                            msg_ = (f"the {side} edge could only grow {round(got * 100)} cm (asked {round(want * 100)}): "
                                    f"it stops at the wall / piece at {axis} {r(lim - (ox if ai == 0 else oy))}")
                            if room > 0.01:
                                msg_ += (f"; the {('W', 'S', 'E', 'N')[jj]} side still has {round(min(room, 9) * 100)} cm free, so if the "
                                         f"user asked for a total size (\"60 cm wide\") grow that side by the {round((want - got) * 100)} cm "
                                         "shortfall too (x_size / y_size does this for you), but not for an even border like a rug's")
                            fits.append(msg_)
                    continue
                if lo is not None and nb[i0] < lo - 0.005:
                    d_ = lo - nb[i0]; nb[i0] += d_; nb[i1] += d_
                    fits.append(f"slid {round(d_ * 100)} cm along +{axis} to stay clear of what is beside it")
                elif hi is not None and nb[i1] > hi + 0.005:
                    d_ = nb[i1] - hi; nb[i0] -= d_; nb[i1] -= d_
                    fits.append(f"slid {round(d_ * 100)} cm along -{axis} to stay clear of what is beside it")
            kx, ky = (nb[2] - nb[0]) / w, (nb[3] - nb[1]) / h
            for e in ents:
                touched.add(e.dxf.handle)
                scale_entity(e, (b[0], b[1]), kx, ky)
                e.translate(nb[0] - b[0], nb[1] - b[1], 0)
            b = ext_of(ents[0])
            dw_, dh_ = (b[2] - b[0]) - w, (b[3] - b[1]) - h
            chg = "; ".join(f"{ax_} size {'+' if d_ > 0 else ''}{round(d_ * 100)} cm ({'BIGGER' if d_ > 0 else 'SMALLER'})"
                            for ax_, d_ in (("x", dw_), ("y", dh_)) if abs(d_) > 0.002) or "NO SIZE CHANGE"
            log.append(f"piece {o['handle']} ({len(ents)} entities) resized {r(w)} x {r(h)} -> {r(b[2] - b[0])} x "
                       f"{r(b[3] - b[1])} [{chg}]; outline now x {r(b[0] - ox)}..{r(b[2] - ox)}, y {r(b[1] - oy)}..{r(b[3] - oy)}"
                       + (" [" + "; ".join(fits) + ". Make furnish.js match this outline (size AND centre) and TELL THE USER "
                          "the size it really got and why]" if fits else ""))
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
    check = [p_["handle"] for p_ in pieces if p_["new"]] + [
        h for h in new if (e := doc.entitydb.get(h)) is not None and e.dxf.layer in FURNI
        and e.dxftype() == "LWPOLYLINE" and len(e) >= 4]
    soft_h = {h for h, b0 in pieces0.items() if b0 and any(all(abs(b0[i] - t[i]) < 0.06 for i in range(4)) for t in soft)}
    clash = clashes(msp, doc, check, soft, ox, oy, soft_h) if check else []
    # New wall lines: what they run through, whether they join a wall, and the walkway left beside them.
    from shapely.geometry import box as _sbox
    nw_ = [doc.entitydb.get(h) for h in new]
    nw_ = [e for e in nw_ if e is not None and e.dxftype() == "LINE" and e.dxf.layer == "1wall"
           and (e.dxf.start - e.dxf.end).magnitude > 0.2]
    if nw_:
        newset = {e.dxf.handle for e in nw_}
        old_w = [e for e in msp.query("LINE") if e.dxf.layer == "1wall" and e.dxf.handle not in newset]
        area_ = lambda b: (b[2] - b[0]) * (b[3] - b[1])
        fo_ = [(e, ext_of(e)) for e in msp if e.dxf.layer in FURNI and e.dxftype() == "LWPOLYLINE" and len(e) >= 4]
        fo_ = [(e, b) for e, b in fo_ if b and area_(b) >= 0.04 and not any(all(abs(b[i] - t[i]) < 0.06 for i in range(4)) for t in soft)]
        fo_ = [(e, b) for e, b in fo_ if not any(e2 is not e and area_(b2) > area_(b) * 1.05 and b2[0] - 0.08 <= b[0] and b[2] <= b2[2] + 0.08
                                                 and b2[1] - 0.08 <= b[1] and b[3] <= b2[3] + 0.08 for e2, b2 in fo_)]  # top-level pieces
        P_ = lambda q: f"({r(q[0] - ox)}, {r(q[1] - oy)})"
        stub = unary_union([LineString([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]) for e in nw_])
        joined = any(LineString([(w.dxf.start.x, w.dxf.start.y), (w.dxf.end.x, w.dxf.end.y)]).distance(stub) < 0.01 for w in old_w)
        through = sorted({e.dxf.handle for e, b in fo_ if stub.intersects(_sbox(b[0] + 0.01, b[1] + 0.01, b[2] - 0.01, b[3] - 0.01))})
        close = sorted((round(stub.distance(_sbox(*b)), 2), e.dxf.handle) for e, b in fo_ if e.dxf.handle not in through
                       and 0 < stub.distance(_sbox(*b)) < 0.6)
        if not joined:
            warnings.append("the new wall doesn't touch any existing wall: it stands free in the room. A partition normally "
                            "runs from a wall (snap one end onto an existing wall face) unless the user asked for a free-standing one")
        if through:
            warnings.append(f"the new wall runs through furniture outline(s) {through}: move the wall or the furniture (both views)")
        if close:
            warnings.append("the new wall leaves only " + ", ".join(f"{round(d * 100)} cm to {h}" for d, h in close[:3])
                            + " (under ~60 cm is no walkway: shift it so the room still works, or say why not)")
    auditor = doc.audit()
    doc.saveas(a.out)
    after = Counter(e.dxf.layer for e in msp)
    delta = {k: after[k] - before[k] for k in set(before) | set(after) if after[k] != before[k]}
    print(json.dumps({"log": log, "new_handles": new, "layer_count_change": delta,
                      "removed_zero_length": zero, "audit_errors": len(auditor.errors),
                      "furniture_changed": bool(layers_hit & set(FURNI)),
                      **({"handles_remapped": vmap} if vmap else {}),
                      **({"pieces_changed": pieces} if pieces else {}),
                      **({"clashes_checked": check, "clashes": clash} if check else {}),
                      **({"windows_moved": moved} if moved else {}),
                      **({"warnings": warnings + [f"deleted only a detail line of a piece that is still there: {d}. A part "
                          "built inside another piece (a stool under a dressing table, a drawer front) has no outline of its "
                          "own, so removing that part changes nothing on the plan: put the line back (discard, redo without "
                          "it) unless the user asked to change that piece's drawing" for d in details_cut]}
                         if warnings or details_cut else {})}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("query"); q.add_argument("src"); q.add_argument("--origin", required=True)
    q.add_argument("--bbox", required=True); q.add_argument("--layers"); q.add_argument("--limit", default="150")
    e = sub.add_parser("edit"); e.add_argument("src"); e.add_argument("out"); e.add_argument("--origin", required=True)
    e.add_argument("--soft", default="")
    a = p.parse_args()
    try:
        query(a) if a.cmd == "query" else edit(a)
    except Exception as ex:
        print(json.dumps({"error": f"{type(ex).__name__}: {ex}"}))
        sys.exit(1)
