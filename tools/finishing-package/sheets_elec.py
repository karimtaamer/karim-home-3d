"""Electrical sheets: lighting (with switch links), switches & controls, sockets & power, low current, schedule."""
import collections
import math
from matplotlib.patches import Circle, Rectangle
from sheetlib import HL, INK, GREY, lw, wrap, text_size_mm
from planbase import sym, Labeller, legend_entry
import build_package as B


def short_h(h):
    return f"{h * 100:.0f}"


def prep(P):
    E = P.m.elec
    pts = E["points"]
    # switch tags west -> east, stacked boxes share a number with a/b
    sw = sorted([p for p in pts if p["type"] == "switch"], key=lambda p: (round(p["x"], 1), -p["y"], -p["h"]))
    tags = {}
    n = 0
    seen = {}
    for p in sw:
        key = (round(p["x"], 3), round(p["y"], 3))
        if key in seen:
            tags[p["id"]] = seen[key] + "b"
            tags[seen[key + ("id",)]] = seen[key] + "a"
        else:
            n += 1
            seen[key] = f"S{n:02d}"
            seen[key + ("id",)] = p["id"]
            tags[p["id"]] = f"S{n:02d}"
    # circuits
    circ = collections.OrderedDict()
    for p in sorted(pts, key=lambda p: p["x"]):
        c = p.get("circuit")
        if c:
            circ.setdefault(c, []).append(("pt", p))
    for l in E["lines"]:
        circ.setdefault(l["circuit"], []).append(("line", l))
    codes = {c: f"C{i:02d}" for i, c in enumerate(circ, 1)}
    # switch -> circuits (Main data first, then package_data inference)
    links = {}
    inferred = set()
    for p in sw:
        gc = p.get("gang_circuits")
        if not gc:
            gc = P.m.data.get("switch_circuits", {}).get(p["id"])
            if gc:
                inferred.add(p["id"])
        links[p["id"]] = gc or []
    return dict(pts=pts, sw=sw, tags=tags, circ=circ, codes=codes, links=links, inferred=inferred)


def heights_txt(pts, t):
    hs = sorted({round(p["h"] * 100) for p in pts if p["type"] == t})
    if not hs:
        return ""
    if len(hs) > 5:
        c = collections.Counter(round(p["h"] * 100) for p in pts if p["type"] == t).most_common(4)
        return " / ".join(f"{h:.0f}" for h, _ in sorted(c)) + " (typ.)"
    return " / ".join(f"{h:.0f}" for h in hs)


def in_win(win, x, y):
    (x0, x1), (y0, y1) = win
    return x0 <= x <= x1 and y0 <= y <= y1


