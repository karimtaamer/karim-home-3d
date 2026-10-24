#!/usr/bin/env python3
"""Edit AI: change the flat from inside the viewer, in words, with what's on screen as the picture.

    python3 edit_ai.py [port]     # serves this folder on http://127.0.0.1:8000 with Edit AI and Generate Photo Spot

The page (edit-ai.js) freezes the 3D or 2D view, the user circles what to change (or picks Whole view), says what
they want and may attach reference pictures. POST /api/edit-ai/chat sends that here; an OpenAI chat model with
vision (EDIT_AI_MODEL, default gpt-5.6-sol, key EDIT_AI_OPENAI_API_KEY, kept apart from Generate Photo Spot's
OPENAI_API_KEY) works through tools: it greps and reads furnish.js / materials.js / the docs, edits them by exact
search/replace, queries and edits the version's DXF (edit_ai_dxf.py), and the model and drawing are rebuilt from the
DXF (build_geometry.py, build_drawing.py) whenever the plan changed, so the 3D and the 2D stay one.

Hot path: the result is live at once. Every changed file is stored by content under edit-ai-live/files/, and a
revision (edit-ai-live/<version>/rev-*.json) lists the files that override the deployed ones for that version. The
page asks GET /api/edit-ai/patches?version= on load and takes those files instead (edit-ai-live/ is a folder here,
Vercel Blob on Vercel: vercel.json rewrites /edit-ai-live/* to the store). An override drops out by itself once the
deployed file equals it (git sync landed); if the deployed file moved on underneath, a text edit is replayed on it.

Git sync, after the edit is already live: here (not on Vercel) the files are written into the repo and committed and
pushed in the background (EDIT_AI_GIT_SYNC=0 turns it off). On Vercel, with EDIT_AI_GITHUB_TOKEN set, the files go
to EDIT_AI_GITHUB_REPO (default karimtaamer/karim-home-3d) on main as one commit through the GitHub API; without
a token there is no git sync and the edit lives in Blob only.

Public: anyone may use it. Each IP gets EDIT_AI_RATE requests an hour (default 20); the key's own cap does the rest.
"""
import base64, hashlib, json, os, re, secrets, shutil, subprocess, sys, tempfile, threading, time, urllib.error, \
    urllib.parse, urllib.request
from collections import defaultdict, deque
from http.server import ThreadingHTTPServer
from pathlib import Path

import photogen
import photogen_blob

ROOT = Path(__file__).resolve().parent
LIVE = "edit-ai-live"  # the store's prefix, and the folder here
BLOB = bool(photogen_blob.token())
ON_VERCEL = bool(os.environ.get("VERCEL"))
MODEL = os.environ.get("EDIT_AI_MODEL", "gpt-5.6-sol")
RATE = int(os.environ.get("EDIT_AI_RATE", "20"))
OPENAI_URL = os.environ.get("EDIT_AI_OPENAI_URL", "https://api.openai.com/v1/chat/completions")  # a test double can stand in
MAX_STEPS = 16  # tool rounds per message
MAX_IMAGE = 3_000_000  # bytes of a data URL
MAX_REFS = 4
# USD per million tokens (input, cached input, output), OpenAI list prices; only to tell the user what a message cost.
PRICES = {"gpt-5.6-sol": (5.0, 0.5, 30.0), "gpt-4.1": (2.0, 0.5, 8.0), "gpt-4.1-mini": (0.4, 0.1, 1.6), "gpt-4.1-nano": (0.1, 0.025, 0.4),
          "gpt-4o": (2.5, 1.25, 10.0), "gpt-4o-mini": (0.15, 0.075, 0.6)}
ORIGIN = (190.4049651574427, -121.6132067325871)  # DWG -> plan, the same for every version (model*.js "origin")

# Each plan version: its DXF, the files built from it and the build flags (README §3-4).
NC_FLAGS = ["--wall", "190.9609,-112.8031,190.9609,-112.3428", "--cut", "191.0309,-114.2431,191.7309,-114.0731",
            "--window", "192.2087,-112.47,1.5,2.1,frosted"]
