"""Move and Resize: the viewer's Move and Resize button drags a piece in 3D or on the 2D plan, or pulls an edge to
resize it, and saves only when the user presses Accept (move.js keeps the change as a draft until then).

POST /api/edit-ai/transform does it without any model call. It makes the same two edits Edit AI's tools make, so the
3D and the 2D change together: furnish.js (the piece's item( x, y; a size as sized(item(...), across, out); a part
inside a piece, e.g. the espresso machine on the coffee bar, as its own position / scale; a part drawn from numbers in
its piece's code, e.g. a TV-wall niche, by changing those numbers) and, when the piece is drawn on the plan, the
version's DXF through edit_ai_dxf.py's move_piece / resize_piece. The plan's answer (it may clamp a resize to the free
span) is what the 3D gets, so both views move by the same metres. Then edit_ai.save() rebuilds the model and drawing,
stores the live override and git-syncs, exactly like an Edit AI change (and Edit AI's Undo takes it back).

One version's change stays in that version (docs/edit-ai/version-isolation.md): a number on a line other versions
also run becomes `version === "<v>" ? new : old`; a piece a loop or shared code places gets a version-guarded line in
furnish.js's MOVED table; and before saving, other_versions_changed() must find every other version unchanged.

Request: {version, rev, op: "move" | "resize", piece: {...}, dx, dy (move) | box (resize: the new plan box)}
piece (from move.js, read off the 3D scene): kind "item" | "part"; x, y, facing of its item( call; anchor: where the
item stands now; lines: furnish.js line numbers on the call stack when item() ran; twins: pieces placed with the same
x, y, facing; scale [across, out] (sized()); box [x0, y0, x1, y1] its plan box now; low / high (m) its lowest /
highest point; label; for a part: part (its p.label text), pos [x, z] and pscale [x, z] in its parent's frame, frame
(where that parent sits in the item's frame, for a part inside a part), param (a part drawn from numbers), hostBox.

What stays 3D-only (docs/edit-ai/when-2d-needed.md): pieces whose lowest point is above head height, lights, AC units,
wall-hung things and anything with no 2furni outline under it. A floor piece drawn on the plan only inside one outline
round several pieces (the dining set) moves in 3D only, and only while it stays inside that outline.
"""
import json, re

import edit_ai as E

NAME = "Move and Resize"
HEAD_HEIGHT = 1.5
U = {"S": (1, 0), "N": (-1, 0), "E": (0, 1), "W": (0, -1)}   # local x (across) in plan
F = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}   # local z (out from the wall) in plan
CALL = re.compile(r"\b(sized\(\s*)?\b(item|rug|plant|art|ac|sconce|pendant)\(")
NUM = re.compile(r"^-?\d+(?:\.\d+)?$")
SIDES = ("N", "S", "E", "W")
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


def set_arg(a, new, v, shared):
    """The arg rewritten to `new` for version v only: a gate on a line other versions run, a plain number otherwise."""
    lead = re.match(r"\s*", a).group(0)
    g = gated(a, v)
    if g:
        return lead + f'version === "{v}" ? {fmt(new)} : {g[1]}'
    if not shared:
        return lead + fmt(new)
    return lead + f'version === "{v}" ? {fmt(new)} : {a.strip()}'


def find_call(text, piece, v):
    """The furnish.js call that placed the piece: {line, call, how} (how: literal / rug / expr / spread / table)."""
    x, y = float(piece["x"]), float(piece["y"])
    lines = [int(n) for n in piece.get("lines") or [] if 0 < int(n) <= text.count("\n") + 1]
    L = text.splitlines()
    if not piece.get("moved"):
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
            if len(a) >= 3 and cs[0]["kind"] not in ("plant", "pendant") and re.fullmatch(r'\s*"[NSEW]"\s*', a[2]) \
                    and a[2].strip().strip('"') == piece.get("facing"):
                return {"line": n, "call": cs[0], "how": "expr"}
    # 3. built in a loop or by shared code: no line of its own, so this version's MOVED table entry
    if int(piece.get("twins") or 1) > 1:
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
    """("own", handle, box) of the 2furni outline drawn for this piece; ("shared", handle, box) when it is drawn only
    inside one outline round several pieces; None for a 3D-only one."""
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
        return "own", best["handle"], best["box"]
    if cover and low < 0.3:
        return "shared", cover["handle"], cover["box"]
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


