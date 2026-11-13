"""Plumbing, ceilings, TV wall details, elevations, specs; build_all() assembles the PDF and the DXF/DWG."""
import math
import re
from pathlib import Path
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, Circle, Polygon as MPoly, FancyBboxPatch
from shapely.geometry import Point, LineString

from sheetlib import Sheet, HL, INK, GREY, LIGHT, lw, wrap, text_size_mm
from planbase import draw_base, Labeller, sym, legend_entry
import build_package as B
import sheets_elec as SE


# ---------------- plumbing ----------------
def plumbing(P):
    s, ax, py = P.plan_sheet("A3", "P301", "Plumbing - wet points & heaters", 100, B.FULL, "mep",
                             "Fixture supply / waste points from Main; drains & falls TO CONFIRM")
    lab = Labeller(ax)
    P.room_labels(ax, lab, size=5.0, dims=False, area=False, arabic=False)
    k = 1 / ax._mm_per_m
    for it in P.m.data["plumbing"]:
        kind = "plumb_tbc" if it.get("confirm") else "plumb"
        sym(ax, kind, it["x"], it["y"], c=HL, size=2.6)
        lab.block(it["x"] - 1.4 * k, it["y"] - 1.4 * k, it["x"] + 1.4 * k, it["y"] + 1.4 * k)
    for it in P.m.data["plumbing"]:
        lab.put(it["x"], it["y"], it["id"], size=4.4, c=INK, weight="bold")
    # electrical water outlets and heater power for cross-reference
    for p in P.m.elec["points"]:
        if p["type"] == "water":
            sym(ax, "water", p["x"], p["y"], c=INK, size=2.2)
    # schedule under the plan
    rows = [[it["id"], it["room"], it["what"][:92], str(it["h"])] for it in P.m.data["plumbing"]]
    y = py - 6
    s.table(s.m + 4, y, [("Id", 9, "left"), ("Room", 30, "left"), ("Fixture / point", 175, "left"), ("Height (m)", 44, "left")],
            rows, size=4.4, row_h=2.75, hl_rows=tuple(i for i, it in enumerate(P.m.data["plumbing"]) if it.get("confirm")))
    x = s.side_x + 2
    yy = s.H - s.m - 4
    s.text(x, yy, "LEGEND", size=6, weight="bold")
    yy -= 5
    legend_entry(s, x + 3, yy, "plumb", "Wet point (supply / waste) from Main", c=HL); yy -= 4.6
    legend_entry(s, x + 3, yy, "plumb_tbc", "Point not in Main: TO CONFIRM", c=HL); yy -= 4.6
    legend_entry(s, x + 3, yy, "water", "Water outlet + valve (electrical file)", c=INK); yy -= 6
    s.notes(x, yy, "NOTES", P.m.data["plumbing_notes"], width_chars=46, size=4.4, gap=2.1)
    return s


# ---------------- ceilings ----------------
def ceilings(P):
    s, ax, py = P.plan_sheet("A3", "C401", "Ceilings - plasterboard, curtain pockets, AC & ceiling devices", 100, B.FULL, "mep",
                             f"Flat plasterboard ceiling at {P.m.ceiling:.2f} m (model)")
    lab = Labeller(ax)
    P.room_labels(ax, lab, size=5.0, dims=False, area=False, arabic=False)
    k = 1 / ax._mm_per_m
    for key, poly, kind in P.m.floors:
        if kind == "outdoor":
            continue
        en, _ = P.room_name(key)
        pt = P.m.data["rooms"].get(key, {}).get("at") or (poly.representative_point().x, poly.representative_point().y)
        lab.put(pt[0], pt[1] - 5.5 * k, f"CH {P.m.ceiling * 100:.0f}", size=4.4, c=HL, offsets=[(0, 0)], leader=False)
    for pk in P.m.pockets():
        ax.add_patch(Rectangle((pk["x0"], pk["y0"]), pk["x1"] - pk["x0"], pk["y1"] - pk["y0"], fc=HL, ec=HL, alpha=0.55,
                               lw=lw(0.2), zorder=8, hatch="////"))
        cx, cy = (pk["x0"] + pk["x1"]) / 2, (pk["y0"] + pk["y1"]) / 2
        lab.put(cx, cy, f"pocket {pk['depth'] * 100:.0f}x{pk['depth'] * 100:.0f} +LED", size=3.8, c=INK)
    for a in P.m.acs():
        ax.add_patch(Rectangle((a["x0"], a["y0"]), a["x1"] - a["x0"], a["y1"] - a["y0"], fc="white", ec=INK, lw=lw(0.3), zorder=8))
        cx, cy = (a["x0"] + a["x1"]) / 2, (a["y0"] + a["y1"]) / 2
        w = max(a["x1"] - a["x0"], a["y1"] - a["y0"])
        lab.put(cx, cy, f"split AC {w * 100:.0f} wide, top {a['h1'] * 100:.0f}", size=3.8, c=INK)
    for p in P.m.elec["points"]:
        if p["h"] >= 2.59 and p["type"] in ("spot", "fan", "sensor", "ap", "power", "pendant"):
            sym(ax, p["type"], p["x"], p["y"], c=INK, size=1.8)
    x = s.side_x + 2
    yy = s.H - s.m - 4
    s.text(x, yy, "LEGEND", size=6, weight="bold"); yy -= 5
    s.page.add_patch(Rectangle((x + 1, yy - 1.4), 4, 2.8, fc=HL, ec=HL, alpha=0.55, hatch="////"))
    s.text(x + 7.5, yy, "Curtain pocket in the ceiling (depth x width cm)", size=4.8); yy -= 4.6
    s.rect(x + 1, yy - 1.2, x + 5, yy + 1.2, w=0.3)
    s.text(x + 7.5, yy, "Wall split AC (outline, top height)", size=4.8); yy -= 4.6
    for t in ("spot", "fan", "sensor", "ap", "power"):
        legend_entry(s, x + 3, yy, t, B.TYPE_NAMES[t] + (" (curtain motor)" if t == "power" else ""), c=INK); yy -= 4.6
    yy -= 2
    s.notes(x, yy, "NOTES", [
        f"Main models one flat plasterboard ceiling at {P.m.ceiling:.2f} m in every indoor room (CH = ceiling height).",
        "No drop-ceiling / bulkhead levels are modelled in Main beyond the curtain pockets: any extra bulkhead for pipes, ducts or a concealed AC is TO CONFIRM before gypsum works.",
        "Supply pipes run in the ceiling void (see P301): leave access panels at joints and under every valve.",
        "Curtain pockets: 15 x 15 (divider 12 x 12) with a warm 24 V LED strip on the room side; curtain motor power in the pocket.",
        "Master shower opening stays open to the ceiling (as modelled).",
        "Spots, fans, sensors and APs are shown for coordination with the ceiling grid; positions per E201-E207.",
    ], width_chars=46, size=4.4, gap=2.1)
    return s