VERSIONS = {
    "main": {"dxf": "dwg/main.dxf", "model": "model.js", "drawing": "drawing.json", "tour": "tour.json", "flags": []},
    "bigger-bedroom": {"dxf": "dwg/bigger-bedroom.dxf", "model": "model-bigger-bedroom.js", "drawing": "drawing-bigger-bedroom.json",
                       "tour": "tour-bigger-bedroom.json", "flags": ["--wall", "196.65,-112.594,196.65,-115.017"]},
    "shifted-bedroom": {"dxf": "dwg/shifted-bedroom.dxf", "model": "model-shifted-bedroom.js", "drawing": "drawing-shifted-bedroom.json",
                        "tour": "tour-shifted-bedroom.json", "flags": ["--cut", "191.0809,-112.944,191.2609,-112.724"]},
    "naghams-changes": {"dxf": "dwg/naghams-changes.dxf", "model": "model-naghams-changes.js", "drawing": "drawing-naghams-changes.json",
                        "tour": "tour-naghams-changes.json", "flags": NC_FLAGS},
    "kareems-changes": {"dxf": "dwg/kareems-changes.dxf", "model": "model-kareems-changes.js", "drawing": "drawing-kareems-changes.json",
                        "tour": "tour-kareems-changes.json", "flags": NC_FLAGS},
    "as-built": {"dxf": "dwg/as-built.dxf", "model": "model-as-built.js", "drawing": "drawing-as-built.json",
                 "tour": "tour-as-built.json", "flags": []},
}
SHARED = ["furnish.js", "materials.js"]  # loaded by the page through the live overrides; shared by every version
DOCS = ["README.md", "DWG_EDITING.md", "CLAUDE.md"]  # read-only context
MIME = {".js": "text/javascript; charset=utf-8", ".json": "application/json", ".dxf": "application/dxf"}


def editable(v):
    c = VERSIONS[v]
    return SHARED + [c["tour"]]


def readable(v):
    c = VERSIONS[v]
    return editable(v) + DOCS + ["index.html", "drawing.js", "check_furnish.py", "tour.json"] + [c["tour"]]


def api_key():
    # Prefer the dedicated Edit AI key; ignore the connector placeholder "[REDACTED]"
    # (Vercel MCP redacts secrets when saving). Fall back to photogen's OPENAI_API_KEY.
    def _ok(v):
        v = (v or "").strip().strip('"\'')
        return v if v and v != "[REDACTED]" and len(v) > 20 else None
    if k := _ok(os.environ.get("EDIT_AI_OPENAI_API_KEY")):
        return k
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            name, _, val = line.partition("=")
            if name.strip() == "EDIT_AI_OPENAI_API_KEY" and (k := _ok(val)):
                return k
    if k := _ok(os.environ.get("OPENAI_API_KEY")):
        return k
    return None


def sha(b):
    return hashlib.sha256(b).hexdigest()[:20]


# --- The live store: content-addressed files and per-version revisions ---------------------------------------------
def put(path, data, mime):
    if BLOB:
        photogen_blob.put(path, data, mime, overwrite=True)
    else:
        (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / path).write_bytes(data)


_cache = {}


def get(path):
    if path in _cache:  # files and revisions are written once under their own names
        return _cache[path]
    data = photogen_blob.get(path) if BLOB else (ROOT / path).read_bytes()
    if len(_cache) > 64:
        _cache.clear()
    _cache[path] = data
    return data


def store(data, path):
    """Keep a file's content under its hash; the URL the page loads it from."""
    url = f"{LIVE}/files/{sha(data)}{Path(path).suffix}"
    put(url, data, MIME.get(Path(path).suffix, "application/octet-stream"))
    return url


def revisions(v):
    pre = f"{LIVE}/{v}/"
    if BLOB:
        names = photogen_blob.names(pre)
    else:
        d = ROOT / pre
        names = [f"{pre}{p.name}" for p in d.glob("rev-*.json")] if d.exists() else []
    return sorted(n for n in names if Path(n).name.startswith("rev-"))


def latest(v, skip=0):
    revs = revisions(v)
    if len(revs) <= skip:
        return None
    return json.loads(get(revs[-1 - skip]))


def deployed(path):
    p = ROOT / path
    return p.read_bytes() if p.exists() else b""


def replay(text, ops):
    """Apply recorded search/replace edits to a newer base; None if one neither applies nor is already in."""
    for o in ops:
        if text.count(o["old"]) == 1:
            text = text.replace(o["old"], o["new"])
        elif o["new"] not in text:
            return None
    return text


def resolve(man):
    """{path: (status, entry, content or None)} for a revision against the files deployed now.
    status: live (use the stored file), replayed (content given), synced (deployed already equals it), conflict."""
    out = {}
    if not man:
        return out
    for path, e in man["files"].items():
        dep = deployed(path)
        if sha(dep) == e["sha"]:
            out[path] = ("synced", e, None)
        elif sha(dep) == e["base"]:
            out[path] = ("live", e, None)
        elif e.get("ops"):
            t = replay(dep.decode(), e["ops"])
            out[path] = ("replayed", e, t.encode()) if t is not None else ("conflict", e, None)
        else:
            out[path] = ("conflict", e, None)
    # Files built from the DXF stand or fall with it.
    for path, (st, e, _) in list(out.items()):
        if e.get("derived") and out.get(e["derived"], ("synced",))[0] == "conflict":
            out[path] = ("conflict", e, None)
    return out


def live_content(path, st):
    status, e, content = st
    if status == "replayed":
        return content
    if status == "live":
        return get(e["url"])
    return deployed(path)


