#!/usr/bin/env python3
"""Build the finishing package (PDF + DXF/DWG) for Karim's apartment from Main (kareems-changes).

    ~/.dwg-tools/bin/python tools/finishing-package/build_package.py --out OUTDIR      # from the repo root
    ~/.dwg-tools/bin/python build_package.py --repo /path/to/karim-home-3d --out OUTDIR  # from anywhere

Needs: node, ezdxf, shapely, matplotlib >= 3.10 (Arabic shaping), pyyaml; ODAFileConverter (+ xvfb-run) for the DWG
(without it the DXF is still written).

Reads Main's model-kareems-changes.js, drawing-kareems-changes.json, electrical-kareems-changes.json,
furnish-kareems-changes.js, design-locks.json and dwg/kareems-changes.dxf, plus package_data.yaml (names, plumbing,
finishes). Every run regenerates every sheet, so a change in Main is one rerun away. Bump `rev` in package_data.yaml.
"""
import argparse
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Polygon as MPoly, Rectangle, Circle, FancyBboxPatch, Arc
from shapely.geometry import Point, LineString, Polygon

from sheetlib import Sheet, HL, INK, GREY, LIGHT, lw, wrap, ar, text_size_mm
from maindata import Main
from planbase import draw_base, Labeller, sym, legend_entry

FULL = ((-0.6, 26.0), (-0.3, 10.4))
WEST = ((-0.35, 14.85), (-0.3, 10.15))
EAST = ((14.55, 25.75), (-0.3, 10.15))
SHEETS = []   # (no, title, paper, scale) for the index

ELEC_SHEETS = {
    "light": ("Electrical - lighting & switch links", {"spot", "pendant", "walllight", "fan", "ledfeed", "lightout"}),
    "switch": ("Electrical - switches & controls", {"switch", "acctl", "sensor"}),
    "power": ("Electrical - sockets & power", {"socket", "power", "wp", "flap", "multi", "db"}),
    "low": ("Electrical - low current (network, TV, intercom)", {"multi", "data", "tv", "phone", "ap", "router", "intercom",
                                                                   "intercom_out", "lcp", "sound", "doorbell", "chime"}),
}
TYPE_NAMES = {
    "spot": "Ceiling spot 6 W (2700 K)", "pendant": "Pendant", "walllight": "Wall light", "fan": "Exhaust fan",
    "ledfeed": "LED driver / accent feed box", "lightout": "Light outlet (no socket)", "switch": "Switch bank",
    "acctl": "AC controller", "sensor": "Presence / motion sensor", "socket": "Socket (single / double)",
    "power": "Dedicated power point", "wp": "Weatherproof socket IP65", "flap": "Furniture flap socket + USB-C",
    "multi": "Combined plate (data/HDMI/TV/sockets)", "db": "Distribution board", "data": "Data Cat6",
    "tv": "TV / antenna point", "phone": "Phone point", "ap": "Wi-Fi access point (PoE)", "router": "Network hub",
    "intercom": "Intercom handset", "intercom_out": "Video doorbell (outside)", "lcp": "Low-current panel",
    "led": "LED strip", "link": "Switch link (key -> circuit)", "water": "Water outlet + valve",
}