# ---------------- TV wall details ----------------
def _num(src, pat, default):
    m = re.search(pat, src)
    return float(m.group(1)) if m else default


def tv_reception(P):
    src = P.m.furnish_src
    L = P.m.locks
    D0 = L["kc-tv-niche-depths"]["run_depth"]
    D1 = L["kc-tv-niche-depths"]["tv_depth"]
    splay = L["kc-tv-niche-depths"]["splay"]
    X0 = L["kc-tv-wall-flush"]["item_x"]           # back line of the build-out (plan x)
    face = L["kc-tv-wall-flush"]["face_x"]
    cy = _num(src, r"named\(item\(17\.25, ([0-9.]+), \"E\"", 3.67)   # item centre (plan y)
    edge = _num(src, r"edge = KC \? (-?[0-9.]+)", -0.4786)
    TW = _num(src, r"const TW = KC \? ([0-9.]+)", 1.668)
    TH = _num(src, r"TH = KC \? ([0-9.]+)", 0.958)
    tvY0 = _num(src, r"tvY0 = KC \? ([0-9.]+)", 0.83)
    m = re.search(r"const tall = KC \? \[\[(-?[0-9.]+), (-?[0-9.]+)\], \[(-?[0-9.]+), (-?[0-9.]+)\]\]", src)
    tall = [[float(m.group(1)), float(m.group(2))], [float(m.group(3)), float(m.group(4))]] if m else [[-1.5428, -1.2028], [-1.1462, -0.8062]]
    m = re.search(r"const low = KC \? \[(-?[0-9.]+), (-?[0-9.]+), ([0-9.]+), ([0-9.]+), ([0-9.]+)\]", src)
    low = [float(v) for v in m.groups()] if m else [-0.2693, 1.5107, 0.33, 0.69, 0.1]
    if "if (SB) low[2] = 0.30" in src:
        low[2] = 0.30
    H = P.m.ceiling
    south = 2.0705                         # south wall face (plan y)
    col_n = L["kc-column-face"]["y_range"][1]  # column north face
    col_s = L["kc-column-face"]["y_range"][0]
    run_end = cy + edge - splay
    box0 = cy + edge
    tcx = cy + (low[0] + low[1]) / 2
    s = P.new("A4", "D501", "Reception TV wall - plan & elevation", "1:25", "L-shaped build-out, recess, TV mounting height")
    sc = 25
    u0, u1 = south - 0.15, col_n + 0.25
    # elevation axes (u = plan y, v = height)
    ax, w, h = s.plan_axes(s.m + 18, s.m + 52, (u0, u1), (-0.05, H + 0.12), sc)
    k = 1 / ax._mm_per_m
    ax.add_patch(Rectangle((south, 0), col_n - south, H, fc="none", ec=INK, lw=lw(0.35), zorder=3))
    ax.add_patch(Rectangle((u0, 0), south - u0, H, fc="#cfcfcf", ec=INK, lw=lw(0.2), hatch="////", zorder=2))
    ax.plot([u0, u1], [0, 0], color=INK, lw=lw(0.5))
    ax.plot([u0, u1], [H, H], color=INK, lw=lw(0.25))
    for yy in (run_end, box0, col_s):
        ax.plot([yy, yy], [0, H], color=INK, lw=lw(0.18), zorder=3)
    ax.text((col_s + col_n) / 2, H / 2, "COLUMN\n(face flush)", fontsize=4.2, ha="center", va="center", rotation=90)
    for a, b in tall:
        ya, yb = cy + a, cy + b
        ax.add_patch(FancyBboxPatch((ya, 0.42), yb - ya, 2.2 - 0.42, boxstyle="round,pad=0,rounding_size=0.13", fc="#efe6d6",
                                    ec=INK, lw=lw(0.25), zorder=4, mutation_aspect=1))
        for sh in (0.86, 1.30, 1.74):
            ax.plot([ya, yb], [sh + 0.025, sh + 0.025], color=INK, lw=lw(0.15), zorder=5)
    la, lb = cy + low[0], cy + low[1]
    ax.add_patch(FancyBboxPatch((la, low[2]), lb - la, low[3] - low[2], boxstyle=f"round,pad=0,rounding_size={low[4]}",
                                fc="#efe6d6", ec=INK, lw=lw(0.25), zorder=4))
    ax.add_patch(Rectangle((tcx - TW / 2, tvY0), TW, TH, fc="#3a3a3a", ec=INK, lw=lw(0.3), zorder=5))
    ax.add_patch(Rectangle((tcx - TW / 2 - 0.025, tvY0 - 0.025), TW + 0.05, TH + 0.05, fc="none", ec=INK, lw=lw(0.15), ls="--", zorder=5))
    ax.add_patch(Rectangle((tcx - 0.4294 - 0.015, 0.710), 0.8588 + 0.03, 0.075, fc="white", ec=INK, lw=lw(0.2), zorder=5))
    ax.text(tcx, 0.7475, "soundbar slot", fontsize=3.4, ha="center", va="center", zorder=6)
    ax.plot([south, col_n], [0.08, 0.08], color=INK, lw=lw(0.12))
    # TV centre and key heights in highlight
    tvc = tvY0 + TH / 2
    ax.plot([tcx - TW / 2 - 0.08, tcx + TW / 2 + 0.08], [tvc, tvc], color=HL, lw=lw(0.2), ls="-.", zorder=7)
    ax.text(tcx, tvc + 0.03, f"TV centre {tvc * 100:.1f}", fontsize=5, color=HL, ha="center", va="bottom", weight="bold", zorder=8,
            bbox=dict(fc="white", ec="none", pad=0.2))
    ax.text(tcx, tvY0 + TH * 0.25, f"TV {TW * 100:.1f} x {TH * 100:.1f}", fontsize=4.6, color="white", ha="center", zorder=8)

    def vdim(x, a, b, txt, side=1):
        ax.plot([x, x], [a, b], color=HL, lw=lw(0.15), zorder=7)
        for v in (a, b):
            ax.plot([x - 0.025, x + 0.025], [v - 0.025, v + 0.025], color=HL, lw=lw(0.3), zorder=7)
        ax.text(x + side * 0.03, (a + b) / 2, txt, fontsize=4.4, color=HL, rotation=90, ha="center",
                va="bottom" if side > 0 else "top", rotation_mode="anchor", zorder=8, bbox=dict(fc="white", ec="none", pad=0.1))

    vdim(tcx + TW / 2 + 0.12, 0, tvY0, f"{tvY0 * 100:.0f}")
    vdim(tcx + TW / 2 + 0.12, tvY0, tvY0 + TH, f"{TH * 100:.1f}")
    vdim(tcx + TW / 2 + 0.24, 0, tvc, f"{tvc * 100:.1f}")
    vdim(la + 0.06, 0, low[2], f"{low[2] * 100:.0f}")
    vdim(la + 0.06, low[2], low[3], f"{(low[3] - low[2]) * 100:.0f}")
    vdim(cy + tall[0][0] - 0.035, 0, 0.42, "42", side=-1)
    vdim(cy + tall[0][0] - 0.035, 0.42, 2.2, "178", side=-1)
    vdim(u1 - 0.1, 0, H, f"{H * 100:.0f}")

    def hdim(v, a, b, txt):
        ax.plot([a, b], [v, v], color=HL, lw=lw(0.15), zorder=7)
        for x in (a, b):
            ax.plot([x - 0.025, x + 0.025], [v - 0.025, v + 0.025], color=HL, lw=lw(0.3), zorder=7)
        ax.text((a + b) / 2, v + 0.02, txt, fontsize=4.2, color=HL, ha="center", va="bottom", zorder=8,
                bbox=dict(fc="white", ec="none", pad=0.1))

    hdim(2.36, south, run_end, f"{(run_end - south) * 100:.1f}")
    hdim(2.36, run_end, box0, f"{(box0 - run_end) * 100:.1f}")
    hdim(2.36, box0, col_s, f"{(col_s - box0) * 100:.1f}")
    hdim(2.48, south, col_n, f"{(col_n - south) * 100:.1f}")
    hdim(0.16, la, lb, f"niche {(lb - la) * 100:.0f}")
    for a, b in tall:
        hdim(2.27, cy + a, cy + b, f"{(b - a) * 100:.0f}")
    # electrical on the wall
    for p in P.m.elec["points"]:
        if abs(p["x"] - face) < 0.32 and south - 0.01 <= p["y"] <= col_n + 0.01 and p["type"] in ("multi", "ledfeed", "socket"):
            sym(ax, p["type"] if p["type"] != "ledfeed" else "ledfeed", p["y"], p["h"], c=HL, size=2.6)
            ax.text(p["y"] + 0.07, p["h"], f"{p['id']} @{p['h'] * 100:.0f}", fontsize=3.9, va="center", zorder=9,
                    bbox=dict(fc="white", ec="none", pad=0.1))
    s.text(s.m + 18, s.m + 52 + h + 3, "ELEVATION A - looking west from the reception (1:25)", size=6, weight="bold")
    # plan / section strip
    ax2, w2, h2 = s.plan_axes(s.m + 18, s.m + 19, (u0, u1), (X0 - 0.12, face + 0.32), sc)
    ax2.set_xlim(u0, u1)
    # plan: x axis = plan y (u), y axis = depth from back line (plan x)
    ax2.add_patch(Rectangle((u0, X0 - 0.12), u1 - u0, 0.12, fc="#cfcfcf", ec=INK, lw=lw(0.2), hatch="////"))
    poly = [(south, X0), (south, X0 + D0), (run_end, X0 + D0), (box0, X0 + D1), (col_s, X0 + D1), (col_s, X0), ]
    ax2.add_patch(MPoly(poly, closed=True, fc="#e8e8e8", ec=INK, lw=lw(0.35), zorder=3))
    ax2.add_patch(Rectangle((col_s, X0 - 0.12), col_n - col_s, face - X0 + 0.12, fc="#9a9a9a", ec=INK, lw=lw(0.3), hatch="xx", zorder=3))
    for a, b in tall:
        ax2.add_patch(Rectangle((cy + a, X0 + 0.005), b - a, D0 - 0.005, fc="white", ec=INK, lw=lw(0.15), ls="--", zorder=4))
    ax2.add_patch(Rectangle((la, X0 + 0.005), lb - la, D1 - 0.005, fc="white", ec=INK, lw=lw(0.15), ls="--", zorder=4))
    ax2.plot([south - 0.15, south], [X0 + D0, X0 + D0], color=INK, lw=lw(0.2))

    def ddim(u, a, b, txt):
        ax2.plot([u, u], [a, b], color=HL, lw=lw(0.15), zorder=7)
        for v in (a, b):
            ax2.plot([u - 0.02, u + 0.02], [v - 0.02, v + 0.02], color=HL, lw=lw(0.3), zorder=7)
        ax2.text(u + 0.03, (a + b) / 2, txt, fontsize=4.2, color=HL, va="center", zorder=8, bbox=dict(fc="white", ec="none", pad=0.05))

    ddim(south + 0.45, X0, X0 + D0, f"{D0 * 100:.2f} run")
    ddim(col_s - 0.32, X0, X0 + D1, f"{D1 * 100:.2f} TV box")
    ax2.text((run_end + box0) / 2, X0 + D1 + 0.06, f"10 cm diagonal over {splay * 100:.2f}", fontsize=4.2, color=HL, ha="center")
    ax2.text(u0 + 0.02, X0 - 0.06, "existing wall", fontsize=3.8, va="center")
    s.text(s.m + 18, s.m + 19 + h2 + 2.5, "PLAN B - build-out (depth from the back line, 1:25)", size=6, weight="bold")
    s.scale_bar(s.m + 18, s.m + 6, 25, metres=2, step=0.5)
    x = s.side_x + 2
    s.notes(x, s.H - s.m - 4, "NOTES", [
        f"Build-out face: TV box {D1 * 100:.2f} deep, flush with the column face; run {D0 * 100:.2f} deep, joined by a straight diagonal (locked 1 Nov 2026).",
        f"TV {TW * 100:.1f} x {TH * 100:.1f} in a plaster opening 2.5 cm larger all round; bottom {tvY0 * 100:.0f}, centre {tvc * 100:.1f} from finished floor.",
        f"Low niche {(lb - la) * 100:.0f} wide, {low[2] * 100:.0f}-{low[3] * 100:.0f} high, oak-lined 18 mm, LED under the top; subwoofer stands at its left end.",
        "Tall niches 34 wide, 42-220, radius 13, oak-lined, 3 shelves + LED; soundbar in a 7.5 deep slot between the niche and the TV.",
        "Plates behind the TV (120) and in the niche (50); LED driver box in the run (140). See E205-E207.",
        "Finish: limewash plaster; oak skirting 8 cm.",
    ], width_chars=36, size=4.4, gap=2.1)
    return s