def patches(v):
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    man = latest(v)
    res = resolve(man)
    files, conflicts = {}, []
    for path, (status, e, content) in res.items():
        if status == "live":
            files[path] = {"url": e["url"], "sha": e["sha"]}
        elif status == "replayed":
            files[path] = {"content": content.decode(), "sha": sha(content)}
        elif status == "conflict":
            conflicts.append(path)
    return {"version": v, "rev": man and man["rev"], "summary": man and man.get("summary"), "files": files,
            "conflicts": conflicts, "ready": bool(api_key()), "model": MODEL, "undo": bool(man and man.get("changed"))}


# --- One message: the workspace the model edits ---------------------------------------------------------------------
class Workspace:
    def __init__(self, v):
        self.v, self.cfg = v, VERSIONS[v]
        self.man = latest(v)
        self.res = resolve(self.man)
        self.files, self.ops, self.changed = {}, defaultdict(list), set()
        self.tmp = Path(tempfile.mkdtemp(prefix="edit-ai-"))
        self.dxf_path = None  # the working DXF once the plan is touched (or read)

    def read(self, path):
        if path not in self.files:
            st = self.res.get(path)
            self.files[path] = live_content(path, st) if st else deployed(path)
        return self.files[path]

    def text(self, path):
        return self.read(path).decode()

    def write(self, path, data, op=None):
        self.files[path] = data
        self.changed.add(path)
        if op:
            self.ops[path].append(op)

    def dxf(self):
        if not self.dxf_path:
            self.dxf_path = self.tmp / "plan.dxf"
            self.dxf_path.write_bytes(self.read(self.cfg["dxf"]))
        return self.dxf_path


def dwg_python():
    for p in (os.environ.get("EDIT_AI_DWG_PYTHON"), str(Path.home() / ".dwg-tools/bin/python")):
        if p and Path(p).exists():
            return p
    return sys.executable


def run(args, cwd=None, stdin=None, timeout=120):
    p = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def rebuild(ws):
    """Build the version's model and drawing from the working DXF (and tour) into the workspace."""
    c, t = ws.cfg, ws.tmp
    for name in {"tour.json", c["tour"]}:
        (t / name).write_bytes(ws.read(name))
    py = dwg_python()
    code, out = run([py, str(ROOT / "build_geometry.py"), str(ws.dxf()), "--out", str(t / c["model"]),
                     "--tour", str(t / c["tour"]), *c["flags"]], cwd=t, timeout=180)
    if code:
        raise RuntimeError(f"build_geometry failed: {out[-1500:]}")
    code2, out2 = run([py, str(ROOT / "build_drawing.py"), str(ws.dxf()), "--model", str(t / c["model"]),
                       "--out", str(t / c["drawing"])], cwd=t, timeout=180)
    if code2:
        raise RuntimeError(f"build_drawing failed: {out2[-1500:]}")
    ws.write(c["model"], (t / c["model"]).read_bytes())
    ws.write(c["drawing"], (t / c["drawing"]).read_bytes())
    return "\n".join(out.splitlines()[-4:] + out2.splitlines()[-1:])


def js_check(ws, path):
    """Parse a JS module with node when there is one (not on Vercel); None when it parses or can't be checked."""
    node = shutil.which("node")
    if not node:
        return None
    f = ws.tmp / (Path(path).stem + ".mjs")
    f.write_bytes(ws.read(path))
    code, out = run([node, "--check", str(f)], timeout=30)
    return out[-1200:] if code else None


# --- Tools the model gets ---------------------------------------------------------------------------------------------
TOOLS = [
    {"name": "grep", "description": "Search readable files for a regex (case-insensitive). Returns up to 40 matching lines with line numbers.",
     "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string", "description": "one file; omit for all readable files"}},
                    "required": ["pattern"]}},
    {"name": "read_file", "description": "Read lines of a readable file (at most 220 lines per call), with line numbers.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}},
                    "required": ["path", "start", "end"]}},
    {"name": "edit_file", "description": "Replace an exact, unique snippet of an editable file (furnish.js, materials.js, the version's tour JSON). "
                                         "`old` must match the file byte for byte (copy it from read_file without the line numbers) and occur once.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
                    "required": ["path", "old", "new"]}},
    {"name": "furniture_near", "description": "furnish.js lines that place an item( x, y, ...) within `radius` m of a plan point, to find the code of a piece you see.",
     "parameters": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "radius": {"type": "number"}},
                    "required": ["x", "y"]}},
    {"name": "plan_rooms", "description": "The version's rooms: name, label position and floor extent in plan metres, plus ceiling/door/window heights.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "dxf_query", "description": "Entities of the version's plan DXF inside a box (plan metres), optionally only some layers "
                                        "(1wall, Windows, 3door, 2furni, Glass, _DIM, ISLAK). Gives handles for dxf_edit.",
     "parameters": {"type": "object", "properties": {"x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"}, "y1": {"type": "number"},
                                                     "layers": {"type": "string", "description": "comma-separated"}},
                    "required": ["x0", "y0", "x1", "y1"]}},
    {"name": "dxf_edit", "description": "Edit the version's plan DXF (plan metres). ops: move {handles,dx,dy}; copy {handles,dx,dy}; delete {handles}; "
                                       "add_line {layer,a:[x,y],b:[x,y]}; add_polyline {layer,points,closed}; set_points {handle,points}. "
                                       "The 3D model and the 2D drawing are rebuilt from it when you finish.",
     "parameters": {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}}}, "required": ["ops"]}},
    {"name": "check", "description": "Check the edits so far: JS syntax of furnish.js / materials.js and, if the plan changed, a trial rebuild of the model and drawing.",
     "parameters": {"type": "object", "properties": {}}},
]


