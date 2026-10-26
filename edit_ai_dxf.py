#!/usr/bin/env python3
"""Edit AI's hands on a plan DXF (run with a Python that has ezdxf: ~/.dwg-tools/bin/python here, the function's
own on Vercel). edit_ai.py calls it; coordinates in and out are plan metres in model.js's frame (plan = DWG - origin).

    edit_ai_dxf.py query IN.dxf --origin ox,oy --bbox x0,y0,x1,y1 [--layers 1wall,2furni]   -> JSON list of entities
        (--blocks: also each furniture INSERT there, whole, with its full extent as "bbox")
    edit_ai_dxf.py edit  IN.dxf OUT.dxf --origin ox,oy  < ops.json                          -> JSON report

`query` also lists what furniture blocks hold (not door blocks): handle "INSERT/ENTITY", "inside_block": its name,
layer the entity's own. An edit op given such a handle explodes that INSERT into model space first (once per call) and
works on the new entity; the report's "handles_remapped" gives virtual -> new handles.

Edit ops (a JSON list), handles as `query` gives them:
    {"op": "move", "handles": [...], "dx": 0.1, "dy": 0}          translate entities (blocks move by their insert)
    {"op": "rotate", "handles": [...], "angle": 90, "centre": [x, y], "dx": 0, "dy": 0}   turned together, then moved
    {"op": "scale", "handles": [...], "base": [x, y], "sx": 1.1, "sy": 1, "dx": 0, "dy": 0}  stretched from base, then moved
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
    {"op": "resize_piece", "handle": "16B8", "grow": {"W": 0.2, "E": 0.2, "S": 0.2}}   (+ "allow_overlap": true: no stop at neighbours)
        or grow / shrink given sides by metres (negative shrinks; missing sides stay put): no arithmetic needed.
After any edit, each piece moved, resized or added is checked against the walls and the other outlines: overlaps are
listed under "clashes" (a rug may sit under things; given as --soft boxes).
    {"op": "rotate_piece", "handle": "1692", "angle": 90, "centre": [x, y], "dx": 0, "dy": 0}
        the same piece (or a whole furniture block, by its INSERT handle) turned by angle degrees (+ = anticlockwise)
        about centre (plan metres; default its own centre), then moved by dx, dy.
    {"op": "move_door", "handle": "16FA", "along": 0.2, "width": 0.8}
        a door drawn loose (its swing ARC is the handle): swing, leaf, jambs and frame bits slide along their wall by
        `along` metres (+ = towards +x / +y; or dx, dy, projected on the wall) and, with width, the leaf (= swing
        radius) is resized, the far jamb moving; the wall faces either side are re-cut to meet the frame again.
    {"op": "add_opening", "at": [x, y], "kind": "door", "width": 0.9, "hinge": "W", "opens": "N"}
        a new opening in the solid wall at plan point (x, y) (on or inside the wall), centred there: kind "window",
        "glass_slider" (full-height glass sliding door), "door" (hinged: hinge = the end of the opening it hangs from,
        a compass word or "start" / "end"; opens = the side of the wall it swings into), "sliding_door" (a solid
        sliding leaf) or "opening" (a bare doorway). Both wall faces are cut and given jambs.
    {"op": "convert_opening", "at": [x, y], "to": "window", "width": 1.2, "shift": 0.1, "hinge": "E", "opens": "S"}
        the existing opening at (x, y) (or "handle": one of its window lines, its swing ARC or its 3door INSERT) emptied
        and refilled as `to` (a kind above, or "wall" to close it); width (default its own) and shift (along the wall)
        resize / move it. Flip a door's hinge or swing: convert_opening to "door" with the other hinge / opens.
    {"op": "remove_opening", "at": [x, y]}      the opening walled up (= convert_opening to "wall")
        Each reports under "openings_changed": kind, centre, width, the gap's box and, for a door, hinge and opens.
        More kinds: "double_door" (two leaves, 1.0-2.6 m), "pocket_door", "barn_door", "bifold_door" (0.6-2.4 m).
    {"op": "add_wall", "a": [x, y], "b": [x, y], "thickness": 0.12, "align": "centre", "through": [x, y]}
        a new wall along a -> b (through: a third point makes it a curve); an end at an existing wall is run onto its
        face and that face broken between the new faces (a T-junction); a free end is capped. "walls_changed".
    {"op": "remove_wall", "at": [x, y]}      the wall at (x, y), junction to junction, with its doors / windows
    {"op": "move_wall", "at": [x, y], "dx": 0.3, "dy": 0}     slid across itself; the walls meeting it follow
    {"op": "set_wall_thickness", "at": [x, y], "thickness": 0.2, "keep": "N"}   keep = the face that stays put
    {"op": "mark_wall", "at": [x, y]}        nothing drawn: reports the wall's run (for a height / glass spec)
    {"op": "rename_room", "name": "BEDROOM 2" | "at": [x, y], "to": "STUDY"}; {"op": "add_room_label", "at", "name"}
    {"op": "add_niche", "at": [x, y], "width": 0.6, "depth": 0.1, "bottom": 0.9, "top": 1.5, "side": "N"}
        a recess into the wall's face (dashed on the plan); reported under "niches" for the 3D
Any edit that leaves one window's long lines out of line with each other (one glazing line left behind) is reported
under "warnings".
New entities copy colour and linetype ByLayer. No TEXT is ever added (every TEXT becomes a room label in the 3D).
"""
import argparse, json, math, sys
from collections import Counter

from ezdxf import recover
from shapely.geometry import LineString, Point
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
    if a.blocks:  # furniture drawn as one block (the WC symbol): the whole INSERT with its full extent, so it moves as one
        out = [d for d in out if d["type"] != "INSERT"]  # listed again below, whole
        for e in doc.modelspace().query("INSERT"):  # content on layer 0 takes the insert's layer (the CHAIR1 armchair)
            lays = {e.dxf.layer if c.dxf.get("layer", "0") == "0" else c.dxf.layer for c in doc.blocks[e.dxf.name]}
            if e.dxf.layer == DOOR_LAYER or not lays & set(FURNI):
                continue
            x = ext_of(e)
            if x and not (x[2] - ox < b[0] or x[0] - ox > b[2] or x[3] - oy < b[1] or x[1] - oy > b[3]):
                out.append({"handle": e.dxf.handle, "type": "INSERT", "layer": e.dxf.layer, "block": e.dxf.name,
                            "rotation": r(e.dxf.get("rotation", 0)), "bbox": [r(x[0] - ox), r(x[1] - oy), r(x[2] - ox), r(x[3] - oy)]})
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


# --- Openings: add, convert and remove doors / windows / sliders / bare doorways on the plan -----------------------------
# The plan holds where an opening is and what it is (window lines, a door swing, sliding panels); heights, glass and a
# terrace window kept as a window live in the version's tour ("openings", "heights"), which edit_ai.py writes from the
# "opening" each of these ops reports.
KINDS = ("window", "glass_slider", "door", "double_door", "sliding_door", "pocket_door", "barn_door", "bifold_door", "opening")


def _canon(u):
    return (-u[0], -u[1]) if abs(u[0]) >= abs(u[1]) and u[0] < 0 or abs(u[1]) > abs(u[0]) and u[1] < 0 else u


def _wall_lines(msp):
    out = []
    for e in msp.query(f'LINE[layer=="{WALL_LAYER}"]'):
        s_ = segs_of(e)[0]
        if math.dist(*s_) > 0.002:
            out.append((e, s_))
    return out


def _faces(lines, p, u, reach_n=0.45, reach_t=4.0):
    """1wall lines along u near p, grouped by their offset across u: {key: [(entity, ta, tb, nn)]} (t, n from p)."""
    n = (-u[1], u[0])
    T = lambda q: (q[0] - p[0]) * u[0] + (q[1] - p[1]) * u[1]
    N = lambda q: (q[0] - p[0]) * n[0] + (q[1] - p[1]) * n[1]
    groups, found = {}, []
    for e, s_ in lines:
        d = math.dist(*s_)
        if abs((s_[1][0] - s_[0][0]) * u[0] + (s_[1][1] - s_[0][1]) * u[1]) / d < 0.999:
            continue
        nn = (N(s_[0]) + N(s_[1])) / 2
        ta, tb = sorted((T(s_[0]), T(s_[1])))
        if abs(nn) <= reach_n and tb >= -reach_t and ta <= reach_t:
            found.append((e, ta, tb, nn))
    # One face = lines within 12 mm of each other across u (the faces either side of a door sit a few mm apart).
    found.sort(key=lambda x: x[3])
    for x in found:
        key = next((k for k in groups if abs(x[3] - groups[k][-1][3]) < 0.012), None)
        groups.setdefault(len(groups) if key is None else key, []).append(x)
    return groups


