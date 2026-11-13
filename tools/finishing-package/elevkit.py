"""Drawing kit for the R1 detail sheets: front-on elevations, sections and enlarged plans drawn with real shapes.

Everything is drawn in metres into an axes made by Sheet.plan_axes (so 1:25 prints true): u = along the wall
(left to right as you face it), v = height above finished floor. `EV` holds one view and offers:
  - frame pieces: floor / ceiling / cut walls (poche), slab, ground
  - finishes: tiles, planks, slats, wood grain, render, stone, glass, mirror
  - objects: wall-hung WC (front / side), basins, mixers, shower sets, rails, hooks, doors, windows, sliders,
    AC units, TV, drawers, curtains, plants, LED lines
  - dimension chains (horizontal / vertical, cm) and callouts with leaders collected and laid out in a column
Black linework plus the one highlight colour (HL) for dimensions and key callouts.
"""
import math
import numpy as np
from matplotlib.patches import Rectangle, Polygon as MPoly, FancyBboxPatch, Circle, Ellipse, Arc, PathPatch
from matplotlib.path import Path as MPath
from sheetlib import HL, INK, GREY, LIGHT, lw

POCHE = "#bdbdbd"
SOFT = "#efefef"
GLASS = "#e6eef2"
WOOD = "#e9dcc4"
STONE = "#ece8e1"
DARK = "#3a3a3a"


def cm(d, nd=None):
    """Metres -> cm text, rounded to 0.5 cm ('28.5', '120')."""
    v = round(d * 200) / 2
    if nd is not None:
        return f"{d * 100:.{nd}f}"
    return f"{v:.0f}" if abs(v - round(v)) < 1e-6 else f"{v:.1f}"


