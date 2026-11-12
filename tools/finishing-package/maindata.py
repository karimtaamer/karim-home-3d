"""Load Main (plan version kareems-changes) from a karim-home-3d checkout: model, 2D drawing, electrical,
furniture boxes, design locks, curtain pockets, commit. Everything the sheets draw comes from here or from
package_data.yaml (the facts Main's files don't hold: names, plumbing points, finishes)."""
import json
import re
import subprocess
from pathlib import Path

import yaml
from shapely.geometry import Polygon, LineString, Point

VERSION = "kareems-changes"


class Main:
    def __init__(self, repo, data_yaml):
        self.repo = Path(repo)
        r = self.repo
        mp = str(r / f"model-{VERSION}.js")
        out = subprocess.run(["node", "-e", "global.window={};require(process.argv[1]);process.stdout.write(JSON.stringify(window.MODEL))", mp],
                             capture_output=True, text=True, check=True, timeout=60)
        self.model = json.loads(out.stdout)
        self.origin = tuple(self.model["origin"])
        self.drawing = json.loads((r / f"drawing-{VERSION}.json").read_text())
        self.elec = json.loads((r / f"electrical-{VERSION}.json").read_text())
        self.locks = {l["id"]: l for l in json.loads((r / "design-locks.json").read_text())["locks"]}
        self.furnish_src = (r / f"furnish-{VERSION}.js").read_text()
        self.data = yaml.safe_load(Path(data_yaml).read_text())
        try:
            self.commit = subprocess.run(["git", "-C", str(r), "rev-parse", "--short", "HEAD"], capture_output=True,
                                         text=True).stdout.strip()
            self.commit_date = subprocess.run(["git", "-C", str(r), "log", "-1", "--format=%cd", "--date=format:%d %b %Y %H:%M"],
                                              capture_output=True, text=True).stdout.strip()
        except Exception:
            self.commit, self.commit_date = "?", ""
        self.ceiling = self.model["ceiling"]
        self._boxes = None

    # ---- geometry ----
    @property
    def walls(self):
        return [Polygon(w["outer"], w.get("holes") or []) for w in self.model["walls"]]

    @property
    def floors(self):
        return [(f["room"], Polygon(f["outer"], f.get("holes") or []), f["kind"]) for f in self.model["floor"]]

    def strokes(self, colour):
        return self.drawing["strokes"].get(colour, [])

    def openings(self):
        """Doors and windows with tags, width and sill/head (model defaults where the opening has none)."""
        M = self.model
        out = []
        nd = nw = 0
        ops = sorted(M["openings"], key=lambda o: (o["kind"] == "door", Polygon(o["outer"]).centroid.x))
        for o in ops:
            p = Polygon(o["outer"])
            minx, miny, maxx, maxy = p.bounds
            w = max(maxx - minx, maxy - miny)
            c = p.centroid
            if o["kind"] == "door":
                nd += 1
                tag = f"D{nd:02d}"
                sill, head = 0.0, M["doorHead"]
                leaf = None
                for s in M["swings"]:
                    if Point(s["hinge"]).distance(p) < 0.15:
                        leaf = s["r"]
                out.append(dict(tag=tag, kind="door", x=c.x, y=c.y, w=w, sill=sill, head=head, leaf=leaf, poly=p))
            else:
                nw += 1
                tag = f"W{nw:02d}"
                sill = o.get("sill", M["sill"] if o["kind"] == "window" else 0.0)
                head = o.get("head", M["winHead"] if o["kind"] == "window" else M["sliderHead"])
                out.append(dict(tag=tag, kind=o["kind"], x=c.x, y=c.y, w=w, sill=sill, head=head,
                                frosted=o.get("frosted", False), poly=p))
        return out

    # ---- furniture boxes from furnish.js ----
    def boxes(self):
        if self._boxes is None:
            from furnish_boxes import boxes
            try:
                self._boxes = boxes(self.repo, VERSION)
            except Exception as e:  # the package still builds without them
                print("WARN furnish boxes:", e)
                self._boxes = []
        return self._boxes

    def acs(self):
        """Wall-mounted split ACs: the furnish ac() bodies (applianceWhite boxes high on a wall, >= 0.6 wide)."""
        out = []
        for b in self.boxes():
            m, x0, x1, y0, y1, h0, h1 = b[:7]
            if m == "applianceWhite" and h1 > 2.3 and max(x1 - x0, y1 - y0) >= 0.6 and h0 > 1.9:
                out.append(dict(x0=x0, x1=x1, y0=y0, y1=y1, h0=h0, h1=h1))
        return out

    def pockets(self):
        """Curtain pockets from furnish.js `const pockets = [...]` rect [x0, y0, x1, y1] and depth."""
        m = re.search(r"const pockets = \[(.*?)\n  \];", self.furnish_src, re.S)
        out = []
        if not m:
            return out
        for r in re.finditer(r"rect: \[([^\]]+)\][^\n]*?depth: ([A-Z0-9.]+)", m.group(1)):
            x0, y0, x1, y1 = [float(v) for v in r.group(1).split(",")]
            d = r.group(2)
            out.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, depth=0.15 if d == "POCKET" else float(d)))
        return out

    # ---- helpers ----
    def to_dwg(self, x, y):
        return x + self.origin[0], y + self.origin[1]

    def clear_dims(self, poly, pt):
        """Clear width (x) and depth (y) of a room polygon through a point."""
        res = []
        for dx, dy in ((1, 0), (0, 1)):
            ln = LineString([(pt[0] - dx * 40, pt[1] - dy * 40), (pt[0] + dx * 40, pt[1] + dy * 40)])
            inter = ln.intersection(poly)
            segs = list(inter.geoms) if hasattr(inter, "geoms") else [inter]
            best = None
            for s in segs:
                if s.length and s.distance(Point(pt)) < 1e-6:
                    best = s
            res.append(best)
        return res
