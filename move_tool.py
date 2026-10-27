"""Move and Resize: the viewer's Move and Resize button drags a piece in 3D or on the 2D plan, or pulls an edge to
resize it, and saves only when the user presses Accept (move.js keeps the change as a draft until then).

POST /api/edit-ai/transform does it without any model call. It makes the same two edits Edit AI's tools make, so the
3D and the 2D change together: furnish.js (the piece's item( x, y; a size as sized(item(...), across, out); a part
inside a piece, e.g. the espresso machine on the coffee bar, as its own position / scale; a part drawn from numbers in
its piece's code, e.g. a TV-wall niche, by changing those numbers) and, when the piece is drawn on the plan, the
version's DXF through edit_ai_dxf.py's move_piece / resize_piece. The plan's answer (it may clamp a resize to the free
span) is what the 3D gets, so both views move by the same metres. Then edit_ai.save() rebuilds the model and drawing,
stores the live override and git-syncs, exactly like an Edit AI change (and Edit AI's Undo takes it back).

Where each piece started: move-origins-<version>.json lists, for every piece Move and Resize has changed, its plan box
and turn (rotation.y) before its FIRST change, found by its label and where its plan box is now; move.js measures
"moved" and "turned" from there, not from the last Accept. It is stored, undone and git-synced with the change.

One version's change stays in that version: since 26 Oct 2026 every version has its own furnish-<version>.js, which
no other version runs, so numbers are written plainly (no `version === "<v>" ? new : old` gates, and no
other_versions_changed() check: on a file only one version runs it can only refuse by mistake). Code in another
version's branch of the file (`if (version === "kareems-changes") ...`, left from the shared file) is still refused.

Request: {version, rev, op: "move" | "resize", piece: {...}, dx, dy, rotate (move; rotate: degrees, + = anticlockwise
on the plan, about the centre of its plan box) | box (resize: the new plan box)}
piece (from move.js, read off the 3D scene): kind "item" | "part"; x, y, facing of its item( call; anchor: where the
item stands now; lines: furnish.js line numbers on the call stack when item() ran; twins: pieces placed with the same
x, y, facing; scale [across, out] (sized()); box [x0, y0, x1, y1] its plan box now; low / high (m) its lowest /
highest point; label; for a part: part (its p.label text), pos [x, z] and pscale [x, z] in its parent's frame, frame
(where that parent sits in the item's frame, for a part inside a part), param (a part drawn from numbers), hostBox.

What stays 3D-only (docs/edit-ai/when-2d-needed.md): pieces whose lowest point is above head height, lights, AC units,
wall-hung things and anything with no 2furni outline under it. A floor piece drawn on the plan only inside one outline
round several pieces (the dining set) moves in 3D only, and only while it stays inside that outline. A piece drawn as
one furniture block (the WC symbol) moves with its whole INSERT; a resize changes only the 3D (the symbol keeps its size).
"""
import json, math, re

import edit_ai as E

NAME = "Move and Resize"
HEAD_HEIGHT = 1.5
U = {"S": (1, 0), "N": (-1, 0), "E": (0, 1), "W": (0, -1)}   # local x (across) in plan
F = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}   # local z (out from the wall) in plan
CALL = re.compile(r"\b(sized\(\s*)?\b(item|rug|plant|art|ac|sconce|pendant)\(")
NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
SIDES = ("N", "S", "E", "W")
FACE = {"S": 0.0, "E": math.pi / 2, "N": math.pi, "W": -math.pi / 2}  # furnish.js's FACING: the item's rotation.y
CANT = f"so it can't be changed with {NAME}. Make an Edit can do it."


def r4(v):
    v = round(float(v), 4)
    return 0.0 if v == 0 else v


def fmt(v):
    s = f"{r4(v):.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def cm(v):
    return f"{abs(v) * 100:.0f} cm"


# --- Reading furnish.js -------------------------------------------------------------------------------------------
def close_paren(text, i):
    """Index of the ')' matching the '(' at text[i], skipping strings, template literals and comments."""
    depth, k, n = 0, i, len(text)
    while k < n:
        c = text[k]
        if c in "\"'`":
            q, k = c, k + 1
            while k < n and text[k] != q:
                k += 2 if text[k] == "\\" else 1
        elif text.startswith("//", k):
            k = text.find("\n", k)
            if k < 0:
                return -1
            continue
        elif text.startswith("/*", k):
            k = text.find("*/", k) + 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return -1


def split_args(s):
    """Top-level comma-separated pieces of an argument list (no parens round it)."""
    out, depth, cur, q = [], 0, "", None
    for c in s:
        if q:
            cur += c
            if c == q:
                q = None
            continue
        if c in "\"'`":
            q = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += c
    out.append(cur)
    return out


def line_start(text, n):
    """Offset of the start of 1-based line n."""
    off = 0
    for _ in range(n - 1):
        off = text.index("\n", off) + 1
    return off


def calls_on_line(text, n):
    """[{kind, name, open, close, args, sized, outer}] for each placing call that starts on line n."""
    s = line_start(text, n)
    e = text.find("\n", s)
    e = len(text) if e < 0 else e
    out = []
    for m in CALL.finditer(text, s, e):
        op = m.end() - 1
        cl = close_paren(text, op)
        if cl < 0:
            continue
        out.append({"kind": m[2], "name": m.start(2), "open": op, "close": cl, "args": split_args(text[op + 1:cl]),
                    "sized": bool(m[1]), "outer": m.start()})
    return out


def near(a, b, tol=0.0015):
    return abs(a - b) <= tol


def helper_def(line):
    return bool(re.search(r"=\s*\([^)]*\)\s*=>|\bfunction\b", line))


def gated(a, v):
    """(new value text, rest) when the arg is this version's gate `version === "v" ? n : rest`, else None."""
    m = re.match(r'^\s*version\s*===\s*"([\w-]+)"\s*\?\s*(-?\d+(?:\.\d+)?)\s*:\s*(.+?)\s*$', a, re.S)
    return (m[2], m[3]) if m and m[1] == v else None


def arg_num(a, v):
    """The arg's value for version v when it's a plain number or this version's gate; else None."""
    a = a.strip()
    if NUM.match(a):
        return float(a)
    g = gated(a, v)
    return float(g[0]) if g else None


def num_for(a, v):
    """The number an arg gives version v through any gates (another version's gate: its rest); else None."""
    a = a.strip()
    m = re.match(r'^version\s*===\s*"([\w-]+)"\s*\?\s*(-?\d+(?:\.\d+)?)\s*:(.+)$', a, re.S)
    if m:
        return float(m[2]) if m[1] == v else num_for(m[3], v)
    return float(a) if NUM.match(a) else None


def set_arg(a, new, v, shared):
    """The arg rewritten to `new` for version v only: a gate on a line other versions run, a plain number otherwise."""
    lead = re.match(r"\s*", a).group(0)
    g = gated(a, v)
    if g:
        return lead + f'version === "{v}" ? {fmt(new)} : {g[1]}'
    if not shared:
        return lead + fmt(new)
    return lead + f'version === "{v}" ? {fmt(new)} : {a.strip()}'


def facing_of(a, v):
    """The facing an arg gives version v: "S" / an angle (rotation.y), plain or this version's gate; else None."""
    a = a.strip()
    m = re.match(r'^version\s*===\s*"([\w-]+)"\s*\?\s*("[NSEW]"|-?\d+(?:\.\d+)?)\s*:(.+)$', a, re.S)
    if m:
        if m[1] != v:
            return facing_of(m[3], v)  # another version's gate: what the rest gives this one
        a = m[2]
    if re.fullmatch(r'"[NSEW]"', a):
        return a.strip('"')
    return float(a) if NUM.match(a) else None


def same_facing(a, b):
    if a is None or b is None:
        return False
    return near(FACE.get(a, a) if isinstance(a, str) else a, FACE.get(b, b) if isinstance(b, str) else float(b), 1e-4)


def facing_at(call):
    """Index of the facing arg of a placing call, or None (a plant or pendant is round: nothing to turn)."""
    if call["kind"] not in ("item", "art", "ac", "sconce"):
        return None
    return 1 if call["args"][0].strip().startswith("...(") else 2


def turned(facing, deg):
    """The facing after turning it deg degrees anticlockwise on the plan: N/E/S/W when square, else rotation.y."""
    a = (FACE[facing] if isinstance(facing, str) else float(facing)) + math.radians(deg)
    a = math.atan2(math.sin(a), math.cos(a))
    k = round(a / (math.pi / 2))
    if abs(a - k * math.pi / 2) < 1e-4:
        return "SENW"[k % 4]
    return round(a, 4)