def elec_sheet(P, D, kind, no, win, scale, part):
    title, types = B.ELEC_SHEETS[kind]
    sub = {"W": "West half (bedroom wing to guest bathroom)", "E": "East half (dining, reception, terrace)", "F": "Whole flat"}[part]
    s, ax, py = P.plan_sheet("A3", no, title + ("" if part == "F" else f" - {'west' if part == 'W' else 'east'}"), scale, win, "mep", sub)
    lab = Labeller(ax)
    P.room_labels(ax, lab, size=5.0, dims=False, area=False, arabic=False)
    k = 1 / ax._mm_per_m
    pts = [p for p in D["pts"] if p["type"] in types and in_win(win, p["x"], p["y"])]
    if kind == "low":
        pts = [p for p in pts if p["type"] != "multi" or True]
    present = collections.Counter(p["type"] for p in pts)
    # LED lines on the lighting sheet
    if kind == "light":
        for l in P.m.elec["lines"]:
            if in_win(win, (l["x0"] + l["x1"]) / 2, (l["y0"] + l["y1"]) / 2):
                ax.plot([l["x0"], l["x1"]], [l["y0"], l["y1"]], color=HL, lw=lw(0.6), ls=(0, (3, 1.5)), zorder=8)
                present["led"] += 1
        # switches drawn small in black, links dashed to the nearest fixture of each mapped circuit
        for p in D["sw"]:
            if not in_win(win, p["x"], p["y"]):
                continue
            sym(ax, "switch", p["x"], p["y"], c=INK, size=2.2)
            lab.block(p["x"] - 1.2 * k, p["y"] - 1.2 * k, p["x"] + 1.2 * k, p["y"] + 1.2 * k)
            for c in D["links"].get(p["id"], []):
                if not c or c not in D["circ"]:
                    continue
                cands = []
                for kk, it in D["circ"][c]:
                    if kk == "pt":
                        cands.append((it["x"], it["y"]))
                    else:
                        cands.append(((it["x0"] + it["x1"]) / 2, (it["y0"] + it["y1"]) / 2))
                tx, ty = min(cands, key=lambda q: math.hypot(q[0] - p["x"], q[1] - p["y"]))
                ax.plot([p["x"], tx], [p["y"], ty], color=INK, lw=lw(0.12), ls=(0, (4, 2)), zorder=7)
            present["link"] += 1
        present["switch"] += 0
    for p in pts:
        c = HL
        sym(ax, p["type"], p["x"], p["y"], c=c, size=2.6 if scale <= 50 else 2.2)
        lab.block(p["x"] - 1.4 * k, p["y"] - 1.4 * k, p["x"] + 1.4 * k, p["y"] + 1.4 * k)
    # labels
    if kind == "light":
        for c, items in D["circ"].items():
            xy = [(it["x"], it["y"]) if kk == "pt" else ((it["x0"] + it["x1"]) / 2, (it["y0"] + it["y1"]) / 2) for kk, it in items]
            xy = [q for q in xy if in_win(win, *q)]
            if not xy:
                continue
            cx = sum(q[0] for q in xy) / len(xy)
            cy = sum(q[1] for q in xy) / len(xy)
            nearest = min(xy, key=lambda q: (q[0] - cx) ** 2 + (q[1] - cy) ** 2)
            lab.put(nearest[0], nearest[1], D["codes"][c], size=4.6, c=INK, weight="bold")
        for p in D["sw"]:
            if in_win(win, p["x"], p["y"]) and not D["tags"][p["id"]].endswith("b"):
                lab.put(p["x"], p["y"], D["tags"][p["id"]].rstrip("a"), size=4.2, c=INK)
        for p in pts:
            if p["type"] in ("ledfeed", "lightout", "walllight"):
                lab.put(p["x"], p["y"], short_h(p["h"]), size=4.2, c=HL)
    elif kind == "switch":
        done = set()
        for p in pts:
            if p["type"] == "switch":
                key = (round(p["x"], 3), round(p["y"], 3))
                if key in done:
                    continue
                done.add(key)
                stack = [q for q in pts if q["type"] == "switch" and (round(q["x"], 3), round(q["y"], 3)) == key]
                tag = D["tags"][stack[0]["id"]].rstrip("ab")
                gang = "+".join(str(len(q.get("gangs") or [])) for q in sorted(stack, key=lambda q: -q["h"]))
                hh = "/".join(short_h(q["h"]) for q in sorted(stack, key=lambda q: -q["h"]))
                lab.put(p["x"], p["y"], f"{tag} {gang}G @{hh}", size=4.6, c=INK)
            else:
                t = {"acctl": "AC ctl", "sensor": (p.get("tech") or "")}.get(p["type"], "")
                lab.put(p["x"], p["y"], f"{t} @{short_h(p['h'])}".strip(), size=4.3, c=INK)
    else:
        for p in pts:
            t = p["type"]
            hh = short_h(p["h"])
            if t == "socket":
                txt = f"{p.get('gang', 2)}x @{hh}"
                if p.get("appliance"):
                    txt += f" {p['appliance'][:16]}"
            elif t == "power":
                ap = (p.get("appliance") or "").replace("electric instant water heater", "inst. heater").replace("curtain motor (future)", "curtain motor")
                ap = ap.split("(")[0].strip()[:22]
                txt = f"{ap} @{hh}"
            elif t == "multi":
                txt = "+".join(p.get("parts", [])) + f" @{hh}"
            elif t == "flap":
                txt = f"flap S+2C @{hh}"
            elif t == "db":
                txt = f"DB 36-way @{hh}"
            elif t == "wp":
                txt = f"IP65 @{hh}"
            else:
                txt = f"@{hh}"
            lab.put(p["x"], p["y"], txt, size=4.4 if scale <= 50 else 3.8, c=INK)
    # side panel: legend with heights
    x = s.side_x + 2
    y = s.H - s.m - 4
    s.text(x, y, "LEGEND (heights cm from slab)", size=6, weight="bold")
    y -= 5
    allpts = D["pts"]
    order = ["spot", "pendant", "walllight", "led", "ledfeed", "lightout", "fan", "link", "switch", "acctl", "sensor",
             "socket", "flap", "power", "wp", "multi", "db", "data", "tv", "phone", "ap", "router", "intercom",
             "intercom_out", "lcp"]
    for t in order:
        if not present.get(t) and not (kind == "light" and t in ("switch",)):
            continue
        ht = heights_txt(allpts, t) if t not in ("led", "link", "spot") else ("ceiling" if t == "spot" else "")
        legend_entry(s, x + 3, y, t, f"{B.TYPE_NAMES.get(t, t)}" + (f"  [{ht}]" if ht else ""),
                     c=HL if t not in ("link", "switch") or kind != "light" else INK)
        y -= 4.6
    y -= 1
    if kind == "light":
        s.text(x, y, "CIRCUITS ON THIS SHEET", size=6, weight="bold")
        rows = []
        for c, items in D["circ"].items():
            xy = [(it["x"], it["y"]) if kk == "pt" else ((it["x0"] + it["x1"]) / 2, (it["y0"] + it["y1"]) / 2) for kk, it in items]
            if not any(in_win(win, *q) for q in xy):
                continue
            n = collections.Counter("LED strip" if kk == "line" else it["type"] for kk, it in items)
            what = ", ".join(f"{v} {kk}" for kk, v in n.items())
            sws = [D["tags"][p["id"]] for p in D["sw"] if c in (D["links"].get(p["id"]) or [])]
            rows.append([D["codes"][c], c, what[:22], ",".join(sorted(set(t.rstrip("ab") for t in sws))) or "-"])
        y = s.table(x, y - 2.5, [("Code", 9, "left"), ("Circuit", 26, "left"), ("Fittings", 25, "left"), ("Switch", 16, "left")],
                    rows, size=4.0, row_h=2.6)
        y -= 2.5
        s.notes(x, y, None, ["Dashed line: switch key to its circuit. Keys of S-switches without circuit ids in Main are inferred from the key text (see E209)."],
                width_chars=48, size=4.2, gap=2.0)
    elif kind == "switch":
        s.notes(x, y, "NOTES", [
            "Label: switch tag, gangs (top+lower box) and height(s). Key-by-key list in the schedule (E209).",
            "Stacked boxes: top 125, lower 113. Bedside 85.",
            "Two-way: front door / dining end / lobby (hallway spots); bedside S/N (pendants).",
        ], width_chars=48, size=4.4, gap=2.1)
    elif kind == "power":
        s.notes(x, y, "NOTES", [
            "Label: gangs (1x / 2x) and height; 'S+2C' = socket + 2 USB-C in a furniture flap.",
            "Dedicated circuits: split ACs (230), instant heaters, oven/hob, curtain motors (future, in ceiling boxes 268).",
            "DB 36-way behind the entrance artwork (top of box 180).",
        ], width_chars=48, size=4.4, gap=2.1)
    else:
        s.notes(x, y, "NOTES", [
            "All data Cat6 home-run to the network hub above the entrance shoe cabinet (ONT + router + 16-port PoE).",
            "APs on PoE in the ceiling. TV plates: D = data, H = HDMI conduit, TV = antenna, 2S = double socket.",
        ], width_chars=48, size=4.4, gap=2.1)
    return s