# ---------------- elevations (generic engine) ----------------
ELEVS = {
    "D502": ("Living room TV wall - elevation", [("A", "Living room - east (TV) wall", (6.133, 4.43), (6.133, 0.555), 0.65)], 25),
    "D601": ("Kitchen elevations", [
        ("A", "Kitchen - north (sink) wall", (6.48, 9.085), (10.205, 9.085), 0.7),
        ("B", "Kitchen - west (hob) wall", (6.48, 5.665), (6.48, 9.085), 0.7),
        ("C", "Kitchen - east (fridge) wall", (10.205, 9.085), (10.205, 5.665), 0.75),
        ("D", "Kitchen - south (pantry) wall", (10.205, 5.665), (6.48, 5.665), 0.7)], 50),
    "D602": ("Master bathroom elevations", [
        ("A", "Master bath - west (vanity / WC) wall", (0.56, 6.14), (0.56, 9.015), 0.65),
        ("B", "Master bath - north (WC / shower) wall", (0.56, 9.015), (2.187, 9.015), 0.6),
        ("C", "Master bath - east wall", (2.187, 9.015), (2.187, 6.14), 0.4),
        ("D", "Master bath - south (door) wall", (2.187, 6.14), (0.56, 6.14), 0.4)], 40),
    "D603": ("Guest bathroom elevations", [
        ("A", "Guest bath - north (bath / WC) wall", (12.12, 9.183), (14.662, 9.183), 0.75),
        ("B", "Guest bath - east (vanity) wall", (14.662, 9.183), (14.662, 6.89), 0.65),
        ("C", "Guest bath - west (bath) wall", (12.12, 6.89), (12.12, 9.183), 0.9),
        ("D", "Guest bath - south (door) wall", (14.662, 6.89), (12.12, 6.89), 0.5)], 40),
    "D604": ("Laundry & coffee corner elevations", [
        ("A", "Laundry - north (machines / heater) wall", (10.325, 9.182), (11.99, 9.182), 0.7),
        ("B", "Laundry - west (joinery) wall", (10.325, 6.894), (10.325, 9.182), 0.7),
        ("C", "Dining - coffee corner, north wall", (19.6, 9.499), (21.22, 9.499), 0.7)], 50),
}


