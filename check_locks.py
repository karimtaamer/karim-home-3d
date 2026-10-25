#!/usr/bin/env python3
"""check_locks: fail when furnish.js or a built model breaks a settled decision in design-locks.json.

    python3 check_locks.py            # exit 1 and list what broke

Standard library only (runs in Edit AI on Vercel, in the deploy workflow and in .githooks/pre-push). Edit AI calls
violations(files) with its working copies before saving, and only lets a new violation through when the request
names the lock (one of its "names"). furnish.js is read as text: if a locked block changes shape so a number can't
be read, that is a violation too (update the reader here with the change).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_locks(read=None):
    read = read or (lambda p: (ROOT / p).read_bytes())
    return json.loads(read("design-locks.json"))["locks"]


def _block(src, start, end="// ---"):
    i = src.find(start)
    if i < 0:
        return None
    j = src.find(end, i + len(start))
    return src[i:j if j > 0 else len(src)]


def _num(block, pattern):
    m = block and re.search(pattern, block)
    return float(m.group(1)) if m else None


def _nums(s):
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s)]


def _model(text):
    return json.loads(text[text.index("=") + 1:].strip().rstrip(";"))


def _tv(furnish):
    b = _block(furnish, "--- Reception: TV wall")
    tall = b and re.search(r"const tall = (?:KC \? )?\[\[([-\d.]+),\s*([-\d.]+)\],\s*\[([-\d.]+),\s*([-\d.]+)\]\]", b)
    hole = b and re.search(r"tall\.map\(\(\[x0, x1\]\) => \[x0, x1, ([\d.]+), ([\d.]+), ([\d.]+)\]\)", b)
    shelves = b and re.search(r"for \(const y of \[([^\]]+)\]\)", b)
    return {"item_x": _num(b, r"item\(\s*([-\d.]+)\s*,"), "run": _num(b, r"D0 = KC \? ([\d.]+)"),
            "tv": _num(b, r"D1 = KC \? ([\d.]+)"), "splay": _num(b, r"const splay = ([\d.]+)"),
            "tall": [float(tall.group(i)) for i in range(1, 5)] if tall else None,
            "hole": [float(hole.group(i)) for i in range(1, 4)] if hole else None,
            "shelves": _nums(shelves.group(1)) if shelves else None,
            "edge": _num(b, r"edge = KC \? (-?[\d.]+)"),
            "low": _nums(re.search(r"const low = KC \? \[([^\]]+)\]", b).group(1))[:2] if b and re.search(r"const low = KC \? \[([^\]]+)\]", b) else None,
            "tcx_from_low": bool(b and "const tcx = (low[0] + low[1]) / 2" in b)}


def check(lock, files):
    """Problems (strings) with one lock; files: path -> text."""
    near = lambda a, b: a is not None and abs(a - b) <= lock.get("tol", 0.003)
    i = lock["id"]
    if i == "kc-column-face":
        m = _model(files[lock["model"]])
        lo, hi = lock["y_range"]
        xs = [x for w in m["walls"] for ring in [w["outer"], *w.get("holes", [])] for x, y in ring
              if lo - 0.03 <= y <= hi + 0.03 and 17.0 <= x <= 18.3]
        face = max(xs) if xs else None
        return [] if near(face, lock["face_x"]) else [
            f"column face is at plan x {face} in {lock['model']}, locked at {lock['face_x']} (rebuild with build_flags.json's --cut)"]
    t = _tv(files["furnish.js"])
    if i == "kc-tv-wall-flush":
        if t["item_x"] is None or t["tv"] is None:
            return ["can't read the TV wall's position/depth in furnish.js"]
        face = round(t["item_x"] + t["tv"], 4)
        return [] if near(face, lock["face_x"]) else [f"TV wall face is at plan x {face}, locked flush with the column at {lock['face_x']}"]
    if i == "kc-tv-niche-depths":
        out = []
        if not near(t["run"], lock["run_depth"]):
            out.append(f"tall niche (run) depth {t['run']}, locked at {lock['run_depth']}")
        if not near(t["tv"], lock["tv_depth"]):
            out.append(f"TV niche (box) depth {t['tv']}, locked at {lock['tv_depth']}")
        if t["run"] is not None and t["tv"] is not None and not near(t["tv"] - t["run"], lock["step"]):
            out.append(f"step between TV box and run {round(t['tv'] - t['run'], 4)}, locked at {lock['step']}")
        if not near(t["splay"], lock["splay"]):
            out.append(f"splayed curve {t['splay']}, locked at {lock['splay']}")
        return out
    if i == "kc-buffet-niche-matches-tv":
        out = []
        b = _block(files["furnish.js"], "Buffet wall per the DWG")
        n = b and re.search(r"const niche = BK \? \[([^\]]+)\]", b)
        sh = b and re.search(r"for \(const y of BK \? \[([^\]]+)\]", b)
        if not n or not sh:
            return ["can't read the buffet niche in furnish.js"]
        x0, x1, y0, y1, r = _nums(n.group(1))
        want = (lock["width"], lock["y0"], lock["y1"], lock["r"])
        for name, got, w in zip(("width", "bottom", "top", "corner radius"), (x1 - x0, y0, y1, r), want):
            if not near(got, w):
                out.append(f"buffet niche {name} {round(got, 4)}, locked at {w}")
        if [round(v, 3) for v in _nums(sh.group(1))] != lock["shelves"]:
            out.append(f"buffet shelves {sh.group(1)}, locked at {lock['shelves']}")
        if t["tall"] and t["hole"]:  # and the TV wall's tall niches are still the same opening
            for a, b_ in zip(t["tall"][::2], t["tall"][1::2]):
                if not near(b_ - a, lock["width"]):
                    out.append(f"TV wall tall niche width {round(b_ - a, 4)} no longer matches the buffet's {lock['width']}")
            for name, got, w in zip(("bottom", "top", "corner radius"), t["hole"], want[1:]):
                if not near(got, w):
                    out.append(f"TV wall tall niche {name} {got} no longer matches the buffet's {w}")
            if t["shelves"] and [round(v, 3) for v in t["shelves"]] != lock["shelves"]:
                out.append(f"TV wall tall niche shelves {t['shelves']} no longer match the buffet's {lock['shelves']}")
        else:
            out.append("can't read the TV wall's tall niches in furnish.js")
        return out
    if i == "kc-tv-wall-centring":
        out = []
        if not t["tall"] or not t["low"] or t["edge"] is None:
            return ["can't read the TV wall's niches / return in furnish.js"]
        if not t["tcx_from_low"]:
            out.append("TV is no longer centred on the low niche (const tcx = (low[0] + low[1]) / 2)")
        if not (near(t["low"][0], lock["low"][0]) and near(t["low"][1], lock["low"][1])):
            out.append(f"low niche {t['low']}, locked at {lock['low']}")
        c = (t["low"][0] + t["low"][1]) / 2
        if not near(c, lock["tv_center"]):
            out.append(f"TV centre local {round(c, 4)}, locked at {lock['tv_center']}")
        if c + lock["tv_width"] / 2 > lock["column_x"]:
            out.append("TV reaches into the column")
        if not near(t["edge"], lock["edge"]):
            out.append(f"splayed return at {t['edge']}, locked at {lock['edge']}")
        want = [v for pair in lock["tall"] for v in pair]
        if any(not near(a, b_) for a, b_ in zip(t["tall"], want)):
            out.append(f"tall niches {t['tall']}, locked at {want}")
        return out
    return [f"unknown lock {i} (add its check to check_locks.py)"]


def violations(read=None):
    """{lock id: [problems]} for every broken lock; read(path) -> bytes (defaults to the repo files)."""
    read = read or (lambda p: (ROOT / p).read_bytes())
    locks = load_locks(read)
    paths = {"furnish.js"} | {l["model"] for l in locks if "model" in l}
    files = {p: read(p).decode() for p in paths}
    out = {}
    for lock in locks:
        if lock.get("suspended"):
            continue
        try:
            probs = check(lock, files)
        except Exception as e:  # noqa: BLE001 - a lock that can't be checked counts as broken
            probs = [f"check failed: {e}"]
        if probs:
            out[lock["id"]] = probs
    return out


def named(lock, message):
    """Does the request name this lock (so breaking it is on purpose)?"""
    msg = (message or "").lower()
    return any(n.lower() in msg for n in lock.get("names", []))


def main():
    bad = violations()
    locks = {l["id"]: l for l in load_locks()}
    for i, probs in bad.items():
        l = locks.get(i, {})
        print(f"LOCK BROKEN {i} ({l.get('decided_by')}, {l.get('date')}): {l.get('what')}")
        for p in probs:
            print(f"  - {p}")
    for l in locks.values():
        if l.get("suspended"):
            print(f"lock suspended {l['id']}: {l['suspended']}")
    if not bad:
        print(f"check_locks: all {len(locks)} design locks hold" + (" (some suspended)" if any(l.get("suspended") for l in locks.values()) else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
