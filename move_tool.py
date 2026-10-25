"""Move / Resize: the viewer's Move button drags a piece in 3D or on the 2D plan, or pulls an edge to resize it.

POST /api/edit-ai/transform does it without any model call. It makes the same two edits Edit AI's tools make, so the
3D and the 2D change together: furnish.js (the piece's item( x, y literal; a size as sized(item(...), across, out); a
part inside a piece, e.g. the espresso machine on the coffee bar, as its own position / scale) and, when the piece is
drawn on the plan, the version's DXF through edit_ai_dxf.py's move_piece / resize_piece. The plan's answer (it may
clamp a resize to the free span) is what the 3D gets, so both views move by the same metres. Then edit_ai.save()
rebuilds the model and drawing, stores the live override and git-syncs, exactly like an Edit AI change (and Edit AI's
Undo takes it back).

Request: {version, rev, op: "move" | "resize", piece: {...}, dx, dy (move) | box (resize: the new plan box)}
piece (from move.js, read off the 3D scene): kind "item" | "part"; x, y, facing of its item( call; lines: furnish.js
line numbers on the call stack when item() ran; scale [across, out] (sized()); box [x0, y0, x1, y1] its plan box now;
low / high (m) its lowest / highest point; label; for a part: part (its p.label text), pos [x, z] and pscale [x, z] in
the item's frame, hostBox the whole item's plan box.

What stays 3D-only (docs/edit-ai/when-2d-needed.md): pieces whose lowest point is above head height, lights, AC units,
wall-hung things and anything with no 2furni outline under it. A floor piece that is only one part of an outline
drawn round several pieces is refused (the plan can't move half an outline): Make an Edit can.
"""
import json, re

import edit_ai as E

HEAD_HEIGHT = 1.5
U = {"S": (1, 0), "N": (-1, 0), "E": (0, 1), "W": (0, -1)}   # local x (across) in plan
F = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}   # local z (out from the wall) in plan
CALL = re.compile(r"\b(sized\(\s*)?\b(item|rug|plant|art|ac|sconce|pendant)\(")
NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
SIDES = ("N", "S", "E", "W")


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
    """[(kind, start of the name, '(' index, ')' index, args, wrapped)] for each placing call that starts on line n."""
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


def find_call(text, piece):
    """The furnish.js call that placed the piece: {line, call, how} or raises ValueError in plain words."""
    x, y = float(piece["x"]), float(piece["y"])
    lines = [int(n) for n in piece.get("lines") or [] if 0 < int(n) <= text.count("\n") + 1]
    L = text.splitlines()
    for n in lines:  # 1. a literal call: item(2.02, 9.015, ... / ac(14.852, 8.79, ... / rug(x0, y0, x1, y1) centred on x, y
        for c in calls_on_line(text, n):
            a = [t.strip() for t in c["args"]]
            if c["kind"] == "rug" and len(a) >= 4 and all(NUM.match(t) for t in a[:4]):
                if near((float(a[0]) + float(a[2])) / 2, x) and near((float(a[1]) + float(a[3])) / 2, y):
                    return {"line": n, "call": c, "how": "rug"}
            elif len(a) >= 2 and NUM.match(a[0]) and NUM.match(a[1]) and near(float(a[0]), x) and near(float(a[1]), y):
                return {"line": n, "call": c, "how": "literal"}
    for n in lines:  # 2. inside `for (const v of [a, b])`: unrolled first (see unroll)
        if helper_def(L[n - 1]):
            continue
        for h in range(n - 1, max(-1, n - 5), -1):
            m = E.LOOP.search(L[h])
            if m and re.search(r"\b(?:item|rug|plant|art|ac|sconce|pendant)\(\s*[^,]*\b" + m[1] + r"\b", L[n - 1]):
                return {"line": n, "loop": h + 1, "var": m[1], "how": "loop"}
    for n in lines:  # 3. one call with worked-out coordinates (item(hb, 7.0 ...): its x, y become literals
        if helper_def(L[n - 1]) or re.search(r"\bfor\s*\(", L[n - 1]):
            continue
        cs = [c for c in calls_on_line(text, n) if c["kind"] != "rug"]
        if len(cs) == 1 and len(cs[0]["args"]) >= 3:
            fa = cs[0]["args"][2].strip() if cs[0]["kind"] not in ("plant", "pendant") else '"S"'
            if fa.strip('"') == piece.get("facing") or not re.fullmatch(r'"[NSEW]"', fa):
                return {"line": n, "call": cs[0], "how": "expr"}
    raise ValueError("I can't find the line of code that places this piece (it's built by shared code), so it can't be "
                     "moved with Move. Make an Edit can do it.")