def set_size(text, call, sa, so, v, shared):
    """Wrap (or rewrap, or unwrap) the call in sized(..., across, out), for version v only on a shared line."""
    inner = text[call["name"]:call["close"] + 1]
    if call["sized"]:
        so_open = text.index("(", call["outer"])
        so_close = close_paren(text, so_open)
        olds = [t.strip() for t in split_args(text[so_open + 1:so_close])[1:3]]
        start, end = call["outer"], so_close + 1
    else:
        olds, start, end = ["1", "1"], call["name"], call["close"] + 1

    def one(old, new):
        if not shared and not gated(old, v):
            return fmt(new)
        g = gated(old, v)
        rest = g[1] if g else old
        return rest if abs(new - 1) < 1e-4 and rest == "1" else f'version === "{v}" ? {fmt(new)} : {rest}'
    args = [one(olds[0], sa), one(olds[1], so)]
    rep = inner if args == ["1", "1"] else f"sized({inner}, {args[0]}, {args[1]})"
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


def set_part(text, call, label, pos, sc, v, shared):
    at, pv = part_block(text, call, label)
    nl = text.index("\n", at) + 1
    k, mine = nl, None
    while (m := PART_LINE.match(text, k)):  # earlier lines: an older version's, or the shared one
        if (m[1] == v) if shared else (m[1] is None):
            mine = m
        k = m.end()
    ind = re.match(r"[ \t]*", text[k:]).group(0) or "      "
    move = f"{pv}.g.position.set({fmt(pos[0])}, 0, {fmt(pos[1])}){', ' if shared else '; '}{pv}.g.scale.set({fmt(sc[0])}, 1, {fmt(sc[1])});"
    line = (f'{ind}{f"if (version === {json.dumps(v)}) " if shared else ""}{move}'
            f"  // Move and Resize: where this part sits / how big, in the piece's frame\n")
    if mine:
        return text[:mine.start()] + line + text[mine.end():]
    return text[:k] + line + text[k:]


def set_table(text, piece, x, y, sa, so, v, label):
    """This version's MOVED line for a piece a loop or shared code places: where it goes and how big."""
    f = piece.get("facing")
    key = f"{fmt(piece['x'])},{fmt(piece['y'])},{f if isinstance(f, str) else json.dumps(f)}"
    rx = re.compile(r'^[ \t]*if \(version === "' + re.escape(v) + r'"\) MOVED\["' + re.escape(key) + r'"\] = \[[^\]]*\];[^\n]*\n', re.M)
    decl = re.search(r"^([ \t]*)const MOVED = \{\};[^\n]*\n", text, re.M)
    same = near(x, float(piece["x"]), 1e-4) and near(y, float(piece["y"]), 1e-4) and near(sa, 1, 1e-4) and near(so, 1, 1e-4)
    line = "" if same else (f'{decl[1]}if (version === "{v}") MOVED["{key}"] = [{fmt(x)}, {fmt(y)}, {fmt(sa)}, {fmt(so)}];'
                            f"  // Move and Resize: {re.sub(r'[^\w ,.()-]', '', label)[:50]}\n")
    if (m := rx.search(text)):
        return text[:m.start()] + line + text[m.end():]
    return text[:decl.end()] + line + text[decl.end():]


# --- A part drawn from numbers in its piece's code (p.label(..., param)) -------------------------------------------
def js_list(v):
    return "[" + ", ".join(js_list(e) for e in v) + "]" if isinstance(v, list) else fmt(v)