class EV:
    def __init__(self, ax, s=None, z0=3):
        self.ax = ax
        self.s = s
        self.k = 1.0 / ax._mm_per_m          # metres per paper mm
        self.notes = []
        self.z = z0

    # ---------- primitives ----------
    def line(self, us, vs, w=0.25, c=INK, ls="-", z=None, clip=False, cap="butt"):
        self.ax.plot(us, vs, color=c, lw=lw(w), ls=ls, zorder=z or self.z + 1, solid_capstyle=cap, clip_on=clip)

    def rect(self, u0, v0, u1, v1, w=0.25, c=INK, fc="none", hatch=None, z=None, ls="-", alpha=1.0, r=0.0):
        if r > 0:
            p = FancyBboxPatch((min(u0, u1), min(v0, v1)), abs(u1 - u0), abs(v1 - v0),
                               boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=c, lw=lw(w), zorder=z or self.z,
                               ls=ls, alpha=alpha, clip_on=False)
            if hatch:
                p.set_hatch(hatch)
        else:
            p = Rectangle((min(u0, u1), min(v0, v1)), abs(u1 - u0), abs(v1 - v0), fc=fc, ec=c, lw=lw(w),
                          zorder=z or self.z, hatch=hatch, ls=ls, alpha=alpha, clip_on=False)
        self.ax.add_patch(p)
        return p

    def poly(self, pts, w=0.25, c=INK, fc="none", hatch=None, z=None, closed=True, ls="-"):
        self.ax.add_patch(MPoly(pts, closed=closed, fc=fc, ec=c, lw=lw(w), hatch=hatch, zorder=z or self.z, ls=ls,
                                clip_on=False))

    def text(self, u, v, t, size=4.4, c=INK, ha="center", va="center", rot=0, weight="normal", bg=None, z=None,
             style="normal"):
        kw = dict(fontsize=size, color=c, ha=ha, va=va, rotation=rot, weight=weight, zorder=z or 12, style=style,
                  rotation_mode="anchor", clip_on=False)
        if bg:
            kw["bbox"] = dict(fc=bg, ec="none", pad=0.15)
        return self.ax.text(u, v, t, **kw)

    # ---------- frame ----------
    def floor(self, u0, u1, depth=0.12, label=None):
        self.line([u0, u1], [0, 0], w=0.5)
        self.rect(u0, -depth, u1, 0, w=0.0, c="none", fc="white", hatch="....", z=self.z - 1)
        if label:
            self.text(u0 + 0.02, -depth / 2, label, size=3.6, ha="left", c=GREY)

    def ceiling(self, u0, u1, H, void=0.10, label=None, hatch="////"):
        self.line([u0, u1], [H, H], w=0.35)
        if void:
            self.rect(u0, H, u1, H + void, w=0.0, c="none", fc="white", hatch=hatch, z=self.z - 1)
            self.line([u0, u1], [H + void, H + void], w=0.12, c=GREY, ls=(0, (4, 2)))
        if label:
            self.text(u0 + 0.03, H + void / 2, label, size=3.6, ha="left", c=GREY, bg="white")

    def cutwall(self, u0, u1, v0, v1, fc=POCHE, hatch="////"):
        self.rect(u0, v0, u1, v1, w=0.35, fc=fc, hatch=hatch, z=self.z + 2)

    def wall_outline(self, u0, u1, v0, v1, w=0.35):
        self.rect(u0, v0, u1, v1, w=w)

    # ---------- finishes ----------
    def tiles(self, u0, v0, u1, v1, tw, th, ou=None, ov=None, c="#8a8a8a", w=0.08, stagger=0.0):
        """Tile joints inside the box; ou/ov = a joint position to set out from."""
        ou = u0 if ou is None else ou
        ov = v0 if ov is None else ov
        v = ov - math.ceil((ov - v0) / th) * th
        row = 0
        segs = []
        while v <= v1 + 1e-6:
            if v0 + 1e-6 < v < v1 - 1e-6:
                segs.append(([u0, u1], [v, v]))
            vb, vt = max(v, v0), min(v + th, v1)
            if vt > vb:
                off = (stagger * tw * (row % 2))
                u = ou + off - math.ceil((ou + off - u0) / tw) * tw
                while u <= u1 + 1e-6:
                    if u0 + 1e-6 < u < u1 - 1e-6:
                        segs.append(([u, u], [vb, vt]))
                    u += tw
            v += th
            row += 1
        for us, vs in segs:
            self.line(us, vs, w=w, c=c, z=self.z + 0.2)

    def vjoints(self, us, v0, v1, c="#8a8a8a", w=0.08, z=None):
        for u in us:
            self.line([u, u], [v0, v1], w=w, c=c, z=self.z + 0.2 if z is None else z)

    def hjoints(self, vs, u0, u1, c="#8a8a8a", w=0.08, z=None):
        for v in vs:
            self.line([u0, u1], [v, v], w=w, c=c, z=self.z + 0.2 if z is None else z)

    def slats(self, u0, u1, v0, v1, pitch=0.045, gap=True, c="#6e6e6e"):
        u = u0 + pitch
        while u < u1 - 1e-6:
            self.line([u, u], [v0, v1], w=0.1, c=c, z=self.z + 0.3)
            u += pitch

    def planks(self, u0, u1, v0, v1, pw=0.20, pl=1.2, vertical=True, c="#8a8a8a"):
        """Wood-look planks: long joints every pw, short end joints staggered."""
        if vertical:
            k = 0
            u = u0
            while u < u1 - 1e-6:
                un = min(u + pw, u1)
                if un < u1 - 1e-6:
                    self.line([un, un], [v0, v1], w=0.08, c=c, z=self.z + 0.2)
                off = (k % 3) * pl / 3
                v = v0 + off + pl * 0.4
                while v < v1 - 1e-6:
                    self.line([u, un], [v, v], w=0.08, c=c, z=self.z + 0.2)
                    v += pl
                u = un
                k += 1
        else:
            k = 0
            v = v0
            while v < v1 - 1e-6:
                vn = min(v + pw, v1)
                if vn < v1 - 1e-6:
                    self.line([u0, u1], [vn, vn], w=0.08, c=c, z=self.z + 0.2)
                off = (k % 3) * pl / 3
                u = u0 + off + pl * 0.4
                while u < u1 - 1e-6:
                    self.line([u, u], [v, vn], w=0.08, c=c, z=self.z + 0.2)
                    u += pl
                v = vn
                k += 1

    def grain(self, u0, v0, u1, v1, n=3, vertical=False, c="#9a8a70"):
        """A few soft wood-grain strokes."""
        rng = np.random.default_rng(int(abs(u0 * 1000 + v0 * 77)) % 9999)
        for i in range(n):
            if vertical:
                u = u0 + (u1 - u0) * (i + 0.5) / n
                vs = np.linspace(v0 + 0.02, v1 - 0.02, 20)
                us = u + 0.006 * np.sin(vs * 9 + rng.uniform(0, 6))
            else:
                v = v0 + (v1 - v0) * (i + 0.5) / n
                us = np.linspace(u0 + 0.02, u1 - 0.02, 20)
                vs = v + 0.005 * np.sin(us * 9 + rng.uniform(0, 6))
            self.ax.plot(us, vs, color=c, lw=lw(0.06), zorder=self.z + 0.3, clip_on=False)

    def glass(self, u0, v0, u1, v1, frame=0.0, fc=GLASS, w=0.2, frosted=False, z=None):
        zz = z if z is not None else self.z + 1
        self.rect(u0, v0, u1, v1, w=w, fc=fc, z=zz, hatch="...." if frosted else None)
        if frame:
            self.rect(u0, v0, u1, v1, w=0.0, c="none", fc="none")
            for a, b, c_, d in ((u0, v0, u1, v0 + frame), (u0, v1 - frame, u1, v1), (u0, v0, u0 + frame, v1),
                                (u1 - frame, v0, u1, v1)):
                self.rect(a, b, c_, d, w=0.12, fc=DARK, z=zz + 0.5)
        # reflection strokes
        W, H = u1 - u0, v1 - v0
        for f, L in ((0.25, 0.22), (0.33, 0.12)):
            cu, cv = u0 + W * f, v0 + H * 0.62
            d = min(W, H) * L
            self.line([cu - d * 0.5, cu + d * 0.5], [cv - d * 0.5, cv + d * 0.5], w=0.1, c="#7d8c94", z=zz + 0.6)

    def mirror(self, u0, v0, u1, v1, r=0.0, frame=0.0, label=None):
        self.rect(u0, v0, u1, v1, w=0.25, fc="#f2f5f7", r=r, z=self.z + 1)
        if frame:
            self.rect(u0 + frame, v0 + frame, u1 - frame, v1 - frame, w=0.1, r=max(r - frame, 0), z=self.z + 1.1)
        W, H = u1 - u0, v1 - v0
        for f, L in ((0.3, 0.26), (0.4, 0.14), (0.62, 0.1)):
            cu, cv = u0 + W * f, v0 + H * 0.58
            d = min(W, H) * L
            self.line([cu - d / 2, cu + d / 2], [cv - d / 2, cv + d / 2], w=0.1, c="#7d8c94", z=self.z + 1.2)

    def pebble(self, uc, vc, w, h, glow=True):
        e = Ellipse((uc, vc), w, h, fc="#f2f5f7", ec=INK, lw=lw(0.25), zorder=self.z + 1, clip_on=False)
        self.ax.add_patch(e)
        if glow:
            self.ax.add_patch(Ellipse((uc, vc), w + 0.05, h + 0.05, fc="none", ec=HL, lw=lw(0.12), ls=(0, (2, 1.5)),
                                      zorder=self.z + 1, clip_on=False))
        for f, L in ((-0.18, 0.2), (-0.08, 0.1)):
            cu, cv = uc + w * f, vc + h * 0.1
            d = min(w, h) * L
            self.line([cu - d / 2, cu + d / 2], [cv - d / 2, cv + d / 2], w=0.1, c="#7d8c94", z=self.z + 1.2)

    def led(self, u0, v0, u1, v1, w=0.35):
        self.line([u0, u1], [v0, v1], w=w, c=HL, ls=(0, (2.2, 1.2)), z=self.z + 3)

    # ---------- sanitaryware & fittings ----------
    def wc_front(self, uc, seat=0.42, w=0.36, bottom=0.25):
        """Wall-hung WC seen from the front."""
        r = 0.09
        t = seat - 0.025
        pts = [(uc - w / 2, t)]
        for a in np.linspace(math.pi, 1.5 * math.pi, 8):
            pts.append((uc - w / 2 + r + r * math.cos(a), bottom + r + r * math.sin(a)))
        for a in np.linspace(1.5 * math.pi, 2 * math.pi, 8):
            pts.append((uc + w / 2 - r + r * math.cos(a), bottom + r + r * math.sin(a)))
        pts.append((uc + w / 2, t))
        self.poly(pts, fc="white", w=0.3, z=self.z + 4)
        self.rect(uc - w / 2 - 0.005, t, uc + w / 2 + 0.005, seat, w=0.25, fc="white", r=0.008, z=self.z + 4.1)
        self.line([uc - w / 2 + 0.05, uc + w / 2 - 0.05], [bottom + 0.05, bottom + 0.05], w=0.08, c=GREY, z=self.z + 4.2)

    def wc_side(self, uw, sgn, seat=0.42, L=0.54, bottom=0.25):
        """Wall-hung WC in side view; uw = wall face, sgn = +1 projects to +u."""
        t = seat - 0.022
        pts = [(0, t), (L - 0.05, t), (L - 0.005, t - 0.025), (L - 0.01, t - 0.07), (L - 0.06, t - 0.11),
               (L * 0.6, t - 0.13), (0.22, t - 0.15), (0.10, bottom), (0, bottom)]
        pts = [(uw + sgn * a, b) for a, b in pts]
        self.poly(pts, fc="white", w=0.3, z=self.z + 4)
        self.rect(uw, seat - 0.022, uw + sgn * (L - 0.02), seat, w=0.25, fc="white", r=0.006, z=self.z + 4.1)
        self.rect(uw, seat, uw + sgn * 0.05, seat + 0.03, w=0.15, fc="white", z=self.z + 4.1)

    def flush_plate(self, uc, v0, v1, w=0.24, dual=True):
        self.rect(uc - w / 2, v0, uc + w / 2, v1, w=0.25, fc="#d9cfa8", r=0.006, z=self.z + 4)
        if dual:
            self.rect(uc - w / 2 + 0.025, v0 + 0.03, uc - 0.01, v1 - 0.03, w=0.12, fc="white", r=0.004, z=self.z + 4.1)
            self.rect(uc + 0.01, v0 + 0.03, uc + w / 2 - 0.025, v1 - 0.03, w=0.12, fc="white", r=0.004, z=self.z + 4.1)

    def bidet_mixer(self, u, v):
        self.ax.add_patch(Circle((u, v), 0.022, fc="white", ec=INK, lw=lw(0.2), zorder=self.z + 4, clip_on=False))
        self.rect(u - 0.006, v + 0.015, u + 0.006, v + 0.06, w=0.15, fc="white", z=self.z + 4)

    def spout(self, u, v, L=0.15, front=True):
        if front:
            self.rect(u - 0.022, v - 0.015, u + 0.022, v + 0.015, w=0.2, fc="white", r=0.005, z=self.z + 4)
        else:
            self.rect(u, v - 0.012, u + L, v + 0.012, w=0.2, fc="white", r=0.004, z=self.z + 4)

    def knob(self, u, v, r=0.025):
        self.ax.add_patch(Circle((u, v), r, fc="white", ec=INK, lw=lw(0.2), zorder=self.z + 4, clip_on=False))
        self.ax.add_patch(Circle((u, v), r * 0.35, fc=INK, ec=INK, lw=lw(0.1), zorder=self.z + 4.1, clip_on=False))

    def plate(self, uc, vc, w=0.18, h=0.18, knobs=2, round_=False):
        if round_:
            self.ax.add_patch(Circle((uc, vc), w / 2, fc="white", ec=INK, lw=lw(0.25), zorder=self.z + 4, clip_on=False))
            self.knob(uc, vc, 0.03)
            return
        self.rect(uc - w / 2, vc - h / 2, uc + w / 2, vc + h / 2, w=0.25, fc="white", r=0.01, z=self.z + 4)
        for i in range(knobs):
            self.knob(uc, vc - h / 4 + i * h / 2 if knobs == 2 else vc, 0.022)

    def rain_front(self, uc, v, dia=0.25):
        self.ax.add_patch(Circle((uc, v + 0.03), 0.018, fc="white", ec=INK, lw=lw(0.2), zorder=self.z + 4, clip_on=False))
        self.rect(uc - dia / 2, v - 0.012, uc + dia / 2, v + 0.004, w=0.25, fc="white", r=0.004, z=self.z + 4)
        for i in range(-3, 4):
            self.line([uc + i * dia / 8, uc + i * dia / 8 - 0.01], [v - 0.02, v - 0.06], w=0.06, c=GREY, z=self.z + 4)

    def rain_side(self, uw, sgn, v, arm=0.42, dia=0.25):
        self.line([uw, uw + sgn * arm], [v + 0.02, v + 0.02], w=0.5, z=self.z + 4)
        a = uw + sgn * arm
        self.rect(a - dia / 2, v - 0.012, a + dia / 2, v + 0.006, w=0.25, fc="white", r=0.004, z=self.z + 4)

    def hand_shower(self, u, v_hold, v_out=None):
        self.rect(u - 0.018, v_hold - 0.02, u + 0.018, v_hold + 0.02, w=0.2, fc="white", z=self.z + 4)
        self.rect(u - 0.016, v_hold - 0.12, u + 0.016, v_hold + 0.12, w=0.25, fc="white", r=0.014, z=self.z + 4.2)
        if v_out is not None:
            self.knob(u, v_out, 0.018)
            uu = np.linspace(0, 1, 30)
            hu = u + 0.05 * np.sin(uu * math.pi)
            hv = v_out + (v_hold - 0.12 - v_out) * uu - 0.18 * np.sin(uu * math.pi)
            self.ax.plot(hu, hv, color=INK, lw=lw(0.15), zorder=self.z + 4, clip_on=False)

    def basin_vessel(self, uc, top, w=0.55, h=0.12):
        """Low vessel basin on a counter (front)."""
        r = h * 0.9
        pts = [(uc - w / 2, top + h)]
        for a in np.linspace(math.pi, 1.5 * math.pi, 10):
            pts.append((uc - w / 2 + r + r * math.cos(a), top + r + r * math.sin(a)))
        for a in np.linspace(1.5 * math.pi, 2 * math.pi, 10):
            pts.append((uc + w / 2 - r + r * math.cos(a), top + r + r * math.sin(a)))
        pts.append((uc + w / 2, top + h))
        self.poly(pts, fc="white", w=0.3, z=self.z + 4)
        self.line([uc - w / 2, uc + w / 2], [top + h, top + h], w=0.3, z=self.z + 4.1)

    def basin_inset(self, uc, top, w=0.48, depth=0.15):
        self.rect(uc - w / 2, top - depth, uc + w / 2, top, w=0.15, ls=(0, (3, 2)), r=0.04, z=self.z + 4)

    def towel_rail(self, u0, u1, v, towel=True):
        self.line([u0, u1], [v, v], w=0.45, z=self.z + 4, cap="round")
        for u in (u0 + 0.02, u1 - 0.02):
            self.rect(u - 0.012, v - 0.015, u + 0.012, v + 0.015, w=0.15, fc="white", z=self.z + 4.1)
        if towel:
            m = (u0 + u1) / 2
            tw = (u1 - u0) * 0.6
            self.rect(m - tw / 2, v - 0.55, m + tw / 2, v + 0.015, w=0.2, fc="#f4f1ea", z=self.z + 3.9, r=0.01)
            self.line([m - tw / 2 + 0.02, m + tw / 2 - 0.02], [v - 0.48, v - 0.48], w=0.08, c=GREY, z=self.z + 3.95)

    def hook(self, u, v):
        self.ax.add_patch(Circle((u, v), 0.016, fc="white", ec=INK, lw=lw(0.2), zorder=self.z + 4, clip_on=False))
        self.line([u, u], [v, v + 0.03], w=0.25, z=self.z + 4)

    def roll(self, u, v):
        self.rect(u - 0.07, v - 0.005, u + 0.07, v + 0.01, w=0.2, fc="white", z=self.z + 4)
        self.ax.add_patch(Circle((u, v - 0.05), 0.055, fc="white", ec=INK, lw=lw(0.2), zorder=self.z + 4, clip_on=False))

    def niche(self, u0, v0, u1, v1, shelves=(), r=0.0, led_top=True, led_shelves=True, fc="#e4e1dc", t=0.02):
        self.rect(u0, v0, u1, v1, w=0.3, fc=fc, r=r, z=self.z + 2)
        self.rect(u0 + 0.012, v0 + 0.012, u1 - 0.012, v1 - 0.012, w=0.08, c=GREY, r=max(r - 0.012, 0), z=self.z + 2.1)
        for s in shelves:
            self.rect(u0 + 0.005, s - t, u1 - 0.005, s, w=0.15, fc="white", z=self.z + 2.2)
            if led_shelves:
                self.led(u0 + 0.03, s - t - 0.008, u1 - 0.03, s - t - 0.008, w=0.25)
        if led_top:
            tv = v1 - (r * 0.6 if r else 0) - 0.02
            self.led(u0 + 0.05, tv, u1 - 0.05, tv, w=0.25)

    def drawers(self, u0, u1, v0, v1, n=None, width=0.6, rows=1, gap=0.004, fc=WOOD, handles="groove"):
        self.rect(u0, v0, u1, v1, w=0.3, fc=fc, z=self.z + 2)
        n = n or max(1, round((u1 - u0) / width))
        for i in range(1, n):
            u = u0 + i * (u1 - u0) / n
            self.line([u, u], [v0 + 0.01, v1 - 0.01], w=0.15, z=self.z + 2.1)
        for j in range(1, rows):
            v = v0 + j * (v1 - v0) / rows
            self.line([u0 + 0.01, u1 - 0.01], [v, v], w=0.15, z=self.z + 2.1)
        if handles == "groove":
            self.line([u0 + 0.01, u1 - 0.01], [v1 - 0.03, v1 - 0.03], w=0.1, c=GREY, z=self.z + 2.1)
        elif handles == "knob":
            for i in range(n):
                uc = u0 + (i + 0.5) * (u1 - u0) / n
                for j in range(rows):
                    vc = v0 + (j + 0.75) * (v1 - v0) / rows
                    self.line([uc - 0.05, uc + 0.05], [vc, vc], w=0.4, z=self.z + 2.2, cap="round")

    def door(self, u0, u1, head=2.10, hinge="left", frame=0.06, leaf_fc="#efe3cc", handle_v=1.0, label=None, glass=False):
        self.rect(u0 - frame, 0, u1 + frame, head + frame, w=0.3, fc="white", z=self.z + 2)
        self.rect(u0, 0.008, u1, head, w=0.3, fc=leaf_fc, z=self.z + 2.1)
        if glass:
            self.glass(u0 + 0.12, 0.25, u1 - 0.12, head - 0.2)
        hu = u1 - 0.07 if hinge == "left" else u0 + 0.07
        sg = -1 if hinge == "left" else 1
        self.ax.add_patch(Circle((hu, handle_v), 0.022, fc="white", ec=INK, lw=lw(0.2), zorder=self.z + 3, clip_on=False))
        self.line([hu, hu + sg * 0.13], [handle_v, handle_v], w=0.5, z=self.z + 3, cap="round")
        # swing indication: lines from the handle-side corners to the hinge side mid-height
        hx = u0 if hinge == "left" else u1
        ox = u1 if hinge == "left" else u0
        self.line([ox, hx, ox], [0.01, head / 2, head], w=0.1, c=GREY, ls=(0, (4, 3)), z=self.z + 2.2)

    def window(self, u0, u1, sill, head, frame=0.06, kind="fixed", frosted=False, panels=None, slide_dir=1):
        self.rect(u0, sill, u1, head, w=0.35, fc="white", z=self.z + 2)
        if kind == "slider":
            n = panels or 2
            pw = (u1 - u0) / n
            for i in range(n):
                a, b = u0 + i * pw, u0 + (i + 1) * pw
                ov = 0.025 if i < n - 1 else 0
                self.rect(a + (0.0 if i == 0 else -0.02), sill + 0.0, b + ov, head, w=0.3, fc="white", z=self.z + 2.2 + i * 0.1)
                self.glass(a + frame + (0 if i == 0 else -0.02), sill + frame + (0.03 if sill == 0 else 0), b + ov - frame,
                           head - frame, frosted=frosted, z=self.z + 2.25 + i * 0.1)
            # arrow on the sliding panel
            i = n - 1 if slide_dir < 0 else 0
            a, b = u0 + i * pw, u0 + (i + 1) * pw
            vm = sill + (head - sill) * 0.42
            self.ax.annotate("", xy=(a + pw / 2 + slide_dir * pw * 0.28, vm), xytext=(a + pw / 2 - slide_dir * pw * 0.28, vm),
                             arrowprops=dict(arrowstyle="-|>", lw=lw(0.25), color=INK, mutation_scale=6), zorder=self.z + 6)
        else:
            n = panels or 1
            pw = (u1 - u0) / n
            for i in range(n):
                a, b = u0 + i * pw, u0 + (i + 1) * pw
                self.rect(a, sill, b, head, w=0.25, fc="white", z=self.z + 2.2)
                self.glass(a + frame, sill + frame, b - frame, head - frame, frosted=frosted, z=self.z + 2.3)
                if kind == "casement":
                    hx, ox = (a, b) if i % 2 == 0 else (b, a)
                    self.line([ox - (frame if ox > hx else -frame), hx + (frame if ox > hx else -frame), ox - (frame if ox > hx else -frame)],
                              [sill + frame, (sill + head) / 2, head - frame], w=0.1, c=GREY, ls=(0, (4, 3)), z=self.z + 3)

    def ac_split(self, uc, top, w=1.05, h=0.30, label=True):
        self.rect(uc - w / 2, top - h, uc + w / 2, top, w=0.3, fc="white", r=0.03, z=self.z + 3)
        self.rect(uc - w / 2 + 0.06, top - h + 0.025, uc + w / 2 - 0.06, top - h + 0.06, w=0.15, fc="#dedede", z=self.z + 3.1)
        self.ax.add_patch(Circle((uc + w / 2 - 0.1, top - h * 0.45), 0.008, fc=INK, ec=INK, zorder=self.z + 3.2, clip_on=False))

    def tv(self, uc, v0, w, h):
        self.rect(uc - w / 2, v0, uc + w / 2, v0 + h, w=0.35, fc=DARK, z=self.z + 3)
        self.rect(uc - w / 2 + 0.01, v0 + 0.01, uc + w / 2 - 0.01, v0 + h - 0.01, w=0.1, c="#6a6a6a", z=self.z + 3.1)

    def curtain(self, u0, u1, v0, v1, folds=None, sheer=False):
        n = folds or max(3, int((u1 - u0) / 0.07))
        us = np.linspace(u0, u1, n * 6 + 1)
        amp = (u1 - u0) / n * 0.25
        self.rect(u0, v0, u1, v1, w=0.0, c="none", fc="#f3efe8" if not sheer else "#f8f8f8", z=self.z + 2.5, alpha=0.9)
        for i in range(n + 1):
            u = u0 + i * (u1 - u0) / n
            self.line([u, u + amp * 0.3], [v1, v0], w=0.08 if sheer else 0.12, c="#8c8577", z=self.z + 2.6)
        self.line([u0, u1], [v0, v0], w=0.12, c="#8c8577", z=self.z + 2.6)

    def plant(self, uc, v0, h=0.5, w=0.35):
        rng = np.random.default_rng(int(uc * 1000) % 999)
        for i in range(9):
            a = math.radians(rng.uniform(60, 120))
            L = h * rng.uniform(0.6, 1.0)
            self.ax.plot([uc, uc + math.cos(a) * L * w / h], [v0, v0 + math.sin(a) * L], color="#7c7c7c", lw=lw(0.12),
                         zorder=self.z + 4, clip_on=False)
            self.ax.add_patch(Ellipse((uc + math.cos(a) * L * w / h, v0 + math.sin(a) * L), 0.05, 0.025,
                                      angle=math.degrees(a), fc="white", ec="#7c7c7c", lw=lw(0.1), zorder=self.z + 4.1, clip_on=False))

    def grille(self, u0, u1, v0, v1, n=8):
        self.rect(u0, v0, u1, v1, w=0.2, fc="white", z=self.z + 3)
        for i in range(1, n):
            v = v0 + i * (v1 - v0) / n
            self.line([u0 + 0.01, u1 - 0.01], [v, v], w=0.08, z=self.z + 3.1)

    def hatch_box(self, u0, v0, u1, v1, kind="brick", label=None):
        h = {"brick": "////", "concrete": "..", "insul": "xx", "screed": "....", "board": None, "soil": ".o", "wood": "|||"}[kind]
        fc = {"brick": "#f0d7c8", "concrete": "#d9d9d9", "insul": "#fff6c8", "screed": "#e9e9e9", "board": "white",
              "soil": "#d8cbb8", "wood": WOOD}[kind]
        self.rect(u0, v0, u1, v1, w=0.25, fc=fc, hatch=h, z=self.z + 2)

    # ---------- symbols on walls ----------
    def elec(self, kind, u, v, size=2.4, c=HL):
        from planbase import sym
        sym(self.ax, kind, u, v, c=c, size=size)

    # ---------- dimensions ----------
    def hchain(self, v, us, txt=None, c=HL, size=4.6, above=True, ext_to=None, fmt=cm):
        us = list(us)
        self.line([us[0], us[-1]], [v, v], w=0.13, c=c, z=11)
        t = 0.9 * self.k
        for i, u in enumerate(us):
            self.line([u - t, u + t], [v - t, v + t], w=0.3, c=c, z=11)
            if ext_to is not None:
                e = ext_to[i] if isinstance(ext_to, (list, tuple)) else ext_to
                if e is not None:
                    self.line([u, u], [e, v + (t if v > e else -t)], w=0.08, c=c, z=10.5)
        for i in range(len(us) - 1):
            d = us[i + 1] - us[i]
            s = txt[i] if txt and i < len(txt) and txt[i] is not None else fmt(abs(d))
            if s == "":
                continue
            off = 1.1 * self.k
            narrow = abs(d) < len(s) * size * 0.2 * self.k
            self.text((us[i] + us[i + 1]) / 2, v + (off if above else -off), s, size=size if not narrow else size * 0.85,
                      c=c, va="bottom" if above else "top", bg="white", z=12)

    def vchain(self, u, vs, txt=None, c=HL, size=4.6, left=False, ext_to=None, fmt=cm):
        vs = list(vs)
        self.line([u, u], [vs[0], vs[-1]], w=0.13, c=c, z=11)
        t = 0.9 * self.k
        for i, v in enumerate(vs):
            self.line([u - t, u + t], [v - t, v + t], w=0.3, c=c, z=11)
            if ext_to is not None:
                e = ext_to[i] if isinstance(ext_to, (list, tuple)) else ext_to
                if e is not None:
                    self.line([e, u + (t if u > e else -t)], [v, v], w=0.08, c=c, z=10.5)
        for i in range(len(vs) - 1):
            d = vs[i + 1] - vs[i]
            s = txt[i] if txt and i < len(txt) and txt[i] is not None else fmt(abs(d))
            if s == "":
                continue
            off = 1.1 * self.k
            self.text(u + (-off if left else off), (vs[i] + vs[i + 1]) / 2, s, size=size, c=c, rot=90,
                      ha="center", va="bottom" if not left else "top", bg="white", z=12)

    def level(self, u, v, txt, c=HL, size=4.2, left=False):
        """Level marker: small triangle on a line with text (e.g. '+0.00 FFL')."""
        k = self.k
        self.poly([(u, v), (u - 1.2 * k, v + 1.6 * k), (u + 1.2 * k, v + 1.6 * k)], fc=c, c=c, w=0.1, z=12)
        self.text(u + (1.8 * k if not left else -1.8 * k), v + 1.0 * k, txt, size=size, c=c, ha="left" if not left else "right",
                  va="center", bg="white")

    # ---------- callouts ----------
    def note(self, u, v, txt, key=False):
        self.notes.append((u, v, txt, key))

    def place_notes(self, side="right", at=None, size=4.4, gap=None, vmin=None, vmax=None, wrap_chars=30, dot=True):
        """Lay out collected callouts in a column at u=at, sorted by height, leaders to their points."""
        from sheetlib import wrap
        if not self.notes:
            return
        notes = sorted(self.notes, key=lambda n: -n[1])
        line_h = size * 0.3528 * 1.2 * self.k
        gap = gap if gap is not None else 0.9 * self.k
        items = []
        for u, v, t, key in notes:
            ls = wrap(t, wrap_chars)
            items.append([u, v, ls, key, len(ls) * line_h])
        # initial targets = point heights; push apart top-down
        ys = [it[1] for it in items]
        top = vmax if vmax is not None else max(ys) + 0.2
        for i, it in enumerate(items):
            y = min(it[1] + it[4] / 2, top)
            if i:
                prev = items[i - 1]
                y = min(y, prev[5] - prev[4] - gap)
            it.append(y)   # it[5] = top of text block
            top = y
        # if we fell below vmin, shift everything up
        if vmin is not None and items[-1][5] - items[-1][4] < vmin:
            sh = vmin - (items[-1][5] - items[-1][4])
            for it in items:
                it[5] += sh
        for u, v, ls, key, h, y in items:
            c = HL if key else INK
            ty = y - line_h / 2
            for j, ln in enumerate(ls):
                self.text(at + (0.25 * self.k if side == "right" else -0.25 * self.k), y - line_h * (j + 0.5), ln, size=size, c=c,
                          ha="left" if side == "right" else "right", va="center", weight="bold" if key else "normal", z=13)
            ex = at
            self.line([u, ex - (1.5 * self.k if side == "right" else -1.5 * self.k), ex], [v, ty, ty], w=0.1, c=c, z=12.5)
            if dot:
                self.ax.add_patch(Circle((u, v), 0.35 * self.k, fc=c, ec=c, zorder=12.6, clip_on=False))
        self.notes = []