def elevation(P, ax, a, b, depth, title_pts=True):
    """Draw the wall from a to b (viewer inside, wall ahead, a on the left) into ax (u along the wall, v height)."""
    ax_, ay_ = a
    bx_, by_ = b
    Lw = math.hypot(bx_ - ax_, by_ - ay_)
    ux, uy = (bx_ - ax_) / Lw, (by_ - ay_) / Lw
    rx, ry = uy, -ux       # room side of the wall (viewer faces f = (-uy, ux); right hand = u)
    H = P.m.ceiling
    ax.add_patch(Rectangle((0, 0), Lw, H, fc="none", ec=INK, lw=lw(0.35), zorder=3))
    ax.plot([-0.1, Lw + 0.1], [0, 0], color=INK, lw=lw(0.5), zorder=3)

    def proj(x, y):
        return (x - ax_) * ux + (y - ay_) * uy, (x - ax_) * rx + (y - ay_) * ry

    # openings on the wall
    for o in P.m.openings():
        u, d = proj(o["x"], o["y"])
        if abs(d) < 0.3 and -0.05 < u < Lw + 0.05:
            w = o["w"]
            ax.add_patch(Rectangle((u - w / 2, o["sill"]), w, o["head"] - o["sill"], fc="white", ec=INK, lw=lw(0.25), zorder=4,
                                   hatch="" if o["kind"] == "door" else ".."))
            ax.text(u, o["head"] + 0.04, f"{o['tag']} {w * 100:.0f}x{(o['head'] - o['sill']) * 100:.0f}" +
                    (f" sill {o['sill'] * 100:.0f}" if o["sill"] else ""), fontsize=3.8, ha="center", va="bottom", zorder=8,
                    bbox=dict(fc="white", ec="none", pad=0.1))
    # furniture boxes in the band in front of the wall
    for bx in P.m.boxes():
        mname, x0, x1, y0, y1, h0, h1 = bx[:7]
        if mname in ("render", "rug", "planter") or h1 - h0 < 0.012:
            continue
        cs = [proj(x, y) for x in (x0, x1) for y in (y0, y1)]
        us = [c[0] for c in cs]
        ds = [c[1] for c in cs]
        if min(ds) > depth or max(ds) < -0.05:
            continue
        u0, u1 = max(min(us), 0), min(max(us), Lw)
        if u1 - u0 < 0.012:
            continue
        ax.add_patch(Rectangle((u0, max(h0, 0)), u1 - u0, min(h1, H) - max(h0, 0), fc="none", ec="#7a7a7a", lw=lw(0.08), zorder=4))
    # TV screens: bottom / top / centre heights
    for bx in P.m.boxes():
        if bx[0] != "screen":
            continue
        mname, x0, x1, y0, y1, h0, h1 = bx[:7]
        cs = [proj(x, y) for x in (x0, x1) for y in (y0, y1)]
        us = [c[0] for c in cs]
        ds = [c[1] for c in cs]
        if min(ds) > depth or max(ds) < -0.05:
            continue
        ue = max(us) + 0.12
        for a0, a1, t in ((0, h0, f"{h0 * 100:.0f}"), (h0, h1, f"{(h1 - h0) * 100:.0f}"), (0, (h0 + h1) / 2, f"c {(h0 + h1) * 50:.1f}")):
            uu = ue + (0.16 if t.startswith("c") else 0)
            ax.plot([uu, uu], [a0, a1], color=HL, lw=lw(0.15), zorder=7)
            for v in (a0, a1):
                ax.plot([uu - 0.02, uu + 0.02], [v - 0.02, v + 0.02], color=HL, lw=lw(0.3), zorder=7)
            ax.text(uu + 0.03, (a0 + a1) / 2, t, fontsize=4.4, color=HL, rotation=90, ha="center", va="bottom",
                    rotation_mode="anchor", zorder=8, bbox=dict(fc="white", ec="none", pad=0.1))
        ax.plot([min(us) - 0.05, max(us) + 0.05], [(h0 + h1) / 2] * 2, color=HL, lw=lw(0.15), ls="-.", zorder=7)
    # electrical points on this wall
    lab = Labeller(ax)
    for p in P.m.elec["points"]:
        u, d = proj(p["x"], p["y"])
        if -0.02 <= u <= Lw + 0.02 and -0.08 <= d <= 0.35 and p["h"] < H - 0.01 and p["type"] not in ("spot", "sensor", "ap", "fan"):
            sym(ax, p["type"], u, p["h"], c=HL, size=2.4)
            lab.block(u - 0.05, p["h"] - 0.05, u + 0.05, p["h"] + 0.05)
    for p in P.m.elec["points"]:
        u, d = proj(p["x"], p["y"])
        if -0.02 <= u <= Lw + 0.02 and -0.08 <= d <= 0.35 and p["h"] < H - 0.01 and p["type"] not in ("spot", "sensor", "ap", "fan"):
            t = {"socket": "S", "power": "P", "switch": "SW", "multi": "M", "ledfeed": "L", "water": "W", "wp": "WP",
                 "flap": "FL", "walllight": "WL", "acctl": "AC", "db": "DB", "router": "HUB", "intercom": "IC",
                 "lightout": "LO", "tv": "TV", "phone": "T", "pendant": "PD"}.get(p["type"], p["type"])
            lab.put(u, p["h"], f"{t} {p['h'] * 100:.0f}", size=4.0, c=INK)
    for it in P.m.data["plumbing"]:
        u, d = proj(it["x"], it["y"])
        if -0.02 <= u <= Lw + 0.02 and -0.05 <= d <= depth * 0.8:
            ax.plot([u, u], [0, 0.12], color=HL, lw=lw(0.4))
            lab.put(u, 0.16, it["id"], size=3.8, c=HL, weight="bold")
    # height dim
    ax.text(Lw + 0.06, H / 2, f"CH {H * 100:.0f}", fontsize=4, rotation=90, va="center", ha="left")
    ax.text(Lw / 2, -0.09, f"{Lw * 100:.0f}", fontsize=4.4, ha="center", va="top", color=HL)
    return Lw