def _axes(lines, p, reach=1.6):
    out = []
    for _, s_ in lines:
        if LineString(s_).distance(Point(p)) > reach or math.dist(*s_) < 0.05:
            continue
        L = math.dist(*s_)
        u = _canon(((s_[1][0] - s_[0][0]) / L, (s_[1][1] - s_[0][1]) / L))
        if not any(abs(u[0] * v[0] + u[1] * v[1]) > 0.999 for v in out):
            out.append(u)
    return out


def _pair(sides, lo=0.06, hi=0.4):
    """The two face offsets (n0 < n1) a wall's thickness apart that p (n = 0) sits in, or nearest to."""
    best = None
    for i, a_ in enumerate(sides):
        for b_ in sides[i + 1:]:
            n0, n1 = sorted((a_, b_))
            if lo <= n1 - n0 <= hi:
                off = 0 if n0 <= 0 <= n1 else min(abs(n0), abs(n1))
                if off <= 0.35 and (best is None or off < best[0] or off == best[0] and n1 - n0 < best[2] - best[1]):
                    best = (off, n0, n1)
    return best


def gap_at(msp, p):
    """The opening (door, window, slider or bare doorway) at or beside DWG point p: (p, u, n, t0, t1, n0, n1), t and n
    measured from p; None if p isn't in an opening."""
    lines = _wall_lines(msp)
    # A window: its own lines give the opening (some walls run both faces straight through their windows).
    wins = [e for e in msp.query(f'LINE LWPOLYLINE[layer=="{WINDOW_LAYER}"]')
            if segs_of(e) and min(LineString(sg).distance(Point(p)) for sg in segs_of(e)) < 0.2]
    if wins:
        c, u, n, t0, t1, n0, n1 = frame(window_cluster(msp, wins[0]))
        faces = [sum(x[3] for x in segs) / len(segs) for segs in _faces(lines, c, u).values()]
        snap = lambda v: min(faces, key=lambda f: abs(f - v)) if faces and min(abs(f - v) for f in faces) < 0.05 else v
        if t1 - t0 >= 0.3:
            return (c, u, n, t0, t1, snap(n0), snap(n1))
    found = []
    for u in _axes(lines, p):
        sides, through = {}, []
        for segs in _faces(lines, p, u).values():
            nn = sum(x[3] for x in segs) / len(segs)
            if any(ta <= 0 <= tb for _, ta, tb, _ in segs):
                through.append(nn)  # this face runs on past p (an outer face drawn across a window)
                continue
            lo_ = [tb for _, ta, tb, _ in segs if tb <= 0]
            hi_ = [ta for _, ta, tb, _ in segs if ta >= 0]
            if lo_ and hi_ and 0.3 <= min(hi_) - max(lo_) <= 4.0:
                sides[nn] = (max(lo_), min(hi_))
        if not sides:
            continue
        for pr, both in ((_pair(sorted(sides)), 0), (_pair(sorted(set(sides) | set(through))), 1)):
            if pr:
                off, n0, n1 = pr
                if n0 not in sides and n1 not in sides:
                    continue
                spans = [sides[x] for x in (n0, n1) if x in sides]
                t0, t1 = min(a_ for a_, _ in spans), max(b_ for _, b_ in spans)
                found.append((both, off, t1 - t0, (p, u, (-u[1], u[0]), t0, t1, n0, n1)))
    return min(found, key=lambda f: (f[0], f[1], f[2]))[3] if found else None


def wall_at(msp, p):
    """The solid wall at or beside DWG point p: (p, u, n, n0, n1) with both faces running past p; None if none."""
    lines = _wall_lines(msp)
    found = []
    for u in _axes(lines, p):
        sides = [sum(x[3] for x in segs) / len(segs) for segs in _faces(lines, p, u).values() if any(ta < 0 < tb for _, ta, tb, _ in segs)]
        pr = _pair(sorted(set(sides)))
        if pr:
            found.append((pr[0], (p, u, (-u[1], u[0]), pr[1], pr[2])))
    return min(found, key=lambda f: f[0])[1] if found else None


def _at(e, q, t, nn, u, n):
    return (q[0] + u[0] * t + n[0] * nn, q[1] + u[1] * t + n[1] * nn)


def open_gap(msp, q, u, n, a, b, n0, n1):
    """Cut [a, b] (along u from q) out of the wall faces at n0 and n1. Refuses where the wall doesn't run the whole
    span on both faces (a corner, the wall's end) or another wall joins it inside the span."""
    lines = _wall_lines(msp)
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    faces = [(e, s_) for e, s_ in lines if abs((s_[1][0] - s_[0][0]) * u[0] + (s_[1][1] - s_[0][1]) * u[1]) / math.dist(*s_) > 0.999
             and min(abs((N(s_[0]) + N(s_[1])) / 2 - nn) for nn in (n0, n1)) < 0.012]
    for nn in (n0, n1):
        cover = sorted(sorted((T(s_[0]), T(s_[1]))) for e, s_ in faces if abs((N(s_[0]) + N(s_[1])) / 2 - nn) < 0.012)
        reach = a
        for ta, tb in cover:
            if ta <= reach + 0.002:
                reach = max(reach, tb)
        if reach < b - 0.002:
            raise ValueError(f"the wall doesn't run the whole {r(b - a)} m there (a corner or the wall's end): pick a "
                             "point further along it, or a narrower opening")
    for e, s_ in lines:  # a wall joining this one inside the span
        if abs((s_[1][0] - s_[0][0]) * n[0] + (s_[1][1] - s_[0][1]) * n[1]) / math.dist(*s_) < 0.999:
            continue
        for z in s_:
            if a + 0.01 < T(z) < b - 0.01 and (abs(N(z) - n0) < 0.01 or abs(N(z) - n1) < 0.01) and \
                    math.dist(*s_) > (n1 - n0) + 0.05:
                raise ValueError("another wall joins this one there: move the opening along the wall")
    for e, s_ in faces:
        ta, tb = T(s_[0]), T(s_[1])
        lo, hi = sorted((ta, tb))
        if hi <= a + 0.001 or lo >= b - 0.001:
            continue
        attrs = {k: e.dxf.get(k) for k in ("layer", "linetype", "color") if e.dxf.hasattr(k)}
        P = lambda t: (s_[0][0] + (s_[1][0] - s_[0][0]) * (t - ta) / (tb - ta), s_[0][1] + (s_[1][1] - s_[0][1]) * (t - ta) / (tb - ta))
        msp.delete_entity(e)
        for x, y in ((lo, a), (b, hi)):
            if y - x > 0.002:
                msp.add_line(P(x), P(y), dxfattribs=attrs)


def close_gap(msp, q, u, n, t0, t1, n0, n1):
    """Wall again across [t0, t1]: each face's two ends at the opening joined into one line, its jambs gone."""
    lines = _wall_lines(msp)
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    for nn in (n0, n1):
        segs = [(e, s_) for e, s_ in lines if abs((s_[1][0] - s_[0][0]) * u[0] + (s_[1][1] - s_[0][1]) * u[1]) / math.dist(*s_) > 0.999
                and abs((N(s_[0]) + N(s_[1])) / 2 - nn) < 0.012]
        if any(min(T(z) for z in s_) <= t0 + 0.01 and max(T(z) for z in s_) >= t1 - 0.01 for _, s_ in segs):
            continue  # this face already runs across the opening
        lo = [(max(T(z) for z in s_), e, s_) for e, s_ in segs if abs(max(T(z) for z in s_) - t0) < 0.04]
        hi = [(min(T(z) for z in s_), e, s_) for e, s_ in segs if abs(min(T(z) for z in s_) - t1) < 0.04]
        pts, gone, attrs = [], [], None
        for got in (max(lo, key=lambda x: x[0], default=None), min(hi, key=lambda x: x[0], default=None)):
            if got:
                _, e, s_ = got
                pts += list(s_)
                gone.append(e)
                attrs = attrs or {k: e.dxf.get(k) for k in ("layer", "linetype", "color") if e.dxf.hasattr(k)}
        far = [_at(None, q, t, nn, u, n) for t in (t0, t1)]
        pts += far if len(gone) < 2 else []
        a_ = min(pts, key=T)
        b_ = max(pts, key=T)
        for e in gone:
            msp.delete_entity(e)
        msp.add_line(a_, b_, dxfattribs=attrs or {"layer": WALL_LAYER})


