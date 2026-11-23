#!/usr/bin/env python3
"""Light and Power Plan's electrical layer -> electrical-light-power-plan.json (that version only).

    python3 build_electrical_light_power_plan.py [--qa FILE]    # writes the JSON; --qa logs every placement (registered -> placed)

Source: ONLY the site engineer's two drawings (Level Up, "Lighting Plan" S08 and "Power Plan" S07, Nov 2026): every symbol
he drew is one point, at his dimensions and heights, even where they differ from Main; nothing of Main's electrical plan
is carried over. The symbols, read off the PDFs room by room, are in light_power_plan_points.py (positions registered onto
Main's plan with reg = x_m = (px - a) / s, y_m = (b - py) / s). Each point is placed:
  - along its wall / in the ceiling at his written dimension from Main's face of the wall he measured from, else where he
    drew it (registered);
  - wall points snapped onto Main's nearest face of the wall he drew them on, 3 mm proud (model-light-power-plan.js);
  - at the height in his box beside the symbol or his H.L= leader note.
Every point has status "engineer", src L / P / LP (light plan, power plan, both: positions from the power plan), pdf (the
symbol's centre on the PDF, points), dim (what placed it) and note (anything doubtful).
"""
import json, math, subprocess, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from light_power_plan_points import POINTS, REG  # noqa: E402

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
P, issues, keyed = [], [], {}
count = Counter()
for e in POINTS:
    t = e["type"]
    cx, cy = e["reg"]
    regs = [(m[0], m[1], m[2:]) for m in e["members"]] if e.get("members") else [(cx, cy, e["pdf"])]
    for (rx, ry, pdf) in regs:
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
        if e.get("pdf_light"):
            d["pdf_light"] = e["pdf_light"]
        if t == "switch":
            n = e["gangs"]
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
        P.append(d)
        if QA:
            qa.append(f"{d['id']:13s} {room[:14]:14s} reg ({rx:.3f},{ry:.3f}) -> ({d['x']:.3f},{d['y']:.3f}) snap {snap:.3f}  {'; '.join(log)}")

for d in P:  # two-way partners (switches marked ديفاتير, linked where his drawing makes the pair obvious)
    if d.get("two_way"):
        d["two_way"] = ",".join(keyed[k] for k in d["two_way"].split(","))  # one or more partners

legend = {
    "spot": "Ceiling spot (engineer's single spot)", "wpspot": "Waterproof ceiling spot", "pendant": "Pendant outlet (دلايات)",
    "walllight": "Wall-light outlet", "ledfeed": "Wall LED outlet", "curtainled": "Curtain-box LED + socket outlet",
    "fan": "Ceiling exhaust fan", "sensor": "Motion sensor (MS)", "ap": "Wi-Fi access point", "switch": "Light switch (gangs; two-way where marked)",
    "shutter": "Shutter button switch", "acsw": "AC switch", "heatersw": "Instant water-heater switch", "boilersw": "Water-heater switch",
    "socket": "Socket (single / double / triple universal)", "wp": "Waterproof socket", "usb": "USB charger outlet",
    "woutlet": "\"W\" outlet (phone charger, per his legend)", "tv": "TV dish outlet", "phone": "Phone outlet (T)", "data": "Data outlet (D)",
    "hdmi": "HDMI cable outlet", "lcp": "Low-current panel (L.C)", "db": "Distribution board (DB)",
}
OUT.write_text(json.dumps({
    "version": "light-power-plan",
    "source": "Site engineer's drawings only (Level Up Construction Innovations, Lighting Plan S08 + Power Plan S07, Nov 2026)",
    "built_by": "build_electrical_light_power_plan.py (edit light_power_plan_points.py, then rerun)",
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