def unroll(text, hdr, var):
    """`for (const v of [a, b]) { body }` (or one statement) written out once per value, v replaced by it."""
    s = line_start(text, hdr)
    m = E.LOOP.search(text, s)
    if not m or m[1] != var:
        raise ValueError("loop changed under me")
    vals = [t.strip() for t in m[2].split(",") if t.strip()]
    k = m.end()
    while text[k] in " \t":
        k += 1
    if text[k] == "{":
        end = close_paren(text, k)
        body, stop = text[k + 1:end], end + 1
    else:  # one statement, to its ';'
        j, depth = k, 0
        while j < len(text):
            if text[j] in "([{":
                depth += 1
            elif text[j] in ")]}":
                depth -= 1
            elif text[j] == ";" and depth == 0:
                break
            j += 1
        body, stop = text[k:j + 1], j + 1
    if re.search(r"\bfor\s*\(|\b(?:const|let)\s+" + var + r"\b", body):
        raise ValueError("this piece is placed in a loop I can't safely split; Make an Edit can do it")
    rx = re.compile(r"(?<![\w.$])" + var + r"(?![\w$])(?!\s*:)")
    ind = re.match(r"[ \t]*", text[s:]).group(0)
    lead = text[s:m.start()]  # e.g. `if (KC) ` before the for: kept on every copy
    comment = ""
    tail_nl = text.find("\n", stop)
    rest = text[stop:tail_nl if tail_nl >= 0 else len(text)]
    if rest.strip().startswith("//"):
        comment, stop = "  " + rest.strip(), (tail_nl if tail_nl >= 0 else len(text))
    blocks = []
    for n_, v in enumerate(vals):
        b = rx.sub(v, body)
        b_lines = [l.strip() for l in b.strip("\n").split("\n") if l.strip() and not (n_ and l.strip().startswith("//"))]
        if lead.strip():
            blocks.append(ind + lead.strip() + " { " + " ".join(b_lines) + " }")
        else:
            blocks += [ind + l for l in b_lines]
    if comment:
        blocks[0] += comment
    return text[:s] + "\n".join(blocks) + text[stop:], len(blocks)


# --- The plan outline under a piece ---------------------------------------------------------------------------------
def outlines_near(ws, box, pad=0.3):
    code, q = E.run([E.dwg_python(), str(E.ROOT / "edit_ai_dxf.py"), "query", str(ws.dxf()), f"--origin={E.ORIGIN[0]},{E.ORIGIN[1]}",
                     f"--bbox={box[0] - pad},{box[1] - pad},{box[2] + pad},{box[3] + pad}", "--layers=2furni,2 furni", "--limit", "400"],
                    timeout=90)
    out = []
    for d in json.loads(q).get("entities", []):
        ps = d.get("points") or ([d["bbox"][:2], d["bbox"][2:]] if d.get("bbox") else [])
        if d["type"] == "LWPOLYLINE" and (len(ps) >= 4 or d.get("n_points", 0) >= 4):
            xs, ys = [p[0] for p in ps], [p[1] for p in ps]
            b = (min(xs), min(ys), max(xs), max(ys))
            if (b[2] - b[0]) * (b[3] - b[1]) >= 0.02:
                out.append({"handle": d["handle"], "box": b})
    return out


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def outline_of(ws, piece):
    """(handle, box) of the 2furni outline drawn for this piece, None for a 3D-only one; ValueError for a shared one."""
    box, low = [float(v) for v in piece["box"]], float(piece.get("low", 0))
    if low >= HEAD_HEIGHT or piece.get("light"):
        return None
    best, best_iou, cover = None, 0.0, None
    for o in outlines_near(ws, box):
        i = inter(box, o["box"])
        iou = i / (area(box) + area(o["box"]) - i) if i else 0.0
        if iou > best_iou:
            best, best_iou = o, iou
        if area(box) and i / area(box) >= 0.8 and (cover is None or area(o["box"]) < area(cover["box"])):
            cover = o
    if best and best_iou >= 0.45:
        return best["handle"], best["box"]
    if cover and low < 0.3:
        raise ValueError(f"On the plan this piece is drawn as part of one outline with the pieces next to it, so moving or "
                         f"resizing it alone would split that outline. Make an Edit can do it.")
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


