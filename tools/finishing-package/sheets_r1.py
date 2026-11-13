"""R1 detail sheets (13 Nov 2026): bathrooms drawn with real shapes, buffet wall, terrace doors, terrace L-seat and BBQ
counter, the living TV wall, and the gypsum-board ceiling set (RCP west/east + sections).

Positions and sizes come from Main (furnish-kareems-changes.js boxes, model openings, electrical file, design locks);
what Main does not hold (tile sizes, floor build-ups, drains, ceiling levels from the Lotus technical package) is drawn
as a recommendation and marked TO CONFIRM. Views are front-on 2D: `a`->`b` is the wall face as you stand in the room
looking at it (a on your left).
"""
import math
from matplotlib.patches import Rectangle, Circle, Polygon as MPoly, FancyBboxPatch, Ellipse
from shapely.geometry import Point

from sheetlib import Sheet, HL, INK, GREY, LIGHT, lw, wrap, text_size_mm
from planbase import draw_base, Labeller, sym, legend_entry
from elevkit import EV, cm, title_under, marker, markers4, section_mark, POCHE, WOOD, STONE, GLASS, DARK, SOFT
import build_package as B

TP = "Lotus technical package (Samra Concepts, 1st issue 20-08-2026)"
TPS = "TP"


class Wall:
    """Wall face from a to b (viewer in the room facing it, a on the left). u along, d = distance into the room."""

    def __init__(self, a, b):
        self.a, self.b = a, b
        self.L = math.hypot(b[0] - a[0], b[1] - a[1])
        self.ux, self.uy = (b[0] - a[0]) / self.L, (b[1] - a[1]) / self.L
        self.rx, self.ry = self.uy, -self.ux

    def u(self, x, y):
        return (x - self.a[0]) * self.ux + (y - self.a[1]) * self.uy

    def d(self, x, y):
        return (x - self.a[0]) * self.rx + (y - self.a[1]) * self.ry


LET = {"socket": "S", "power": "P", "switch": "SW", "multi": "M", "ledfeed": "L", "water": "W", "wp": "WP", "flap": "FL",
       "walllight": "WL", "acctl": "AC", "db": "DB", "router": "HUB", "intercom": "IC", "lightout": "LO", "tv": "TV",
       "phone": "T", "pendant": "PD", "data": "D", "intercom_out": "VD"}


def elec_overlay(ev, P, wall, H, depth=0.4, u_range=None, size=2.3, labels=True, skip_ids=()):
    """Electrical points on this wall (and boxes on joinery in front of it) with type + height."""
    u0, u1 = u_range or (-0.02, wall.L + 0.02)
    out = []
    for p in P.m.elec["points"]:
        if p["id"] in skip_ids:
            continue
        u, d = wall.u(p["x"], p["y"]), wall.d(p["x"], p["y"])
        if u0 <= u <= u1 and -0.04 <= d <= depth and p["h"] < H - 0.01 and p["type"] not in ("spot", "sensor", "ap", "fan"):
            ev.elec(p["type"], u, p["h"], size=size)
            out.append((u, p))
    if labels:
        for u, p in out:
            ev.text(u + size * 0.75 * ev.k, p["h"] + size * 0.55 * ev.k, f"{LET.get(p['type'], p['type'])} {p['h'] * 100:.0f}",
                    size=3.5, c=HL, ha="left", va="bottom", bg="white")
    return out


def plumb_overlay(ev, P, wall, depth=0.9, u_range=None):
    u0, u1 = u_range or (-0.02, wall.L + 0.02)
    for it in P.m.data["plumbing"]:
        u, d = wall.u(it["x"], it["y"]), wall.d(it["x"], it["y"])
        if u0 <= u <= u1 and -0.05 <= d <= depth:
            ev.text(u, -0.06, it["id"], size=3.6, c=HL, weight="bold", va="top", bg="white")


def view(s, x, y, ul, vl, sc):
    ax, w, h = s.plan_axes(x, y, ul, vl, sc)
    return EV(ax, s), w, h


def std_frame(ev, L, H, left_cut=0.12, right_cut=0.12, slab=0.10, fl_label="FFL ±0.00", ceil_label=None):
    """Room shell for an interior elevation: floor, ceiling + void, both side walls cut."""
    ev.floor(-left_cut, L + right_cut, depth=slab)
    ev.ceiling(-left_cut, L + right_cut, H, void=0.10, label=ceil_label)
    if left_cut:
        ev.cutwall(-left_cut, 0, -slab, H + 0.10)
    if right_cut:
        ev.cutwall(L, L + right_cut, -slab, H + 0.10)
    ev.level(-left_cut - 0.40, 0, "FFL", size=4.0)
    ev.level(-left_cut - 0.40, H, f"CH {H * 100:.0f}", size=4.0)


def side_notes(s, items, title="NOTES", y=None, size=4.3, width=36):
    return s.notes(s.side_x + 2, y if y is not None else s.H - s.m - 4, title, items, width_chars=width, size=size, gap=2.05)


def plan_view(P, s, x, y, xl, yl, sc, mode="furn", labels=True):
    ax, w, h = s.plan_axes(x, y, xl, yl, sc)
    draw_base(ax, P.m, mode)
    return ax, w, h