def schedule(P, D, no_base):
    pts = [p for p in D["pts"] if p["type"] != "spot"]
    pts.sort(key=lambda p: (p.get("room") or "", p["type"], p["h"]))
    spots = collections.Counter((p.get("room"), p.get("circuit")) for p in D["pts"] if p["type"] == "spot")
    rows = []
    for p in pts:
        tag = D["tags"].get(p["id"], "")
        desc = p.get("label", "")
        if p["type"] == "switch":
            keys = []
            cc = D["links"].get(p["id"]) or []
            for i, g in enumerate(p.get("gangs") or [], 1):
                c = cc[i - 1] if i - 1 < len(cc) else None
                keys.append(f"{i}: {g}" + (f" [{D['codes'][c]}]" if c in D["codes"] else ""))
            desc = desc.split(" — ")[0] + " — " + " | ".join(keys)
        rows.append([p["id"], tag, p.get("room") or "", B.TYPE_NAMES.get(p["type"], p["type"]), f"{p['h'] * 100:.0f}", desc])
    for (room, c), n in spots.items():
        rows.append(["spots", "", room or "", "Ceiling spot 6 W", "ceil.", f"{n} spots on circuit {c} [{D['codes'].get(c, '')}]"])
    per = 40
    pages = []
    npages = math.ceil(len(rows) / per)
    for i in range(0, len(rows), per):
        no = f"E209.{i // per + 1}"
        s = P.new("A4", no, f"Electrical schedule ({i // per + 1}/{npages})", "-",
                  "All points in Main's electrical file; spots summarised per circuit")
        x0 = s.m + 2
        x1 = s.side_x - 2
        widths = [23, 8, 21, 37, 8]
        xs = [x0]
        for w in widths:
            xs.append(xs[-1] + w)
        y = s.H - s.m - 4
        s.rect(x0, y - 3.2, x1, y, fc="#e6e6e6", w=0.2)
        for xx, t in zip(xs, ["Id", "Tag", "Room", "Type", "h cm", "Description"]):
            s.text(xx + 0.6, y - 1.6, t, size=4.4, weight="bold")
        y -= 3.2
        dchars = int((x1 - xs[-1]) / (0.56 * 3.7 * 0.3528)) - 2
        for r in rows[i:i + per]:
            ln = wrap(r[5], dchars)
            if len(ln) > 2:
                ln = ln[:2]
                ln[1] = ln[1][: dchars - 4] + " ..."
            rh = 4.6 if len(ln) > 1 else 2.9
            s.rect(x0, y - rh, x1, y, w=0.1)
            for xx, v in zip(xs[:5], r[:5]):
                s.text(xx + 0.6, y - 1.45, str(v)[:26], size=3.9)
            for j, l in enumerate(ln):
                s.text(xs[5] + 0.6, y - 1.45 - j * 1.7, l, size=3.7)
            y -= rh
        s.notes(s.side_x + 2, s.H - s.m - 4, "NOTES", [
            "Heights in cm from the concrete slab (designer's plan convention), to confirm with the floor build-up.",
            "Ids match Main's electrical-kareems-changes.json and the hover labels on the live model.",
            "Tags S01.. match the switch sheets; [Cxx] = lighting circuit code on E201/E202.",
        ], width_chars=34, size=4.3, gap=2.1)
        pages.append(s)
    return pages
