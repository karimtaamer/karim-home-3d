#!/usr/bin/env python3
"""Turn a DXF floor plan into model.js (walls, openings, furniture, labels) for the Three.js viewer.

Usage: ~/.dwg-tools/bin/python build_geometry.py <plan.dxf> [--out model.js] [--tour tour.json] [--wall x0,y0,x1,y1 ...] [--window x,y,sill,head[,frosted] ...] [--debug debug.png]
(--out / --tour name another plan version's model and tour, e.g. model-naghams-changes.js and
tour-naghams-changes.json; see VERSIONS in index.html. --wall adds a wall face line the drawing
left out, in DWG coordinates; repeat it for several. --window gives one window its own sill and head,
and frosted glass, without touching the others.)

The version's tour JSON may also carry (Edit AI writes them; DWG coordinates):
    "heights": {"ceiling": 2.6, "door": 2.1, "sill": 0.9, "window": 2.1, "slider": 2.4, "parapet": 1.1}
        home-wide heights in metres (any left out keep the defaults below)
    "openings": [{"at": [x, y], "kind": "window" | "slider" | "door", "sill": 0.6, "head": 2.4, "frosted": true,
                  "panel": "glass" | "wood"}]
        the opening holding point `at` becomes that kind (a terrace window stays a window instead of a slider, a bare
        doorway becomes a sliding door) and gets its own sill / head (doors and sliders: head) / glass / panel; any
        other keys (frame, leaf, glass, panes, style, handle, arch, fanlight...) go to the viewer as they are.
    "rooms": {"NAME": {"kind": "wet" | "dry" | "outdoor", ...}}   a room's kind (floor / lining defaults); the rest
        (floor, walls, ceiling, ceilingHeight, skirting, tileHeight, floorLevel, light, skylights) goes to the viewer
    "walls": [{"a": [x, y], "b": [x, y], "thickness": 0.12, "height": 1.1, "glass": true}]
        that stretch of wall built low (height) and / or as glass instead of a full-height solid wall
    "niches": [{"box": [[x, y], ...4], "bottom": 0.9, "top": 1.5}]   a recess carved into the wall, solid below / above
    "notes": [{"at": [x, y], "text": "..."}]   pinned notes; "start": [x, y] where the walk-through starts;
    "parapet": {"glass": true}   every terrace parapet built as a glass balustrade (its height: heights.parapet)
"""
import heapq
import json
import math
import sys
from pathlib import Path

from ezdxf import path as ezpath
from ezdxf import recover
from shapely.geometry import LineString, MultiPoint, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union, voronoi_diagram
from shapely.strtree import STRtree
from shapely.validation import make_valid

WALL_LAYER, WINDOW_LAYER, DOOR_LAYER, FURNI_LAYERS = "1wall", "Windows", "3door", ("2furni", "2 furni")
CEILING, DOOR_HEAD, SILL, WIN_HEAD, PARAPET, SLIDER_HEAD = 2.6, 2.1, 0.9, 2.1, 1.1, 2.4
LOOK = ("frame", "leaf", "glass", "panes", "transoms", "style", "handle", "arch", "fanlight", "shape")  # opening looks
CLEARANCE, GRID = 0.18, 0.1  # tour camera keeps this far from walls; path-finding grid (m)
WET = ("kitchen", "toilet", "bath", "wc", "laundry", "shower", "مطبخ", "حمام", "غسيل")
OUTDOOR = ("terrace", "balcony", "garden", "roof", "تراس", "بلكونة", "شرفة", "حديقة")
LINE_LAYERS = {WALL_LAYER: "wall", WINDOW_LAYER: "window", DOOR_LAYER: "door", "2furni": "furniture", "2 furni": "furniture"}
MIN_T, MAX_T = 0.04, 0.5  # wall thickness range (m)
BRIDGE = 0.75  # closes gaps up to 1.5 m (doors / windows)
SKIN = 0.01  # room lining thickness (m): wall tiles / skirting sit on this, the walls stay as drawn


def as_polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def entity_segments(e):
    t = e.dxftype()
    if t == "LINE":
        return [((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y))]
    if t == "LWPOLYLINE":
        p = [(a[0], a[1]) for a in e.get_points("xy")]
        if e.closed:
            p.append(p[0])
        return list(zip(p, p[1:]))
    return []


def load_tour(path):
    """tour.json, or a version's tour that "extends" it: its seeds / stops replace the base's of the same name / room."""
    if not path.exists():
        return {}
    t = json.loads(path.read_text())
    if "extends" not in t:
        return t
    base = load_tour(path.with_name(t.pop("extends")))
    for k, key in (("seeds", "name"), ("stops", "room")):
        mine = {x[key]: x for x in t.pop(k, [])}
        base[k] = [mine.pop(x[key], x) for x in base.get(k, [])] + list(mine.values())
    return {**base, **t}


def plan_bounds(msp):
    xs, ys = [], []
    for e in msp.query(f'LINE[layer=="{WALL_LAYER}"]'):
        xs += [e.dxf.start.x, e.dxf.end.x]
        ys += [e.dxf.start.y, e.dxf.end.y]
    return box(min(xs) - 0.3, min(ys) - 0.3, max(xs) + 0.3, max(ys) + 0.3)