def clear_gap(msp, q, u, n, t0, t1, n0, n1):
    """Delete what fills the opening: window lines, a door (swing, leaf, jambs, frame hatch, a 3door block), sliding
    panels. Wall faces and other walls stay. Returns how many entities went."""
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    w, th = t1 - t0, n1 - n0
    gone = []
    for e in list(msp):
        lay, t_ = e.dxf.layer, e.dxftype()
        if t_ == "INSERT":
            if lay == DOOR_LAYER:
                z = (e.dxf.insert.x, e.dxf.insert.y)
                if t0 - 0.15 <= T(z) <= t1 + 0.15 and n0 - 0.15 <= N(z) <= n1 + 0.15:
                    gone.append(e)
            continue
        if lay not in (WINDOW_LAYER, WALL_LAYER, DOOR_LAYER, "_DIM") and t_ != "HATCH" or t_ in ("DIMENSION", "TEXT", "MTEXT"):
            continue
        b_ = ext_of(e)
        if not b_:
            continue
        cs = [(b_[0], b_[1]), (b_[2], b_[1]), (b_[0], b_[3]), (b_[2], b_[3])]
        ts, ns = [T(z) for z in cs], [N(z) for z in cs]
        slack = 0.06 if lay == WINDOW_LAYER else w + 0.1  # a door swings out into the room
        if not (min(ts) >= t0 - 0.05 and max(ts) <= t1 + 0.05 and min(ns) >= n0 - slack and max(ns) <= n1 + slack):
            continue
        if lay == WALL_LAYER and t_ == "LINE":
            s_ = segs_of(e)[0]
            d = math.dist(*s_) or 1
            along = abs((s_[1][0] - s_[0][0]) * u[0] + (s_[1][1] - s_[0][1]) * u[1]) / d
            if along > 0.999 and not (n0 - 0.02 <= N(s_[0]) <= n1 + 0.02):
                continue  # another wall's face out in the room
            if along < 0.001 and d > th + 0.06:
                continue  # a wall running off this one, not a jamb
        gone.append(e)
    for e in gone:
        msp.delete_entity(e)
    return len(gone)


def _side(word, n):
    """+1 / -1: which side of the wall (along n) a compass word ("N", "south", ...) or "+" / "-" names."""
    w_ = str(word or "").strip().lower()
    vec = {"n": (0, 1), "north": (0, 1), "s": (0, -1), "south": (0, -1), "e": (1, 0), "east": (1, 0), "w": (-1, 0), "west": (-1, 0)}.get(w_)
    if w_ in ("+", "+1", "1"):
        return 1
    if w_ in ("-", "-1"):
        return -1
    if vec is None:
        raise ValueError(f"say the side as N, S, E or W, not {word!r}")
    d = vec[0] * n[0] + vec[1] * n[1]
    if abs(d) < 0.5:
        raise ValueError(f"{word!r} runs along this wall; the wall's sides are "
                         f"{'N / S' if abs(n[1]) > abs(n[0]) else 'E / W'}")
    return 1 if d > 0 else -1


def _end(word, u):
    """-1 (the start, low t) / +1 (the end): which end of the opening a compass word or "start" / "end" names."""
    w_ = str(word or "start").strip().lower()
    if w_ in ("start", "-"):
        return -1
    if w_ in ("end", "+"):
        return 1
    return _side(word, u)


def draw_opening(msp, q, u, n, a, b, n0, n1, kind, hinge=None, opens=None):
    """Fill [a, b] of the wall (faces at n0, n1) as `kind`. Returns what was drawn (hinge, sides) in DWG metres."""
    P = lambda t, nn: _at(None, q, t, nn, u, n)
    out = {}
    if kind in ("window", "glass_slider"):
        for (t_a, n_a), (t_b, n_b) in (((a, n0), (b, n0)), ((b, n0), (b, n1)), ((b, n1), (a, n1)), ((a, n1), (a, n0)),
                                       ((a, (n0 + n1) / 2), (b, (n0 + n1) / 2))):
            msp.add_line(P(t_a, n_a), P(t_b, n_b), dxfattribs={"layer": WINDOW_LAYER})
        return out
    for t in (a, b):  # door frames: the wall's jambs
        msp.add_line(P(t, n0), P(t, n1), dxfattribs={"layer": WALL_LAYER})
    if kind == "door":
        w = b - a
        if not 0.5 <= w <= 1.3:
            raise ValueError(f"a hinged door is 0.5 to 1.3 m wide; this opening is {r(w)} m (give a width)")
        e_ = _end(hinge, u)
        sg = _side(opens, n) if opens else 1
        face = n1 if sg > 0 else n0
        hn = face - sg * 0.02  # hinge just inside the frame, so the closed leaf crosses the opening
        h_t, c_t = (a, b) if e_ < 0 else (b, a)
        H, E = P(h_t, hn), P(c_t, hn)
        O = (H[0] + n[0] * sg * w, H[1] + n[1] * sg * w)
        aE = math.degrees(math.atan2(E[1] - H[1], E[0] - H[0])) % 360
        aO = math.degrees(math.atan2(O[1] - H[1], O[0] - H[0])) % 360
        start, end = (aE, aO) if (aO - aE) % 360 <= 180 else (aO, aE)
        msp.add_arc(H, w, start, end, dxfattribs={"layer": WALL_LAYER})
        k_ = (E[0] - H[0]) / w * 0.04, (E[1] - H[1]) / w * 0.04  # leaf 4 cm thick, towards the closed side
        msp.add_lwpolyline([H, O, (O[0] + k_[0], O[1] + k_[1]), (H[0] + k_[0], H[1] + k_[1])], close=True,
                           dxfattribs={"layer": "_DIM"})
        a0 = math.atan2(E[1] - H[1], E[0] - H[0])
        turn = math.pi / 2 if (aO - aE) % 360 <= 180 else -math.pi / 2
        out = {"hinge": H, "opens": "+n" if sg > 0 else "-n",
               "sweep": [H] + [(H[0] + w * math.cos(a0 + turn * k / 12), H[1] + w * math.sin(a0 + turn * k / 12)) for k in range(13)]}
    elif kind == "double_door":
        w = b - a
        if not 1.0 <= w <= 2.6:
            raise ValueError(f"double doors are 1.0 to 2.6 m wide; this opening is {r(w)} m (give a width)")
        sg = _side(opens, n) if opens else 1
        hn = (n1 if sg > 0 else n0) - sg * 0.02
        out = {"hinges": [], "opens": "+n" if sg > 0 else "-n", "sweep": None}
        for h_t, sgn_ in ((a, 1), (b, -1)):  # one leaf from each jamb, closed ends meeting in the middle
            H, E = P(h_t, hn), P((a + b) / 2, hn)
            r_ = w / 2
            O = (H[0] + n[0] * sg * r_, H[1] + n[1] * sg * r_)
            aE = math.degrees(math.atan2(E[1] - H[1], E[0] - H[0])) % 360
            aO = math.degrees(math.atan2(O[1] - H[1], O[0] - H[0])) % 360
            st, en = (aE, aO) if (aO - aE) % 360 <= 180 else (aO, aE)
            msp.add_arc(H, r_, st, en, dxfattribs={"layer": WALL_LAYER})
            k_ = (E[0] - H[0]) / r_ * 0.04, (E[1] - H[1]) / r_ * 0.04
            msp.add_lwpolyline([H, O, (O[0] + k_[0], O[1] + k_[1]), (H[0] + k_[0], H[1] + k_[1])], close=True, dxfattribs={"layer": "_DIM"})
            out["hinges"].append(H)
        out["hinge"] = out["hinges"][0]
    elif kind in ("sliding_door", "pocket_door", "barn_door", "bifold_door"):
        w = b - a
        if not 0.6 <= w <= 2.4:
            raise ValueError(f"a sliding / folding door is 0.6 to 2.4 m wide; this opening is {r(w)} m (give a width)")
        if kind == "bifold_door":  # the folded leaves drawn as a zig-zag in the opening
            m, nm, k = (a + b) / 2, (n0 + n1) / 2, max(2, round(w / 0.45))
            zz = [P(a + (b - a) * i / k, nm + (0.06 if i % 2 else -0.06)) for i in range(k + 1)]
            msp.add_lwpolyline(zz, dxfattribs={"layer": DOOR_LAYER})
            return out
        m, nm = (a + b) / 2, (n0 + n1) / 2
        for t_a, t_b, nn in ((a, m + 0.05, nm - 0.025), (m - 0.05, b, nm + 0.005)):
            msp.add_lwpolyline([P(t_a, nn), P(t_b, nn), P(t_b, nn + 0.02), P(t_a, nn + 0.02)], close=True,
                               dxfattribs={"layer": DOOR_LAYER})
    return out


