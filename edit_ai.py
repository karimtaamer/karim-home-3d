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
import base64, hashlib, json, os, re, secrets, shutil, subprocess, sys, tempfile, threading, time, urllib.error, \
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
# Extra models a request may pick with "model" (comma-separated, e.g. for an A/B run); empty = only MODEL.
ALLOWED_MODELS = {m.strip() for m in os.environ.get("EDIT_AI_MODELS", "").split(",") if m.strip()} | {MODEL}
MAX_STEPS = 20  # tool rounds per message
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


PLACE = re.compile(r"\b(?:item|rug)\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)")
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
                                       "grow {N:0.2,S:0.2,E:0.2,W:0.2}; \"10 cm wider\" on a piece facing N/S = grow {E:0.05,W:0.05}; no arithmetic. "
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
        return "every edit of this message is thrown away; nothing will be saved unless you edit again"
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
never out in the room. A new piece that stands on the floor (table, chair, cabinet) also gets its footprint drawn on \
the plan: dxf_edit add_polyline on 2furni, closed, drawn exactly where the 3D puts it: its back edge through (x, y) \
and its depth out in the facing direction (facing "E" with depth d: x .. x + d; "N": y .. y + d), width centred on \
(x, y); wall-hung things (TV, art, shelves, lights) don't. Before adding or moving a piece, check with \
furniture_near what already stands there and don't overlap it; if the spot is taken, pick the nearest free one and say so. \
Keep the room usable: ~70 cm clear in front of wardrobe / cabinet fronts and door swings, ~60 cm beside the bed; a \
new chair or table never goes in front of the wardrobe doors.
- Keep 3D and 2D together: a piece drawn on the plan (2furni) that you move or resize in furnish.js gets exactly the \
same change in the DXF (furniture_near gives its outline's handle: dxf_edit move_piece / resize_piece), and a DXF \
furniture change gets the same change in furnish.js. Move only the pieces asked for (plus their group, below): \
other neighbours stay unless the user wants them to follow, and then they move in both furnish.js and the DXF. A resize that leaves \
a neighbour overlapping or with an odd gap (bedside tables beside a narrower bed) moves that neighbour too, both views. A wall moved in the DXF must keep \
both faces, close its junctions exactly (snap endpoints to existing ones within 0.1 mm), and the furniture against it \
moves with it in furnish.js.
- \"At the foot of / beside / in front of\" a piece: line the new piece up with that piece's plan outline (centred on \
it unless told otherwise) and set it 5-10 cm off it, not across the room.
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


def chat(req):
    v = req.get("version") or "main"
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    if not api_key():
        raise PermissionError("Edit AI isn't switched on yet: set EDIT_AI_OPENAI_API_KEY (or OPENAI_API_KEY) on the server.")
    model = req.get("model") or MODEL
    if model not in ALLOWED_MODELS:
        raise ValueError(f"model {model!r} isn't allowed here")
    message = (req.get("message") or "").strip()[:4000]
    if not message:
        raise ValueError("Say what you want changed.")
    ctx = req.get("context") or {}
    image = check_image(req.get("image"), "the view")
    refs = [check_image(u, f"reference {i + 1}") for i, u in enumerate((req.get("refs") or [])[:MAX_REFS])]
    ws = Workspace(v)
    ws.allow_as_built = v == "as-built"  # only ever reached from the as-built page itself
    ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines = False, False, {}, {}, []
    sys_prompt = SYSTEM.format(showing="2D drawing" if ctx.get("showing") == "drawing" else "3D model", version=v,
                               marked="" if ctx.get("wholeView") else ", with what the user circled marked in red")
    if not plan_edits():
        sys_prompt += ("\n\nThis server can't edit the plan DXF (walls, windows, doors): only furnish.js, materials.js and the tour. "
                       "If the request needs a wall, window or door moved, say plainly that plan edits are unavailable right now.")
    messages = [{"role": "system", "content": sys_prompt}]
    for h in (req.get("history") or [])[-8:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str):
            messages.append({"role": h["role"], "content": h["text"][:2000]})
    content = [{"type": "text", "text": f"{context_text(ctx)}\n\nRequest: {message}"},
               {"type": "image_url", "image_url": {"url": image, "detail": "high"}}]
    content += [{"type": "image_url", "image_url": {"url": u, "detail": "low"}} for u in refs]
    messages.append({"role": "user", "content": content})
    total, reply, steps, trace = {"prompt_tokens": 0, "completion_tokens": 0, "cached": 0}, "", [], []
    nudged = False
    try:
        for step in range(MAX_STEPS):
            res = openai(messages, first=step == 0, model=model)  # look before answering: no "done" without a tool call
            cost(res.get("usage") or {}, total)
            msg = res["choices"][0]["message"]
            messages.append({k: msg[k] for k in ("role", "content", "tool_calls") if msg.get(k) is not None})
            if not msg.get("tool_calls"):
                reply = msg.get("content") or ""
                nudge = None if nudged or step >= MAX_STEPS - 3 else review(ws, message, reply)
                if nudge:  # one second look before saving: 2D and 3D out of step, a lost opening, a give-up with edits left
                    nudged = True
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
        else:
            reply = "I ran out of steps before finishing; nothing was changed. Try a narrower request."
            ws.changed.clear()
        if not ws.changed and reply and re.search(r"\b(I('ve| have)?|have been) (changed|made|moved|added|removed|replaced|updated|set)\b", reply):
            reply = "Nothing was changed yet: " + reply  # the model claimed an edit it never made
        result = save(ws, reply or message) if ws.changed else None
    finally:
        shutil.rmtree(ws.tmp, ignore_errors=True)
    usd = dollars(total, model)
    print(f"[edit-ai] {v} ({model}): {len(steps)} tool calls, {total['prompt_tokens']} in ({total['cached']} cached) / "
          f"{total['completion_tokens']} out tokens, ${usd}; changed {sorted(ws.changed) or 'nothing'}", flush=True)
    return {"reply": reply or "Done.", "changed": sorted(ws.changed), "rev": result and result["rev"], "model": model,
            "tokens": total, "usd": usd, "steps": len(steps), "sync": result and result.get("sync"),
            **({"trace": trace} if req.get("debug") else {})}


NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
GAVE_UP = re.compile(r"\b(couldn'?t|could not|can'?t|cannot|unable|wasn'?t able|not possible|left (it |them |everything )?(as it was|unchanged)|"
                     r"(made|changed) nothing|no changes?( were)? made|didn'?t change)\b", re.I)
REMOVAL = re.compile(r"\b(remove|delete|close|block|wall up|fill in|get rid)\b|شيل|امسح|اقفل|اقفل|سد", re.I)


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
    tail = " Then reply to the user as you normally would, about the change itself (don't mention this check)."
    f0 = ws.orig["furnish.js"].decode() if "furnish.js" in ws.orig else ws.text("furnish.js")
    f1 = ws.text("furnish.js")
    now = set(f1.splitlines())
    # A plan piece moved / resized: the 3D line(s) standing on it must have changed too.
    for h, b in ws.pieces.items():
        lines = [(i, line) for i, px, py, line in placed_lines(ws, f0)
                 if b[0] - 0.15 <= px <= b[2] + 0.15 and b[1] - 0.15 <= py <= b[3] + 0.15]
        if lines and all(line in now for _, line in lines):
            return (f"Check 2D vs 3D: you changed plan piece {h} (was x {b[0]}..{b[2]}, y {b[1]}..{b[3]}) but its 3D line(s) in "
                    "furnish.js didn't change: " + "; ".join(f"line {i}: {line.strip()[:160]}" for i, line in lines[:4])
                    + ". Give the 3D piece exactly the same move / resize (for this version only), or put the plan piece "
                      "back if it wasn't meant to change." + tail)
    # A 3D piece moved / resized: the plan outline it stands on must have changed too.
    ops = [o for o in ws.ops.get("furnish.js") or []
           if Counter(NUMBER.findall(o["old"])) != Counter(NUMBER.findall(o["new"]))
           and not (o["new"].startswith(o["old"]) or o["new"].endswith(o["old"]))]  # not a pure addition
    gone = [(i, px, py, line) for i, px, py, line in placed_lines(ws, f0)
            if line not in now and any(len(seg.strip()) > 8 and seg.strip() in line for o in ops for seg in o["old"].splitlines())]
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
                        "changed (colour, finish, doors), nothing is needed." + tail)
    loop_ops = [o for o in ops if any(re.search(r"\bfor \(const|\bitem\(|\brug\(", l)
                                      and l.strip() not in {n_.strip() for n_ in o["new"].splitlines()}
                                      for l in o["old"].splitlines())]
    if loop_ops and not ws.dxf_furni and not gone:
        return ("Check 2D vs 3D: you moved or resized furniture in furnish.js but nothing on the plan (2furni). If the "
                "piece is drawn on the plan (furniture_near lists the outlines there), give its outline exactly the same "
                "change now with dxf_edit move_piece / resize_piece; things not drawn on the plan need nothing." + tail)
    # A plan piece that now runs into a wall or another piece.
    hits = [c for cs in ws.clashes.values() for c in cs]
    if any(not c.get("free") for c in hits):
        free = [f"{c['piece']}: {c['free']}" for c in hits if c.get("free")]
        hits = [c for c in hits if not c.get("free")]
        desc = "; ".join(f"{c['piece']} overlaps {c['with']} at x {c['overlap'][0]}..{c['overlap'][2]}, "
                         f"y {c['overlap'][1]}..{c['overlap'][3]}" for c in hits[:4])
        if free:
            desc += (" (" + "; ".join(free) + ": a piece wider than its free span can't fit there as asked; then "
                     "make it as big as fits, or move the neighbour if the user would expect that, and say so)")
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
        lo_b, hi_b = min(bx[0] for bx in boxes), max(bx[1] for bx in boxes)
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
            xs_ = [b2[0] for b2 in bare]
            problems.append(f"it leaves the wall bare between local x {min(xs_)} and {max(xs_)} at heights "
                            f"{sorted({round(b2[1], 2) for b2 in bare})} m (beside a window the boxes have to run full height, "
                            "0..M.ceiling)")
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
            if min(b[2], z[2]) - max(b[0], z[0]) > 0.08 and min(b[3], z[3]) - max(b[1], z[1]) > 0.08:
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