def pair_walls(segs):
    """Two parallel lines 4-50 cm apart with overlapping spans = one wall strip."""
    strips = []
    for i, (a0, a1) in enumerate(segs):
        ax, ay = a1[0] - a0[0], a1[1] - a0[1]
        la = math.hypot(ax, ay)
        if la < 0.03:
            continue
        ux, uy = ax / la, ay / la
        for b0, b1 in segs[i + 1:]:
            bx, by = b1[0] - b0[0], b1[1] - b0[1]
            lb = math.hypot(bx, by)
            if lb < 0.03 or abs(ux * by - uy * bx) / lb > 0.02:
                continue
            d = (b0[0] - a0[0]) * -uy + (b0[1] - a0[1]) * ux
            if not MIN_T <= abs(d) <= MAX_T:
                continue
            tb = sorted([(b0[0] - a0[0]) * ux + (b0[1] - a0[1]) * uy, (b1[0] - a0[0]) * ux + (b1[1] - a0[1]) * uy])
            t0, t1 = max(0, tb[0]), min(la, tb[1])
            if t1 - t0 >= 0.03:
                strips.append({"o": a0, "u": (ux, uy), "t0": t0, "t1": t1, "d": d})
    body = [strip_poly(s, s["t0"], s["t1"]) for s in strips]

    # Corner squares: wall i's end pushed by wall j's thickness overlaps wall j's end pushed by
    # wall i's thickness exactly at an L corner (or the gap between collinear pieces at a junction).
    out = list(body)
    for i, si in enumerate(strips):
        for j in range(i + 1, len(strips)):
            sj = strips[j]
            ui, uj = si["u"], sj["u"]
            if abs(ui[0] * uj[1] - ui[1] * uj[0]) < 0.05:  # parallel: only join pieces on the same axis
                ci, cj = strip_point(si, 0, si["d"] / 2), strip_point(sj, 0, sj["d"] / 2)
                if abs((cj[0] - ci[0]) * -ui[1] + (cj[1] - ci[1]) * ui[0]) > 0.02:
                    continue
                # The same span paired twice (a pier face matched to two back lines) is one wall, not
                # two pieces meeting end to end: squares off its ends would widen it.
                ends = lambda s: sorted([strip_point(s, s["t0"], s["d"] / 2), strip_point(s, s["t1"], s["d"] / 2)])
                if all(math.dist(p, q) < 0.02 for p, q in zip(ends(si), ends(sj))):
                    continue
                # A sliver (under 5 cm) inside a real wall's span (0.5 m or more), e.g. a door jamb tucked
                # 2 cm under a wall's end in master-v12, is part of that wall: squares off its ends would
                # push wall into the doorway. (Jamb pieces inside short frame strips keep their squares.)
                span = lambda s: sorted(strip_point(s, t, 0)[0] * ui[0] + strip_point(s, t, 0)[1] * ui[1] for t in (s["t0"], s["t1"]))
                inside = lambda a, b: b[0] - 0.002 <= a[0] and a[1] <= b[1] + 0.002 and a[1] - a[0] < 0.05 <= 0.5 <= b[1] - b[0]
                if inside(span(si), span(sj)) or inside(span(sj), span(si)):
                    continue
            if body[i].distance(body[j]) > 0.02:
                continue
            for ei in strip_ends(si, abs(sj["d"])):
                for ej in strip_ends(sj, abs(si["d"])):
                    sq = ei.intersection(ej)
                    if sq.area > 0.001 and sq.distance(body[i]) < 0.01 and sq.distance(body[j]) < 0.01:
                        out.append(sq)
    return out


def strip_point(s, t, off):
    (ox, oy), (ux, uy) = s["o"], s["u"]
    return ox + ux * t - uy * off, oy + uy * t + ux * off


def strip_poly(s, t0, t1):
    return Polygon([strip_point(s, t0, 0), strip_point(s, t1, 0), strip_point(s, t1, s["d"]), strip_point(s, t0, s["d"])])


def strip_ends(s, length):
    return [strip_poly(s, s["t0"] - length, s["t0"]), strip_poly(s, s["t1"], s["t1"] + length)]


def room_kind(name):
    n = name.lower()
    return "outdoor" if any(w in n for w in OUTDOOR) else "wet" if any(w in n for w in WET) else "dry"


def plan_lines(msp, B, door_blocks=True):
    """The drawing's linework (walls, windows, doors, furniture) flattened to polylines, for the ink-plan look."""
    out = []

    def add(e, cls):
        t = e.dxftype()
        if t == "INSERT":
            try:
                for v in e.virtual_entities():
                    add(v, "door" if cls == "wall" else cls)
            except Exception:
                pass
            return
        if t not in ("LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"):
            return
        try:
            pts = [(v.x, v.y) for v in ezpath.make_path(e).flattening(0.01)]
        except Exception:
            return
        if len(pts) >= 2 and B.contains(Point(pts[0])):
            out.append((cls, pts))

    for e in msp:
        cls = LINE_LAYERS.get(e.dxf.layer)
        if cls and (door_blocks or not (e.dxftype() == "INSERT" and e.dxf.layer == DOOR_LAYER)):
            add(e, cls)
    return out