# --- Walls: add, move, remove, thickness; room names; niches ---------------------------------------------------------
LABEL_LAYER = "ISLAK"


def _par(s_, u, tol=0.999):
    d = math.dist(*s_)
    return d > 1e-6 and abs((s_[1][0] - s_[0][0]) * u[0] + (s_[1][1] - s_[0][1]) * u[1]) / d >= tol


def wall_run(msp, p):
    """The wall at DWG point p from junction to junction (carried on across its own doors and windows, where both
    faces break together and no other wall meets the break): (q, u, n, n0, n1, t0, t1), t measured from q."""
    wa = wall_at(msp, p)
    if not wa:
        return None
    q, u, n, n0, n1 = wa
    th = n1 - n0
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    lines = _wall_lines(msp)
    iv = {n0: [], n1: []}
    for e, s_ in lines:
        if _par(s_, u):
            nn = (N(s_[0]) + N(s_[1])) / 2
            for f in (n0, n1):
                if abs(nn - f) < 0.012:
                    iv[f].append(sorted((T(s_[0]), T(s_[1]))))
    merged = {}
    for f, xs in iv.items():
        m = []
        for a_, b_ in sorted(xs):
            if m and a_ <= m[-1][1] + 0.003:
                m[-1][1] = max(m[-1][1], b_)
            else:
                m.append([a_, b_])
        merged[f] = m
    seg = lambda f, t: next((x for x in merged[f] if x[0] - 0.003 <= t <= x[1] + 0.003), None)

    def joined(t):  # another wall runs off this one at t (a line across it, longer than a jamb)
        for e, s_ in lines:
            if _par(s_, (n[0], n[1])) and math.dist(*s_) > th + 0.06:
                if any(abs(T(z) - t) < 0.01 and min(abs(N(z) - n0), abs(N(z) - n1)) < 0.01 for z in s_):
                    return True
        return False
    ext = []
    for sgn in (1, -1):
        a_, b_ = seg(n0, 0), seg(n1, 0)
        if not a_ or not b_:
            return None
        ea, eb = (a_[1], b_[1]) if sgn > 0 else (a_[0], b_[0])
        while True:
            near = min(ea, eb) if sgn > 0 else max(ea, eb)
            if abs(ea - eb) > 0.1 or joined(ea) or joined(eb):
                break  # one face goes on (a wall joins the other) or a wall runs off here
            if sgn > 0:
                na = next((x for x in merged[n0] if x[0] > ea + 0.003), None)
                nb = next((x for x in merged[n1] if x[0] > eb + 0.003), None)
            else:
                na = next((x for x in reversed(merged[n0]) if x[1] < ea - 0.003), None)
                nb = next((x for x in reversed(merged[n1]) if x[1] < eb - 0.003), None)
            if not na or not nb:
                break
            nxt = (na, nb)
            sa, sb = (na[0], nb[0]) if sgn > 0 else (na[1], nb[1])
            if abs(sa - sb) > 0.1 or abs(sa - near) > 4.0 or joined(sa) or joined(sb):
                break
            ea, eb = (nxt[0][1], nxt[1][1]) if sgn > 0 else (nxt[0][0], nxt[1][0])
        ext.append(min(ea, eb) if sgn > 0 else max(ea, eb))
    return q, u, n, n0, n1, ext[1], ext[0]


def split_faces(msp, q, u, n, n0, n1, ts):
    """Split the face lines at n0 / n1 at each t in ts (so a stretch of wall can move or go on its own)."""
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    for t in ts:
        for e, s_ in _wall_lines(msp):
            if not _par(s_, u) or min(abs((N(s_[0]) + N(s_[1])) / 2 - f) for f in (n0, n1)) > 0.012:
                continue
            ta, tb = T(s_[0]), T(s_[1])
            if min(ta, tb) + 0.002 < t < max(ta, tb) - 0.002:
                attrs = {k: e.dxf.get(k) for k in ("layer", "linetype", "color") if e.dxf.hasattr(k)}
                m = (s_[0][0] + (s_[1][0] - s_[0][0]) * (t - ta) / (tb - ta), s_[0][1] + (s_[1][1] - s_[0][1]) * (t - ta) / (tb - ta))
                msp.delete_entity(e)
                msp.add_line(s_[0], m, dxfattribs=attrs)
                msp.add_line(m, s_[1], dxfattribs=attrs)


def run_pieces(msp, q, u, n, faces, t0, t1):
    """The face lines (at the offsets in faces) lying within [t0, t1]: [(entity, seg, offset)]."""
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    out = []
    for e, s_ in _wall_lines(msp):
        if not _par(s_, u):
            continue
        nn = (N(s_[0]) + N(s_[1])) / 2
        f = next((f for f in faces if abs(nn - f) < 0.012), None)
        if f is not None and min(T(s_[0]), T(s_[1])) >= t0 - 0.003 and max(T(s_[0]), T(s_[1])) <= t1 + 0.003:
            out.append((e, s_, f))
    return out


def _touching(msp, lines_geo, skip, tol=0.003):
    """1wall LINE endpoints (not in skip) lying on any of lines_geo: [(entity, end index)]."""
    out = []
    for e, s_ in _wall_lines(msp):
        if e.dxf.handle in skip:
            continue
        for i, z in enumerate(s_):
            if any(LineString(g).distance(Point(z)) < tol for g in lines_geo):
                out.append((e, i))
    return out


def _move_end(e, i, d):
    z = e.dxf.start if i == 0 else e.dxf.end
    new = (z.x + d[0], z.y + d[1], 0)
    if i == 0:
        e.dxf.start = new
    else:
        e.dxf.end = new


def move_faces(msp, pieces, d, u, carry=()):
    """Move wall face lines by d and keep every wall they meet joined: an end of another wall's line lying on them
    slides by d too (a partition meeting this wall is lengthened / shortened, a T-junction's break in a through wall
    follows, a corner stays a corner). `carry` (window / door entities in the wall) moves with it."""
    geo = [s_ for _, s_, _ in pieces]
    skip = {e.dxf.handle for e, _, _ in pieces}
    for e, i in _touching(msp, geo, skip):
        s_ = segs_of(e)[0]
        if _par(s_, u):
            continue  # this wall's own face carrying on past the junction
        _move_end(e, i, d)
    for e in list(carry) + [e for e, _, _ in pieces]:
        e.translate(d[0], d[1], 0)


def carried(msp, q, u, n, n0, n1, t0, t1):
    """What sits in the wall between t0 and t1: window lines, door swings / leaves / frames, door blocks, jambs."""
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    out = []
    for e in msp:
        lay, t_ = e.dxf.layer, e.dxftype()
        if t_ == "INSERT":
            if lay == DOOR_LAYER:
                z = (e.dxf.insert.x, e.dxf.insert.y)
                if t0 - 0.05 <= T(z) <= t1 + 0.05 and n0 - 0.15 <= N(z) <= n1 + 0.15:
                    out.append(e)
            continue
        if lay not in (WINDOW_LAYER, WALL_LAYER, "_DIM", DOOR_LAYER) and t_ != "HATCH":
            continue
        if t_ == "ARC":
            z = (e.dxf.center.x, e.dxf.center.y)
            if t0 - 0.05 <= T(z) <= t1 + 0.05 and n0 - 0.05 <= N(z) <= n1 + 0.05:
                out.append(e)
            continue
        b_ = ext_of(e)
        if not b_:
            continue
        cs = [(b_[0], b_[1]), (b_[2], b_[1]), (b_[0], b_[3]), (b_[2], b_[3])]
        ts, ns = [T(z) for z in cs], [N(z) for z in cs]
        slack = 0.02 if lay in (WINDOW_LAYER, WALL_LAYER) else 1.4
        if min(ts) >= t0 - 0.02 and max(ts) <= t1 + 0.02 and min(ns) >= n0 - slack and max(ns) <= n1 + slack:
            if lay == WALL_LAYER and t_ == "LINE" and _par(segs_of(e)[0], u):
                continue  # a face: moved as a face
            out.append(e)
    return out


