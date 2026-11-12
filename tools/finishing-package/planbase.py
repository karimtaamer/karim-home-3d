"""Plan linework and symbols drawn into a plan axes (plan metres)."""
import math
from matplotlib.patches import Polygon as MPoly, Circle, Rectangle, Wedge, Arc
from matplotlib.collections import LineCollection
from sheetlib import lw, INK, GREY, LIGHT, HL, text_size_mm, ar, _AR_FONT

WALL_FILL = {"arch": "#2b2b2b", "mep": "#a6a6a6", "furn": "#555555"}


def _segs(strokes):
    segs = []
    for s in strokes:
        pts = list(zip(s[0::2], s[1::2]))
        segs.extend(zip(pts[:-1], pts[1:]))
    return segs


def draw_base(ax, main, mode="arch"):
    """mode: arch (layout), furn (furniture black), mep (walls grey, furniture faint)."""
    fill = WALL_FILL[mode]
    for p in main.walls:
        for g in (p.geoms if hasattr(p, "geoms") else [p]):
            ax.add_patch(MPoly(list(g.exterior.coords), closed=True, fc=fill, ec="none", zorder=2))
    wall_c = INK if mode != "mep" else "#555555"
    ax.add_collection(LineCollection(_segs(main.strokes("#ff0000")), colors=wall_c, linewidths=lw(0.25 if mode != "mep" else 0.18), zorder=3))
    ax.add_collection(LineCollection(_segs(main.strokes("#007ca5")), colors=wall_c, linewidths=lw(0.13), zorder=3))
    ax.add_collection(LineCollection(_segs(main.strokes("#7f3f3f")), colors=wall_c, linewidths=lw(0.13), zorder=3))
    ax.add_collection(LineCollection(_segs(main.strokes("#0000ff")), colors=wall_c, linewidths=lw(0.1), zorder=3))
    ax.add_collection(LineCollection(_segs(main.strokes("#00ffff")), colors=wall_c, linewidths=lw(0.1), zorder=3))
    fc = {"arch": "#9a9a9a", "furn": INK, "mep": "#cfcfcf"}[mode]
    fw = {"arch": 0.1, "furn": 0.14, "mep": 0.08}[mode]
    ax.add_collection(LineCollection(_segs(main.strokes("#00ff00")) + _segs(main.strokes("#808080")), colors=fc,
                                     linewidths=lw(fw), zorder=2.5))
    # openings: window glass lines already in the DXF; fill wall gaps white so openings read
    for o in main.model["openings"]:
        pts = o["outer"]
        ax.add_patch(MPoly(pts, closed=True, fc="white", ec="none", zorder=2.2))


class Labeller:
    """Places plan text without overlaps (estimated boxes in plan metres)."""

    def __init__(self, ax):
        self.ax = ax
        self.k = 1.0 / ax._mm_per_m  # metres per mm
        self.boxes = []

    def free(self, b):
        for q in self.boxes:
            if b[0] < q[2] and b[2] > q[0] and b[1] < q[3] and b[3] > q[1]:
                return False
        (x0, x1), (y0, y1) = self.ax._lim
        return b[0] >= x0 and b[2] <= x1 and b[1] >= y0 and b[3] <= y1

    def block(self, x0, y0, x1, y1):
        self.boxes.append((x0, y0, x1, y1))

    def put(self, x, y, s, size=4.5, c=INK, offsets=None, weight="normal", force=False, leader=True, bg="white"):
        wmm, hmm = text_size_mm(s, size)
        w, h = wmm * self.k, hmm * self.k
        r = 2.2 * self.k
        offsets = offsets or [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1), (2, 0), (-2, 0),
                              (0, 2), (0, -2), (2, 2), (-2, -2), (2, -2), (-2, 2), (3, 0), (-3, 0), (0, 3), (0, -3)]
        for dx, dy in offsets:
            cx = x + dx * (r + w / 2 if dx else 0) + (math.copysign(w / 2, dx) * (abs(dx) - 1) if abs(dx) > 1 else 0)
            cy = y + dy * (r + h / 2 if dy else 0) + (math.copysign(h / 2, dy) * (abs(dy) - 1) if abs(dy) > 1 else 0)
            b = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if self.free(b):
                break
        else:
            if not force:
                cx, cy = x + r + w / 2, y
                b = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        self.boxes.append(b)
        self.ax.text(cx, cy, s, fontsize=size, color=c, ha="center", va="center", zorder=8, weight=weight,
                     bbox=dict(fc=bg, ec="none", pad=0.15, alpha=0.85) if bg else None)
        if leader and math.hypot(cx - x, cy - y) > r * 1.6:
            # leader to the nearest box edge
            ex = min(max(x, b[0]), b[2])
            ey = min(max(y, b[1]), b[3])
            self.ax.plot([x, ex], [y, ey], color=c, lw=lw(0.08), zorder=7)
        return b