class Pkg:
    def __init__(self, main, out):
        self.m = main
        self.out = Path(out)
        md = main.data["meta"]
        self.meta = dict(project=md["project"], client=md["client"], engineer=md["engineer"], rev=md["rev"],
                         date=md["date"], drawn=md["drawn"],
                         source=f"karim-home-3d Main (kareems-changes) @ {main.commit} ({main.commit_date})")
        self.pages = []

    # ---------- helpers ----------
    def new(self, paper, no, title, scale_txt, sub=""):
        s = Sheet(paper, self.meta)
        s.frame()
        s.title_block(no, title, scale_txt, sub)
        SHEETS.append((no, title, paper, scale_txt))
        return s

    def room_name(self, key):
        r = self.m.data["rooms"].get(key, {})
        return r.get("en", key.title()), r.get("ar", "")

    def room_labels(self, ax, lab, size=6.2, dims=True, area=True, arabic=True, dimc=HL):
        rows = []
        for key, poly, kind in self.m.floors:
            en, arn = self.room_name(key)
            info = self.m.data["rooms"].get(key, {})
            pt = info.get("at")
            if pt is None:
                c = poly.representative_point()
                pt = (c.x, c.y)
            a = poly.area
            rows.append((en, arn, a, kind))
            (wx0, wx1), (wy0, wy1) = ax._lim
            if not (wx0 + 0.6 <= pt[0] <= wx1 - 0.6 and wy0 <= pt[1] <= wy1):
                continue
            if dims and not info.get("nodims"):
                k0 = 1 / ax._mm_per_m
                wseg = dseg = None
                for dy in (-7.5, -9.5, 6.5, -5.5, -12):
                    q = (pt[0], pt[1] + dy * k0)
                    if poly.contains(Point(q)):
                        wseg = self.m.clear_dims(poly, q)[0]
                        if wseg is not None:
                            break
                for dx in (14, -14, 18, -18, 10, -10, 22, -22, 6, -6):
                    q = (pt[0] + dx * k0, pt[1])
                    if poly.contains(Point(q)):
                        dseg = self.m.clear_dims(poly, q)[1]
                        if dseg is not None:
                            break
                for seg, horiz in ((wseg, True), (dseg, False)):
                    if seg is None:
                        continue
                    (x0, y0), (x1, y1) = list(seg.coords)[0], list(seg.coords)[-1]
                    self.dim_line(ax, (x0, y0), (x1, y1), f"{seg.length * 100:.0f}", c=dimc, off=0, size=4.6, lab=lab)
            k = 1 / ax._mm_per_m
            ax.text(pt[0], pt[1] + 2.2 * k, en.upper(), fontsize=size, ha="center", va="center", weight="bold", zorder=9,
                    bbox=dict(fc="white", ec="none", pad=0.3))
            if arabic and arn:
                from sheetlib import _AR_FONT
                ax.text(pt[0], pt[1] - 0.6 * k, ar(arn), fontsize=size - 0.6, ha="center", va="center", zorder=9,
                        fontproperties=_AR_FONT, bbox=dict(fc="white", ec="none", pad=0.2))
            if area:
                ax.text(pt[0], pt[1] - 3.4 * k, f"{a:.2f} m²", fontsize=size - 1.4, ha="center", va="center", zorder=9,
                        bbox=dict(fc="white", ec="none", pad=0.2))
            w = text_size_mm(en.upper(), size)[0] * k
            lab.block(pt[0] - w / 2, pt[1] - 4.6 * k, pt[0] + w / 2, pt[1] + 3.6 * k)
        return rows

    def dim_line(self, ax, p0, p1, txt, c=INK, off=0.0, size=4.8, lab=None, ext=False):
        (x0, y0), (x1, y1) = p0, p1
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1e-6:
            return
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        nx, ny = -uy, ux
        a0 = (x0 + nx * off, y0 + ny * off)
        a1 = (x1 + nx * off, y1 + ny * off)
        if ext and off:
            for p, a in ((p0, a0), (p1, a1)):
                ax.plot([p[0] + nx * off * 0.1, a[0] + nx * 0.1 * math.copysign(1, off)],
                        [p[1] + ny * off * 0.1, a[1] + ny * 0.1 * math.copysign(1, off)], color=c, lw=lw(0.1), zorder=6)
        ax.plot([a0[0], a1[0]], [a0[1], a1[1]], color=c, lw=lw(0.13), zorder=6)
        t = 0.9 / ax._mm_per_m
        for a in (a0, a1):  # 45° ticks
            ax.plot([a[0] - (ux + nx) * t, a[0] + (ux + nx) * t], [a[1] - (uy + ny) * t, a[1] + (uy + ny) * t],
                    color=c, lw=lw(0.25), zorder=6)
        ang = math.degrees(math.atan2(uy, ux))
        if ang > 90 or ang <= -90:
            ang += 180
        mx, my = (a0[0] + a1[0]) / 2, (a0[1] + a1[1]) / 2
        k = 1.4 / ax._mm_per_m
        tx, ty = mx + nx * k * (1 if off >= 0 else -1), my + ny * k * (1 if off >= 0 else -1)
        ax.text(tx, ty, txt, fontsize=size, color=c, ha="center", va="center", rotation=ang, rotation_mode="anchor",
                zorder=9, bbox=dict(fc="white", ec="none", pad=0.1))
        if lab is not None:
            w, h = text_size_mm(txt, size)
            w, h = w / ax._mm_per_m, h / ax._mm_per_m
            if abs(ux) > abs(uy):
                lab.block(tx - w / 2, ty - h / 2, tx + w / 2, ty + h / 2)
            else:
                lab.block(tx - h / 2, ty - w / 2, tx + h / 2, ty + w / 2)

    def plan_sheet(self, paper, no, title, scale, window, mode, sub="", plan_y=None):
        s = self.new(paper, no, title, f"1:{scale}", sub)
        (x0, x1), (y0, y1) = window
        wmm = (x1 - x0) * 1000 / scale
        hmm = (y1 - y0) * 1000 / scale
        left = s.m + (s.side_x - s.m - wmm) / 2
        top = s.H - s.m - 14
        py = plan_y if plan_y is not None else top - hmm
        ax, _, _ = s.plan_axes(left, py, window[0], window[1], scale)
        draw_base(ax, self.m, mode)
        s.heading(s.m + 4, s.H - s.m - 7, no.split("-")[0][-3:] if False else no, title.upper())
        s.north(s.side_x - 10, s.H - s.m - 12)
        s.scale_bar(s.side_x - 75 if scale >= 100 else s.side_x - 120, s.m + 8, scale, metres=5, step=1)
        return s, ax, py

    # ---------- sheets ----------
    def cover(self):
        s = Sheet("A3", self.meta)
        s.frame()
        s.title_block("A000", "Cover & sheet index", "-", "")
        SHEETS.insert(0, ("A000", "Cover & sheet index", "A3", "-"))
        self.cover_sheet = s
        return s

    def fill_cover(self):
        s = self.cover_sheet
        md = self.m.data["meta"]
        s.text(s.m + 10, s.H - 38, "AL LOTUS, NEW CAIRO", size=11, c=GREY, weight="bold")
        s.text(s.m + 10, s.H - 52, "FINISHING PACKAGE", size=30, weight="bold")
        s.text(s.m + 10, s.H - 66, "Karim Tamer apartment - Main design (kareems-changes) - for site use", size=12)
        s.text(s.m + 10, s.H - 78, "حزمة التشطيب - شقة كريم تامر - اللوتس، القاهرة الجديدة", size=13, arabic=True)
        s.text(s.m + 10, s.H - 92, f"Revision {md['rev']}  |  {md['date']}  |  Site engineer: {md['engineer']}", size=9)
        s.text(s.m + 10, s.H - 100, f"Source: {self.meta['source']}", size=7, c=GREY)
        # sheet index
        y = s.H - 116
        s.text(s.m + 10, y, "SHEET INDEX", size=9, weight="bold")
        rows = [[no, t, p, sc] for no, t, p, sc in SHEETS]
        s.table(s.m + 10, y - 3, [("No.", 18, "left"), ("Sheet", 120, "left"), ("Paper", 16, "center"), ("Scale", 22, "center")],
                rows, size=5.6, row_h=3.7)
        notes = [
            "All dimensions in centimetres (cm) unless marked m. Plan dimensions are clear (finished-wall to finished-wall in the model); verify on site before any work and report differences before starting.",
            "Print each sheet at 100 % (no 'fit to page') on the paper size in its title block; the scale bar checks the print.",
            "Source of truth: the live 3D model, Main version, https://karim-home-3d.vercel.app/?v=main. This package is regenerated from it; the latest revision supersedes earlier ones.",
            "Demolition and new-wall sheets are not part of this package (issued separately). This package shows the final layout.",
            "Items marked 'TO CONFIRM' are not fixed in the model and must be agreed with Karim before work.",
            "One highlight colour (orange) marks the subject of each sheet and key dimensions; everything prints legibly in black and white.",
            "Electrical heights are from the concrete slab, as given by the designer's electrical plan, until the floor build-up is confirmed.",
        ]
        s.notes(275 - 0, s.H - 116, "GENERAL NOTES", notes, width_chars=40, size=5.6, gap=2.7)
        # key plan
        ax, w, h = s.plan_axes(s.side_x - 132, s.m + 8, FULL[0], FULL[1], 200)
        draw_base(ax, self.m, "arch")
        lab = Labeller(ax)
        for key, poly, kind in self.m.floors:
            en, _ = self.room_name(key)
            pt = self.m.data["rooms"].get(key, {}).get("at") or (poly.representative_point().x, poly.representative_point().y)
            ax.text(pt[0], pt[1], en, fontsize=4.2, ha="center", va="center", zorder=9, bbox=dict(fc="white", ec="none", pad=0.1))
        s.text(s.side_x - 132, s.m + 8 + h + 3, "KEY PLAN 1:200", size=6, weight="bold")

    def layout(self):
        s, ax, py = self.plan_sheet("A3", "A101", "Layout & dimensions", 100, FULL, "arch",
                                    "Room names, areas, clear room dims, openings")
        lab = Labeller(ax)
        rows = self.room_labels(ax, lab)
        # overall dimensions from the wall outline
        from shapely.ops import unary_union
        U = unary_union(self.m.walls)
        bx0, by0, bx1, by1 = U.bounds
        self.dim_line(ax, (bx0, by1), (bx1, by1), f"{(bx1 - bx0) * 100:.0f}", off=0.55, size=5.2, ext=True)
        self.dim_line(ax, (bx0, by0), (bx0, by1), f"{(by1 - by0) * 100:.0f}", off=0.45, size=5.2, ext=True)
        # openings tags
        ops = self.m.openings()
        k = 1 / ax._mm_per_m
        for o in ops:
            tag = o["tag"]
            p = o["poly"]
            b = p.bounds
            horiz = (b[2] - b[0]) > (b[3] - b[1])
            if o["kind"] == "door":
                ax.add_patch(Rectangle((o["x"] - 2.6 * k, o["y"] - 1.4 * k), 5.2 * k, 2.8 * k, fc="white", ec=INK, lw=lw(0.15), zorder=9))
            else:
                ax.add_patch(Circle((o["x"], o["y"]), 1.8 * k, fc="white", ec=INK, lw=lw(0.15), zorder=9))
            ax.text(o["x"], o["y"], tag, fontsize=3.8, ha="center", va="center", zorder=10, weight="bold")
            lab.block(o["x"] - 2.6 * k, o["y"] - 1.6 * k, o["x"] + 2.6 * k, o["y"] + 1.6 * k)
        # side panel: area schedule + openings schedule
        x = s.side_x + 2
        y = s.H - s.m - 4
        s.text(x, y, "ROOM AREAS (net floor, model)", size=6, weight="bold")
        rr = []
        tot = 0
        for en, arn, a, kind in rows:
            rr.append([en, kind, f"{a:.2f}"])
            if kind != "outdoor":
                tot += a
        rr.append(["Total indoor", "", f"{tot:.2f}"])
        y = s.table(x, y - 2.5, [("Room", 40, "left"), ("Type", 14, "center"), ("m²", 22, "center")], rr, size=4.8, row_h=3.0,
                    hl_rows=(len(rr) - 1,))
        y -= 4
        s.text(x, y, "OPENINGS (model; heights from finished floor)", size=6, weight="bold")
        orow = []
        for o in ops:
            leaf = f" leaf {o['leaf'] * 100:.0f}" if o.get("leaf") else ""
            extra = " frosted" if o.get("frosted") else ""
            orow.append([o["tag"], o["kind"] + extra, f"{o['w'] * 100:.0f}{leaf}", f"{o['sill'] * 100:.0f}", f"{o['head'] * 100:.0f}"])
        y = s.table(x, y - 2.5, [("Tag", 9, "left"), ("Type", 19, "left"), ("Width", 22, "center"), ("Sill", 12, "center"),
                                 ("Head", 14, "center")], orow, size=4.5, row_h=2.8)
        y -= 3
        s.notes(x, y, "NOTES", [
            "Orange dimensions: clear room width / depth through the room label (cm).",
            "Door width = opening in the wall; leaf from the swing radius.",
            f"Ceiling {self.m.ceiling:.2f} m; door head {self.m.model['doorHead']:.2f} m.",
        ], width_chars=46, size=4.6, gap=2.2)
        return s

    def furniture(self):
        s, ax, py = self.plan_sheet("A3", "A102", "Furniture layout & measurements", 100, FULL, "furn",
                                    "Fixed joinery and loose furniture with sizes (W x D cm)")
        lab = Labeller(ax)
        self.room_labels(ax, lab, size=5.0, dims=False, area=False, arabic=False)
        closed = []
        for st in self.m.strokes("#00ff00"):
            if len(st) >= 8 and abs(st[0] - st[-2]) < 1e-3 and abs(st[1] - st[-1]) < 1e-3:
                xs, ys = st[0::2], st[1::2]
                closed.append((min(xs), min(ys), max(xs), max(ys)))
        rows = []
        for i, f in enumerate(self.m.data["furniture"], 1):
            x, y = f["at"]
            cands = [b for b in closed if b[0] - 0.01 <= x <= b[2] + 0.01 and b[1] - 0.01 <= y <= b[3] + 0.01]
            size = f.get("size")
            if not size and cands:
                b = min(cands, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                size = f"{(b[2] - b[0]) * 100:.0f} x {(b[3] - b[1]) * 100:.0f}"
            size = size or "-"
            tag = f"F{i:02d}"
            k = 1 / ax._mm_per_m
            ax.add_patch(Circle((x, y), 1.7 * k, fc=HL, ec="none", zorder=9))
            ax.text(x, y, f"{i}", fontsize=3.8, ha="center", va="center", color="white", weight="bold", zorder=10)
            lab.block(x - 1.8 * k, y - 1.8 * k, x + 1.8 * k, y + 1.8 * k)
            rows.append([f"{i}", f["name"], size])
        x = s.side_x + 2
        y = s.H - s.m - 4
        s.text(x, y, "FURNITURE & JOINERY (W x D cm, plan)", size=6, weight="bold")
        y = s.table(x, y - 2.5, [("#", 6, "center"), ("Item", 50, "left"), ("Size", 22, "center")], rows, size=4.5, row_h=2.75)
        s.notes(x, y - 3, "NOTES", [
            "Sizes are the plan outline in the Main drawing (x by y, not width by depth when rotated).",
            "Joinery heights: see the elevation sheets D501-D604.",
            "Loose furniture is for clearance only; fixed joinery dimensions to be confirmed with the joinery shop drawings.",
        ], width_chars=46, size=4.5, gap=2.2)
        return s


def main():
    ap = argparse.ArgumentParser()
    here_repo = HERE.parents[1] if (HERE.parents[1] / "furnish-kareems-changes.js").exists() else None
    ap.add_argument("--repo", default=str(here_repo) if here_repo else None, required=here_repo is None,
                    help="karim-home-3d checkout (default: the repo this folder sits in)")
    ap.add_argument("--out", default="package-out", help="output folder (PDF, DXF, DWG, sheet index)")
    ap.add_argument("--data", default=str(HERE / "package_data.yaml"))
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    m = Main(a.repo, a.data)
    P = Pkg(m, a.out)
    import sheets_more  # noqa: the electrical, plumbing, ceiling, detail and spec sheets
    sheets_more.build_all(P, a)


if __name__ == "__main__":
    main()