def numbered(text, start, end):
    lines = text.splitlines()
    start, end = max(1, start), min(len(lines), end, start + 219)
    return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1)) + f"\n[{len(lines)} lines in all]"


def tool(ws, name, a):
    v = ws.v
    if name == "grep":
        rx = re.compile(a["pattern"], re.I)
        paths = [a["path"]] if a.get("path") else readable(v)
        hits = []
        for p in paths:
            if p not in readable(v):
                return f"{p} isn't readable here. Readable: {', '.join(readable(v))}"
            for i, line in enumerate(ws.text(p).splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{p}:{i}: {line[:240]}")
                    if len(hits) >= 40:
                        return "\n".join(hits) + "\n[more matches cut; narrow the pattern]"
        return "\n".join(hits) or "no matches"
    if name == "read_file":
        p = a["path"]
        if p not in readable(v):
            return f"{p} isn't readable here. Readable: {', '.join(readable(v))}"
        return numbered(ws.text(p), int(a["start"]), int(a["end"]))
    if name == "edit_file":
        p = a["path"]
        if p not in editable(v):
            return f"{p} can't be edited. Editable: {', '.join(editable(v))}; the plan through dxf_edit."
        t, n = ws.text(p), ws.text(p).count(a["old"])
        if not a["old"] or n != 1:
            return f"`old` occurs {n} times in {p}; it has to match exactly once. Read the lines again and copy them exactly."
        t = t.replace(a["old"], a["new"])
        ws.write(p, t.encode(), {"old": a["old"], "new": a["new"]})
        if p.endswith(".js") and (err := js_check(ws, p)):  # kept, so it can be fixed; saving checks again
            return f"edited, but {p} no longer parses:\n{err}"
        if p.endswith(".json"):
            try:
                json.loads(t)
            except ValueError as e:
                return f"edited, but {p} is no longer valid JSON: {e}"
        return f"edited {p}"
    if name == "furniture_near":
        x, y, rad = float(a["x"]), float(a["y"]), float(a.get("radius") or 1.0)
        out = []
        for i, line in enumerate(ws.text("furnish.js").splitlines(), 1):
            for m in re.finditer(r"\bitem\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", line):
                if ((float(m[1]) - x) ** 2 + (float(m[2]) - y) ** 2) ** 0.5 <= rad:
                    out.append(f"furnish.js:{i}: {line.strip()[:240]}")
                    break
        return "\n".join(out[:40]) or "no item( x, y ) literal that near; try grep for the room or the piece's name"
    if name == "plan_rooms":
        s = ws.text(ws.cfg["model"])
        m = json.loads(s[s.index("{"):s.rindex("}") + 1])
        labels = [{"name": l["text"], "at": [l["x"], l["y"]]} for l in m.get("labels", [])]
        floors = []
        for f in m.get("floor", []):
            ring = f.get("outer") or []
            if ring:
                xs, ys = [q[0] for q in ring], [q[1] for q in ring]
                box = [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]
                inside = [l["name"] for l in labels if box[0] <= l["at"][0] <= box[2] and box[1] <= l["at"][1] <= box[3]]
                floors.append({"rooms": inside, "box": box})
        return json.dumps({"heights": {k: m[k] for k in ("ceiling", "doorHead", "sill", "winHead", "sliderHead")},
                           "bounds": m["bounds"], "labels": labels, "floor_areas": floors})[:6000]
    if name == "dxf_query":
        args = [dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(ws.dxf()), "--origin", f"{ORIGIN[0]},{ORIGIN[1]}",
                "--bbox", f"{a['x0']},{a['y0']},{a['x1']},{a['y1']}", "--limit", "120"]
        if a.get("layers"):
            args += ["--layers", a["layers"]]
        code, out = run(args, timeout=90)
        return out[:24000]
    if name == "dxf_edit":
        if v == "as-built" and not ws.allow_as_built:
            return "As-built is the survey of the flat as it stands; it can't be edited from another version."
        out_path = ws.tmp / "plan-next.dxf"
        code, out = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "edit", str(ws.dxf()), str(out_path),
                         "--origin", f"{ORIGIN[0]},{ORIGIN[1]}"], stdin=json.dumps(a["ops"]), timeout=120)
        if code:
            return f"nothing changed: {out[-1500:]}"
        out_path.replace(ws.dxf())
        ws.write(ws.cfg["dxf"], ws.dxf().read_bytes())
        ws.plan_dirty = True
        return out
    if name == "check":
        notes = []
        for p in SHARED:
            if p in ws.changed and (err := js_check(ws, p)):
                notes.append(f"{p}: {err}")
        if getattr(ws, "plan_dirty", False) or ws.cfg["tour"] in ws.changed:
            try:
                notes.append(rebuild(ws))
                ws.plan_dirty = False
            except Exception as e:
                notes.append(str(e))
        return "\n".join(notes) or ("no syntax problems" if shutil.which("node") else "no node here, syntax can't be checked; be careful")
    return f"unknown tool {name}"