def elev_sheet(P, no):
    title, views, sc = ELEVS[no]
    s = P.new("A4", no, title, f"1:{sc}", "Model geometry: openings, joinery outlines, electrical & wet points on each wall")
    H = P.m.ceiling
    avail_w = s.side_x - s.m - 8
    # 2x2 grid (or a single wide view)
    cells = [(s.m + 6, s.H / 2 + 6), (s.m + 6 + avail_w / 2, s.H / 2 + 6), (s.m + 6, s.m + 14), (s.m + 6 + avail_w / 2, s.m + 14)]
    if len(views) == 1:
        cells = [(s.m + 14, s.m + 22)]
    for (tag, name, a, b, depth), (cx, cy) in zip(views, cells):
        Lw = math.hypot(b[0] - a[0], b[1] - a[1])
        ax, w, h = s.plan_axes(cx + 2, cy + 4, (-0.12, Lw + 0.25), (-0.15, H + 0.25), sc)
        elevation(P, ax, a, b, depth)
        s.text(cx + 2, cy + 4 + h + 2.5, f"{tag}  {name}", size=5.6, weight="bold")
    s.scale_bar(s.side_x - 72 if sc >= 40 else s.side_x - 100, s.m + 4.5, sc, metres=2 if sc < 50 else 3, step=0.5 if sc < 50 else 1,
                label=f"SCALE 1:{sc}")
    s.notes(s.side_x + 2, s.H - s.m - 4, "NOTES", [
        "Viewed from inside the room; left/right as you face the wall. Heights in cm from finished floor (electrical: from slab, to confirm).",
        "Grey outlines: joinery and appliance boxes from the Main 3D model (sanitaryware and other modelled shapes are not drawn; see plans).",
        "Orange: electrical points (with height) and wet points (P-ids, see P301).",
        "Dotted fill = window; plain = door.",
    ], width_chars=36, size=4.3, gap=2.05)
    return s