def walk_route(walkable, a, b):
    """Shortest grid path from a to b inside `walkable` (A*), simplified to a few waypoints."""
    from shapely.prepared import prep
    ok = prep(walkable)
    x0, y0, x1, y1 = walkable.bounds
    cell = lambda p: (round((p[0] - x0) / GRID), round((p[1] - y0) / GRID))
    pos = lambda c: (x0 + c[0] * GRID, y0 + c[1] * GRID)
    free = {}
    def is_free(c):
        if c not in free:
            free[c] = ok.contains(Point(pos(c)))
        return free[c]
    start, goal = cell(a), cell(b)
    free[start] = free[goal] = True
    steps = [(dx, dy, math.hypot(dx, dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
    best, came, todo = {start: 0}, {}, [(0, start)]
    while todo:
        _, c = heapq.heappop(todo)
        if c == goal:
            break
        for dx, dy, w in steps:
            n = (c[0] + dx, c[1] + dy)
            if is_free(n) and best[c] + w < best.get(n, 1e9):
                best[n], came[n] = best[c] + w, c
                heapq.heappush(todo, (best[n] + math.dist(n, goal), n))
    if goal not in came and goal != start:
        print(f"  no walking route {a} -> {b}; using a straight line")
        return [a, b]
    path, c = [b], goal
    while c in came:
        c = came[c]
        path.append(pos(c))
    path[-1] = a
    return list(LineString(path[::-1]).simplify(0.08).coords)


def rectangularity(p):
    r = p.minimum_rotated_rectangle
    return p.area / r.area if r.area else 0


def rect_dims(p):
    c = list(p.minimum_rotated_rectangle.exterior.coords)
    s = sorted([math.dist(c[0], c[1]), math.dist(c[1], c[2])])
    return s[0], s[1]


def main():
    src = Path(sys.argv[1])
    arg = lambda k: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else None
    debug = arg("--debug")
    doc, _ = recover.readfile(src)
    msp = doc.modelspace()
    B = plan_bounds(msp)
    tour = load_tour(Path(__file__).parent / (arg("--tour") or "tour.json"))
    inb = lambda s: B.contains(LineString(s))

    wall_segs, window_segs, closed_wall = [], [], []
    for e in msp:
        lay = e.dxf.layer
        if lay == WALL_LAYER:
            if e.dxftype() == "LWPOLYLINE" and e.closed:
                pts = [(a[0], a[1]) for a in e.get_points("xy")]
                poly = Polygon(pts)
                if poly.is_valid and B.contains(poly) and poly.area > 0.005:
                    closed_wall.append(poly)
            # Dashed wall-layer lines mark something overhead (an arch, a bulkhead), not a wall.
            lt = e.dxf.get("linetype", "BYLAYER")
            if lt.upper() == "BYLAYER":
                lt = doc.layers.get(lay).dxf.linetype
            if not any(k in lt.upper() for k in ("DASH", "HIDDEN")):
                wall_segs += [s for s in entity_segments(e) if inb(s)]
        elif lay == WINDOW_LAYER:
            window_segs += [s for s in entity_segments(e) if inb(s)]
    for i, k in enumerate(sys.argv):
        if k == "--wall":
            x0, y0, x1, y1 = map(float, sys.argv[i + 1].split(","))
            wall_segs.append(((x0, y0), (x1, y1)))

    # Closed outlines that are thin or column-sized are solid; large closed ones are rooms/shafts.
    solids = [p for p in closed_wall if p.area < 1.5]
    shafts = [p for p in closed_wall if p.area >= 1.5 and rectangularity(p) > 0.9]
    walls = unary_union(pair_walls(wall_segs) + solids)
    walls = walls.buffer(0.01, join_style=2).buffer(-0.01, join_style=2)
    closed = walls.buffer(BRIDGE, join_style=2).buffer(-BRIDGE, join_style=2)

    # Windows: each cluster of window-layer lines marks an opening through the wall.
    openings = []
    clusters = as_polys(unary_union([LineString(s).buffer(0.03) for s in window_segs]))
    for c in clusters:
        # The opening runs the cluster's length and the wall's full thickness (glazing lines often
        # sit on one face only, which would leave the rest of the reveal open to the outside).
        rect = list(c.minimum_rotated_rectangle.exterior.coords)
        long_edge = max(((rect[0], rect[1]), (rect[1], rect[2])), key=lambda e: math.dist(*e))
        L = math.dist(*long_edge)
        if L < 0.2:
            continue
        ux, uy = (long_edge[1][0] - long_edge[0][0]) / L, (long_edge[1][1] - long_edge[0][1]) / L
        m = c.minimum_rotated_rectangle.centroid
        # Read the thickness from the solid wall just past each end of the window; where one end
        # meets a cross wall, the span both ends share is the wall the window sits in.
        spans = []
        # A window given its own heights (--window) reads the wall at its middle instead: an end probe that lands
        # in a build-out or a cross wall would run the opening out into the room.
        own = any(c.buffer(0.01).contains(Point(float(o[0]), float(o[1])))
                  for o in (sys.argv[i + 1].split(",") for i, k in enumerate(sys.argv) if k == "--window"))
        for t in ((0,) if own else (-L / 2 - 0.08, L / 2 + 0.08)):
            px, py = m.x + ux * t, m.y + uy * t
            cut = LineString([(px + uy * 0.6, py - ux * 0.6), (px - uy * 0.6, py + ux * 0.6)]).intersection(walls)
            pieces = [q for q in getattr(cut, "geoms", [cut]) if not q.is_empty and q.length > 0.03]
            if pieces:
                q = min(pieces, key=lambda q: q.distance(Point(px, py)))
                ns = [(x - m.x) * -uy + (y - m.y) * ux for x, y in q.coords]
                spans.append((min(ns), max(ns)))
        n0, n1 = (max(a for a, _ in spans), min(b for _, b in spans)) if spans else (0, 0)
        if n1 - n0 < 0.05 or n1 - n0 > MAX_T:  # fall back to the glazing lines' own depth
            w = min(math.dist(rect[0], rect[1]), math.dist(rect[1], rect[2]))
            n0, n1 = -max(w, 0.1) / 2, max(w, 0.1) / 2
        g = Polygon([(m.x + ux * t - uy * n, m.y + uy * t + ux * n)
                     for t, n in ((-L / 2, n0), (L / 2, n0), (L / 2, n1), (-L / 2, n1))])
        if g.area > 0.02:
            openings.append(("window", g))
    windows = unary_union([g for _, g in openings]) if openings else Polygon()
    # 4 mm margin: a window fitted a hair skew to its wall (2 mm over the guest WC's 0.98 m) would otherwise leave
    # 1 mm wedges along both wall faces, which extrude into full-height sheets hiding part of the glass and frame.
    walls = walls.difference(windows.buffer(0.004, join_style=2))

    # Doors: gaps the closing bridges. Walls must touch only the short ends (a notch filled along
    # a wall face touches a long side), and the gap must be door-sized or have a door swing nearby.
    gaps = closed.difference(walls).difference(windows.buffer(0.01, join_style=2))
    doors = []
    # 1) Door swings: hinge + closed-leaf end span the opening; wall faces either side give its depth.
    # Swings are drawn loose on the wall layer or inside door blocks (dynamic blocks hold one arc
    # per leaf size; the right size is the one whose closed leaf lands on the far jamb).
    door_swings = []  # (hinge, radius, closed-leaf end) per door, for drawing a clean swing
    swings = {}  # hinge -> ([arcs], drawn as a door block?)
    def collect(entities, door_block_at=None, depth=0):
        for e in entities:
            if e.dxftype() == "INSERT" and depth < 4:
                # Dynamic door blocks also carry the arcs of their other states; the live one is
                # hinged at the block's insertion point.
                at = Point(e.dxf.insert.x, e.dxf.insert.y) if e.dxf.layer == DOOR_LAYER else door_block_at
                try:
                    collect(e.virtual_entities(), at, depth + 1)
                except Exception:
                    pass
            elif e.dxftype() == "ARC" and 0.5 <= e.dxf.radius <= 1.3:
                w = e.ocs().to_wcs(e.dxf.center)  # mirrored blocks store arcs in a flipped OCS
                c = Point(w.x, w.y)
                if B.contains(c) and (door_block_at is None or c.distance(door_block_at) < 0.3):
                    swings.setdefault((round(c.x, 2), round(c.y, 2)), ([], door_block_at is not None))[0].append(e)
    collect(msp)
    # Double doors: two swings whose closed leaves meet in the middle (each leaf's end lands on the other's, not a jamb).
    all_ends = [(h, (a.start_point.x, a.start_point.y)) for h, (arcs_, _) in swings.items() for a in arcs_] + \
               [(h, (a.end_point.x, a.end_point.y)) for h, (arcs_, _) in swings.items() for a in arcs_]
    leaf_ends = {}
    for h, e in all_ends:
        leaf_ends.setdefault(h, []).extend(f for h2, f in all_ends if h2 != h and math.dist(e, f) < 0.03)
    # The open leaf is drawn (a hatched panel); the closed position is empty - that's the opening.
    # Only lines running a good part of the leaf count: the other states of a dynamic door block
    # next door leave a litter of short jamb pieces over this one's closed position.
    ink = [LineString(p) for c, p in plan_lines(msp, B) if c in ("wall", "door")]
    ink_tree = STRtree(ink)
    def leaf_ink(c, e):
        band = LineString([c, e]).buffer(0.04)
        runs = (ink[i].intersection(band).length for i in ink_tree.query(band))
        return sum(l for l in runs if l > 0.25 * math.dist(c, e))
    wall_band = walls.buffer(0.03, join_style=2)  # a closed leaf is drawn on the wall's face
    for c, (arcs, from_block) in swings.items():
        if not B.contains(Point(c)):
            continue
        best = None
        for arc in arcs:
            r = arc.dxf.radius
            if not 0.5 <= r <= 1.3:
                continue
            ends = [(arc.start_point.x, arc.start_point.y), (arc.end_point.x, arc.end_point.y)]
            # A closed leaf crosses the gap and ends on the far jamb; an open leaf ends out in the
            # room (the gap closing also fills small rooms, so crossing gap alone isn't enough).
            across = [e for e in ends if LineString([c, e]).intersection(gaps).length >= 0.4 * r
                      and (Point(e).distance(walls) < 0.2 or any(math.dist(e, f) < 0.03 for f in leaf_ends.get(c, ())))]
            if not across and leaf_ends.get(c):  # double doors wider than the bridging: their own gap, at their width
                zone = Point(c).buffer(2 * r + 0.5)
                wide = walls.intersection(zone).buffer(r + 0.1, join_style=2).buffer(-(r + 0.1), join_style=2)
                wide = wide.difference(walls).difference(windows.buffer(0.01, join_style=2))
                across = [e for e in ends if LineString([c, e]).intersection(wide).length >= 0.4 * r
                          and any(math.dist(e, f) < 0.03 for f in leaf_ends[c])]
            # A door drawn over a wall the drawing kept continuous: closed leaf lies inside the wall.
            buried = [e for e in ends if LineString([c, e]).intersection(wall_band).length >= 0.8 * r]
            if not across and not buried and not from_block:
                continue
            end = min(across or buried or ends, key=lambda e: leaf_ink(c, e))
            fit = Point(end).distance(walls)
            if best is None or fit < best[0] - 0.01:
                best = (fit, r, end, not across and bool(buried), next((e for e in ends if e != end), end))
        if best is None:
            continue
        fit, r, end, in_wall, drawn_open = best
        swing_of = (c, r, end, drawn_open)
        if in_wall:  # cut the opening the drawing left solid, then treat it like any other door
            ang = round(math.atan2(end[1] - c[1], end[0] - c[0]) / (math.pi / 4)) * (math.pi / 4)
            mid = Point(c[0] + math.cos(ang) * r / 2, c[1] + math.sin(ang) * r / 2)
            piece = next((q for q in as_polys(walls) if q.buffer(0.04).contains(mid)), None)
            if piece is None:
                continue
            ux, uy = math.cos(ang), math.sin(ang)
            cross = LineString([(mid.x + uy * 0.6, mid.y - ux * 0.6), (mid.x - uy * 0.6, mid.y + ux * 0.6)]).intersection(piece)
            g = min((q for q in getattr(cross, "geoms", [cross]) if not q.is_empty), key=lambda q: q.distance(mid), default=None)
            if g is None:
                continue
            ns = [(x - c[0]) * -uy + (y - c[1]) * ux for x, y in g.coords]
            hole = Polygon([(c[0] + ux * t - uy * n, c[1] + uy * t + ux * n)
                            for t, n in ((0, min(ns)), (r, min(ns)), (r, max(ns)), (0, max(ns)))])
            walls = walls.difference(hole.buffer(0.005, join_style=2))
            gaps = gaps.union(hole)
            fit = 0
        # Snap the leaf direction to the nearest 45 degrees (closed leaves are drawn slightly off-axis).
        ang = round(math.atan2(end[1] - c[1], end[0] - c[0]) / (math.pi / 4)) * (math.pi / 4)
        ux, uy = math.cos(ang), math.sin(ang)
        band = lambda t0, t1, n0, n1: Polygon([(c[0] + ux * t - uy * n, c[1] + uy * t + ux * n)
                                               for t, n in ((t0, n0), (t1, n0), (t1, n1), (t0, n1))])
        # Opening depth = wall thickness common to both jambs, read along a line across each jamb.
        spans = []
        for ts in ((-0.03, -0.08, -0.15), (r + 0.03, r + 0.08, r + 0.15)):
            for t in ts:  # first cut line that crosses the jamb wall
                pt = lambda n: (c[0] + ux * t - uy * n, c[1] + uy * t + ux * n)
                cut = LineString([pt(-0.6), pt(0.6)]).intersection(walls)
                pieces = [g for g in getattr(cut, "geoms", [cut]) if not g.is_empty and g.length > 0.03]
                if pieces:
                    g = min(pieces, key=lambda g: g.distance(Point(pt(0))))
                    ns = [(x - c[0]) * -uy + (y - c[1]) * ux for x, y in g.coords]
                    spans.append((min(ns), max(ns)))
                    break
        if spans:
            n0, n1 = max(a for a, _ in spans), min(b for _, b in spans)
            if n1 - n0 < 0.1:  # jamb is a wall end, not a face: use a nominal 12 cm lintel
                mid = (n0 + n1) / 2 if n1 > n0 else (min(a for a, _ in spans) + max(b for _, b in spans)) / 2
                n0, n1 = mid - 0.06, mid + 0.06
            if n1 - n0 > 0.03:
                # Run the lintel on to the walls when the hinge or leaf stops just short of them.
                back = Point(c).distance(walls)
                d = band(-(back + 0.01 if back < 0.25 else 0), r + (fit + 0.01 if fit < 0.25 else 0), n0, n1)
                # Several states of one door block (or a loose arc over a block) = one door.
                if not any(d.centroid.distance(o.centroid) < 0.4 for o in doors):
                    doors.append(d)
                    door_swings.append(swing_of)
    # A leaf can be a little narrower than its wall gap (frame); the door fills the whole gap.
    for i, d in enumerate(doors):
        for g in as_polys(gaps):
            if g.intersects(d):
                u = unary_union([d, g])
                w, l = rect_dims(u)
                if w <= MAX_T + 0.1 and l <= 2.0:
                    d = u.minimum_rotated_rectangle
        doors[i] = d
    # 2) Plain gaps (door drawn as a block): thin, door-wide, and walls touch only the short ends.
    wall_edge = walls.buffer(0.005, join_style=2)
    for g in as_polys(gaps):
        if g.area < 0.02 or any(g.intersects(d) for d in doors):
            continue
        w, l = rect_dims(g)
        if w <= MAX_T + 0.1 and 0.6 <= l <= 2.0 and rectangularity(g) > 0.8 and \
                g.exterior.intersection(wall_edge).length < 0.8 * l:
            doors.append(g.minimum_rotated_rectangle)
    for d in doors:
        if not any(k == "door" and g.symmetric_difference(d).area < 0.01 for k, g in openings):
            openings.append(("door", d))
    # A wall-thin gap narrower than any door is wall the drawing left out (e.g. behind an open leaf).
    taken = unary_union([g for _, g in openings]).buffer(0.01, join_style=2)
    fills = []
    for g in as_polys(gaps.difference(taken)):
        if g.area < 0.005:
            continue
        w, l = rect_dims(g)
        if w <= MAX_T + 0.05 and l < 0.6 and rectangularity(g) > 0.7:
            fills.append(g)
    if fills:
        walls = unary_union([walls] + fills).buffer(0.002, join_style=2).buffer(-0.002, join_style=2)
    # A part-height recess (niche, dashed in the drawing) is carved full height; furnish.js fills above and below it.
    # Run the rectangle a little past the wall face: an edge exactly on it leaves a sliver that closes the recess.
    for i, k in enumerate(sys.argv):
        if k == "--cut":
            x0, y0, x1, y1 = map(float, sys.argv[i + 1].split(","))
            walls = walls.difference(box(x0, y0, x1, y1))
    niches = []  # the tour's recesses: carved full height here, solid below `bottom` and above `top` in the viewer
    for nc in tour.get("niches", []):
        try:
            poly = Polygon([tuple(q) for q in nc["box"]])
        except Exception:
            continue
        if poly.is_valid and poly.area > 0.001 and poly.intersects(walls):
            walls = walls.difference(poly.buffer(0.002, join_style=2))
            niches.append((poly, float(nc.get("bottom", 0)), float(nc.get("top", CEILING))))

    # Floor: the flat's outline (walls + openings, small gaps bridged), with holes filled.
    solid = make_valid(unary_union([walls] + [g for _, g in openings])).buffer(0.005, join_style=2)
    shell = solid.buffer(1.0, join_style=2).buffer(-1.0, join_style=2)
    outline = max(as_polys(shell), key=lambda q: q.area).exterior
    floor = Polygon(outline).difference(walls)

    furniture = []
    for e in msp:
        if e.dxf.layer in FURNI_LAYERS and e.dxftype() == "LWPOLYLINE" and e.closed:
            pts = [(a[0], a[1]) for a in e.get_points("xy")]
            if len(pts) >= 3:
                p = Polygon(pts)
                if p.is_valid and B.contains(p) and 0.05 < p.area < 6:
                    furniture.append(p)


    labels = []
    for t in msp.query("TEXT MTEXT"):
        pt = t.dxf.insert
        if B.contains(Point(pt.x, pt.y)):
            labels.append({"text": t.plain_text().strip().rstrip("."), "x": pt.x, "y": pt.y})
    # Two-line names ("MASTER" over "BEDROOM.") become one label; repeated names get numbered.
    labels.sort(key=lambda l: -l["y"])
    merged = []
    for l in labels:
        top = next((m for m in merged if abs(m["x"] - l["x"]) < 1.0 and 0 < m["y"] - l["y"] < 0.6), None)
        if top:
            top["text"] += " " + l["text"]
        else:
            merged.append(dict(l))
    for name in {m["text"] for m in merged}:
        same = [m for m in merged if m["text"] == name]
        if len(same) > 1:
            for k, m in enumerate(sorted(same, key=lambda m: m["x"]), 1):
                m["text"] += f" {k}"
    labels = merged

    # Rooms: regions fully enclosed by walls + openings; what's left of the floor is open space.
    enclosed = [Polygon(h) for g in as_polys(solid) for h in g.interiors if Polygon(h).area > 0.3]
    # Open (not enclosed) floor: drop thin strips the outline closing added outside the walls.
    leftover = floor.difference(unary_union(enclosed)).buffer(-0.12, join_style=2).buffer(0.12, join_style=2)
    # Doors always divide rooms, even where the floor leaks round a door's end.
    cut = unary_union([g for k, g in openings if k == "door"]).buffer(0.06, join_style=2)
    regions = [(q, closed_in) for gs, closed_in in ((enclosed, True), ([g for g in as_polys(leftover) if g.area > 0.3], False))
               for g in gs for q in as_polys(g.difference(cut)) if q.area > 0.3]
    # A region holding several room names (open-plan) is split between them by nearest name.
    moved = {sd["name"] for sd in tour.get("seeds", []) if sd.get("replace")}
    seeds = [(l["text"], (l["x"] + 0.3, l["y"] + 0.1)) for l in labels if l["text"] not in moved] + \
            [(sd["name"], tuple(sd["at"])) for sd in tour.get("seeds", [])]
    # Home-wide heights from the version's tour (Edit AI): the rest keep the defaults.
    hts = tour.get("heights") or {}
    ceiling, door_head, sill_h, win_head, slider_head, parapet_h = (
        float(hts.get(k, d)) for k, d in (("ceiling", CEILING), ("door", DOOR_HEAD), ("sill", SILL), ("window", WIN_HEAD),
                                           ("slider", SLIDER_HEAD), ("parapet", PARAPET)))
    specs_r = {k.upper().rstrip("."): v for k, v in (tour.get("rooms") or {}).items() if isinstance(v, dict)}
    kind_of = lambda n: specs_r.get(n.upper().rstrip("."), {}).get("kind") if specs_r.get(n.upper().rstrip("."), {}).get("kind") \
        in ("wet", "dry", "outdoor") else room_kind(n)
    rooms = []  # (name, kind, polygon)
    for g, closed_in in regions:
        inside = [(n, pt) for n, pt in seeds if g.contains(Point(pt))]
        if not inside:
            if not closed_in and g.distance(outline) < 0.05:
                continue  # unnamed floor on the flat's outer edge is outside the flat
            # Unnamed enclosed nook (e.g. a shower zone): belongs to the nearest named room.
            inside = [min(seeds, key=lambda sd: g.distance(Point(sd[1])))]
        if len({n for n, _ in inside}) == 1:
            parts = [(inside[0][0], g)]
        else:
            cells = voronoi_diagram(MultiPoint([pt for _, pt in inside]), envelope=g.envelope.buffer(5)).geoms
            parts = [(n, next(c for c in cells if c.contains(Point(pt))).intersection(g)) for n, pt in inside]
        for n, part in parts:
            rooms.append((n, kind_of(n), part.intersection(floor)))
    # One entry per room name.
    merged_rooms = {}
    for n, k, g in rooms:
        merged_rooms[n] = (k, unary_union([merged_rooms[n][1], g]) if n in merged_rooms else g)
    rooms = [(n, k, g) for n, (k, g) in merged_rooms.items()]
    floor = unary_union([g for _, _, g in rooms])
    outdoor = unary_union([g for _, k, g in rooms if k == "outdoor"]) if rooms else Polygon()
    indoor = unary_union([g for _, k, g in rooms if k != "outdoor"]) if rooms else Polygon()
    # Walls bounding only the outdoor space are parapets, not full-height walls.
    parapet = walls.intersection(outdoor.buffer(0.6, join_style=2)).difference(indoor.buffer(0.6, join_style=2))
    full = walls.difference(parapet)
    special = []  # the tour's low / glass stretches of wall, taken out of the full-height and parapet walls
    for ws_ in tour.get("walls", []):
        try:
            seg = LineString([tuple(ws_["a"]), tuple(ws_["b"])])
            region = seg.buffer(float(ws_.get("thickness", 0.12)) / 2 + 0.01, cap_style=2, join_style=2)
        except Exception:
            continue
        part = walls.intersection(region)
        if part.is_empty:
            continue
        full, parapet = full.difference(region), parapet.difference(region)
        special.append((part, float(ws_.get("height", CEILING)), bool(ws_.get("glass"))))

    # Windows between an indoor room and the terrace are full-height sliding doors (per renders).
    named = {n: g for n, _, g in rooms}
    for i, (k, g) in enumerate(openings):
        if k == "window" and g.buffer(0.3).intersects(outdoor) and g.buffer(0.3).intersects(indoor):
            openings[i] = ("slider", g)
    # The tour's opening specs: a kind of its own (before the route, which walks only through doors and sliders) and
    # its own heights / glass / panel for the model.
    specs = [o for o in tour.get("openings", []) if isinstance(o, dict) and len(o.get("at") or []) == 2]
    spec_of = lambda g: next((o for o in specs if g.buffer(0.05).contains(Point(*o["at"]))), {})
    for i, (k, g) in enumerate(openings):
        if spec_of(g).get("kind") in ("window", "slider", "door"):
            openings[i] = (spec_of(g)["kind"], g)

    # Tour route: outside the front door, then stop to stop, walking through doors and sliders.
    legs, start, nav = [], None, None
    if tour.get("stops"):
        passable = unary_union([g for k, g in openings if k in ("door", "slider")])
        entry = min((g for k, g in openings if k == "door"), key=lambda g: g.distance(Point(tour["entry"])))
        c = entry.centroid
        rect = list(entry.minimum_rotated_rectangle.exterior.coords)
        e1, e2 = (rect[0], rect[1]), (rect[1], rect[2])
        short = min((e1, e2), key=lambda e: math.dist(*e))
        nx, ny = short[1][0] - short[0][0], short[1][1] - short[0][1]
        L = math.hypot(nx, ny)
        nx, ny = nx / L, ny / L
        if floor.contains(Point(c.x + nx * 0.5, c.y + ny * 0.5)):
            nx, ny = -nx, -ny
        start = tuple(tour["start"]) if len(tour.get("start") or []) == 2 else (c.x + nx * 1.6, c.y + ny * 1.6)
        apron = LineString([(c.x, c.y), start]).buffer(0.5)
        walkable = unary_union([floor, passable.buffer(0.15), apron]).difference(walls.buffer(CLEARANCE, join_style=2))
        walkable = unary_union([walkable, apron.difference(walls.buffer(0.05))])
        pts = [start] + [tuple(st["eye"]) for st in tour["stops"]]
        legs = [walk_route(walkable, a, b) for a, b in zip(pts, pts[1:])]
        # Walkable grid for the viewer's own route-finding (walk to a room through the doors).
        from shapely.prepared import prep
        ok = prep(walkable)
        gx0, gy0, gx1, gy1 = walkable.bounds
        cols, rows_n = int((gx1 - gx0) / GRID) + 1, int((gy1 - gy0) / GRID) + 1
        nav = {"x0": round(gx0, 3), "y0": round(gy0, 3), "cell": GRID, "cols": cols,
               "rows": ["".join("1" if ok.contains(Point(gx0 + i * GRID, gy0 + j * GRID)) else "0" for i in range(cols))
                        for j in range(rows_n)]}

    # Linework for the ink plan: only what lies on the flat (not the void or stray blocks), and
    # without the drawing's own door swings (dynamic door blocks draw every size at once).
    on_flat = unary_union([floor, walls, unary_union([g for _, g in openings])]).buffer(0.05)
    hinges = [Point(c) for c, *_ in door_swings]
    def is_swing(pts):
        return len(pts) > 4 and any(math.dist(pts[0], (h.x, h.y)) > 0.4 and
                                    abs(math.dist(pts[0], (h.x, h.y)) - math.dist(pts[-1], (h.x, h.y))) < 0.03 and
                                    abs(math.dist(pts[len(pts) // 2], (h.x, h.y)) - math.dist(pts[0], (h.x, h.y))) < 0.03
                                    for h in hinges)
    drawn = [(c, pts) for c, pts in plan_lines(msp, B, door_blocks=False)
             if on_flat.contains(LineString(pts).interpolate(0.5, normalized=True))
             and not (c in ("wall", "door") and is_swing(pts))]

    # Room skins: a 1 cm lining inside each room's walls (stone in bathrooms, skirting elsewhere),
    # kept out of doorways and window reveals (and off open-plan room boundaries, which have no wall).
    gaps_all = unary_union([g for _, g in openings]).buffer(0.12, join_style=2)
    wall_face = walls.buffer(0.03, join_style=2)
    skins = [(n, k, p) for n, k, g in rooms if k != "outdoor"
             for p in as_polys(g.difference(g.buffer(-SKIN, join_style=2)).intersection(wall_face).difference(gaps_all))
             if p.area > 0.0005]

    # Doors the viewer stands open the way the drawing swings them (others: the first side that lands in a room).
    as_drawn = lambda c: any(math.dist(c, h) < 0.1 for h in tour.get("doorsAsDrawn", []))
    # --window x,y,sill,head[,frosted]: the window whose opening holds DWG point x,y gets its own sill and head
    # (and frosted glass), the rest keep SILL / WIN_HEAD. Nothing is written for windows without one.
    overrides = [sys.argv[i + 1].split(",") for i, k in enumerate(sys.argv) if k == "--window"]
    def window_override(k, g):
        own = {}
        for o in overrides:
            if k == "window" and g.buffer(0.01).contains(Point(float(o[0]), float(o[1]))):
                own = {"sill": float(o[2]), "head": float(o[3]), **({"frosted": True} if "frosted" in o[4:] else {})}
                break
        sp = spec_of(g)  # the tour's spec wins over --window
        for key in (("sill", "head") if k == "window" else ("head",)):
            if sp.get(key) is not None:
                own[key] = float(sp[key])
        if k == "window" and sp.get("frosted") is not None:
            own.pop("frosted", None)
            own.update({"frosted": True} if sp["frosted"] else {})
        if k == "slider" and sp.get("panel") in ("glass", "wood"):
            own["panel"] = sp["panel"]
        for key in LOOK:  # how it looks: the viewer's business
            if sp.get(key) is not None:
                own[key] = sp[key]
        return own
    # A swing whose opening is no longer a door (made a window or a slider) isn't drawn; one whose door has its own
    # head gets it for the leaf.
    door_at = lambda c: next(((k, g) for k, g in openings if g.buffer(0.15).contains(Point(c))), (None, None))
    door_swings = [sw for sw in door_swings if door_at(sw[0])[0] in ("door", None)]
    ox, oy = B.bounds[0], B.bounds[1]
    ring = lambda p: [[round(x - ox, 4), round(y - oy, 4)] for x, y in p.exterior.coords[:-1]]
    holes = lambda p: [[[round(x - ox, 4), round(y - oy, 4)] for x, y in h.coords[:-1]] for h in p.interiors]
    model = {
        "ceiling": ceiling, "doorHead": door_head, "sill": sill_h, "winHead": win_head, "sliderHead": slider_head,
        "bounds": [B.bounds[2] - ox, B.bounds[3] - oy],
        "walls": [{"outer": ring(p), "holes": holes(p), "height": ceiling} for p in as_polys(full) if p.area > 0.002]
                 + [{"outer": ring(p), "holes": holes(p), "height": parapet_h, **({"glass": True} if (tour.get("parapet") or {}).get("glass") else {})}
                    for p in as_polys(parapet) if p.area > 0.002]
                 + [{"outer": ring(p), "holes": holes(p), "height": min(h_, ceiling), **({"glass": True} if gl_ else {})}
                    for part_, h_, gl_ in special for p in as_polys(part_) if p.area > 0.002],
        "niches": [{"outer": ring(p), "bottom": b_, "top": t_} for p, b_, t_ in niches],
        "rooms": {n: v for n, v in (tour.get("rooms") or {}).items() if isinstance(v, dict)},
        "notes": [{"at": [round(n_["at"][0] - ox, 3), round(n_["at"][1] - oy, 3)], "text": str(n_.get("text", ""))[:200]}
                  for n_ in tour.get("notes", []) if len(n_.get("at") or []) == 2],
        "floor": [{"outer": ring(p), "holes": holes(p), "kind": k, "room": n} for n, k, g in rooms for p in as_polys(g)],
        "skins": [{"outer": ring(p), "holes": holes(p), "kind": k, "room": n} for n, k, p in skins],
        "lines": [{"kind": c, "pts": [[round(x - ox, 3), round(y - oy, 3)] for x, y in pts]} for c, pts in drawn],
        "swings": [{"hinge": [round(c[0] - ox, 3), round(c[1] - oy, 3)], "r": round(r, 3),
                    "closed": [round(e[0] - ox, 3), round(e[1] - oy, 3)],
                    **({"open": [round(o[0] - ox, 3), round(o[1] - oy, 3)]} if as_drawn(c) else {}),
                    **({k_: v_ for k_, v_ in window_override("door", door_at(c)[1]).items() if k_ in ("head",) + LOOK}
                       if door_at(c)[1] is not None else {})}
                   for c, r, e, o in door_swings],
        "origin": [ox, oy],
        "tour": {
            "title": tour.get("title", ""), "subtitle": tour.get("subtitle", ""),
            "finishes": tour.get("finishes", {}),
            "start": [round(start[0] - ox, 3), round(start[1] - oy, 3)] if start else None,
            "stops": [{**st, "eye": [round(st["eye"][0] - ox, 3), round(st["eye"][1] - oy, 3)],
                       "look": [round(st["look"][0] - ox, 3), round(st["look"][1] - oy, 3)]} for st in tour.get("stops", [])],
            "legs": [[[round(x - ox, 3), round(y - oy, 3)] for x, y in leg] for leg in legs],
        },
        "nav": nav and {**nav, "x0": round(nav["x0"] - ox, 3), "y0": round(nav["y0"] - oy, 3)},
        "openings": [{"kind": k, "outer": ring(g), **window_override(k, g)} for k, g in openings],
        "shafts": [ring(p) for p in shafts],
        "furniture": [ring(p) for p in furniture],
        "labels": [{"text": l["text"], "x": round(l["x"] - ox, 3), "y": round(l["y"] - oy, 3)} for l in labels],
    }
    out = Path(__file__).parent / (arg("--out") or "model.js")
    out.write_text("window.MODEL = " + json.dumps(model) + ";\n")
    for k, g in openings:
        if k == "door":
            w, l = rect_dims(g)
            print(f"  door at ({g.centroid.x:.2f}, {g.centroid.y:.2f}), {l:.2f} m wide")
    print(f"{out}: {len(model['walls'])} wall pieces, {sum(k == 'door' for k, _ in openings)} doors, "
          f"{sum(k == 'window' for k, _ in openings)} windows, {len(furniture)} furniture, {len(shafts)} shafts")

    if debug:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(30, 12))
        for s in wall_segs:
            ax.plot(*zip(*s), color="k", lw=0.4)
        for s in window_segs:
            ax.plot(*zip(*s), color="b", lw=0.4)
        for p in as_polys(walls):
            ax.fill(*p.exterior.xy, color="grey", alpha=0.7)
            for h in p.interiors:
                ax.fill(*h.xy, color="white")
        for k, g in openings:
            ax.fill(*g.exterior.xy, color={"window": "deepskyblue", "slider": "navy"}.get(k, "orange"), alpha=0.9)
        for leg in legs:
            ax.plot(*zip(*leg), color="red", lw=1.5)
        for st in tour.get("stops", []):
            ax.annotate("", xy=st["look"], xytext=st["eye"], arrowprops=dict(arrowstyle="->", color="crimson"))
        for n, k, g in rooms:
            for p in as_polys(g):
                ax.fill(*p.exterior.xy, alpha=0.35)
                ax.text(p.centroid.x, p.centroid.y, n, fontsize=9, ha="center")
        for p in shafts:
            ax.fill(*p.exterior.xy, color="purple", alpha=0.3)
        for p in furniture:
            ax.plot(*p.exterior.xy, color="green", lw=0.4)
        ax.set_aspect("equal")
        fig.savefig(debug, dpi=80, bbox_inches="tight")


if __name__ == "__main__":
    main()