# ---------- electrical symbols (size in mm on paper) ----------
def sym(ax, kind, x, y, c=INK, size=2.6, facing=None, txt=None):
    k = size / ax._mm_per_m / 2.0  # radius in metres
    z = 9
    L = lw(0.18)

    def circ(r=k, fc="white"):
        ax.add_patch(Circle((x, y), r, fc=fc, ec=c, lw=L, zorder=z))

    def letters(t, s=3.4):
        ax.text(x, y, t, fontsize=s, ha="center", va="center", color=c, zorder=z + 1, weight="bold")

    if kind == "spot":
        circ(k * 0.8)
        d = k * 0.8 * 0.7
        ax.plot([x - d, x + d], [y - d, y + d], color=c, lw=L, zorder=z + 1)
        ax.plot([x - d, x + d], [y + d, y - d], color=c, lw=L, zorder=z + 1)
    elif kind == "pendant":
        circ(k, fc="white"); ax.add_patch(Circle((x, y), k * 0.5, fc=c, ec=c, lw=L, zorder=z + 1))
    elif kind == "walllight":
        ax.add_patch(Wedge((x, y), k, 0, 360, width=k * 0.45, fc=c, ec=c, lw=L, zorder=z))
    elif kind == "fan":
        circ(); letters("F")
    elif kind == "sensor":
        ax.add_patch(MPoly([(x, y + k), (x + k, y - k * 0.8), (x - k, y - k * 0.8)], closed=True, fc="white", ec=c, lw=L, zorder=z))
        letters("S", 3.0)
    elif kind == "ledfeed":
        ax.add_patch(Rectangle((x - k * 0.75, y - k * 0.75), 1.5 * k, 1.5 * k, fc="white", ec=c, lw=L, zorder=z)); letters("L", 3.2)
    elif kind == "lightout":
        circ(); d = k * 0.7
        ax.plot([x - d, x + d], [y - d, y + d], color=c, lw=L, zorder=z + 1); ax.plot([x - d, x + d], [y + d, y - d], color=c, lw=L, zorder=z + 1)
        ax.add_patch(Circle((x, y), k * 0.3, fc=c, ec=c, zorder=z + 2))
    elif kind == "switch":
        circ(k * 0.85, fc=c); ax.plot([x, x + k * 1.3], [y, y + k * 1.3], color=c, lw=L, zorder=z)
    elif kind == "acctl":
        ax.add_patch(Rectangle((x - k, y - k * 0.7), 2 * k, 1.4 * k, fc="white", ec=c, lw=L, zorder=z)); letters("AC", 2.6)
    elif kind in ("socket", "wp", "flap"):
        circ(k * 0.85, fc="white")
        ax.add_patch(Wedge((x, y), k * 0.85, 180, 360, fc=c, ec=c, lw=L, zorder=z + 1))
        if kind == "wp":
            ax.add_patch(Rectangle((x - k * 1.2, y - k * 1.2), 2.4 * k, 2.4 * k, fc="none", ec=c, lw=L, zorder=z))
        if kind == "flap":
            ax.add_patch(Rectangle((x - k * 1.2, y - k * 1.2), 2.4 * k, 2.4 * k, fc="none", ec=c, lw=L, ls=(0, (2, 1)), zorder=z))
    elif kind == "power":
        ax.add_patch(Rectangle((x - k * 0.85, y - k * 0.85), 1.7 * k, 1.7 * k, fc="white", ec=c, lw=L, zorder=z))
        ax.add_patch(MPoly([(x - k * 0.85, y - k * 0.85), (x + k * 0.85, y - k * 0.85), (x + k * 0.85, y + k * 0.85)],
                           closed=True, fc=c, ec=c, lw=L, zorder=z + 1))
    elif kind == "water":
        circ(); letters("W", 3.2)
    elif kind in ("multi", "data", "tv", "phone"):
        ax.add_patch(MPoly([(x - k, y - k * 0.85), (x + k, y - k * 0.85), (x, y + k)], closed=True, fc="white", ec=c, lw=L, zorder=z))
        letters({"multi": "M", "data": "D", "tv": "TV", "phone": "T"}[kind], 2.6)
    elif kind in ("db", "router", "lcp"):
        ax.add_patch(Rectangle((x - k * 1.4, y - k * 0.8), 2.8 * k, 1.6 * k, fc="#d9d9d9", ec=c, lw=L, zorder=z, hatch="////"))
        letters({"db": "DB", "router": "HUB", "lcp": "LCP"}[kind], 2.6)
    elif kind == "ap":
        circ(); letters("AP", 2.6)
    elif kind in ("intercom", "intercom_out", "doorbell", "chime", "sound"):
        ax.add_patch(Rectangle((x - k * 0.85, y - k * 0.85), 1.7 * k, 1.7 * k, fc="white", ec=c, lw=L, zorder=z))
        letters({"intercom": "IC", "intercom_out": "VD", "doorbell": "DB", "chime": "CH", "sound": "SN"}[kind], 2.5)
    elif kind == "plumb":
        ax.add_patch(Circle((x, y), k, fc="white", ec=c, lw=lw(0.25), zorder=z))
        ax.add_patch(Circle((x, y), k * 0.45, fc=c, ec=c, zorder=z + 1))
    elif kind == "plumb_tbc":
        ax.add_patch(Circle((x, y), k, fc="white", ec=c, lw=lw(0.25), ls=(0, (2, 1)), zorder=z))
        letters("?", 3.4)
    else:
        circ(); letters("?")
    return k


def legend_entry(sheet, x, y, kind, label, c=INK):
    """Draw a legend symbol on the page (mm) via a tiny axes in metres-equivalent."""
    ax = sheet.fig.add_axes([(x - 3) / sheet.W, (y - 3) / sheet.H, 6 / sheet.W, 6 / sheet.H])
    ax.set_xlim(-3, 3); ax.set_ylim(-3, 3); ax.set_aspect("equal"); ax.axis("off")
    ax._mm_per_m = 1.0
    if kind == "led":
        ax.plot([-2.6, 2.6], [0, 0], color=c, lw=lw(0.5), ls=(0, (3, 1.5)))
    elif kind == "link":
        ax.plot([-2.6, 2.6], [0, 0], color=c, lw=lw(0.15), ls=(0, (4, 2)))
    else:
        sym(ax, kind, 0, 0, c=c, size=2.8)
    sheet.text(x + 4.5, y, label, size=4.8)