def title_under(s, ax, x_mm, y_mm, tag, text, sub=None, scale=None):
    """View title: circled tag + bold title + scale, like the R0 heading but smaller."""
    s.page.add_patch(Circle((x_mm + 3, y_mm), 3, fc="white", ec=INK, lw=lw(0.3), zorder=5))
    s.text(x_mm + 3, y_mm, tag, size=5.2, ha="center", weight="bold")
    s.text(x_mm + 7.5, y_mm + 0.6, text, size=6.2, weight="bold")
    if scale or sub:
        s.text(x_mm + 7.5, y_mm - 2.6, " | ".join(t for t in (scale, sub) if t), size=4.4, c=GREY)


def marker(ax, x, y, tag, ang_deg, sheet_ref=None, r_mm=2.6, c=INK):
    """Elevation marker on a plan: circle with a filled pointer facing the view direction (deg, 0 = +x)."""
    k = 1.0 / ax._mm_per_m
    r = r_mm * k
    a = math.radians(ang_deg)
    tip = (x + math.cos(a) * r * 1.8, y + math.sin(a) * r * 1.8)
    l = (x + math.cos(a + 1.15) * r, y + math.sin(a + 1.15) * r)
    rr = (x + math.cos(a - 1.15) * r, y + math.sin(a - 1.15) * r)
    ax.add_patch(MPoly([tip, l, rr], closed=True, fc=c, ec=c, lw=lw(0.2), zorder=20, clip_on=False))
    ax.add_patch(Circle((x, y), r, fc="white", ec=c, lw=lw(0.3), zorder=21, clip_on=False))
    ax.text(x, y + (0.25 * r if sheet_ref else 0), tag, fontsize=5.2, ha="center", va="center", weight="bold", zorder=22,
            color=c)
    if sheet_ref:
        ax.plot([x - r * 0.8, x + r * 0.8], [y - 0.1 * r, y - 0.1 * r], color=c, lw=lw(0.12), zorder=22)
        ax.text(x, y - 0.55 * r, sheet_ref, fontsize=2.9, ha="center", va="center", zorder=22, color=c)