def pdim(ax, p0, p1, txt=None, off=0.0, c=HL, size=4.2):
    """Plan dimension line (metres) with ticks and text."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy, ux
    a0 = (x0 + nx * off, y0 + ny * off)
    a1 = (x1 + nx * off, y1 + ny * off)
    k = 1 / ax._mm_per_m
    ax.plot([a0[0], a1[0]], [a0[1], a1[1]], color=c, lw=lw(0.13), zorder=15, clip_on=False)
    for a in (a0, a1):
        ax.plot([a[0] - (ux + nx) * 0.9 * k, a[0] + (ux + nx) * 0.9 * k], [a[1] - (uy + ny) * 0.9 * k, a[1] + (uy + ny) * 0.9 * k],
                color=c, lw=lw(0.3), zorder=15, clip_on=False)
    if off:
        for p, a in ((p0, a0), (p1, a1)):
            ax.plot([p[0], a[0]], [p[1], a[1]], color=c, lw=lw(0.08), zorder=14, clip_on=False)
    ang = math.degrees(math.atan2(uy, ux))
    if ang > 90 or ang <= -90:
        ang += 180
    mx, my = (a0[0] + a1[0]) / 2, (a0[1] + a1[1]) / 2
    sg = 1 if off >= 0 else -1
    ax.text(mx + nx * 1.3 * k * sg, my + ny * 1.3 * k * sg, txt or cm(L), fontsize=size, color=c, ha="center", va="center",
            rotation=ang, rotation_mode="anchor", zorder=16, bbox=dict(fc="white", ec="none", pad=0.1), clip_on=False)


def plan_label(ax, x, y, t, size=4.0, c=INK, ha="center", weight="normal", rot=0):
    ax.text(x, y, t, fontsize=size, color=c, ha=ha, va="center", zorder=17, weight=weight, rotation=rot,
            bbox=dict(fc="white", ec="none", pad=0.12, alpha=0.9), clip_on=False)


def keyplan(P, s, x, y, focus, sc=200, w_m=None):
    """Small key plan (1:200) with the focus area highlighted."""
    ax, w, h = s.plan_axes(x, y, B.FULL[0], B.FULL[1], sc)
    draw_base(ax, P.m, "mep")
    (fx0, fy0, fx1, fy1) = focus
    ax.add_patch(Rectangle((fx0, fy0), fx1 - fx0, fy1 - fy0, fc=HL, ec=HL, alpha=0.35, lw=lw(0.3), zorder=10))
    s.text(x, y + h + 2, "KEY PLAN 1:200", size=4.2, weight="bold")
    return ax


# =====================================================================================================================
# MASTER BATHROOM
# =====================================================================================================================
MB = dict(x0=0.556, x1=2.242, y0=6.135, y1=9.02)


def mb_plan(P, s, x, y, sc=25, refs=None):
    X0, X1, Y0, Y1 = MB["x0"], MB["x1"], MB["y0"], MB["y1"]
    ax, w, h = plan_view(P, s, x, y, (X0 - 0.62, X1 + 0.28), (Y0 - 0.30, Y1 + 0.58), sc)
    k = 1 / ax._mm_per_m
    # zones and labels
    plan_label(ax, 0.86, 6.69, "VANITY 110 x 58\ninset basin", 3.6)
    plan_label(ax, 0.86, 8.30, "SHOWER\n78.5 x 135", 3.8, weight="bold")
    plan_label(ax, 0.75, 7.735, "fold-up\nseat", 3.2)
    plan_label(ax, 1.80, 8.40, "WC", 3.8, weight="bold")
    plan_label(ax, 1.80, 8.875, "frame box 30", 3.0)
    plan_label(ax, 0.95, 7.385, "partition + niche", 3.0)
    plan_label(ax, 1.70, 6.75, "MASTER\nBATHROOM", 4.2, weight="bold")
    # glass screen highlight
    ax.plot([1.351, 1.351], [8.12, 8.81], color=HL, lw=lw(0.5), zorder=12)
    plan_label(ax, 1.42, 8.46, "glass 69", 3.0, c=HL, ha="left", rot=90)
    # drain (proposed)
    ax.add_patch(Rectangle((0.60, 8.70), 0.70, 0.06, fc="white", ec=HL, lw=lw(0.25), ls=(0, (2, 1)), zorder=12))
    plan_label(ax, 0.95, 8.62, "linear drain (proposed)", 2.9, c=HL)
    # dims
    pdim(ax, (X0, Y1), (X1, Y1), off=0.48)
    pdim(ax, (X0, Y1), (1.341, Y1), off=0.36)
    pdim(ax, (1.361, Y1), (X1, Y1), off=0.36)
    pdim(ax, (X0, Y0), (X0, Y1), off=0.50)
    pdim(ax, (X0, Y0), (X0, 7.235), off=0.36)
    pdim(ax, (X0, 7.235), (X0, 7.46), off=0.36, txt="22.5")
    pdim(ax, (X0, 7.46), (X0, 8.81), off=0.36)
    pdim(ax, (1.351, 7.46), (1.351, 8.12), "66 entry", off=-0.08, size=3.8)
    markers4(ax, 1.80, 7.62, refs)
    return ax, w, h


def mb_elev_A(P, s, x, y, sc=25):
    """West wall, seen from the room (cut at x 1.33, just inside the shower glass)."""
    H = P.m.ceiling
    Y0, Y1 = MB["y0"], MB["y1"]
    wall = Wall((0.556, Y0), (0.556, Y1))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda yy: yy - Y0
    std_frame(ev, L, H)
    # oak slat cladding behind the vanity, then large porcelain in the shower
    ev.rect(0, 0, U(7.235), H, w=0.2, fc="#f1e7d6")
    ev.slats(0, U(7.235), 0, H, pitch=0.045)
    ev.rect(U(7.46), 0, U(8.81), H, w=0.2, fc=STONE)
    ev.tiles(U(7.46), 0, U(8.81), H, 0.60, 1.20, ou=U(7.46), ov=0.0)
    # partition end (shower side niche faces north, hidden) - seen end-on, 15.5 thick
    ev.rect(U(7.305), 0, U(7.46), H, w=0.3, fc=STONE)
    ev.tiles(U(7.305), 0, U(7.46), H, 0.60, 1.20, ov=0.0)
    ev.note(U(7.38), 1.95, "Partition 15.5 (end face), porcelain on all faces; lit niche 67 x 13.5 on its shower face, see C")
    # shower back build-out (21 deep, buries the column) - cut
    ev.cutwall(U(8.81), L, -0.10, H + 0.10, fc="#d6d6d6", hatch="xx")
    ev.text(U(8.915), 1.55, "build-out 21\n(column)", size=3.4, rot=90)
    # vanity: floating carcass 30-80, marble top 80-86, LED under
    ev.drawers(U(6.145), U(7.225), 0.30, 0.80, n=2, rows=1, fc=WOOD)
    ev.grain(U(6.145), 0.30, U(7.225), 0.80, n=4)
    ev.rect(U(6.145), 0.80, U(7.225), 0.86, w=0.3, fc="#f4f2ee", z=ev.z + 2.5)
    ev.basin_inset(U(6.6851), 0.86, w=0.47, depth=0.15)
    ev.led(U(6.16), 0.285, U(7.21), 0.285)
    ev.rect(U(6.185), 0.37, U(6.425), 0.74, w=0.15, ls=(0, (3, 2)), z=ev.z + 2.6)
    ev.text(U(6.305), 0.55, "heater\n7.5 kW", size=3.0, z=14)
    # wall spout + handle on the slats under the cabinet
    ev.rect(U(6.645), 1.00, U(6.725), 1.06, w=0.2, fc="white", z=ev.z + 4)
    ev.spout(U(6.685), 1.03)
    # mirrored medicine cabinet 80 x 75, two leaves, glow behind
    ev.led(U(6.265), 1.30, U(6.265), 2.09)
    ev.led(U(7.105), 1.30, U(7.105), 2.09)
    ev.mirror(U(6.285), 1.32, U(6.685), 2.07)
    ev.mirror(U(6.685), 1.32, U(7.085), 2.07)
    ev.line([U(6.66), U(6.66)], [1.62, 1.78], w=0.4)
    ev.line([U(6.71), U(6.71)], [1.62, 1.78], w=0.4)
    # fold-up teak seat 45 wide, top 45 (open)
    ev.rect(U(7.51), 0.42, U(7.96), 0.45, w=0.3, fc="#d9b48a")
    for yy in (7.545, 7.925):
        ev.rect(U(yy) - 0.012, 0.25, U(yy) + 0.012, 0.42, w=0.15, fc="#cfc3a6")
    # shower set on the build-out face (side view): mixer 100, diverter 120, hand shower, rain arm 42 out at 210-214
    for v, r in ((1.01, 0.075), (1.21, 0.06)):
        ev.rect(U(8.81) - 0.03, v - r, U(8.81), v + r, w=0.25, fc="white", z=ev.z + 5)
    ev.rain_side(U(8.81), -1, 2.10, arm=0.42, dia=0.26)
    ev.hand_shower(U(8.81) - 0.045, 1.13)
    ev.line([U(8.12), U(8.12)], [0, 2.0], w=0.12, c=GREY, ls=(0, (5, 2)))
    ev.text(U(8.465), 2.04, "glass screen 69 (in front, dashed)", size=3.2, c=GREY, va="bottom")
    ev.line([U(8.12), U(8.81)], [2.0, 2.0], w=0.12, c=GREY, ls=(0, (5, 2)))
    # floor fall in the shower (proposed)
    ev.line([U(7.46), U(8.71)], [0.0, -0.02], w=0.2, c=HL, ls=(0, (3, 1.5)))
    ev.text(U(8.10), -0.05, "fall 1.5-2 % to linear drain at the build-out (proposed)", size=3.2, c=HL, va="top", bg="white")
    # electrical
    elec_overlay(ev, P, wall, H, depth=0.45, u_range=(0, U(8.81)))
    # dimensions
    ev.hchain(H + 0.17, [0, U(7.235), U(7.305), U(7.46), U(8.81), L])
    ev.hchain(-0.17, [U(6.145), U(6.6851), U(7.225)], above=False)
    ev.vchain(-0.24, [0, 0.30, 0.80, 0.86, 1.32, 2.07, H], left=True)
    ev.vchain(U(7.73), [0, 0.45], size=3.6)
    ev.vchain(U(8.40), [0, 1.01, 1.21, 2.10], size=3.6)
    # callouts
    ev.note(U(6.5), 2.4, "Honey-oak slatted cladding, full height, on battens (vanity wall)")
    ev.note(U(6.4), 1.85, "Mirrored medicine cabinet 80 x 75 x 30 deep, 2 leaves, 3 glass shelves; LED glow round it")
    ev.note(U(6.685), 1.03, "Wall spout + mixer (concealed body) at 100-106")
    ev.note(U(6.9), 0.83, "Marble top 6 cm, top 86; inset basin centred y 6.685", key=True)
    ev.note(U(7.0), 0.55, "Floating vanity, oak veneer, 2 drawers, 30-80; 7.5 kW heater inside (P02)")
    ev.note(U(7.0), 0.285, "LED under the vanity (L-206)")
    ev.note(U(7.73), 0.44, "Fold-up teak seat 45 x 35, top 45, champagne brackets", key=False)
    ev.note(U(8.3), 2.3, "Rain head 26 on a 42 cm wall arm, 210")
    ev.note(U(8.78), 1.21, "3-way diverter 120 / thermostatic mixer 100 (concealed bodies in the build-out)")
    ev.note(U(8.3), 1.6, "Large-format stone-look porcelain, wall-to-ceiling; 60 x 120 setting-out TO CONFIRM")
    ev.place_notes(at=L + 0.40, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def mb_elev_B(P, s, x, y, sc=25):
    """North wall: shower back (build-out face y 8.81) and WC bay with its frame box and the frosted window."""
    H = P.m.ceiling
    X0, X1 = MB["x0"], MB["x1"]
    wall = Wall((X0, 9.02), (X1, 9.02))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda xx: xx - X0
    std_frame(ev, L, H)
    # shower back build-out face (21 in front of the wall): porcelain, fittings
    ev.rect(0, 0, U(1.341), H, w=0.25, fc=STONE)
    ev.tiles(0, 0, U(1.341), H, 0.60, 1.20, ou=U(0.9485) - 0.30, ov=0.0)
    ev.plate(U(0.9485), 1.01, w=0.15, round_=True)
    ev.plate(U(0.9485), 1.21, w=0.12, round_=True)
    ev.hand_shower(U(0.6685), 1.13, v_out=0.92)
    ev.rain_front(U(0.9485), 2.10, dia=0.26)
    ev.line([U(0.9485), U(0.9485)], [2.10, 2.14], w=0.4)
    # glass screen edge (cut) + channel
    ev.rect(U(1.341), 0, U(1.361), 2.0, w=0.3, fc=DARK)
    # WC bay: frame box 30 deep to 112 with porcelain ledge, flush plate, pan, bidet mixer
    ev.rect(U(1.361), 0, U(2.242), 1.12, w=0.3, fc=STONE, z=ev.z + 2)
    ev.tiles(U(1.361), 0, U(2.242), 1.10, 0.60, 1.20, ou=U(1.804) - 0.30, ov=0.0)
    ev.rect(U(1.361), 1.10, U(2.242), 1.12, w=0.3, fc="white", z=ev.z + 2.2)
    ev.flush_plate(U(1.804), 0.92, 1.08)
    ev.wc_front(U(1.804), seat=0.42, w=0.36, bottom=0.25)
    ev.bidet_mixer(U(1.50), 0.575)
    # porcelain under the frosted window, the window (sill 150 head 210)
    ev.rect(U(1.361), 1.12, U(2.242), H, w=0.2, fc=STONE)
    ev.tiles(U(1.361), 1.12, U(2.242), H, 0.60, 1.20, ou=U(1.804) - 0.30, ov=0.0)
    ev.window(U(1.474), U(2.134), 1.50, 2.10, frosted=True)
    # electrical
    elec_overlay(ev, P, wall, H, depth=0.45)
    # dims
    ev.hchain(H + 0.17, [0, U(1.341), U(1.361), U(2.242)])
    ev.hchain(-0.17, [0, U(0.9485), U(1.50), U(1.804), U(2.242)], above=False, size=3.6)
    ev.vchain(L + 0.24, [0, 0.42, 0.92, 1.08, 1.12, 1.50, 2.10, H])
    ev.vchain(-0.24, [0, 0.92, 1.01, 1.21, 2.10], left=True)
    ev.note(U(0.9485), 2.30, "Rain head 26 (arm 42, see A)")
    ev.note(U(0.9485), 1.21, "Diverter 120 / mixer 100, on the shower centreline")
    ev.note(U(0.6685), 0.95, "Hand shower: holder + wall outlet 92, west end")
    ev.note(U(1.351), 1.70, "Clear glass 10 mm, chrome channel, 200 high", key=True)
    ev.note(U(1.95), 1.11, "Porcelain ledge on the frame box, top 112")
    ev.note(U(1.70), 1.00, "Flush plate 24 x 16 at 92-108 (access to cistern)")
    ev.note(U(1.95), 0.40, "Wall-hung WC 36 x 54, seat 42; concealed frame in a 30 cm box", key=True)
    ev.note(U(1.50), 0.575, "Bidet mixer (plain, no spray gun) 55")
    ev.note(U(1.80), 1.80, "Frosted window 66 x 60, sill 150 (existing); porcelain reveals")
    ev.place_notes(at=L + 0.40, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def mb_elev_C(P, s, x, y, sc=25):
    """East wall (bedroom partition), seen from the room; WC bay on the left in side view, door at the right."""
    H = P.m.ceiling
    Y0, Y1 = MB["y0"], MB["y1"]
    wall = Wall((2.242, Y1), (2.242, Y0))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda yy: Y1 - yy
    std_frame(ev, L, H)
    ev.rect(0, 0, L, H, w=0.15, fc="#f6f3ee")
    ev.text(U(7.4), 2.35, "limewash plaster above 120 / porcelain splash zone TO CONFIRM", size=3.2, c=GREY)
    # WC box cut (y 8.73-9.02) and pan in side view
    ev.cutwall(0, U(8.73), 0, 1.12, fc="#d9d4cb", hatch="////")
    ev.wc_side(U(8.73), 1, seat=0.42, L=0.54)
    ev.rect(0, 1.12, U(8.81), H, w=0.25, fc="#d6d6d6", hatch="xx")
    ev.text(U(8.915), 1.9, "shower build-out\n(cut)", size=3.0, rot=90)
    # shower glass end (side view) from 8.81 to 8.12
    ev.glass(U(8.81), 0.0, U(8.12), 2.0)
    # towel rail and hooks
    ev.towel_rail(U(7.663) - 0.30, U(7.663) + 0.30, 1.15)
    for yy in (7.283, 7.133, 6.983):
        ev.hook(U(yy), 1.45)
    # door D01 at the right end (on the south wall, seen in section): leaf open against this wall
    ev.rect(U(6.135) - 0.0, 0, L, 2.10, w=0.0, c="none", fc="white")
    ev.rect(U(6.825), 0.01, U(6.135) - 0.05, 2.10, w=0.3, fc="#efe3cc", z=ev.z + 3)
    ev.text((U(6.825) + U(6.135) - 0.05) / 2, 1.05, "door leaf\n(open)", size=3.2, z=14)
    elec_overlay(ev, P, wall, H, depth=0.45)
    ev.hchain(H + 0.17, [0, U(8.73), U(8.12), U(7.663), U(6.825), L])
    ev.vchain(L + 0.24, [0, 0.42, 1.12, 1.15, 1.45, 2.10, H])
    ev.note(U(8.45), 0.42, "WC pan 54 long, seat 42 (side view)")
    ev.note(U(8.85), 0.8, "Frame box 30 deep x 112 (cut)")
    ev.note(U(8.4), 1.6, "Glass screen 69 long x 200 (side view)", key=True)
    ev.note(U(7.663), 1.15, "Towel rail (unheated), ~60 wide; height TO CONFIRM")
    ev.note(U(7.13), 1.45, "3 champagne-bronze hooks at 145")
    ev.note(U(6.5), 1.7, "Door D01 71 opening, leaf 69, opens in against this wall")
    ev.place_notes(at=L + 0.40, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def mb_elev_D(P, s, x, y, sc=25):
    """South wall (door wall), cut at y 6.40 through the vanity: vanity and cabinet in section."""
    H = P.m.ceiling
    X0, X1 = MB["x0"], MB["x1"]
    wall = Wall((X1, 6.135), (X0, 6.135))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda xx: X1 - xx
    std_frame(ev, L, H)
    ev.rect(0, 0, L, H, w=0.15, fc="#f6f3ee")
    ev.door(U(2.095), U(1.386), head=2.10, hinge="left", frame=0.05)
    # slats on the west wall (cut at the right) and vanity / cabinet in section
    ev.rect(U(0.576), 0, U(0.556), H, w=0.25, fc="#e3cfae")
    ev.rect(U(1.156), 0.30, U(0.576), 0.80, w=0.3, fc=WOOD, hatch="////", z=ev.z + 3)
    ev.rect(U(1.156), 0.80, U(0.576), 0.86, w=0.3, fc="#f4f2ee", hatch="....", z=ev.z + 3)
    ev.rect(U(0.876), 1.32, U(0.576), 2.07, w=0.3, fc=WOOD, hatch="////", z=ev.z + 3)
    ev.rect(U(0.876), 1.33, U(0.870), 2.06, w=0.1, fc="#f2f5f7", z=ev.z + 3.1)
    for v in (1.508, 1.687, 1.865):
        ev.line([U(0.831), U(0.588)], [v, v], w=0.2, c=GREY, z=ev.z + 3.2)
    ev.led(U(1.076), 0.285, U(0.606), 0.285)
    elec_overlay(ev, P, wall, H, depth=0.45)
    ev.hchain(H + 0.17, [0, U(2.095), U(1.386), U(1.156), U(0.876), L])
    ev.vchain(-0.24, [0, 0.30, 0.80, 0.86, 1.32, 2.07, 2.10, H], left=True)
    ev.note(U(1.74), 1.05, "Door D01: opening 71, leaf 69, flush honey-oak, head 210; hinge on the east jamb, opens in", key=True)
    ev.note(U(0.85), 0.55, "Vanity in section: 58 deep, carcass 30-80 (drawers)")
    ev.note(U(0.85), 0.84, "Marble top 6 cm, top 86")
    ev.note(U(0.72), 1.69, "Cabinet 30 deep, 3 glass shelves, mirror leaves")
    ev.note(U(0.566), 2.35, "Oak slats on battens (cut)")
    ev.place_notes(at=L + 0.40, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def shower_floor_section(P, s, x, y, sc=10):
    """S1: shower floor build-up at the drain end (partition face = 0, build-out face = 1.35), recommended."""
    ev, w, h = view(s, x, y, (0.80, 1.62), (-0.15, 0.24), sc)
    L = 1.35
    fall = 0.022
    z = lambda u: -0.012 - fall * u / L          # finished tile level
    ev.rect(0.80, -0.15, 1.60, -0.10, w=0.3, fc="#d9d9d9", hatch="..", z=ev.z + 1)
    ev.text(0.84, -0.125, "RC slab", size=3.8, ha="left", z=14)
    ev.poly([(0.80, -0.10), (L, -0.10), (L, z(L) - 0.018), (0.80, z(0.80) - 0.018)], fc="#ececec", hatch="....", w=0.2, z=ev.z + 1)
    ev.poly([(0.80, z(0.80) - 0.018), (L - 0.08, z(L - 0.08) - 0.018), (L - 0.08, z(L - 0.08)), (0.80, z(0.80))], fc="white", w=0.25, z=ev.z + 2)
    for i in range(1, 9):
        u = 0.80 + i * 0.06
        ev.line([u, u], [z(u) - 0.018, z(u)], w=0.1, c=GREY, z=ev.z + 2.1)
    ev.line([0.80, L, L], [-0.098, -0.098, 0.20], w=0.7, c=HL, z=ev.z + 4)
    ev.rect(L - 0.08, z(L) - 0.035, L, z(L), w=0.3, fc="white", z=ev.z + 3)     # channel
    ev.line([L - 0.075, L - 0.005], [z(L) - 0.002, z(L) - 0.002], w=0.6, c=INK, z=ev.z + 3.1)
    ev.rect(L - 0.06, -0.10, L - 0.02, z(L) - 0.035, w=0.2, fc="white", z=ev.z + 3)   # outlet
    ev.cutwall(L, L + 0.21, -0.10, 0.24, fc="#d6d6d6", hatch="xx")
    ev.rect(L - 0.01, z(L), L, 0.24, w=0.2, fc="white", z=ev.z + 3)                     # wall tile
    ev.text(L + 0.105, 0.10, "build-out 21", size=3.8, rot=90)
    # break line
    ev.line([0.82, 0.83, 0.81, 0.82], [-0.16, 0.0, 0.02, 0.24], w=0.2, c=GREY)
    ev.vchain(1.10, [z(1.10), 0.0], txt=["fall"], size=3.8)
    ev.note(1.00, z(1.00), "Porcelain 2 cm on full-bed flexible adhesive (C2TE S1); grout joints run to the drain")
    ev.note(1.05, z(1.05) - 0.03, "Sand-cement screed laid to a 1.5-2 % fall toward the drain (2 cm over the 135 run), no flat spots")
    ev.note(0.95, -0.098, "Waterproofing membrane ON THE SLAB, under the screed, clamped in the drain flange; turned up 15 cm on all bathroom walls and to >= 200 inside the shower", key=True)
    ev.note(L - 0.04, z(L) - 0.02, "Linear drain ~70 cm along the build-out, 50 mm outlet with trap, falls >= 1 % to the stack: position and route TO CONFIRM (not in Main or the Lotus TP)", key=True)
    ev.place_notes(at=1.66, size=4.0, wrap_chars=78, vmin=-0.15, vmax=0.24)
    return ev, w, h


def wc_section(P, s, x, y, sc=20):
    """S2: wall-hung WC on a concealed frame inside the 30 cm box (generic, per the frame maker)."""
    ev, w, h = view(s, x, y, (-0.42, 0.66), (-0.12, 1.65), sc)
    ev.floor(-0.42, 0.62, depth=0.10)
    ev.cutwall(-0.42, -0.30, -0.10, 1.65)            # north wall
    ev.rect(-0.30, 0, 0.0, 1.12, w=0.35, fc="white")  # box
    ev.rect(-0.27, 0.0, -0.20, 1.06, w=0.2, fc="#e6e6e6", hatch="xx")   # steel frame
    ev.rect(-0.20, 0.62, -0.05, 1.00, w=0.2, fc="white", r=0.02)        # cistern
    ev.text(-0.125, 0.81, "cistern", size=3.0, rot=90)
    ev.rect(-0.30, 1.10, 0.02, 1.12, w=0.3, fc="white")
    ev.rect(0.0, 0.92, 0.012, 1.08, w=0.3, fc="#d9cfa8")
    ev.wc_side(0.0, 1, seat=0.42, L=0.54)
    ev.line([-0.27, 0.0], [0.23, 0.23], w=1.2, c="#9a9a9a")
    ev.line([-0.27, -0.27], [0.23, -0.06], w=1.2, c="#9a9a9a")
    ev.text(-0.36, 0.08, "Ø110", size=3.2, rot=90)
    ev.vchain(0.60, [0, 0.42, 0.92, 1.08, 1.12])
    ev.hchain(1.30, [-0.30, 0.0, 0.54])
    ev.note(-0.235, 0.5, "Branded concealed frame (Geberit / Grohe / Ideal class) fixed to floor + wall")
    ev.note(-0.125, 0.95, "Cistern serviced through the flush-plate opening")
    ev.note(0.27, 0.42, "Seat 40-42 from finished floor (frame height set from FFL)", key=True)
    ev.note(-0.27, 0.10, "Waste Ø110 to the stack, fall >= 1 %; route TO CONFIRM by plumber")
    ev.note(0.0, 1.11, "Box: steel studs or blocks, cement board, porcelain; top ledge 112")
    ev.place_notes(at=0.68, size=4.0, wrap_chars=26, vmin=-0.1, vmax=1.65)
    return ev, w, h


def fixture_table(s, x, y, rows, title, widths=(44, 26, 18, 13)):
    s.text(x, y, title, size=6, weight="bold")
    cols = [("Item", widths[0], "left"), ("Size (cm)", widths[1], "left"), ("Height (cm)", widths[2], "left"), ("Ref", widths[3], "left")]
    return s.table(x, y - 2.5, cols, rows, size=4.4, row_h=3.2, hl_rows=tuple(i for i, r in enumerate(rows) if "CONFIRM" in " ".join(r).upper()))


MB_ROWS = [
    ["Vanity, floating, oak veneer, 2 drawers", "110 x 58", "30-80", "A, D"],
    ["Marble top + inset basin (centred)", "110 x 58 x 6", "top 86", "A"],
    ["Wall spout + concealed mixer", "-", "100-106", "A"],
    ["Mirrored medicine cabinet, 3 shelves", "80 x 75 x 30", "132-207", "A, D"],
    ["Instant heater 7.5 kW (in the vanity)", "24 x 37", "37-74", "P02"],
    ["Shower, walk-in", "78.5 x 135", "-", "Plan"],
    ["Thermostatic mixer / 3-way diverter", "dia 15 / 12", "100 / 120", "B"],
    ["Rain head on wall arm (42)", "dia 26", "210", "A, B"],
    ["Hand shower holder + outlet", "-", "92-125", "B"],
    ["Fold-up teak seat", "45 x 35", "top 45", "A"],
    ["Fixed glass screen 10 mm + channel", "69 long", "0-200", "B, C"],
    ["Partition niche, 2 slab shelves, LED", "67 x 13.5", "89.5-174", "C note"],
    ["Wall-hung WC on concealed frame", "36 x 54", "seat 42", "B, S2"],
    ["Frame box with porcelain ledge", "88 x 30", "top 112", "B, S2"],
    ["Flush plate (dual)", "24 x 16", "92-108", "B"],
    ["Bidet mixer (no spray gun)", "-", "55", "B"],
    ["Towel rail (unheated)", "~60", "TO CONFIRM", "C"],
    ["Hooks x3, champagne bronze", "-", "145", "C"],
    ["Linear floor drain", "~70", "floor", "S1 CONFIRM"],
    ["Exhaust fan (ceiling, ducted out)", "-", "ceiling", "C401"],
]

GB_ROWS = [
    ["Drop-in bath Duravit Slim (acrylic)", "170 x 75", "rim 55", "A, C, S3"],
    ["Bath deck, porcelain, wall to wall", "95 x 230", "top 55", "A, C, D"],
    ["Fixed glass screen, black frame", "121 long", "56-231", "A, C"],
    ["Concealed thermostatic mixer (plate)", "18 x 18", "96-114", "A"],
    ["Bath spout", "15 out", "66-69", "A"],
    ["Hand spray outlet + holder", "-", "110-127", "A"],
    ["Shower head on wall arm (35)", "dia 25", "225", "A, C"],
    ["Niches x2, walnut-lined, LED", "25 x 27 deep", "80-200", "D"],
    ["Niche shelves (4 per niche)", "-", "105/130/155/180", "D"],
    ["Wall-hung WC on low frame", "36 x 54", "seat 42", "A"],
    ["Flush panel walnut + brass button", "24 x 16", "68-84", "A"],
    ["Bidet mixer / roll holder", "-", "57 / 60-72", "A"],
    ["Stone counter (travertine look)", "230 x 57 x 13", "72-85", "B"],
    ["Vessel basin (wide, low)", "60 x 40", "85-96", "B"],
    ["Wall spout + 2 handles", "-", "102-105", "B"],
    ["Rounded mirror, bronze frame", "104 x 88", "112-200", "B"],
    ["Floating walnut drawers (5 fronts)", "228 x 52", "20-50", "B"],
    ["Open shelf with baskets", "-", "50-72", "B"],
    ["Floor drain", "-", "floor", "TO CONFIRM"],
    ["Exhaust fan (ceiling, ducted out)", "-", "ceiling", "C401"],
]


def sheet_master(P):
    out = []
    refs = {"A": "D602.2", "B": "D602.3", "C": "D602.4", "D": "D602.5"}
    # .1 plan + fixture schedule
    s = P.new("A4", "D602.1", "Master bathroom - plan & fixture schedule", "1:25", "Plan with elevation marks A-D; every fixture with size and height")
    ax, w, h = mb_plan(P, s, s.m + 4, s.m + 22, refs=refs)
    title_under(s, None, s.m + 4, s.m + 12, "P", "PLAN - master bathroom", scale="1:25")
    fixture_table(s, s.m + 110, s.H - s.m - 6, MB_ROWS, "FIXTURE SCHEDULE (heights from finished floor)")
    side_notes(s, [
        "Front-on views from inside the bathroom; heights in cm from finished floor (FFL). Plan dimensions are finished faces from the Main model.",
        "Orange = dimensions, key callouts, LED lines and electrical points (letters + height, from E2xx).",
        "Shower 78.5 clear x 135 deep, walk-in (66 entry) beside a 69 fixed glass screen. Floor drain and falls are NOT in Main or in the Lotus TP: proposed linear drain at the build-out, TO CONFIRM.",
        "Tile module: Main gives the finish (stone-look porcelain), not the size. 60 x 120 is drawn as a setting-out guide, TO CONFIRM with the tiler before the first tile.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    # .2 A + S1
    s = P.new("A4", "D602.2", "Master bathroom - west wall", "1:25 / 1:10", "Vanity, cabinet, shower seat and shower set; S1 shower floor at the drain")
    ev, w, h = mb_elev_A(P, s, s.m + 4, s.m + 62)
    title_under(s, None, s.m + 4, s.m + 55, "A", "ELEVATION A - west wall (vanity + shower)", scale="1:25")
    ev, w2, h2 = shower_floor_section(P, s, s.m + 4, s.m + 12, sc=10)
    title_under(s, None, s.m + 4, s.m + 6, "S1", "SECTION S1 - shower floor at the drain (recommended)", scale="1:10")
    side_notes(s, [
        "Vanity 110 x 58, floating 30-80, marble top to 86 (Main, 31 Oct 2026). Medicine cabinet 80 x 75, bottom 132, 30 deep, centred on the basin.",
        "Shower: concealed mixer and diverter bodies set to the finished tile face of the 21 build-out.",
        "Waterproof the whole bathroom floor with 15 cm upstands, and the shower walls to at least 200; flood test 24-48 h before tiling (KB E2).",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    # .3 B
    s = P.new("A4", "D602.3", "Master bathroom - north wall", "1:20", "Shower back (build-out) and the WC bay with frame box and frosted window")
    ev, w, h = mb_elev_B(P, s, s.m + 6, s.m + 24, sc=20)
    title_under(s, None, s.m + 6, s.m + 16, "B", "ELEVATION B - north wall (shower back + WC)", scale="1:20")
    side_notes(s, [
        "WC bay 88 wide: concealed frame in a 30 cm box to 112, porcelain-clad with a porcelain top ledge; flush plate centred on the pan.",
        "Glass screen: 10 mm toughened clear glass in a chrome floor/wall channel, 200 high, 69 long.",
        "Frosted window W01 66 x 60, sill 150 (existing opening).",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 20, metres=1, step=0.25, label="SCALE 1:20")
    out.append(s)
    # .4 C
    s = P.new("A4", "D602.4", "Master bathroom - east wall", "1:25", "WC in side view, glass screen end, towel rail, hooks, door leaf")
    ev, w, h = mb_elev_C(P, s, s.m + 18, s.m + 24)
    title_under(s, None, s.m + 18, s.m + 16, "C", "ELEVATION C - east wall (bedroom partition)", scale="1:25")
    side_notes(s, [
        "Partition niche (shower face of the partition, not seen in A-D): 67 wide x 13.5 deep finished, 89.5 to 174, porcelain slab shelves at 119 and 148.5 (4 cm), warm LED under each top; driver in the dry cabinet (L-207).",
        "Exhaust fan in the ceiling (F-112, own key), ducted to outside with a back-draft flap; presence sensor S-175.",
        "Hooks and towel rail need solid backing in the partition.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    # .5 D + S2
    s = P.new("A4", "D602.5", "Master bathroom - south wall & WC section", "1:25 / 1:20", "Door wall with the vanity in section; S2 wall-hung WC on its frame")
    ev, w, h = mb_elev_D(P, s, s.m + 2, s.m + 24)
    title_under(s, None, s.m + 2, s.m + 16, "D", "ELEVATION D - south (door) wall", scale="1:25")
    ev, w2, h2 = wc_section(P, s, s.m + 136, s.m + 60, sc=20)
    title_under(s, None, s.m + 130, s.m + 52, "S2", "SECTION S2 - WC frame box", scale="1:20")
    side_notes(s, [
        "WC frame: choose the brand before first fix; box size and flush plate position follow its installation sheet.",
        "Bathroom door: moisture-resistant leaf and frame, 1 cm undercut for make-up air to the fan.",
        "Heater 7.5 kW in the vanity (P02): dedicated circuit + isolator; keep the vanity back removable for service.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    return out


# =====================================================================================================================
# GUEST BATHROOM
# =====================================================================================================================
GB = dict(x0=12.115, x1=14.662, y0=6.891, y1=9.186)
TRAV = "#ece4d6"     # travertine-look porcelain
OAKB = "#e8d6b8"


def gb_tiles(ev, u0, u1, ou, v0=0.0, v1=None, H=2.60):
    """Guest bath wall tiles: 80 strip below, 120 x 60 vertical 80-200, 60 strip above 200 (decided 9 Nov 2026)."""
    v1 = H if v1 is None else v1
    ev.rect(u0, v0, u1, v1, w=0.2, fc=TRAV)
    ev.tiles(u0, max(v0, 0.0), u1, v1, 0.60, 2.60, ou=ou, ov=0.0)
    ev.hjoints([v for v in (0.80, 2.00) if v0 < v < v1], u0, u1)


def gb_plan(P, s, x, y, sc=25, refs=None):
    X0, X1, Y0, Y1 = GB["x0"], GB["x1"], GB["y0"], GB["y1"]
    ax, w, h = plan_view(P, s, x, y, (X0 - 0.55, X1 + 0.04), (Y0 - 0.28, Y1 + 0.50), sc)
    plan_label(ax, 12.59, 8.25, "BATH 170 x 75\ndrop-in, rim 55", 3.6, weight="bold")
    plan_label(ax, 12.59, 7.04, "niches x2\n(build-out 30)", 3.2)
    plan_label(ax, 13.572, 8.80, "WC", 3.8, weight="bold")
    plan_label(ax, 14.36, 8.60, "COUNTER 230 x 57\ntop 85", 3.4, rot=90)
    plan_label(ax, 13.55, 7.45, "GUEST\nBATHROOM", 4.2, weight="bold")
    ax.plot([12.982, 12.982], [7.978, 9.192], color=HL, lw=lw(0.5), zorder=12)
    plan_label(ax, 13.03, 8.40, "glass 121", 3.0, c=HL, ha="left", rot=90)
    ax.add_patch(Circle((13.40, 7.35), 0.05, fc="white", ec=HL, lw=lw(0.3), ls=(0, (2, 1)), zorder=12))
    plan_label(ax, 13.40, 7.24, "floor drain (P10)\nTO CONFIRM", 2.8, c=HL)
    pdim(ax, (X0, Y1), (X1, Y1), off=0.42)
    pdim(ax, (X0, Y1), (13.065, Y1), off=0.30)
    pdim(ax, (13.065, Y1), (14.06, Y1), off=0.30)
    pdim(ax, (14.06, Y1), (X1, Y1), off=0.30)
    pdim(ax, (X0, Y0), (X0, Y1), off=0.42)
    pdim(ax, (X0, Y0), (X0, 7.191), off=0.30)
    pdim(ax, (X0, 7.191), (X0, Y1), off=0.30)
    pdim(ax, (13.103, Y0), (13.968, Y0), "86.5 door", off=-0.16, size=3.6)
    markers4(ax, 13.62, 8.02, refs)
    return ax, w, h


def gb_elev_A(P, s, x, y, sc=25):
    """North wall, cut at y 8.55 looking north: bath in section, shower set, WC under the window, counter in section."""
    H = P.m.ceiling
    X0, X1 = GB["x0"], GB["x1"]
    wall = Wall((X0, 9.186), (X1, 9.186))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda xx: xx - X0
    std_frame(ev, L, H)
    gb_tiles(ev, 0, U(14.63), ou=U(12.59), H=H)
    # oak battens on the east wall, seen in section at the right
    ev.rect(U(14.63), 0, L, H, w=0.25, fc=OAKB, hatch="||||", z=ev.z + 3)
    # window W05 (sill 90, head 210) with porcelain reveals
    ev.window(U(13.276), U(14.256), 0.90, 2.10, frosted=True)
    # bath deck + tub in section
    ev.hatch_box(0, 0, U(12.215), 0.55, "brick")
    ev.hatch_box(U(12.965), 0, U(13.065), 0.55, "brick")
    ev.rect(0, 0.535, U(13.065), 0.55, w=0.3, fc=TRAV, z=ev.z + 3)
    tub = [(U(12.215), 0.55), (U(12.24), 0.52), (U(12.30), 0.14), (U(12.36), 0.09), (U(12.82), 0.09), (U(12.88), 0.14),
           (U(12.94), 0.52), (U(12.965), 0.55)]
    ev.poly(tub, fc="white", w=0.45, closed=False, z=ev.z + 3)
    ev.rect(U(12.215), 0.0, U(12.965), 0.09, w=0.15, fc="#efefef", hatch="..", z=ev.z + 2.5)
    ev.text(U(12.59), 0.30, "bath (section)", size=3.4, z=14)
    # glass screen edge-on on the deck
    ev.rect(U(12.962), 0.55, U(13.002), 2.31, w=0.3, fc=DARK, z=ev.z + 4)
    # bath/shower set on the north wall
    ev.plate(U(12.546), 1.05, w=0.18, h=0.18)
    ev.spout(U(12.546), 0.675)
    ev.hand_shower(U(12.296), 1.18, v_out=1.10)
    ev.rain_front(U(12.546), 2.25, dia=0.25)
    ev.line([U(12.546), U(12.546)], [2.25, 2.262], w=0.4)
    # WC, flush panel, bidet mixer, roll holder
    ev.rect(U(13.452), 0.68, U(13.692), 0.84, w=0.3, fc=WOOD, z=ev.z + 4)
    ev.grain(U(13.452), 0.68, U(13.692), 0.84, n=2)
    ev.rect(U(13.512), 0.74, U(13.632), 0.78, w=0.25, fc="#d9cfa8", r=0.006, z=ev.z + 4.2)
    ev.wc_front(U(13.572), seat=0.42, w=0.36, bottom=0.25)
    ev.bidet_mixer(U(13.272), 0.577)
    ev.roll(U(13.862), 0.70)
    # counter in section (x 14.06-14.63): stone slab, walnut unit, baskets, LEDs
    ev.rect(U(14.06), 0.72, U(14.63), 0.85, w=0.35, fc=TRAV, hatch="....", z=ev.z + 3.5)
    ev.rect(U(14.11), 0.20, U(14.63), 0.50, w=0.35, fc=WOOD, hatch="////", z=ev.z + 3.5)
    ev.rect(U(14.28), 0.50, U(14.56), 0.60, w=0.2, fc="#e6dccb", z=ev.z + 3.5)
    ev.led(U(14.15), 0.19, U(14.60), 0.19)
    ev.led(U(14.56), 0.712, U(14.61), 0.712)
    elec_overlay(ev, P, wall, H, depth=0.45)
    plumb_overlay(ev, P, wall, depth=0.6)
    ev.hchain(H + 0.17, [0, U(12.215), U(12.546), U(12.965), U(13.065), U(13.276), U(13.572), U(14.256), L])
    ev.hchain(-0.17, [U(12.115), U(12.59), U(13.065), U(14.06), L], above=False)
    ev.vchain(-0.24, [0, 0.55, 0.675, 0.80, 0.96, 1.14, 2.00, 2.25, H], left=True)
    ev.vchain(L + 0.24, [0, 0.20, 0.42, 0.50, 0.72, 0.85, 0.90, 2.10, H])
    ev.note(U(12.30), 1.90, "Travertine-look porcelain 120 x 60 vertical, 80-200; 80 strip below, 60 strip above; joint set out from x 12.59 (niche joint)", key=True)
    ev.note(U(12.546), 2.25, "Head 25 on a 35 cm wall arm, 225")
    ev.note(U(12.546), 1.05, "Concealed thermostatic mixer, square brass plate 18 x 18, 96-114")
    ev.note(U(12.296), 1.20, "Hand spray: outlet 110 + holder 116-120")
    ev.note(U(12.546), 0.675, "Bath spout 66-69, 15 out")
    ev.note(U(12.70), 0.30, "Drop-in bath (Duravit Slim 170 x 75) on a brick deck, rim 55; see S3")
    ev.note(U(12.982), 1.60, "Fixed glass 8-10 mm, black frame, 56-231 (edge-on)")
    ev.note(U(13.80), 1.50, "Window W05 98 wide, sill 90, head 210 (existing); obscure film / frosted TO CONFIRM")
    ev.note(U(13.572), 0.80, "Walnut flush panel 24 x 16 at 68-84, brass button (low frame under the sill)", key=True)
    ev.note(U(13.572), 0.35, "Wall-hung WC, seat 42")
    ev.note(U(13.272), 0.577, "Bidet mixer 57")
    ev.note(U(13.862), 0.66, "Roll holder 60-72")
    ev.note(U(14.35), 0.785, "Counter (section): travertine slab 72-85, walnut unit 20-50, baskets on the open shelf")
    ev.place_notes(at=L + 0.42, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def gb_elev_B(P, s, x, y, sc=25):
    """East wall: the counter run with the vessel basin, rounded mirror and oak battens."""
    H = P.m.ceiling
    Y0, Y1 = GB["y0"], GB["y1"]
    wall = Wall((14.662, Y1), (14.662, Y0))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda yy: Y1 - yy
    std_frame(ev, L, H)
    ev.rect(0, 0, L, H, w=0.2, fc=OAKB)
    ev.slats(0, L, 0, H, pitch=0.06)
    # rounded mirror 104 x 88, bronze frame, centred on the basin
    ev.mirror(U(8.27), 1.12, U(7.23), 2.00, r=0.14, frame=0.015)
    # stone counter 72-85 full length, vessel basin centred y 7.75, wall spout + 2 handles
    ev.rect(U(9.175), 0.72, U(6.895), 0.85, w=0.35, fc=TRAV, z=ev.z + 3)
    ev.hjoints([0.785], U(9.175) + 0.01, U(6.895) - 0.01, c="#b9ad98", z=ev.z + 3.3)
    ev.basin_vessel(U(7.75), 0.85, w=0.60, h=0.11)
    ev.spout(U(7.75), 1.035)
    ev.knob(U(7.75) - 0.11, 1.035)
    ev.knob(U(7.75) + 0.11, 1.035)
    ev.led(U(9.135), 0.712, U(6.935), 0.712)
    # open shelf with baskets 50-60, walnut unit 20-50 with 5 fronts, LED under
    for a, b in ((7.6, 7.9), (8.05, 8.35), (8.65, 8.95)):
        ev.rect(U(b), 0.50, U(a), 0.60, w=0.25, fc="#e6dccb", r=0.01, z=ev.z + 3)
        ev.hjoints([0.55], U(b) + 0.01, U(a) - 0.01, c="#b7aa94", z=ev.z + 3.3)
    ev.rect(U(9.175), 0.495, U(6.895), 0.505, w=0.2, fc=WOOD, z=ev.z + 3)
    ev.drawers(U(9.175), U(6.895), 0.20, 0.44, n=5, fc=WOOD)
    ev.rect(U(9.175), 0.44, U(6.895), 0.50, w=0.2, fc=WOOD, z=ev.z + 2.6)
    ev.led(U(9.135), 0.19, U(6.935), 0.19)
    elec_overlay(ev, P, wall, H, depth=0.70)
    ev.hchain(H + 0.17, [0, U(8.27), U(7.75), U(7.23), L])
    ev.hchain(-0.17, [U(9.175), U(8.719), U(8.263), U(7.807), U(7.351), U(6.895)], above=False)
    ev.vchain(-0.24, [0, 0.20, 0.44, 0.50, 0.72, 0.85, 0.96, 1.12, 2.00, H], left=True)
    ev.note(U(7.40), 1.70, "Rounded mirror 104 x 88, brushed-bronze frame, 112-200, centred on the basin", key=True)
    ev.note(U(7.75), 1.035, "Wall spout + 2 handles 102-105 (concealed body in the wall)")
    ev.note(U(7.95), 0.92, "White vessel basin 60 x 40, wide and low, 85-96")
    ev.note(U(8.60), 0.80, "Grey travertine slab 13 thick, 57 deep, top 85, full wall length", key=True)
    ev.note(U(8.80), 0.71, "LED under the slab (warm)")
    ev.note(U(8.20), 0.55, "Open shelf 50-72 with 3 woven baskets")
    ev.note(U(8.00), 0.32, "Floating walnut unit 20-50, 5 push-open fronts")
    ev.note(U(8.50), 0.19, "LED under the unit (floor wash)")
    ev.note(U(8.70), 2.30, "Vertical oak battens on the wall, full height (sealed, splash zone)")
    ev.place_notes(at=L + 0.42, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def gb_elev_C(P, s, x, y, sc=25):
    """West wall, cut at x 13.10 looking west: deck front, glass screen with towels, wood-look plank wall."""
    H = P.m.ceiling
    Y0, Y1 = GB["y0"], GB["y1"]
    wall = Wall((12.115, Y0), (12.115, Y1))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda yy: yy - Y0
    std_frame(ev, L, H)
    ev.rect(0, 0, L, H, w=0.2, fc="#e6d6bd")
    ev.planks(0, L, 0.55, H, pw=0.20, pl=1.20, vertical=True)
    # niche build-out end face (x 13.065, full height)
    gb_tiles(ev, 0, U(7.191), ou=0.0, H=H)
    ev.line([U(7.191), U(7.191)], [0, H], w=0.35, z=ev.z + 2)
    # deck front 0-55 with joints
    ev.rect(U(7.191), 0, L, 0.55, w=0.35, fc=TRAV, z=ev.z + 3)
    ev.vjoints([U(v) for v in (7.487, 8.087, 8.687)], 0, 0.55, z=ev.z + 3.3)
    ev.line([U(7.191), L], [0.55, 0.55], w=0.5, z=ev.z + 3.2)
    ev.poly([(U(7.461), 0.55), (U(7.50), 0.14), (U(7.56), 0.09), (U(9.06), 0.09), (U(9.12), 0.14), (U(9.161), 0.55)],
            w=0.2, c=GREY, closed=False, ls=(0, (4, 2)), z=ev.z + 3.3)
    ev.rect(U(8.30) - 0.15, 0.12, U(8.30) + 0.15, 0.42, w=0.3, c=HL, ls=(0, (3, 1.5)), z=ev.z + 3.4)
    ev.text(U(8.30), 0.27, "access\npanel", size=3.0, c=HL, z=ev.z + 3.5)
    # glass screen with black frame, towels on bars
    ev.glass(U(7.978), 0.55, U(9.192), 2.31, frame=0.03, z=ev.z + 4)
    for a, b in ((8.11, 8.31), (8.91, 9.11)):
        ev.rect(U(a) - 0.01, 1.84, U(b) + 0.01, 1.90, w=0.3, fc=DARK, z=ev.z + 5)
        ev.rect(U(a), 1.20, U(b), 1.85, w=0.25, fc="#f4f1ea", r=0.01, z=ev.z + 5.1)
        ev.line([U(a) + 0.02, U(b) - 0.02], [1.27, 1.27], w=0.08, c=GREY, z=ev.z + 5.2)
    # head on the north wall arm (side)
    ev.rain_side(L, -1, 2.25, arm=0.35, dia=0.25)
    elec_overlay(ev, P, wall, H, depth=0.35)
    ev.hchain(H + 0.17, [0, U(7.191), U(7.978), L])
    ev.hchain(-0.17, [U(7.191), U(7.487), U(8.087), U(8.687), L], above=False)
    ev.vchain(L + 0.24, [0, 0.55, 1.20, 1.84, 1.90, 2.25, 2.31, H])
    ev.vchain(-0.24, [0, 0.80, 2.00, H], left=True)
    ev.note(U(7.08), 1.40, "Niche build-out end, 30 deep, tiled as the walls (niches face the bath, see D)")
    ev.note(U(8.6), 2.45, "Wood-look porcelain planks on the bath wall, above the deck")
    ev.note(U(8.5), 1.60, "Fixed glass screen 121 long, 56-231, slim black frame", key=True)
    ev.note(U(8.21), 1.50, "Towels on 2 black bars at 184-190 fixed to the glass frame (bouclé)")
    ev.note(U(9.0), 2.25, "Head on 35 cm arm (side), 225")
    ev.note(U(7.80), 0.48, "Deck front porcelain, joints at y 7.487 / 8.087 / 8.687; rim 55")
    ev.note(U(8.30), 0.27, "Removable tiled access panel ~30 x 30 to reach the bath waste and trap (recommended, TO CONFIRM)", key=True)
    ev.note(U(9.0), 0.12, "Bath outline behind the deck (dashed)")
    ev.place_notes(at=L + 0.42, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def gb_elev_D(P, s, x, y, sc=25):
    """South wall (door wall), cut at y 7.30: counter in section at the left, door, niche build-out face over the deck."""
    H = P.m.ceiling
    X0, X1 = GB["x0"], GB["x1"]
    wall = Wall((X1, 6.891), (X0, 6.891))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda xx: X1 - xx
    std_frame(ev, L, H)
    gb_tiles(ev, U(14.63), U(13.065), ou=U(12.59), H=H)
    ev.door(U(13.968), U(13.103), head=2.10, hinge="right", frame=0.05)
    # niche build-out face (y 7.191) above the deck, two lit niches
    gb_tiles(ev, U(13.065), L, ou=U(12.59), v0=0.55, H=H)
    ev.niche(U(12.90), 0.80, U(12.65), 2.00, shelves=(1.05, 1.30, 1.55, 1.80), fc="#d8c3a3", t=0.012)
    ev.niche(U(12.53), 0.80, U(12.28), 2.00, shelves=(1.05, 1.30, 1.55, 1.80), fc="#d8c3a3", t=0.012)
    # deck in section
    ev.hatch_box(U(13.065), 0, L, 0.535, "brick")
    ev.rect(U(13.065), 0.535, L, 0.55, w=0.3, fc=TRAV, z=ev.z + 3)
    # oak battens (cut) and counter in section at the left
    ev.rect(0, 0, U(14.63), H, w=0.25, fc=OAKB, hatch="||||", z=ev.z + 3)
    ev.rect(U(14.63), 0.72, U(14.06), 0.85, w=0.35, fc=TRAV, hatch="....", z=ev.z + 3.5)
    ev.rect(U(14.63), 0.20, U(14.11), 0.50, w=0.35, fc=WOOD, hatch="////", z=ev.z + 3.5)
    ev.led(U(14.60), 0.19, U(14.15), 0.19)
    elec_overlay(ev, P, wall, H, depth=0.40)
    ev.hchain(H + 0.17, [0, U(14.06), U(13.968), U(13.103), U(13.065), U(12.90), U(12.65), U(12.59), U(12.53), U(12.28), L])
    ev.vchain(L + 0.24, [0, 0.55, 0.80, 1.05, 1.30, 1.55, 1.80, 2.00, H])
    ev.vchain(-0.24, [0, 0.20, 0.50, 0.72, 0.85, 2.10, H], left=True)
    ev.note(U(13.53), 1.30, "Door D07: opening 86.5, flush honey-oak, head 210, hinge on the west jamb, opens in", key=True)
    ev.note(U(12.775), 1.92, "Two niches 25 wide x 27 deep, 80-200, walnut-lined, warm LED under the top", key=True)
    ev.note(U(12.405), 1.425, "4 walnut shelves per niche at 105 / 130 / 155 / 180")
    ev.note(U(12.59), 2.20, "Niches sit either side of the tile joint at x 12.59; 120 x 60 tiles 80-200")
    ev.note(U(12.80), 0.30, "Bath deck (section), brick + porcelain, top 55")
    ev.note(U(14.35), 0.785, "Counter in section: slab 72-85, unit 20-50")
    ev.place_notes(at=L + 0.42, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def bath_section(P, s, x, y, sc=20):
    """S3: drop-in bath on its brick deck, cut at y 8.3 looking north (recommended build-up)."""
    ev, w, h = view(s, x, y, (11.98, 13.20), (-0.12, 0.70), sc)
    ev.floor(11.98, 13.20, depth=0.10)
    ev.cutwall(11.98, 12.115, -0.10, 0.70)
    ev.rect(12.115, 0, 12.125, 0.70, w=0.2, fc="#e6d6bd", z=ev.z + 3)
    ev.hatch_box(12.125, 0, 12.215, 0.52, "brick")
    ev.hatch_box(12.965, 0, 13.065, 0.52, "brick")
    ev.rect(12.125, 0.52, 12.235, 0.55, w=0.3, fc=TRAV, z=ev.z + 3)
    ev.rect(12.945, 0.52, 13.065, 0.55, w=0.3, fc=TRAV, z=ev.z + 3)
    ev.rect(13.055, 0, 13.065, 0.52, w=0.25, fc=TRAV, z=ev.z + 3)
    tub = [(12.215, 0.55), (12.24, 0.52), (12.30, 0.14), (12.36, 0.09), (12.82, 0.09), (12.88, 0.14), (12.94, 0.52), (12.965, 0.55)]
    ev.poly(tub, fc="white", w=0.5, closed=False, z=ev.z + 4)
    ev.poly([(12.215, 0.55), (12.965, 0.55)], w=0.6, closed=False, z=ev.z + 4)
    for u in (12.40, 12.78):
        ev.rect(u - 0.02, 0.0, u + 0.02, 0.09, w=0.25, fc="#dcdcdc", z=ev.z + 4)
    ev.line([12.115, 13.065], [0.0, 0.0], w=0.7, c=HL, z=ev.z + 5)
    ev.line([12.12, 12.12], [0.0, 0.70], w=0.7, c=HL, z=ev.z + 5)
    ev.rect(12.962, 0.55, 13.002, 0.70, w=0.3, fc=DARK, z=ev.z + 5)
    ev.hchain(0.64, [12.115, 12.215, 12.965, 13.065])
    ev.vchain(13.12, [0, 0.09, 0.55])
    ev.note(12.59, 0.09, "Bath on its adjustable feet on the screeded floor; not hung on the deck edge")
    ev.note(12.17, 0.30, "Brick deck walls 10, rendered, tiled; deck top falls 1 % into the bath")
    ev.note(12.235, 0.55, "Flexible silicone (sanitary) between rim and tiles, after a fill test")
    ev.note(12.12, 0.60, "Membrane on the floor under the bath and up the walls to >= 200 above the shower zone", key=True)
    ev.note(13.06, 0.30, "Access panel in the deck front for the waste/overflow (at the north end, P06)", key=True)
    ev.place_notes(at=13.25, size=4.0, wrap_chars=70, vmin=-0.12, vmax=0.70)
    return ev, w, h


def sheet_guest(P):
    out = []
    refs = {"A": "D603.2", "B": "D603.3", "C": "D603.4", "D": "D603.5"}
    s = P.new("A4", "D603.1", "Guest bathroom - plan & fixture schedule", "1:25", "Plan with elevation marks A-D; every fixture with size and height")
    gb_plan(P, s, s.m + 2, s.m + 22, refs=refs)
    title_under(s, None, s.m + 2, s.m + 12, "P", "PLAN - guest bathroom", scale="1:25")
    fixture_table(s, s.m + 137, s.H - s.m - 6, GB_ROWS, "FIXTURE SCHEDULE (cm from finished floor)", widths=(33, 18, 15, 10))
    side_notes(s, [
        "Front-on views from inside the bathroom; heights in cm from finished floor. Positions from the Main model (9 Nov 2026 decisions).",
        "Tiles: travertine-look porcelain 120 x 60 laid vertical between 80 and 200, an 80 strip below and a 60 strip above. Start the setting-out from the joint at x 12.59 that splits the two niches.",
        "Floor drain is not in Main or in the Lotus TP (TP p.6 gives supply points only): P10 proposed near the door, TO CONFIRM.",
        f"Lotus TP p.9 shows this bathroom with a ceiling 60 cm below the slab and a ducted AC unit above it; Main keeps a flat 260 ceiling and wall splits. See C401-C404.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    specs = [
        ("D603.2", "Guest bathroom - north wall", "Bath and shower set, WC under the window, counter in section", gb_elev_A, "A",
         "ELEVATION A - north wall (bath, WC, counter end)",
         ["Mixer and diverter bodies are set to the finished tile face: fix them after the tile thickness is known.",
          "WC frame is the low type (flush panel 68-84 under the 90 sill): check the frame model fits under the window before ordering.",
          "Bath / shower zone: membrane to at least 200 on the north and west walls, 15 cm upstand elsewhere; flood test 24-48 h."]),
        ("D603.3", "Guest bathroom - east wall", "Counter run with the vessel basin, rounded mirror, oak battens", gb_elev_B, "B",
         "ELEVATION B - east wall (counter + mirror)",
         ["Counter slab on concealed steel brackets / wall fixing; floating unit hung from the wall (no legs). Fix points into blockwork.",
          "Basin waste Ø40 with bottle trap inside the walnut unit; leave a service panel in the unit back.",
          "Oak battens behind a splash zone: sealed oak or wood-look alternative, TO CONFIRM with Karim."]),
        ("D603.4", "Guest bathroom - west wall & bath section", "Deck front, glass screen, plank wall; S3 drop-in bath on its deck", gb_elev_C, "C",
         "ELEVATION C - west wall (deck front + glass)", None),
        ("D603.5", "Guest bathroom - south wall", "Door, two lit niches over the deck, counter in section", gb_elev_D, "D",
         "ELEVATION D - south wall (door + niches)",
         ["Niche boxes: cement board or block lined, waterproofed inside before the walnut lining; walnut must be sealed (wet zone).",
          "LED in each niche: 24 V strip in an aluminium profile with diffuser, driver outside the wet zone (L-209 at 245 on this wall).",
          "Door undercut 1 cm for make-up air to the extract fan."]),
    ]
    for no, title, sub, fn, tag, cap, notes in specs:
        s = P.new("A4", no, title, "1:25" if notes else "1:25 / 1:20", sub)
        if notes:
            fn(P, s, s.m + 6, s.m + 24)
            title_under(s, None, s.m + 6, s.m + 16, tag, cap, scale="1:25")
            side_notes(s, notes)
        else:
            fn(P, s, s.m + 6, s.m + 67)
            title_under(s, None, s.m + 6, s.m + 59, tag, cap, scale="1:25")
            bath_section(P, s, s.m + 6, s.m + 12, sc=20)
            title_under(s, None, s.m + 6, s.m + 6, "S3", "SECTION S3 - drop-in bath on its deck (recommended)", scale="1:20")
            side_notes(s, [
                "Deck walls in brick, rendered and waterproofed before tiling; bath bedded on its own feet, not on the deck edges.",
                "Fill the bath before sealing the rim so the silicone joint is made at full load.",
                "Leave a removable tiled panel in the deck front for the waste and overflow (north end).",
            ])
        s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
        out.append(s)
    return out


# =====================================================================================================================
# DINING BUFFET WALL
# =====================================================================================================================
BW = dict(wall=14.79, front=15.2768, y0=6.787, ych=6.887, ycut=7.487, ynorth=9.5045)
LIME = "#efe6d8"


def buffet_elev(P, s, x, y, sc=25):
    """Dining west wall seen from the dining (looking west): block with lit niche, sideboard, panel, mirror, AC."""
    H = P.m.ceiling
    Y0, YN = BW["y0"], BW["ynorth"]
    wall = Wall((BW["wall"], Y0), (BW["wall"], YN))
    L = wall.L
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    U = lambda yy: yy - Y0
    std_frame(ev, L, H, left_cut=0.0)
    ev.text(-0.10, 1.30, "corridor", size=3.6, c=GREY, rot=90)
    # block (48.7 deep): chamfer face + 60 flat front, limewash
    ev.rect(0, 0, U(BW["ycut"]), H, w=0.35, fc=LIME, z=ev.z + 1)
    ev.line([U(BW["ych"]), U(BW["ych"])], [0, H], w=0.2, z=ev.z + 1.2)
    ev.text(U(6.837), 2.35, "10 x 10\nchamfer", size=3.0, rot=90, z=14)
    ev.line([U(BW["ycut"]), U(BW["ycut"])], [0, H], w=0.45, z=ev.z + 1.3)
    # niche 34 x 25 deep, 0.42-2.20, rounded top, oak shelves, LED under each shelf and the top
    ev.niche(U(7.007), 0.42, U(7.347), 2.20, shelves=(0.885, 1.325, 1.765), r=0.13, fc="#e5dccd", t=0.025)
    for a, b in ((7.056, 7.08), (7.085, 7.111), (7.115, 7.141), (7.146, 7.17)):
        ev.rect(U(a), 1.765, U(b), 1.93, w=0.15, fc="#d9c9b0", z=ev.z + 2.4)
    # wall panel 18.2 deep over the sideboard, mirror and AC on it
    ev.rect(U(BW["ycut"]), 0.83, L, H, w=0.25, fc=LIME, z=ev.z + 0.5)
    ev.pebble(U(8.49575), 1.60, 0.92, 0.80)
    ev.ac_split(U(8.496), 2.42, w=1.05, h=0.30)
    # walnut sideboard 197 x 50, 12-83, 4 fronts, recessed plinth
    ev.rect(U(7.507), 0, U(9.427), 0.12, w=0.25, fc=DARK, z=ev.z + 2)
    ev.drawers(U(7.487), U(9.457), 0.12, 0.80, n=4, fc=WOOD, handles=None)
    ev.grain(U(7.487), 0.12, U(9.457), 0.80, n=5)
    ev.rect(U(7.487), 0.80, U(9.457), 0.83, w=0.3, fc=WOOD, z=ev.z + 2.6)
    elec_overlay(ev, P, wall, H, depth=0.70)
    ev.line([U(8.496), U(8.496)], [0.85, H], w=0.15, c=HL, ls=(0, (8, 2, 1, 2)))
    ev.text(U(8.496), H - 0.04, "CL", size=3.4, c=HL, va="top", bg="white")
    ev.hchain(H + 0.17, [0, U(BW["ych"]), U(7.007), U(7.347), U(BW["ycut"]), U(7.9435), U(9.0485), L])
    ev.hchain(-0.17, [U(7.487), U(8.04975), U(8.94175), U(9.457), L], above=False)
    ev.vchain(-0.24, [0, 0.42, 0.885, 1.325, 1.765, 2.20, H], left=True)
    ev.vchain(L + 0.24, [0, 0.12, 0.83, 1.20, 2.00, 2.12, 2.42, H])
    ev.note(U(7.177), 2.12, "Arched niche 34 wide x 25 deep, 42-220, radius 13; LED under the top", key=True)
    ev.note(U(7.177), 1.10, "3 oak-veneer shelves 2.5 thick at 88.5 / 132.5 / 176.5, warm LED under each")
    ev.note(U(6.837), 0.60, "Block 48.7 deep, limewash; 10 x 10 chamfer on the corridor corner")
    ev.note(U(8.496), 2.27, "Wall split AC 105 x 30, top 242, centred on the wall (CL y 8.496); drain route TO CONFIRM", key=True)
    ev.note(U(8.25), 1.60, "Pebble mirror 92 x 80, 120-200, centred on the same line, glow behind (L-190)", key=True)
    ev.note(U(7.70), 1.30, "Panel 18.2 deep, limewash, carries the mirror and AC (hides pipes + cables)")
    ev.note(U(8.0), 0.81, "Walnut top 3 cm, top 83")
    ev.note(U(8.70), 0.45, "Walnut sideboard 197 x 50, 4 push-open doors, 12-80")
    ev.note(U(8.2), 0.06, "Recessed dark plinth 12 (set back 6)")
    ev.place_notes(at=L + 0.42, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def buffet_plan(P, s, x, y, sc=25):
    """Plan aligned under the elevation: u = y - 6.787 along, d = distance from the wall face (down the page)."""
    Y0, YN = BW["y0"], BW["ynorth"]
    D = BW["front"] - BW["wall"]
    L = YN - Y0
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.80, 0.30), sc)
    U = lambda yy: yy - Y0
    ev.rect(-0.05, 0, L + 0.12, 0.25, w=0.35, fc=POCHE, hatch="////", z=ev.z + 2)
    ev.rect(L, -0.62, L + 0.12, 0.25, w=0.35, fc=POCHE, hatch="////", z=ev.z + 2)
    ch = 0.10
    blk = [(0, 0), (0, -(D - ch)), (ch, -D), (U(BW["ycut"]), -D), (U(BW["ycut"]), 0)]
    ev.poly(blk, fc=LIME, w=0.45, z=ev.z + 2.2)
    ev.rect(U(7.007), -D, U(7.347), -(D - 0.25), w=0.35, fc="white", z=ev.z + 2.4)
    ev.rect(U(7.022), -D + 0.01, U(7.332), -(D - 0.24), w=0.12, c=GREY, ls=(0, (2, 1)), z=ev.z + 2.5)
    ev.rect(U(BW["ycut"]), -0.182, U(9.477), 0, w=0.3, fc=LIME, z=ev.z + 2.2)
    ev.rect(U(7.487), -0.50, U(9.457), -0.182, w=0.35, fc=WOOD, z=ev.z + 2.3)
    ev.rect(U(7.487), -0.50, U(9.457), 0, w=0.35, z=ev.z + 2.35)
    for yy in (7.98, 8.47, 8.963):
        ev.line([U(yy), U(yy)], [-0.50, -0.47], w=0.2, z=ev.z + 2.4)
    ev.rect(U(7.971), -0.412, U(9.021), -0.182, w=0.2, ls=(0, (4, 2)), c=GREY, z=ev.z + 2.6)
    ev.text(U(8.496), -0.30, "AC above (dashed)", size=3.2, c=GREY, z=ev.z + 2.7)
    ev.text(U(8.496), -0.42, "SIDEBOARD 197 x 50", size=3.6, weight="bold", z=ev.z + 2.7)
    ev.text(U(7.177), -0.12, "BLOCK", size=3.4, weight="bold", z=ev.z + 2.7)
    ev.hchain(-0.62, [0, ch, U(BW["ycut"])], above=False)
    ev.hchain(-0.56, [U(7.007), U(7.347)], above=False, size=4.0)
    ev.hchain(-0.62, [U(7.487), U(9.457)], above=False)
    ev.vchain(-0.10, [-D, -(D - ch), 0], left=True, size=4.0)
    ev.vchain(-0.30, [-D, 0], left=True, txt=["48.7 (50)"])
    ev.vchain(U(7.177), [-D, -(D - 0.25)], size=4.0)
    ev.vchain(U(9.30), [-0.50, -0.182, 0], size=4.0)
    ev.note(U(0.05 + Y0), -(D - 0.05), "10 x 10 diagonal on the corridor corner", key=True)
    ev.note(U(7.177), -(D - 0.2), "Niche 34 x 25 deep (arched top)")
    ev.note(U(7.30), -0.25, "60 flat front between the chamfer and the sideboard")
    ev.note(U(9.0), -0.09, "Panel 18.2 deep, full width over the sideboard")
    ev.place_notes(at=L + 0.42, wrap_chars=36, vmin=-0.75, vmax=0.25)
    return ev, w, h


def buffet_section(P, s, x, y, sc=20):
    """S4: cut at y 8.50 looking north - panel, mirror, AC, sideboard (d horizontal, wall on the left)."""
    H = P.m.ceiling
    ev, w, h = view(s, x, y, (-0.30, 0.75), (-0.12, H + 0.15), sc)
    ev.floor(-0.30, 0.70, depth=0.10)
    ev.ceiling(-0.30, 0.70, H, void=0.10)
    ev.cutwall(-0.25, 0.0, -0.10, H + 0.10)
    ev.rect(0, 0.83, 0.182, H, w=0.4, fc=LIME, hatch="xx", z=ev.z + 2)
    ev.rect(0.182, 2.12, 0.412, 2.42, w=0.35, fc="white", r=0.03, z=ev.z + 3)
    ev.rect(0.182, 1.20, 0.205, 2.00, w=0.3, fc="#f2f5f7", z=ev.z + 3)
    ev.led(0.186, 1.18, 0.186, 2.02)
    ev.rect(0.0, 0.12, 0.44, 0.80, w=0.4, fc=WOOD, hatch="////", z=ev.z + 2)
    ev.rect(0.0, 0.80, 0.50, 0.83, w=0.4, fc=WOOD, z=ev.z + 2)
    ev.rect(0.44, 0.12, 0.50, 0.80, w=0.4, fc=WOOD, z=ev.z + 2)
    ev.rect(0.0, 0.0, 0.44, 0.12, w=0.3, fc=DARK, z=ev.z + 2)
    ev.hchain(H + 0.06, [0, 0.182, 0.412], size=4.0)
    ev.hchain(-0.06, [0, 0.44, 0.50], above=False, size=4.0)
    ev.vchain(0.62, [0, 0.12, 0.80, 0.83, 1.20, 2.00, 2.12, 2.42, H], size=4.0)
    ev.note(0.09, 1.6, "Panel: metal stud + 2 x 12.5 board, carries mirror + AC on plywood backing")
    ev.note(0.30, 2.27, "AC 23 deep; pipes + drain hidden in the panel")
    ev.note(0.19, 1.45, "Mirror 92 x 80, LED glow behind")
    ev.note(0.25, 0.45, "Sideboard 50 deep; plinth set back 6")
    ev.place_notes(at=0.80, size=4.0, wrap_chars=24, vmin=0.0, vmax=H)
    return ev, w, h


def niche_section(P, s, x, y, sc=20):
    """S5: cut through the niche at y 7.18 looking north (d horizontal from the wall face)."""
    H = P.m.ceiling
    D = BW["front"] - BW["wall"]
    ev, w, h = view(s, x, y, (-0.30, 0.75), (-0.12, H + 0.15), sc)
    ev.floor(-0.30, 0.70, depth=0.10)
    ev.ceiling(-0.30, 0.70, H, void=0.10)
    ev.cutwall(-0.25, 0.0, -0.10, H + 0.10)
    ev.rect(0, 0, D, 0.42, w=0.4, fc=LIME, hatch="xx", z=ev.z + 2)
    ev.rect(0, 2.20, D, H, w=0.4, fc=LIME, hatch="xx", z=ev.z + 2)
    ev.rect(0, 0.42, D - 0.25, 2.20, w=0.4, fc=LIME, hatch="xx", z=ev.z + 2)
    for v in (0.885, 1.325, 1.765):
        ev.rect(D - 0.25, v - 0.025, D - 0.01, v, w=0.3, fc=WOOD, z=ev.z + 3)
        ev.led(D - 0.22, v - 0.032, D - 0.04, v - 0.032)
    ev.led(D - 0.22, 2.106, D - 0.04, 2.106)
    ev.hchain(H + 0.06, [0, D - 0.25, D], size=4.0)
    ev.vchain(0.62, [0, 0.42, 0.885, 1.325, 1.765, 2.20, H], size=4.0)
    ev.note(D - 0.12, 2.12, "LED in an aluminium channel under the arch, driver L-189 in the block at 40")
    ev.note(D - 0.12, 1.325, "Oak shelves 2.5 on hidden steel pins")
    ev.note(0.12, 0.80, "Block: brick or metal stud + board, 48.7 deep; niche lined with board, edges with angle bead")
    ev.place_notes(at=0.80, size=4.0, wrap_chars=24, vmin=0.0, vmax=H)
    return ev, w, h


def sheet_buffet(P):
    out = []
    s = P.new("A4", "D503.1", "Dining buffet wall - elevation & plan", "1:25", "West wall of the dining: niche block, sideboard, mirror and AC on one centre line")
    buffet_elev(P, s, s.m + 6, s.m + 64)
    title_under(s, None, s.m + 6, s.m + 57, "A", "ELEVATION - dining buffet wall, looking west", scale="1:25")
    buffet_plan(P, s, s.m + 6, s.m + 14)
    title_under(s, None, s.m + 6, s.m + 7, "P", "PLAN - aligned under the elevation", scale="1:25")
    side_notes(s, [
        "Mirror (92 x 80) and AC (105 x 30) are centred on the same vertical line, y 8.496 = middle of the sideboard run (Karim's mock-up).",
        "Sideboard 197 long x 50 deep, top 83; set the panel and block first, then measure the gap and order the sideboard to site size.",
        "Block 48.7 (called 50) deep; 70 run = 10 chamfer + 60 flat front; niche 34 x 25 deep.",
        "AC on a dedicated circuit (P-154 at 230); condensate drain route behind the panel TO CONFIRM.",
        "Lotus TP p.20 shows this wall with wood cladding and no niche block; Main (Karim) governs.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    s = P.new("A4", "D503.2", "Dining buffet wall - sections", "1:20", "S4 through the panel, mirror, AC and sideboard; S5 through the lit niche")
    buffet_section(P, s, s.m + 8, s.m + 22)
    title_under(s, None, s.m + 8, s.m + 14, "S4", "SECTION S4 - panel, AC, sideboard", scale="1:20")
    niche_section(P, s, s.m + 112, s.m + 22)
    title_under(s, None, s.m + 112, s.m + 14, "S5", "SECTION S5 - lit niche", scale="1:20")
    side_notes(s, [
        "Plywood backing (18 mm) inside the panel behind the mirror and AC before boarding.",
        "LED drivers stay reachable: L-189 in the block (at 40, behind a removable panel), L-190 behind the mirror.",
        "All dims in cm; heights from finished floor.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 20, metres=1, step=0.25, label="SCALE 1:20")
    out.append(s)
    return out


# =====================================================================================================================
# TERRACE DOORS (east wall)
# =====================================================================================================================
EW = dict(xin=21.222, xout=21.472, ys=2.07, yn=9.50)


def east_inside(P, s, x, y, sc=50, yr=(2.07, 9.50), notes=True, ul=None):
    """East wall from inside (reception + dining, looking east); left = north."""
    H = P.m.ceiling
    wall = Wall((EW["xin"], yr[1]), (EW["xin"], yr[0]))
    L = wall.L
    U = lambda yy: yr[1] - yy
    k = 25.0 / sc
    ev, w, h = view(s, x, y, ul or (-0.58 / k, L + 1.30 / k), (-0.22 / k, H + 0.34 / k), sc)
    std_frame(ev, L, H, left_cut=0.12 if yr[1] >= 9.49 else 0.0, right_cut=0.12 if yr[0] <= 2.08 else 0.0)
    ev.rect(0, 0, L, H, w=0.15, fc="#f6f1e8")
    # curtain pocket in the ceiling (15 x 15) and the divider pocket (12 x 12)
    pu0, pu1 = max(U(8.379), 0), min(U(2.772), L)
    if pu1 > pu0:
        ev.rect(pu0, H, pu1, H + 0.15, w=0.3, c=HL, ls=(0, (3, 1.5)), z=ev.z + 6)
        ev.text((pu0 + pu1) / 2, H + 0.075, "curtain pocket 15 x 15 in the ceiling", size=3.4 * k ** 0.3, c=HL, bg="white", z=ev.z + 7)
    if 0 <= U(5.651) <= L:
        ev.rect(U(5.711), H, U(5.591), H + 0.12, w=0.3, c=HL, ls=(0, (3, 1.5)), z=ev.z + 6)
    # coffee counter end (north corner)
    if U(9.50) >= -0.01 and U(8.84) <= L:
        ev.rect(max(U(9.50), 0), 0, U(8.84), 0.97, w=0.35, fc=WOOD, hatch="////", z=ev.z + 3)
        ev.rect(max(U(9.50), 0), 0.97, U(8.84), 1.00, w=0.35, fc="#f4f2ee", z=ev.z + 3)
        for v in (1.63, 1.88):
            ev.rect(max(U(9.50), 0), v, U(9.22), v + 0.035, w=0.3, fc=WOOD, z=ev.z + 3)
    # W08 slider (sill 0, head 240) and W07 window (sill 60, head 240)
    if U(6.24) <= L + 0.01:
        ev.window(U(7.979), U(6.24), 0.0, 2.40, kind="slider", panels=2, slide_dir=-1)
        ev.curtain(U(7.979) - 0.30, U(7.979) + 0.05, 0.01, 2.58, sheer=True)
        ev.curtain(U(6.24) - 0.05, U(6.24) + 0.40, 0.01, 2.58, sheer=True)
    if U(3.135) <= L + 0.01 and U(5.195) >= -0.01:
        ev.window(U(5.195), U(3.135), 0.60, 2.40, kind="slider", panels=2, slide_dir=1)
        ev.curtain(U(5.195) - 0.05, U(5.195) + 0.30, 0.01, 2.58, sheer=True)
        ev.curtain(U(3.135) - 0.30, U(3.135) + 0.05, 0.01, 2.58, sheer=True)
        # sofa back in front of the window
        ev.rect(U(5.165), 0.04, U(3.165), 0.86, w=0.25, fc="#ece7de", r=0.04, z=ev.z + 5)
        ev.text(U(4.165), 0.45, "sofa (in front)", size=3.6 * k ** 0.3, c=GREY, z=ev.z + 6)
    elec_overlay(ev, P, wall, H, depth=0.30, size=2.4 * k ** 0.3)
    for yy in (2.82, 8.33):
        if 0 <= U(yy) <= L:
            ev.elec("power", U(yy), 2.53, size=2.4 * k ** 0.3)
            ev.text(U(yy) + 0.08, 2.53, "P 268 (curtain motor, in the pocket)", size=3.2 * k ** 0.3, c=HL, ha="left", bg="white")
    return ev, w, h, L, U


def east_outside(P, s, x, y, sc=50, yr=(1.78, 9.50), ul=None):
    """East wall from the terrace (looking west); left = south. Seat and BBQ counter ends in section."""
    wall = Wall((EW["xout"], yr[0]), (EW["xout"], yr[1]))
    L = wall.L
    U = lambda yy: yy - yr[0]
    inr = lambda a, b: a >= yr[0] - 0.01 and b <= yr[1] + 0.01
    k = 25.0 / sc
    ev, w, h = view(s, x, y, ul or (-0.58 / k, L + 1.30 / k), (-0.22 / k, 3.10 + 0.20 / k), sc)
    ev.floor(-0.12 if yr[0] < 1.8 else 0, L + (0.12 if yr[1] > 9.49 else 0), depth=0.10)
    ev.rect(0, 0, L, 2.96, w=0.15, fc="#efebe4")
    ev.rect(-0.12 if yr[0] < 1.8 else 0, 2.96, L + 0.12, 3.10, w=0.3, fc=POCHE, hatch="////", z=ev.z + 2)
    ev.line([0, L], [2.80, 2.80], w=0.2, c=GREY, ls=(0, (6, 3)))
    ev.text(L / 2, 2.88, "terrace slatted wood ceiling (Lotus TP p.9) - level TO CONFIRM", size=3.6, c=GREY, bg="white")
    if inr(3.135, 5.195):
        ev.window(U(3.135), U(5.195), 0.60, 2.40, kind="slider", panels=2)
    if inr(6.24, 7.979):
        ev.window(U(6.24), U(7.979), 0.0, 2.40, kind="slider", panels=2, slide_dir=1)
    for yy, v0, v1 in ((2.45, 2.06, 2.34), (5.775, 1.86, 2.14), (8.60, 1.86, 2.14)):
        if inr(yy, yy):
            ev.rect(U(yy) - 0.04, v0, U(yy) + 0.04, v1, w=0.3, fc="#d9c08a", r=0.01, z=ev.z + 4)
    if inr(1.78, 2.68):
        ev.rect(U(1.78), 0, U(1.98), 0.93, w=0.35, fc="#e8e0d2", hatch="////", z=ev.z + 3)
        ev.rect(U(1.78), 0.88, U(1.98), 0.93, w=0.2, fc="#bfae92", hatch=".o", z=ev.z + 3.1)
        ev.rect(U(1.98), 0, U(2.08), 0.93, w=0.35, fc="#e8e0d2", hatch="////", z=ev.z + 3)
        ev.rect(U(1.98), 0.93, U(2.08), 0.95, w=0.3, fc="#cfc8bb", z=ev.z + 3)
        ev.rect(U(2.08), 0.06, U(2.56), 0.36, w=0.35, fc="#f0d7c8", hatch="////", z=ev.z + 3)
        ev.rect(U(2.62), 0.06, U(2.68), 0.36, w=0.3, fc=WOOD, z=ev.z + 3.1)
        ev.rect(U(2.084), 0.36, U(2.68), 0.40, w=0.3, fc=WOOD, z=ev.z + 3.1)
        ev.rect(U(2.11), 0.40, U(2.66), 0.45, w=0.25, fc="#efe9df", r=0.02, z=ev.z + 3.2)
        ev.rect(U(2.09), 0.44, U(2.29), 0.86, w=0.25, fc="#e3e6dd", r=0.03, z=ev.z + 3.2)
    if inr(8.78, 9.27):
        ev.rect(U(8.80), 0.08, U(9.27), 0.90, w=0.35, fc="#f0d7c8", hatch="////", z=ev.z + 3)
        ev.rect(U(8.78), 0.90, U(9.27), 0.94, w=0.3, fc="#cfc8bb", z=ev.z + 3.1)
        ev.rect(U(9.25), 0.94, U(9.27), 1.30, w=0.3, fc="#cfc8bb", z=ev.z + 3.1)
        ev.rect(U(8.80), 0.08, U(8.86), 0.90, w=0.3, fc=WOOD, z=ev.z + 3.2)
        ev.led(U(8.83), 0.056, U(8.85), 0.056)
    elec_overlay(ev, P, wall, 2.9, depth=0.12, size=2.4 * k ** 0.3)
    return ev, w, h, L, U


def sheet_terrace_doors(P):
    out = []
    H = P.m.ceiling
    s = P.new("A4", "D504", "Terrace doors - inside & outside", "1:50",
              "Window W07 and slider W08 as seen standing in the room and standing on the terrace")
    ev, w, h, L, U = east_inside(P, s, s.m + 6, s.m + 112, sc=50)
    ev.hchain(H + 0.42, [0, U(7.979), U(6.24), U(5.195), U(3.135), L], size=4.2)
    ev.vchain(L + 0.40, [0, 0.60, 2.40, H], size=4.2)
    ev.note(U(7.11), 1.2, "W08 slider 174 x 240, sill 0", key=True)
    ev.note(U(4.165), 1.5, "W07 206 x 240, sill 60", key=True)
    ev.note(U(5.651), 2.45, "Divider curtain pocket 12 x 12")
    ev.place_notes(at=L + 0.85, size=4.0, wrap_chars=22, vmin=0, vmax=H + 0.2)
    title_under(s, None, s.m + 6, s.m + 104, "A", "FROM INSIDE - reception + dining, looking east (north on the left)", scale="1:50")
    ev, w, h, L2, U2 = east_outside(P, s, s.m + 6, s.m + 20, sc=50, ul=(-0.5, 7.72 + 1.9))
    ev.hchain(3.30, [0, U2(1.98), U2(2.68), U2(3.135), U2(5.195), U2(6.24), U2(7.979), U2(8.78), U2(9.27)], size=4.2)
    ev.vchain(L2 + 0.40, [0, 0.45, 0.60, 0.95, 1.86, 2.40, 2.96], size=4.2)
    ev.note(U2(7.11), 1.2, "W08 slider from outside, sill 0: threshold see D505.3", key=True)
    ev.note(U2(2.33), 0.40, "L-seat end (section) D506")
    ev.note(U2(9.02), 0.70, "BBQ counter end (section) D508")
    ev.note(U2(5.775), 2.0, "3 wall lights (brass)")
    ev.place_notes(at=L2 + 0.70, size=4.0, wrap_chars=22, vmin=0, vmax=3.0)
    title_under(s, None, s.m + 6, s.m + 12, "B", "FROM THE TERRACE - looking west (south on the left)", scale="1:50")
    side_notes(s, [
        "Both openings are existing: W07 206 wide, sill 60, head 240; W08 sliding door 174 wide, sill 0, head 240 (Main model).",
        "Inside, both openings sit under one 15 x 15 curtain pocket (y 2.77-8.38) with motorised tracks; the 12 x 12 pocket at y 5.65 is the reception / dining divider curtain.",
        "Frame colour, glass (double glazing recommended for heat and noise) and the W07 opening type are TO CONFIRM; drawn as 2-panel sliders.",
        "Terrace finished level, threshold and door drainage: see D505.3 (TO CONFIRM on site).",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 50, metres=2, step=0.5, label="SCALE 1:50")
    out.append(s)
    # D505.1 / D505.2: slider W08 at 1:25 from inside and from the terrace
    s = P.new("A4", "D505.1", "Slider W08 - from inside", "1:25", "The dining sliding door with curtains, ceiling pocket and switches")
    ev, w, h, L, U = east_inside(P, s, s.m + 2, s.m + 24, sc=25, yr=(5.95, 9.50), ul=(-0.58, 3.55 + 1.20))
    ev.hchain(H + 0.30, [0, U(8.84), U(7.979), U(6.24), L])
    ev.vchain(-0.24, [0, 1.00, 1.20, 2.40, H], left=True)
    ev.note(U(7.11), 1.6, "W08 sliding door 174 x 240, 2 panels, sill 0 (flush), aluminium frame colour TO CONFIRM", key=True)
    ev.note(U(7.70), 2.20, "Sheer + linen curtains, motorised, stacked to the sides when open")
    ev.note(U(8.0), 2.66, "Curtain pocket 15 x 15 in the ceiling, see D505.3 S6")
    ev.note(U(8.6), 1.20, "Terrace-light switch by the door, 120")
    ev.note(U(9.2), 0.98, "Coffee counter (section), marble top 100")
    ev.place_notes(at=L + 0.42, wrap_chars=30, vmin=-0.2, vmax=H + 0.25)
    title_under(s, None, s.m + 2, s.m + 16, "A", "W08 FROM INSIDE (dining, looking east; north on the left)", scale="1:25")
    side_notes(s, [
        "Sliding door W08: 2 panels, 174 x 240, one fixed and one sliding (direction TO CONFIRM); bottom track recessed so the inside sill is flush.",
        "Curtains run in the ceiling pocket: sheer + linen on a double motorised track; motor power P at 268 inside the pocket (both ends).",
        "Double glazing recommended (heat and street noise); frame colour to match the other windows.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    s = P.new("A4", "D505.2", "Slider W08 - from the terrace", "1:25", "The same door from the terrace: wall lights, outdoor sockets, BBQ counter end")
    ev, w, h, L, U = east_outside(P, s, s.m + 2, s.m + 24, sc=25, yr=(5.45, 9.50), ul=(-0.32, 4.05 + 1.0))
    ev.hchain(3.20, [0, U(5.775), U(6.24), U(7.979), U(8.60), U(8.78), U(9.27), L])
    ev.vchain(-0.24, [0, 0.45, 0.90, 1.30, 1.86, 2.14, 2.40, 2.96], left=True)
    ev.note(U(7.11), 1.6, "W08 from outside; threshold, drain and membrane: D505.3 S7", key=True)
    ev.note(U(5.775), 2.0, "Brass wall lights 186-214 (y 5.775 and 8.60)")
    ev.note(U(5.70), 0.45, "Weatherproof socket + outdoor TV point on the pier, 45")
    ev.note(U(9.02), 0.60, "BBQ counter end (section): WPC front, stone top 94, upstand 130; LED under the lip")
    ev.place_notes(at=L + 0.30, wrap_chars=24, vmin=-0.2, vmax=3.0)
    title_under(s, None, s.m + 2, s.m + 16, "B", "W08 FROM THE TERRACE (looking west; south on the left)", scale="1:25")
    side_notes(s, [
        "Outside wall finish: exterior render + paint as the rest of the facade (TO CONFIRM; Lotus TP p.17 gives interior finishes only).",
        "All outdoor points IP65 with RCD protection (30 mA).",
        "Terrace ceiling: slatted wood per Lotus TP p.9 (7550 x 3259); its level is TO CONFIRM - keep it above the 240 door head.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    # D505.3: head and threshold sections
    s = P.new("A4", "D505.3", "Slider W08 - head and threshold sections", "1:10",
              "Curtain pocket at the head; threshold and terrace drainage at the sill (recommended, TO CONFIRM)")
    door_head_section(P, s, s.m + 6, s.m + 104)
    title_under(s, None, s.m + 6, s.m + 96, "S6", "SECTION S6 - head: ceiling, curtain pocket, door head", scale="1:10")
    door_sill_section(P, s, s.m + 6, s.m + 22)
    title_under(s, None, s.m + 6, s.m + 14, "S7", "SECTION S7 - threshold to the terrace (recommended)", scale="1:10")
    side_notes(s, [
        "Pocket: 15 wide x 15 deep, formed in the gypsum ceiling with a metal angle on the room side; inside painted dark so the track does not show.",
        "Double track (sheer at the glass, linen in front), motor end with power at 268; fix the tracks to timber or steel backing, not to the board.",
        "Slab soffit about 296 (Lotus TP p.9: dining 281 + 15); measure on site before setting the ceiling grid.",
        "Threshold: Main has no terrace level. Recommended: terrace finished 2-3 cm below the inside floor at the door, a slot drain along the sill, and the membrane turned up under the frame. TO CONFIRM.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 10, metres=0.5, step=0.1, label="SCALE 1:10")
    out.append(s)
    return out


def door_head_section(P, s, x, y, sc=10):
    """S6: section through the head of W08 (x horizontal: room on the left, terrace on the right)."""
    H = P.m.ceiling
    ev, w, h = view(s, x, y, (20.70, 21.80), (2.28, 3.02), sc)
    SOFF = 2.96
    ev.rect(20.70, SOFF, 21.80, 3.02, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 2)
    ev.rect(21.222, 2.40, 21.472, SOFF, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 2)
    ev.text(21.347, 2.68, "RC beam /\nlintel", size=3.6, z=ev.z + 3)
    # ceiling board line at 2.60 with the pocket 15 x 15 next to the wall
    ev.rect(20.70, H, 21.062, H + 0.0125, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(21.050, H, 21.062, H + 0.15, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(21.050, H + 0.15, 21.222, H + 0.1625, w=0.3, fc="white", z=ev.z + 3)
    for xx in (20.80, 21.00):
        ev.line([xx, xx], [H + 0.0125, SOFF], w=0.35, c=GREY, z=ev.z + 2.5)
    ev.line([20.70, 21.06], [H + 0.04, H + 0.04], w=0.5, c=GREY, z=ev.z + 2.5)
    # tracks + curtains
    for xx, lab in ((21.105, "sheer"), (21.175, "linen")):
        ev.rect(xx - 0.015, H + 0.12, xx + 0.015, H + 0.15, w=0.3, fc="#cfcfcf", z=ev.z + 4)
        ev.line([xx, xx], [H + 0.12, 2.28], w=0.3, c="#8c8577", ls=(0, (4, 2)), z=ev.z + 4)
    # door frame head
    ev.rect(21.30, 2.36, 21.42, 2.40, w=0.35, fc="white", z=ev.z + 4)
    ev.rect(21.33, 2.28, 21.39, 2.36, w=0.25, fc=GLASS, z=ev.z + 4)
    ev.text(21.53, 2.32, "slider head 240", size=3.6, ha="left")
    ev.vchain(20.76, [2.40, H, H + 0.15, SOFF], left=True, size=4.0)
    ev.hchain(2.98, [21.062, 21.222, 21.472], size=4.0)
    ev.note(21.105, 2.50, "Track 1: sheer (glass side)")
    ev.note(21.175, 2.45, "Track 2: linen / blackout, motorised; power at 268 in the pocket")
    ev.note(21.056, 2.68, "Pocket side: 12.5 board on a steel angle + stud; edge with metal bead", key=True)
    ev.note(20.90, 2.63, "Ceiling 12.5 board on 60/27 furring, hangers to the slab (C403)")
    ev.note(21.62, 2.90, "Terrace: slatted wood ceiling per Lotus TP, level TO CONFIRM")
    ev.place_notes(at=21.86, size=4.0, wrap_chars=60, vmin=2.30, vmax=3.0)
    return ev, w, h


def door_sill_section(P, s, x, y, sc=10):
    """S7: threshold (recommended): inside floor flush to the frame, terrace 2-3 cm lower with a slot drain."""
    ev, w, h = view(s, x, y, (20.70, 21.80), (-0.22, 0.30), sc)
    ev.rect(20.70, -0.22, 21.80, -0.15, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 1)
    ev.rect(20.70, -0.15, 21.30, -0.02, w=0.25, fc="#ececec", hatch="....", z=ev.z + 1)
    ev.rect(20.70, -0.02, 21.30, 0.0, w=0.3, fc="white", z=ev.z + 2)
    ev.text(20.95, -0.01, "inside floor finish", size=3.4, z=ev.z + 3)
    ev.rect(21.30, -0.04, 21.42, 0.02, w=0.35, fc="white", z=ev.z + 3)
    ev.rect(21.33, 0.02, 21.39, 0.30, w=0.25, fc=GLASS, z=ev.z + 3)
    ev.rect(21.42, -0.10, 21.52, -0.025, w=0.3, fc="white", z=ev.z + 3)
    ev.line([21.43, 21.51], [-0.027, -0.027], w=0.6, z=ev.z + 3.1)
    ev.poly([(21.52, -0.15), (21.80, -0.15), (21.80, -0.04 - 0.004), (21.52, -0.04)], fc="#ececec", hatch="....", w=0.25, z=ev.z + 1)
    ev.poly([(21.52, -0.04), (21.80, -0.044), (21.80, -0.024), (21.52, -0.02)], fc="#e8e0d2", w=0.3, z=ev.z + 2)
    ev.line([21.30, 21.30, 21.80], [-0.02, -0.148, -0.148], w=0.7, c=HL, z=ev.z + 4)
    ev.line([21.30, 21.30], [-0.148, 0.05], w=0.7, c=HL, z=ev.z + 4)
    ev.vchain(21.75, [-0.02, 0.0], txt=["2-3"], size=4.0)
    ev.note(20.95, -0.08, "Inside screed + tile / HDF (Lotus TP p.8 floor finishes)")
    ev.note(21.36, -0.01, "Slider bottom track recessed so the inside is flush (no step)", key=True)
    ev.note(21.47, -0.06, "Slot drain along the sill, connected to the terrace drain (TO CONFIRM)", key=True)
    ev.note(21.30, -0.10, "Terrace membrane turned up >= 15 cm behind / under the frame before the frame is fixed", key=True)
    ev.note(21.66, -0.03, "Terrace tile falls >= 1.5 % away from the door")
    ev.place_notes(at=21.86, size=4.0, wrap_chars=60, vmin=-0.20, vmax=0.28)
    return ev, w, h


# =====================================================================================================================
# TERRACE: L-SEAT AND BBQ COUNTER
# =====================================================================================================================
WPC = "#c9a27a"
RENDER = "#ece6dc"


def wpc_boards(ev, u0, u1, v0, v1, pitch=0.10):
    v = v0 + pitch
    while v < v1 - 1e-6:
        ev.line([u0, u1], [v, v], w=0.08, c="#8a6f52", z=ev.z + 3.3)
        v += pitch


def terrace_plan(P, s, x, y, sc=50):
    ax, w, h = plan_view(P, s, x, y, (20.95, 25.55), (1.45, 9.75), sc)
    plan_label(ax, 23.0, 2.38, "L-SEAT (south run)", 3.8, weight="bold")
    plan_label(ax, 24.54, 3.9, "L-SEAT (east run)", 3.8, weight="bold", rot=90)
    plan_label(ax, 23.1, 9.03, "BBQ COUNTER", 3.8, weight="bold")
    plan_label(ax, 23.3, 1.88, "planter 20", 3.0)
    plan_label(ax, 25.04, 3.9, "planter 20", 3.0, rot=90)
    plan_label(ax, 22.8, 5.0, "TERRACE", 5.0, weight="bold")
    section_mark(ax, (22.5, 1.60), (22.5, 2.95), "S8", look=1)
    section_mark(ax, (22.6, 8.55), (22.6, 9.45), "S9", look=1)
    marker(ax, 23.0, 3.35, "A", -90, "D507")
    marker(ax, 23.55, 4.2, "B", 0, "D507")
    marker(ax, 23.1, 8.1, "C", 90, "D508")
    pdim(ax, (21.472, 1.78), (25.143, 1.78), off=-0.35)
    pdim(ax, (21.472, 2.68), (24.243, 2.68), off=0.30, size=3.8)
    pdim(ax, (24.843, 2.08), (24.843, 5.443), off=-0.62, size=3.8)
    pdim(ax, (21.47, 8.78), (24.76, 8.78), off=-0.30, size=3.8)
    pdim(ax, (24.243, 5.443), (24.843, 5.443), off=0.25, size=3.6)
    pdim(ax, (24.76, 8.78), (24.76, 9.27), off=-0.25, size=3.6)
    return ax, w, h


def seat_section(P, s, x, y, sc=10):
    """S8: L-seat south run, cut at x 22.5 looking west (u = y: parapet/planter on the left, terrace on the right)."""
    ev, w, h = view(s, x, y, (1.62, 2.86), (-0.14, 1.06), sc)
    ev.rect(1.62, -0.14, 2.86, -0.07, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 1)
    ev.rect(1.62, -0.07, 2.86, -0.02, w=0.25, fc="#ececec", hatch="....", z=ev.z + 1)
    ev.rect(1.62, -0.02, 2.86, 0.0, w=0.3, fc="#e8e0d2", z=ev.z + 1.2)
    ev.text(2.80, -0.045, "screed to falls", size=3.2, ha="right", z=ev.z + 2)
    # parapet (existing) and planter 20 behind
    ev.cutwall(1.62, 1.78, -0.07, 1.06, fc="#d6d6d6", hatch="xx")
    ev.text(1.70, 0.70, "parapet\n(existing)", size=3.2, rot=90, z=ev.z + 4)
    ev.hatch_box(1.78, 0.0, 1.98, 0.47, "brick")
    ev.rect(1.78, 0.47, 1.98, 0.52, w=0.3, fc="#d9d9d9", hatch="..", z=ev.z + 2.2)
    ev.rect(1.78, 0.52, 1.98, 0.57, w=0.2, fc="#efefef", hatch="oo", z=ev.z + 2.2)
    ev.rect(1.78, 0.57, 1.98, 0.88, w=0.25, fc="#bfae92", hatch=".o", z=ev.z + 2.2)
    ev.line([1.785, 1.785, 1.975, 1.975], [0.92, 0.522, 0.522, 0.92], w=0.6, c=HL, z=ev.z + 4)
    # back wall 10 + coping
    ev.hatch_box(1.98, 0.0, 2.08, 0.93, "brick")
    ev.rect(1.97, 0.93, 2.09, 0.95, w=0.3, fc="#cfc8bb", z=ev.z + 3)
    # storage: base, front wall, lids, WPC skin, return lip, recessed plinth, LED
    ev.rect(2.08, 0.0, 2.56, 0.05, w=0.3, fc="#d9d9d9", hatch="..", z=ev.z + 2.2)
    ev.hatch_box(2.56, 0.08, 2.66, 0.36, "brick")
    ev.hatch_box(2.56, 0.0, 2.62, 0.06, "brick")
    ev.rect(2.66, 0.06, 2.68, 0.36, w=0.3, fc=WPC, z=ev.z + 3)
    ev.rect(2.62, 0.06, 2.68, 0.08, w=0.3, fc=WPC, z=ev.z + 3)
    ev.rect(2.635, 0.052, 2.65, 0.06, w=0.2, fc=HL, z=ev.z + 3.1)
    ev.poly([(2.64, 0.052), (2.60, 0.0), (2.75, 0.0)], fc="#ffe2c8", w=0.0, c="none", z=ev.z + 1.5)
    ev.rect(2.084, 0.36, 2.68, 0.40, w=0.35, fc=WPC, z=ev.z + 3)
    ev.rect(2.11, 0.40, 2.66, 0.45, w=0.25, fc="#efe9df", r=0.015, z=ev.z + 3)
    ev.poly([(2.09, 0.44), (2.29, 0.44), (2.20, 0.86), (2.09, 0.86)], fc="#e3e6dd", w=0.25, z=ev.z + 3)
    ev.rect(2.084, 0.345, 2.12, 0.36, w=0.2, fc="#a0a0a0", z=ev.z + 3.2)
    ev.text(2.32, 0.20, "hollow storage\n(lift-up lid)", size=3.6, z=ev.z + 3)
    ev.ax.annotate("", xy=(2.62, 0.52), xytext=(2.66, 0.41), arrowprops=dict(arrowstyle="-|>", lw=lw(0.25), color=GREY,
                   connectionstyle="arc3,rad=0.4", mutation_scale=5), zorder=ev.z + 5)
    # waterproofing
    ev.line([1.78, 2.86], [-0.021, -0.021], w=0.6, c=HL, z=ev.z + 4)
    ev.line([1.785, 1.785], [-0.021, 0.30], w=0.6, c=HL, z=ev.z + 4)
    ev.hchain(1.02, [1.78, 1.98, 2.08, 2.68])
    ev.hchain(-0.10, [2.56, 2.62, 2.66, 2.68], above=False, size=4.0)
    ev.vchain(2.80, [0, 0.06, 0.36, 0.40, 0.45], size=4.0)
    ev.vchain(1.56, [0, 0.52, 0.88, 0.95], left=True, size=4.0)
    ev.note(1.88, 0.75, "Planter 20 wide: soil 31 (to 88) on a 5 cm drainage layer + filter fabric", key=False)
    ev.note(1.80, 0.60, "Root-resistant waterproof membrane lining the planter, weep outlets to the terrace drain", key=True)
    ev.note(2.03, 0.94, "Back wall 10 (brick, rendered), stone coping 93-95: back 50 above the cushion")
    ev.note(2.38, 0.38, "Lift-up WPC lid 4 on a frame, hinged at the back, gas strut")
    ev.note(2.38, 0.43, "Seat cushion 5 (outdoor fabric), back cushion leans on the wall")
    ev.note(2.61, 0.22, "Front: 10 brick wall, rendered, clad in WPC 2 on aluminium battens", key=True)
    ev.note(2.65, 0.07, "WPC return lip under the cladding; LED strip in a profile under it, 5-6 above the floor, lights the floor", key=True)
    ev.note(2.59, 0.03, "Bottom course recessed 6 from the WPC face (shadow gap)", key=True)
    ev.note(2.30, 0.025, "Storage base slab 5, falls to a weep hole; vent gap under the lid")
    ev.note(2.20, -0.021, "Terrace membrane continuous under the seat and up the walls >= 20 cm, before the masonry")
    ev.place_notes(at=2.92, size=4.0, wrap_chars=46, vmin=-0.14, vmax=1.04)
    return ev, w, h


def seat_elev_south(P, s, x, y, sc=25):
    """A: south run seen from the terrace, looking south (left = east). East run in section at the left."""
    X1 = 24.843
    U = lambda xx: X1 - xx
    L = U(21.472)
    ev, w, h = view(s, x, y, (-0.55, L + 1.30), (-0.20, 1.45), sc)
    ev.floor(-0.40, L + 0.12, depth=0.08)
    ev.cutwall(L, L + 0.25, -0.08, 1.45)
    ev.text(L + 0.125, 1.1, "house wall", size=3.4, rot=90, z=ev.z + 4)
    # behind: back wall render + coping, plants
    ev.rect(0, 0.36, U(21.489), 0.93, w=0.25, fc=RENDER, z=ev.z + 1)
    ev.rect(-0.02, 0.93, U(21.489), 0.95, w=0.3, fc="#cfc8bb", z=ev.z + 1.2)
    for xx in (21.8, 22.5, 23.2, 23.9):
        ev.plant(U(xx), 0.95, h=0.22, w=0.30)
    # front: plinth (recessed, dark), LED, WPC face, lids, cushions
    ev.rect(U(24.263), 0, U(21.489), 0.06, w=0.25, fc="#9c9488", z=ev.z + 2)
    ev.led(U(24.28), 0.056, U(21.509), 0.056)
    ev.rect(U(24.263), 0.06, U(21.489), 0.36, w=0.35, fc=WPC, z=ev.z + 3)
    wpc_boards(ev, U(24.263), U(21.489), 0.06, 0.36)
    ev.rect(U(24.239), 0.36, U(21.493), 0.40, w=0.3, fc=WPC, z=ev.z + 3.4)
    ev.vjoints([U(xx) for xx in (22.178, 22.866, 23.554)], 0.36, 0.40, c=INK, w=0.2, z=ev.z + 3.8)
    for a, b in ((21.513, 22.154), (22.202, 22.842), (22.89, 23.53), (23.578, 24.219)):
        ev.rect(U(b), 0.40, U(a), 0.45, w=0.25, fc="#efe9df", r=0.015, z=ev.z + 3.5)
    for a, b in ((21.689, 22.129), (22.369, 22.809), (23.049, 23.489), (23.729, 24.169)):
        ev.rect(U(b), 0.45, U(a), 0.858, w=0.25, fc="#e3e6dd", r=0.04, z=ev.z + 3.4)
    # east run in section (cut at y 3.0)
    ev.hatch_box(U(24.943), 0, U(24.843), 0.93, "brick")
    ev.rect(U(24.953), 0.93, U(24.833), 0.95, w=0.3, fc="#cfc8bb", z=ev.z + 3)
    ev.hatch_box(U(25.143), 0, U(24.943), 0.52, "brick")
    ev.rect(U(25.143), 0.52, U(24.943), 0.88, w=0.25, fc="#bfae92", hatch=".o", z=ev.z + 3)
    ev.rect(U(24.843), 0, U(24.363), 0.05, w=0.3, fc="#d9d9d9", hatch="..", z=ev.z + 3)
    ev.hatch_box(U(24.363), 0.08, U(24.263), 0.36, "brick")
    ev.hatch_box(U(24.363), 0.0, U(24.303), 0.06, "brick")
    ev.rect(U(24.263), 0.06, U(24.243), 0.36, w=0.3, fc=WPC, z=ev.z + 3)
    ev.rect(U(24.839), 0.36, U(24.243), 0.40, w=0.35, fc=WPC, z=ev.z + 3)
    ev.rect(U(24.813), 0.40, U(24.263), 0.45, w=0.25, fc="#efe9df", r=0.015, z=ev.z + 3)
    ev.rect(U(24.832), 0.442, U(24.634), 0.858, w=0.25, fc="#e3e6dd", r=0.03, z=ev.z + 3)
    elec_overlay(ev, P, Wall((25.0, 2.0), (21.4, 2.0)), 1.4, depth=0.75, size=2.6)
    ev.hchain(1.25, [U(25.143), U(24.943), U(24.843), U(24.243), U(22.178), U(22.866), U(23.554), U(21.489), L], size=4.0)
    ev.vchain(-0.36, [0, 0.06, 0.36, 0.40, 0.45, 0.86, 0.95], left=True, size=4.0)
    ev.note(U(23.0), 0.20, "WPC cladding on the front, boards horizontal", key=True)
    ev.note(U(22.6), 0.056, "LED under the return lip, ~6 above the floor; plinth recessed 6 (dark shadow)", key=True)
    ev.note(U(23.2), 0.38, "4 lift-up WPC lids ~68 wide (storage below)")
    ev.note(U(22.5), 0.43, "Seat cushions, top 45")
    ev.note(U(22.6), 0.70, "Back cushions 44 x 42 leaning on the back wall")
    ev.note(U(23.3), 0.94, "Rendered back wall 10, stone coping at 95")
    ev.note(U(23.9), 1.10, "Planter behind (20): low planting")
    ev.note(U(24.6), 0.25, "East run in section (cut at y 3.00)")
    ev.place_notes(at=L + 0.36, size=4.2, wrap_chars=32, vmin=-0.18, vmax=1.42)
    return ev, w, h


def seat_elev_east(P, s, x, y, sc=25):
    """B: east run seen from the terrace, looking east (left = north). South run in section at the right."""
    Y1 = 5.443
    U = lambda yy: Y1 - yy
    L = U(1.78)
    ev, w, h = view(s, x, y, (-0.55, L + 1.30), (-0.20, 1.45), sc)
    ev.floor(-0.10, L + 0.12, depth=0.08)
    ev.cutwall(L, L + 0.18, -0.08, 1.20)
    ev.text(L + 0.09, 0.95, "parapet", size=3.4, rot=90, z=ev.z + 4)
    ev.rect(0, 0, U(5.343), 0.95, w=0.3, fc=RENDER, z=ev.z + 2)
    ev.rect(U(5.343), 0.36, U(2.08), 0.93, w=0.25, fc=RENDER, z=ev.z + 1)
    ev.rect(U(5.343), 0.93, U(2.08), 0.95, w=0.3, fc="#cfc8bb", z=ev.z + 1.2)
    for yy in (4.9, 4.2, 3.5, 2.8):
        ev.plant(U(yy), 0.95, h=0.22, w=0.30)
    ev.rect(U(5.443), 0, U(2.66), 0.06, w=0.25, fc="#9c9488", z=ev.z + 2)
    ev.led(U(5.423), 0.056, U(2.643), 0.056)
    ev.rect(U(5.443), 0.06, U(2.66), 0.36, w=0.35, fc=WPC, z=ev.z + 3)
    wpc_boards(ev, U(5.443), U(2.66), 0.06, 0.36)
    ev.rect(U(5.439), 0.36, U(2.684), 0.40, w=0.3, fc=WPC, z=ev.z + 3.4)
    ev.vjoints([U(yy) for yy in (3.371, 4.0615, 4.752)], 0.36, 0.40, c=INK, w=0.2, z=ev.z + 3.8)
    for a, b in ((2.704, 3.347), (3.395, 4.037), (4.085, 4.728), (4.776, 5.419)):
        ev.rect(U(b), 0.40, U(a), 0.45, w=0.25, fc="#efe9df", r=0.015, z=ev.z + 3.5)
    for a, b in ((2.83, 3.27), (3.51, 3.95), (4.19, 4.63), (4.87, 5.31)):
        ev.rect(U(b), 0.45, U(a), 0.858, w=0.25, fc="#e3e6dd", r=0.04, z=ev.z + 3.4)
    # south run in section (cut at x 24.0)
    ev.hatch_box(U(1.98), 0, U(1.78), 0.47, "brick")
    ev.rect(U(1.98), 0.52, U(1.78), 0.88, w=0.25, fc="#bfae92", hatch=".o", z=ev.z + 3)
    ev.hatch_box(U(2.08), 0, U(1.98), 0.93, "brick")
    ev.rect(U(2.09), 0.93, U(1.97), 0.95, w=0.3, fc="#cfc8bb", z=ev.z + 3)
    ev.rect(U(2.56), 0, U(2.08), 0.05, w=0.3, fc="#d9d9d9", hatch="..", z=ev.z + 3)
    ev.hatch_box(U(2.66), 0.08, U(2.56), 0.36, "brick")
    ev.hatch_box(U(2.62), 0.0, U(2.56), 0.06, "brick")
    ev.rect(U(2.68), 0.06, U(2.66), 0.36, w=0.3, fc=WPC, z=ev.z + 3)
    ev.rect(U(2.68), 0.36, U(2.084), 0.40, w=0.35, fc=WPC, z=ev.z + 3)
    ev.rect(U(2.66), 0.40, U(2.11), 0.45, w=0.25, fc="#efe9df", r=0.015, z=ev.z + 3)
    elec_overlay(ev, P, Wall((24.75, 5.6), (24.75, 1.7)), 1.4, depth=0.6, size=2.6)
    ev.hchain(1.25, [0, U(5.343), U(4.752), U(4.0615), U(3.371), U(2.68), U(2.08), U(1.98), L], size=4.0)
    ev.vchain(-0.36, [0, 0.06, 0.36, 0.40, 0.45, 0.86, 0.95], left=True, size=4.0)
    ev.note(U(5.39), 0.70, "Seat end: rendered return, 95 high, closes the planter")
    ev.note(U(4.0), 0.20, "WPC cladding, same lip + LED detail as S8", key=True)
    ev.note(U(4.4), 0.38, "4 lift-up lids ~68 + corner lid 60 x 60")
    ev.note(U(3.0), 0.70, "Back cushions on the east run")
    ev.note(U(2.35), 0.25, "South run in section (cut at x 24.0), see S8")
    ev.place_notes(at=L + 0.30, size=4.2, wrap_chars=32, vmin=-0.18, vmax=1.42)
    return ev, w, h


def bbq_elev(P, s, x, y, sc=25):
    """C: BBQ counter seen from the terrace, looking north (left = west)."""
    X0 = 21.47
    U = lambda xx: xx - X0
    L = U(24.76)
    ev, w, h = view(s, x, y, (-0.55, L + 1.30), (-0.20, 1.80), sc)
    ev.floor(-0.25, L + 0.20, depth=0.08)
    ev.cutwall(-0.25, 0, -0.08, 1.75)
    ev.rect(0, 0, L + 0.20, 1.65, w=0.0, c="none", fc="#f3f0ea")
    ev.line([0, L + 0.2], [1.65, 1.65], w=0.2, c=GREY, ls=(0, (6, 3)))
    ev.text(L / 2, 1.58, "north wall / parapet behind (existing)", size=3.4, c=GREY)
    ev.rect(0, 0, L, 0.06, w=0.25, fc="#9c9488", z=ev.z + 2)
    ev.led(0.03, 0.056, L - 0.03, 0.056)
    ev.rect(0, 0.06, L, 0.90, w=0.35, fc=WPC, z=ev.z + 3)
    js = [U(xx) for xx in (22.018, 22.567, 23.115, 23.663, 24.212)]
    ev.vjoints(js, 0.08, 0.89, c=INK, w=0.25, z=ev.z + 3.8)
    for a, b in zip([0] + js, js + [L]):
        ev.line([(a + b) / 2 - 0.06, (a + b) / 2 + 0.06], [0.80, 0.80], w=0.5, cap="round", z=ev.z + 3.5)
    ev.rect(-0.0, 0.90, L, 0.94, w=0.35, fc="#cfc8bb", z=ev.z + 3.6)
    ev.rect(0, 0.94, L, 1.30, w=0.3, fc="#ddd6c8", z=ev.z + 2.5)
    ev.rect(U(22.215), 0.94, U(23.015), 1.12, w=0.35, fc="#e3e3e3", r=0.01, z=ev.z + 4)
    ev.rect(U(22.215), 1.12, U(23.015), 1.18, w=0.35, fc=DARK, r=0.01, z=ev.z + 4)
    ev.text(U(22.615), 1.03, "grill", size=3.6, z=ev.z + 5)
    elec_overlay(ev, P, Wall((21.47, 9.27), (24.76, 9.27)), 1.6, depth=0.5, size=2.6)
    ev.hchain(1.72, [0, U(22.215), U(23.015), L], size=4.0)
    ev.hchain(-0.12, [0] + js + [L], above=False, size=3.8)
    ev.vchain(L + 0.24, [0, 0.06, 0.90, 0.94, 1.12, 1.18, 1.30], size=4.0)
    ev.note(U(23.9), 0.50, "6 WPC doors ~55 wide on stainless hinges; carcass in brick / block, rendered inside", key=True)
    ev.note(U(23.4), 0.056, "Recessed plinth 6 + LED under the WPC return lip (same as the seat)", key=True)
    ev.note(U(24.3), 0.92, "Stone top 4, top 94, 2 cm overhang")
    ev.note(U(24.0), 1.20, "Stone upstand 36 high on the back wall (to 130)")
    ev.note(U(22.615), 1.15, "Grill head 80 x 40 on the top (type TO CONFIRM: gas / charcoal / electric)", key=True)
    ev.note(U(23.55), 1.12, "Weatherproof socket 112 on the upstand (WP-169)")
    ev.place_notes(at=L + 0.42, size=4.2, wrap_chars=34, vmin=-0.18, vmax=1.75)
    return ev, w, h


def bbq_section(P, s, x, y, sc=20):
    """S9: through the grill at x 22.6 looking west (u = y: front on the left)."""
    ev, w, h = view(s, x, y, (8.66, 9.45), (-0.12, 1.42), sc)
    ev.floor(8.66, 9.45, depth=0.08)
    ev.cutwall(9.27, 9.45, -0.08, 1.42, fc="#d6d6d6", hatch="xx")
    ev.hatch_box(9.17, 0.06, 9.25, 0.90, "brick")
    ev.rect(9.25, 0.0, 9.27, 0.94, w=0.2, fc=RENDER, z=ev.z + 2.5)
    ev.hatch_box(8.86, 0.0, 9.27, 0.06, "brick")
    ev.rect(8.86, 0.06, 9.17, 0.10, w=0.3, fc="#d9d9d9", hatch="..", z=ev.z + 2.5)
    ev.rect(8.80, 0.85, 9.25, 0.90, w=0.3, fc="#d9d9d9", hatch="..", z=ev.z + 2.5)
    ev.rect(8.78, 0.90, 9.27, 0.94, w=0.35, fc="#cfc8bb", z=ev.z + 3)
    ev.rect(9.25, 0.94, 9.27, 1.30, w=0.35, fc="#cfc8bb", z=ev.z + 3)
    ev.rect(8.80, 0.08, 8.82, 0.85, w=0.3, fc=WPC, z=ev.z + 3)
    ev.rect(8.80, 0.06, 8.86, 0.08, w=0.3, fc=WPC, z=ev.z + 3)
    ev.rect(8.83, 0.052, 8.845, 0.06, w=0.2, fc=HL, z=ev.z + 3.1)
    ev.rect(8.82, 0.94, 9.22, 1.12, w=0.35, fc="#e3e3e3", r=0.01, z=ev.z + 4)
    ev.rect(8.82, 1.12, 9.22, 1.18, w=0.35, fc=DARK, r=0.01, z=ev.z + 4)
    ev.text(9.0, 0.48, "storage\n(ventilated if\ngas bottle)", size=3.4, z=ev.z + 4)
    ev.line([8.70, 9.27], [-0.02, -0.02], w=0.6, c=HL, z=ev.z + 4)
    ev.hchain(1.32, [8.78, 8.80, 9.22, 9.27], size=3.8)
    ev.vchain(8.72, [0, 0.06, 0.85, 0.94, 1.18, 1.30], left=True, size=3.8)
    ev.note(8.81, 0.40, "WPC door 2 on hinges, gap 3 mm")
    ev.note(8.84, 0.056, "LED under the return lip; plinth recessed 6")
    ev.note(9.00, 0.875, "Cement board / concrete shelf under the stone top")
    ev.note(9.02, 1.06, "Grill on the top; heat shield + no WPC within 15 cm of the burner")
    ev.note(9.21, 0.50, "Back wall 8-10 brick, rendered")
    ev.note(9.10, -0.02, "Terrace membrane continuous under the counter")
    ev.place_notes(at=9.50, size=4.0, wrap_chars=40, vmin=-0.12, vmax=1.40)
    return ev, w, h


def sheet_terrace(P):
    out = []
    s = P.new("A4", "D506.1", "Terrace - plan of the L-seat and BBQ counter", "1:50", "Setting-out plan with section marks S8 / S9 and views A-C")
    terrace_plan(P, s, s.m + 4, s.m + 14, sc=50)
    title_under(s, None, s.m + 4, s.m + 7, "P", "TERRACE PLAN", scale="1:50")
    s.notes(s.m + 104, s.H - s.m - 6, "HOW IT IS BUILT", [
        "L-seat: masonry first (10 brick walls, rendered), then WPC cladding on the fronts. Seat 60 deep, top 45 with cushion; back 50 above the cushion (coping 95).",
        "Planter 20 wide runs behind both runs (soil top 88), lined with a root-resistant membrane, weep outlets to the terrace drain.",
        "Storage: each seat module is hollow with a lift-up WPC lid (~68 wide; corner 60 x 60). Base slab falls to a weep hole.",
        "WPC turns back under itself as a return lip; LED strip under the lip about 6 cm off the floor lights the floor. The brick bottom course is set back 6 cm (shadow gap).",
        "BBQ counter: same language - WPC doors on a masonry carcass, stone top 94, stone upstand to 130, grill on the top.",
        "Before any masonry: terrace membrane continuous under both pieces and up the walls >= 20 cm; flood test 48 h. Falls >= 1.5 % to the drains (P18 TO CONFIRM).",
        "Structure: added masonry weight on the terrace slab must be checked by a structural engineer.",
    ], width_chars=60, size=4.6)
    side_notes(s, [
        "Plan geometry from Main (furnish file, 12 Nov 2026 decisions).",
        "Lotus TP p.6 still shows a terrace basin which Karim removed; p.9 shows a slatted wood ceiling over the terrace (7550 x 3259).",
        "Terrace drains, falls and finished level are not in Main or the Lotus TP: TO CONFIRM on site.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 50, metres=2, step=0.5, label="SCALE 1:50")
    out.append(s)
    s = P.new("A4", "D506.2", "Terrace - L-seat section", "1:10", "S8 through the south run: planter, back, storage, WPC front, lip and LED")
    seat_section(P, s, s.m + 4, s.m + 26, sc=10)
    title_under(s, None, s.m + 4, s.m + 14, "S8", "SECTION S8 - L-seat (south run)", scale="1:10")
    side_notes(s, [
        "Dimensions in cm. Heights from the terrace finished floor.",
        "Order: membrane + protection screed -> brick walls -> render -> aluminium battens -> WPC -> lids -> LED + cushions.",
        "WPC: fix with hidden clips on aluminium battens, 5 mm expansion gaps, no screws through the face.",
        "LED: IP67 24 V strip in an aluminium profile with diffuser; driver in the IP65 box on the house wall (L-211 at 30).",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 10, metres=0.5, step=0.1, label="SCALE 1:10")
    out.append(s)
    s = P.new("A4", "D507", "Terrace - L-seat elevations", "1:25", "A south run and B east run as seen standing on the terrace")
    seat_elev_south(P, s, s.m + 4, s.m + 114)
    title_under(s, None, s.m + 4, s.m + 106, "A", "A - SOUTH RUN, looking south (east on the left)", scale="1:25")
    seat_elev_east(P, s, s.m + 4, s.m + 24)
    title_under(s, None, s.m + 4, s.m + 16, "B", "B - EAST RUN, looking east (north on the left)", scale="1:25")
    side_notes(s, [
        "Lid joints line up with the internal 5 cm partitions; each module is one storage bay.",
        "Cushions: outdoor fabric, removable covers; store them in the bays.",
        "Lighting on this side: light outlet LO-173 at 30 by the planter corner (spots above the seat), seat-lip LED feed L-211 at 30.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    s = P.new("A4", "D508", "Terrace - BBQ counter", "1:25 / 1:20", "C front elevation and S9 section through the grill")
    bbq_elev(P, s, s.m + 4, s.m + 100)
    title_under(s, None, s.m + 4, s.m + 92, "C", "C - BBQ COUNTER, looking north (west on the left)", scale="1:25")
    bbq_section(P, s, s.m + 12, s.m + 6, sc=20)
    title_under(s, None, s.m + 112, s.m + 14, "S9", "SECTION S9 - through the grill", scale="1:20")
    side_notes(s, [
        "Counter 329 x 49 (Main). Top 94, upstand 130.",
        "Grill type TO CONFIRM. Gas: ventilated cabinet with low vents, approved hose, no WPC near the burner. Electric: dedicated circuit + RCD.",
        "Stone top and upstand: same stone as the seat coping; seal after fixing.",
        "Plinth recess + LED as the seat; LED feed L-212 on the house wall at 30.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    out.append(s)
    return out


# =====================================================================================================================
# GYPSUM-BOARD CEILINGS (RCP + sections)
# =====================================================================================================================
SOFFIT = 2.96      # approx. slab soffit from the Lotus TP (dining FCL 2810 + 150); measure on site
CEIL = {   # key: (board, TP FCL below slab mm, TP note)
    "LIVING ROOM": ("C01", 150, ""),
    "RECEPTION": ("C01", 600, "TP: concealed ducted AC, 60x60 access"),
    "DINING": ("C01", 150, ""),
    "TOILET 2": ("C02", 600, "TP: ducted unit above, 60x60 access"),
    "KITCHEN": ("C02", 200, ""),
    "MASTER BEDROOM": ("C01", 150, ""),
    "TOILET 1": ("C02", 200, ""),
    "ENTRANCE": ("C01", 150, "TP: 10 cm perimeter offsets"),
    "HALLWAY": ("C01", 150, "TP: 10 cm perimeter offsets"),
    "LAUNDRY": ("C02", 200, ""),
}
BOARD = {"C01": "white gypsum board 12.5", "C02": "green moisture-resistant board 12.5", "C03": "red fire-rated board 12.5",
         "C04": "cement board (exterior / wet)"}
APANELS = [("AP1", 1.80, 6.60, "master bath: heater + valves"), ("AP2", 13.62, 7.65, "guest bath: valves + fan duct"),
           ("AP3", 11.15, 8.55, "laundry: 9.5 kW heater feeds"), ("AP4", 8.20, 7.55, "kitchen: supply joints"),
           ("AP5", 12.40, 5.85, "hallway: supply branch"), ("AP6", 9.10, 5.10, "entrance: supply run"),
           ("AP7", 20.30, 8.50, "coffee corner water line")]


def ceiling_rcp(P, no, window, title):
    s = P.new("A3", no, title, "1:50", "Reflected ceiling plan: board type, ceiling height (Main) vs Lotus TP level, pockets, access panels")
    (x0, x1), (y0, y1) = window
    ax, w, h = s.plan_axes(s.m + 6, s.H - s.m - 14 - (y1 - y0) * 20, window[0], window[1], 50)
    draw_base(ax, P.m, "mep")
    s.heading(s.m + 4, s.H - s.m - 7, no, title.upper())
    s.north(s.side_x - 10, s.H - s.m - 12)
    k = 1 / ax._mm_per_m
    for key, poly, kind in P.m.floors:
        cx, cy = poly.representative_point().x, poly.representative_point().y
        at = P.m.data["rooms"].get(key, {}).get("at")
        if at:
            cx, cy = at
        if not (x0 < cx < x1):
            continue
        if kind == "outdoor":
            ax.add_patch(MPoly(list(poly.exterior.coords), closed=True, fc="none", ec=GREY, lw=lw(0.1), hatch="||||", zorder=2, alpha=0.5))
            plan_label(ax, cx, cy + 0.9, "TERRACE: slatted wood ceiling\n(Lotus TP p.9) - level TO CONFIRM", 4.4)
            continue
        board, fcl, note = CEIL.get(key, ("C01", None, ""))
        if board == "C02":
            ax.add_patch(MPoly(list(poly.exterior.coords), closed=True, fc="none", ec="#9a9a9a", lw=lw(0.05), hatch="\\\\\\\\", zorder=2))
        en, _ = P.room_name(key)
        tp = f"TP: -{fcl} = ~{(SOFFIT * 1000 - fcl) / 10:.0f}" if fcl else ""
        txt = f"{en.upper()}\n{board}   CH {P.m.ceiling * 100:.0f}\n({tp})" + (f"\n{note}" if note else "")
        ax.text(cx, cy, txt, fontsize=4.6, ha="center", va="center", zorder=18, linespacing=1.25,
                bbox=dict(fc="white", ec=HL, lw=lw(0.25), pad=0.6, boxstyle="round,pad=0.4"), clip_on=False)
    for i, pk in enumerate(P.m.pockets()):
        if pk["x1"] < x0 or pk["x0"] > x1:
            continue
        ax.add_patch(Rectangle((pk["x0"], pk["y0"]), pk["x1"] - pk["x0"], pk["y1"] - pk["y0"], fc=HL, ec=HL, alpha=0.55,
                               lw=lw(0.2), zorder=8, hatch="////"))
        cxp, cyp = (pk["x0"] + pk["x1"]) / 2, (pk["y0"] + pk["y1"]) / 2
        vert = (pk["y1"] - pk["y0"]) > (pk["x1"] - pk["x0"])
        d = pk["depth"] * 100
        ax.text(cxp + (-0.22 if vert else 0), cyp + (0 if vert else -0.22), f"CP{i + 1}  pocket {d:.0f}x{d:.0f}", fontsize=4.0,
                color=HL, ha="center", va="center", rotation=90 if vert else 0, zorder=18, weight="bold",
                bbox=dict(fc="white", ec="none", pad=0.1), clip_on=False)
    for a in P.m.acs():
        if not (x0 < a["x0"] < x1):
            continue
        ax.add_patch(Rectangle((a["x0"], a["y0"]), a["x1"] - a["x0"], a["y1"] - a["y0"], fc="white", ec=INK, lw=lw(0.3), zorder=8))
    for tag, xx, yy, why in APANELS:
        if not (x0 < xx < x1):
            continue
        ax.add_patch(Rectangle((xx - 0.30, yy - 0.30), 0.60, 0.60, fc="none", ec=HL, lw=lw(0.35), ls=(0, (3, 1.5)), zorder=12))
        ax.plot([xx - 0.30, xx + 0.30], [yy - 0.30, yy + 0.30], color=HL, lw=lw(0.12), zorder=12)
        ax.plot([xx - 0.30, xx + 0.30], [yy + 0.30, yy - 0.30], color=HL, lw=lw(0.12), zorder=12)
        ax.text(xx, yy - 0.40, tag, fontsize=4.2, color=HL, ha="center", va="top", weight="bold", zorder=18,
                bbox=dict(fc="white", ec="none", pad=0.1), clip_on=False)
    for p in P.m.elec["points"]:
        if p["h"] >= 2.59 and p["type"] in ("spot", "fan", "sensor", "ap", "power", "pendant") and x0 < p["x"] < x1:
            sym(ax, p["type"], p["x"], p["y"], c=INK, size=2.0)
    return s, ax


def ceiling_legend(s, x, yy):
    s.text(x, yy, "LEGEND", size=6, weight="bold"); yy -= 5
    s.page.add_patch(Rectangle((x + 1, yy - 1.4), 4, 2.8, fc=HL, ec=HL, alpha=0.55, hatch="////"))
    s.text(x + 7.5, yy, "CP = curtain pocket in the ceiling (C403)", size=4.8); yy -= 4.6
    s.page.add_patch(Rectangle((x + 1, yy - 1.4), 4, 2.8, fc="none", ec="#9a9a9a", hatch="\\\\\\\\", lw=lw(0.1)))
    s.text(x + 7.5, yy, "C02 green board (wet rooms); others C01 white", size=4.8); yy -= 4.6
    s.page.add_patch(Rectangle((x + 1.5, yy - 1.5), 3, 3, fc="none", ec=HL, lw=lw(0.35), ls=(0, (3, 1.5))))
    s.line([(x + 1.5, yy - 1.5), (x + 4.5, yy + 1.5)], w=0.12, c=HL)
    s.line([(x + 1.5, yy + 1.5), (x + 4.5, yy - 1.5)], w=0.12, c=HL)
    s.text(x + 7.5, yy, "AP = access panel 60 x 60 (proposed, C404)", size=4.8); yy -= 4.6
    s.rect(x + 1, yy - 1.2, x + 5, yy + 1.2, w=0.3)
    s.text(x + 7.5, yy, "Wall split AC (outline)", size=4.8); yy -= 4.6
    for t in ("spot", "fan", "sensor", "ap", "power"):
        legend_entry(s, x + 3, yy, t, B.TYPE_NAMES[t] + (" (curtain motor)" if t == "power" else ""), c=INK); yy -= 4.6
    s.text(x, yy, "CH = finished ceiling height (Main). TP = Lotus TP level below the", size=4.4); yy -= 3.4
    s.text(x, yy, "slab, converted with a soffit of ~296 (measure on site).", size=4.4); yy -= 4
    return yy


def sheet_ceilings(P):
    out = []
    s, ax = ceiling_rcp(P, "C401", ((-0.6, 15.0), (-0.3, 10.4)), "Ceilings - RCP west (bedroom, kitchen, bathrooms)")
    section_mark(ax, (12.9, 5.2), (12.9, 6.75), "CS1", look=1)
    section_mark(ax, (0.9, 7.5), (2.3, 7.5), "CS4", look=1)
    s.scale_bar(s.side_x - 120, s.m + 8, 50, metres=3, step=0.5, label="SCALE 1:50")
    yy = ceiling_legend(s, s.side_x + 2, s.H - s.m - 4)
    s.notes(s.side_x + 2, yy - 2, "NOTES", [
        f"Main: one flat ceiling at {P.m.ceiling * 100:.0f} in every room. Lotus TP p.9 sets stepped levels (table on C402). Main governs; TP levels shown for reference.",
        "Void above 260 is ~36 cm (soffit ~296): enough for supply pipes, pockets and downlights. Measure the soffit in every room before fixing the grid.",
        "Wet rooms (bathrooms, kitchen, laundry): green moisture-resistant board, furring at 40 cm, moisture-resistant paint (C404 CS4).",
        "Access panels AP1-AP7 sit under valves, heaters and pipe joints: final position to suit the pipes as laid (P301).",
        "Bathroom fans: duct to outside with a back-draft flap; keep the duct run short and falling outward.",
    ], width_chars=46, size=4.4, gap=2.0)
    out.append(s)
    s, ax = ceiling_rcp(P, "C402", ((14.0, 26.0), (-0.3, 10.4)), "Ceilings - RCP east (reception, dining, terrace)")
    section_mark(ax, (20.75, 7.0), (21.6, 7.0), "CS2", look=1)
    section_mark(ax, (19.6, 5.651), (20.6, 5.651), "CS3", look=-1)
    ax.add_patch(Rectangle((18.2, 3.2), 1.4, 0.7, fc="none", ec=GREY, lw=lw(0.3), ls=(0, (5, 3)), zorder=9))
    plan_label(ax, 18.9, 3.05, "TP option only: concealed ducted unit\n(ceiling drop to ~236) - NOT in Main", 3.6, c=GREY)
    s.scale_bar(s.side_x - 120, s.m + 8, 50, metres=3, step=0.5, label="SCALE 1:50")
    rows = []
    for key, (board, fcl, note) in CEIL.items():
        en, _ = P.room_name(key)
        tpch = (SOFFIT * 1000 - fcl) / 10
        rows.append([en, f"{P.m.ceiling * 100:.0f}", f"-{fcl}", f"~{tpch:.0f}", board])
    rows.append(["Terrace", "-", "slats", "CONFIRM", "wood"])
    tx = s.m + 254
    s.text(tx, s.H - s.m - 24, "CEILING LEVELS: MAIN vs LOTUS TP (p.9)", size=6, weight="bold")
    s.table(tx, s.H - s.m - 27, [("Room", 22, "left"), ("CH Main", 10, "left"), ("TP FCL", 10, "left"), ("TP CH", 10, "left"),
                                  ("Board", 9, "left")], rows, size=3.9, row_h=3.0)
    s.notes(tx, s.H - s.m - 75, "CONFLICTS TO RESOLVE", [
        "TP drops the reception and the guest bathroom to ~236 to hide ducted AC units. Main uses wall splits and keeps 260: no drop needed.",
        "TP has no curtain pockets at 15 x 15; Main has CP pockets at every window (C403).",
        "Everywhere else TP sits higher (276-281) than Main (260). Lower ceilings cost height but give room for pipes; decide one level per room before gypsum works.",
    ], width_chars=34, size=4.2, gap=1.8)
    yy = ceiling_legend(s, s.side_x + 2, s.H - s.m - 4)
    s.notes(s.side_x + 2, yy - 2, "NOTES", [
        "CS2 = pocket at the terrace doors (C403 / D505.3); CS3 = divider pocket 12 x 12 between reception and dining.",
        "Curtain motors are powered inside the pockets (P at 268); leave the pocket open full length for service.",
        "Terrace slatted ceiling: exterior-grade timber or aluminium wood-look on a galvanised frame; level TO CONFIRM.",
    ], width_chars=46, size=4.4, gap=2.0)
    out.append(s)
    # C403: pockets + typical ceiling
    s = P.new("A4", "C403", "Ceiling details - curtain pockets & typical ceiling", "1:5 / 1:10", "CS2 curtain pocket 15 x 15, CS3 divider pocket 12 x 12, CS1 typical suspended ceiling")
    pocket_detail(P, s, s.m + 4, s.m + 112, w_=0.15, title="CS2 - CURTAIN POCKET 15 x 15 (window wall)", tracks=2)
    pocket_detail(P, s, s.m + 4, s.m + 26, w_=0.12, title="CS3 - DIVIDER POCKET 12 x 12 (reception / dining)", tracks=1)
    typical_ceiling(P, s, s.m + 112, s.m + 22)
    side_notes(s, [
        "Pocket sides: 12.5 board on a steel angle (L 30/30) screwed to a stud hung from the slab; metal corner bead on every edge.",
        "Paint the inside of the pockets a darker shade so the tracks and motor disappear.",
        "LED: warm 2700 K 24 V strip in an aluminium profile on the room-side lip, washing the curtain (R0 C401). Driver reachable inside the pocket.",
        "Track backing: 18 mm plywood or steel strip fixed to the slab before boarding; tracks are never screwed only into board.",
        "Ceiling levels: Main 260 flat; Lotus TP stepped levels on C402.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 5, metres=0.25, step=0.05, label="SCALE 1:5 (pockets)")
    out.append(s)
    # C404: access panel, bathroom ceiling, concealed AC option
    s = P.new("A4", "C404", "Ceiling details - access panel, bathroom ceiling, concealed AC option", "1:5 / 1:10 / 1:20",
              "AP 60 x 60 access panel; CS4 bathroom ceiling with fan; Lotus TP concealed-AC option for reference")
    access_panel(P, s, s.m + 4, s.m + 110)
    bath_ceiling(P, s, s.m + 4, s.m + 22)
    concealed_ac(P, s, s.m + 112, s.m + 22)
    side_notes(s, [
        "Access panels: factory-made gypsum panels with a hidden frame and push-latch, same board as the ceiling (green in wet rooms).",
        "Bathroom ceilings: green board, joints taped, moisture-resistant primer + anti-mould paint; seal all penetrations.",
        "Concealed AC is the Lotus TP option only: Main uses wall splits. If it is chosen, the ceiling in that room drops to ~236 and the unit needs a 60 x 60 hatch under its filter and a condensate fall.",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 10, metres=0.5, step=0.1, label="SCALE 1:10")
    out.append(s)
    return out


def pocket_detail(P, s, x, y, w_=0.15, title="", tracks=2, sc=5):
    H = P.m.ceiling
    ST = H + 0.215                      # slab drawn here: void shortened (real soffit ~296)
    ev, w, h = view(s, x, y, (-0.26, 0.05), (2.53, ST + 0.04), sc)
    ev.rect(-0.26, ST, 0.05, ST + 0.04, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 2)
    ev.line([-0.13, -0.12, -0.14, -0.13], [ST - 0.01, ST + 0.02, ST + 0.03, ST + 0.05], w=0.3, c=INK, z=ev.z + 5)
    ev.text(-0.20, ST + 0.02, "slab (void shortened)", size=3.6, bg="white", z=ev.z + 5)
    ev.cutwall(0.0, 0.05, 2.53, ST)
    ev.rect(-0.012, 2.53, 0.0, ST, w=0.2, fc="white", z=ev.z + 2.5)
    ev.rect(-0.26, H, -w_ - 0.012, H + 0.0125, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(-w_ - 0.0245, H, -w_ - 0.012, H + w_, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(-w_ - 0.0245, H + w_, -0.012, H + w_ + 0.0125, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(-w_ - 0.0245 - 0.03, H + w_ - 0.03, -w_ - 0.0245, H + w_ + 0.0125, w=0.25, fc="#cfcfcf", z=ev.z + 3)
    ev.rect(-0.26, H + 0.0125, -w_ - 0.0245, H + 0.04, w=0.2, fc="#cfcfcf", z=ev.z + 2.8)
    for xx in (-0.23, -w_ - 0.04):
        ev.line([xx, xx], [H + 0.04, ST], w=0.4, c=GREY, z=ev.z + 2.6)
    ev.rect(-w_ + 0.005, H + w_ + 0.0125, -0.02, H + w_ + 0.03, w=0.25, fc="#e7d3b0", hatch="////", z=ev.z + 3)
    pos = [-w_ * 0.35, -w_ * 0.72] if tracks == 2 else [-w_ * 0.5]
    for xx in pos:
        ev.rect(xx - 0.012, H + w_ - 0.02, xx + 0.012, H + w_, w=0.3, fc="#bdbdbd", z=ev.z + 4)
        ev.line([xx, xx], [H + w_ - 0.02, 2.53], w=0.35, c="#8c8577", ls=(0, (4, 2)), z=ev.z + 4)
    ev.rect(-w_ - 0.016, H - 0.012, -w_ - 0.0, H, w=0.2, fc=HL, z=ev.z + 4.2)
    ev.hchain(2.555, [-w_ - 0.0245, -0.012, 0.0], size=4.0, above=False)
    ev.vchain(-0.245, [H, H + w_ + 0.0125], left=True, size=4.0)
    ev.note(-0.20, H + 0.006, "12.5 board on 60/27 furring")
    ev.note(-w_ - 0.018, H + w_ * 0.5, "Pocket side: board on steel angle + stud, corner bead", key=True)
    ev.note(-w_ * 0.5, H + w_ + 0.02, "Plywood 18 backing for the tracks, fixed to the slab")
    ev.note(pos[0], H + w_ - 0.01, ("Double track: sheer (glass side) + linen, motorised" if tracks == 2 else "Single track for the divider curtain"), key=True)
    ev.note(-w_ - 0.008, H - 0.006, "LED profile on the room-side lip (warm 24 V)")
    ev.note(-0.006, 2.60, "Window head / wall face")
    ev.place_notes(at=0.09, size=4.0, wrap_chars=34, vmin=2.53, vmax=ST + 0.04)
    title_under(s, None, x, y - 8, "CS", title, scale="1:5")
    return ev


def typical_ceiling(P, s, x, y, sc=10):
    H = P.m.ceiling
    ev, w, h = view(s, x, y, (0.0, 0.75), (2.48, 3.02), sc)
    ev.rect(0.0, SOFFIT, 0.75, 3.02, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 2)
    ev.rect(0.0, H, 0.75, H + 0.0125, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(0.0, H + 0.0125, 0.75, H + 0.04, w=0.2, fc="#e6e6e6", z=ev.z + 2.8)
    for xx in (0.05, 0.55):
        ev.line([xx, xx], [H + 0.04, SOFFIT], w=0.4, c=GREY, z=ev.z + 2.6)
        ev.rect(xx - 0.02, H + 0.04, xx + 0.02, H + 0.07, w=0.25, fc="#cfcfcf", z=ev.z + 2.7)
        ev.rect(xx - 0.008, SOFFIT - 0.02, xx + 0.008, SOFFIT, w=0.25, fc="#9a9a9a", z=ev.z + 2.7)
    ev.rect(0.25, H + 0.0125, 0.33, H + 0.10, w=0.25, fc="white", z=ev.z + 3.2)
    ev.text(0.29, H + 0.13, "spot", size=3.4, z=ev.z + 4)
    ev.line([0.36, 0.60], [H + 0.16, H + 0.16], w=1.0, c="#7aa7c7", z=ev.z + 3)
    ev.text(0.48, H + 0.19, "PPR supply", size=3.4, z=ev.z + 4)
    ev.hchain(2.995, [0.05, 0.55], txt=["hangers <= 120 (drawn closer)"], size=3.8)
    ev.vchain(0.70, [H, SOFFIT], txt=["~36 void"], size=4.0)
    ev.note(0.05, 2.80, "Hanger: anchor + threaded rod / adjustable hanger, max 120 c/c")
    ev.note(0.30, H + 0.055, "Main channel + 60/27 furring @ 50 (40 in wet rooms), profiles >= 0.4 mm galvanised")
    ev.note(0.15, H + 0.006, "12.5 board, joints taped + 2 coats filler, paint")
    ev.note(0.29, H + 0.06, "Spot housing: 7-10 cm free depth")
    ev.place_notes(at=0.78, size=4.0, wrap_chars=30, vmin=2.48, vmax=3.0)
    title_under(s, None, x, y - 8, "CS1", "CS1 - TYPICAL SUSPENDED CEILING", scale="1:10")
    return ev


def access_panel(P, s, x, y, sc=5):
    H = P.m.ceiling
    ev, w, h = view(s, x, y, (-0.05, 0.68), (H - 0.06, H + 0.12), sc)
    ev.rect(-0.05, H, 0.0, H + 0.0125, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(0.62, H, 0.68, H + 0.0125, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(0.0, H + 0.0125, 0.012, H + 0.06, w=0.25, fc="#cfcfcf", z=ev.z + 3)
    ev.rect(0.608, H + 0.0125, 0.62, H + 0.06, w=0.25, fc="#cfcfcf", z=ev.z + 3)
    ev.rect(0.004, H - 0.0005, 0.616, H + 0.012, w=0.3, fc="#f5f5f5", z=ev.z + 3.2)
    ev.line([0.004, 0.10], [H + 0.012, H - 0.05], w=0.2, c=GREY, ls=(0, (3, 2)), z=ev.z + 3)
    ev.text(0.30, H + 0.08, "valve / pipe joint above", size=3.6, z=ev.z + 4)
    ev.hchain(H + 0.105, [0.0, 0.62], txt=["60 clear"], size=4.0)
    ev.note(0.31, H + 0.006, "Panel 60 x 60, same board, hidden aluminium frame, push-latch + safety cord", key=True)
    ev.note(0.006, H + 0.04, "Frame fixed to the furring, not to the board")
    ev.place_notes(at=0.72, size=4.0, wrap_chars=40, vmin=H - 0.06, vmax=H + 0.12)
    title_under(s, None, x, y - 8, "AP", "AP - ACCESS PANEL 60 x 60 (section)", scale="1:5")
    return ev


def bath_ceiling(P, s, x, y, sc=10):
    H = P.m.ceiling
    ev, w, h = view(s, x, y, (0.0, 0.75), (2.48, 3.02), sc)
    ev.rect(0.0, SOFFIT, 0.75, 3.02, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 2)
    ev.cutwall(0.0, 0.06, 2.48, SOFFIT)
    ev.rect(0.06, H, 0.75, H + 0.0125, w=0.3, fc="#dfeedd", z=ev.z + 3)
    ev.rect(0.06, H + 0.0125, 0.75, H + 0.04, w=0.2, fc="#e6e6e6", z=ev.z + 2.8)
    ev.rect(0.40, H + 0.0125, 0.52, H + 0.08, w=0.3, fc="white", z=ev.z + 3.2)
    ev.poly([(0.52, H + 0.05), (0.62, H + 0.10), (0.06, H + 0.27)], w=0.0, c="none", closed=False)
    ev.line([0.46, 0.46, 0.06], [H + 0.08, H + 0.22, H + 0.25], w=2.2, c="#bdbdbd", z=ev.z + 3)
    ev.rect(0.06, 2.49, 0.075, H, w=0.2, fc="#e4ddd0", z=ev.z + 3)
    ev.vchain(0.70, [H, SOFFIT], txt=["~36 void"], size=4.0)
    ev.note(0.30, H + 0.006, "Green board 12.5, furring @ 40, anti-mould paint", key=True)
    ev.note(0.46, H + 0.05, "Exhaust fan in the ceiling (own key / sensor)")
    ev.note(0.30, H + 0.235, "Duct 100 falling to outside, back-draft flap at the wall")
    ev.note(0.067, 2.52, "Wall tiles stop 2-3 mm under the board; silicone joint")
    ev.place_notes(at=0.78, size=4.0, wrap_chars=30, vmin=2.48, vmax=3.0)
    title_under(s, None, x, y - 8, "CS4", "CS4 - BATHROOM CEILING WITH FAN", scale="1:10")
    return ev


def concealed_ac(P, s, x, y, sc=20):
    ev, w, h = view(s, x, y, (0.0, 1.50), (2.20, 3.02), sc)
    ev.rect(0.0, SOFFIT, 1.50, 3.02, w=0.35, fc="#d9d9d9", hatch="..", z=ev.z + 2)
    ev.rect(0.0, 2.36, 1.50, 2.3725, w=0.3, fc="white", z=ev.z + 3)
    ev.rect(0.25, 2.55, 1.15, 2.76, w=0.35, fc="#eeeeee", z=ev.z + 3)
    ev.text(0.70, 2.655, "ducted unit ~21 high", size=3.8, z=ev.z + 4)
    ev.rect(0.40, 2.3725, 1.00, 2.385, w=0.3, c=HL, fc="white", z=ev.z + 3.5)
    ev.line([1.15, 1.45], [2.60, 2.58], w=0.6, c="#7aa7c7", z=ev.z + 3)
    ev.line([0.25, 0.10], [2.58, 2.56], w=0.4, c=GREY, ls=(0, (4, 2)), z=ev.z + 3)
    ev.vchain(1.47, [2.36, SOFFIT], txt=["~60 (TP)"], size=4.0)
    ev.note(0.70, 2.38, "60 x 60 hatch under the filter side", key=True)
    ev.note(1.30, 2.59, "Condensate drain with >= 1 % fall")
    ev.note(0.70, 2.70, "Hung on rods with anti-vibration mounts")
    ev.note(0.17, 2.57, "Supply / return grilles in the ceiling or a side bulkhead")
    ev.place_notes(at=1.52, size=4.0, wrap_chars=26, vmin=2.22, vmax=3.0)
    title_under(s, None, x, y - 8, "TP", "LOTUS TP OPTION - concealed ducted AC (not in Main)", scale="1:20")
    return ev


# =====================================================================================================================
# LIVING ROOM TV WALL
# =====================================================================================================================
TAUPE = "#d9cbbb"


def living_tv_elev(P, s, x, y, sc=25):
    H = P.m.ceiling
    wall = Wall((6.133, 4.43), (6.133, 0.555))
    L = wall.L
    U = lambda yy: 4.43 - yy
    ev, w, h = view(s, x, y, (-0.58, L + 1.30), (-0.22, H + 0.30), sc)
    std_frame(ev, L, H)
    ev.rect(0, 0, L, H, w=0.15, fc="#f3eee6")
    ev.rect(U(4.0), 0, L, H, w=0.3, fc=TAUPE, z=ev.z + 1)
    ev.text(U(3.75), 2.40, "limewash taupe panel", size=3.6, c=GREY, z=ev.z + 2)
    ev.rect(0, 0, L, 0.08, w=0.25, fc=WOOD, z=ev.z + 2)
    # sconces with LED
    for yy in (1.10, 3.40):
        ev.rect(U(yy) - 0.012, 1.15, U(yy) + 0.012, 1.90, w=0.3, fc="#d9c08a", r=0.006, z=ev.z + 4)
        ev.led(U(yy), 1.17, U(yy), 1.88)
    # TV
    ev.tv(U(2.25), 1.10, 1.60, 0.85)
    ev.line([U(2.25), U(2.25)], [0.80, 2.15], w=0.15, c=HL, ls=(0, (8, 2, 1, 2)))
    # console
    ev.drawers(U(3.12), U(1.38), 0.45, 0.72, n=3, fc=WOOD, handles=None)
    ev.grain(U(3.12), 0.45, U(1.38), 0.72, n=3)
    ev.rect(U(3.12), 0.72, U(1.38), 0.75, w=0.35, fc="#e7e2d8", z=ev.z + 2.6)
    ev.led(U(3.09), 0.44, U(1.41), 0.44)
    elec_overlay(ev, P, wall, H, depth=0.45)
    ev.hchain(H + 0.17, [0, U(4.0), U(3.40), U(3.05), U(2.25), U(1.45), U(1.10), L])
    ev.hchain(-0.17, [U(3.12), U(1.38)], above=False)
    ev.vchain(-0.24, [0, 0.45, 0.75, 1.10, 1.525, 1.95, H], left=True)
    ev.vchain(L + 0.24, [0, 1.15, 1.90, H])
    ev.note(U(2.25), 1.80, "TV 160 x 85 (65\"), bottom 110, centre 152.5; wall bracket on solid backing", key=True)
    ev.note(U(3.40), 1.60, "Thin brass LED sconces 115-190, 115 either side of the TV centre line")
    ev.note(U(2.6), 0.60, "Floating walnut console 174 x 40, 45-72, 3 push-open fronts")
    ev.note(U(2.0), 0.735, "Stone top 3 cm, top 75")
    ev.note(U(2.8), 0.44, "LED under-glow (L-203 driver in the console)")
    ev.note(U(3.8), 1.20, "Limewash taupe panel 350 wide, full height (wall face)", key=True)
    ev.note(U(1.7), 1.20, "TV plate 120 behind the TV; console plate 60 (data, HDMI, TV, 2 sockets)")
    ev.note(U(1.0), 0.04, "Oak skirting ~8")
    ev.place_notes(at=L + 0.42, wrap_chars=36, vmin=-0.2, vmax=H + 0.25)
    return ev, w, h


def sheet_living_tv(P):
    s = P.new("A4", "D502", "Living room TV wall - elevation", "1:25",
              "Front-on view of the TV wall with TV, console, sconces and points")
    living_tv_elev(P, s, s.m + 2, s.m + 24)
    title_under(s, None, s.m + 2, s.m + 16, "A", "ELEVATION - living room east (TV) wall, looking east", scale="1:25")
    side_notes(s, [
        "TV wall face x 6.138 on the column plane (Main); TV centre line y 2.25.",
        "Backing: 18 mm plywood or solid blockwork behind the TV bracket and the console cleat; mark before plastering.",
        "TV on a low-profile tilt bracket (TV ~5 cm off the wall); console 40 deep hung on a concealed steel cleat into blockwork.",
        "Cables: 2 x 40 mm conduits inside the wall from the console plate (60) to the TV plate (120).",
        "Lotus TP p.24 shows the living room with a wall split AC and ceiling -150; Main governs (CH 260).",
    ])
    s.scale_bar(s.side_x - 62, s.m + 5, 25, metres=1, step=0.25, label="SCALE 1:25")
    return [s]