def set_facing(text, call, f, v, shared):
    i = facing_at(call)
    a = call["args"]
    lead = re.match(r"\s*", a[i]).group(0)
    new = f'"{f}"' if isinstance(f, str) else fmt(f)
    m = re.match(r'^\s*version\s*===\s*"' + re.escape(v) + r'"\s*\?\s*(?:"[NSEW]"|-?\d+(?:\.\d+)?)\s*:\s*(.+?)\s*$', a[i], re.S)
    rest = m[1] if m else a[i].strip()
    if (m or shared) and rest != new:
        new = f'version === "{v}" ? {new} : {rest}'
    args = a[:i] + [lead + new] + a[i + 1:]
    return text[:call["open"] + 1] + ",".join(args) + text[call["close"]:]


def find_call(text, piece, v):
    """The furnish.js call that placed the piece: {line, call, how} (how: literal / rug / expr / spread / table)."""
    x, y = float(piece["x"]), float(piece["y"])
    lines = [int(n) for n in piece.get("lines") or [] if 0 < int(n) <= text.count("\n") + 1]
    L = text.splitlines()
    # a plant grows its leaves from a seed made of its x, y: new numbers there would grow a different plant, so it
    # keeps them and goes in the MOVED table (item() puts it where it goes)
    plant = any(c["kind"] == "plant" for n in lines for c in calls_on_line(text, n))
    if not piece.get("moved") and not plant:
        for n in lines:  # 1. a literal call: item(2.02, 9.015, ... / rug(x0, y0, x1, y1) centred on x, y
            for c in calls_on_line(text, n):
                a = [arg_num(t, v) for t in c["args"][:4]]
                if c["kind"] == "rug" and len(a) >= 4 and None not in a:
                    if near((a[0] + a[2]) / 2, x) and near((a[1] + a[3]) / 2, y):
                        return {"line": n, "call": c, "how": "rug"}
                elif len(a) >= 2 and None not in a[:2] and near(a[0], x) and near(a[1], y):
                    return {"line": n, "call": c, "how": "literal"}
        for n in lines:  # 2. one call, not in a loop, with worked-out coordinates (item(KC ? SC : 18.86, ...)
            if helper_def(L[n - 1]) or in_loop(L, n):
                continue
            cs = [c for c in calls_on_line(text, n) if c["kind"] != "rug"]
            if len(cs) != 1:
                continue
            a = cs[0]["args"]
            if a[0].strip().startswith("...(") and len(a) >= 2:
                return {"line": n, "call": cs[0], "how": "spread"}
            if len(a) >= 3 and cs[0]["kind"] not in ("plant", "pendant") and same_facing(facing_of(a[2], v), piece.get("facing")):
                return {"line": n, "call": cs[0], "how": "expr"}
    # 3. built in a loop or by shared code: no line of its own, so this version's MOVED table entry
    if int(piece.get("twins") or 1) > 1 and not int(piece.get("twin") or 0):  # no "#n" key in this furnish file
        raise ValueError("Another piece is placed at the same spot by the same code, so this one can't be told apart, " + CANT)
    if "const MOVED = {};" not in text:
        raise ValueError("I can't find the line of code that places this piece (it's built by shared code), " + CANT)
    return {"line": None, "call": None, "how": "table"}


def in_loop(L, n):
    """Is line n a loop body (a for on it, or a for header a few lines up whose variable it uses)?"""
    if re.search(r"\bfor\s*\(", L[n - 1]):
        return True
    for h in range(n - 2, max(-1, n - 6), -1):
        m = re.search(r"\bfor\s*\(\s*(?:const|let)\s+(\[[^\]]*\]|\w+)", L[h])
        if m and any(re.search(r"\b" + w + r"\b", L[n - 1]) for w in re.findall(r"\w+", m[1])):
            return True
    return False


def scopes(text, v):
    """shared(n): does furnish.js line n also run for some other version?"""
    mine = E.version_scope(text, v)
    others = [E.version_scope(text, o) for o in sorted(E.furnish_versions(text) - {v})]
    return lambda n: mine[n - 1] is not True or any(s[n - 1] is not False for s in others)


# --- The plan outline under a piece ---------------------------------------------------------------------------------
def ent_box(d):
    """A queried entity's plan box: its points, its extent (a curve, a block) or its circle; None when it has none."""
    if d.get("bbox"):
        return tuple(d["bbox"])
    if d.get("points"):
        xs, ys = [p[0] for p in d["points"]], [p[1] for p in d["points"]]
        return min(xs), min(ys), max(xs), max(ys)
    if d.get("centre") and d.get("radius"):
        (cx, cy), r = d["centre"], d["radius"]
        return cx - r, cy - r, cx + r, cy + r
    return None


