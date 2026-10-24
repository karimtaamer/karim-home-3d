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
New entities copy colour and linetype ByLayer. No TEXT is ever added (every TEXT becomes a room label in the 3D).
"""
import argparse, json, sys
from collections import Counter

from ezdxf import recover

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
    out.sort(key=lambda d: (d["layer"], d["type"]))
    print(json.dumps({"count": len(out), "entities": out[:int(a.limit)], "truncated": len(out) > int(a.limit)}))


def edit(a):
    doc, _ = recover.readfile(a.src)
    msp = doc.modelspace()
    ox, oy = map(float, a.origin.split(","))
    W = lambda p: (float(p[0]) + ox, float(p[1]) + oy)
    before = Counter(e.dxf.layer for e in msp)
    ops = json.load(sys.stdin)
    log, new, touched = [], [], set()

    def get(h):
        touched.add(h)
        e = doc.entitydb.get(h)
        if e is None or not e.is_alive or e.get_layout() is None or e.get_layout().name != msp.name:
            raise ValueError(f"no model-space entity with handle {h}")
        return e

    def attrs(layer):
        if layer not in ADD_LAYERS:
            raise ValueError(f"layer {layer!r} is not one Edit AI may draw on ({', '.join(sorted(ADD_LAYERS))})")
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
        else:
            raise ValueError(f"unknown op {k!r}")
    # No zero-length lines left behind.
    zero = [e.dxf.handle for e in msp.query("LINE")
            if e.dxf.handle in touched | set(new) and (e.dxf.start - e.dxf.end).magnitude < 1e-4]
    for h in zero:
        msp.delete_entity(doc.entitydb.get(h))
    auditor = doc.audit()
    doc.saveas(a.out)
    after = Counter(e.dxf.layer for e in msp)
    delta = {k: after[k] - before[k] for k in set(before) | set(after) if after[k] != before[k]}
    print(json.dumps({"log": log, "new_handles": new, "layer_count_change": delta,
                      "removed_zero_length": zero, "audit_errors": len(auditor.errors)}))


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