def write_furnish(ws, new_text, note):
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


def set_xy(text, call, x, y):
    a = call["args"]
    lead0 = re.match(r"\s*", a[0]).group(0)
    lead1 = re.match(r"\s*", a[1]).group(0)
    new_args = [lead0 + fmt(x), lead1 + fmt(y)] + a[2:]
    return text[:call["open"] + 1] + ",".join(new_args) + text[call["close"]:]


def set_rug(text, call, b):
    a = call["args"]
    new = [re.match(r"\s*", a[k]).group(0) + fmt(b[k]) for k in range(4)] + a[4:]
    return text[:call["open"] + 1] + ",".join(new) + text[call["close"]:]


def set_size(text, call, sa, so):
    """Wrap (or rewrap, or unwrap) the call in sized(..., across, out)."""
    one = abs(sa - 1) < 1e-4 and abs(so - 1) < 1e-4
    if call["sized"]:
        so_open = text.index("(", call["outer"])
        so_close = close_paren(text, so_open)
        inner = text[call["name"]:call["close"] + 1]
        rep = inner if one else f"sized({inner}, {fmt(sa)}, {fmt(so)})"
        return text[:call["outer"]] + rep + text[so_close + 1:]
    if one:
        return text
    inner = text[call["name"]:call["close"] + 1]
    return text[:call["name"]] + f"sized({inner}, {fmt(sa)}, {fmt(so)})" + text[call["close"] + 1:]


def part_block(text, call, label):
    """(start of the p.label("<label>", p => { line, offset just after its '{') inside the item's call."""
    seg = text[call["open"]:call["close"]]
    m = re.search(r"\b\w+\.label\(\s*\"" + re.escape(label) + r"\"\s*,\s*(\w+)\s*=>\s*\{", seg)
    if not m:
        raise ValueError(f"I can't find where the {label} is built, so it can't be moved with Move. Make an Edit can do it.")
    return call["open"] + m.end(), m[1]


MOVE_LINE = re.compile(r"[ \t]*\w+\.g\.position\.set\([^)]*\);\s*\w+\.g\.scale\.set\([^)]*\);\s*// Move tool[^\n]*\n")


def set_part(text, call, label, pos, sc):
    at, pv = part_block(text, call, label)
    nl = text.index("\n", at) + 1
    rest = text[nl:]
    m = MOVE_LINE.match(rest)
    ind = re.match(r"[ \t]*", rest).group(0) or "      "
    line = (f"{ind}{pv}.g.position.set({fmt(pos[0])}, 0, {fmt(pos[1])}); {pv}.g.scale.set({fmt(sc[0])}, 1, {fmt(sc[1])});"
            f"  // Move tool: where this part sits / how big, in the piece's frame\n")
    if abs(pos[0]) < 1e-4 and abs(pos[1]) < 1e-4 and abs(sc[0] - 1) < 1e-4 and abs(sc[1] - 1) < 1e-4:
        line = ""
    return text[:nl] + line + (rest[m.end():] if m else rest)


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
    try:
        return json.loads(out.split("\nfurnish.js items within")[0])
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