def cut_face(msp, q, u, n, a, b, nn):
    """Break the one wall face at offset nn between a and b (a partition joining it: a T-junction)."""
    T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
    N = lambda z: (z[0] - q[0]) * n[0] + (z[1] - q[1]) * n[1]
    for e, s_ in _wall_lines(msp):
        if not _par(s_, u) or abs((N(s_[0]) + N(s_[1])) / 2 - nn) > 0.012:
            continue
        ta, tb = T(s_[0]), T(s_[1])
        lo, hi = sorted((ta, tb))
        if hi <= a + 0.001 or lo >= b - 0.001:
            continue
        attrs = {k: e.dxf.get(k) for k in ("layer", "linetype", "color") if e.dxf.hasattr(k)}
        P = lambda t: (s_[0][0] + (s_[1][0] - s_[0][0]) * (t - ta) / (tb - ta), s_[0][1] + (s_[1][1] - s_[0][1]) * (t - ta) / (tb - ta))
        msp.delete_entity(e)
        for x, y in ((lo, a), (b, hi)):
            if y - x > 0.002:
                msp.add_line(P(x), P(y), dxfattribs=attrs)


def _snap_end(msp, end, d, t):
    """Where a new wall's end meets an existing wall it runs into: (point on that wall's near face, its frame) or None."""
    wa = wall_at(msp, end)
    if not wa:
        # a little short of the wall: look a few cm on along the new wall
        for k in (0.05, 0.1, 0.15, 0.2):
            wa = wall_at(msp, (end[0] + d[0] * k, end[1] + d[1] * k))
            if wa:
                break
    if not wa:
        return None
    q, u, n, n0, n1 = wa
    if abs(d[0] * u[0] + d[1] * u[1]) > 0.17:
        return None  # it meets that wall at a slant: left free
    # the near face: the one facing the new wall's body (back along -d)
    side = -(d[0] * n[0] + d[1] * n[1])
    nn = n1 if side > 0 else n0
    T = (end[0] - q[0]) * u[0] + (end[1] - q[1]) * u[1]
    return (q[0] + u[0] * T + n[0] * nn, q[1] + u[1] * T + n[1] * nn), (q, u, n, nn)


def add_wall(msp, A, B, t, align="centre", through=None):
    """A new wall from A to B (DWG), t thick: two face lines (a curve through `through` as short straight pieces),
    each end run onto the wall it meets (that wall's face broken between the new faces: a T-junction) or capped."""
    if math.dist(A, B) < 0.2:
        raise ValueError("a wall needs to be at least 20 cm long")
    if not 0.05 <= t <= 0.5:
        raise ValueError("a wall is 5 to 50 cm thick")
    pts = [A, B]
    if through:  # a circular arc A -> through -> B as ~25 cm pieces
        (x1, y1), (x2, y2), (x3, y3) = A, through, B
        dd = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if abs(dd) < 1e-9:
            raise ValueError("those three points are in a line: a straight wall")
        ux = ((x1 ** 2 + y1 ** 2) * (y2 - y3) + (x2 ** 2 + y2 ** 2) * (y3 - y1) + (x3 ** 2 + y3 ** 2) * (y1 - y2)) / dd
        uy = ((x1 ** 2 + y1 ** 2) * (x3 - x2) + (x2 ** 2 + y2 ** 2) * (x1 - x3) + (x3 ** 2 + y3 ** 2) * (x2 - x1)) / dd
        R = math.dist((ux, uy), A)
        a1, a2, a3 = (math.atan2(z[1] - uy, z[0] - ux) for z in (A, through, B))
        ccw = (a2 - a1) % (2 * math.pi) < (a3 - a1) % (2 * math.pi)
        span = (a3 - a1) % (2 * math.pi) if ccw else -((a1 - a3) % (2 * math.pi))
        k = max(4, int(abs(span) * R / 0.25))
        pts = [(ux + R * math.cos(a1 + span * i / k), uy + R * math.sin(a1 + span * i / k)) for i in range(k + 1)]
    off = {"centre": (-t / 2, t / 2), "left": (0, t), "right": (-t, 0)}.get(align)
    if off is None:
        raise ValueError("align is centre, left or right (of the line from a to b)")
    dirs = []
    for i in range(len(pts) - 1):
        L = math.dist(pts[i], pts[i + 1])
        dirs.append(((pts[i + 1][0] - pts[i][0]) / L, (pts[i + 1][1] - pts[i][1]) / L))
    # snap the ends onto the walls they meet
    ends = []
    for k_, (z, d) in enumerate(((pts[0], (-dirs[0][0], -dirs[0][1])), (pts[-1], dirs[-1]))):
        sn = _snap_end(msp, z, d, t)
        if sn:
            hit, fr = sn
            pts[0 if k_ == 0 else -1] = hit
        ends.append(sn and sn[1])
    def nrm(i):  # the left normal at point i (averaged at a bend)
        ds = [dirs[j] for j in (i - 1, i) if 0 <= j < len(dirs)]
        x, y = sum(d[0] for d in ds), sum(d[1] for d in ds)
        L = math.hypot(x, y)
        return (-y / L, x / L)
    faces = []
    for o in off:
        faces.append([(z[0] + nrm(i)[0] * o, z[1] + nrm(i)[1] * o) for i, z in enumerate(pts)])
    attrs = {"layer": WALL_LAYER}
    new = []
    for f in faces:
        for i in range(len(f) - 1):
            new.append(msp.add_line(f[i], f[i + 1], dxfattribs=attrs).dxf.handle)
    for k_, fr in enumerate(ends):
        i = 0 if k_ == 0 else -1
        a_, b_ = faces[0][i], faces[1][i]
        if fr:  # T-junction: break that wall's near face between the new faces
            q, u, n, nn = fr
            T = lambda z: (z[0] - q[0]) * u[0] + (z[1] - q[1]) * u[1]
            lo, hi = sorted((T(a_), T(b_)))
            cut_face(msp, q, u, n, lo, hi, nn)
        else:
            new.append(msp.add_line(a_, b_, dxfattribs=attrs).dxf.handle)
    return pts, faces, new, [bool(e) for e in ends]


def remove_wall(msp, p):
    """The wall at p, junction to junction, with what sits in it. A through wall it was broken for is joined up again;
    a wall left with an open end (it went on past a junction, or turned a corner into this one) is capped."""
    run = wall_run(msp, p)
    if not run:
        raise ValueError("no wall there: give a point on (inside) the wall")
    q, u, n, n0, n1, t0, t1 = run
    split_faces(msp, q, u, n, n0, n1, (t0, t1))
    pieces = run_pieces(msp, q, u, n, (n0, n1), t0, t1)
    stuff = carried(msp, q, u, n, n0, n1, t0, t1)
    ends = [z for _, s_, _ in pieces for z in s_]
    for e in stuff:
        msp.delete_entity(e)
    for e, _, _ in pieces:
        msp.delete_entity(e)
    for e, s_ in _wall_lines(msp):  # caps / jambs across the removed wall's ends
        if _par(s_, n) and math.dist(*s_) <= (n1 - n0) + 0.03 and all(any(math.dist(z, w) < 0.004 for w in ends) for z in s_):
            msp.delete_entity(e)
    touch = [(e, s_, i, e.dxf.handle) for e, s_ in _wall_lines(msp) for i, z in enumerate(s_) if any(math.dist(z, w) < 0.004 for w in ends)]
    used = set()
    for x in touch:  # a through wall's face broken for this one: its two pieces joined
        for y in touch:
            if x[3] == y[3] or {x[3], y[3]} & used:
                continue
            ux = ((x[1][1][0] - x[1][0][0]) / math.dist(*x[1]), (x[1][1][1] - x[1][0][1]) / math.dist(*x[1]))
            if not _par(y[1], ux) or LineString(x[1]).distance(Point(y[1][0])) > 0.004 and \
                    abs((y[1][0][0] - x[1][0][0]) * -ux[1] + (y[1][0][1] - x[1][0][1]) * ux[0]) > 0.004:
                continue
            attrs = {k: x[0].dxf.get(k) for k in ("layer", "linetype", "color") if x[0].dxf.hasattr(k)}
            far_x, far_y = x[1][1 - x[2]], y[1][1 - y[2]]
            msp.delete_entity(x[0]); msp.delete_entity(y[0])
            msp.add_line(far_x, far_y, dxfattribs=attrs)
            used |= {x[3], y[3]}
    left = [x[1][x[2]] for x in touch if x[3] not in used]
    capped, done = 0, set()
    for i, za in enumerate(left):  # ends left open where the wall stood: closed across its footprint (along n)
        for j, zb in enumerate(left):
            if j <= i or i in done or j in done:
                continue
            dd = math.dist(za, zb)
            if 0.03 <= dd <= 0.45 and abs((zb[0] - za[0]) * u[0] + (zb[1] - za[1]) * u[1]) < 0.02:
                msp.add_line(za, zb, dxfattribs={"layer": WALL_LAYER})
                capped += 1
                done |= {i, j}
    return q, u, n, n0, n1, t0, t1, len(pieces) + len(stuff), capped