SYSTEM = """\
You are Edit AI inside the 3D viewer of Karim's apartment (Lotus, New Cairo). The user is looking at the {showing} \
of plan version "{version}" and wants something in it changed. You change it yourself, with the tools, and the page \
reloads with your change live. Any change is in scope: furniture, joinery, finishes and materials, lights, doors, \
windows and walls.

How the project is built:
- The plan DXF (one per version, edited with dxf_query / dxf_edit) is the source of the walls (layer 1wall: every \
wall is two parallel face lines, 0.11-0.12 m apart inside, 0.25 m outside), windows (Windows), doors (3door blocks, \
plus jambs / swing arcs on 1wall), furniture outlines (2furni: closed polylines) and room names (ISLAK TEXT). The 3D \
walls/openings (model JS) and the 2D drawing are rebuilt from the DXF automatically after you edit it. Never add TEXT.
- furnish.js builds every piece of furniture, joinery and fitting in 3D, in plan metres (x east, y north, origin the \
plan's south-west corner; heights in metres above the floor), with item(x, y, facing, build). It is shared by all \
versions and branches on `version === "..."`. Change only version "{version}" unless the user asks otherwise: if a line \
serves several versions, split it, e.g. `version === "{version}" ? newValue : oldValue`. materials.js holds the \
materials (colours, textures) that furnish.js uses by name (mat.whiteLacquer, ...).
- Keep 3D and 2D together: a piece drawn on the plan (2furni) that you move or resize in furnish.js gets the same \
change in the DXF, and a DXF furniture change gets the same change in furnish.js. A wall moved in the DXF must keep \
both faces, close its junctions exactly (snap endpoints to existing ones within 0.1 mm), and the furniture against it \
moves with it in furnish.js.
- DXF coordinates in the tools are plan metres (the same frame as furnish.js and the camera numbers below).

Work fast and cheap: find the code with furniture_near / grep around the plan point the user marked, read only the \
lines you need, make the smallest edits that do the job, run `check` once after editing, then answer. Don't re-read \
whole files. If the request is ambiguous, make the most sensible choice and say what you chose. If something truly \
can't be done, change nothing and say why.

The picture: image 1 is the frozen view{marked}. Later images are the user's references (looks to copy, not a plan).

Answer the user in one to three short sentences, plain words, sizes in cm: what you changed and anything they should \
check. No code, no file names unless asked."""


def context_text(ctx):
    c = ctx or {}
    lines = [f"Screen: {'2D drawing' if c.get('showing') == 'drawing' else '3D model'}"
             + (f", {c.get('mode')} view" if c.get("showing") != "drawing" and c.get("mode") else "")]
    if c.get("room"):
        lines.append(f"Room the camera is in: {c['room']}")
    if c.get("cam"):
        x, y, h, lx, ly, lh, *fov = c["cam"]
        lines.append(f"Camera at plan ({x}, {y}), eye height {h} m, looking toward ({lx}, {ly}, {lh})"
                     + (f", vertical FOV {fov[0]}°" if fov else ""))
    if c.get("planBox"):
        lines.append(f"Plan area on screen (x0, y0, x1, y1 m): {c['planBox']}")
    if c.get("highlightBox"):
        lines.append(f"Plan area the user circled (x0, y0, x1, y1 m): {c['highlightBox']}")
    for h in (c.get("hits") or [])[:10]:
        lines.append(f"Circled surface at plan ({h.get('x')}, {h.get('y')}), {h.get('h')} m up"
                     + (f", material {h['material']}" if h.get("material") else "")
                     + (", a furniture piece" if h.get("furniture") else ", architecture (wall/floor/ceiling)"))
    lines.append("The user chose Whole view (no circle): the request is about everything in the picture."
                 if c.get("wholeView") else "The user circled the part to change in red on image 1.")
    return "\n".join(lines)


