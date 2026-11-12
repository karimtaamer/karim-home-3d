"""Sheet engine for the finishing package: pages in paper millimetres, plans in plan metres at an exact scale.

Every page is a matplotlib figure the size of the paper. `Sheet.page` is an axes in millimetres (frame, title block,
tables, notes). `Sheet.plan_axes()` adds an axes in plan metres placed so 1 m = 1000/scale mm on paper, so a plan
printed at 100 % measures true to scale. Black linework on white plus one highlight colour (HL).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon as MPoly, Circle, Wedge, FancyBboxPatch
from matplotlib import font_manager
from pathlib import Path

HL = "#e8590c"            # the one highlight colour
INK = "#000000"
GREY = "#8c8c8c"
LIGHT = "#c8c8c8"
PT_MM = 0.3528            # 1 pt in mm
PAPER = {"A3": (420.0, 297.0), "A4": (297.0, 210.0)}

plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["hatch.linewidth"] = 0.3

_AR_FONT = None
for cand in ["/workspace/NotoNaskhArabic-Regular.ttf", "/workspace/NotoSansArabic-Regular.ttf"]:
    if Path(cand).exists():
        _AR_FONT = font_manager.FontProperties(fname=cand)
        break


def ar(s):
    """Arabic text shaped and ordered for matplotlib (which draws left to right, unshaped)."""
    if tuple(int(v) for v in matplotlib.__version__.split(".")[:2]) >= (3, 10):
        return s  # matplotlib shapes and orders Arabic itself (libraqm layout)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(s))
    except Exception:
        return s


def lw(mm):
    return mm / PT_MM


def text_size_mm(s, size):
    lines = str(s).split("\n")
    return max(len(x) for x in lines) * 0.56 * size * PT_MM, len(lines) * 1.25 * size * PT_MM


def wrap(s, n):
    out, line = [], ""
    for w in str(s).split():
        if len(line) + len(w) + 1 > n and line:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out or [""]


class Sheet:
    def __init__(self, paper="A3", meta=None):
        self.paper = paper
        self.W, self.H = PAPER[paper]
        self.fig = plt.figure(figsize=(self.W / 25.4, self.H / 25.4))
        self.page = self.fig.add_axes([0, 0, 1, 1])
        self.page.set_xlim(0, self.W)
        self.page.set_ylim(0, self.H)
        self.page.axis("off")
        self.meta = meta or {}
        self.side_w = 82.0 if paper == "A3" else 64.0
        self.m = 10.0
        self.side_x = self.W - self.m - self.side_w
        self.tb_h = 76.0 if paper == "A3" else 84.0
        self.placed = []  # text boxes in page mm, for collision avoidance

    # ---------- primitives in page mm ----------
    def line(self, pts, w=0.25, c=INK, ls="-", z=3, ax=None):
        ax = ax or self.page
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=c, lw=lw(w), ls=ls, solid_capstyle="butt", zorder=z)

    def rect(self, x0, y0, x1, y1, w=0.25, c=INK, fc="none", z=2, ax=None, ls="-"):
        (ax or self.page).add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, lw=lw(w), ec=c, fc=fc, zorder=z, ls=ls))

    def text(self, x, y, s, size=6, c=INK, ha="left", va="center", weight="normal", rot=0, z=6, ax=None, arabic=False,
             bg=None, style="normal"):
        kw = dict(fontsize=size, color=c, ha=ha, va=va, weight=weight, rotation=rot, zorder=z, style=style,
                  rotation_mode="anchor")
        if arabic and _AR_FONT is not None:
            kw["fontproperties"] = _AR_FONT
            kw.pop("weight")
            kw["fontsize"] = size
            s = ar(s)
        if bg:
            kw["bbox"] = dict(fc=bg, ec="none", pad=0.6)
        return (ax or self.page).text(x, y, s, **kw)

    # ---------- frame and title block ----------
    def frame(self):
        m = self.m
        self.rect(m, m, self.W - m, self.H - m, w=0.5)
        self.line([(self.side_x, m), (self.side_x, self.H - m)], w=0.35)
        self.line([(self.side_x, m + self.tb_h), (self.W - m, m + self.tb_h)], w=0.35)

    def title_block(self, sheet_no, sheet_name, scale_txt, sub=""):
        md = self.meta
        x0, x1 = self.side_x, self.W - self.m
        A3 = self.paper == "A3"
        nchar = 46 if A3 else 34
        grid = self.m + 21
        tz = grid + (21 if A3 else 23)          # top of the title zone
        # project rows, top down
        cy = self.m + self.tb_h - 3.0
        for k, v in (("PROJECT", md.get("project", "")), ("CLIENT", md.get("client", "")),
                     ("SITE ENGINEER", md.get("engineer", "")), ("SOURCE", md.get("source", ""))):
            self.text(x0 + 1.5, cy, k, size=4.0, c=GREY)
            ls = wrap(v, nchar)
            for i, ln in enumerate(ls):
                self.text(x0 + 1.5, cy - 2.4 - i * 2.2, ln, size=4.8)
            cy -= 2.4 + 2.2 * len(ls) + 1.0
        self.line([(x0, tz), (x1, tz)], w=0.2)
        self.text(x0 + 1.5, tz - 2.2, "SHEET TITLE", size=4.0, c=GREY)
        nl = wrap(sheet_name, 30 if A3 else 25)[:2]
        for i, ln in enumerate(nl):
            self.text(x0 + 1.5, tz - 5.6 - i * 3.4, ln, size=7.2, weight="bold")
        yy = tz - 5.6 - 3.4 * len(nl) - 0.6
        for ln in wrap(sub, 58 if A3 else 44)[:2]:
            self.text(x0 + 1.5, yy, ln, size=4.4)
            yy -= 2.2
        gy0 = self.m
        self.line([(x0, grid), (x1, grid)], w=0.2)
        cols = [x0, x0 + (x1 - x0) * 0.32, x0 + (x1 - x0) * 0.62, x1]
        fields_top = [("SCALE", scale_txt), ("DATE", md.get("date", "")), ("REVISION", md.get("rev", ""))]
        fields_bot = [("PAPER", f"{self.paper} landscape" if self.paper == "A3" else "A4 land."), ("DRAWN", md.get("drawn", "")), ("SHEET No.", sheet_no)]
        for row, fy in ((fields_top, gy0 + 10.5), (fields_bot, gy0)):
            self.line([(x0, fy + 10.5), (x1, fy + 10.5)], w=0.2)
            for i, (k, v) in enumerate(row):
                self.line([(cols[i], fy), (cols[i], fy + 10.5)], w=0.2)
                self.text(cols[i] + 1.2, fy + 8.4, k, size=4.0, c=GREY)
                big = k == "SHEET No."
                vv = v if big or len(v) < 16 else v[:15]
                self.text(cols[i] + 1.2, fy + 3.6, vv, size=(9 if A3 else 7.5) if big else (5.2 if A3 else 4.4),
                          weight="bold" if big else "normal", c=HL if big else INK)

    # ---------- plan axes ----------
    def plan_axes(self, x_mm, y_mm, xlim, ylim, scale):
        w = (xlim[1] - xlim[0]) * 1000.0 / scale
        h = (ylim[1] - ylim[0]) * 1000.0 / scale
        ax = self.fig.add_axes([x_mm / self.W, y_mm / self.H, w / self.W, h / self.H])
        ax.set_xlim(*xlim)
        ax.set_ylim(*ylim)
        ax.set_aspect("equal")
        ax.axis("off")
        ax._mm_per_m = 1000.0 / scale
        ax._origin_mm = (x_mm, y_mm)
        ax._lim = (xlim, ylim)
        return ax, w, h

    def to_page(self, ax, x, y):
        (x0, _), (y0, _) = ax._lim
        return ax._origin_mm[0] + (x - x0) * ax._mm_per_m, ax._origin_mm[1] + (y - y0) * ax._mm_per_m

    def scale_bar(self, x, y, scale, metres=5, step=1, label=None):
        mm = 1000.0 / scale
        n = int(metres / step)
        for i in range(n):
            fc = INK if i % 2 == 0 else "white"
            self.rect(x + i * step * mm, y, x + (i + 1) * step * mm, y + 1.6, w=0.2, fc=fc)
        for i in range(n + 1):
            v = i * step
            self.text(x + i * step * mm, y - 2.2, f"{v:g}", size=4.8, ha="center")
        self.text(x + n * step * mm + 2, y - 2.2, "m", size=4.8)
        self.text(x, y + 4.0, label or f"SCALE 1:{scale} (on {self.paper})", size=5.5, weight="bold")

    def north(self, x, y, r=5):
        self.page.add_patch(MPoly([(x, y + r), (x - r * 0.45, y - r * 0.7), (x, y - r * 0.3)], closed=True, fc=INK,
                                  ec=INK, lw=lw(0.2), zorder=5))
        self.page.add_patch(MPoly([(x, y + r), (x + r * 0.45, y - r * 0.7), (x, y - r * 0.3)], closed=True, fc="white",
                                  ec=INK, lw=lw(0.2), zorder=5))
        self.text(x, y + r + 2.4, "N", size=7, ha="center", weight="bold")
        self.text(x, y - r - 2.2, "plan north (+Y)", size=4.0, ha="center", c=GREY)

    def heading(self, x, y, tag, title, sub=None):
        self.page.add_patch(Circle((x + 4, y), 4, fc="white", ec=INK, lw=lw(0.35), zorder=5))
        self.text(x + 4, y, tag, size=6.5, ha="center", weight="bold")
        self.text(x + 10, y + 0.8, title, size=9, weight="bold")
        if sub:
            self.text(x + 10, y - 3.4, sub, size=5.2, c=INK)

    def table(self, x, y, cols, rows, size=5.0, row_h=3.4, head=True, hl_rows=()):
        """cols: [(title, width_mm, align)]; rows: list of lists. Draws downward from y (top). Returns bottom y."""
        cy = y
        tot = sum(c[1] for c in cols)
        if head:
            self.rect(x, cy - row_h, x + tot, cy, w=0.25, fc="#e6e6e6")
            cx = x
            for t, w, a in cols:
                self.text(cx + 0.8 if a == "left" else cx + w / 2, cy - row_h / 2, t, size=size, weight="bold",
                          ha="left" if a == "left" else "center")
                cx += w
            cy -= row_h
        for ri, r in enumerate(rows):
            self.rect(x, cy - row_h, x + tot, cy, w=0.12)
            cx = x
            for (t, w, a), v in zip(cols, r):
                col = HL if ri in hl_rows else INK
                self.text(cx + 0.8 if a == "left" else cx + w / 2, cy - row_h / 2, v, size=size, c=col,
                          ha="left" if a == "left" else "center")
                cx += w
            cy -= row_h
        return cy

    def notes(self, x, y, title, items, width_chars=52, size=5.0, gap=2.35):
        if title:
            self.text(x, y, title, size=5.8, weight="bold")
            y -= 3.6
        for i, n in enumerate(items, 1):
            ls = wrap(n, width_chars)
            self.text(x, y, f"{i}.", size=size)
            for k, ln in enumerate(ls):
                self.text(x + 3.2, y - k * gap, ln, size=size)
            y -= gap * len(ls) + 0.8
        return y

    def save(self, pdf):
        pdf.savefig(self.fig)
        plt.close(self.fig)
