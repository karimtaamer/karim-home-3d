#!/usr/bin/env python3
"""Engineer Electrical Plan's electrical layer (plan version id "light-power-plan", the Light and Power Plan until 24 Nov
2026) -> electrical-light-power-plan.json (that version only).

    python3 build_electrical_light_power_plan.py [--qa FILE]    # writes the JSON; --qa logs every placement (registered -> placed)

Source: ONLY the site engineer's latest drawings (Level Up): Power Plan S07 R01, Lighting Plan S08 R01 and the switches
sheet S09 (no revision number): every symbol he drew is one point, at his dimensions and heights, even where they differ
from Main; nothing of Main's electrical plan is carried over. The symbols of his first sheets, read off the PDFs room by
room, are POINTS in light_power_plan_points.py (positions registered onto Main's plan with reg = x_m = (px - a) / s,
y_m = (b - py) / s); R01_DROP / R01_CHANGE / R01_ADD there bring them to R01, and CIRCUIT / PLATES carry S09's switch
codes (each load's `circuit`, each plate's `codes` and gangs; plates sharing a code are two-way). Each point is placed:
  - along its wall / in the ceiling at his written dimension from Main's face of the wall he measured from, else where he
    drew it (registered);
  - wall points snapped onto Main's nearest face of the wall he drew them on, 3 mm proud (model-light-power-plan.js);
  - at the height in his box beside the symbol or his H.L= leader note.
Every point has status "engineer", src L / P / S or combos (light, power, switches sheet; the first letter placed it), pdf
(the symbol's registered centre on that R01 / S09 sheet, display points; pdf_light on S08 R01 when both), dim (what placed
it) and note (anything doubtful, and "R01: ..." for what his revision changed).
"""
import json, math, subprocess, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from light_power_plan_points import (POINTS, REG, SHEET_M, SHEET_DPI, R01_DROP, R01_CHANGE, R01_ADD,  # noqa: E402
                                     CODES, CIRCUIT, MOTOR, NO_CODE, PLATES)

OUT = ROOT / "electrical-light-power-plan.json"
M = json.loads(subprocess.run(["node", "-e", 'global.window={};require("./model-light-power-plan.js");'
                               'process.stdout.write(JSON.stringify(window.MODEL))'], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout)
CEIL = M["ceiling"]
QA = sys.argv[sys.argv.index("--qa") + 1] if "--qa" in sys.argv else None  # file for the per-point placement log
qa = []

# Main's wall faces (copied from build_electrical.py's face(), which runs its build when imported)
EDGES = []
for w in M["walls"]:
    for ring in [w["outer"], *w.get("holes", [])]:
        for i in range(len(ring)):
            EDGES.append((ring[i - 1], ring[i]))
DIRS = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}


def hit(x, y, wall, reach=6.0):
    """Distance from (x, y) to the first wall face towards `wall` (N/E/S/W), or None."""
    dx, dy = DIRS[wall]
    best = None
    for (ax, ay), (bx, by) in EDGES:
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((ax - x) * ey - (ay - y) * ex) / den
        u = ((ax - x) * dy - (ay - y) * dx) / den
        if 1e-6 < t < reach and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best):
            best = t
    return best


def face(x, y, wall, proud=0.003):
    t = hit(x, y, wall)
    if t is None:
        raise SystemExit(f"no wall {wall} of ({x}, {y})")
    dx, dy = DIRS[wall]
    return round(x + dx * (t - proud), 4), round(y + dy * (t - proud), 4), t


def dimmed(x, y, r, log):
    """Apply the engineer's written dimensions r = [(wall, metres[, '@x..' / '@y..'])] from Main's faces."""
    for spec in r:
        wall, d = spec[0], spec[1]
        ox, oy = x, y
        if len(spec) > 2:
            k, v = spec[2][1], float(spec[2][2:])
            ox, oy = (v, y) if k == "x" else (x, v)
        t = hit(ox, oy, wall)
        if t is None:
            raise SystemExit(f"dimension: no wall {wall} of ({ox}, {oy})")
        fx, fy = ox + DIRS[wall][0] * t, oy + DIRS[wall][1] * t
        if wall in "WE":
            nx = fx + d if wall == "W" else fx - d
            log.append(f"x {x:.3f} -> {nx:.3f} ({nx - x:+.3f}) {wall} face {fx:.3f} + {d}")
            x = nx
        else:
            ny = fy + d if wall == "S" else fy - d
            log.append(f"y {y:.3f} -> {ny:.3f} ({ny - y:+.3f}) {wall} face {fy:.3f} + {d}")
            y = ny
    return x, y