def check_image(u, what):
    if not isinstance(u, str) or not re.match(r"^data:image/(jpeg|png|webp);base64,", u):
        raise ValueError(f"{what} must be a JPEG, PNG or WebP image")
    if len(u) > MAX_IMAGE:
        raise ValueError(f"{what} is too large (keep it under ~2 MB)")
    return u


def plan_edits():
    """Walls and other DXF edits need the DWG folder and build scripts, which .vercelignore keeps off the deploy."""
    return (ROOT / "dwg").is_dir() and (ROOT / "build_geometry.py").exists() and (ROOT / "build_drawing.py").exists()


def openai(messages, first=False):
    tools = [t for t in TOOLS if plan_edits() or not t["name"].startswith("dxf_")]
    req = urllib.request.Request(OPENAI_URL, method="POST", data=json.dumps({
        "model": MODEL, "messages": messages, **({"reasoning_effort": "none"} if MODEL.startswith(("gpt-5", "gpt-6")) else {"temperature": 0.2}), **({"tool_choice": "required"} if first else {}),
        "tools": [{"type": "function", "function": t} for t in tools]}).encode(),
        headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:300]
        raise RuntimeError(f"OpenAI said {e.code}: {msg}")


def cost(usage, total):
    for k in ("prompt_tokens", "completion_tokens"):
        total[k] += usage.get(k, 0)
    total["cached"] += (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)


def dollars(total):
    p = next((v for k, v in sorted(PRICES.items(), key=lambda kv: -len(kv[0])) if MODEL.startswith(k)), None)
    if not p:
        return None
    fresh = total["prompt_tokens"] - total["cached"]
    return round((fresh * p[0] + total["cached"] * p[1] + total["completion_tokens"] * p[2]) / 1e6, 4)


def chat(req):
    v = req.get("version") or "main"
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    if not api_key():
        raise PermissionError("Edit AI isn't switched on yet: set EDIT_AI_OPENAI_API_KEY (or OPENAI_API_KEY) on the server.")
    message = (req.get("message") or "").strip()[:4000]
    if not message:
        raise ValueError("Say what you want changed.")
    ctx = req.get("context") or {}
    image = check_image(req.get("image"), "the view")
    refs = [check_image(u, f"reference {i + 1}") for i, u in enumerate((req.get("refs") or [])[:MAX_REFS])]
    ws = Workspace(v)
    ws.allow_as_built = v == "as-built"  # only ever reached from the as-built page itself
    ws.plan_dirty = False
    sys_prompt = SYSTEM.format(showing="2D drawing" if ctx.get("showing") == "drawing" else "3D model", version=v,
                               marked="" if ctx.get("wholeView") else ", with what the user circled marked in red")
    if not plan_edits():
        sys_prompt += ("\n\nThis server can't edit the plan DXF (walls, windows, doors): only furnish.js, materials.js and the tour. "
                       "If the request needs a wall moved, say so plainly and suggest asking Karim to run Edit AI locally.")
    messages = [{"role": "system", "content": sys_prompt}]
    for h in (req.get("history") or [])[-8:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str):
            messages.append({"role": h["role"], "content": h["text"][:2000]})
    content = [{"type": "text", "text": f"{context_text(ctx)}\n\nRequest: {message}"},
               {"type": "image_url", "image_url": {"url": image, "detail": "high"}}]
    content += [{"type": "image_url", "image_url": {"url": u, "detail": "low"}} for u in refs]
    messages.append({"role": "user", "content": content})
    total, reply, steps = {"prompt_tokens": 0, "completion_tokens": 0, "cached": 0}, "", []
    try:
        for step in range(MAX_STEPS):
            res = openai(messages, first=step == 0)  # look before answering: no "done" without a tool call
            cost(res.get("usage") or {}, total)
            msg = res["choices"][0]["message"]
            messages.append({k: msg[k] for k in ("role", "content", "tool_calls") if msg.get(k) is not None})
            if not msg.get("tool_calls"):
                reply = msg.get("content") or ""
                break
            for call in msg["tool_calls"]:
                name = call["function"]["name"]
                try:
                    out = tool(ws, name, json.loads(call["function"]["arguments"] or "{}"))
                except Exception as e:
                    out = f"error: {type(e).__name__}: {e}"
                steps.append(name)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(out)})
        else:
            reply = "I ran out of steps before finishing; nothing was changed. Try a narrower request."
            ws.changed.clear()
        if not ws.changed and reply and re.search(r"\b(I('ve| have)?|have been) (changed|made|moved|added|removed|replaced|updated|set)\b", reply):
            reply = "Nothing was changed yet: " + reply  # the model claimed an edit it never made
        result = save(ws, reply or message) if ws.changed else None
    finally:
        shutil.rmtree(ws.tmp, ignore_errors=True)
    usd = dollars(total)
    print(f"[edit-ai] {v}: {len(steps)} tool calls, {total['prompt_tokens']} in ({total['cached']} cached) / "
          f"{total['completion_tokens']} out tokens, ${usd}; changed {sorted(ws.changed) or 'nothing'}", flush=True)
    return {"reply": reply or "Done.", "changed": sorted(ws.changed), "rev": result and result["rev"], "model": MODEL,
            "tokens": total, "usd": usd, "steps": len(steps), "sync": result and result.get("sync")}