def set_param(text, call, param, lo, hi, v):
    """Set across lo..hi (the item's local x) in the array the part is drawn from, e.g. tall[1] = [lo, hi]."""
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
    i0, i1 = param["x"]
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
    v = E.plan_version(req.get("version"))
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
    text = f0 = ws.text("furnish.js")
    shared = scopes(text, v)
    found = find_call(text, piece, v)
    if found["line"] and E.version_scope(text, v)[found["line"] - 1] is False:
        raise ValueError("That code belongs to another plan version.")
    call = found["call"]
    sh = shared(found["line"]) if found["line"] else True
    label = piece.get("label") or "piece"
    is_part = piece.get("kind") == "part"
    param = piece.get("param") if is_part else None
    if is_part and found["how"] not in ("literal", "expr", "spread"):
        raise ValueError(f"The {label} sits in a piece built by shared code, " + CANT)
    notes = []
    box = [float(t) for t in piece["box"]]
    outline = None if piece.get("noPlan") or param else outline_of(ws, piece)  # a niche is cut into a wall: not on the plan
    own = outline and outline[0] == "own"
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

    if op == "move":
        dx, dy = float(req.get("dx") or 0), float(req.get("dy") or 0)
        if abs(dx) < 0.001 and abs(dy) < 0.001:
            raise ValueError("That didn't move it.")
        nbox = [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]
    else:
        nbox = [float(t) for t in req["box"]]
        if nbox[2] - nbox[0] < min(0.03, box[2] - box[0]) - 1e-4 or nbox[3] - nbox[1] < min(0.02, box[3] - box[1]) - 1e-4:
            raise ValueError("That's too small to be a piece.")
        side = {"E": nbox[2] - box[2], "W": box[0] - nbox[0], "N": nbox[3] - box[3], "S": box[1] - nbox[1]}
        if not any(abs(d) >= 0.001 for d in side.values()):
            raise ValueError("That didn't change its size.")

    if outline and outline[0] == "shared":  # drawn inside one outline round several pieces: 3D only, inside it
        if area(nbox) and inter(nbox, outline[2]) / area(nbox) < 0.8:
            raise ValueError("On the plan this piece is drawn inside one outline with the pieces next to it, so it can only "
                             "be adjusted within that outline. Make an Edit can redraw the plan.")
        notes.append("on the plan it's drawn as part of a group outline, so only the 3D changed")
    elif own:  # the plan moves first; the 3D follows what the plan really did
        ob = outline[2]
        if op == "move":
            rep = plan_op(ws, [{"op": "move_piece", "handle": outline[1], "dx": r4(dx), "dy": r4(dy)}])
            nb = changed_box(rep, outline[1], ob)
            if not nb:
                raise ValueError("There's no room to move it that way: on the plan it already touches " + blocker(rep) + ".")
            want = (dx, dy)
            dx, dy = (nb[0] + nb[2] - ob[0] - ob[2]) / 2, (nb[1] + nb[3] - ob[1] - ob[3]) / 2
            if abs(dx - want[0]) > 0.005 or abs(dy - want[1]) > 0.005:
                notes.append(f"it only had room to go {describe(dx, dy)} before it touches {blocker(rep)}")
            nbox = [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]
        else:
            side = {k: r4(d) for k, d in side.items() if abs(d) >= 0.001}
            rep = plan_op(ws, [{"op": "resize_piece", "handle": outline[1], "grow": side}])
            nb = changed_box(rep, outline[1], ob)
            if not nb:
                raise ValueError("There's no room to make it bigger that way: on the plan it already touches " + blocker(rep) + ".")
            real = {"E": nb[2] - ob[2], "W": ob[0] - nb[0], "N": nb[3] - ob[3], "S": ob[1] - nb[1]}
            for k in SIDES:
                if abs(real[k] - side.get(k, 0)) > 0.005:
                    notes.append(f"the plan only had room for {cm(real[k])} on the {dict(N='north', S='south', E='east', W='west')[k]} side")
            nbox = [box[0] - real["W"], box[1] - real["S"], box[2] + real["E"], box[3] + real["N"]]
        notes += [f"it now runs into {c.get('with')}" for c in rep.get("clashes", []) if not c.get("free")][:2]

    dx, dy = (nbox[0] + nbox[2] - box[0] - box[2]) / 2, (nbox[1] + nbox[3] - box[1] - box[3]) / 2
    resized = op == "resize"
    if (resized or is_part) and facing not in U and found["how"] != "rug":
        raise ValueError("This piece is turned at an angle; it can only be moved, not resized. Make an Edit can.")
    if param:  # a niche: change the numbers it's drawn from (across only; its depth is the wall's)
        (ia, sa), (io, so) = axes(facing)
        lo_d, hi_d = nbox[ia] - box[ia], nbox[ia + 2] - box[ia + 2]
        if sa < 0:
            lo_d, hi_d = -hi_d, -lo_d
        if abs((nbox[io + 2] - nbox[io]) - (box[io + 2] - box[io])) > 0.003 or abs(nbox[io] - box[io]) > 0.003:
            notes.append(f"its depth is set by the wall it's cut into, so only its width changed")
        # the current numbers come from the code; the plan box only says how far each edge moved
        text_probe, old = set_param(text, call, param, 0, 0, v)
        text, _ = set_param(text, call, param, old[0] + lo_d / si[0], old[1] + hi_d / si[0], v)
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
        text = set_part(text, call, piece["part"], pos, psc, v, sh)
    elif found["how"] == "rug":
        a = [arg_num(t, v) for t in call["args"][:4]]
        text = set_rug(text, call, [a[0] + nbox[0] - box[0], a[1] + nbox[1] - box[1], a[2] + nbox[2] - box[2], a[3] + nbox[3] - box[3]], v, sh)
    else:
        a_new, s_new = [A[0] + dx, A[1] + dy], list(si)
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
        if found["how"] == "table":
            text = set_table(text, piece, a_new[0], a_new[1], s_new[0], s_new[1], v, label)
        else:
            if abs(a_new[0] - A[0]) > 1e-4 or abs(a_new[1] - A[1]) > 1e-4:
                text = set_xy(text, call, a_new[0], a_new[1], v, sh)
                call = next(c for c in calls_on_line(text, found["line"]) if c["kind"] == call["kind"])
            if resized:
                text = set_size(text, call, s_new[0], s_new[1], v, sh)
    w0, d0 = box[2] - box[0], box[3] - box[1]
    w1, d1 = nbox[2] - nbox[0], nbox[3] - nbox[1]
    summary = (f"{NAME}: {label} to {w1 * 100:.0f} × {d1 * 100:.0f} cm on plan (was {w0 * 100:.0f} × {d0 * 100:.0f})" if resized
               else f"{NAME}: {label} {describe(dx, dy)}")
    if not outline:
        notes.append("it isn't drawn on the 2D plan (3D-only), so only the 3D changed")
    if resized and not is_part and piece.get("hasParts"):
        notes.append("the things on it were stretched with it; move or resize them on their own if they look off")
    if is_part and piece.get("hostBox") and not param:
        hb = [float(t) for t in piece["hostBox"]]
        if nbox[0] < hb[0] - 0.01 or nbox[2] > hb[2] + 0.01 or nbox[1] < hb[1] - 0.01 or nbox[3] > hb[3] + 0.01:
            notes.append(f"the {label} now hangs past the edge of {piece.get('hostLabel') or 'the piece it sits on'}")
    if (others := E.other_versions_changed(f0, text, v)):
        raise ValueError(f"That change would also show in {', '.join(others)}, and a change in one version must stay in it, "
                         "so nothing was saved. Make an Edit can do it.")
    write_furnish(ws, text)
    if (breaks := E.lock_breaks(ws, "")):  # a settled decision: saved on purpose (Accept), its lock suspended; Undo restores it
        E.lock_breaks(ws, " ".join(l["names"][0] for l, _ in breaks), record=True)
        notes.append("this changes a settled design decision (" + "; ".join(l["what"][:90] for l, _ in breaks)
                     + "), so that lock is now suspended; Undo puts it back")
    man = E.save(ws, summary + (" (" + "; ".join(notes) + ")" if notes else ""))
    return {"rev": man["rev"], "changed": sorted(ws.changed), "summary": summary, "notes": notes, "op": op,
            "plan": bool(own), "outline": own and outline[1], "moved": [r4(dx), r4(dy)], "box": [r4(t) for t in nbox],
            "how": found["how"], "sync": man.get("sync")}