NAMES = {  # default label head per type
    "spot": "Ceiling spot", "wpspot": "Waterproof ceiling spot", "pendant": "Pendant outlet", "sensor": "Motion sensor (MS)",
    "fan": "Ceiling exhaust fan", "ap": "Wi-Fi access point", "socket": "Socket", "wp": "Waterproof socket",
}
def sheet_pt(sheet, x, y):
    """metres -> the point on his R01 / S09 sheet (L: S08 R01, same frame as REG; P: S07 R01; S: S09; display points)"""
    lx, ly = x * REG["s"] + REG["a"], REG["b"] - y * REG["s"]
    if sheet == "L":
        return [round(lx, 1), round(ly, 1)]
    (a, b, c), (d, e, f) = SHEET_M[sheet]
    px, py = lx * 300 / 72, ly * 300 / 72
    k = 72 / SHEET_DPI
    return [round((a * px + b * py + c) * k, 1), round((d * px + e * py + f) * k, 1)]


P, issues, keyed = [], [], {}
count = Counter()
FIRST = {id(e) for e in POINTS}
for e in POINTS + R01_ADD:
    t = e["type"]
    cx, cy = e["reg"]
    regs = [(m[0], m[1]) for m in e["members"]] if e.get("members") else [(cx, cy)]
    for (rx, ry) in regs:
        pdf = sheet_pt(e["src"][0], rx, ry)
        log = []
        # the dimension fixes the cluster's (pair's) centre; each spot keeps its offset from it
        x, y = dimmed(cx, cy, e.get("r") or [], log)
        x, y = x + (rx - cx), y + (ry - cy)
        facing, snap = None, 0
        if e.get("wall"):
            wall, _, at = e["wall"].partition("@")  # "N@x7.4": the face found from x 7.4 (the point is under a window)
            if at:
                ox, oy = (float(at[1:]), y) if at[0] == "x" else (x, float(at[1:]))
                fx, fy, snap = face(ox, oy, wall)
                x, y = (x, fy) if wall in "NS" else (fx, y)
            else:
                x, y, snap = face(x, y, wall)
            facing = OPP[wall]
        elif e.get("facing"):  # on a wall Main's model doesn't have (the terrace parapets): as drawn
            facing = e["facing"]
            if snap > 0.25:
                issues.append(f"{e['room']} {t} {e.get('label', '')}: snap {snap:.2f} m to the {e['wall']} wall")
        count[t] += 1
        pid = f"{t}-{count[t]}"
        room = e["room"]
        lab = e.get("label") or f"{NAMES.get(t, t)} — {room.lower()}"
        h = e.get("h", CEIL)
        d = {"id": e.get("id", pid), "type": t, "room": room, "x": round(x, 4), "y": round(y, 4), "h": round(h, 3),
             "facing": facing, "label": lab, "status": "engineer", "src": e["src"],
             "pdf": [round(pdf[0], 1), round(pdf[1], 1)], "dim": e.get("dim", "registered")}
        if "L" in e["src"][1:]:
            d["pdf_light"] = sheet_pt("L", rx, ry)
        if t == "switch":
            n = e.get("gangs", 0)  # R01_ADD switches: their gangs come from PLATES below
            d["gangs"] = e.get("gang_text") or [f"Lights — {room.lower()} (gang {i + 1}; circuit not marked on the engineer's plan)" for i in range(n)]
            if e.get("two_way"):
                d["two_way"] = e["two_way"]  # the partner's key, turned into its id below
        if e.get("key"):
            keyed[e["key"]] = d["id"]
        if t in ("socket", "wp") and e.get("gang"):
            d["gang"] = e["gang"]
        for k in ("w", "hh"):  # panel sizes as drawn (DB, L.C)
            if e.get(k):
                d[k] = e[k]
        if e.get("unreadable_h"):
            d["h_unreadable"] = True
        if e.get("note"):
            d["note"] = e["note"]
        if e.get("r01"):
            d["note"] = "; ".join(filter(None, [d.get("note"), f"R01: {e['r01']}"]))
        d["_first"] = id(e) in FIRST  # from his first sheets (R01_DROP applies to these only)
        P.append(d)
        if QA:
            qa.append(f"{d['id']:13s} {room[:14]:14s} reg ({rx:.3f},{ry:.3f}) -> ({d['x']:.3f},{d['y']:.3f}) snap {snap:.3f}  {'; '.join(log)}")

for d in P:  # two-way partners (switches marked ديفاتير, linked where his drawing makes the pair obvious)
    if d.get("two_way"):
        d["two_way"] = ",".join(keyed[k] for k in d["two_way"].split(","))  # one or more partners