def tv_living(P):
    s = elev_sheet(P, "D502")
    s.notes(s.side_x + 2, s.H - s.m - 66, "TV WALL (Main)", [
        "TV 160 x 85, bottom 110, top 195 (centre 152.5) from finished floor.",
        "Floating walnut console 174 wide x 40 deep, 45-75 high, stone top; LED under-glow.",
        "Thin brass LED sconces each side at 115 from the TV centre line, 115-190 high; feeds at 152.",
        "Limewash taupe panel 350 wide, full height, on the column plane (TV wall face x 6.138).",
        "Plates: TV plate 120 behind the TV, console plate 60 (D, HDMI, TV, 2S).",
    ], width_chars=36, size=4.3, gap=2.05)
    return s


# ---------------- specs ----------------
def specs(P):
    rows = P.m.data["specs"]
    per = 24
    out = []
    for i in range(0, len(rows), per):
        no = f"S701" if i == 0 else f"S70{1 + i // per}"
        s = P.new("A4", no, "Specifications, finishes & heights" + (" (cont.)" if i else ""), "-",
                  "Design intent from Main + decisions to date; 'to confirm' = not fixed yet")
        y = s.H - s.m - 6
        x0 = s.m + 2
        cols = [("Area", 26, "left"), ("Item", 34, "left"), ("Specification", 112, "left"), ("Status", 40, "left")]
        tot = sum(c[1] for c in cols)
        s.rect(x0, y - 3.4, x0 + tot, y, fc="#e6e6e6", w=0.25)
        cx = x0
        for t, w, a in cols:
            s.text(cx + 0.8, y - 1.7, t, size=5, weight="bold")
            cx += w
        y -= 3.4
        for r in rows[i:i + per]:
            spec_l = wrap(r[2], 72)
            st_l = wrap(r[3], 24)
            item_l = wrap(r[1], 20)
            n = max(len(spec_l), len(st_l), len(item_l))
            rh = 2.5 * n + 1.4
            s.rect(x0, y - rh, x0 + tot, y, w=0.12)
            cx = x0
            for (t, w, a), lines in zip(cols, ([r[0]], item_l, spec_l, st_l)):
                for j, ln in enumerate(lines):
                    conf = "confirm" in r[3].lower() and t == "Status"
                    s.text(cx + 0.8, y - 1.9 - j * 2.5, ln, size=4.6, c=HL if conf else INK, weight="bold" if conf else "normal")
                cx += w
            y -= rh
        s.notes(s.side_x + 2, s.H - s.m - 4, "NOTES", [
            "Sources: Main model (dimensions, heights), the designer's renders (finish intent) and Karim's recorded decisions (dates given).",
            "Orange status = TO CONFIRM before ordering or starting that trade.",
            "Brands and product codes are not fixed unless named.",
        ], width_chars=36, size=4.3, gap=2.05)
        out.append(s)
    return out