def save(ws, summary):
    """Make the workspace's changes live: rebuild what the plan needs, store the files, write a revision."""
    for p in SHARED:
        if p in ws.changed and (err := js_check(ws, p)):
            raise RuntimeError(f"the edit left {p} broken, so nothing was saved:\n{err}")
    if ws.plan_dirty or ws.cfg["tour"] in ws.changed:
        rebuild(ws)
    derived_from = ws.cfg["dxf"] if ws.cfg["dxf"] in ws.changed else None
    files = {}
    for path, (status, e, _) in resolve(ws.man).items():  # what stays live from before
        if status in ("live", "replayed"):
            files[path] = e
    for path in ws.changed:
        prev = ws.res.get(path)
        dep = deployed(path)
        data = ws.files[path]
        e = {"sha": sha(data), "url": store(data, path), "base": sha(dep), "base_url": store(dep, path) if dep else None}
        if path.endswith((".js", ".json")) and path in ws.ops and path not in (ws.cfg["model"], ws.cfg["drawing"]):
            e["ops"] = (prev[1].get("ops") or [] if prev and prev[0] in ("live", "replayed") else []) + ws.ops[path]
        if path in (ws.cfg["model"], ws.cfg["drawing"]) and derived_from:
            e["derived"] = derived_from
        if e["sha"] == e["base"]:
            files.pop(path, None)  # back to what is deployed
        else:
            files[path] = e
    return write_rev(ws.v, files, summary, sorted(ws.changed), {p: ws.files[p] for p in ws.changed})


def write_rev(v, files, summary, changed, contents):
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{int(time.time() * 1000) % 1000:03d}"
    rev = f"{stamp}-{secrets.token_hex(3)}"
    prev = revisions(v)
    man = {"version": v, "rev": rev, "parent": prev[-1] if prev else None, "summary": summary[:300],
           "changed": changed, "files": files, "at": int(time.time())}
    put(f"{LIVE}/{v}/rev-{rev}.json", json.dumps(man).encode(), "application/json")
    man["sync"] = git_sync(v, contents, summary)
    return man


def undo(req):
    """Put the version back as it was before its last Edit AI change (a new revision, so it can be redone by hand)."""
    v = req.get("version") or "main"
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    cur = latest(v)
    if not cur or not cur.get("changed"):
        raise ValueError("there is no Edit AI change to undo here")
    before = json.loads(get(cur["parent"])) if cur.get("parent") else None
    res_before = resolve(before)
    files = {p: e for p, (st, e, _) in resolve(cur).items() if st in ("live", "replayed")}
    contents = {}
    for path in cur["changed"]:
        e = cur["files"].get(path)
        if path in res_before and res_before[path][0] in ("live", "replayed"):
            data = live_content(path, res_before[path])
        else:
            # Nothing live before it: back to what is deployed now (not the file the edit started from, which may be
            # older than main and would hide later commits).
            data = deployed(path)
        dep = deployed(path)
        if sha(data) == sha(dep):
            files.pop(path, None)
        else:
            files[path] = {"sha": sha(data), "url": store(data, path), "base": sha(dep), "base_url": store(dep, path) if dep else None}
        contents[path] = data
    man = write_rev(v, files, f"Undo: {cur.get('summary', '')}", sorted(contents), contents)
    return {"rev": man["rev"], "changed": sorted(contents), "sync": man.get("sync")}


def reset(req):
    """Drop every live Edit AI override for a version: it shows exactly what is deployed (a new, empty revision)."""
    v = req.get("version") or "main"
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{int(time.time() * 1000) % 1000:03d}"
    rev = f"{stamp}-{secrets.token_hex(3)}"
    prev = revisions(v)
    man = {"version": v, "rev": rev, "parent": prev[-1] if prev else None, "summary": "Reset to the deployed files",
           "changed": [], "files": {}, "at": int(time.time())}
    put(f"{LIVE}/{v}/rev-{rev}.json", json.dumps(man).encode(), "application/json")
    return {"rev": rev, "changed": []}


# --- Git sync, after the change is already live ----------------------------------------------------------------------
_git_lock = threading.Lock()


def git_token():
    if os.environ.get("EDIT_AI_GITHUB_TOKEN"):
        return os.environ["EDIT_AI_GITHUB_TOKEN"]
    if ON_VERCEL:
        return None
    try:
        return subprocess.run(["gh", "auth", "token", "-u", os.environ.get("EDIT_AI_GITHUB_USER", "karimtaamer")],
                              capture_output=True, text=True, timeout=20).stdout.strip() or None
    except Exception:
        return None