def outlines_near(ws, box, pad=0.3):
    """(outlines, lines): the piece-sized 2furni outlines and blocks round box, and every 2furni entity there with its box."""
    code, q = E.run([E.dwg_python(), str(E.ROOT / "edit_ai_dxf.py"), "query", str(ws.dxf()), f"--origin={E.ORIGIN[0]},{E.ORIGIN[1]}",
                     f"--bbox={box[0] - pad},{box[1] - pad},{box[2] + pad},{box[3] + pad}", "--layers=2furni,2 furni", "--limit", "400",
                     "--blocks"], timeout=90)
    try:  # the JSON comes first; any stderr (a warning on Vercel) follows it: "Extra data" with json.loads
        found = json.JSONDecoder().raw_decode(q.lstrip())[0]
    except ValueError:
        raise ValueError(f"the plan lookup gave an answer I can't read: {q[:300]}")
    out, lines = [], []
    for d in found.get("entities", []):
        if (b := ent_box(d)):
            lines.append({"handle": d["handle"], "box": b, "block": d["type"] == "INSERT"})
        if d["type"] == "INSERT":  # a piece drawn as one block: the whole block
            if d.get("bbox"):
                out.append({"handle": d["handle"], "box": tuple(d["bbox"]), "block": True})
            continue
        ps = d.get("points") or ([d["bbox"][:2], d["bbox"][2:]] if d.get("bbox") else [])
        if d["type"] == "LWPOLYLINE" and (len(ps) >= 4 or d.get("n_points", 0) >= 4):
            xs, ys = [p[0] for p in ps], [p[1] for p in ps]
            b = (min(xs), min(ys), max(xs), max(ys))
            if (b[2] - b[0]) * (b[3] - b[1]) >= 0.02:
                out.append({"handle": d["handle"], "box": b, "pts": d.get("points")})  # pts: None for a curve (box only)
    return out, lines


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def inside(p, pts):
    """Is plan point p inside the polygon pts (closed or not: its last point joins its first)?"""
    hit = False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < (x1 - x0) * (p[1] - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def within(b, outer, tol=0.02):
    return outer[0] - tol <= b[0] and outer[1] - tol <= b[1] and b[2] <= outer[2] + tol and b[3] <= outer[3] + tol


def drawn_lines(lines, box, others):
    """The 2furni entities that draw a piece with no outline of its own (the corner sofa: seat, backs, end table, each
    a line or polyline): all those lying inside its plan box, less any inside a smaller neighbour's box (a rug's box
    holds the coffee table's outline, which isn't the rug's). A block member counts only when its block doesn't."""
    a0 = area(box)
    whole = {l["handle"] for l in lines if l["block"] and within(l["box"], box, 0.01)}
    out = []
    for l in lines:  # 1 cm slack: a neighbour's line 2 cm off its edge (a plant beside the TV wall) isn't its own
        if not within(l["box"], box, 0.01) or ("/" in l["handle"] and l["handle"].split("/")[0] in whole):
            continue
        if any(area(o) < a0 - 1e-6 and within(l["box"], o, 0.005) for o in others):
            continue
        out.append(l)
    return out


def outline_of(ws, piece):
    """("own", handle, box) of the 2furni outline drawn for this piece; ("block", handle, box) when it is drawn as one
    furniture block; ("shared", handle, box) when it is drawn only inside one outline round several pieces; ("lines",
    [handles], box) when it is drawn as several lines inside its plan box (no outline of its own); None for a
    3D-only one."""
    box, low = [float(v) for v in piece["box"]], float(piece.get("low", 0))
    if low >= HEAD_HEIGHT or piece.get("light"):
        return None
    best, best_iou, blk, blk_iou, cover = None, 0.0, None, 0.0, None
    outlines, lines = outlines_near(ws, box)
    for o in outlines:
        i = inter(box, o["box"])
        iou = i / (area(box) + area(o["box"]) - i) if i else 0.0
        if o.get("block"):
            if iou > blk_iou:
                blk, blk_iou = o, iou
        elif iou > best_iou:
            best, best_iou = o, iou
        # a group outline it stands in: its real shape, not just its extent (a plant in the crook of the terrace's L planter)
        mid = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        if not o.get("block") and area(box) and i / area(box) >= 0.8 and (not o.get("pts") or inside(mid, o["pts"])) \
                and (cover is None or area(o["box"]) < area(cover["box"])):
            cover = o
    if best and best_iou >= 0.45:
        return "own", best["handle"], best["box"]
    if blk and blk_iou >= 0.45:  # no outline of its own: the block it's drawn as
        return "block", blk["handle"], blk["box"]
    if cover and low < 0.3:
        return "shared", cover["handle"], cover["box"]
    drawn = drawn_lines(lines, box, [[float(t) for t in o] for o in piece.get("others") or []])
    if drawn:
        b = [min(l["box"][0] for l in drawn), min(l["box"][1] for l in drawn), max(l["box"][2] for l in drawn), max(l["box"][3] for l in drawn)]
        return "lines", [l["handle"] for l in drawn], b
    return None


# --- Geometry: plan box of a piece <-> its anchor / position and scale ------------------------------------------------
def axes(facing):
    """((plan axis index, sign) across, (plan axis index, sign) out) for a facing."""
    ux, uy = U[facing]
    fx, fy = F[facing]
    return ((0, ux) if ux else (1, uy)), ((0, fx) if fx else (1, fy))


def solve(A, P, S, Si, sign, b0, b1, n0, n1):
    """One plan axis: the piece spans b0..b1 with plan = A + sign·Si·(P + S·u); it should span n0..n1.
    Returns (A', P', S'): for an item P stays 0 and A moves; for a part A (the item's anchor) stays and P moves."""
    k = (n1 - n0) / (b1 - b0) if b1 - b0 > 1e-6 else 1.0
    c, c2 = (b0 + b1) / 2, (n0 + n1) / 2
    um = (sign * (c - A) / Si - P) / S
    S2 = S * k
    return A, sign * (c2 - A) / Si - S2 * um, S2


# --- Where each piece started (move-origins-<version>.json) -----------------------------------------------------------
def origins_path(v):
    return f"move-origins-{v}.json"


def origin_at(entries, label, box, tol=0.05):
    """The entry for the piece with this label whose plan box is now centred within tol of box's centre, or None."""
    c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    best = min((e for e in entries if e["label"] == label), default=None,
               key=lambda e: math.hypot(e["at"][0] - c[0], e["at"][1] - c[1]))
    return best if best and math.hypot(best["at"][0] - c[0], best["at"][1] - c[1]) <= tol else None


def record_origin(ws, v, label, box, rot, nbox, nrot, z=None, nz=None):
    """Carry the piece's first box / turn / height (low, high) over to where it is now (dropped once it is back where
    it started)."""
    path = origins_path(v)
    try:
        entries = json.loads(ws.text(path) or "[]")
    except ValueError:
        entries = []
    o = origin_at(entries, label, box)
    if o:
        entries.remove(o)
    first = {"box": o["box"], "rot": o["rot"], **({"z": o["z"]} if o.get("z") else {})} if o else \
        {"box": [r4(t) for t in box], "rot": r4(rot), **({"z": [r4(t) for t in z]} if z else {})}
    if z and "z" not in first:  # an entry from before heights: it started at the height it had then
        first["z"] = [r4(t) for t in z]
    back = all(abs(a - b) < 0.003 for a, b in zip(first["box"], nbox)) and abs(first["rot"] - nrot) < 1e-3 \
        and (not nz or not first.get("z") or all(abs(a - b) < 0.003 for a, b in zip(first["z"], nz)))
    if not back:
        entries.append({"label": label, "at": [r4((nbox[0] + nbox[2]) / 2), r4((nbox[1] + nbox[3]) / 2)], **first})
    entries.sort(key=lambda e: (e["label"], e["at"]))
    body = "[\n" + ",\n".join(json.dumps(e) for e in entries) + "\n]\n" if entries else "[]\n"
    ws.write(path, body.encode())  # a line each: merges cleanly


# --- Editing furnish.js ------------------------------------------------------------------------------------------------
def unique_op(text, start, end):
    """(old, new-offsets) context around text[start:end] that occurs once: whole lines, grown until unique."""
    s = text.rfind("\n", 0, start) + 1
    e = text.find("\n", end)
    e = len(text) if e < 0 else e
    while text.count(text[s:e]) > 1 and (s > 0 or e < len(text)):
        s = text.rfind("\n", 0, max(0, s - 1)) + 1 if s > 0 else 0
        e2 = text.find("\n", e + 1)
        e = len(text) if e2 < 0 else e2
    return s, e


def write_furnish(ws, new_text):
    old = ws.text("furnish.js")
    if new_text == old:
        return
    # one search/replace op over the changed span, for the live override's replay
    i = 0
    while i < min(len(old), len(new_text)) and old[i] == new_text[i]:
        i += 1
    j = 0
    while j < min(len(old), len(new_text)) - i and old[-1 - j] == new_text[-1 - j]:
        j += 1
    s, e = unique_op(old, i, len(old) - j)
    tail = len(old) - e
    ws.write("furnish.js", new_text.encode(), {"old": old[s:e], "new": new_text[s:len(new_text) - tail]})
    if (err := E.js_check(ws, "furnish.js")):
        raise RuntimeError(f"the change would break furnish.js, so nothing was saved: {err}")


def set_xy(text, call, x, y, v, shared):
    a = call["args"]
    if a[0].strip().startswith("...("):  # item(...(KC ? [a, b] : [c, d]), "S", ...)
        inner = a[0].strip()[3:]
        body = inner[1:-1].strip()
        m = re.match(r'^version\s*===\s*"' + re.escape(v) + r'"\s*\?\s*\[[^\]]*\]\s*:\s*(.+)$', body, re.S)
        rest = m[1] if m else body
        new0 = re.match(r"\s*", a[0]).group(0) + (f'...(version === "{v}" ? [{fmt(x)}, {fmt(y)}] : {rest})' if shared or m
                                                  else f"...[{fmt(x)}, {fmt(y)}]")
        return text[:call["open"] + 1] + ",".join([new0] + a[1:]) + text[call["close"]:]
    new_args = [set_arg(a[0], x, v, shared), set_arg(a[1], y, v, shared)] + a[2:]
    return text[:call["open"] + 1] + ",".join(new_args) + text[call["close"]:]


def set_rug(text, call, b, v, shared):
    a = call["args"]
    new = [set_arg(a[k], b[k], v, shared) for k in range(4)] + a[4:]
    return text[:call["open"] + 1] + ",".join(new) + text[call["close"]:]


SIZED_DEFAULTS = ["1", "1", "1", "0"]  # across, out, up (height scale), lift (m)


def sized_args(text, call):
    """The call's sized(..., across, out, up, lift) args as text (defaults where it has none)."""
    if not call["sized"]:
        return list(SIZED_DEFAULTS)
    so_open = text.index("(", call["outer"])
    # only what follows the piece's own call: its body can hold comments with apostrophes, which split_args reads as quotes
    olds = [t.strip() for t in split_args(text[call["close"] + 1:close_paren(text, so_open)])[1:5]]
    return olds + SIZED_DEFAULTS[len(olds):]


def set_size(text, call, sa, so, v, shared, up=None, lift=None):
    """Wrap (or rewrap, or unwrap) the call in sized(..., across, out[, up, lift]), for version v only on a shared line.
    up / lift None: as they are."""
    inner = text[call["name"]:call["close"] + 1]
    olds = sized_args(text, call)
    if call["sized"]:
        so_open = text.index("(", call["outer"])
        start, end = call["outer"], close_paren(text, so_open) + 1
    else:
        start, end = call["name"], call["close"] + 1

    def one(old, new, unit):
        if new is None:
            return old
        if not shared and not gated(old, v):
            return fmt(new)
        g = gated(old, v)
        rest = g[1] if g else old
        return rest if abs(new - float(unit)) < 1e-4 and rest == unit else f'version === "{v}" ? {fmt(new)} : {rest}'
    args = [one(o, n, u) for o, n, u in zip(olds, [sa, so, up, lift], SIZED_DEFAULTS)]
    while len(args) > 2 and args[-1] == SIZED_DEFAULTS[len(args) - 1]:  # no trailing defaults
        args.pop()
    rep = inner if args == ["1", "1"] else f"sized({inner}, {', '.join(args)})"
    return text[:start] + rep + text[end:]


def part_block(text, call, label):
    """(offset just after the '{' of p.label("<label>", p => {, its parameter name) inside the item's call."""
    seg = text[call["open"]:call["close"]]
    m = re.search(r"\b\w+\.label\(\s*\"" + re.escape(label) + r"\"\s*,\s*(\w+)\s*=>\s*\{", seg)
    if not m:
        raise ValueError(f"I can't find where the {label} is built, " + CANT)
    return call["open"] + m.end(), m[1]


PART_LINE = re.compile(r'[ \t]*(?:if \(version === "([\w-]+)"\) )?\w+\.g\.position\.set\([^)]*\)[;,]\s*\w+\.g\.scale\.set\([^)]*\);'
                       r'\s*// Move(?: and Resize| tool)[^\n]*\n')


def set_part(text, call, label, pos, sc, v, shared, py=0.0, sy=1.0):
    """This part's line: where it sits (pos [x, z], py its height) and how big (sc [x, z], sy its height scale)."""
    at, pv = part_block(text, call, label)
    nl = text.index("\n", at) + 1
    k, mine = nl, None
    while (m := PART_LINE.match(text, k)):  # earlier lines: an older version's, or the shared one
        if (m[1] == v) if shared else (m[1] is None):
            mine = m
        k = m.end()
    ind = re.match(r"[ \t]*", text[k:]).group(0) or "      "
    move = (f"{pv}.g.position.set({fmt(pos[0])}, {fmt(py)}, {fmt(pos[1])}){', ' if shared else '; '}"
            f"{pv}.g.scale.set({fmt(sc[0])}, {fmt(sy)}, {fmt(sc[1])});")
    line = (f'{ind}{f"if (version === {json.dumps(v)}) " if shared else ""}{move}'
            f"  // Move and Resize: where this part sits / how big, in the piece's frame\n")
    if mine:
        return text[:mine.start()] + line + text[mine.end():]
    return text[:k] + line + text[k:]


def table_key(piece):
    """Its MOVED key: "x,y,facing", plus "#n" when other pieces are placed with the same x, y, facing (the nth placed)."""
    f = piece.get("facing")
    key = f"{fmt(piece['x'])},{fmt(piece['y'])},{f if isinstance(f, str) else json.dumps(f)}"
    return key + (f"#{int(piece['twin'])}" if int(piece.get("twins") or 1) > 1 and int(piece.get("twin") or 0) else "")


def table_entry(text, piece, v):
    """This version's MOVED values for the piece ([x, y, across, out(, up, lift)]), or None."""
    key = table_key(piece)
    m = re.search(r'^[ \t]*if \(version === "' + re.escape(v) + r'"\) MOVED\["' + re.escape(key) + r'"\] = \[([^\]]*)\];', text, re.M)
    return [float(t) for t in m[1].split(",")] if m else None


def set_table(text, piece, x, y, sa, so, v, label, up=1.0, lift=0.0):
    """This version's MOVED line for a piece a loop or shared code places: where it goes, how big, how high."""
    key = table_key(piece)
    rx = re.compile(r'^[ \t]*if \(version === "' + re.escape(v) + r'"\) MOVED\["' + re.escape(key) + r'"\] = \[[^\]]*\];[^\n]*\n', re.M)
    decl = re.search(r"^([ \t]*)const MOVED = \{\};[^\n]*\n", text, re.M)
    same = near(x, float(piece["x"]), 1e-4) and near(y, float(piece["y"]), 1e-4) and near(sa, 1, 1e-4) and near(so, 1, 1e-4) \
        and near(up, 1, 1e-4) and near(lift, 0, 1e-4)
    vals = [x, y, sa, so] + ([] if near(up, 1, 1e-4) and near(lift, 0, 1e-4) else [up, lift])
    nums = ", ".join(fmt(t) for t in vals)
    tidy = re.sub(r"[^\w ,.()-]", "", label)[:50]  # outside the f-string: Python 3.11 (local) allows no backslash in one
    line = "" if same else (f'{decl[1]}if (version === "{v}") MOVED["{key}"] = [{nums}];'
                            f"  // Move and Resize: {tidy}\n")
    if (m := rx.search(text)):
        return text[:m.start()] + line + text[m.end():]
    return text[:decl.end()] + line + text[decl.end():]


# --- A part drawn from numbers in its piece's code (p.label(..., param)) -------------------------------------------
def js_list(v):
    return "[" + ", ".join(js_list(e) for e in v) + "]" if isinstance(v, list) else fmt(v)


def set_param(text, call, param, lo, hi, v, axis="x"):
    """Set across lo..hi (the item's local x; axis "z": its height, when param has "z") in the array the part is
    drawn from, e.g. tall[1] = [lo, hi]."""
    src = param["src"]
    m = re.compile(r"(?:\bconst\b|\blet\b|,)\s*" + re.escape(src) + r"\s*=(?!=)\s*").search(text, call["open"], call["close"])
    if not m:
        raise ValueError(f"I can't find the numbers the {src} is drawn from, " + CANT)
    s = m.end()
    k, depth = s, 0
    while k < len(text) and not (depth == 0 and text[k] in ",;\n"):
        depth += text[k] in "([{"
        depth -= text[k] in ")]}"
        k += 1
    expr = text[s:k].rstrip()
    e = s + len(expr)
    t = re.match(r"^(\w+)\s*\?\s*", expr)
    if t and expr[t.end()] == "[":  # KC ? [...] : [...]
        a0 = s + t.end()
        a1 = close_paren(text, a0) + 1
        cond = re.search(r"\b(?:const|let)\s+" + t[1] + r"\s*=\s*([^,;\n]+)", text)
        exclusive = cond and re.fullmatch(r'\s*version\s*===\s*"' + re.escape(v) + r'"\s*', cond[1])
        arr_s, arr_e = (a0, a1) if exclusive else (s, e)
    elif expr.startswith("["):
        exclusive, arr_s, arr_e = False, s, e
    else:
        raise ValueError(f"The {src} numbers are worked out in code, " + CANT)
    src_text = text[arr_s:arr_e] if exclusive else expr if expr.startswith("[") else text[s + t.end():close_paren(text, s + t.end()) + 1]
    if not re.fullmatch(r"[\s\d.,\[\]-]+", src_text):
        raise ValueError(f"The {src} numbers aren't plain numbers, " + CANT)
    arr = json.loads(src_text)
    el = arr
    for i in param.get("at", []):
        el = el[i]
    i0, i1 = param[axis]
    old = (el[i0], el[i1])
    el[i0], el[i1] = r4(lo), r4(hi)
    new = js_list(arr)
    if exclusive:
        return text[:arr_s] + new + text[arr_e:], old
    return text[:s] + f'version === "{v}" ? {new} : {expr}' + text[e:], old


# --- The request ------------------------------------------------------------------------------------------------------
def describe(dx, dy):
    parts = []
    if abs(dx) >= 0.005:
        parts.append(f"{cm(dx)} {'east' if dx > 0 else 'west'}")
    if abs(dy) >= 0.005:
        parts.append(f"{cm(dy)} {'north' if dy > 0 else 'south'}")
    return " and ".join(parts) or "a hair"


def plan_op(ws, ops):
    out = E.tool(ws, "dxf_edit", {"ops": ops})
    if out.startswith("nothing changed") or out.startswith("As-built"):
        raise ValueError(f"the plan wouldn't take it: {out[:300]}")
    try:  # the JSON comes first; notes and any stderr (a warning on Vercel) follow it
        return json.JSONDecoder().raw_decode(out.lstrip())[0]
    except ValueError:
        raise ValueError(f"the plan edit gave an answer I can't read: {out[:300]}")


def blocker(rep):
    for l in rep.get("log", []):
        m = re.search(r"touches (wall [\w-]+|[\w -]+?)(?: -|\])", l)
        if m:
            return "a wall" if m[1].startswith("wall") else m[1].strip()
    return "something"


def changed_box(rep, handle, old):
    h2 = (rep.get("handles_remapped") or {}).get(handle, handle)
    for pc in rep.get("pieces_changed", []):
        if pc["handle"] in (handle, h2) or (pc["old"] and all(abs(a - b) < 0.003 for a, b in zip(pc["old"], old))):
            return pc["new"]
    return None


def set_removed(text, piece, v, label, gone=True):
    """This version's REMOVED line for a piece Move and Resize deleted: its item( call stays (other versions may run it),
    the piece just never joins the scene. Keyed like MOVED, by x, y, facing as the code places it."""
    f = piece.get("facing")
    key = f"{fmt(piece['x'])},{fmt(piece['y'])},{f if isinstance(f, str) else json.dumps(f)}"
    if int(piece.get("twins") or 1) > 1 and int(piece.get("twin") or 0):  # one of several at the same spot: its number
        key += f"#{int(piece['twin'])}"
    rx = re.compile(r'^[ \t]*if \(version === "' + re.escape(v) + r'"\) REMOVED\.add\("' + re.escape(key) + r'"\);[^\n]*\n', re.M)
    decl = re.search(r"^([ \t]*)const REMOVED = new Set\(\);[^\n]*\n", text, re.M)
    if not decl:
        raise ValueError("I can't find furnish.js's REMOVED list, " + CANT)
    tidy = re.sub(r"[^\w ,.()-]", "", label)[:50]
    line = f'{decl[1]}if (version === "{v}") REMOVED.add("{key}");  // Move and Resize: deleted {tidy}\n' if gone else ""
    if (m := rx.search(text)):
        return text[:m.start()] + line + text[m.end():]
    return text[:decl.end()] + line + text[decl.end():]


# --- Walls, doors and windows, picked on the 2D drawing: the plan changes and the 3D is rebuilt from it ----------------
OPEN_NAME = {"window": "window", "slider": "glass slider", "door": "door"}
DOOR_FRAME = 0.0225  # m: a door redrawn by convert_opening rebuilds with a gap this much wider than its width (measured)


def plan_element(req, v):
    """op "wall": {at: [x, y] a point in the wall; info: true -> its run, nothing saved; dx, dy -> slid across itself
    (the walls meeting it follow); del -> removed with its doors / windows}. op "opening": {at, kind (window / slider /
    door), box [x0, y0, x1, y1] its gap; shift (m along its wall, + = towards +x / +y), width (m) -> moved / resized
    along its wall; del -> walled up}. Plan metres. Saved like any change (rebuilt, one revision, Undo)."""
    op, at = req["op"], [float(t) for t in req.get("at") or []]
    if len(at) != 2:
        raise ValueError("Say where: at [x, y].")
    ws = E.Workspace(v)
    ws.allow_as_built = False
    ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = False, False, {}, {}, [], []
    if not req.get("info") and req.get("rev") is not None and req.get("rev") != (ws.man and ws.man.get("rev")):
        raise ValueError("This page is behind the latest change to this version. Reload and try again.")
    notes = []
    if op == "wall":
        run = plan_op(ws, [{"op": "mark_wall", "at": at}]).get("walls_changed") or []
        if not run:
            raise ValueError("There's no wall there.")
        w = run[0]
        a, b, t = w["a"], w["b"], float(w["thickness"])
        if req.get("info"):
            return {"op": "wall", "a": a, "b": b, "thickness": t}
        if req.get("del"):
            rep = plan_op(ws, [{"op": "remove_wall", "at": at}])
            summary = f"{NAME}: removed the wall from ({a[0]:.2f}, {a[1]:.2f}) to ({b[0]:.2f}, {b[1]:.2f})"
        else:
            dx, dy = float(req.get("dx") or 0), float(req.get("dy") or 0)
            if abs(dx) < 0.001 and abs(dy) < 0.001:
                raise ValueError("That didn't move it.")
            rep = plan_op(ws, [{"op": "move_wall", "at": at, "dx": r4(dx), "dy": r4(dy)}])
            summary = f"{NAME}: wall moved {describe(dx, dy)}"
        notes += [str(x) for x in rep.get("warnings") or []][:2]
    else:
        kind = req.get("kind") or "window"
        name = OPEN_NAME.get(kind, "opening")
        box = [float(t) for t in req.get("box") or []]
        if len(box) != 4:
            raise ValueError("Send the opening's box.")
        along = 0 if box[2] - box[0] >= box[3] - box[1] else 1  # its wall runs along plan x (0) or y (1)
        w0 = box[along + 2] - box[along]
        shift, width = float(req.get("shift") or 0), float(req.get("width") or w0)
        if req.get("del"):
            rep = plan_op(ws, [{"op": "remove_opening", "at": at}])
            summary = f"{NAME}: {name} walled up"
        else:
            if abs(shift) < 0.001 and abs(width - w0) < 0.001:
                raise ValueError("That didn't change it.")
            if width < 0.3:
                raise ValueError(f"A {name} under 30 cm wide isn't one.")
            layer = "Windows" if kind in ("window", "slider") else "3door"
            pad = 0.25
            code, q = E.run([E.dwg_python(), str(E.ROOT / "edit_ai_dxf.py"), "query", str(ws.dxf()), f"--origin={E.ORIGIN[0]},{E.ORIGIN[1]}",
                             f"--bbox={box[0] - pad},{box[1] - pad},{box[2] + pad},{box[3] + pad}", f"--layers={layer}", "--limit", "60"], timeout=90)
            try:
                found = json.JSONDecoder().raw_decode(q.lstrip())[0].get("entities", [])
            except ValueError:
                raise ValueError(f"the plan lookup gave an answer I can't read: {q[:300]}")
            d = [0.0, 0.0]
            d[along] = shift
            grow = width - w0  # the ops' own "width" isn't the gap (a window's is its glazing): only the change is passed on
            if kind in ("window", "slider") and (h := next((e["handle"] for e in found if e["type"] == "LINE"), None)):
                rep = plan_op(ws, [{"op": "move_window", "handle": h, "dx": r4(d[0]), "dy": r4(d[1])}])
                if abs(grow) >= 0.001:
                    wm = (rep.get("windows_moved") or [{}])[0]
                    rep = plan_op(ws, [{"op": "move_window", "handle": h, "dx": 0, "dy": 0, "width": r4(float(wm["new_width"]) + grow)}])
            elif kind == "door" and abs(grow) < 0.001 and (h := next((e["handle"] for e in found if e["type"] == "ARC"), None)):
                rep = plan_op(ws, [{"op": "move_door", "handle": h, "along": r4(shift)}])  # a loose door slides as drawn
            else:  # a block door (or a resize): emptied and redrawn the same kind at its own width, then resized about its centre
                to = {"window": "window", "slider": "glass_slider", "door": "door"}.get(kind, "opening")
                # a redrawn door's frame leaves the 3D gap ~2 cm wider than the width asked for: ask for the gap less that
                rep = plan_op(ws, [{"op": "convert_opening", "at": at, "to": to, "shift": r4(shift),
                                    "width": r4(width - (DOOR_FRAME if kind == "door" else 0))}])
                if kind == "door":
                    notes.append("the door was redrawn from its block; check which way it opens")
            bits = ([f"{cm(shift)} {('east' if shift > 0 else 'west') if along == 0 else ('north' if shift > 0 else 'south')}"]
                    if abs(shift) >= 0.005 else []) + ([f"{width * 100:.0f} cm wide (was {w0 * 100:.0f})"] if abs(width - w0) >= 0.005 else [])
            summary = f"{NAME}: {name} " + " and ".join(bits)
        notes += [str(x) for x in rep.get("warnings") or []][:2]
    if (breaks := E.lock_breaks(ws, "")):
        E.lock_breaks(ws, " ".join(l["names"][0] for l, _ in breaks), record=True)
        notes.append("this changes a settled design decision (" + "; ".join(l["what"][:90] for l, _ in breaks)
                     + "), so that lock is now suspended; Undo puts it back")
    man = E.save(ws, summary + (" (" + "; ".join(notes) + ")" if notes else ""))
    return {"rev": man["rev"], "changed": sorted(ws.changed), "summary": summary, "notes": notes, "op": op, "plan": True,
            "sync": man.get("sync")}


def save(ws, summary):
    """E.save, or in a batch just note the piece's summary (the batch saves once at the end)."""
    if getattr(ws, "batch", None) is not None:
        ws.batch.append(summary)
        return {"rev": None}
    return E.save(ws, summary)


def batch(req, v):
    """op "batch": a group (Shift-click) moved or deleted together, every piece in one workspace and saved as one
    revision, so one Undo takes it all back. items: [{op: "move" | "delete", piece, dx, dy}]; the pieces leading the move
    go first, so none is blocked on the plan by one that is about to move out of the way."""
    items = req.get("items") or []
    if not 2 <= len(items) <= 40:
        raise ValueError("A group is 2 to 40 pieces.")
    if any(it.get("op") not in ("move", "delete") for it in items):
        raise ValueError("A group can be moved or deleted together; resize or turn one piece at a time.")
    lead = lambda it: -sum(((float(it["piece"]["box"][k]) + float(it["piece"]["box"][k + 2])) / 2) * float(it.get(d) or 0)
                           for k, d in ((0, "dx"), (1, "dy")))
    ws = E.Workspace(v)
    ws.batch, notes, out = [], [], []
    for it in sorted(items, key=lead):
        try:
            r = transform({**it, "version": v, "rev": req.get("rev")}, ws)
        except ValueError as e:
            raise ValueError(f"The {it['piece'].get('label') or 'piece'}: {e} Nothing in the group was saved.")
        out.append(r)
        notes += [f"{it['piece'].get('label') or 'piece'}: {n}" for n in r.get("notes") or []]
    names = ", ".join(dict.fromkeys(str(it["piece"].get("label") or "piece") for it in items))[:120]
    first = items[0]
    summary = (f"{NAME}: deleted {len(items)} pieces ({names})" if first["op"] == "delete"
               else f"{NAME}: {len(items)} pieces {describe(float(first.get('dx') or 0), float(first.get('dy') or 0))} ({names})")
    ws.batch = None
    man = E.save(ws, summary + (" (" + "; ".join(notes[:6]) + ")" if notes else ""))
    return {"rev": man["rev"], "changed": sorted(ws.changed), "summary": summary, "notes": notes[:6], "op": "batch",
            "plan": any(r.get("plan") for r in out),
            "items": out, "sync": man.get("sync")}


def delete(ws, v, piece, text, found, sh, label):
    """op "delete": the piece goes from the 3D (a REMOVED line; a part shrunk to nothing on its own line) and from the
    plan (its outline or block, and the lines drawn inside it; a group outline round several pieces stays)."""
    f0, notes = text, []
    is_part = piece.get("kind") == "part"
    if piece.get("param"):
        raise ValueError(f"The {label} is cut into a wall, so deleting it means filling the wall in. Make an Edit can do it.")
    if is_part:
        pos = [float(t) for t in piece.get("pos") or [0, 0]]
        text = set_part(text, found["call"], piece["part"], pos, [0, 0], v, sh, float(piece.get("posY") or 0), 0)
    else:
        if int(piece.get("twins") or 1) > 1 and not int(piece.get("twin") or 0):
            raise ValueError("Another piece is placed at the same spot by the same code, so this one can't be told apart, " + CANT)
        text = set_removed(text, piece, v, label)
    outline = None if piece.get("noPlan") or is_part else outline_of(ws, piece)
    kind = outline and outline[0]
    if kind == "own":  # the outline and what's drawn inside it (a pillow, a sink bowl), not a smaller neighbour's lines
        outs, lines = outlines_near(ws, outline[2], pad=0.01)
        inner = drawn_lines(lines, list(outline[2]), [[float(t) for t in o] for o in piece.get("others") or []])
        pieces = {o["handle"] for o in outs}  # another piece's own outline or block inside it (a rug's coffee table) stays
        plan_op(ws, [{"op": "delete", "handles": [outline[1]] + [l["handle"] for l in inner if l["handle"] not in pieces
                                                                 and "/" not in l["handle"]], "detail": True}])
    elif kind == "block":
        plan_op(ws, [{"op": "delete", "handles": [outline[1]]}])
    elif kind == "lines":
        plan_op(ws, [{"op": "delete", "handles": [h for h in outline[1] if "/" not in h], "detail": True}])
    elif kind == "shared":
        notes.append("on the plan it's drawn inside one outline with the pieces next to it, so only the 3D changed")
    else:
        notes.append("it isn't drawn on the 2D plan (3D-only), so only the 3D changed")
    write_furnish(ws, text)  # the version's own furnish file: nothing to check against other versions (module docstring)
    if (breaks := E.lock_breaks(ws, "")):  # a settled decision: deleted on purpose (Accept), its lock suspended; Undo restores it
        E.lock_breaks(ws, " ".join(l["names"][0] for l, _ in breaks), record=True)
        notes.append("this changes a settled design decision (" + "; ".join(l["what"][:90] for l, _ in breaks)
                     + "), so that lock is now suspended; Undo puts it back")
    summary = f"{NAME}: deleted the {label}"
    man = save(ws, summary + (" (" + "; ".join(notes) + ")" if notes else ""))
    return {"rev": man["rev"], "changed": sorted(ws.changed), "summary": summary, "notes": notes, "op": "delete",
            "plan": kind in ("own", "block", "lines"), "outline": outline and outline[1], "how": found["how"], "sync": man.get("sync")}


def transform(req, ws=None):
    v = E.plan_version(req.get("version"))
    if v not in E.VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    if v == "as-built":
        raise ValueError("As-built is the survey of the flat as it stands; it can't be changed.")
    op, piece = req.get("op"), req.get("piece") or {}
    if op in ("wall", "opening"):
        return plan_element(req, v)
    if op not in ("move", "resize", "delete", "batch"):
        raise ValueError("op must be move, resize, delete or batch")
    facing = piece.get("facing")
    if op == "batch":
        return batch(req, v)
    ws = ws or E.Workspace(v)  # a batch passes its own: every piece in one workspace, saved once
    ws.allow_as_built = False
    ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = getattr(ws, "plan_dirty", False), False, {}, {}, [], []
    cur = ws.man and ws.man.get("rev")
    if req.get("rev") is not None and req.get("rev") != cur:
        raise ValueError("This page is behind the latest change to this version. Reload and try again.")
    text = f0 = ws.text("furnish.js")
    shared = lambda n: False  # the version's own file: no line of it runs for another version (see the docstring)
    try:
        found = find_call(text, piece, v)
    except ValueError:
        if op != "delete" or piece.get("kind") == "part":
            raise
        found = {"line": None, "call": None, "how": "table"}  # a whole piece goes by its REMOVED key: no line of its own needed
    if found["line"] and E.version_scope(text, v)[found["line"] - 1] is False:
        raise ValueError("That code belongs to another plan version.")
    call = found["call"]
    sh = shared(found["line"]) if found["line"] else True
    label = piece.get("label") or "piece"
    is_part = piece.get("kind") == "part"
    param = piece.get("param") if is_part else None
    if is_part and found["how"] not in ("literal", "expr", "spread"):
        raise ValueError(f"The {label} sits in a piece built by shared code, " + CANT)
    if op == "delete":
        return delete(ws, v, piece, text, found, sh, label)
    notes = []
    box = [float(t) for t in piece["box"]]
    outline = None if piece.get("noPlan") or param else outline_of(ws, piece)  # a niche is cut into a wall: not on the plan
    own = outline and outline[0] == "own"
    block = outline and outline[0] == "block"
    x, y = float(piece["x"]), float(piece["y"])
    A = [float(t) for t in piece.get("anchor") or [x, y]]  # where the item stands now (a MOVED piece isn't at x, y)
    si = [float(t) for t in piece.get("scale") or [1, 1]]
    if is_part and piece.get("frame"):  # a part inside a part: work in its parent's frame
        fr = piece["frame"]
        if fr.get("turned"):
            raise ValueError(f"The {label} is turned inside its piece, " + CANT)
        if facing not in U:
            raise ValueError("This piece is turned at an angle; its parts can't be changed on their own. Make an Edit can.")
        (ia_, sa_), (io_, so_) = axes(facing)
        A[ia_] += sa_ * si[0] * float(fr["pos"][0])
        A[io_] += so_ * si[1] * float(fr["pos"][1])
        si = [si[0] * float(fr["scale"][0]), si[1] * float(fr["scale"][1])]

    rot = (float(req.get("rotate") or 0) + 180) % 360 - 180 if op == "move" else 0.0
    rot = 0.0 if abs(rot) < 0.05 else rot
    if rot:
        if is_part:
            raise ValueError(f"The {label} is part of a piece; turn the whole piece instead.")
        if found["how"] in ("rug", "table") or facing_at(call) is None or facing_of(call["args"][facing_at(call)], v) is None:
            raise ValueError(f"The {label} is placed by code that has no facing of its own to turn, " + CANT)
    # Height: low / high (m) now; dz (move) or z = [low, high] (resize) asks for new ones. The plan has no heights.
    L0, H0 = float(piece.get("low", 0)), float(piece.get("high", 0))
    dz = float(req.get("dz") or 0) if op == "move" else 0.0
    dz = 0.0 if abs(dz) < 0.001 else dz
    zbox = [float(t) for t in req["z"]] if op == "resize" and req.get("z") else None
    if zbox and abs(zbox[0] - L0) < 0.001 and abs(zbox[1] - H0) < 0.001:
        zbox = None
    if zbox and (zbox[1] - zbox[0] < min(0.01, H0 - L0) - 1e-4 or H0 - L0 < 1e-4):
        raise ValueError("That's too small to be a piece.")
    if op == "move":
        dx, dy = float(req.get("dx") or 0), float(req.get("dy") or 0)
        if abs(dx) < 0.001 and abs(dy) < 0.001 and not rot and not dz:
            raise ValueError("That didn't move it.")
        nbox = [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]
        if rot:  # turned about the centre of its plan box: the box it then takes
            c, t = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), math.radians(rot)
            hw, hd = (box[2] - box[0]) / 2, (box[3] - box[1]) / 2
            ew, ed = abs(hw * math.cos(t)) + abs(hd * math.sin(t)), abs(hw * math.sin(t)) + abs(hd * math.cos(t))
            nbox = [c[0] + dx - ew, c[1] + dy - ed, c[0] + dx + ew, c[1] + dy + ed]
        planar = abs(dx) >= 0.001 or abs(dy) >= 0.001 or bool(rot)
    else:
        nbox = [float(t) for t in req.get("box") or box]
        if nbox[2] - nbox[0] < min(0.03, box[2] - box[0]) - 1e-4 or nbox[3] - nbox[1] < min(0.02, box[3] - box[1]) - 1e-4:
            raise ValueError("That's too small to be a piece.")
        side = {"E": nbox[2] - box[2], "W": box[0] - nbox[0], "N": nbox[3] - box[3], "S": box[1] - nbox[1]}
        planar = any(abs(d) >= 0.001 for d in side.values())
        if not planar:
            nbox = list(box)
            if not zbox:
                raise ValueError("That didn't change its size.")
    if (dz or zbox) and param and not param.get("z"):
        raise ValueError(f"The {label}'s height is fixed in the code it's cut from in the wall (a settled design: the tall "
                         "niches match each other), " + CANT)

    if not planar:
        if outline:
            notes.append("the 2D plan shows no heights, so only the 3D changed")
    elif outline and outline[0] == "shared":  # drawn inside one outline round several pieces: 3D only, inside it
        if area(nbox) and inter(nbox, outline[2]) / area(nbox) < 0.8:
            raise ValueError("On the plan this piece is drawn inside one outline with the pieces next to it, so it can only "
                             "be adjusted within that outline. Make an Edit can redraw the plan.")
        notes.append("on the plan it's drawn as part of a group outline, so only the 3D changed")
    elif outline and outline[0] == "lines":  # drawn as several lines: they all go (or stretch) with it
        if rot:
            c = [r4((box[0] + box[2]) / 2), r4((box[1] + box[3]) / 2)]
            plan_op(ws, [{"op": "rotate", "handles": outline[1], "angle": round(rot, 3), "centre": c, "dx": r4(dx), "dy": r4(dy)}])
        elif op == "move":
            plan_op(ws, [{"op": "move", "handles": outline[1], "dx": r4(dx), "dy": r4(dy)}])
        else:  # the plan box maps onto the new one: x' = n0 + (x - b0)·k
            kx, ky = (nbox[2] - nbox[0]) / (box[2] - box[0]), (nbox[3] - nbox[1]) / (box[3] - box[1])
            plan_op(ws, [{"op": "scale", "handles": outline[1], "base": [r4(box[0]), r4(box[1])], "sx": round(kx, 6), "sy": round(ky, 6),
                          "dx": r4(nbox[0] - box[0]), "dy": r4(nbox[1] - box[1])}])
    elif (block or own) and rot:  # turned: the plan piece turns about the same point and moves the same metres
        rep = plan_op(ws, [{"op": "rotate_piece", "handle": outline[1], "angle": round(rot, 3),
                            "centre": [r4((box[0] + box[2]) / 2), r4((box[1] + box[3]) / 2)], "dx": r4(dx), "dy": r4(dy)}])
        notes += [f"it now runs into {c.get('with')}" for c in rep.get("clashes", []) if not c.get("free")][:2]
    elif block:  # drawn as one block (the WC symbol): a move takes the whole block with it, a resize stretches it
        if op == "move":
            plan_op(ws, [{"op": "move", "handles": [outline[1]], "dx": r4(dx), "dy": r4(dy)}])
        else:  # the plan box maps onto the new one, as the 3D does: x' = n0 + (x - b0)·k
            kx, ky = (nbox[2] - nbox[0]) / (box[2] - box[0]), (nbox[3] - nbox[1]) / (box[3] - box[1])
            plan_op(ws, [{"op": "scale", "handles": [outline[1]], "base": [r4(box[0]), r4(box[1])], "sx": round(kx, 6), "sy": round(ky, 6),
                          "dx": r4(nbox[0] - box[0]), "dy": r4(nbox[1] - box[1])}])
    elif own:  # the plan moves first; the 3D follows what the plan really did
        ob = outline[2]
        if op == "move":
            rep = plan_op(ws, [{"op": "move_piece", "handle": outline[1], "dx": r4(dx), "dy": r4(dy), "allow_overlap": True}])
            nb = changed_box(rep, outline[1], ob)
            if not nb:
                raise ValueError("There's no room to move it that way: on the plan it already touches " + blocker(rep) + ".")
            want = (dx, dy)
            dx, dy = (nb[0] + nb[2] - ob[0] - ob[2]) / 2, (nb[1] + nb[3] - ob[1] - ob[3]) / 2
            if abs(dx) < 0.001 and abs(dy) < 0.001 and not dz:  # clamped to nothing: no empty revision
                raise ValueError("There's no room to move it that way: on the plan it already touches " + blocker(rep) + ".")
            if abs(dx - want[0]) > 0.005 or abs(dy - want[1]) > 0.005:
                notes.append(f"it only had room to go {describe(dx, dy)} before it touches {blocker(rep)}")
            nbox = [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]
        else:
            side = {k: r4(d) for k, d in side.items() if abs(d) >= 0.001}
            rep = plan_op(ws, [{"op": "resize_piece", "handle": outline[1], "grow": side, "allow_overlap": True}])
            nb = changed_box(rep, outline[1], ob)
            if not nb:
                raise ValueError("There's no room to make it bigger that way: on the plan it already touches " + blocker(rep) + ".")
            real = {"E": nb[2] - ob[2], "W": ob[0] - nb[0], "N": nb[3] - ob[3], "S": ob[1] - nb[1]}
            if all(abs(t) < 0.001 for t in real.values()) and not zbox:  # clamped to nothing: no empty revision
                raise ValueError("There's no room to make it bigger that way: on the plan it already touches " + blocker(rep) + ".")
            for k in SIDES:
                if abs(real[k] - side.get(k, 0)) > 0.005:
                    notes.append(f"the plan only had room for {cm(real[k])} on the {dict(N='north', S='south', E='east', W='west')[k]} side")
            nbox = [box[0] - real["W"], box[1] - real["S"], box[2] + real["E"], box[3] + real["N"]]
        notes += [f"it now runs into {c.get('with')}" for c in rep.get("clashes", []) if not c.get("free")][:2]

    dx, dy = (nbox[0] + nbox[2] - box[0] - box[2]) / 2, (nbox[1] + nbox[3] - box[1] - box[3]) / 2
    resized = op == "resize" and planar  # its plan size changed (a height-only resize is just zbox)
    nz = [L0 + dz, H0 + dz] if dz else zbox or [L0, H0]
    if (resized or (is_part and planar)) and facing not in U and found["how"] != "rug":
        raise ValueError("This piece is turned at an angle; it can only be moved, not resized. Make an Edit can.")
    # Its height in its frame: world = P + S·y. A new low / high gives the new S and P (the piece's base moves with it).
    k_z = (nz[1] - nz[0]) / (H0 - L0) if H0 - L0 > 1e-6 else 1.0

    def heights(P, S, K=1.0):
        """(P', S') for a frame at P (world) with height scale S, under a factor K (its parents' scale) to the world."""
        if not (dz or zbox):
            return P, S
        if dz:
            return P + dz / K, S
        S2 = S * k_z
        return (nz[0] - (L0 - P * K) * k_z) / K, S2  # low stays the same point of the piece, scaled
    if param:  # a niche: change the numbers it's drawn from (across only; its depth is the wall's)
        (ia, sa), (io, so) = axes(facing)
        lo_d, hi_d = nbox[ia] - box[ia], nbox[ia + 2] - box[ia + 2]
        if sa < 0:
            lo_d, hi_d = -hi_d, -lo_d
        if abs((nbox[io + 2] - nbox[io]) - (box[io + 2] - box[io])) > 0.003 or abs(nbox[io] - box[io]) > 0.003:
            if abs(lo_d) < 0.001 and abs(hi_d) < 0.001 and not (dz or zbox):  # nothing left to change: no empty revision
                raise ValueError(f"The {label} is cut into its wall: it can slide along the wall or get wider or narrower, "
                                 "but not move out of it or deeper into it.")
            notes.append(f"its depth is set by the wall it's cut into, so only its width changed")
        # the current numbers come from the code; the plan box only says how far each edge moved
        if planar:
            text_probe, old = set_param(text, call, param, 0, 0, v)
            text, _ = set_param(text, call, param, old[0] + lo_d / si[0], old[1] + hi_d / si[0], v)
        if dz or zbox:  # its bottom and top move as far as the draft's (the item's height scale aside)
            sy_ = float(piece.get("sy") or 1)
            text_probe, old = set_param(text, call, param, 0, 0, v, "z")
            text, _ = set_param(text, call, param, old[0] + (nz[0] - L0) / sy_, old[1] + (nz[1] - H0) / sy_, v, "z")
    elif is_part:
        (ia, sa), (io, so) = axes(facing)
        pos = [float(t) for t in piece.get("pos") or [0, 0]]
        psc = [float(t) for t in piece.get("pscale") or [1, 1]]
        if resized:
            _, pa, s_a = solve(A[ia], pos[0], psc[0], si[0], sa, box[ia], box[ia + 2], nbox[ia], nbox[ia + 2])
            _, po, s_o = solve(A[io], pos[1], psc[1], si[1], so, box[io], box[io + 2], nbox[io], nbox[io + 2])
            pos, psc = [pa, po], [s_a, s_o]
        else:
            d = (dx, dy)
            pos = [pos[0] + sa * d[ia] / si[0], pos[1] + so * d[io] / si[1]]
        # its height: world = base + K·(py + ps·y), base / K from the item (and the part it sits in)
        fr = piece.get("frame") or {}
        K = float(piece.get("sy") or 1) * float(fr.get("scaleY") or 1)
        base = float(piece.get("py") or 0) + float(piece.get("sy") or 1) * float(fr.get("posY") or 0)
        py, ps = float(piece.get("posY") or 0), float(piece.get("pscaleY") or 1)
        if dz or zbox:  # the same sum as heights(), in the part's frame (P = base + K·py)
            P2, S2 = heights((base + K * py) / K, ps, K)
            py, ps = P2 - base / K, S2
        text = set_part(text, call, piece["part"], pos, psc, v, sh, py, ps)
    elif found["how"] == "rug":
        a = [arg_num(t, v) for t in call["args"][:4]]
        if planar:
            text = set_rug(text, call, [a[0] + nbox[0] - box[0], a[1] + nbox[1] - box[1], a[2] + nbox[2] - box[2], a[3] + nbox[3] - box[3]], v, sh)
            call = next(c for c in calls_on_line(text, found["line"]) if c["name"] == call["name"])
        if dz or zbox:
            old = sized_args(text, call)
            P0, S0 = float(piece.get("py") or 0), float(piece.get("sy") or 1)
            P1, S1 = heights(P0, S0)
            text = set_size(text, call, num_for(old[0], v) or 1, num_for(old[1], v) or 1, v, sh, S1, (num_for(old[3], v) or 0) + P1 - P0)
    else:
        a_new, s_new = [A[0] + dx, A[1] + dy], list(si)
        if rot:  # its back-centre swings round the centre of its plan box
            c, t = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), math.radians(rot)
            u, w = A[0] - c[0], A[1] - c[1]
            a_new = [c[0] + u * math.cos(t) - w * math.sin(t) + dx, c[1] + u * math.sin(t) + w * math.cos(t) + dy]
        if resized:  # plan = A + sign·S·u: the anchor moves and the scale changes
            (ia, sa), (io, so) = axes(facing)

            def item_axis(i_, sgn, s0):
                k = (nbox[i_ + 2] - nbox[i_]) / (box[i_ + 2] - box[i_])
                um = sgn * ((box[i_] + box[i_ + 2]) / 2 - A[i_]) / s0
                s1 = s0 * k
                return (nbox[i_] + nbox[i_ + 2]) / 2 - sgn * s1 * um, s1
            a_new = list(A)
            a_new[ia], s_new[0] = item_axis(ia, sa, si[0])
            a_new[io], s_new[1] = item_axis(io, so, si[1])
        P0, S0 = float(piece.get("py") or 0), float(piece.get("sy") or 1)
        P1, S1 = heights(P0, S0)
        if found["how"] == "table":
            e = table_entry(text, piece, v) or []
            lift0 = e[5] if len(e) > 5 else 0.0
            text = set_table(text, piece, a_new[0], a_new[1], s_new[0], s_new[1], v, label, S1, lift0 + P1 - P0)
        else:
            if abs(a_new[0] - A[0]) > 1e-4 or abs(a_new[1] - A[1]) > 1e-4:
                text = set_xy(text, call, a_new[0], a_new[1], v, sh)
                call = next(c for c in calls_on_line(text, found["line"]) if c["name"] == call["name"])
            if rot:
                text = set_facing(text, call, turned(facing_of(call["args"][facing_at(call)], v), rot), v, sh)
                call = next(c for c in calls_on_line(text, found["line"]) if c["name"] == call["name"])
            if resized or dz or zbox:
                old = sized_args(text, call)
                lift = (num_for(old[3], v) or 0) + P1 - P0 if (dz or zbox) else None
                text = set_size(text, call, s_new[0], s_new[1], v, sh, S1 if (dz or zbox) else None, lift)
    w0, d0 = box[2] - box[0], box[3] - box[1]
    w1, d1 = nbox[2] - nbox[0], nbox[3] - nbox[1]
    if resized:
        summary = f"{NAME}: {label} to {w1 * 100:.0f} × {d1 * 100:.0f} cm on plan (was {w0 * 100:.0f} × {d0 * 100:.0f})"
    elif rot:
        summary = (f"{NAME}: {label} turned {abs(rot):g}° {'anticlockwise' if rot > 0 else 'clockwise'}"
                   + (f" and moved {describe(dx, dy)}" if abs(dx) >= 0.005 or abs(dy) >= 0.005 else ""))
    elif planar:
        summary = f"{NAME}: {label} {describe(dx, dy)}"
    else:
        summary = f"{NAME}: {label}"
    if dz:
        summary += (" and" if planar else "") + f" {cm(dz)} {'up' if dz > 0 else 'down'}"
    elif zbox:
        summary += f"{',' if planar else ''} {(nz[1] - nz[0]) * 100:.0f} cm tall (was {(H0 - L0) * 100:.0f})"
    if not outline:
        notes.append("it isn't drawn on the 2D plan (3D-only), so only the 3D changed")
    if (resized or zbox) and not is_part and piece.get("hasParts"):
        notes.append("the things on it were stretched with it; move or resize them on their own if they look off")
    if is_part and piece.get("hostBox") and not param:
        hb = [float(t) for t in piece["hostBox"]]
        if nbox[0] < hb[0] - 0.01 or nbox[2] > hb[2] + 0.01 or nbox[1] < hb[1] - 0.01 or nbox[3] > hb[3] + 0.01:
            notes.append(f"the {label} now hangs past the edge of {piece.get('hostLabel') or 'the piece it sits on'}")
    write_furnish(ws, text)
    rot0 = float(piece.get("rot") or 0)
    record_origin(ws, v, label, box, rot0, nbox, rot0 + math.radians(rot), [L0, H0], nz)
    if (breaks := E.lock_breaks(ws, "")):  # a settled decision: saved on purpose (Accept), its lock suspended; Undo restores it
        E.lock_breaks(ws, " ".join(l["names"][0] for l, _ in breaks), record=True)
        notes.append("this changes a settled design decision (" + "; ".join(l["what"][:90] for l, _ in breaks)
                     + "), so that lock is now suspended; Undo puts it back")
    man = save(ws, summary + (" (" + "; ".join(notes) + ")" if notes else ""))
    on_plan = planar and outline and (own or block or outline[0] == "lines")
    return {"rev": man["rev"], "changed": sorted(ws.changed), "summary": summary, "notes": notes, "op": op,
            "plan": bool(on_plan), "outline": (own or block) and outline[1], "drawn": outline and outline[0], "lines": outline[1] if outline and outline[0] == "lines" else None,
            "moved": [r4(dx), r4(dy)], "rotated": rot, "box": [r4(t) for t in nbox], "z": [r4(t) for t in nz],
            "how": found["how"], "sync": man.get("sync")}