# ---------------- DXF / DWG ----------------
def export_dxf(P, path):
    import ezdxf
    from ezdxf import recover
    doc, _ = recover.readfile(str(P.m.repo / "dwg" / "kareems-changes.dxf"))
    msp = doc.modelspace()
    ox, oy = P.m.origin
    layers = {"E-LIGHT": 30, "E-SWITCH": 5, "E-POWER": 1, "E-LOWCURRENT": 4, "E-LINK": 8, "P-WET": 3, "C-CEILING": 6,
              "A-PKG-TEXT": 7, "A-PKG-DIMS": 30}
    for n, c in layers.items():
        if n not in doc.layers:
            doc.layers.add(n, color=c)
    lay_for = {}
    for kind, (_, types) in B.ELEC_SHEETS.items():
        for t in types:
            lay_for.setdefault(t, {"light": "E-LIGHT", "switch": "E-SWITCH", "power": "E-POWER", "low": "E-LOWCURRENT"}[kind])
    for p in P.m.elec["points"]:
        L = lay_for.get(p["type"], "E-POWER" if p["type"] == "water" else "E-LIGHT")
        x, y = p["x"] + ox, p["y"] + oy
        msp.add_circle((x, y), 0.06, dxfattribs={"layer": L})
        msp.add_text(f"{p['id']} {p['h'] * 100:.0f}", height=0.05, dxfattribs={"layer": L}).set_placement((x + 0.08, y + 0.02))
    for l in P.m.elec["lines"]:
        msp.add_line((l["x0"] + ox, l["y0"] + oy), (l["x1"] + ox, l["y1"] + oy), dxfattribs={"layer": "E-LIGHT", "linetype": "DASHED"} if "DASHED" in doc.linetypes else {"layer": "E-LIGHT"})
    for it in P.m.data["plumbing"]:
        x, y = it["x"] + ox, it["y"] + oy
        msp.add_circle((x, y), 0.08, dxfattribs={"layer": "P-WET"})
        msp.add_text(f"{it['id']} {it['what'][:60]}", height=0.06, dxfattribs={"layer": "P-WET"}).set_placement((x + 0.1, y))
    for pk in P.m.pockets():
        pts = [(pk["x0"] + ox, pk["y0"] + oy), (pk["x1"] + ox, pk["y0"] + oy), (pk["x1"] + ox, pk["y1"] + oy), (pk["x0"] + ox, pk["y1"] + oy)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "C-CEILING"})
    for a in P.m.acs():
        pts = [(a["x0"] + ox, a["y0"] + oy), (a["x1"] + ox, a["y0"] + oy), (a["x1"] + ox, a["y1"] + oy), (a["x0"] + ox, a["y1"] + oy)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "C-CEILING"})
    import sheets_r1 as R1
    for tag, xx, yy, why in R1.APANELS:      # R1: proposed 60 x 60 ceiling access panels
        x, y = xx + ox, yy + oy
        msp.add_lwpolyline([(x - 0.3, y - 0.3), (x + 0.3, y - 0.3), (x + 0.3, y + 0.3), (x - 0.3, y + 0.3)], close=True,
                           dxfattribs={"layer": "C-CEILING"})
        msp.add_text(f"{tag} access panel 60x60 - {why}", height=0.06, dxfattribs={"layer": "C-CEILING"}).set_placement((x - 0.3, y - 0.42))
    for key, poly, kind in P.m.floors:          # R1: ceiling tag per room (board, Main CH, Lotus TP level)
        if kind == "outdoor":
            continue
        board, fcl, note = R1.CEIL.get(key, ("C01", None, ""))
        pt = P.m.data["rooms"].get(key, {}).get("at") or (poly.representative_point().x, poly.representative_point().y)
        msp.add_text(f"{board} CH {P.m.ceiling * 100:.0f} (TP -{fcl})", height=0.08,
                     dxfattribs={"layer": "C-CEILING"}).set_placement((pt[0] + ox, pt[1] + oy - 0.55))
    for key, poly, kind in P.m.floors:
        en, _ = P.room_name(key)
        pt = P.m.data["rooms"].get(key, {}).get("at") or (poly.representative_point().x, poly.representative_point().y)
        msp.add_text(f"{en} {poly.area:.2f} m2", height=0.12, dxfattribs={"layer": "A-PKG-TEXT"}).set_placement((pt[0] + ox, pt[1] + oy - 0.35))
    doc.saveas(str(path))
    return path