# R01: what his revised sheets removed / changed (R01_ADD went through the loop above)
P = [d for d in P if not (d["id"] in R01_DROP and d.pop("_first"))]
for d in P:
    d.pop("_first", None)
byid = {d["id"]: d for d in P}
assert len(byid) == len(P), "duplicate ids"
for pid, ch in R01_CHANGE.items():
    d = byid[pid]
    for k, v in ch.items():
        if k == "r":
            log = []
            d["x"], d["y"] = (round(v_, 4) for v_ in dimmed(d["x"], d["y"], v, log))
        elif k == "r01":
            d["note"] = "; ".join(filter(None, [d.get("note"), f"R01: {v}"]))
        else:
            d[k] = v

# S09: each load's switch code, each plate's codes (gangs), two-way where a code is on several plates
LOADS = {"spot", "wpspot", "pendant", "walllight", "ledfeed", "curtainled", "fan"}
code_plates = {}
for sid, (codes, _) in PLATES.items():
    for c in codes:
        code_plates.setdefault(c, []).append(sid)
for d in P:
    pid, note = d["id"], []
    if d["type"] in LOADS:
        if pid in CIRCUIT:
            d["circuit"] = CIRCUIT[pid]
            d["label"] += f", switch {CIRCUIT[pid]}"
            if pid in MOTOR:
                d["motor_circuit"] = MOTOR[pid]
                d["label"] += f" (curtain motor {MOTOR[pid]})"
        elif pid in NO_CODE:
            note.append(NO_CODE[pid])
        else:
            raise SystemExit(f"{pid}: a load with no S09 entry (CIRCUIT or NO_CODE)")
        d["src"] += "S"
    if d["type"] == "switch":
        codes, pnote = PLATES[pid]
        d["codes"] = codes
        d["gangs"] = [f"{c} — {CODES[c]}" for c in codes]
        mates = sorted({s for c in codes for s in code_plates[c] if s != pid}, key=lambda s: int(s.split("-")[1]))
        if mates:
            d["two_way"] = ",".join(mates)
        else:
            d.pop("two_way", None)
        if "light switch" in d["label"]:
            tail = d["label"].split(" — ", 1)[1]
            d["label"] = f"{'Two-way ' if mates else ''}{len(codes)}-gang light switch — {tail}"
        d["label"] += f" ({','.join(codes)})"
        note.append(pnote)
        if "S" not in d["src"]:
            d["src"] += "S"
    if any(note):
        d["note"] = "; ".join(filter(None, [d.get("note"), *note]))
for d in P:
    assert "stack" not in d

legend = {
    "spot": "Ceiling spot (engineer's single spot)", "wpspot": "Waterproof ceiling spot", "pendant": "Pendant outlet (دلايات)",
    "walllight": "Wall-light outlet", "ledfeed": "Wall LED outlet", "curtainled": "Curtain-box LED + socket outlet",
    "fan": "Ceiling exhaust fan", "sensor": "Motion sensor (MS)", "ap": "Wi-Fi access point",
    "switch": "Light switch (one gang per S09 code; two-way where a code is on several plates)",
    "shutterout": "Shutter outlet (feed for an electric roller shutter)",
    "shutter": "Shutter button switch", "acsw": "AC switch", "heatersw": "Instant water-heater switch", "boilersw": "Water-heater switch",
    "socket": "Socket (single / double / triple universal)", "wp": "Waterproof socket", "usb": "USB charger outlet",
    "woutlet": "\"W\" outlet (phone charger, per his legend)", "tv": "TV dish outlet", "phone": "Phone outlet (T)", "data": "Data outlet (D)",
    "hdmi": "HDMI cable outlet", "lcp": "Low-current panel (L.C)", "db": "Distribution board (DB)",
}
OUT.write_text(json.dumps({
    "version": "light-power-plan",
    "source": "Site engineer's drawings only (Level Up Construction Innovations, Nov 2026): Power Plan S07 R01, Lighting Plan "
              "S08 R01, switches S09 (no revision number)",    "built_by": "build_electrical_light_power_plan.py (edit light_power_plan_points.py, then rerun)",
    "heights": "metres; his boxed heights and H.L= notes (cm), as written",
    "lighting": "fixtures",
    "legend": legend, "points": P, "lines": [],
}, ensure_ascii=False, indent=1) + "\n")
print(f"{OUT.name}: {len(P)} points")
for k, v in sorted(Counter(p["type"] for p in P).items()):
    print(f"  {k:11s} {v}")
for i in issues:
    print("  CHECK:", i)
if QA:
    Path(QA).write_text("\n".join(qa) + "\n")