def git_sync(v, contents, summary):
    msg = "Edit AI (%s): %s" % (v, re.sub(r"\s+", " ", summary).strip()[:120])
    if os.environ.get("EDIT_AI_GIT_SYNC", "1") == "0":
        return "off"
    if ON_VERCEL or BLOB:
        if not os.environ.get("EDIT_AI_GITHUB_TOKEN"):
            return "off (no EDIT_AI_GITHUB_TOKEN): live in Blob only"
        try:
            return github_commit(contents, msg)
        except Exception as e:
            print(f"[edit-ai] git sync failed: {e}", flush=True)
            return f"failed: {e}"
    threading.Thread(target=local_commit, args=(contents, msg), daemon=True).start()
    return "committing in the background"


def local_commit(contents, msg):
    with _git_lock:
        try:
            for path, data in contents.items():
                (ROOT / path).write_bytes(data)
            paths = sorted(contents)
            git = ["git", "-C", str(ROOT)]
            run(git + ["add", "--", *paths])
            code, out = run(git + ["commit", "-m", msg, "--", *paths])
            if code:
                print(f"[edit-ai] commit: {out[-400:]}", flush=True)
                return
            tok = git_token()
            auth = ["-c", "credential.helper=", "-c",
                    f"credential.helper=!f() {{ echo username=x-access-token; echo password={tok}; }}; f"] if tok else []
            code, out = run(["git", *auth, "-C", str(ROOT), "pull", "--rebase", "--autostash"], timeout=120)
            code, out = run(["git", *auth, "-C", str(ROOT), "push"], timeout=120)
            print(f"[edit-ai] {'pushed' if not code else 'push failed: ' + out[-400:]}: {msg}", flush=True)
        except Exception as e:
            print(f"[edit-ai] git sync failed: {e}", flush=True)


def gh(method, route, body=None):
    repo = os.environ.get("EDIT_AI_GITHUB_REPO", "karimtaamer/karim-home-3d")
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}{route}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {os.environ['EDIT_AI_GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github+json", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def github_commit(contents, msg):
    branch = os.environ.get("EDIT_AI_GITHUB_BRANCH", "main")
    head = gh("GET", f"/git/ref/heads/{branch}")["object"]["sha"]
    tree = gh("GET", f"/git/commits/{head}")["tree"]["sha"]
    entries = []
    for path, data in contents.items():
        blob = gh("POST", "/git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = gh("POST", "/git/trees", {"base_tree": tree, "tree": entries})["sha"]
    commit = gh("POST", "/git/commits", {"message": msg, "tree": new_tree, "parents": [head]})["sha"]
    gh("PATCH", f"/git/refs/heads/{branch}", {"sha": commit})
    return f"committed {commit[:7]}"


# --- HTTP ---------------------------------------------------------------------------------------------------------------
_hits = defaultdict(deque)


def limited(ip):
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE:
        return True
    q.append(now)
    return False


class Handler(photogen.Handler):
    def edit_action(self):
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path.rstrip("/") == "/api/edit-ai":
            return q.get("action", ["status"])[0], q
        if url.path.startswith("/api/edit-ai/"):
            return url.path.split("/")[3], q
        return None, q

    def do_GET(self):
        act, q = self.edit_action()
        if not act:
            return super().do_GET()
        try:
            if act == "status":
                return self.reply(200, {"ready": bool(api_key()), "model": MODEL})
            if act == "patches":
                return self.reply(200, patches(q.get("version", ["main"])[0]))
        except Exception as e:
            print(f"[edit-ai] {act}: {e}", flush=True)
            return self.reply(400 if isinstance(e, ValueError) else 502, {"error": str(e)})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        act, _ = self.edit_action()
        if not act:
            return super().do_POST()
        routes = {"chat": chat, "undo": undo, "reset": reset}
        if act not in routes:
            return self.reply(404, {"error": "not found"})
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        if act == "chat" and limited(ip):
            return self.reply(429, {"error": f"That's {RATE} edits this hour from here; try again later."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 16_000_000:
                return self.reply(413, {"error": "too much to send at once; fewer or smaller pictures"})
            self.reply(200, routes[act](json.loads(self.rfile.read(n))))
        except PermissionError as e:
            self.reply(503, {"error": str(e), "code": "no-key"})
        except Exception as e:
            print(f"[edit-ai] {act}: {type(e).__name__}: {e}", flush=True)
            self.reply(400 if isinstance(e, (ValueError, KeyError)) else 502, {"error": str(e)})


if __name__ == "__main__":
    port = next((int(a) for a in sys.argv[1:] if a.isdigit()), 8000)
    print(f"Serving http://127.0.0.1:{port}  ·  Edit AI: {MODEL}"
          f"{'' if api_key() else '  (no EDIT_AI_OPENAI_API_KEY: editing is off)'}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