def move_wall(msp, p, shift, faces="both"):
    """Slide the wall at p (junction to junction) by `shift` metres along its normal (+ = its n side), or only one
    face (`faces` = the offset to move: thickness change). Walls meeting it follow; where the same straight wall
    carries on past a junction, the moved stretch is joined to it with a short jog."""
    run = wall_run(msp, p)
    if not run:
        raise ValueError("no wall there: give a point on (inside) the wall")
    q, u, n, n0, n1, t0, t1 = run
    which = (n0, n1) if faces == "both" else (faces,)
    split_faces(msp, q, u, n, n0, n1, (t0, t1))
    pieces = run_pieces(msp, q, u, n, which, t0, t1)
    d = (n[0] * shift, n[1] * shift)
    stay = [(e, s_) for e, s_ in _wall_lines(msp) if _par(s_, u) and e.dxf.handle not in {x[0].dxf.handle for x in pieces}]
    old_ends = [z for _, s_, _ in pieces for z in s_]
    jogs = [z for z in old_ends if any(any(math.dist(z, w) < 0.003 for w in s_) for _, s_ in stay)]
    carry = carried(msp, q, u, n, n0, n1, t0, t1) if faces == "both" else []
    if faces != "both":  # a window's lines on the moved face stretch with it
        for e in msp.query(f'LINE[layer=="{WINDOW_LAYER}"]'):
            s_ = segs_of(e)[0]
            for i, z in enumerate(s_):
                if any(LineString(g).distance(Point(z)) < 0.003 for _, g, _ in pieces):
                    _move_end(e, i, d)
    move_faces(msp, pieces, d, u, carry)
    for z in jogs:
        msp.add_line(z, (z[0] + d[0], z[1] + d[1]), dxfattribs={"layer": WALL_LAYER})
    # every moved end should still meet a wall line; one that doesn't (slid past the column / wall it stopped on) is
    # reported, not guessed at
    mine = {e.dxf.handle for e, _, _ in pieces}
    others = [g for e, g in _wall_lines(msp) if e.dxf.handle not in mine]
    loose = sorted({(round(z[0] + d[0], 3), round(z[1] + d[1], 3)) for z in old_ends
                    if not any(LineString(g).distance(Point(z[0] + d[0], z[1] + d[1])) < 0.004 for g in others)})
    return q, u, n, n0, n1, t0, t1, len(pieces), len(jogs), loose


def rename_room(msp, at=None, name=None, to=None):
    """A room's name (ISLAK TEXT, the label the 3D names its room by): its words changed, a two-line name made one."""
    if not to or not str(to).strip():
        raise ValueError("say the new name")
    txts = [e for e in msp.query("TEXT MTEXT") if e.dxf.layer == LABEL_LAYER]
    word = lambda e: (e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text).strip().rstrip(".")
    pos = lambda e: (e.dxf.insert.x, e.dxf.insert.y)
    groups, seen = [], set()
    for e in sorted(txts, key=lambda e: -pos(e)[1]):  # two-line names ("MASTER" over "BEDROOM.") are one name
        if e.dxf.handle in seen:
            continue
        g = [e]
        seen.add(e.dxf.handle)
        for f in sorted(txts, key=lambda f: -pos(f)[1]):
            if f.dxf.handle not in seen and abs(pos(f)[0] - pos(g[-1])[0]) < 1.0 and 0 < pos(g[-1])[1] - pos(f)[1] < 0.6:
                g.append(f)
                seen.add(f.dxf.handle)
        groups.append(g)
    key = lambda g: " ".join(word(e) for e in g).upper()
    if name:
        want = str(name).strip().upper().rstrip(".")
        hit = [g for g in groups if key(g) == want or key(g) == " ".join(want.split()[:-1]) and want.split()[-1].isdigit()]
    else:
        hit = sorted(groups, key=lambda g: math.dist(pos(g[0]), at))[:1] if at else []
    if not hit:
        raise ValueError(f"no room name {name or at} on the plan; names: {sorted({key(g) for g in groups})}")
    g = hit[0]
    old = key(g)
    first = g[0]
    if first.dxftype() == "MTEXT":
        first.text = str(to).strip().upper()
    else:
        first.dxf.text = str(to).strip().upper()
    for e in g[1:]:
        msp.delete_entity(e)
    return old, str(to).strip().upper(), pos(first)


def add_room_label(msp, at, name):
    """A room name for a new room: TEXT on ISLAK in the style of the plan's other names."""
    if not name or not str(name).strip():
        raise ValueError("say the room's name")
    like = next((e for e in msp.query("TEXT") if e.dxf.layer == LABEL_LAYER), None)
    attrs = {"layer": LABEL_LAYER, "height": like.dxf.height if like else 0.2}
    if like is not None:
        for k in ("style", "color", "width"):
            if like.dxf.hasattr(k):
                attrs[k] = like.dxf.get(k)
    t = msp.add_text(str(name).strip().upper(), dxfattribs=attrs)
    t.dxf.insert = (at[0], at[1], 0)
    return t.dxf.handle


def niche_box(msp, p, width, depth, side=None):
    """A recess into the wall at p: (box corners in DWG, the face it opens from)."""
    wa = wall_at(msp, p)
    if not wa:
        raise ValueError("no wall there: give a point on the wall's face")
    q, u, n, n0, n1 = wa
    th = n1 - n0
    if not 0.02 <= depth <= th - 0.02:
        raise ValueError(f"this wall is {r(th)} m thick: a niche can go {r(max(0, th - 0.02))} m deep at most")
    face = (n1 if _side(side, n) > 0 else n0) if side else (n0 if abs(n0) < abs(n1) else n1)
    inward = 1 if face == n0 else -1
    P = lambda t, nn: (q[0] + u[0] * t + n[0] * nn, q[1] + u[1] * t + n[1] * nn)
    box_ = [P(-width / 2, face), P(width / 2, face), P(width / 2, face + inward * depth), P(-width / 2, face + inward * depth)]
    return box_, face


def opening_report(q, u, n, a, b, n0, n1, kind, drawn, ox, oy):  # noqa: C901
    P = lambda t, nn: _at(None, q, t, nn, u, n)
    pl = lambda z: [r(z[0] - ox), r(z[1] - oy)]
    c = P((a + b) / 2, (n0 + n1) / 2)
    rep = {"kind": kind, "centre": pl(c), "width": r(b - a), "wall_thickness": r(n1 - n0),
           "box": [pl(P(a, n0)), pl(P(b, n1))], "along": "x" if abs(u[0]) > abs(u[1]) else "y"}
    if drawn.get("hinges"):
        rep["hinges"] = [pl(h) for h in drawn["hinges"]]
    if drawn.get("hinge"):
        rep["hinge"] = pl(drawn["hinge"])
        sg = 1 if drawn["opens"] == "+n" else -1
        v = (n[0] * sg, n[1] * sg)
        rep["opens"] = "N" if v[1] > 0.5 else "S" if v[1] < -0.5 else "E" if v[0] > 0.5 else "W"
    return rep