def section_mark(ax, p0, p1, tag, ref=None, look=1, c=HL):
    """Section cut line with end bubbles; look = +1/-1: which side the view looks to (perpendicular)."""
    k = 1.0 / ax._mm_per_m
    (x0, y0), (x1, y1) = p0, p1
    ax.plot([x0, x1], [y0, y1], color=c, lw=lw(0.3), ls=(0, (8, 2, 1, 2)), zorder=19, clip_on=False)
    L = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy * look, ux * look
    for (x, y) in (p0, p1):
        ax.add_patch(Circle((x, y), 2.2 * k, fc="white", ec=c, lw=lw(0.3), zorder=20, clip_on=False))
        ax.text(x, y, tag, fontsize=4.6, ha="center", va="center", weight="bold", color=c, zorder=21)
        ax.annotate("", xy=(x + nx * 4.5 * k, y + ny * 4.5 * k), xytext=(x + nx * 2.2 * k, y + ny * 2.2 * k),
                    arrowprops=dict(arrowstyle="-|>", color=c, lw=lw(0.3), mutation_scale=5), zorder=20)


def markers4(ax, x, y, refs=None, d_mm=6.0, dirs=(("A", 180), ("B", 90), ("C", 0), ("D", -90))):
    """Four elevation markers round one point (A west, B north, C east, D south by default)."""
    refs = refs or {}
    k = 1.0 / ax._mm_per_m
    for tag, ang in dirs:
        a = math.radians(ang)
        marker(ax, x + math.cos(a) * d_mm * k, y + math.sin(a) * d_mm * k, tag, ang, refs.get(tag), r_mm=2.4)
