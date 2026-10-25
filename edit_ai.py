#!/usr/bin/env python3
"""Edit AI: change the flat from inside the viewer, in words, with what's on screen as the picture.

    python3 edit_ai.py [port]     # serves this folder on http://127.0.0.1:8000 with Edit AI and Generate Photo Spot

The page (edit-ai.js) freezes the 3D or 2D view, the user circles what to change (or picks Whole view), says what
they want and may attach reference pictures. POST /api/edit-ai/chat sends that here; an OpenAI chat model with
vision (EDIT_AI_MODEL, default gpt-6-luna; gpt-6.1* / gpt-6-astra go through /v1/responses, key EDIT_AI_OPENAI_API_KEY, kept apart from Generate Photo Spot's
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
import base64, difflib, hashlib, json, math, os, re, secrets, shutil, subprocess, sys, tempfile, threading, time, urllib.error, \
    urllib.parse, urllib.request
from collections import Counter, defaultdict, deque
from http.server import ThreadingHTTPServer
from pathlib import Path

import photogen
import photogen_blob

ROOT = Path(__file__).resolve().parent
LIVE = "edit-ai-live"  # the store's prefix, and the folder here
BLOB = bool(photogen_blob.token())
ON_VERCEL = bool(os.environ.get("VERCEL"))
MODEL = os.environ.get("EDIT_AI_MODEL", "gpt-6-luna")
RATE = int(os.environ.get("EDIT_AI_RATE", "20"))
OPENAI_URL = os.environ.get("EDIT_AI_OPENAI_URL", "https://api.openai.com/v1/chat/completions")  # a test double can stand in
RESPONSES_URL = os.environ.get("EDIT_AI_OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
# Models that only take function tools on /v1/responses (EDIT_AI_API=responses forces it for any model).
RESPONSES_MODELS = ("gpt-6.1", "gpt-6-astra")
# Auto-routing (pick_model): easy edits stay on the cheap model, complex ones go to the strong one.
EASY_MODEL = "gpt-6-luna"
COMPLEX_MODEL = os.environ.get("EDIT_AI_COMPLEX_MODEL", "gpt-6.1-sol")
# Extra models a request may pick with "model" (comma-separated, e.g. for an A/B run); MODEL and both routes always allowed.
ALLOWED_MODELS = {m.strip() for m in os.environ.get("EDIT_AI_MODELS", "").split(",") if m.strip()} | {MODEL, EASY_MODEL, COMPLEX_MODEL}
MAX_STEPS = 36  # tool rounds per message (was 20; hard openable/plan builds were dying early)
MAX_IMAGE = 3_000_000  # bytes of a data URL
MAX_REFS = 4
# USD per million tokens (input, cached input, output), OpenAI list prices; only to tell the user what a message cost.
PRICES = {"gpt-6.1-sol": (2.0, 0.1, 10.0), "gpt-6-luna": (0.1, 0.01, 0.5), "gpt-6-sol": (2.0, 0.2, 10.0), "gpt-5.6-sol": (4.0, 0.4, 20.0), "gpt-4.1": (2.0, 0.5, 8.0), "gpt-4.1-mini": (0.4, 0.1, 1.6), "gpt-4.1-nano": (0.1, 0.025, 0.4),
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
        self.files, self.ops, self.changed, self.orig = {}, defaultdict(list), set(), {}
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
        if path not in self.orig:
            self.orig[path] = self.read(path)
        self.files[path] = data
        self.changed.add(path)
        if op:
            self.ops[path].append(op)

    def discard(self):
        for p in list(self.changed):
            self.files[p] = self.orig.pop(p, self.files.get(p))
            self.ops.pop(p, None)
        self.changed.clear()
        if self.dxf_path:
            self.dxf_path.write_bytes(self.read(self.cfg["dxf"]))
        self.plan_dirty, self.dxf_furni, self.pieces = False, False, {}
        self.clashes, self.new_outlines, self.moves = {}, [], []
        if hasattr(self, "model0"):
            del self.model0

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
    env = None
    if args and args[0] == sys.executable:
        # On Vercel the requirements.txt packages sit on this process's sys.path, not necessarily the child's.
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
        if not os.access(Path.home(), os.W_OK):  # Vercel's home is read-only; ezdxf wants a cache dir
            env["XDG_CACHE_HOME"] = tempfile.gettempdir()
    p = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
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


def js_balance(src):
    """Rough JS sanity check without node: brackets, strings, template literals and comments must balance.
    Returns None when fine, else a short message with the line."""
    stack, i, n, line = [], 0, len(src), 1
    pairs = {")": "(", "]": "[", "}": "{"}
    prev = ""  # last significant char, to tell a regex literal from a division
    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1; i += 1; continue
        if ch in " \t\r":
            i += 1; continue
        if src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                return f"line {line}: comment never closed"
            line += src.count("\n", i, j); i = j + 2; continue
        if ch in "'\"":
            j = i + 1
            while j < n and src[j] != ch:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n":
                    return f"line {line}: string never closed"
                j += 1
            if j >= n:
                return f"line {line}: string never closed"
            i = j + 1; prev = "a"; continue
        if ch == "`":
            stack.append(("`", line)); i += 1
            # scan template text until ` or ${
            while True:
                while i < n and src[i] not in "`$\\":
                    if src[i] == "\n":
                        line += 1
                    i += 1
                if i >= n:
                    return f"line {stack[-1][1]}: template literal never closed"
                if src[i] == "\\":
                    i += 2; continue
                if src[i] == "`":
                    stack.pop(); i += 1; prev = "a"; break
                if src.startswith("${", i):
                    stack.append(("${", line)); i += 2; break
                i += 1
            continue
        if ch == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^" or src[max(0, i - 7):i].rstrip().endswith(("return", "typeof"))):
            j, cls = i + 1, False
            while j < n and (cls or src[j] != "/"):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                elif src[j] == "\n":
                    return f"line {line}: regex never closed"
                j += 1
            i = j + 1; prev = "a"; continue
        if ch in "([{":
            stack.append((ch, line))
        elif ch in ")]":
            if not stack or stack[-1][0] != pairs[ch]:
                return f"line {line}: unexpected '{ch}'" + (f" (open '{stack[-1][0]}' from line {stack[-1][1]})" if stack else "")
            stack.pop()
        elif ch == "}":
            if stack and stack[-1][0] == "${":
                stack.pop()
                # back into the template text
                while True:
                    while i + 1 < n and src[i + 1] not in "`$\\":
                        if src[i + 1] == "\n":
                            line += 1
                        i += 1
                    i += 1
                    if i >= n:
                        return "template literal never closed"
                    if src[i] == "\\":
                        i += 1; continue
                    if src[i] == "`":
                        stack.pop(); prev = "a"; break
                    if src.startswith("${", i):
                        stack.append(("${", line)); i += 1; break
                i += 1; continue
            if not stack or stack[-1][0] != "{":
                return f"line {line}: unexpected '}}'" + (f" (open '{stack[-1][0]}' from line {stack[-1][1]})" if stack else "")
            stack.pop()
        prev = ch if not (ch.isalnum() or ch in "_$.") else "a"
        i += 1
    if stack:
        return f"line {stack[-1][1]}: '{stack[-1][0]}' never closed"
    return None


def version_scope(text, version):
    """Per line of furnish.js: False when the line sits in (or is guarded by) a version branch that doesn't run for
    `version`, True when the version branches around it all do, None when there are none or it can't tell."""
    def ev(cond):
        if "version" not in cond:
            return None
        c = re.sub(r"\[([^\]]*)\]\.includes\(\s*version\s*\)", r"(version in [\1])", cond)
        c = c.replace("!==", " != ").replace("===", " == ").replace("&&", " and ").replace("||", " or ")
        c = re.sub(r"!(?!=)", " not ", c)
        if re.search(r"[A-Za-z_]\w*", re.sub(r'"[^"]*"|\'[^\']*\'|\b(version|and|or|not|in)\b', "", c)):
            return None  # other names in the condition
        try:
            return bool(eval(c, {"__builtins__": {}}, {"version": version}))
        except Exception:
            return None
    out, stack, last, chain = [], [], {}, {}
    for raw in text.splitlines():
        line = re.sub(r"//(?=(?:[^\"'`]|\"[^\"]*\"|'[^']*')*$).*", "", raw)  # drop the comment
        code = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`', lambda m: "_" * len(m.group(0)), line)
        guard = None
        m = re.match(r"\s*if\s*\((.*?)\)\s*[A-Za-z_]", line)  # a one-line guard: if (version === "x") item(... {
        if m and not re.match(r"\s*if\s*\(.*\)\s*\{\s*$", code):
            guard = ev(m.group(1))
        pushed_guard = False
        for j, ch in enumerate(code):
            if ch == "}":
                if stack:
                    last[len(stack)] = stack.pop()
            elif ch == "{":
                head = code[:j]
                mm = re.search(r"\bif\s*\((.*)\)\s*$", head)
                d = len(stack)
                if mm:
                    v = ev(line[mm.start(1):mm.end(1)])  # same positions in the line with its strings
                    if re.search(r"\belse\s+if\s*\(", head):  # runs only if no branch before it did
                        prev = chain.get(d)
                        v = False if prev is True else v if prev is False else (False if v is False else None)
                        chain[d] = True if prev is True or v is True else (False if prev is False and v is False else None)
                    else:
                        chain[d] = v
                    stack.append(v)
                elif re.search(r"\belse\s*$", head):
                    prev = chain.get(d)
                    stack.append(None if prev is None else not prev)
                elif guard is not None and not pushed_guard:  # the guarded call's own block
                    stack.append(guard)
                    pushed_guard = True
                else:
                    stack.append("plain")
        allv = [c for c in stack if c != "plain"] + ([guard] if guard is not None else [])
        out.append(False if False in allv else (True if allv and all(v is True for v in allv) else None))
    return out


CALLS = re.compile(r"\b(?:item|rug|plant|art|ac|sconce|pendant)\(")  # any call, loop bodies too
PLACE = re.compile(r"\b(?:item|rug|plant|art|ac|sconce|pendant)\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)")
RUG = re.compile(r"\brug\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)")
ITEM = re.compile(r"\bitem\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*\"([NSEW])\"")


def loose_replace(text, old, new):
    """`old` matched ignoring each line's indentation and trailing spaces (models often miscount the spaces
    after read_file's line numbers). Returns the new text if exactly one place matches, else None; `new` is
    re-indented by the same amount the match is."""
    lines = old.strip("\n").split("\n")
    if not any(l.strip() for l in lines):
        return None
    rx = re.compile("\n".join(r"[ \t]*" + re.escape(l.strip()) + r"[ \t]*" for l in lines), re.M)
    hits = [m for m in rx.finditer(text) if m.start() == 0 or text[m.start() - 1] == "\n"]
    if len(hits) != 1:
        return None
    m = hits[0]
    ind = lambda l: len(l) - len(l.lstrip(" "))
    first = next(l for l in lines if l.strip())
    delta = ind(text[m.start():m.end()].split("\n")[lines.index(first)]) - ind(first)
    out = []
    for l in new.strip("\n").split("\n"):
        out.append((" " * delta + l) if delta >= 0 else l[min(-delta, ind(l)):])
    return text[:m.start()] + "\n".join(out) + text[m.end():]


NUMV = r"(-?[\d.]+|M\.ceiling)"
SHAPE = {"box": re.compile(r"\bp\.box\(\s*" + r",\s*".join([NUMV] * 4)),
         "face": re.compile(r"\bp\.face\(\s*" + r",\s*".join([NUMV] * 4)),
         "pebble": re.compile(r"\bp\.pebble\(\s*" + r",\s*".join([NUMV] * 4))}


def wall_shapes(lines, i, ceil=2.6):
    """(along0, along1, z0, z1) in plan coords along the wall for the literal p.box / p.face / p.pebble of the
    item( block starting at 1-based line i; [] when it builds through a helper we can't read."""
    m = ITEM.search(lines[i - 1])
    if not m:
        return []
    x, y, f = float(m[1]), float(m[2]), m[3]
    block, depth = [], 0
    for line in lines[i - 1:i + 60]:
        block.append(line)
        depth += line.count("(") - line.count(")")
        if depth <= 0:
            break
    text = "\n".join(block)
    v = lambda t: ceil if t == "M.ceiling" else float(t)
    out = []
    for kind, rx in SHAPE.items():
        for a in rx.finditer(text):
            try:
                n = [v(t) for t in a.groups()]
            except ValueError:
                continue
            l0, l1, z0, z1 = (n[0] - n[2] / 2, n[0] + n[2] / 2, n[1] - n[3] / 2, n[1] + n[3] / 2) if kind == "pebble" else n
            s_, o = {"S": (1, x), "N": (-1, x), "E": (1, y), "W": (-1, y)}[f]
            a0, a1 = sorted((o + s_ * l0, o + s_ * l1))
            out.append((a0, a1, min(z0, z1), max(z0, z1)))
    return out


def placed_lines(ws, text=None):
    """(line no, x, y, line) for each item( x, y / rug( x0, y0 literal that runs for this version."""
    text = ws.text("furnish.js") if text is None else text
    sc = version_scope(text, ws.v)
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if sc[i - 1] is False:
            continue
        for m in PLACE.finditer(line):
            out.append((i, float(m[1]), float(m[2]), line))
            break
    return out


def mat_names(ws):
    return set(re.findall(r"^\s+(\w+)\s*:", ws.text("materials.js"), re.M))


def unknown_mats(ws, text):
    return sorted(set(re.findall(r"\bmat\.(\w+)", text)) - mat_names(ws))


def opening_counts(model_bytes):
    s = model_bytes.decode()
    m = json.loads(s[s.index("{"):s.rindex("}") + 1])
    return Counter(o["kind"] for o in m.get("openings", []))


def js_check(ws, path):
    """Parse a JS module with node when there is one (not on Vercel); None when it parses or can't be checked."""
    node = shutil.which("node")
    if not node:  # Vercel: no node, so at least brackets, strings and comments must balance
        err = js_balance(ws.text(path))
        return f"{path}: {err}" if err else None
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
    {"name": "furniture_near", "description": "furnish.js lines that place an item( x, y, ...) within `radius` m of a plan point, to find the code of a piece you see, "
                                              "plus the plan's furniture outlines (2furni) there, with handles for move_piece / resize_piece.",
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
                                       "add_line {layer,a:[x,y],b:[x,y]}; add_polyline {layer,points,closed}; set_points {handle,points}; "
                                       "move_window {handle (any one Windows line of it), centre_on? (handle of a piece to centre it on, e.g. the bed outline), centre? [x, y or null], dx?, dy?, width?}: moves (and resizes) the whole window and "
                                       "re-cuts the wall faces around it; ALWAYS use it to move or resize a window, never move window lines one by one. "
                                       "move_piece {handle (a furniture outline), dx, dy}: moves that piece's outline and the detail lines drawn inside it "
                                       "(pillows, sheet...), nothing else; ALWAYS use it to move furniture on the plan (a bbox `move` drags neighbouring pieces too). "
                                       "resize_piece {handle, grow? {N?, S?, E?, W?: metres to push that edge out, negative pulls it in; sides left out stay put}, "
                                       "or x_size?, y_size? (new plan extents in m) with anchor? ('N' keeps the north edge, 'SW' a corner; default centre)}: "
                                       "resizes a piece and its details; use it whenever a piece changes size. Prefer grow: \"20 cm bigger all round\" = "
                                       "grow {N:0.2,S:0.2,E:0.2,W:0.2}; \"10 cm wider\" on a piece facing N/S = grow {E:0.05,W:0.05}; no arithmetic. For a target size (\"make it 60 cm wide\") use x_size / y_size instead: it lands inside the piece's free span by itself. "
                                       "Growing keeps a piece inside its free span (walls, the pieces beside it): if its log line says ONLY .. FITS, NO ROOM, "
                                       "could only grow or slid, that is what was done on the plan: make furnish.js match the outline (size and centre; "
                                       "pieces drawn in one loop can each get their own size) and tell the user the size it really got and why. "
                                       "The result lists clashes (a piece now running into a wall or another piece): fix them before answering. "
                                       "move_door {handle (the door's swing ARC), along? (m along its wall, + = +x/+y), dx?/dy?, width? (new leaf width = swing radius, m)}: "
                                       "moves and / or widens a door drawn loose (swing, leaf, jambs) and re-cuts the wall faces so the 3D opening follows; "
                                       "ALWAYS use it for a door, never move, delete or redraw door pieces by hand. "
                                       "The 3D model and the 2D drawing are rebuilt from it when you finish.",
     "parameters": {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}}}, "required": ["ops"]}},
    {"name": "check", "description": "Check the edits so far: JS syntax of furnish.js / materials.js and, if the plan changed, a trial rebuild of the model and drawing.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "discard", "description": "Throw away every edit made for this message (files and plan back to how they were). Call it before "
                                       "answering whenever you can't do what was asked, so nothing half-done is saved.",
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
        if a["old"] and n == 1:
            t = t.replace(a["old"], a["new"])
        elif a["old"] and n == 0 and (t2 := loose_replace(t, a["old"], a["new"])) is not None:
            t = t2  # same lines, only the indentation was off
        else:
            return f"`old` occurs {n} times in {p}; it has to match exactly once. Read the lines again and copy them exactly."
        ws.write(p, t.encode(), {"old": a["old"], "new": a["new"]})
        if p.endswith(".js") and (err := js_check(ws, p)):  # kept, so it can be fixed; saving checks again
            return f"edited, but {p} no longer parses:\n{err}"
        if p == "furnish.js" and (bad := unknown_mats(ws, a["new"])):  # an unknown mat.x renders nothing (or breaks the page)
            return (f"edited, but materials.js has no {', '.join('mat.' + b for b in bad)}: fix it now, using one of: "
                    f"{', '.join(sorted(mat_names(ws)))} (or add the material to materials.js first)")
        if p.endswith(".json"):
            try:
                json.loads(t)
            except ValueError as e:
                return f"edited, but {p} is no longer valid JSON: {e}"
        return f"edited {p}"
    if name == "furniture_near":
        x, y, rad = float(a["x"]), float(a["y"]), float(a.get("radius") or 1.0)
        text = ws.text("furnish.js")
        hidden = sum(1 for i, line in enumerate(text.splitlines(), 1) for m in PLACE.finditer(line)
                     if ((float(m[1]) - x) ** 2 + (float(m[2]) - y) ** 2) ** 0.5 <= rad) 
        pieces, boxes = [], []
        if plan_edits():
            try:
                code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(ws.dxf()), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                               f"--bbox={x - rad},{y - rad},{x + rad},{y + rad}", "--layers=2furni,2 furni", "--limit", "400"], timeout=90)
                for d in json.loads(q).get("entities", []):
                    ps = d.get("points") or []
                    if d["type"] == "LWPOLYLINE" and len(ps) >= 4:
                        xs, ys = [p[0] for p in ps], [p[1] for p in ps]
                        if (max(xs) - min(xs)) * (max(ys) - min(ys)) >= 0.04:
                            boxes.append((min(xs), min(ys), max(xs), max(ys)))
                            pieces.append(f"{d['handle']}: x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
            except Exception:
                pass
        out = []
        for i, px, py, line in placed_lines(ws, text):  # near the point, or standing on a plan outline found here
            near = ((px - x) ** 2 + (py - y) ** 2) ** 0.5 <= rad
            on = any(b[0] - 0.15 <= px <= b[2] + 0.15 and b[1] - 0.15 <= py <= b[3] + 0.15 for b in boxes)
            if near or on:
                out.append(f"furnish.js:{i}: {line.strip()[:240]}")
        res = "\n".join(out[:40]) or "no item( x, y ) literal that near; try grep for the room or the piece's name"
        if hidden > len(out):
            res += f"\n({hidden - len(out)} more near here belong to other versions' branches and don't show in {ws.v}: leave them)"
        if pieces:
            res += "\nPlan furniture outlines here (2furni handle: extent):\n" + "\n".join(pieces[:25])
        return res
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
        args = [dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(ws.dxf()), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                f"--bbox={a['x0']},{a['y0']},{a['x1']},{a['y1']}", "--limit", "120"]
        if a.get("layers"):
            args += [f"--layers={a['layers']}"]
        code, out = run(args, timeout=90)
        return out[:24000]
    if name == "dxf_edit":
        if v == "as-built" and not ws.allow_as_built:
            return "As-built is the survey of the flat as it stands; it can't be edited from another version."
        ops_ = []
        for o in a.get("ops") or []:  # {"move_window": {...}} -> {"op": "move_window", ...}
            if isinstance(o, dict) and "op" not in o and len(o) == 1 and isinstance(next(iter(o.values())), dict):
                k_, v_ = next(iter(o.items()))
                o = {"op": k_, **v_}
            ops_.append(o)
        pm_ = {o.get("handle") for o in ops_ if isinstance(o, dict) and o.get("op") in ("move_piece", "resize_piece")}
        dup_ = [o for o in ops_ if isinstance(o, dict) and o.get("op") == "move" and o.get("handles")
                and set(o["handles"]) <= pm_]
        ops_ = [o for o in ops_ if not any(o is d_ for d_ in dup_)]  # the same piece moved twice in one call
        if not ops_:
            return "no ops given: nothing changed on the plan"
        a = {**a, "ops": ops_}
        for o in ops_:
            if o.get("op") == "add_polyline" and o.get("layer") in ("2furni", "2 furni") and len(o.get("points") or []) >= 4:
                ws.new_outlines.append([pt[:2] for pt in o["points"]])
        out_path = ws.tmp / "plan-next.dxf"
        rugs = {";".join(m_.groups()) for t_ in {ws.text("furnish.js"), (ws.orig.get("furnish.js") or b"").decode()}
                for m_ in RUG.finditer(t_)}
        code, out = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "edit", str(ws.dxf()), str(out_path),
                         f"--origin={ORIGIN[0]},{ORIGIN[1]}", "--soft=" + ";".join(r_.replace(";", ",") for r_ in rugs)],
                        stdin=json.dumps(a["ops"]), timeout=120)
        if code:
            return f"nothing changed: {out[-1500:]}"
        if not hasattr(ws, "model0"):
            ws.model0 = ws.read(ws.cfg["model"])  # the 3D before this message, to spot a lost opening
        out_path.replace(ws.dxf())
        ws.write(ws.cfg["dxf"], ws.dxf().read_bytes())
        ws.plan_dirty = True
        try:
            rep_ = json.loads(out)
            ws.dxf_furni = ws.dxf_furni or rep_.get("furniture_changed", False)
            for pc in rep_.get("pieces_changed", []):
                ws.pieces.setdefault(pc["handle"], pc["old"])
                o_, n_ = pc["old"], pc["new"]
                if not n_ or not o_:  # deleted (or new): nothing moved; a deleted new piece no longer needs checking
                    ws.new_outlines = [q_ for q_ in ws.new_outlines if not o_ or not all(abs(u_ - w_) < 0.005 for u_, w_ in zip(
                        [min(t[0] for t in q_), min(t[1] for t in q_), max(t[0] for t in q_), max(t[1] for t in q_)], o_))]
                    continue
                for k_, pts_ in enumerate(ws.new_outlines):  # a new piece moved / resized afterwards: check where it is now
                    bx_ = [min(q[0] for q in pts_), min(q[1] for q in pts_), max(q[0] for q in pts_), max(q[1] for q in pts_)]
                    if all(abs(u_ - w_) < 0.005 for u_, w_ in zip(bx_, o_)):
                        ws.new_outlines[k_] = [[n_[0], n_[1]], [n_[2], n_[1]], [n_[2], n_[3]], [n_[0], n_[3]]]
                ws.moves.append(((n_[0] + n_[2] - o_[0] - o_[2]) / 2, (n_[1] + n_[3] - o_[1] - o_[3]) / 2))
            for w_ in rep_.get("windows_moved", []):
                if "old_centre" in w_ and w_.get("old_width"):
                    ws.win_moved = getattr(ws, "win_moved", []) + [(*w_["old_centre"][:2], w_["old_width"] / 2 + 0.3)]
                if "old_centre" in w_ and "new_centre" in w_:
                    ws.moves.append((w_["new_centre"][0] - w_["old_centre"][0], w_["new_centre"][1] - w_["old_centre"][1]))
                elif w_.get("old_opening") and w_.get("new_opening"):
                    (a0, a1), (b0, b1) = w_["old_opening"], w_["new_opening"]
                    ws.moves.append(((b0[0] + b1[0] - a0[0] - a1[0]) / 2, (b0[1] + b1[1] - a0[1] - a1[1]) / 2))
            for h_ in rep_.get("clashes_checked", []):
                ws.clashes[h_] = [c_ for c_ in rep_.get("clashes", []) if c_["piece"] == h_]
        except ValueError:
            pass
        try:  # what hangs in a moved window (sheers, curtains) has to follow it in furnish.js
            for w in json.loads(out).get("windows_moved", []):
                if "old_centre" not in w:
                    continue  # a door
                (x, y), half = w["old_centre"], w["old_width"] / 2 + 0.3
                near = tool(ws, "furniture_near", {"x": x, "y": y, "radius": half})
                out += (f"\nfurnish.js items within {half:.2f} m of the window's old centre ({x}, {y}); move any curtain / "
                        f"sheer / blind among them to the new centre {w['new_centre']} (width {w['new_width']} m):\n{near}")
        except ValueError:
            pass
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
                if (lost := lost_openings(ws)):
                    notes.append(lost)
            except Exception as e:
                notes.append(str(e))
        return "\n".join(notes) or ("no syntax problems" if shutil.which("node") else
                                    "no syntax problems found (brackets, strings and templates balance; full JS parse not available here)")
    if name == "discard":
        ws.discard()
        return ("every edit of this message is thrown away; nothing will be saved unless you edit again. If you stop now, tell "
                "the user nothing was changed (don't describe any change as done) and what stopped you")
    return f"unknown tool {name}"


def lost_openings(ws):
    """A warning when the rebuilt 3D has fewer doors or windows than before this message."""
    if not hasattr(ws, "model0") or ws.cfg["model"] not in ws.changed:
        return None
    a, b = opening_counts(ws.model0), opening_counts(ws.read(ws.cfg["model"]))
    gone = {k: a[k] - b[k] for k in a if b[k] < a[k]}
    if not gone:
        return None
    return ("WARNING: the rebuilt 3D lost " + ", ".join(f"{n} {k} opening(s)" for k, n in gone.items())
            + " (a door or window no longer cuts its wall). Unless the user asked to remove it, fix the plan "
              "(move_door / move_window keep openings intact) or call discard. Then reply to the user (don't mention this check).")


# The openable-cabinet rule below follows furnish.js medCabinet (medicine cabinet) and heaterVanity (under-sink
# cabinet), the userData.openable contract in interact.js; the plant rule points at plant() and models/plant-vase.glb.
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
materials (colours, textures) that furnish.js uses by name (mat.whiteLacquer, ...). Use only names that exist there \
(grep materials.js first): an unknown mat.x breaks the 3D.
- item(x, y, facing, build): (x, y) is the middle of the piece's BACK, facing (N/S/E/W) is the way its front looks, \
i.e. away from its wall into the room: a piece on a room's south wall faces "N", on its east wall "W". Inside build, \
local x runs across the piece, y up and z out from its back into the room. A piece against a wall has (x, y) on the \
wall's ROOM-SIDE face: a wall is two face lines ~11 cm apart (dxf_query, layer 1wall) and the right one is the one \
nearer the room's middle (other pieces on that wall in furniture_near show it, e.g. item(2.36, 4.55, "N") = south \
wall face y 4.55). Something "on the wall facing the bed" goes on the wall opposite the headboard, at that face, \
never out in the room. Every NEW piece of furniture or joinery gets its footprint on the plan in the same edit, so \
the user can find and edit it in 2D: one that stands on the floor (table, chair, cabinet) and one fixed to a wall that \
reaches out ~30 cm or more below head height (a wall / fold-down desk, a floating vanity, console or bench, a wall \
bed, a deep wall cabinet). Draw it with dxf_edit add_polyline on 2furni, closed, exactly where the 3D puts it: its back \
edge through (x, y) and its depth out in the facing direction (facing "E" with depth d: x .. x + d; "N": y .. y + d), \
width centred on (x, y); a fold-down piece is drawn at its open depth. Only thin wall-hung things (TV, art, mirrors, \
lights, shallow shelves, paint panels) and parts built inside another piece's item go without. The reverse too: a \
new outline drawn on the plan gets its matching item(...) in furnish.js. A wall-hung thing must not overlap what is already on that \
wall (mirror, shelves, a dressing table's mirror, wardrobe, windows, doors): check furniture_near along the wall and \
slide it along to the free stretch (say so). Before adding or moving a piece, check with \
furniture_near what already stands there and don't overlap it; if the spot is taken, pick the nearest free one and say so. \
Keep the room usable: ~70 cm clear in front of wardrobe / cabinet fronts and door swings, ~60 cm beside the bed, ~80 cm \
walkway from the room's door to the bed and between pieces you walk past; a new chair or table never goes in front of \
the wardrobe doors or in a door's swing, and a freestanding piece (chair, sofa, table) faces into the room or toward \
what it serves (TV, table, window), never its back to the room's middle.
- Keep 3D and 2D together: a piece drawn on the plan (2furni) that you move or resize in furnish.js gets exactly the \
same change in the DXF (furniture_near gives its outline's handle: dxf_edit move_piece / resize_piece), and a DXF \
furniture change gets the same change in furnish.js. Move only the pieces asked for (plus their group, below): \
other neighbours stay unless the user wants them to follow, and then they move in both furnish.js and the DXF. A resize that leaves \
a neighbour overlapping or with an odd gap (bedside tables beside a narrower bed) moves that neighbour too, both views. A wall moved in the DXF must keep \
both faces, close its junctions exactly (snap endpoints to existing ones within 0.1 mm), and the furniture against it \
moves with it in furnish.js.
- Where a NEW piece goes: a place the user names (\"at the foot of the bed\", \"in the corner left of the bed\", \"in the \
kitchen\") wins. Otherwise (\"add X\", \"put X here\") it goes where the user is pointing, because that is where they \
will look for it: at the circled spot (beside it if that exact spot is taken), or in Whole view somewhere inside the \
picture: in the room the camera is in, in front of the camera and inside its field of view (the context below gives \
the view's centre on the floor and its width), on the free floor / wall stretch nearest the view's centre that suits \
the piece. Never put it behind the camera, out of frame or in another room because a spot there looks emptier; if \
nothing in view fits, use the nearest free spot in this room and say where it went.
- Two or more red marks with a move / put / relocate / shift request (\"put it here\", \"move this there\"): it is a \
from -> to move, not two additions. Mark 1 (drawn first) is the piece to move, Mark 2 is where it goes (the context \
below lists each mark). Move that piece (3D line and its plan outline together) to Mark 2, keeping its size and \
orientation (re-face it only if it moves onto a different wall); nothing stays behind at Mark 1. Height: if Mark 2's \
centre hit gives a height ("... m up" on a wall or furniture surface), put the piece at that height, since drawing \
Mark 2 higher or lower IS the user asking for a new height; only if Mark 2 is on the floor / has no useful height keep \
the piece's current height. Never ignore a clear vertical difference between Mark 1 and Mark 2 on a wall.
- \"At the foot of / beside / in front of\" a piece: line the new piece up with that piece's plan outline (centred on \
it unless told otherwise) and set it 5-10 cm off it, not across the room. At the foot of a bed whose headboard faces \
"S" (foot edge at y = F): item(bed centre x, F - 0.05, "S", ...), i.e. the new piece's back toward the bed and its \
depth running away from it; its outline then runs y F - 0.05 - depth .. F - 0.05.
- Groups that belong together: a bed's bedside tables (and the pendants over them) and the rug under it move WITH \
the bed when the bed moves, unless the user says otherwise (\"only the bed\"); say that they followed. rug(x0, y0, x1, \
y1) gives the rug's plan extent directly: to resize a rug, resize_piece grow on its outline and add the same metres \
to those four numbers (x0 - W, y0 - S, x1 + E, y1 + N); a rug may run under furniture but not into a wall: if a side \
hits one, stop that side at the wall face and say so.
- Sizes beside a neighbour: a piece next to the bed (or another piece / a wall) that gets wider grows on its free \
side (grow {{W: ...}} for a bedside table west of the bed), never into its neighbour. If it is already touching what \
the user wants it moved toward, don't move it: say it already touches. pendant(x, y, h): h is the height of the \
lamp's bottom above the floor (raise 20 cm = h + 0.2). Things built inside a loop from the loop variable (the \
pendants over the bedside tables use the tables' x) already follow it: don't touch their other numbers.
- Painting / finishing ONE wall (\"paint the wall behind the bed green\"): the walls themselves aren't in furnish.js, \
so add a thin full-height panel on that wall's room-side face, like the existing feature wall line \
`item(6.15, 2.25, "W", p => p.box(-1.75, 1.75, 0, M.ceiling, 0, 0.012, mat.limewashTaupe))`: width = the wall's \
length inside THIS room only (corner to corner of the room-side face, not into the next room), facing into the \
room; leave window openings clear: box left of the window, box right of it, a strip under it (0..M.sill) and over it \
(M.winHead..M.ceiling), all in local x (along the wall), material from materials.js (add a tinted \
copy of limewash there if no colour fits). Repainting every wall of a room is the same, one panel per wall.
- Height (\"taller\", \"lower\", \"85 cm high\") is 3D only: the plan outline is the footprint and stays as it is. \
A target height is the top of the piece above the floor (\"85 cm high\" = top at 0.85); stretch or shrink the parts \
under the top to suit, and nothing goes below the floor (no box starting under 0).
- Colours and finishes: never change an existing material in materials.js (every piece in every version that uses it \
would change); add a new named one (a tinted copy in the colour asked for, not the nearest existing material) and use it only on \
the pieces asked for. Change the surfaces you \
actually see in the picture (a wardrobe's door leaves and frame, a cabinet's fronts): read the builder and follow \
the branch that runs for this call's arguments; editing a branch that doesn't run changes nothing.
- Replacing a piece (\"replace X with Y\", \"make X round instead\"): the new one takes X's place and size unless told \
otherwise. If X has its own plan outline, that outline becomes Y's footprint; a part built inside another piece's \
item (a stool tucked under a dressing table, a mirror over it) has no outline of its own: leave the host piece and its \
outline alone.
- Shapes in build: p.box(x0, x1, y0, y1, z0, z1) is a block: x across the piece, y0..y1 HEIGHT above the floor, \
z0..z1 out from its back (a seat 45 cm high is y 0.41..0.45; its legs run y 0..0.41); p.cyl(x, z, r, y0, y1) stands upright (a leg, pot, lamp \
base, column); a round disc facing out from the wall (round mirror, clock, plate) is an upright cyl turned: \
p.cyl(x, z + t / 2, r, y - t / 2, y + t / 2, material, 64).rotation.x = Math.PI / 2 (centre at height y, t thick; \
the 2nd argument is how far out from the wall, so it stays small: a 70 cm mirror 1.35 m up on the wall face is \
p.cyl(0.2, 0.006, 0.35, 1.344, 1.356, mat.mirror, 64).rotation.x = Math.PI / 2); \
p.pebble(...) is an organic oval, not a circle. Keep a light / halo the old piece had (a slightly larger disc of \
mat.ledStrip just behind) unless told otherwise.
- Cabinets that open (\"make this cabinet open\", \"put X inside this\", \"open the wardrobe so I can see inside\"): use \
the project's openable pattern (interact.js; copy furnish.js medCabinet / heaterVanity), never a static open niche or \
doors left off. Inside the piece's build: `const c = new THREE.Group(), q = part(c), leaves = []; p.g.add(c);` then the \
carcass AND everything inside it with q (so they sit behind the doors and count as the cabinet). Each door is its own \
group hinged on its outer edge at the front face: `const d = new THREE.Group(); d.position.set(s * h, 0, front); c.add(d); \
part(d).box(s < 0 ? 0 : -h, s < 0 ? h : 0, y0, y1, 0, 0.02, material); leaves.push({{ obj: d, axis: "y", open: s * 100 * \
Math.PI / 180 }});` (s = -1 hinge on the -x side, +1 on the +x side: the free edges swing out; 88 degrees beside a wall; \
a sliding door is {{ obj: d, slide: new THREE.Vector3(dx, 0, 0) }}). Build the doors CLOSED; then `c.userData.openable = \
{{ id: "<unique-kebab-id>", label: "<Name>", leaves, anchor: new THREE.Vector3(0, (y0 + y1) / 2, front + 0.06), reach: 1.8, \
duration: 0.6 }}` (add `peek: 0.95` for a cabinet under counter height). To make an existing cabinet open, keep its \
carcass and turn its door boxes into such leaves. Contents fit the inside: between the side boards, on a shelf or the \
bottom board, from the back panel face to ~3 cm short of the doors; size them for real (a bottled-water dispenser ~30 \
x 35 x 45 cm). Say they open with a tap / E in Walk.
- Plants, greenery, flowers and decor vases are never bare p.cyl stacks. A potted plant or olive-branch vase at a plan \
point: plant(x, y, h, pot, base) (base = the height of the surface it stands on, e.g. plant(x, y, 0.5, 0.065, 1.02) on a \
1.02 shelf; tall floor olive plant(x, y, 1.6, 0.24)). On a shelf / counter inside a build: p.model("models/plant-vase.glb", \
null, x, surfaceTop, z, {{ height: 0.3, cross: true }}) (0.25-0.4 high), as on the dressing table's lit shelf column; bottles \
and toiletries: p.model("models/mbath-bottles.glb", null, x, surfaceTop, z, {{ width: 0.24 }}). Other styling (books, \
bowls, ceramics): copy an existing styled shelf in furnish.js (grep "small books", "vases", "styling") with real \
proportions, two or three pieces spaced along the shelf with room to breathe, not stacked.
- Compass words are plan axes, whatever the view: north = +y (dy > 0), south = -y, east = +x, west = -x. When \
the user names one (\"towards the bed wall (north)\"), move that way.
- Never move or reshape parts of a piece the user didn't name (the bed's pillow lines, a neighbour's outline) just to \
clear an overlap; if what they asked for collides, do the closest that fits and say so.
- \"Left\" / \"right\" / \"behind\" in a 3D view are as seen from the camera (camera position and look point below), \
and in the 2D drawing as on screen (x east = right, y north = up). Convert to plan x / y before editing.
- Windows: move or resize one only with dxf_edit's move_window op (it takes every line of the window and closes / opens the wall faces, so the 3D opening matches the 2D). To centre a window on a piece (e.g. "over the bed"), find the piece's main 2furni outline in dxf_query (the largest closed outline; its "centre" is given) and pass its handle as centre_on, never a hand-worked dx; the result says where the window now runs, so check its centre equals the piece's. Then move what hangs in that window in furnish.js (sheers, curtains, blinds: the edit result lists them) to the window's new centre and width, so the 3D matches.
- Doors: move or widen one only with dxf_edit's move_door op (handle = its swing ARC on 1wall / 3door), which moves \
the swing, leaf and jambs and re-cuts the wall faces so the 3D opening follows. Never delete, redraw or move door \
pieces by hand: that removes the opening from the 3D. A door drawn as a block (INSERT) can't be changed here: say so.
- DXF coordinates in the tools are plan metres (the same frame as furnish.js and the camera numbers below).

Work fast and cheap: find the code with furniture_near / grep around the plan point the user marked, read only the \
lines you need, make the smallest edits that do the job, run `check` once after editing, then answer. Don't re-read \
whole files. If the request is ambiguous, make the most sensible choice and say what you chose. If something truly \
can't be done, call discard (so nothing half-done is saved) and say why; never say you left something unchanged \
while edits are still pending.

The picture: image 1 is the frozen view{marked}. Later images are the user's references (looks to copy, not a plan).

Answer the user in one to three short sentences, plain words, sizes in cm: what you changed and anything they should \
check. No code, no file names unless asked."""


def image_aspect(u):
    """Width / height of a data-URL PNG or JPEG (None if it can't be read)."""
    try:
        b = base64.b64decode(u.split(",", 1)[1][:60000] + "===")
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(b[16:20], "big") / int.from_bytes(b[20:24], "big")
        i = 2
        while i < len(b) - 9:
            if b[i] != 0xFF:
                i += 1
                continue
            mk, ln = b[i + 1], int.from_bytes(b[i + 2:i + 4], "big")
            if 0xC0 <= mk <= 0xCF and mk not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(b[i + 7:i + 9], "big") / int.from_bytes(b[i + 5:i + 7], "big")
            i += 2 + ln
    except Exception:
        pass
    return None


def half_hfov(cam, aspect):
    vf = math.radians(float(cam[6]) if len(cam) > 6 and cam[6] else 60.0)
    return math.degrees(math.atan(math.tan(vf / 2) * (aspect or 1.5)))


def in_ring(ring, px, py):
    hit = False
    for k in range(len(ring)):
        (ax, ay), (bx, by) = ring[k - 1][:2], ring[k][:2]
        if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def view_floor(cam, aspect, rings=None):
    """(x, y, half horizontal FOV) where the middle of a walk view meets the floor (capped at 5 m out, and kept
    inside the room the camera stands in, ~25 cm off its far wall)."""
    try:
        x, y, h, lx, ly, lh = map(float, cam[:6])
    except (TypeError, ValueError):
        return None
    d = math.hypot(lx - x, ly - y)
    if d < 1e-6:
        return None
    t = h / (h - lh) if lh < h else 99
    r = min(d * t, 5.0)
    home = next((g for g in rings or [] if g and in_ring(g, x, y)), None)
    if home:
        k = 0.05
        while k < r and in_ring(home, x + (lx - x) / d * (k + 0.25), y + (ly - y) / d * (k + 0.25)):
            k += 0.05
        r = min(r, k)
    return round(x + (lx - x) / d * r, 2), round(y + (ly - y) / d * r, 2), round(half_hfov(cam, aspect))


def context_text(ctx, aspect=None, rings=None):
    c = ctx or {}
    lines = [f"Screen: {'2D drawing' if c.get('showing') == 'drawing' else '3D model'}"
             + (f", {c.get('mode')} view" if c.get("showing") != "drawing" and c.get("mode") else "")]
    if c.get("room"):
        lines.append(f"Room the camera is in: {c['room']}")
    if c.get("cam"):
        x, y, h, lx, ly, lh, *fov = c["cam"]
        lines.append(f"Camera at plan ({x}, {y}), eye height {h} m, looking toward ({lx}, {ly}, {lh})"
                     + (f", vertical FOV {fov[0]}°" if fov else ""))
        if c.get("mode") in (None, "walk") and (v_ := view_floor(c["cam"], aspect, rings)):
            lines.append(f"Centre of the view meets the floor at about plan ({v_[0]}, {v_[1]}); the picture spans about "
                         f"{v_[2]}° either side of the look direction (anything outside that is out of frame)")
    if c.get("planBox"):
        lines.append(f"Plan area on screen (x0, y0, x1, y1 m): {c['planBox']}")
    ms = marks_of(c)
    surf = lambda h, lead: (f"{lead} plan ({h.get('x')}, {h.get('y')}), {h.get('h')} m up"
                            + (f", material {h['material']}" if h.get("material") else "")
                            + (", a furniture piece" if h.get("furniture") else ", architecture (wall/floor/ceiling)"))
    if len(ms) >= 2:
        lines.append(f"The user drew {len(ms)} separate red marks on image 1, numbered in the order drawn:")
        for m in ms:
            role = "the thing to move / the source" if m["i"] == 1 else "destination" + (f" {m['i'] - 1}" if len(ms) > 2 else "")
            sb = m.get("screenBox")
            where = f" (on screen x {round(sb[0] * 100)}-{round(sb[2] * 100)}%, y {round(sb[1] * 100)}-{round(sb[3] * 100)}% from top-left)" if sb and len(sb) == 4 else ""
            lines.append(f"Mark {m['i']} ({role}){where}:")
            if m.get("planBox"):
                lines.append(f"  plan area (x0, y0, x1, y1 m): {m['planBox']}")
            for k, h in enumerate((m.get("hits") or [])[:6]):
                lines.append(surf(h, "  centre at" if k == 0 else "  also on"))
            if not m.get("planBox") and not m.get("hits"):
                lines.append("  (nothing solid under it)")
        lines.append("Convention: Mark 1 is the thing to move (or the source); Mark 2 and later are where it goes. If the "
                     "request is a move / put / relocate (\"put it here\", \"move this there\"), move the piece at Mark 1 to "
                     "Mark 2 at Mark 2's height (its centre hit's \"m up\") when that hit has one, keeping the current height only "
                     "when Mark 2 doesn't imply one (floor / no height), keep its size and orientation, "
                     "and move its plan outline with it. Don't add a second copy at Mark 2 or treat both marks as \"add here\".")
        return "\n".join(lines)
    if c.get("highlightBox"):
        lines.append(f"Plan area the user circled (x0, y0, x1, y1 m): {c['highlightBox']}")
    for h in (c.get("hits") or [])[:10]:
        lines.append(surf(h, "Circled surface at"))
    lines.append("The user chose Whole view (no circle): the request is about everything in the picture."
                 if c.get("wholeView") else "The user circled the part to change in red on image 1.")
    return "\n".join(lines)


def marks_of(c):
    """The separate red marks the client sent (context.marks, in draw order), cleaned; [] for one mark / Whole view."""
    if (c or {}).get("wholeView"):
        return []
    out = []
    for n, m in enumerate((c or {}).get("marks") or []):
        if isinstance(m, dict) and len(out) < 6:
            out.append({"i": len(out) + 1, "screenBox": m.get("screenBox"), "planBox": m.get("planBox"),
                        "hits": [h for h in (m.get("hits") or []) if isinstance(h, dict)]})
    return out if len(out) >= 2 else []


def mark_point(m):
    """A mark's plan point: its first (centre) hit, or its plan box's centre."""
    for h in m.get("hits") or []:
        if h.get("x") is not None and h.get("y") is not None:
            return float(h["x"]), float(h["y"])
    b = m.get("planBox")
    if b and len(b) == 4:
        return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return None


def check_image(u, what):
    if not isinstance(u, str) or not re.match(r"^data:image/(jpeg|png|webp);base64,", u):
        raise ValueError(f"{what} must be a JPEG, PNG or WebP image")
    if len(u) > MAX_IMAGE:
        raise ValueError(f"{what} is too large (keep it under ~2 MB)")
    return u


def plan_edits():
    """Walls and other DXF edits need the DWG folder, the build scripts and ezdxf + shapely (requirements.txt)."""
    if not ((ROOT / "dwg").is_dir() and (ROOT / "build_geometry.py").exists() and (ROOT / "build_drawing.py").exists()):
        return False
    if dwg_python() != sys.executable:
        return True
    import importlib.util
    return all(importlib.util.find_spec(m) for m in ("ezdxf", "shapely"))


def uses_responses(model):
    return os.environ.get("EDIT_AI_API") == "responses" or model.startswith(RESPONSES_MODELS) or model in _RESPONSES_ONLY


_RESPONSES_ONLY = set()  # models chat/completions turned away with "use /v1/responses" since this process started


def post(url, body):
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
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


def openai(messages, first=False, model=None):
    """One model turn over the chat-completions style history in `messages`; returns a chat-completions style
    result ({"choices": [{"message": ...}], "usage": ...}) whichever API answered."""
    model = model or MODEL
    tools = [t for t in TOOLS if plan_edits() or not t["name"].startswith("dxf_")]
    if not uses_responses(model):
        try:
            return post(OPENAI_URL, {
                "model": model, "messages": messages,
                **({"reasoning_effort": "none"} if model.startswith(("gpt-5", "gpt-6")) else {"temperature": 0.2}),
                **({"tool_choice": "required"} if first else {}),
                "tools": [{"type": "function", "function": t} for t in tools]})
        except RuntimeError as e:
            if "/v1/responses" not in str(e) and "reasoning_effort" not in str(e):
                raise
            _RESPONSES_ONLY.add(model)  # e.g. "function tools ... use /v1/responses": take the other road from now on
    return responses(messages, tools, first, model)


def responses(messages, tools, first, model):
    """The same turn on POST /v1/responses. The history stays in chat-completions shape (so the loop in chat() is
    one loop) and is translated every turn: system -> instructions, text / image_url parts -> input_text /
    input_image, an assistant's tool_calls -> function_call items, role "tool" -> function_call_output. Stateless
    (store false, no previous_response_id): each turn sends the whole conversation, like chat/completions."""
    instructions, items = [], []
    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":
            instructions.append(content)
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m["tool_call_id"], "output": content or ""})
        else:
            if isinstance(content, list):
                parts = []
                for c in content:
                    if c.get("type") == "text":
                        parts.append({"type": "input_text" if role == "user" else "output_text", "text": c["text"]})
                    elif c.get("type") == "image_url":
                        parts.append({"type": "input_image", "image_url": c["image_url"]["url"],
                                      "detail": c["image_url"].get("detail", "auto")})
                items.append({"role": role, "content": parts})
            elif content:
                items.append({"role": role, "content": content})
            for call in m.get("tool_calls") or []:
                items.append({"type": "function_call", "call_id": call["id"], "name": call["function"]["name"],
                              "arguments": call["function"]["arguments"] or "{}"})
    res = post(RESPONSES_URL, {
        "model": model, "instructions": "\n\n".join(instructions) or None, "input": items, "store": False,
        "reasoning": {"effort": os.environ.get("EDIT_AI_REASONING", "low")},
        **({"tool_choice": "required"} if first else {}),
        "tools": [{"type": "function", "name": t["name"], "description": t.get("description", ""),
                   "parameters": t["parameters"]} for t in tools]})
    text, calls = [], []
    for o in res.get("output") or []:
        if o.get("type") == "message":
            text += [c.get("text", "") for c in o.get("content") or [] if c.get("type") == "output_text"]
        elif o.get("type") == "function_call":
            calls.append({"id": o["call_id"], "type": "function",
                          "function": {"name": o["name"], "arguments": o.get("arguments") or "{}"}})
    u = res.get("usage") or {}
    return {"choices": [{"message": {"role": "assistant", "content": "".join(text) or None, "tool_calls": calls or None}}],
            "usage": {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0),
                      "prompt_tokens_details": {"cached_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens", 0)}}}


def cost(usage, total):
    for k in ("prompt_tokens", "completion_tokens"):
        total[k] += usage.get(k, 0)
    total["cached"] += (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)


def dollars(total, model=None):
    model = model or MODEL
    p = next((v for k, v in sorted(PRICES.items(), key=lambda kv: -len(kv[0])) if model.startswith(k)), None)
    if not p:
        return None
    fresh = total["prompt_tokens"] - total["cached"]
    return round((fresh * p[0] + total["cached"] * p[1] + total["completion_tokens"] * p[2]) / 1e6, 4)


# Why route at all: Luna "finished" a fold-down desk between the window and the coffee unit by parking it at the
# wrong wall strip (didn't measure between the two landmarks), finishing it in the wall colour (invisible closed),
# hinging a 2.5 cm strip instead of the front (open showed nothing) and dropping an unrelated plant in the same
# search/replace. New / openable / between-landmarks / plan / multi-part / ref-driven edits therefore go to
# COMPLEX_MODEL up front; plain colour, height, small-move and rename edits stay on EASY_MODEL. Decided here from
# the words alone, before any model call (no Luna-reads-then-escalates, no classifier call).
_COMPLEX_RES = [re.compile(p, re.I) for p in (
    r"\b(add|adding|new|install|build|create)\b", r"\bput (a|an|some|in)\b", r"\bmake (a|an)\b(?! (bit|little|touch|tad)\b)",
    r"\bfold(ing|s|ed)?[- ]?(down|out|away|up)\b", r"\bfold(able|-able)\b", r"\bopenable\b", r"\bput (it |them )?inside\b",
    r"\bmake (it |them )?open", r"\bopen (the |a )?(wardrobe|cabinet|cupboard|closet|door|desk|drawer)", r"\bhinge",
    r"\bbetween\b.+\band\b",
    r"\b(replace[sd]?\b[^.]{0,40}?\bwith|turn\b[^.]{0,40}?\binto|convert)\b",
    r"\b(and then|then also|also)\b",
)]
# Plan edits: a wall / window / door / opening that moves, goes, appears or changes size (not just its colour).
_PLAN_RE = re.compile(r"\b(wall|window|door|doorway|opening|column|partition)s?\b", re.I)
_PLAN_VERB_RE = re.compile(r"\b(move|shift|remove|delete|demolish|knock|widen|narrow|extend|shorten|enlarge|split|cut|close|open up|push|pull)", re.I)
_EASY_RE = re.compile(r"\b(colou?r|paint|finish|tone|shade|darker|lighter|warmer|cooler|matte|gloss|wood|oak|walnut|marble|"
                      r"black|white|grey|gray|beige|blue|green|red|pink|yellow|navy|olive|taller|shorter|higher|lower|height|"
                      r"wider|narrower|bigger|smaller|move|slide|shift|nudge|rename|cm|mm)\b", re.I)


def is_complex_edit(message, refs=()):
    """True when the request needs the strong model (see the fold-desk note above)."""
    m = message or ""
    if refs:
        return True
    if any(r.search(m) for r in _COMPLEX_RES):
        return True
    if _PLAN_RE.search(m) and _PLAN_VERB_RE.search(m) and not re.search(r"\b(colou?r|paint|finish)\b", m, re.I):
        return True
    clauses = [c for c in re.split(r"[.;\n]|,\s*(?:and\s+)?|\band\b", m) if len(c.split()) >= 3]
    if len(m.split()) > 30 and len(clauses) >= 3 and not _EASY_RE.search(m):
        return True  # a long multi-clause ask with nothing that reads as a plain tweak
    return False  # short / ambiguous / colour-height-move-rename only: the cheap model


def pick_model(message, refs=()):
    return COMPLEX_MODEL if is_complex_edit(message, refs) else EASY_MODEL


def chat(req):
    v = req.get("version") or "main"
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    if not api_key():
        raise PermissionError("Edit AI isn't switched on yet: set EDIT_AI_OPENAI_API_KEY (or OPENAI_API_KEY) on the server.")
    model = req.get("model")
    if model and model not in ALLOWED_MODELS:
        raise ValueError(f"model {model!r} isn't allowed here")
    message = (req.get("message") or "").strip()[:4000]
    if not message:
        raise ValueError("Say what you want changed.")
    ctx = req.get("context") or {}
    image = check_image(req.get("image"), "the view")
    refs = [check_image(u, f"reference {i + 1}") for i, u in enumerate((req.get("refs") or [])[:MAX_REFS])]
    if model:
        route = "explicit"  # an A/B pick from the client wins
    else:
        model = pick_model(message, refs)
        route = "complex" if model == COMPLEX_MODEL else "easy"
    ws = Workspace(v)
    ws.allow_as_built = v == "as-built"  # only ever reached from the as-built page itself
    ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = False, False, {}, {}, [], []
    ws.win_moved = []
    sys_prompt = SYSTEM.format(showing="2D drawing" if ctx.get("showing") == "drawing" else "3D model", version=v,
                               marked="" if ctx.get("wholeView") else ", with what the user circled marked in red")
    if not plan_edits():
        sys_prompt += ("\n\nThis server can't edit the plan DXF (walls, windows, doors): only furnish.js, materials.js and the tour. "
                       "If the request needs a wall, window or door moved, say plainly that plan edits are unavailable right now.")
    messages = [{"role": "system", "content": sys_prompt}]
    for h in (req.get("history") or [])[-8:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str):
            messages.append({"role": h["role"], "content": h["text"][:2000]})
    ws.ctx, ws.aspect = ctx, image_aspect(image)
    try:
        sm_ = ws.text(ws.cfg["model"])
        rings_ = [f.get("outer") or [] for f in json.loads(sm_[sm_.index("{"):sm_.rindex("}") + 1]).get("floor", [])]
    except Exception:
        rings_ = []
    content = [{"type": "text", "text": f"{context_text(ctx, ws.aspect, rings_)}\n\nRequest: {message}"},
               {"type": "image_url", "image_url": {"url": image, "detail": "high"}}]
    content += [{"type": "image_url", "image_url": {"url": u, "detail": "low"}} for u in refs]
    messages.append({"role": "user", "content": content})
    total, reply, steps, trace = {"prompt_tokens": 0, "completion_tokens": 0, "cached": 0}, "", [], []
    nudged = 0
    try:
        for step in range(MAX_STEPS):
            res = openai(messages, first=step == 0, model=model)  # look before answering: no "done" without a tool call
            cost(res.get("usage") or {}, total)
            msg = res["choices"][0]["message"]
            messages.append({k: msg[k] for k in ("role", "content", "tool_calls") if msg.get(k) is not None})
            if not msg.get("tool_calls"):
                reply = msg.get("content") or ""
                nudge = None if nudged >= 3 or step >= MAX_STEPS - 3 else review(ws, message, reply)
                if nudge:  # up to two second looks before saving: 2D and 3D out of step, a lost opening, a give-up with edits left
                    nudged += 1
                    trace.append({"tool": "(review)", "args": "", "out": nudge[:700]})
                    messages.append({"role": "user", "content": nudge})
                    continue
                break
            for call in msg["tool_calls"]:
                name = call["function"]["name"]
                try:
                    out = tool(ws, name, json.loads(call["function"]["arguments"] or "{}"))
                except Exception as e:
                    out = f"error: {type(e).__name__}: {e}"
                steps.append(name)
                trace.append({"tool": name, "args": call["function"]["arguments"][:600], "out": str(out)[:700]})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(out)})
            if step == MAX_STEPS - 3 and ws.changed:  # don't lose a finished edit to the step limit
                messages.append({"role": "user", "content": "Only 2 steps left. If your edits are done and the last check "
                                 "passed, reply to the user now (no more tool calls); otherwise call discard and tell the user "
                                 "nothing was changed and what couldn't be finished."})
        else:
            reply = "I ran out of steps before finishing; nothing was changed. Try a narrower request."
            ws.changed.clear()
        if not ws.changed and reply and re.search(r"\b(I('ve| have)?|have been) (changed|made|moved|added|removed|replaced|updated|set)\b", reply):
            reply = "Nothing was changed yet: " + reply  # the model claimed an edit it never made
        result = save(ws, reply or message) if ws.changed else None
    finally:
        shutil.rmtree(ws.tmp, ignore_errors=True)
    usd = dollars(total, model)
    print(f"[edit-ai] {v} ({model}, {route}): {len(steps)} tool calls, {total['prompt_tokens']} in ({total['cached']} cached) / "
          f"{total['completion_tokens']} out tokens, ${usd}; changed {sorted(ws.changed) or 'nothing'}", flush=True)
    return {"reply": reply or "Done.", "changed": sorted(ws.changed), "rev": result and result["rev"], "model": model,
            "route": route, "tokens": total, "usd": usd, "steps": len(steps), "sync": result and result.get("sync"),
            **({"trace": trace} if req.get("debug") else {})}


COMPASS = {"north": re.compile(r"\bnorth(wards?)?\b|شمال", re.I), "south": re.compile(r"\bsouth(wards?)?\b|جنوب", re.I),
           "east": re.compile(r"\beast(wards?)?\b|شرق", re.I), "west": re.compile(r"\bwest(wards?)?\b|غرب", re.I)}
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
GAVE_UP = re.compile(r"\b(couldn'?t|could not|can'?t|cannot|unable|wasn'?t able|not possible|left (it |them |everything )?(as it was|unchanged)|"
                     r"(made|changed) nothing|no changes?( were)? made|didn'?t change)\b", re.I)
REMOVAL = re.compile(r"\b(remove|delete|close|block|wall up|fill in|get rid)\b|شيل|امسح|اقفل|اقفل|سد", re.I)


PLANT = re.compile(r"\bplant\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*(?:,\s*([\d.]+)\s*)?(?:,\s*([\d.]+)\s*)?(?:,\s*([\d.]+))?")


def footprint(txt):
    """What of a furnish.js snippet decides the plan footprint: where items stand (and their builder's arguments) and
    the across / out extents of its boxes and cylinders, leaving heights out. Equal before and after = height / look only."""
    heads = sorted(re.findall(r"\b(?:item|rug)\(([^;]*?)(?:, p =>|\)\s*;|$)", txt, re.M))
    ext = []
    for m in re.finditer(r"\bp\.(box|cyl)\(([^;]*?)\)\s*(?:;|\.|$)", txt, re.M):
        a = [x.strip() for x in m[2].split(",")]
        try:
            if m[1] == "box":
                v = [float(eval(a[k], {"__builtins__": {}}, {})) for k in (0, 1, 4, 5)]
                ext.append((v[0], v[1], v[2], v[3]))
            else:
                x_, z_, r_ = (float(eval(a[k], {"__builtins__": {}}, {})) for k in (0, 1, 2))
                ext.append((x_ - r_, x_ + r_, z_ - r_, z_ + r_))
        except Exception:
            return (heads, txt)  # can't read it: count it as a footprint change
    bb = (round(min(e[0] for e in ext), 3), round(max(e[1] for e in ext), 3), round(min(e[2] for e in ext), 3),
          round(max(e[3] for e in ext), 3)) if ext else None
    return (heads, bb)


def blocked_spot(ws, f0, f1):
    """A note when a newly added floor piece stands in a door's swing or a new pot stands inside another piece."""
    was = set(f0.splitlines())
    feet = [(f"the new plan outline x {round(min(q[0] for q in pts), 2)}..{round(max(q[0] for q in pts), 2)}, "
             f"y {round(min(q[1] for q in pts), 2)}..{round(max(q[1] for q in pts), 2)}",
             (min(q[0] for q in pts), min(q[1] for q in pts), max(q[0] for q in pts), max(q[1] for q in pts)))
            for pts in ws.new_outlines if pts]
    pots = []
    for i, px, py, line in placed_lines(ws, f1):
        m = PLANT.search(line)
        if line in was or not m or (m[5] and float(m[5]) > 0.05):
            continue
        r_ = float(m[4]) / 2 + 0.02 if m[4] else 0.13
        b = (px - r_, py - r_, px + r_, py + r_)
        pots.append((i, line, b))
        feet.append((f"furnish.js line {i} ({line.strip()[:90]})", b))
    try:
        sm = ws.text(ws.cfg["model"])
        swings = json.loads(sm[sm.index("{"):sm.rindex("}") + 1]).get("swings", [])
    except Exception:
        swings = []
    for what, b in feet:
        for sw in swings:
            (hx, hy), r = sw["hinge"], float(sw["r"])
            nx, ny = min(max(hx, b[0]), b[2]), min(max(hy, b[1]), b[3])
            d_ = math.hypot(nx - hx, ny - hy)
            if d_ < r - 0.05:
                cx, cy = (b[0] + b[2]) / 2 - hx, (b[1] + b[3]) / 2 - hy
                k = math.hypot(cx, cy) or 1
                need = r + 0.05 - d_
                return (f"Check the door: {what} stands where the door hinged at plan ({round(hx, 2)}, {round(hy, 2)}) "
                        f"swings ({round(r * 100)} cm leaf), so the door would hit it or the doorway is blocked. The leaf "
                        f"sweeps everything within {round(r, 2)} m of the hinge; the piece's nearest corner is {round(d_, 2)} m "
                        f"from it, so it has to go about {round(need, 2)} m further away (straight away from the hinge that is "
                        f"dx {round(need * cx / k, 2)}, dy {round(need * cy / k, 2)}; or slide it further along its wall). Put it "
                        "on the nearest free stretch clear of the swing in one move (3D line and plan outline together), "
                        "or if nothing fits there, say so.")
    if pots and plan_edits():
        src = ws.tmp / "plan-pots.dxf"
        src.write_bytes(ws.orig.get(ws.cfg["dxf"]) or ws.read(ws.cfg["dxf"]))
        for i, line, b in pots[:3]:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(src), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                           f"--bbox={b[0]},{b[1]},{b[2]},{b[3]}", "--layers=2furni,2 furni", "--limit", "200"], timeout=90)
            try:
                ents = json.loads(q).get("entities", [])
            except ValueError:
                continue
            for d in ents:
                ps = d.get("points") or []
                if d["type"] != "LWPOLYLINE" or len(ps) < 4:
                    continue
                xs, ys = [p_[0] for p_ in ps], [p_[1] for p_ in ps]
                if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 0.04:
                    continue
                if min(xs) + 0.03 < cx < max(xs) - 0.03 and min(ys) + 0.03 < cy < max(ys) - 0.03:
                    return (f"Check the fit: furnish.js line {i} ({line.strip()[:100]}) puts a new floor pot at plan "
                            f"({round(cx, 2)}, {round(cy, 2)}), inside plan piece {d['handle']} (x {min(xs)}..{max(xs)}, "
                            f"y {min(ys)}..{max(ys)}): it would stand inside that piece. Use furniture_near, put it on free "
                            "floor beside the piece (or on top of it with plant's base height if the user wants it there), "
                            "smaller if the gap is tight, and say so.")
    return None


NAMED_PLACE = re.compile(r"\b(at|on|in|by|beside|next to|near|behind|under|above|over|opposite|facing|between|corner|"
                         r"foot|left|right|wall)\b|جنب|فوق|تحت|ورا|قدام|عند|على|في|يمين|شمال", re.I)
POINTED = re.compile(r"\b(here|there|this (spot|place|corner|area|room))\b|هنا|هناك", re.I)


MOVE_ASK = re.compile(r"\b(move|put|place|relocate|shift|bring|take|transfer|carry|here|there)\b|انقل|نقل|حط|هنا|هناك", re.I)


def two_mark_move(ws, message, f0, f1):
    """Once per request: with 2+ marks and a move / put-here ask, a note when no changed placement landed at Mark 2, or a
    new copy went there while the piece at Mark 1 stayed. None when it can't tell (e.g. only local build coords changed)."""
    ms = marks_of(getattr(ws, "ctx", None) or {})
    if len(ms) < 2 or getattr(ws, "move_nudged", False) or not MOVE_ASK.search(message or "") or f0 == f1:
        return None
    a, b = mark_point(ms[0]), mark_point(ms[1])
    if not a or not b or math.hypot(a[0] - b[0], a[1] - b[1]) < 0.5:
        return None
    old = placed_lines(ws, f0)
    was = {l for _, _, _, l in old}
    changed = [(i, px, py, l) for i, px, py, l in placed_lines(ws, f1) if l not in was]
    if not changed:
        return None  # nothing with plan coordinates changed (e.g. a nested part's local numbers): can't judge
    near_b = [t for t in changed if math.hypot(t[1] - b[0], t[2] - b[1]) <= 1.0]
    left = [t for t in old if math.hypot(t[1] - a[0], t[2] - a[1]) <= 0.6 and t[3] in f1.splitlines()]
    fmt = lambda p: f"({round(p[0], 2)}, {round(p[1], 2)})"
    if not near_b:
        ws.move_nudged = True
        i, px, py, l = min(changed, key=lambda t: math.hypot(t[1] - b[0], t[2] - b[1]))
        return (f"Check the move: the user drew two marks and asked to move / put something there. Mark 1 (the piece) is "
                f"around plan {fmt(a)}, Mark 2 (where it goes) around {fmt(b)}, but the nearest line you changed (furnish.js "
                f"line {i}: {l.strip()[:110]}) is at ({px}, {py}), {round(math.hypot(px - b[0], py - b[1]), 1)} m from Mark 2. "
                "Move the piece at Mark 1 to Mark 2 (same size and orientation; match Mark 2's height when Mark 2's hit has "
                "one, otherwise keep its height; plan outline too), "
                "or if you read the marks differently, say how.")
    if len(placed_lines(ws, f1)) > len(old) and left:
        ws.move_nudged = True
        i, px, py, l = left[0]
        return (f"Check the move: the user asked to move the piece at Mark 1 {fmt(a)} to Mark 2 {fmt(b)}. You added a "
                f"new piece at Mark 2, but furnish.js line {i} ({l.strip()[:110]}) still stands at Mark 1. If that is the "
                "piece they meant, move it instead of copying it (remove the original, plan outline too); if it isn't, "
                "leave it and say what you moved.")
    return None


def off_view(ws, message, f0, f1, rings):
    """A note when a newly added piece sits away from where the user pointed (circle, or the picture), else None."""
    c = getattr(ws, "ctx", None) or {}
    cam = c.get("cam") if c.get("showing") != "drawing" and c.get("mode") in (None, "walk") else None
    try:
        sm = ws.text(ws.cfg["model"])
        names = [(f.get("room") or "").strip() for f in json.loads(sm[sm.index("{"):sm.rindex("}") + 1]).get("floor", [])]
    except Exception:
        names = [""] * len(rings)
    def room_of(px, py):
        for n, ring in enumerate(rings):
            hit = False
            for k in range(len(ring)):
                (ax, ay), (bx, by) = ring[k - 1][:2], ring[k][:2]
                if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
                    hit = not hit
            if hit:
                return n
        return -1
    old_pts = [(px, py) for _, px, py, _ in placed_lines(ws, f0)]
    was = set(f0.splitlines())
    added = []
    for i, px, py, line in placed_lines(ws, f1):
        if line in was or any(abs(px - a) < 0.02 and abs(py - b) < 0.02 for a, b in old_pts):
            continue
        m = ITEM.search(line)
        if m:  # stand 15 cm in front of its back, inside the room it faces
            dx, dy = {"N": (0, 0.15), "S": (0, -0.15), "E": (0.15, 0), "W": (-0.15, 0)}[m[3]]
            px, py = px + dx, py + dy
        added.append((i, round(px, 2), round(py, 2), line))
    if not added or len(placed_lines(ws, f1)) <= len(placed_lines(ws, f0)) or len(CALLS.findall(f1)) <= len(CALLS.findall(f0)):  # e.g. a loop unrolled, not an addition
        return None  # nothing new (a move, resize or swap in place)
    named = NAMED_PLACE.search(message) and not POINTED.search(message)
    msg_l = message.lower()
    say = lambda i, line: f"furnish.js line {i} ({line.strip()[:110]})"
    if cam and len(cam) >= 6:
        home = room_of(float(cam[0]), float(cam[1]))
        for i, px, py, line in added[:4]:
            r = room_of(px, py)
            other = names[r] if 0 <= r < len(names) else ""
            if home >= 0 and r >= 0 and r != home and not any(w in msg_l for w in other.lower().split() if len(w) > 3):
                return (f"Check placement: {say(i, line)} puts the new piece in the {other.title() or 'next room'}, but the "
                        f"user is standing in the {names[home].title() or 'room the camera is in'} and didn't name another room. "
                        "Put it in this room, where the user is looking (move the 3D line and its plan outline together), "
                        "and say where it went.")
    if named:
        return None
    if not c.get("wholeView") and (c.get("hits") or c.get("highlightBox")):
        pts = [(float(h["x"]), float(h["y"])) for h in c.get("hits") or [] if h.get("x") is not None and h.get("y") is not None]
        if (b := c.get("highlightBox")) and len(b) == 4:
            pts.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
        for i, px, py, line in added[:4]:
            d = min((math.hypot(px - a, py - b) for a, b in pts), default=0)
            if d > 1.2:
                a, b = min(pts, key=lambda q: math.hypot(px - q[0], py - q[1]))
                return (f"Check placement: the user circled the spot for it around plan ({round(a, 2)}, {round(b, 2)}), but "
                        f"{say(i, line)} puts the new piece at about ({px}, {py}), {round(d, 1)} m away. Put it at the circled "
                        "spot (if that exact spot is taken, the nearest free spot right beside it), 3D line and plan outline "
                        "together, and say where it went.")
        return None
    if cam and len(cam) >= 6:
        x, y = float(cam[0]), float(cam[1])
        hh = half_hfov(cam, getattr(ws, "aspect", None))
        look = math.atan2(float(cam[4]) - y, float(cam[3]) - x)
        vf = view_floor(cam, getattr(ws, "aspect", None), rings)
        for i, px, py, line in added[:4]:
            off = abs((math.degrees(math.atan2(py - y, px - x) - look) + 180) % 360 - 180)
            if math.hypot(px - x, py - y) > 0.4 and off > hh + 10:
                return (f"Check placement: {say(i, line)} puts the new piece at about ({px}, {py}), {round(off)}° off the "
                        f"camera's look direction, so it is out of the picture the user is looking at (the view spans about "
                        f"{round(hh)}° either side{f'; its centre meets the floor near ({vf[0]}, {vf[1]})' if vf else ''}). "
                        "They asked without naming a place, so put it where they can see it: the free floor / wall stretch "
                        "inside the view nearest its centre that suits the piece, in this room (3D line and plan outline "
                        "together), and say where it went.")
    return None


PRIM = re.compile(r"\b[a-z]\w*\.(box|cyl)\(([^;]*?)\)\s*(?:;|\.|,|\)|$)", re.M)  # p.box / p.cyl calls; not the wall SHAPE dict above
BUILDER = re.compile(r"\bitem\(\s*-?[\d.]+\s*,\s*-?[\d.]+\s*,\s*\"[NSEW]\"\s*,\s*\w+\(")


def unplanned(ws, f0, f1, new_items):
    """A note when a new piece in furnish.js (on the floor, or fixed to a wall and reaching out into the room) has no
    plan outline (2furni) under it, or a new plan outline has no 3D piece standing on it, else None."""
    if not plan_edits():
        return None
    cur = ws.tmp / "plan-unplanned.dxf"
    cur.write_bytes(ws.read(ws.cfg["dxf"]))
    def outlines(bx):
        code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(cur), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                       "--bbox=" + ",".join(str(round(v_, 4)) for v_ in bx), "--layers=2furni,2 furni", "--limit", "400"], timeout=90)
        try:
            ents = json.loads(q).get("entities", [])
        except ValueError:
            return []
        return [(min(p_[0] for p_ in d["points"]), min(p_[1] for p_ in d["points"]), max(p_[0] for p_ in d["points"]),
                 max(p_[1] for p_ in d["points"])) for d in ents if d["type"] == "LWPOLYLINE" and len(d.get("points") or []) >= 4]
    num = lambda s: float(eval(s, {"__builtins__": {}}, {}))
    old_pts = [(px, py) for _, px, py, _ in placed_lines(ws, f0)]
    L1 = f1.splitlines()
    for i, line in new_items[:4]:
        m = ITEM.search(line)
        x, y, f = float(m[1]), float(m[2]), m[3]
        if any(abs(x - a) < 0.02 and abs(y - b) < 0.02 for a, b in old_pts):
            continue  # changed in place, not a new piece
        blk, dep = "", 0
        for k in range(i - 1, min(i + 40, len(L1))):
            blk += L1[k] + "\n"
            dep += L1[k].count("(") - L1[k].count(")")
            if dep <= 0:
                break
        ext = []  # (across x0, x1, height y0, out z0, z1) of each shape whose numbers can be read
        for s in PRIM.finditer(blk):
            a = [t.strip() for t in s[2].split(",")]
            try:
                if s[1] == "box":
                    ext.append((num(a[0]), num(a[1]), num(a[2]), num(a[4]), num(a[5])))
                else:
                    cx, cz, r = num(a[0]), num(a[1]), num(a[2])
                    ext.append((cx - r, cx + r, num(a[3]), cz - r, cz + r))
            except Exception:
                continue
        ux, uy = {"S": (1, 0), "N": (-1, 0), "E": (0, 1), "W": (0, -1)}[f]
        fx, fy = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}[f]
        if ext:
            low, deep = min(e[2] for e in ext), max(e[4] for e in ext)
            if not ((low <= 0.05 and deep >= 0.15) or (deep >= 0.3 and low < 1.5)):
                continue  # thin wall-hung (art, TV, lights, shallow shelf, paint panel): no outline
            a0, a1 = min(e[0] for e in ext), max(e[1] for e in ext)
            z0 = max(0.0, min(e[3] for e in ext))
            pts = [(x + ux * u + fx * z, y + uy * u + fy * z) for u in (a0, a1) for z in (z0, deep)]
            b = (min(p_[0] for p_ in pts), min(p_[1] for p_ in pts), max(p_[0] for p_ in pts), max(p_[1] for p_ in pts))
        elif BUILDER.search(blk):  # item(x, y, "S", bed(...)): a builder's piece, size unknown here
            low, deep, b = 0.0, None, (x, y, x, y)
        else:
            continue
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        inside = lambda c: c[0] - 0.05 <= cx <= c[2] + 0.05 and c[1] - 0.05 <= cy <= c[3] + 0.05
        drawn = [[min(q[0] for q in p_), min(q[1] for q in p_), max(q[0] for q in p_), max(q[1] for q in p_)] for p_ in ws.new_outlines if p_]
        if any(inside(c) for c in drawn) or any(inside(c) for c in outlines((b[0] - 0.1, b[1] - 0.1, b[2] + 0.1, b[3] + 0.1))):
            continue
        r3 = lambda v_: round(v_, 3)
        where = (f"x {r3(b[0])}..{r3(b[2])}, y {r3(b[1])}..{r3(b[3])}" if deep is not None else f"its back-centre ({x}, {y})")
        return (f"Check 2D vs 3D: your new furnish.js line {i} ({line.strip()[:120]}) adds a piece that "
                + ("stands on the floor" if low <= 0.05 else f"reaches {round(deep * 100)} cm out from its wall")
                + f", but the plan has no outline for it at {where}, so the user can't find or edit it in 2D. Draw its "
                "footprint now: dxf_edit add_polyline on 2furni, closed, back edge through the item's (x, y), depth out in "
                "its facing direction, width centred on it (a fold-down piece at its open depth). If it is only a thin "
                "wall-hung thing or part of another piece's outline, keep your edit as it is.")
    was = {re.sub(r"\s+", "", l) for l in f0.splitlines()}
    placed = placed_lines(ws, f1)
    for pts in ws.new_outlines[:4]:
        if not pts:
            continue
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        b = (min(xs), min(ys), max(xs), max(ys))
        if (b[2] - b[0]) * (b[3] - b[1]) < 0.04:
            continue  # a detail line (a pillow, a basin), not a piece
        if any(b[0] - 0.15 <= px <= b[2] + 0.15 and b[1] - 0.15 <= py <= b[3] + 0.15 for _, px, py, _ in placed):
            continue
        if any(re.sub(r"\s+", "", l) not in was and re.search(r"for \(const \w+ of \[", l) for l in L1):
            continue  # a new loop of items: its positions aren't literal, leave it to the model
        return (f"Check 2D vs 3D: you drew a new plan outline (2furni, x {round(b[0], 3)}..{round(b[2], 3)}, y "
                f"{round(b[1], 3)}..{round(b[3], 3)}) but no furnish.js item stands on it, so the 3D doesn't have the "
                "piece. Add its item(x, y, facing, build) for this version: back-centre on the outline's wall-side edge, "
                "facing into the room, the outline's width and depth; or remove the outline if it wasn't meant.")
    return None


def review(ws, message, reply):
    """What to point out to the model before its edits are saved, or None."""
    if not ws.changed:
        return None
    if GAVE_UP.search(reply or "") and not re.search(r"\binstead\b|\b(so|but) I(\'ve| have)? (made|set|went|used|put|moved|added|changed|widened|resized)\b", reply or "", re.I):
        return ("You say it couldn't be done, but your edits are still pending and would be saved as they are. If you're "
                "giving up, call discard now and then answer; if the change is in fact done, check it and tell the user "
                "what changed (don't mention this check).")
    if ws.plan_dirty:
        try:
            rebuild(ws)
            ws.plan_dirty = False
        except Exception as e:
            return f"The plan no longer rebuilds ({str(e)[:600]}). Fix it or call discard."
    if (lost := lost_openings(ws)) and not REMOVAL.search(message):
        return lost
    tail = (" Then reply to the user as you normally would, about the change itself compared with how it was before their "
            "request (a piece you added is \"added\", not \"moved\"; don't mention this check).")
    f0 = ws.orig["furnish.js"].decode() if "furnish.js" in ws.orig else ws.text("furnish.js")
    f1 = ws.text("furnish.js")
    # An existing material changed in place: every piece and version using it would change.
    if "materials.js" in ws.changed and "materials.js" in ws.orig:
        m0_, m1_ = ws.orig["materials.js"].decode(), ws.text("materials.js")
        defs = lambda t: {m_[1]: m_[2].strip() for m_ in re.finditer(r"^\s+(\w+)\s*:\s*(.+)$", t, re.M)}
        d0_, d1_ = defs(m0_), defs(m1_)
        hit_ = [k for k in d0_ if k in d1_ and d0_[k] != d1_[k]]
        if hit_:
            uses = len(re.findall(r"\bmat\." + re.escape(hit_[0]) + r"\b", f1))
            return (f"Check the material: you changed the existing material {hit_[0]} in materials.js, which {uses} place(s) in "
                    "furnish.js use (other pieces, other versions). Put it back as it was, add a new material next to it "
                    "(a tinted copy with its own name) and use that only on the piece(s) the user asked about." + tail)
    # A compass direction the user named, and every move went the other way.
    named = {d for d, rx in COMPASS.items() if rx.search(message)}
    if len(named) == 1 and ws.moves:
        d = named.pop()
        ax, sg = {"north": (1, 1), "south": (1, -1), "east": (0, 1), "west": (0, -1)}[d]
        along = [m_[ax] for m_ in ws.moves if abs(m_[ax]) > 0.02]
        if along and all(v_ * sg < 0 for v_ in along):
            return (f"Check the direction: the user said {d}, which is plan {'+' if sg > 0 else '-'}{'y' if ax else 'x'} "
                    f"(north = +y, south = -y, east = +x, west = -x), but what you moved went the opposite way "
                    f"({', '.join(f'{v_:+.2f} m' for v_ in along[:3])} in {'y' if ax else 'x'}). Undo that (call discard) and "
                    "redo it in the direction the user named, in both views." + tail)
    # furnish.js edits that only touch lines which never run for this version.
    if f0 != f1:
        sc0, sc1 = version_scope(f0, ws.v), version_scope(f1, ws.v)
        L0, L1_ = f0.splitlines(), f1.splitlines()
        touched = []
        for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0, L1_, autojunk=False).get_opcodes():
            if tag_ == "equal":
                continue
            touched += [sc1[j] for j in range(j0, j1) if L1_[j].strip()] + [sc0[i] for i in range(i0, i1) if L0[i].strip() and tag_ == "delete"]
        if touched and all(t_ is False for t_ in touched):
            return (f"Check the version: every line you changed in furnish.js sits in a branch that doesn't run for version "
                    f"\"{ws.v}\" (another version's `if (version === ...)` block), so nothing changes in what the user sees. "
                    f"Find the line that builds this piece for \"{ws.v}\" (furniture_near lists only the ones that run here; "
                    "pieces shared by several versions sit after the per-version blocks), put the change there instead "
                    "(split it with a version check if the line serves other versions) and revert the edit you made." + tail)
    def bare(l):  # a line's code, without its trailing // comment or spacing (a comment-only edit isn't a change)
        return re.sub(r"\s+", "", re.sub(r"\s//.*$", "", l))
    now = {bare(l) for l in f1.splitlines()}
    # A plan piece moved / resized: the 3D line(s) standing on it must have changed too.
    for h, b in ws.pieces.items():
        lines = [(i, line) for i, px, py, line in placed_lines(ws, f0)
                 if b[0] - 0.15 <= px <= b[2] + 0.15 and b[1] - 0.15 <= py <= b[3] + 0.15]
        if lines and all(bare(line) in now for _, line in lines):
            return (f"Check 2D vs 3D: you changed plan piece {h} (was x {b[0]}..{b[2]}, y {b[1]}..{b[3]}) but its 3D line(s) in "
                    "furnish.js didn't change: " + "; ".join(f"line {i}: {line.strip()[:160]}" for i, line in lines[:4])
                    + ". Give the 3D piece exactly the same move / resize (for this version only), or put the plan piece "
                      "back if it wasn't meant to change." + tail)
    # A 3D piece moved / resized: the plan outline it stands on must have changed too.
    ops = [o for o in ws.ops.get("furnish.js") or []
           if Counter(NUMBER.findall(o["old"])) != Counter(NUMBER.findall(o["new"]))
           and not (o["new"].startswith(o["old"]) or o["new"].endswith(o["old"]))  # not a pure addition
           and footprint(o["old"]) != footprint(o["new"])]  # height / look only: the plan outline is the footprint
    in_window = lambda px, py: any(abs(px - wx) <= hw and abs(py - wy) <= 0.3 for wx, wy, hw in getattr(ws, "win_moved", []))
    gone = [(i, px, py, line) for i, px, py, line in placed_lines(ws, f0)
            if bare(line) not in now and not in_window(px, py) and any(len(seg.strip()) > 8 and seg.strip() in line for o in ops for seg in o["old"].splitlines())]
    if gone and plan_edits():
        src = ws.tmp / "plan-before.dxf"
        src.write_bytes(ws.orig.get(ws.cfg["dxf"]) or ws.read(ws.cfg["dxf"]))
        for i, px, py, line in gone:
            code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(src), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                           f"--bbox={px - 0.05},{py - 0.05},{px + 0.05},{py + 0.05}", "--layers=2furni,2 furni", "--limit", "400"],
                          timeout=90)
            try:
                ents = json.loads(q).get("entities", [])
            except ValueError:
                continue
            hits = []
            for d in ents:
                ps = d.get("points") or []
                if d["type"] == "LWPOLYLINE" and len(ps) >= 4 and d["handle"] not in ws.pieces:
                    xs, ys = [p[0] for p in ps], [p[1] for p in ps]
                    if min(xs) - 0.15 <= px <= max(xs) + 0.15 and min(ys) - 0.15 <= py <= max(ys) + 0.15 \
                            and (max(xs) - min(xs)) * (max(ys) - min(ys)) >= 0.04:
                        hits.append((d["handle"], [min(xs), min(ys), max(xs), max(ys)]))
            if hits:
                h, bb = min(hits, key=lambda t: (t[1][2] - t[1][0]) * (t[1][3] - t[1][1]))
                return (f"Check 2D vs 3D: you changed furnish.js line {i} ({line.strip()[:120]}) but the plan outline it stands on, "
                        f"{h} (x {bb[0]}..{bb[2]}, y {bb[1]}..{bb[3]}), didn't change. If you moved or resized that piece, give "
                        "the outline exactly the same change now with dxf_edit move_piece / resize_piece; if only its look "
                        "or height changed (colour, finish, doors, taller / lower: the outline is the footprint), keep your "
                        "3D edit as it is: you're done, reply to the user." + tail)
    was = {bare(l) for l in f0.splitlines()}  # only lines that stood before this message (not the model's own new piece)
    loop_ops = [o for o in ops if any(re.search(r"\bfor \(const|\bitem\(|\brug\(", l) and bare(l) in was
                                      and bare(l) not in {bare(n_) for n_ in o["new"].splitlines()}
                                      for l in o["old"].splitlines())]
    if loop_ops and not ws.dxf_furni and not gone:
        return ("Check 2D vs 3D: you moved or resized furniture in furnish.js but nothing on the plan (2furni). If the "
                "piece is drawn on the plan (furniture_near lists the outlines there), give its outline exactly the same "
                "change now with dxf_edit move_piece / resize_piece; things not drawn on the plan, and changes of height or "
                "look only (taller, lower, colour: the outline is the footprint), need nothing: keep your 3D edit as it is, "
                "you're done, reply to the user." + tail)
    # A new piece on a wall overlapping (along the wall and in height) what already stands / hangs there.
    if f1 != f0:
        L1, old_lines, cl = f1.splitlines(), set(f0.splitlines()), 2.6
        on_wall = [(i, ITEM.search(l)) for i, _, _, l in placed_lines(ws, f1) if ITEM.search(l)]
        for i, m in on_wall:
            if L1[i - 1] in old_lines:
                continue
            mine = wall_shapes(L1, i, cl)
            if not mine:
                continue
            blk, dep = "", 0
            for k in range(i - 1, min(i + 40, len(L1))):
                blk += L1[k] + "\n"
                dep += L1[k].count("(") - L1[k].count(")")
                if dep <= 0:
                    break
            if re.search(r"p\.box\([^()]*,\s*0(?:\.0+)?\s*,\s*M\.ceiling\s*,\s*-?0(?:\.0+)?\s*,\s*0\.0[0-4]\d*\s*,", blk):
                continue  # a paint / cladding panel: it runs behind what stands on the wall (its own check is below)
            fa, back = m[3], float(m[2] if m[3] in "NS" else m[1])
            for j, m2 in on_wall:
                if j == i or L1[j - 1] not in old_lines or m2[3] != fa or abs(float(m2[2] if fa in "NS" else m2[1]) - back) > 0.08:
                    continue
                theirs = wall_shapes(L1, j, cl)
                hit = [(a, b) for a in mine for b in theirs
                       if min(a[1], b[1]) - max(a[0], b[0]) > 0.03 and min(a[3], b[3]) - max(a[2], b[2]) > 0.03]
                if hit:
                    a, b = hit[0]
                    ax2 = "x" if fa in "NS" else "y"
                    spans = sorted({(round(min(t[0] for t in wall_shapes(L1, k, cl)), 2), round(max(t[1] for t in wall_shapes(L1, k, cl)), 2))
                                    for k, m3 in on_wall if k != i and m3[3] == fa and wall_shapes(L1, k, cl)
                                    and abs(float(m3[2] if fa in "NS" else m3[1]) - back) <= 0.08})
                    return (f"Check the wall: your new furnish.js line {i} ({L1[i - 1].strip()[:100]}) spans plan {ax2} "
                            f"{round(a[0], 2)}..{round(a[1], 2)} at height {round(a[2], 2)}..{round(a[3], 2)}, which runs into line {j} "
                            f"({L1[j - 1].strip()[:100]}) at {ax2} {round(b[0], 2)}..{round(b[1], 2)}, height {round(b[2], 2)}.."
                            f"{round(b[3], 2)} on the same wall. Taken stretches of this wall ({ax2}): {spans}. Move it along to a free "
                            "stretch (make it smaller if none is wide enough, and say so), with its plan outline to match." + tail)
    # Parts of another piece (a bed's pillow lines) moved on their own, or "at the foot of the bed" not at its foot.
    def outlines_before(bx):
        src = ws.tmp / "plan-before2.dxf"
        src.write_bytes(ws.orig.get(ws.cfg["dxf"]) or ws.read(ws.cfg["dxf"]))
        code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(src), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                       "--bbox=" + ",".join(str(round(v_, 4)) for v_ in bx), "--layers=2furni,2 furni", "--limit", "400"], timeout=90)
        try:
            ents = json.loads(q).get("entities", [])
        except ValueError:
            return []
        out = []
        for d in ents:
            ps = d.get("points") or []
            if d["type"] == "LWPOLYLINE" and len(ps) >= 4:
                xs, ys = [p_[0] for p_ in ps], [p_[1] for p_ in ps]
                out.append((d["handle"], (min(xs), min(ys), max(xs), max(ys))))
        return out
    rug_boxes = [tuple(float(v_) for v_ in m_.groups()) for m_ in RUG.finditer(f0)]
    is_rug = lambda c_: any(all(abs(c_[k] - r_[k]) < 0.05 for k in range(4)) for r_ in rug_boxes)
    if ws.pieces:
        for h, b in list(ws.pieces.items())[:6]:
            for h2, c in outlines_before((b[0] - 0.05, b[1] - 0.05, b[2] + 0.05, b[3] + 0.05)):
                if h2 != h and h2 not in ws.pieces and not is_rug(c) and (c[2] - c[0]) * (c[3] - c[1]) > 2 * (b[2] - b[0]) * (b[3] - b[1]) + 0.05 \
                        and c[0] - 0.01 <= b[0] and b[2] <= c[2] + 0.01 and c[1] - 0.01 <= b[1] and b[3] <= c[3] + 0.01:
                    return (f"Check the plan: you moved or resized {h} (x {round(b[0], 3)}..{round(b[2], 3)}, y {round(b[1], 3)}.."
                            f"{round(b[3], 3)}), which is a part drawn inside piece {h2} (x {round(c[0], 3)}..{round(c[2], 3)}, y "
                            f"{round(c[1], 3)}..{round(c[3], 3)}, e.g. a bed's pillow line) while {h2} itself stayed. Don't move parts "
                            f"of a piece the user didn't ask about: call discard and redo the change without touching {h} (if the "
                            "piece the user meant already touches its neighbour, say so instead of forcing it)." + tail)
    if re.search(r"\bfoot of (the |my )?bed|\bend of (the |my )?bed|رجل السرير|اخر السرير|آخر السرير", message, re.I) and ws.new_outlines:
        beds = [(i, px, py, l) for i, px, py, l in placed_lines(ws, f1) if re.search(r"\bbed\(", l) and ITEM.search(l)]
        if beds:
            i, px, py, l = beds[0]
            fb = ITEM.search(l)[3]
            hold = [c for h2, c in outlines_before((px - 0.05, py - 0.05, px + 0.05, py + 0.05))
                    if c[0] - 0.05 <= px <= c[2] + 0.05 and c[1] - 0.05 <= py <= c[3] + 0.05]
            if hold:
                c = max(hold, key=lambda c_: (c_[2] - c_[0]) * (c_[3] - c_[1]))
                foot, sgn = {"S": (c[1], -1), "N": (c[3], 1), "E": (c[2], 1), "W": (c[0], -1)}[fb]
                for pts in ws.new_outlines:
                    xs, ys = [q_[0] for q_ in pts], [q_[1] for q_ in pts]
                    near = {"S": max(ys), "N": min(ys), "E": min(xs), "W": max(xs)}[fb]
                    gap = (near - foot) * sgn
                    if gap > 0.15 or gap < -0.01:
                        ax2 = "y" if fb in "NS" else "x"
                        return (f"Check the placement: the user asked for it at the foot of the bed, whose foot edge is at {ax2} "
                                f"{round(foot, 3)}, but your new outline's near edge is at {ax2} {round(near, 3)} ({round(abs(gap) * 100)} cm "
                                f"{'away from' if gap > 0 else 'inside'} the bed). Set it 5-10 cm off the foot (near edge at {ax2} "
                                f"{round(foot + sgn * 0.05, 3)}), in 3D and on the plan, sitting over the rug end is fine." + tail)
    # A resized / moved plan piece: a new or changed item line standing on it sits at the middle of its back.
    if ws.pieces:
        cur_ = ws.tmp / "plan-pieces.dxf"
        cur_.write_bytes(ws.read(ws.cfg["dxf"]))
        old_lines = set(f0.splitlines())
        for h, b0 in list(ws.pieces.items())[:4]:
            code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(cur_), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                           f"--bbox={b0[0] - 1},{b0[1] - 1},{b0[2] + 1},{b0[3] + 1}", "--layers=2furni,2 furni", "--limit", "400"],
                          timeout=90)
            try:
                ent = next((d for d in json.loads(q).get("entities", []) if d["handle"] == h), None)
            except ValueError:
                ent = None
            ps = (ent or {}).get("points") or []
            if len(ps) < 4:
                continue
            xs, ys = [p_[0] for p_ in ps], [p_[1] for p_ in ps]
            b = (min(xs), min(ys), max(xs), max(ys))
            if (b[2] - b[0]) * (b[3] - b[1]) < 0.04:
                continue
            for i, px, py, line in placed_lines(ws, f1):
                im = ITEM.search(line)
                if not im or line in old_lines or not (b[0] - 0.05 <= px <= b[2] + 0.05 and b[1] - 0.05 <= py <= b[3] + 0.05):
                    continue
                f = im[3]
                edge = {"E": b[0], "W": b[2], "N": b[1], "S": b[3]}[f]
                at, pos, mid, ax2 = (px, py, (b[1] + b[3]) / 2, "y") if f in "EW" else (py, px, (b[0] + b[2]) / 2, "x")
                if abs(at - edge) <= 0.05 and abs(pos - mid) > 0.03:
                    return (f"Check 2D vs 3D: plan piece {h} now runs x {round(b[0], 3)}..{round(b[2], 3)}, y {round(b[1], 3)}.."
                            f"{round(b[3], 3)} (middle of its back at {ax2} {round(mid, 3)}), but furnish.js line {i} "
                            f"({line.strip()[:120]}) puts the 3D piece's back-centre at {ax2} {pos}. item()'s x, y is the middle "
                            f"of the back, so a piece resized on one side moves its centre by half the change: set it to "
                            f"{round(mid, 3)} (or change the outline to match)." + tail)
            # The same for pieces placed from a loop: for (const x of [2.02, 4.35]) { item(x, 9.015, "S", ...) }
            L1b = f1.splitlines()
            for k, line in enumerate(L1b):
                lm = re.search(r"for \(const (\w+) of \[([-\d.,\s]+)\]\)", line)
                if not lm or bare(line) in was:
                    continue
                for nxt in L1b[k + 1:k + 4]:
                    im = re.search(r"\bitem\(\s*" + lm[1] + r"\s*,\s*(-?[\d.]+)\s*,\s*\"([NSEW])\"", nxt)
                    if not im:
                        continue
                    f, at = im[2], float(im[1])
                    if f not in "NS" or abs(at - {"N": b[1], "S": b[3]}[f]) > 0.05:
                        continue
                    mid = (b[0] + b[2]) / 2
                    vals = [float(v_) for v_ in lm[2].split(",") if v_.strip()]
                    near_ = min(vals, key=lambda v_: abs(v_ - mid))
                    if abs(near_ - mid) > 0.03 and b[0] <= near_ <= b[2] and b[2] - b[0] < 1.2:
                        return (f"Check 2D vs 3D: plan piece {h} now runs x {round(b[0], 3)}..{round(b[2], 3)} (middle of its back "
                                f"at x {round(mid, 3)}), but furnish.js line {k + 1} ({line.strip()[:100]}) puts the 3D piece at "
                                f"x {near_}. Make them the same: set that value to {round(mid, 3)}, or move the outline to match "
                                "(if the piece can't move as asked, put both back and say why)." + tail)
    # A plan piece that now runs into a wall or another piece.
    hits = [c for cs in ws.clashes.values() for c in cs]
    if any(not c.get("free") for c in hits):
        free = [f"{c['piece']}: {c['free']}" for c in hits if c.get("free")]
        hits = [c for c in hits if not c.get("free")]
        desc = "; ".join(f"{c['piece']} overlaps {c['with']} at x {c['overlap'][0]}..{c['overlap'][2]}, "
                         f"y {c['overlap'][1]}..{c['overlap'][3]}" for c in hits[:4])
        if free:
            desc += (" (" + "; ".join(free) + ": a piece wider than its free span can't fit there as asked; then "
                     "make it as big as fits: its outline exactly fills that span (resize_piece x_size/y_size = the span, then move_piece so "
                     "its edges sit on the span ends), with the same size and centre in furnish.js; or move the neighbour if the "
                     "user would expect that; and say so)")
        return ("Check the fit: on the plan " + desc + ". A real piece can't go into a wall or through another piece. "
                "Fix it in both views the same way: shift or size the piece so it fits (dxf_edit move_piece / "
                "resize_piece with grow, and the furnish.js line to match), or, if the user would expect the neighbour to "
                "make room, move that too in both views. If it really can't fit as asked, do the closest that fits and say "
                "so." + tail)
    # A new / moved wall piece standing on the far face of its wall (its front would be inside the wall).
    new_items = [(i, line) for i, _, _, line in placed_lines(ws, f1) if line not in set(f0.splitlines()) and ITEM.search(line)]
    try:
        sm = ws.text(ws.cfg["model"])
        rings = [f.get("outer") or [] for f in json.loads(sm[sm.index("{"):sm.rindex("}") + 1]).get("floor", [])]
    except Exception:
        rings = []
    def ring_at(px, py):
        for n, ring in enumerate(rings):
            hit = False
            for k in range(len(ring)):
                (ax, ay), (bx, by) = ring[k - 1][:2], ring[k][:2]
                if (ay > py) != (by > py) and px < ax + (py - ay) * (bx - ax) / (by - ay):
                    hit = not hit
            if hit:
                return n
        return -1
    on_floor = lambda px, py: ring_at(px, py) >= 0
    try:
        mj_ = json.loads(sm[sm.index("{"):sm.rindex("}") + 1])
        sill, win_head, ceil_h = float(mj_.get("sill") or 0.9), float(mj_.get("winHead") or 2.1), float(mj_.get("ceiling") or 2.6)
        wins = [o["outer"] for o in json.loads(sm[sm.index("{"):sm.rindex("}") + 1]).get("openings", [])
                if o.get("kind") == "window" and o.get("outer")]
    except Exception:
        wins, sill, win_head, ceil_h = [], 0.9, 2.1, 2.6
    if (blk_ := blocked_spot(ws, f0, f1)):  # a new floor piece in a door's swing, or a pot inside another piece
        return blk_ + tail
    if rings and (off := off_view(ws, message, f0, f1, rings)):  # a new piece where the user isn't looking
        return off + tail
    if (mv_ := two_mark_move(ws, message, f0, f1)):  # "put it here" with two marks, and nothing went to Mark 2
        return mv_ + tail
    for i, line in new_items[:4]:  # its front has to look into a room, not out of the flat
        m = ITEM.search(line)
        x, y, f = float(m[1]), float(m[2]), m[3]
        dx_, dy_ = {"N": (0, 0.3), "S": (0, -0.3), "E": (0.3, 0), "W": (-0.3, 0)}[f]
        if rings and not on_floor(x + dx_, y + dy_) and on_floor(x - dx_, y - dy_):
            opp = {"N": "S", "S": "N", "E": "W", "W": "E"}[f]
            return (f"Check placement: furnish.js line {i} ({line.strip()[:120]}) faces \"{f}\", but 30 cm in front of it "
                    f"is outside the flat: it is on the outer face of its wall, looking out. Put its back on the wall's "
                    f"room-side face (dxf_query 1wall: the face line nearer the room, ~11-25 cm in) and face it \"{opp}\"; "
                    "for a facing flip, local x runs the other way, so mirror any x offsets inside build." + tail)
    for i, line in new_items[:4]:  # a free-standing piece the wrong way round: back to the room, front at a wall
        m = ITEM.search(line)
        x, y, f = float(m[1]), float(m[2]), m[3]
        fx, fy = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}[f]
        L1, blk, dep = f1.splitlines(), "", 0
        for k in range(i - 1, min(i + 40, len(L1))):
            blk += L1[k] + "\n"
            dep += L1[k].count("(") - L1[k].count(")")
            if dep <= 0:
                break
        zs = [float(b_[1]) for b_ in re.finditer(r"p\.box\([^()]*?,[^(),]*,\s*0(?:\.0+)?\s*,[^(),]*,[^(),]*,\s*(-?[\d.]+)\s*,", blk)]
        if not rings or not zs:
            continue  # nothing standing on the floor
        d_ = max(zs)
        home = ring_at(x + fx * d_ / 2, y + fy * d_ / 2)
        if home >= 0 and ring_at(x - fx * 0.12, y - fy * 0.12) == home and ring_at(x + fx * (d_ + 0.35), y + fy * (d_ + 0.35)) != home:
            opp = {"N": "S", "S": "N", "E": "W", "W": "E"}[f]
            return (f"Check facing: furnish.js line {i} ({line.strip()[:110]}) faces \"{f}\" with its back out in the room "
                    f"and its front less than 35 cm from the wall ahead of it, so its front / controls face the wall. "
                    f"Turn it round: back on that wall's room-side face, facing \"{opp}\" (local x runs the other way, so "
                    "mirror x offsets inside build), with its plan outline to match." + tail)
    PANEL = re.compile(r"p\.box\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*([\w.]+)\s*,\s*([\w.]+)\s*,\s*-?0(?:\.0+)?\s*,\s*(0\.0[0-4]\d*)")
    for i, line in new_items[:4]:  # a paint / cladding panel stays on this room's wall and leaves the windows open
        m = ITEM.search(line)
        x, y, f = float(m[1]), float(m[2]), m[3]
        ux, uy = {"S": (1, 0), "N": (-1, 0), "E": (0, 1), "W": (0, -1)}[f]
        fx, fy = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}[f]
        L1, blk, dep = f1.splitlines(), "", 0
        for k in range(i - 1, min(i + 40, len(L1))):  # the item's whole call, which may span lines
            blk += L1[k] + "\n"
            dep += L1[k].count("(") - L1[k].count(")")
            if dep <= 0:
                break
        boxes = [(float(b_[1]), float(b_[2]), b_[4], b_[3]) for b_ in PANEL.finditer(blk) if float(b_[2]) - float(b_[1]) > 0.3]
        if not boxes or not rings:
            continue
        full = lambda bx: bx[3] in ("0", "0.0") and (bx[2] == "M.ceiling" or (re.fullmatch(r"[\d.]+", bx[2]) and float(bx[2]) >= ceil_h - 0.1))
        if not any(full(bx) for bx in boxes):
            continue  # no floor-to-ceiling box: a TV, shelf or headboard on the wall, not a paint / cladding panel
        home = ring_at(x + fx * 0.05, y + fy * 0.05)
        if home < 0:
            continue
        span_ = []
        for sgn in (-1, 1):  # how far this room's face of the wall runs each way
            t = 0.0
            while abs(t) < 12 and ring_at(x + ux * (t + sgn * 0.02) + fx * 0.05, y + uy * (t + sgn * 0.02) + fy * 0.05) == home:
                t += sgn * 0.02
            span_.append(round(t, 2))
        w0, w1 = span_
        ax_ = "x" if ux else "y"
        pl = lambda t: round((x if ux else y) + t * (ux + uy), 3)  # local x along the wall -> plan coordinate
        rng = lambda a_, b_: f"{min(pl(a_), pl(b_))}..{max(pl(a_), pl(b_))}"
        problems = []
        hv = {"M.sill": sill, "M.winHead": win_head, "M.ceiling": ceil_h, "0": 0.0}
        hnum = lambda v: hv.get(v, float(v) if re.fullmatch(r"-?[\d.]+", v) else None)
        for a_, b_, top, z0_ in boxes:
            if a_ < w0 - 0.03 or b_ > w1 + 0.03:
                problems.append(f"box {a_}..{b_} covers plan {ax_} {rng(a_, b_)}, past this room's face of the wall, "
                                f"which runs plan {ax_} {rng(w0, w1)} (beyond is the next wall or room)")
            for wo in wins:  # window on this wall: close to the back line, overlapping along it
                ds = [(px - x) * fx + (py - y) * fy for px, py in wo]
                ts = [(px - x) * ux + (py - y) * uy for px, py in wo]
                if min(ds) < 0.05 and max(ds) > -0.6 and min(ts) < min(b_, w1) - 0.05 and max(ts) > max(a_, w0) + 0.05 and (hnum(top) or 9) > sill + 0.02 and (hnum(z0_) or 0) < win_head - 0.02:
                    problems.append(f"box {a_}..{b_} (plan {ax_} {rng(a_, b_)}) covers the window at plan {ax_} "
                                    f"{rng(min(ts), max(ts))}")
        wspans = [(min(ts), max(ts)) for wo in wins
                  for ds in [[(px - x) * fx + (py - y) * fy for px, py in wo]]
                  for ts in [[(px - x) * ux + (py - y) * uy for px, py in wo]] if min(ds) < 0.05 and max(ds) > -0.6]
        sg_, o_ = ux + uy, (x if ux else y)
        for i2, line2 in new_items:  # the same paint job split over several items on this wall counts as one
            m2 = ITEM.search(line2)
            if i2 == i or m2[3] != f or abs(float(m2[2] if f in "NS" else m2[1]) - (y if f in "NS" else x)) > 0.03:
                continue
            o2, blk2, dep2 = float(m2[1] if f in "NS" else m2[2]), "", 0
            for k in range(i2 - 1, min(i2 + 40, len(L1))):
                blk2 += L1[k] + "\n"
                dep2 += L1[k].count("(") - L1[k].count(")")
                if dep2 <= 0:
                    break
            for b_ in PANEL.finditer(blk2):
                a2, c2 = sorted(((o2 + sg_ * float(b_[1]) - o_) * sg_, (o2 + sg_ * float(b_[2]) - o_) * sg_))
                boxes.append((a2, c2, b_[4], b_[3]))
        lo_b, hi_b = min(bx[0] for bx in boxes), max(bx[1] for bx in boxes)
        for q1 in range(len(boxes)):  # two coats on the same plane flicker (z-fighting): they must meet edge to edge
            for q2 in range(q1 + 1, len(boxes)):
                (a1, c1, t1, z1), (a2, c2, t2, z2) = boxes[q1], boxes[q2]
                h1, h2 = (hnum(z1) or 0.0, hnum(t1) or 9.0), (hnum(z2) or 0.0, hnum(t2) or 9.0)
                if min(c1, c2) - max(a1, a2) > 0.03 and min(h1[1], h2[1]) - max(h1[0], h2[0]) > 0.03:
                    problems.append(f"two paint boxes overlap along the wall at local x {round(max(a1, a2), 3)}..{round(min(c1, c2), 3)} "
                                    f"(plan {ax_} {rng(max(a1, a2), min(c1, c2))}): coplanar panels flicker in 3D; keep ONE item "
                                    "per wall and trim the boxes so they meet edge to edge")
                    break
            else:
                continue
            break
        if re.search(r"\b(paint|colou?r|wall|finish|limewash|wallpaper)|دهان|لون|حيط", message, re.I) \
                and not re.search(r"\b(strip|band|stripe|half|part|panel|section|accent)\b|نص|جزء", message, re.I):
            lo_b, hi_b = w0, w1  # a whole-wall finish runs corner to corner
        bare = []
        t = max(w0, lo_b) + 0.05
        while t < min(w1, hi_b) - 0.05:  # a one-wall paint job leaves no bare bands between its ends
            for h_ in (0.4, 1.5, ceil_h - 0.2):
                if any(a_ <= t <= b_ for a_, b_ in wspans) and sill < h_ < win_head:
                    continue
                if not any(a_ - 0.01 <= t <= b_ + 0.01 and (hnum(z0) or 0) - 0.01 <= h_ <= (hnum(z1) or 9) + 0.01
                           for a_, b_, z1, z0 in boxes):
                    bare.append((round(t, 2), h_))
            t += 0.05
        if len(bare) >= 2 and not problems:
            under = [b2 for b2 in bare if any(a_ <= b2[0] <= c_ for a_, c_ in wspans)]
            side = [b2 for b2 in bare if b2 not in under]
            if side:
                xs_ = [b2[0] for b2 in side]
                problems.append(f"it leaves the wall bare between local x {min(xs_)} and {max(xs_)} (plan {ax_} "
                                f"{rng(min(xs_), max(xs_))}) at heights {sorted({round(b2[1], 2) for b2 in side})} m: away from "
                                "the windows the boxes run full height, 0..M.ceiling")
            if under:
                xs_ = [b2[0] for b2 in under]
                hs_ = sorted({round(b2[1], 2) for b2 in under})
                problems.append(f"it leaves the wall bare under / over the window around local x {min(xs_)}..{max(xs_)} at "
                                f"heights {hs_} m: add a box 0..M.sill under the window and M.winHead..M.ceiling over it, "
                                "spanning the window's width, never one box across the window opening itself")
        if problems:
            wl = sorted({rng(min(ts), max(ts)) for wo in wins
                         for ds in [[(px - x) * fx + (py - y) * fy for px, py in wo]]
                         for ts in [[(px - x) * ux + (py - y) * uy for px, py in wo]]
                         if min(ds) < 0.05 and max(ds) > -0.6 and min(ts) < w1 and max(ts) > w0})
            return (f"Check the panel: furnish.js line {i} ({line.strip()[:140]}): " + "; ".join(problems[:3]) + ". "
                    f"This room's wall here runs plan {ax_} {rng(w0, w1)}" + (f", window(s) at plan {ax_} " + ", ".join(wl)
                    if wl else "") + f". Cover exactly that: full-height boxes from the room corner to each window and "
                    "between windows, plus a strip under each window (0..M.sill) and over it (M.winHead..M.ceiling). Box " +
                    (f"x values are local to the item: local = plan {ax_} - {x if ux else y} " if ux + uy > 0 else
                     f"x values are local to the item: local = {x if ux else y} - plan {ax_} ") +
                    f"(\"{f}\" runs along plan {'+' if ux + uy > 0 else '-'}{ax_})." + tail)
    if (miss := unplanned(ws, f0, f1, new_items)):  # a new 3D piece with no plan outline, or a new outline with no 3D piece
        return miss + tail
    for i, line in new_items[:4]:  # a new floor piece's plan outline has to start at its back, like the 3D does
        m = ITEM.search(line)
        x, y, f = float(m[1]), float(m[2]), m[3]
        for pts in ws.new_outlines:
            xs, ys = [q[0] for q in pts], [q[1] for q in pts]
            b = (min(xs), min(ys), max(xs), max(ys))
            if not (b[0] - 0.3 <= x <= b[2] + 0.3 and b[1] - 0.3 <= y <= b[3] + 0.3):
                continue
            edge = {"E": b[0], "W": b[2], "N": b[1], "S": b[3]}[f]
            at = x if f in "EW" else y
            mid, pos = ((b[1] + b[3]) / 2, y) if f in "EW" else ((b[0] + b[2]) / 2, x)
            if abs(at - edge) <= 0.05 and abs(mid - pos) > 0.04:
                ax2 = "y" if f in "EW" else "x"
                return (f"Check 2D vs 3D: furnish.js line {i} ({line.strip()[:120]}) centres the piece at {ax2} {pos}, but its "
                        f"new plan outline is centred at {ax2} {round(mid, 3)} (runs {ax2} {round(b[1] if f in 'EW' else b[0], 3)}.."
                        f"{round(b[3] if f in 'EW' else b[2], 3)}). item()'s x, y is the middle of the back: make them the "
                        "same piece (move the item or the outline)." + tail)
            if abs(at - edge) > 0.05:
                d = b[2] - b[0] if f in "EW" else b[3] - b[1]
                want = {"E": f"x {x}..{round(x + d, 3)}", "W": f"x {round(x - d, 3)}..{x}",
                        "N": f"y {y}..{round(y + d, 3)}", "S": f"y {round(y - d, 3)}..{y}"}[f]
                return (f"Check 2D vs 3D: furnish.js line {i} ({line.strip()[:120]}) puts the piece's BACK at ({x}, {y}) "
                        f"facing \"{f}\", so in 3D it runs {want}, but its new plan outline runs x {b[0]}..{b[2]}, "
                        f"y {b[1]}..{b[3]}. Make them the same piece: set the outline's points (dxf_edit set_points) "
                        "to start at the back and extend the piece's depth in the facing direction, or move the item." + tail)
    # A new piece parked in front of wardrobe doors (the room has to stay usable).
    fronts = []
    for i, px, py, line in placed_lines(ws, f1):
        wm = re.search(r"\bwardrobe\(\s*([\d.]+)", line)
        im = ITEM.search(line)
        if wm and im and line not in {l for _, l in new_items}:
            hw, f = float(wm[1]) / 2, im[3]
            fronts.append((i, {"E": (px + 0.6, py - hw, px + 1.2, py + hw), "W": (px - 1.2, py - hw, px - 0.6, py + hw),
                               "N": (px - hw, py + 0.6, px + hw, py + 1.2), "S": (px - hw, py - 1.2, px + hw, py - 0.6)}[f]))
    for pts in ws.new_outlines:
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        b = (min(xs), min(ys), max(xs), max(ys))
        for i, z in fronts:
            if min(b[2], z[2]) - max(b[0], z[0]) > 0.03 and min(b[3], z[3]) - max(b[1], z[1]) > 0.03:
                return (f"Check the room still works: the new piece's outline (x {round(b[0], 3)}..{round(b[2], 3)}, y "
                        f"{round(b[1], 3)}..{round(b[3], 3)}) stands in front of the wardrobe doors of furnish.js line {i}, "
                        f"in the ~60 cm that has to stay clear to open them (x {round(z[0], 3)}..{round(z[2], 3)}, y "
                        f"{round(z[1], 3)}..{round(z[3], 3)}). Move it (plan outline and furnish.js line together) out of "
                        "that strip, or tell the user why there is nowhere else." + tail)
    if new_items:
        cur = ws.tmp / "plan-now.dxf"
        cur.write_bytes(ws.read(ws.cfg["dxf"]))
        for i, line in new_items[:4]:
            m = ITEM.search(line)
            x, y, f = float(m[1]), float(m[2]), m[3]
            code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(cur), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                           f"--bbox={x - 0.4},{y - 0.4},{x + 0.4},{y + 0.4}", "--layers=1wall", "--limit", "200"], timeout=90)
            try:
                ents = json.loads(q).get("entities", [])
            except ValueError:
                continue
            ax, d = (1, 1 if f == "N" else -1) if f in "NS" else (0, 1 if f == "E" else -1)
            at, along = (y, x) if ax == 1 else (x, y)
            faces = []
            for e in ents:
                ps = e.get("points") or []
                if e["type"] != "LINE" or len(ps) != 2 or abs(ps[0][ax] - ps[1][ax]) > 0.005:
                    continue
                lo, hi = sorted((ps[0][1 - ax], ps[1][1 - ax]))
                if lo - 0.05 <= along <= hi + 0.05:
                    faces.append(ps[0][ax])
            on = [c for c in faces if abs(c - at) < 0.02]
            ahead = sorted((c - at) * d for c in faces if 0.04 < (c - at) * d < 0.35)
            if on and ahead:
                good = round(at + d * ahead[0], 3)
                axis = "y" if ax == 1 else "x"
                return (f"Check placement: furnish.js line {i} ({line.strip()[:120]}) has its back on the far face of a "
                        f"wall ({axis} {round(on[0], 3)}): facing \"{f}\" its front would be inside the wall. The face on the "
                        f"room side is {axis} {good}; put the back there (keep the facing if it points into the room)." + tail)
    return None
    return None


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
                return self.reply(200, {"ready": bool(api_key()), "model": MODEL, "api": "responses" if uses_responses(MODEL) else "chat",
                                        "models": sorted(ALLOWED_MODELS), "planEdits": plan_edits()})
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