def edit(a):
    doc, _ = recover.readfile(a.src)
    msp = doc.modelspace()
    ox, oy = map(float, a.origin.split(","))
    W = lambda p: (float(p[0]) + ox, float(p[1]) + oy)
    before = Counter(e.dxf.layer for e in msp)
    ops = json.load(sys.stdin)
    log, new, touched, moved, opened, swing_hits = [], [], set(), [], [], []
    walls_changed, renamed, niches_ = [], [], []
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
            raise ValueError(f"{h} is inside a door block (INSERT): it can't be edited piece by piece. To change that "
                             "door, convert_opening it (handle: the INSERT) to \"door\" (or what the user wants): it is redrawn")
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
        elif k == "rotate":  # several entities turned together about centre (plan metres), then moved
            cx, cy = W(o["centre"])
            dx, dy, ang = float(o.get("dx", 0)), float(o.get("dy", 0)), float(o["angle"])
            for h in o["handles"]:
                e = get(h)
                touched.add(e.dxf.handle)
                e.translate(-cx, -cy, 0)
                e.rotate_z(math.radians(ang))
                e.translate(cx + dx, cy + dy, 0)
            log.append(f"turned {len(o['handles'])} by {r(ang)} degrees about ({r(cx - ox)}, {r(cy - oy)}), moved by ({dx}, {dy})")
        elif k == "scale":  # several entities stretched together: x' = base + (x - base)·sx + dx (plan metres), likewise y
            from ezdxf.math import Matrix44
            bx, by = W(o["base"])
            sx, sy, dx, dy = float(o["sx"]), float(o["sy"]), float(o.get("dx", 0)), float(o.get("dy", 0))
            m = Matrix44.chain(Matrix44.translate(-bx, -by, 0), Matrix44.scale(sx, sy, 1), Matrix44.translate(bx + dx, by + dy, 0))
            for h in o["handles"]:
                e = get(h)
                touched.add(e.dxf.handle)
                try:
                    e.transform(m)
                except Exception:  # a circle / arc can't stretch one way only: its centre moves, its radius takes the smaller
                    if e.dxftype() not in ("CIRCLE", "ARC"):
                        raise ValueError(f"{e.dxftype()} {e.dxf.handle} can't be stretched that way (turned in its block?)")
                    c = e.dxf.center
                    e.dxf.center = (bx + (c.x - bx) * sx + dx, by + (c.y - by) * sy + dy, c.z)
                    e.dxf.radius *= min(sx, sy)
            log.append(f"stretched {len(o['handles'])} by ({r(sx)}, {r(sy)}) from ({r(bx - ox)}, {r(by - oy)}), moved by ({dx}, {dy})")
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
            gone_, n_del_ = {real(h) for h in o["handles"]}, 0
            for h in o["handles"]:
                e = get(h)
                b = ext_of(e) if e.dxf.layer in FURNI else None
                if b and not (e.dxftype() == "LWPOLYLINE" and len(e) >= 4 and area_(b) >= 0.04):
                    own = [(area_(b2), e2.dxf.handle, b2) for e2, b2 in outl_ if e2.dxf.handle not in gone_
                           and b2[0] - 0.01 <= b[0] and b[2] <= b2[2] + 0.01 and b2[1] - 0.01 <= b[1] and b[3] <= b2[3] + 0.01]
                    if own and not o.get("detail"):
                        _, oh, ob_ = min(own)
                        details_cut.append(f"{e.dxf.handle} (a {e.dxftype()} drawn inside piece {oh}, x {r(ob_[0] - ox)}..{r(ob_[2] - ox)}, "
                                           f"y {r(ob_[1] - oy)}..{r(ob_[3] - oy)}, which stays)")
                        continue  # kept: a line of a piece that stays isn't a piece of its own
                msp.delete_entity(e)
                n_del_ += 1
            log.append(f"deleted {n_del_}")
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
        elif k == "rotate_piece":
            e0 = get(o["handle"])
            ents = [e0] if e0.dxftype() == "INSERT" else piece_members(msp, e0)[0]
            b = ext_of(e0)
            cx, cy = W(o["centre"]) if o.get("centre") else ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            dx, dy, ang = float(o.get("dx", 0)), float(o.get("dy", 0)), float(o["angle"])
            for e in ents:
                touched.add(e.dxf.handle)
                e.translate(-cx, -cy, 0)
                e.rotate_z(math.radians(ang))
                e.translate(cx + dx, cy + dy, 0)
            b = ext_of(e0)
            log.append(f"piece {o['handle']} ({len(ents)} entities) turned {r(ang)} degrees about ({r(cx - ox)}, {r(cy - oy)}) "
                       f"and moved by ({dx}, {dy}); now x {r(b[0] - ox)}..{r(b[2] - ox)}, y {r(b[1] - oy)}..{r(b[3] - oy)}")
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
            try:  # allow_overlap (Move and Resize: the user dragged it there): no stopping at walls / neighbours
                spans = ([None, None], [None, None]) if o.get("allow_overlap") else room_around(msp, doc, o["handle"], soft)
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
                                 "block (INSERT): convert_opening it to \"door\" first (it is redrawn as a loose door), then move it")
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
        elif k in ("add_wall", "remove_wall", "move_wall", "set_wall_thickness", "mark_wall"):
            P_ = lambda q_, u_, n_, t_, nn_: [r(q_[0] + u_[0] * t_ + n_[0] * nn_ - ox), r(q_[1] + u_[1] * t_ + n_[1] * nn_ - oy)]
            if k == "add_wall":
                pts_, faces_, nh_, snapped_ = add_wall(msp, W(o["a"]), W(o["b"]), float(o.get("thickness") or 0.12),
                                                     o.get("align") or "centre", W(o["through"]) if o.get("through") else None)
                new += nh_
                ch_ = {"op": k, "a": [r(pts_[0][0] - ox), r(pts_[0][1] - oy)], "b": [r(pts_[-1][0] - ox), r(pts_[-1][1] - oy)],
                       "thickness": float(o.get("thickness") or 0.12), "joined": snapped_, "curved": bool(o.get("through"))}
                log.append(f"wall {ch_['a']} -> {ch_['b']}, {ch_['thickness']} m thick" + (", curved" if o.get("through") else "")
                           + f"; ends {'joined to a wall' if snapped_[0] else 'free (capped)'} / {'joined to a wall' if snapped_[1] else 'free (capped)'}")
            else:
                at_ = W(o["at"])
                run_ = wall_run(msp, at_)
                if not run_:
                    raise ValueError(f"no wall at {o['at']}: give a point on (inside) the wall")
                q, u, n, n0, n1, t0, t1 = run_
                mid_ = (n0 + n1) / 2
                ch_ = {"op": k, "a": P_(q, u, n, t0, mid_), "b": P_(q, u, n, t1, mid_), "thickness": r(n1 - n0)}
                if k == "remove_wall":
                    *_, cnt_, cap_ = remove_wall(msp, at_)
                    log.append(f"wall {ch_['a']} -> {ch_['b']} removed ({cnt_} entities; {cap_} open end(s) capped)")
                elif k == "move_wall":
                    sh_ = float(o.get("dx", 0)) * n[0] + float(o.get("dy", 0)) * n[1]
                    if abs(sh_) < 0.002:
                        raise ValueError("dx / dy must be across the wall (a wall slides sideways, not along itself)")
                    *_, np_, jg_, loose_ = move_wall(msp, at_, sh_)
                    ch_["moved"] = [r(n[0] * sh_), r(n[1] * sh_)]
                    log.append(f"wall {ch_['a']} -> {ch_['b']} moved {ch_['moved']} ({np_} face lines; {jg_} jog(s) to the wall it carries on as)")
                    if loose_:
                        swing_hits.append(f"after the move, wall end(s) {[[r(x - ox), r(y - oy)] for x, y in loose_]} no longer meet "
                                          "a wall (they slid past the column / wall they stopped on): extend the wall to the next "
                                          "face with set_points, or move it less")
                elif k == "set_wall_thickness":
                    new_t = float(o["thickness"])
                    if not 0.05 <= new_t <= 0.5:
                        raise ValueError("a wall is 5 to 50 cm thick")
                    dt = new_t - (n1 - n0)
                    keep = o.get("keep")
                    moves = [(n1, dt / 2), (n0, -dt / 2)] if not keep else ([(n0, -dt)] if _side(keep, n) > 0 else [(n1, dt)])
                    for face_, sh_ in moves:
                        run2 = wall_run(msp, at_)
                        f_ = min((run2[3], run2[4]), key=lambda v: abs(v - face_)) if run2 else face_
                        *_, loose_ = move_wall(msp, at_, sh_, faces=f_)
                        if loose_:
                            swing_hits.append(f"the thicker wall's end(s) {[[r(x - ox), r(y - oy)] for x, y in loose_]} no "
                                              "longer meet a wall: check that junction")
                    ch_["thickness"] = new_t
                    log.append(f"wall {ch_['a']} -> {ch_['b']}: {r(n1 - n0)} -> {new_t} m thick")
                else:
                    log.append(f"wall {ch_['a']} -> {ch_['b']} ({ch_['thickness']} m thick) marked")
            for key_ in ("height", "glass"):
                if o.get(key_) is not None:
                    ch_[key_] = o[key_]
            walls_changed.append(ch_)
        elif k in ("rename_room", "add_room_label"):
            if k == "rename_room":
                old_, new_n, at_ = rename_room(msp, W(o["at"]) if o.get("at") else None, o.get("name"), o.get("to"))
                renamed.append({"old": old_, "new": new_n})
                log.append(f"room {old_} is now {new_n}")
            else:
                h_ = add_room_label(msp, W(o["at"]), o.get("name"))
                renamed.append({"old": None, "new": str(o["name"]).strip().upper(), "at": o["at"]})
                log.append(f"room name {o['name']} added at {o['at']} ({h_})")
        elif k == "add_niche":
            w_, dp_ = float(o.get("width") or 0.6), float(o.get("depth") or 0.1)
            box_, face_ = niche_box(msp, W(o["at"]), w_, dp_, o.get("side"))
            lt_ = next((n_ for n_ in ("DASHED2", "DASHED", "HIDDEN") if n_ in doc.linetypes), None)
            for i_ in range(4):  # dashed, as the plan draws its niches (and the build skips dashed lines)
                msp.add_line(box_[i_], box_[(i_ + 1) % 4], dxfattribs={"layer": WALL_LAYER, **({"linetype": lt_} if lt_ else {})})
            bottom_, top_ = float(o.get("bottom", 0.9)), float(o.get("top", 1.5))
            if not 0 <= bottom_ < top_:
                raise ValueError("a niche's top must be above its bottom")
            niches_.append({"box": [[r(z[0] - ox), r(z[1] - oy)] for z in box_], "bottom": bottom_, "top": top_})
            log.append(f"niche {w_} x {dp_} m deep, {bottom_}-{top_} m up, at {o['at']}")
        elif k in ("add_opening", "convert_opening", "remove_opening"):
            to = "wall" if k == "remove_opening" else o.get("kind" if k == "add_opening" else "to")
            if to not in KINDS + (("wall",) if k != "add_opening" else ()):
                raise ValueError(f"kind must be one of {', '.join(KINDS)}" + (" or wall" if k != "add_opening" else ""))
            if k == "add_opening":
                q_ = W(o["at"])
                wa = wall_at(msp, q_)
                if not wa:
                    raise ValueError(f"no wall (two faces) at {o['at']}: give a point on the wall, e.g. from dxf_query 1wall")
                q, u, n, n0, n1 = wa
                w = float(o.get("width") or (0.9 if to in ("door", "opening", "sliding_door") else 1.2))
                a_, b_ = -w / 2, w / 2
                old = None
            else:
                seeds = []
                if o.get("handle"):
                    e = get(o["handle"])
                    if e.dxftype() == "ARC":
                        c_ = (e.dxf.center.x, e.dxf.center.y)
                        seeds += [((c_[0] + z.x) / 2, (c_[1] + z.y) / 2) for z in (e.start_point, e.end_point)]
                    elif e.dxf.layer == WINDOW_LAYER:
                        seeds.append(frame(window_cluster(msp, e))[0])
                    elif e.dxftype() == "INSERT":
                        seeds.append((e.dxf.insert.x, e.dxf.insert.y))
                    else:
                        raise ValueError(f"{o['handle']} isn't a window line, a door swing ARC or a door INSERT: give at [x, y] instead")
                if o.get("at"):
                    seeds.append(W(o["at"]))
                g = None
                for z in seeds:
                    g = gap_at(msp, z)
                    for ax_ in ([] if g else _axes(_wall_lines(msp), z)):
                        for d in (0.3, -0.3, 0.45, -0.45, 0.6, -0.6):
                            g = gap_at(msp, (z[0] + ax_[0] * d, z[1] + ax_[1] * d))
                            if g:
                                break
                        if g:
                            break
                    if g:
                        break
                if not g:
                    raise ValueError("no door / window / doorway found there: give a point inside the opening (between its jambs)")
                q, u, n, t0, t1, n0, n1 = g
                old = opening_report(q, u, n, t0, t1, n0, n1, "old", {}, ox, oy)
                cleared = clear_gap(msp, q, u, n, t0, t1, n0, n1)
                close_gap(msp, q, u, n, t0, t1, n0, n1)
                w = float(o.get("width") or (t1 - t0))
                mid = (t0 + t1) / 2 + float(o.get("shift") or 0)
                a_, b_ = mid - w / 2, mid + w / 2
            drawn = {}
            if to != "wall":
                open_gap(msp, q, u, n, a_, b_, n0, n1)
                drawn = draw_opening(msp, q, u, n, a_, b_, n0, n1, to, o.get("hinge"), o.get("opens"))
            rep_ = opening_report(q, u, n, a_, b_, n0, n1, to, drawn, ox, oy)
            if drawn.get("hinges"):  # double doors: each leaf's swing
                drawn["sweep"] = None
            if drawn.get("sweep"):  # a door must open into clear floor: furniture lines and fixture blocks in its swing
                from shapely.geometry import Polygon as _Poly, box as _box
                sweep_ = _Poly(drawn["sweep"]).buffer(-0.02)
                for f_ in msp:
                    t3 = f_.dxftype()
                    if t3 == "INSERT" and f_.dxf.layer != DOOR_LAYER:
                        b3 = ext_of(f_)
                        hit_ = b3 and sweep_.intersection(_box(*b3)).area > 0.003
                    elif f_.dxf.layer in FURNI and t3 in ("LINE", "LWPOLYLINE"):
                        hit_ = any(sweep_.intersection(LineString(sg)).length > 0.03 for sg in segs_of(f_))
                    else:
                        continue
                    if hit_:
                        b3 = ext_of(f_)
                        swing_hits.append(f"the door at {rep_['centre']} swings into {getattr(f_.dxf, 'name', '') or t3} "
                                          f"{f_.dxf.handle} on {f_.dxf.layer} (x {r(b3[0] - ox)}..{r(b3[2] - ox)}, y "
                                          f"{r(b3[1] - oy)}..{r(b3[3] - oy)}): open it the other way (opens / hinge), use a "
                                          "sliding_door, or move that piece")
            if old:
                rep_["old_box"], rep_["old_width"] = old["box"], old["width"]
            opened.append(rep_)
            log.append(f"{k}: {to} {rep_['width']} m wide at {rep_['centre']}" + (f", hinge {rep_['hinge']}, opens {rep_['opens']}"
                       if rep_.get("hinge") else "") + (f" (was {old['width']} m, {cleared} entities cleared)" if old else ""))
        else:
            raise ValueError(f"unknown op {k!r}")
    # No zero-length lines left behind.
    zero = [e.dxf.handle for e in msp.query("LINE")
            if e.dxf.handle in touched | set(new) and (e.dxf.start - e.dxf.end).magnitude < 1e-4]
    for h in zero:
        msp.delete_entity(doc.entitydb.get(h))
    warnings, seen = list(swing_hits), set()
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
                      "furniture_changed": bool(layers_hit & set(FURNI)) and not (  # not when every piece touched stayed put
                          touched and touched <= set(pieces0) and not pieces and not new and not any(k in FURNI for k in delta)),
                      **({"handles_remapped": vmap} if vmap else {}),
                      **({"pieces_changed": pieces} if pieces else {}),
                      **({"clashes_checked": check, "clashes": clash} if check else {}),
                      **({"windows_moved": moved} if moved else {}),
                      **({"openings_changed": opened} if opened else {}),
                      **({"walls_changed": walls_changed} if walls_changed else {}),
                      **({"rooms_renamed": renamed} if renamed else {}),
                      **({"niches": niches_} if niches_ else {}),
                      **({"warnings": warnings + [f"KEPT {d}: it is a detail line of a piece that stays, not a piece of its own. "
                          "A part built inside another piece (a stool under a dressing table, a drawer front) has no outline "
                          "of its own, so removing that part is a 3D-only change: keep your furnish.js edit, the plan is right "
                          "as it is, don't delete that line. Only when the user asked for that drawn line itself to go (they pointed at the line, not at a part of the piece), delete it with \"detail\": true"
                          for d in details_cut]}
                         if warnings or details_cut else {})}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("query"); q.add_argument("src"); q.add_argument("--origin", required=True)
    q.add_argument("--bbox", required=True); q.add_argument("--layers"); q.add_argument("--limit", default="150")
    q.add_argument("--blocks", action="store_true")
    e = sub.add_parser("edit"); e.add_argument("src"); e.add_argument("out"); e.add_argument("--origin", required=True)
    e.add_argument("--soft", default="")
    a = p.parse_args()
    try:
        query(a) if a.cmd == "query" else edit(a)
    except Exception as ex:
        print(json.dumps({"error": f"{type(ex).__name__}: {ex}"}))
        sys.exit(1)