def to_dwg(dxf, dwg):
    import shutil, subprocess, tempfile
    with tempfile.TemporaryDirectory() as i, tempfile.TemporaryDirectory() as o:
        shutil.copy(dxf, Path(i) / Path(dxf).name)
        cmd = ["ODAFileConverter", i, o, "ACAD2018", "DWG", "0", "1", "*.DXF"]
        if shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a"] + cmd
        subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        outs = list(Path(o).glob("*.dwg"))
        if not outs:
            return None
        shutil.copy(outs[0], dwg)
        return dwg


# ---------------- assemble ----------------
def build_all(P, args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    D = SE.prep(P)
    pages = [P.cover()]
    pages.append(P.layout())
    pages.append(P.furniture())
    pages.append(SE.elec_sheet(P, D, "light", "E201", B.WEST, 50, "W"))
    pages.append(SE.elec_sheet(P, D, "light", "E202", B.EAST, 50, "E"))
    pages.append(SE.elec_sheet(P, D, "switch", "E203", B.WEST, 50, "W"))
    pages.append(SE.elec_sheet(P, D, "switch", "E204", B.EAST, 50, "E"))
    pages.append(SE.elec_sheet(P, D, "power", "E205", B.WEST, 50, "W"))
    pages.append(SE.elec_sheet(P, D, "power", "E206", B.EAST, 50, "E"))
    pages.append(SE.elec_sheet(P, D, "low", "E207", B.FULL, 100, "F"))
    pages += SE.schedule(P, D, "E209")
    pages.append(plumbing(P))
    import sheets_r1 as R1
    pages += R1.sheet_ceilings(P)                 # C401-C404 gypsum-board ceilings (R1)
    pages.append(tv_reception(P))
    pages += R1.sheet_living_tv(P)                # D502 (R1 redraw)
    pages += R1.sheet_buffet(P)                   # D503.1-.2
    pages += R1.sheet_terrace_doors(P)            # D504, D505.1-.3
    pages += R1.sheet_terrace(P)                  # D506.1-.2, D507, D508
    pages.append(elev_sheet(P, "D601"))
    pages += R1.sheet_master(P)                   # D602.1-.5
    pages += R1.sheet_guest(P)                    # D603.1-.5
    pages.append(elev_sheet(P, "D604"))
    pages += specs(P)
    P.fill_cover()
    md = P.m.data["meta"]
    pdf_path = out / f"Al Lotus - Finishing Package - Main - {md['rev']}.pdf"
    with PdfPages(pdf_path) as pdf:
        info = pdf.infodict()
        info["Title"] = f"Al Lotus - Finishing Package - Main - {md['rev']}"
        info["Author"] = "Grok Bot for Karim Tamer"
        info["Subject"] = P.meta["source"]
        for s in pages:
            s.save(pdf)
    print("PDF", pdf_path, "pages", len(pages))
    dxf = export_dxf(P, out / f"Al Lotus - Main plans - {md['rev']}.dxf")
    print("DXF", dxf)
    dwg = to_dwg(dxf, out / f"Al Lotus - Main plans - {md['rev']}.dwg")
    print("DWG", dwg)
    (out / "sheet-index.txt").write_text("\n".join(f"{no}\t{t}\t{p}\t{sc}" for no, t, p, sc in B.SHEETS) + "\n")