def transform(req):
    v = req.get("version") or "main"
    if v not in E.VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    if v == "as-built":
        raise ValueError("As-built is the survey of the flat as it stands; it can't be changed.")
    op, piece = req.get("op"), req.get("piece") or {}
    if op not in ("move", "resize"):
        raise ValueError("op must be move or resize")
    facing = piece.get("facing")
    ws = E.Workspace(v)
    ws.allow_as_built = False
    ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = False, False, {}, {}, [], []
    cur = ws.man and ws.man.get("rev")
    if req.get("rev") is not None and req.get("rev") != cur:
        raise ValueError("This page is behind the latest change to this version. Reload and try again.")
    text = ws.text("furnish.js")
    sc_ = E.version_scope(text, v)
    found = find_call(text, piece)
    if found["how"] == "loop":
        text, _ = unroll(text, found["loop"], found["var"])
        lines = [n for n in range(found["loop"], found["loop"] + 12)]
        found = find_call(text, {**piece, "lines": lines})
        if found["how"] != "literal":
            raise ValueError("I couldn't split this piece out of the loop that places it. Make an Edit can do it.")
    if sc_[found["line"] - 1] is False and found["how"] != "loop":
        raise ValueError("That code belongs to another plan version.")
    call = found["call"]
    label = piece.get("label") or "piece"
    is_part = piece.get("kind") == "part"
    notes = []
    box = [float(t) for t in piece["box"]]
    outline = None if piece.get("noPlan") else outline_of(ws, piece)
    x, y = float(piece["x"]), float(piece["y"])
    si = [float(t) for t in piece.get("scale") or [1, 1]]

    if op == "move":
        dx, dy = float(req.get("dx") or 0), float(req.get("dy") or 0)
        if abs(dx) < 0.001 and abs(dy) < 0.001:
            raise ValueError("That didn't move it.")
        if outline:
            ops = [{"op": "move_piece", "handle": outline[0], "dx": r4(dx), "dy": r4(dy)}]  # its details / inner outlines go too
            rep = plan_op(ws, ops)
            nb = changed_box(rep, outline[0], outline[1])
            if not nb:
                raise ValueError("There's no room to move it that way: on the plan it already touches " + blocker(rep) + ".")
            want = (dx, dy)
            dx, dy = (nb[0] + nb[2] - outline[1][0] - outline[1][2]) / 2, (nb[1] + nb[3] - outline[1][1] - outline[1][3]) / 2
            if abs(dx - want[0]) > 0.005 or abs(dy - want[1]) > 0.005:
                notes.append(f"it only had room to go {describe(dx, dy)} before it touches {blocker(rep)}")
            notes += [f"it now runs into {c.get('with')}" for c in rep.get("clashes", []) if not c.get("free")][:2]
        if is_part:
            if facing not in U:
                raise ValueError("This piece is turned at an angle; Move can't shift its parts. Make an Edit can.")
            (ia, sa), (io, so) = axes(facing)
            d = (dx, dy)
            pos = [float(t) for t in piece.get("pos") or [0, 0]]
            psc = [float(t) for t in piece.get("pscale") or [1, 1]]
            pos = [pos[0] + sa * d[ia] / si[0], pos[1] + so * d[io] / si[1]]
            text = set_part(text, call, piece["part"], pos, psc)
            nb3 = [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]
        elif found["how"] == "rug":
            a = [float(t) for t in call["args"][:4]]
            text = set_rug(text, call, [a[0] + dx, a[1] + dy, a[2] + dx, a[3] + dy])
        else:
            text = set_xy(text, call, x + dx, y + dy)
        summary = f"Move: {label} {describe(dx, dy)}"
        res_d = [r4(dx), r4(dy)]
    else:
        nbox = [float(t) for t in req["box"]]
        if nbox[2] - nbox[0] < 0.03 or nbox[3] - nbox[1] < 0.02:
            raise ValueError("That's too small to be a piece.")
        side = {"E": nbox[2] - box[2], "W": box[0] - nbox[0], "N": nbox[3] - box[3], "S": box[1] - nbox[1]}
        side = {k: r4(d) for k, d in side.items() if abs(d) >= 0.001}
        if not side:
            raise ValueError("That didn't change its size.")
        if outline:
            rep = plan_op(ws, [{"op": "resize_piece", "handle": outline[0], "grow": side}])
            nb = changed_box(rep, outline[0], outline[1])
            if not nb:
                raise ValueError("There's no room to make it bigger that way: on the plan it already touches " + blocker(rep) + ".")
            ob = outline[1]
            if nb:  # what the plan really did (it keeps a piece inside its free span)
                real = {"E": nb[2] - ob[2], "W": ob[0] - nb[0], "N": nb[3] - ob[3], "S": ob[1] - nb[1]}
                for k in SIDES:
                    if abs(real[k] - side.get(k, 0)) > 0.005:
                        notes.append(f"the plan only had room for {cm(real[k])} on the {dict(N='north', S='south', E='east', W='west')[k]} side")
                side = {k: d for k, d in real.items() if abs(d) >= 0.0005}
            notes += [f"it now runs into {c.get('with')}" for c in rep.get("clashes", []) if not c.get("free")][:2]
            nbox = [box[0] - side.get("W", 0), box[1] - side.get("S", 0), box[2] + side.get("E", 0), box[3] + side.get("N", 0)]
        if found["how"] == "rug":
            a = [float(t) for t in call["args"][:4]]
            text = set_rug(text, call, [a[0] - side.get("W", 0), a[1] - side.get("S", 0), a[2] + side.get("E", 0), a[3] + side.get("N", 0)])
        else:
            if facing not in U:
                raise ValueError("This piece is turned at an angle; Move can only move it, not resize it. Make an Edit can.")
            (ia, sa), (io, so) = axes(facing)
            A = [x, y]
            if is_part:
                pos = [float(t) for t in piece.get("pos") or [0, 0]]
                psc = [float(t) for t in piece.get("pscale") or [1, 1]]
                _, pa, s_a = solve(A[ia], pos[0], psc[0], si[0], sa, box[ia], box[ia + 2], nbox[ia], nbox[ia + 2])
                _, po, s_o = solve(A[io], pos[1], psc[1], si[1], so, box[io], box[io + 2], nbox[io], nbox[io + 2])
                text = set_part(text, call, piece["part"], [pa, po], [s_a, s_o])
            else:
                # item: plan = A + sign·S·u (P = 0): the anchor moves, the scale changes
                def item_axis(i_, sgn, s0):
                    k = (nbox[i_ + 2] - nbox[i_]) / (box[i_ + 2] - box[i_])
                    um = sgn * ((box[i_] + box[i_ + 2]) / 2 - A[i_]) / s0
                    s1 = s0 * k
                    return (nbox[i_] + nbox[i_ + 2]) / 2 - sgn * s1 * um, s1
                a_new = list(A)
                a_new[ia], s_a = item_axis(ia, sa, si[0])
                a_new[io], s_o = item_axis(io, so, si[1])
                if found["how"] == "literal" and (abs(a_new[0] - x) > 1e-4 or abs(a_new[1] - y) > 1e-4) or found["how"] == "expr":
                    text = set_xy(text, call, a_new[0], a_new[1])
                    call = next(c for c in calls_on_line(text, found["line"]) if c["kind"] == call["kind"])
                text = set_size(text, call, s_a, s_o)
        w0, d0 = box[2] - box[0], box[3] - box[1]
        w1, d1 = nbox[2] - nbox[0], nbox[3] - nbox[1]
        summary = f"Resize: {label} to {w1 * 100:.0f} × {d1 * 100:.0f} cm on plan (was {w0 * 100:.0f} × {d0 * 100:.0f})"
        nb3 = nbox
        res_d = None
    if not outline:
        notes.append("it isn't drawn on the 2D plan (3D-only), so only the 3D changed")
    if op == "resize" and not is_part and piece.get("hasParts"):
        notes.append("the things on it were stretched with it; move or resize them on their own if they look off")
    if is_part and piece.get("hostBox"):
        hb = [float(t) for t in piece["hostBox"]]
        b3 = nb3 if op == "resize" else nb3
        if b3[0] < hb[0] - 0.01 or b3[2] > hb[2] + 0.01 or b3[1] < hb[1] - 0.01 or b3[3] > hb[3] + 0.01:
            host = piece.get("hostLabel") or "the piece it sits on"
            notes.append(f"the {label} now hangs past the edge of {host}")
    write_furnish(ws, text, summary)
    man = E.save(ws, summary + (" (" + "; ".join(notes) + ")" if notes else ""))
    return {"rev": man["rev"], "changed": sorted(ws.changed), "summary": summary, "notes": notes,
            "plan": bool(outline), "outline": outline and outline[0], "moved": res_d, "sync": man.get("sync")}
