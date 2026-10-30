#!/usr/bin/env python3
"""Edit AI: change the flat from inside the viewer, in words, with what's on screen as the picture.

    python3 edit_ai.py [port]     # serves this folder on http://127.0.0.1:8000 with Edit AI and Generate Photo Spot

The page (edit-ai.js) freezes the 3D or 2D view, the user circles what to change (or picks Whole view), says what
they want and may attach reference pictures. POST /api/edit-ai/precheck first grades the wording (gpt-6-luna, a few
hundred tokens); POST /api/edit-ai/chat then sends it here; an OpenAI chat model with vision works through tools
(routed per message: easy -> gpt-6-luna, complex -> gpt-6.1-sol, key EDIT_AI_OPENAI_API_KEY, kept apart from Generate
Photo Spot's OPENAI_API_KEY; a Claude id in EDIT_AI_EASY_MODEL / EDIT_AI_COMPLEX_MODEL runs on the Anthropic Messages
API with ANTHROPIC_API_KEY instead): it greps and reads furnish.js / materials.js / the docs, edits them by exact
search/replace, queries and edits the version's DXF (edit_ai_dxf.py), and the model and drawing are rebuilt from the
DXF (build_geometry.py, build_drawing.py) whenever the plan changed, so the 3D and the 2D stay one. Before saving,
gpt-6.1-sol reviews the finished edit against the request (review_edit); a low score sends its notes back to the
editor for one fix round. chat(stream=True) reports those steps as NDJSON lines while it runs.

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
ANTHROPIC_URL = os.environ.get("EDIT_AI_ANTHROPIC_URL", "https://api.anthropic.com/v1/messages")
# Models that only take function tools on /v1/responses (EDIT_AI_API=responses forces it for any model).
RESPONSES_MODELS = ("gpt-6.1", "gpt-6-astra")
# Auto-routing (pick_model): easy edits stay on the cheap model, complex ones go to the strong one. GPT by choice
# (26 Oct 2026); Claude ids still work here (Haiku 5.5 in Luna's role, Sonnet 5.5 in Sol's) and fall back to their
# OpenAI stand-in (OPENAI_FALLBACK) without an Anthropic key.
EASY_MODEL = os.environ.get("EDIT_AI_EASY_MODEL", "gpt-6-luna")
COMPLEX_MODEL = os.environ.get("EDIT_AI_COMPLEX_MODEL", "gpt-6.1-sol")
OPENAI_FALLBACK = {"easy": "gpt-6-luna", "complex": "gpt-6.1-sol"}
# Extra models a request may pick with "model" (comma-separated, e.g. for an A/B run); MODEL and both routes always allowed.
ALLOWED_MODELS = {m.strip() for m in os.environ.get("EDIT_AI_MODELS", "").split(",") if m.strip()} | {MODEL, EASY_MODEL, COMPLEX_MODEL, *OPENAI_FALLBACK.values()}
MAX_STEPS = 36  # tool rounds per message (was 20; hard openable/plan builds were dying early)
# Quality gates around an edit, both on OpenAI (EDIT_AI_OPENAI_API_KEY); EDIT_AI_GATES=0 turns them off, and a gate
# that fails lets the edit through as before. Precheck: Luna grades the wording before any edit model runs. Review:
# Sol scores the finished edit 0-10 before it is saved; under REVIEW_PASS the editor gets its notes for one fix round
# of up to FIX_STEPS, then Sol scores the fixed edit once more for the record (no second fix round).
PRECHECK_MODEL = os.environ.get("EDIT_AI_PRECHECK_MODEL", "gpt-6-luna")
REVIEW_MODEL = os.environ.get("EDIT_AI_REVIEW_MODEL", "gpt-6.1-sol")
REVIEW_PASS = 7
# Below this the edit isn't saved, whatever the fix round did: the reviewer found it missed the request (e2e 28 Oct 2026:
# edits scored 0-4 were saved as "Your edit is done": J211 / J212 / J215 / J218 / J225 / J265).
REVIEW_KEEP = 5
FIX_STEPS = 20
MAX_STEPS_COMPLEX = 60  # the strong model's big jobs (a whole room redone); TIME_LIMIT still bounds it
TIME_LIMIT = float(os.environ.get("EDIT_AI_TIME_LIMIT", "270" if os.environ.get("VERCEL") else "900"))  # s; Vercel stops at 300
MAX_IMAGE = 3_000_000  # bytes of a data URL
MAX_REFS = 4
# USD per million tokens (input, cached input, output[, cache write]); only to tell the user what a message cost.
# Claude: Anthropic list prices (platform.claude.com/docs/en/about-claude/pricing, rate card effective 2026-10-07);
# Haiku 5.5 doubles up above 100K prompt tokens per call (PRICES_LONG). OpenAI: OpenAI list prices.
PRICES_LONG = {"claude-haiku-5-5": (100_000, (0.50, 0.05, 2.50, 0.625))}
PRICES = {"claude-haiku-5-5": (0.10, 0.01, 0.50, 0.125), "claude-sonnet-5-5": (2.0, 0.10, 10.0, 2.50),
          "claude-opus-5-5": (4.0, 0.20, 20.0, 5.0), "claude-haiku-4-5": (1.0, 0.10, 5.0, 1.25), "claude-sonnet-4-5": (3.0, 0.30, 15.0, 3.75),
          "gpt-6.1-sol": (2.0, 0.1, 10.0), "gpt-6-luna": (0.1, 0.01, 0.5), "gpt-6-sol": (2.0, 0.2, 10.0), "gpt-5.6-sol": (4.0, 0.4, 20.0), "gpt-4.1": (2.0, 0.5, 8.0), "gpt-4.1-mini": (0.4, 0.1, 1.6), "gpt-4.1-nano": (0.1, 0.025, 0.4),
          "gpt-4o": (2.5, 1.25, 10.0), "gpt-4o-mini": (0.15, 0.075, 0.6)}
ORIGIN = (190.4049651574427, -121.6132067325871)  # DWG -> plan, the same for every version (model*.js "origin")

# Each plan version: its DXF, the files built from it and the build flags. They live in build_flags.json, the one
# file the manual build (build_version.py, README) also reads, so a plan rebuild here can't drift from it (25 Oct:
# Edit AI 0a5a7de rebuilt Main without the reception column --cut and re-inflated the column to 17.862).
# Since 2026-10-25 the page's Main loads the kareems-changes plan; "Karim's version" (?v=kareems-changes on the page)
# loads its own karims-version plan since 26 Oct 2026. Bigger / Shifted Bedroom are retired. A request for "main"
# (or with no version) is an edit to Main's plan.
ALIASES = {"main": "kareems-changes"}
VERSIONS = {k: c for k, c in json.loads((Path(__file__).resolve().parent / "build_flags.json").read_text()).items()
            if not k.startswith("_")}
# Every version has its own furniture and materials since 26 Oct 2026 (Karim: "each version should have its own
# everything"): furnish-<v>.js and materials-<v>.js. The model, the tools and the checks call them by these names;
# own() turns a name into the version's file wherever a file is read, stored or committed (the page does the same).
OWN = ["furnish.js", "materials.js"]
DOCS = ["README.md", "DWG_EDITING.md", "CLAUDE.md",  # read-only context
        "docs/edit-ai/when-2d-needed.md", "docs/edit-ai/3d-only-patterns.md",  # decision notes: does an edit need the plan?
        "docs/edit-ai/version-isolation.md"]  # every version has its own files
MIME = {".js": "text/javascript; charset=utf-8", ".json": "application/json", ".dxf": "application/dxf"}


def own(v, path):
    """The version's own file for a generic name ("furnish.js" -> "furnish-karims-version.js"); other paths as they are."""
    return path.replace(".js", f"-{v}.js") if path in OWN else path


# Live overrides (by sha) already pulled into git when each version got its own files: the shared furnish.js ones and
# Main's tour, which git now holds in its standalone form. They drop out instead of merging onto the new files.
PULLED = {"kareems-changes": {"9924d0735c024e622ba3", "c3d4ac30615a61048d3a"}, "naghams-changes": {"99b962fa671a0b66c38a"}}


def editable(v):
    c = VERSIONS[v]
    return OWN + [c["tour"]]


def readable(v):
    c = VERSIONS[v]
    return editable(v) + DOCS + ["index.html", "drawing.js", "check_furnish.py", "design-locks.json", "build_flags.json"]


def _key(*names):
    """The first usable value of these env names (env first, then .env here); ignores the connector placeholder."""
    def _ok(v):
        v = (v or "").strip().strip('"\'')
        return v if v and v != "[REDACTED]" and len(v) > 20 else None
    env = ROOT / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    for n in names:
        if k := _ok(os.environ.get(n)):
            return k
        for line in lines:
            name, _, val = line.partition("=")
            if name.strip() == n and (k := _ok(val)):
                return k
    return None


def anthropic_key():
    if k := _key("EDIT_AI_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        return k
    # Vercel MCP redacts $file values that match (or base64-decode to) process.env secrets → "[REDACTED]".
    # Store xor(0x5A)+base64 under EDIT_AI_ANTHROPIC_API_KEY_B64 instead.
    import base64
    b64 = (os.environ.get("EDIT_AI_ANTHROPIC_API_KEY_B64") or "").strip()
    if b64 and b64 != "[REDACTED]":
        try:
            raw = bytes(b ^ 0x5A for b in base64.b64decode(b64)).decode("utf-8").strip()
            if raw and len(raw) > 20:
                return raw
        except Exception:
            pass
    return None


def is_claude(model):
    return (model or "").startswith("claude")


def ready():
    return bool(anthropic_key() or api_key())


def live_model(model):
    """The model a message really runs on: a Claude pick falls back to its OpenAI stand-in without an Anthropic key."""
    if is_claude(model) and not anthropic_key():
        return OPENAI_FALLBACK["complex" if model == COMPLEX_MODEL or "sonnet" in model or "opus" in model else "easy"]
    return model


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
    if len(_cache) > 256:  # revisions are read again for own_shas(): room for the recent ones
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


_fresh = {}  # path -> (time, bytes): git main's copy, a few seconds old at most


def fresh(path):
    """What an edit starts from when the version has no live override: git main as it is now on Vercel, not the
    deployed bundle. Every edit commits to main and Vercel builds about one deploy a minute, so the bundle can be
    several commits behind; on 27 Oct 2026 an edit read a stale bundle and committed back a change an Undo had
    already taken out (grey bedroom walls, 1cb6d52 -> 089d570). The bundle stays the page's reference (patches)."""
    if not (ON_VERCEL and os.environ.get("EDIT_AI_GITHUB_TOKEN")) or os.environ.get("EDIT_AI_FRESH_FROM_GIT") == "0":
        return deployed(path)
    hit = _fresh.get(path)
    if hit and time.time() - hit[0] < 15:
        return hit[1]
    repo = os.environ.get("EDIT_AI_GITHUB_REPO", "karimtaamer/karim-home-3d")
    branch = os.environ.get("EDIT_AI_GITHUB_BRANCH", "main")
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(path)}?ref={branch}",
                                 headers={"Authorization": f"Bearer {os.environ['EDIT_AI_GITHUB_TOKEN']}",
                                          "Accept": "application/vnd.github.raw"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[edit-ai] fresh {path}: {e}; using the deployed copy", flush=True)
            return deployed(path)
        data = b""
    except Exception as e:
        print(f"[edit-ai] fresh {path}: {e}; using the deployed copy", flush=True)
        return deployed(path)
    _fresh[path] = (time.time(), data)
    return data


def merge3(base, live, dep):
    """Line-based three-way merge: the Edit AI change (base -> live) laid onto a newer deployed file (base -> dep).
    None when both sides touched the same lines differently (a real conflict)."""
    B, L, D = base.splitlines(True), live.splitlines(True), dep.splitlines(True)

    def hunks(new):
        return [(i1, i2, new[j1:j2]) for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, B, new, autojunk=False).get_opcodes()
                if tag != "equal"]

    changes = sorted({(i1, i2, tuple(r)) for i1, i2, r in hunks(L) + hunks(D)})  # identical hunks on both sides count once
    for (a1, a2, ar), (b1, b2, br) in zip(changes, changes[1:]):
        empty = a1 == a2 or b1 == b2
        if (a1 <= b2 and b1 <= a2) if empty else (a1 < b2 and b1 < a2):
            return None
    out, at = [], 0
    for i1, i2, r in changes:
        out += B[at:i1] + list(r)
        at = i2
    return "".join(out + B[at:])


def replay(text, ops):
    """Apply recorded search/replace edits to a newer base; None if one neither applies nor is already in."""
    for o in ops:
        if o["new"] in text:  # already in (e.g. the edit was pulled into git): applying it again would duplicate an insertion
            continue
        if text.count(o["old"]) != 1:
            return None
        text = text.replace(o["old"], o["new"])
    return text


def resolve(man):
    """{path: (status, entry, content or None)} for a revision against the files deployed now.
    status: live (use the stored file), replayed (content given), synced (deployed already equals it), conflict."""
    out, owned = {}, None
    if not man:
        return out
    for path, e in man["files"].items():
        if e["sha"] in PULLED.get(man["version"], ()):
            continue
        if path in OWN:  # a revision from before the split (26 Oct 2026), when every version shared furnish.js / materials.js
            if (st := legacy(man["version"], path, e)):
                out[own(man["version"], path)] = st
            continue
        dep = deployed(path)
        if sha(dep) == e["sha"]:
            out[path] = ("synced", e, None)
        elif sha(dep) == e["base"] or sha(dep) in (owned := owned if owned is not None else own_shas(man["version"]))[path]:
            # The bundle is one of this version's own recent states (a deploy of an earlier Edit AI commit catching up,
            # e.g. an edit whose Undo isn't deployed yet): not a newer push, so the live file stands as it is. Merging
            # onto it brought an undone change back on 27 Oct 2026 (glass parapet, test 19 -> 21).
            out[path] = ("live", e, None)
        else:
            # The deployed file moved on (a git push): keep the live edit on top of it. A three-way merge against the
            # file the edit started from is tried first (it also covers undo revisions, which carry no ops), then the
            # recorded search/replace ops. Only when both fail is it a conflict, and a conflict is kept, never dropped.
            t = None
            if path.endswith((".js", ".json")) and e.get("base_url"):
                try:
                    t = merge3(get(e["base_url"]).decode(), get(e["url"]).decode(), dep.decode())
                except Exception as err:
                    print(f"[edit-ai] merge {path}: {err}", flush=True)
            if t is None and e.get("ops"):
                t = replay(dep.decode(), e["ops"])
            out[path] = ("replayed", e, t.encode()) if t is not None else ("conflict", e, None)
    # Files built from the DXF stand or fall with it.
    for path, (st, e, _) in list(out.items()):
        if e.get("derived") and out.get(e["derived"], ("synced",))[0] == "conflict":
            out[path] = ("conflict", e, None)
    return out


def own_shas(v, n=30):
    """{path: shas} this version's last n revisions stored: states Edit AI itself made (one listing, cached reads)."""
    out = defaultdict(set)
    for name in revisions(v)[-n:]:
        try:
            files = json.loads(get(name)).get("files", {})
        except Exception:
            continue
        for path, f in files.items():
            out[path].add(f["sha"])
    return out


def legacy(v, path, e):
    """A live furnish.js / materials.js override from before the split, for the version's own file now: None when it
    was pulled into git with the split (PULLED) or its edits are already in the file, else its search/replace ops
    replayed onto the file, else a conflict (kept for edit_ai_pull.py)."""
    if e["sha"] in PULLED.get(v, ()):
        return None
    dep = deployed(own(v, path))
    t = replay(dep.decode(), e["ops"]) if e.get("ops") else None
    if t is not None and t.encode() == dep:
        return None
    return ("replayed", e, t.encode()) if t is not None else ("conflict", e, None)


def live_content(path, st):
    status, e, content = st
    if status == "replayed":
        return content
    if status == "live":
        return get(e["url"])
    return deployed(path)


def plan_version(v):
    """The plan version a request's version names (ALIASES resolved; none = Main)."""
    v = v or "main"
    return ALIASES.get(v, v)


def patches(v):
    v = plan_version(v)
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
            "conflicts": conflicts, "ready": ready(), "model": live_model(MODEL), "undo": undo_target(man) is not None}


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
            p = own(self.v, path)
            st = self.res.get(p)
            self.files[path] = live_content(p, st) if st else fresh(p)  # git main, not a bundle that may lag
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
        self.pieces_now, self.plan_moves, self.clamped, self.rotated = {}, {}, False, False
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
    try:
        p = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:  # a busy box: the caller (or the model, as a tool's answer) hears it; the chat goes on (e2e J308 r3)
        return 124, f"timed out after {timeout} s ({Path(str(args[1] if len(args) > 1 else args[0])).name} {args[2] if len(args) > 2 else ''}); try again"
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


def runs_as(text, version):
    """The version a furnish file's code runs as. Nagham's file (an exact copy of Main's 3D, 8c99f62) starts
    `if (version === "naghams-changes") version = "kareems-changes";`, so in it Main's branches are the ones that run and
    a `version === "naghams-changes"` test never passes (e2e 28 Oct 2026: Move saves and Edit AI edits that never showed,
    and Main's branches there refused as "another plan version")."""
    m = re.search(r'^[ \t]*if \(version === "' + re.escape(version) + r'"\) version = "([\w-]+)";', text, re.M)
    return m[1] if m else version


def version_scope(text, version):
    """Per line of furnish.js: False when the line sits in (or is guarded by) a version branch that doesn't run for
    `version`, True when the version branches around it all do, None when there are none or it can't tell."""
    version = runs_as(text, version)

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


def for_version(text, version):
    """furnish.js as `version` runs it, near enough to compare: comments, spacing and the lines in other versions'
    branches dropped, `version === "x"` conditions folded to true / false and `true ? a : b` to the side taken."""
    version = runs_as(text, version)
    sc = version_scope(text, version)
    L = text.splitlines()
    # A line closing another version's block ends in the scope around it, but belongs to that block.
    keep = [s is not False and not (k and sc[k - 1] is False and l.strip().startswith("}")) for k, (l, s) in enumerate(zip(L, sc))]
    t = " ".join(re.sub(r"//(?=(?:[^\"'`]|\"[^\"]*\"|'[^']*')*$).*", "", l) for l, k in zip(L, keep) if k)
    t = re.sub(r"\s*([^\w$\s])\s*", r"\1", re.sub(r"\s+", " ", t)).strip()
    lit = lambda b: "true" if b else "false"
    t = re.sub(r"\[([^\]]*)\]\.includes\(version\)",
               lambda m: lit(version in re.findall(r"[\"']([^\"']*)[\"']", m[1])), t)
    t = re.sub(r"version(===|!==|==|!=)([\"'])([^\"']*)\2", lambda m: lit((m[3] == version) == ("=" == m[1][0])), t)
    t = re.sub(r"([\"'])([^\"']*)\1(===|!==|==|!=)version", lambda m: lit((m[2] == version) == ("=" == m[3][0])), t)
    for _ in range(2000):  # fold: !lit, (lit), lit && lit, lit || lit, lit ? a : b (one ternary a pass; stops when done)
        t0 = t
        t = re.sub(r"!(true|false)\b", lambda m: lit(m[1] == "false"), t)
        t = re.sub(r"\((true|false)\)", r"\1", t)
        t = re.sub(r"\b(true|false)&&(true|false)\b", lambda m: lit(m[1] == m[2] == "true"), t)
        if t == t0:
            t = re.sub(r"\b(true|false)\|\|(true|false)\b(?!&&)", lambda m: lit("true" in (m[1], m[2])), t)
        if t == t0:
            t = _fold_ternary(t)
        if t == t0:  # const KC = version === "x", ... then KC ? a : b
            for m in re.finditer(r"\b(?:const|let) ([A-Za-z_$][\w$]*)=(true|false)(?=[,;])", t):
                t = re.sub(r"(?<![\w$.])" + re.escape(m[1]) + r"(?![\w$])(?!=[^=])", m[2], t)
        if t == t0:
            break
    return _unsized(t)


def _unsized(t):
    """sized(x,1,1) (and sized(x,1,1,1,0): height scale 1, lift 0) is x: Move and Resize's size for one version folds to
    that in the others."""
    k = 0
    while (i := t.find("sized(", k)) >= 0:
        depth, j, cut = 0, i + 5, []
        while j < len(t):
            if t[j] in "([{":
                depth += 1
            elif t[j] in ")]}":
                depth -= 1
                if depth == 0:
                    break
            elif t[j] == "," and depth == 1:
                cut.append(j)
            j += 1
        vals = [t[a + 1:b] for a, b in zip(cut, cut[1:] + [j])]
        # not part of a longer name (iffalsesized( is a folded condition); "." too: a comment the folding keeps (one with
        # an apostrophe) can end in one, and nothing calls .sized(
        is_call = i == 0 or not (t[i - 1].isalnum() or t[i - 1] in "_$") or t[:i].endswith(("true", "false"))
        if is_call and len(cut) > 2 and vals[2:] == ["1", "0"][:len(cut) - 2]:  # height 1, lift 0: as sized(x, a, o)
            t = t[:cut[2]] + t[j:]
            k = i
        elif is_call and len(cut) == 2 and vals == ["1", "1"]:
            t = t[:i] + t[i + 6:cut[0]] + t[j + 1:]
            k = i
        else:
            k = i + 1
    return t


def _fold_ternary(t):
    """The first `true ? a : b` / `false ? a : b` (whose condition is the bare literal) replaced by a or b."""
    for m in re.finditer(r"\b(true|false)\?", t):
        if m.start() and t[m.start() - 1] not in "(,=:?[{;>" and not t[:m.start()].endswith("return"):
            continue  # x && true ? ...: the literal is only part of the condition
        i, depth, nest, colon = m.end(), 0, 0, None
        while i < len(t):
            c = t[i]
            if c in "\"'`":
                i = t.find(c, i + 1) if t.find(c, i + 1) > 0 else len(t)
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and c == "?":
                nest += 1
            elif depth == 0 and c == ":":  # a ternary nested in either branch (a ? b : c ? d : e) closes its own ':'
                if nest > 0:
                    nest -= 1
                elif colon is None:
                    colon = i
                else:
                    break
            elif depth == 0 and c in ",;" and colon is not None:
                break
            i += 1
        if colon is None:
            continue
        return t[:m.start()] + (t[m.end():colon] if m[1] == "true" else t[colon + 1:i]) + t[i:]
    return t


def furnish_versions(text):
    """Every version furnish.js can run as: the plan versions and any other name it compares `version` with."""
    named = re.findall(r"version\s*[!=]==?\s*[\"']([^\"']+)|[\"']([^\"']+)[\"']\s*[!=]==?\s*version", text)
    named += [(s, "") for m in re.finditer(r"\[([^\]]*)\]\.includes\(\s*version\s*\)", text) for s in re.findall(r"[\"']([^\"']+)[\"']", m[1])]
    return set(VERSIONS) | {a or b for a, b in named}


ALL_VERSIONS = re.compile(r"\b(all|every|each|both|other) (the )?(plan )?versions?\b|\bevery ?where\b|\bin all of them\b|"
                          r"\b(all|every) (the )?(plans|layouts|options)\b", re.I)


def other_versions_changed(f0, f1, version):
    """The other versions whose furnish.js the edit (f0 -> f1) changes: a change for `version` only leaves them as they were."""
    return sorted(o for o in furnish_versions(f0 + f1) - {version} if for_version(f0, o) != for_version(f1, o))


def mats_changed(ws):
    """Existing materials.js entries the edit changed in place (new names are fine: nothing else uses them yet)."""
    if "materials.js" not in ws.changed or "materials.js" not in ws.orig:
        return []
    defs = lambda t: {m_[1]: m_[2].strip() for m_ in re.finditer(r"^\s+(\w+)\s*:\s*(.+)$", t, re.M)}
    d0, d1 = defs(ws.orig["materials.js"].decode()), defs(ws.text("materials.js"))
    return [k for k in d0 if k in d1 and d0[k] != d1[k]]


CALLS = re.compile(r"\b(?:item|rug|plant|art|ac|sconce|pendant)\(")  # any call, loop bodies too
PLACE = re.compile(r"\b(?:item|rug|plant|art|ac|sconce|pendant)\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)")
RUG = re.compile(r"\brug\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)")
ITEM = re.compile(r"\bitem\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*\"([NSEW])\"")
# its facing letter, also on a line whose x / y are expressions (a version ternary hid every turn: e2e J206 r4)
ITEM_FACING = re.compile(r'\bitem\(.*?,\s*"([NSEW])"\s*,')
TURN_ASK = re.compile(r"\b(turn|rotate|face|facing|toward|towards)\b|لفّ|لف |وجّه|ناحية|ناحيه", re.I)
TV_WORD = re.compile(r"\bTV\b|\btelevision\b|تلفزيون|تليفزيون|تلفاز|الشاشة", re.I)


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


LOOP = re.compile(r"\bfor \(const (\w+) of \[([-\d.,\s]+)\]\)")


def loop_placed(ws, text):
    """(item line no, x, y, [for line, item line]) for each piece a `for (const x of [a, b])` loop places with
    item(x, y / item(x, y) a few lines below, for this version: placed_lines can't see those (no literal x / y)."""
    sc = version_scope(text, ws.v)
    L = text.splitlines()
    out = []
    for i, line in enumerate(L):
        m = LOOP.search(line)
        if not m or sc[i] is False:
            continue
        vals = [float(v) for v in m[2].split(",") if v.strip()]
        rx = re.compile(r"\bitem\(\s*(?:" + m[1] + r"\s*,\s*(-?[\d.]+)|(-?[\d.]+)\s*,\s*" + m[1] + r"\b)")
        for j in range(i, min(i + 4, len(L))):  # every row the loop places: the dining chairs' N and S rows (e2e J210 r4)
            if (a := rx.search(L[j])):
                out += [(j + 1, v, float(a[1]), [line, L[j]]) if a[1] else (j + 1, float(a[2]), v, [line, L[j]]) for v in vals]
                if not re.search(r"\]\)\s*\{\s*(//.*)?$", line):
                    break  # a one-line loop places one row
    return out


def comment_only(before, after):
    """True when furnish.js text `after` differs from `before` (bytes or str) only in // comments and spacing."""
    if before is None:
        return False
    code = lambda s: [c for l in (s.decode() if isinstance(s, bytes) else s).splitlines()
                      if (c := re.sub(r"\s+", "", re.sub(r"(^|\s)//.*$", "", l)))]
    return code(before) == code(after)


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
                                              "plus the plan's furniture outlines (2furni) there, with handles for move_piece / resize_piece. "
                                              "An outline stored inside a block has a handle INSERT/ENTITY (e.g. A25/A28): use it as usual, "
                                              "the edit explodes the block for you.",
     "parameters": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "radius": {"type": "number"}},
                    "required": ["x", "y"]}},
    {"name": "plan_rooms", "description": "The version's rooms: name, label position and floor extent in plan metres, plus ceiling/door/window heights and every opening (kind, centre, width, its own heights).",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "set_openings", "description": "Heights, glass and kind of doors / windows / sliders, which the plan doesn't hold (it only knows "
                                            "where they are). openings: [{at: [x, y] plan metres inside the opening (plan_rooms lists them), "
                                            "sill? head? (m above the floor; a door or slider takes head only), frosted? (true/false), "
                                            "kind? (window | slider | door: what it is built as, e.g. a terrace slider kept a window), "
                                            "panel? (glass | wood: a slider's leaf), frame? leaf? handle? (materials.js name or \"#rrggbb\"; handle also "
                                            "brass | black | chrome | nickel | none), glass? (clear | frosted | tinted | bronze | "
                                            "reflective), panes? transoms? (bars), style? (door: flush | panelled | glazed | louvred | "
                                            "hidden; slider: bifold | pocket | barn), arch? (true), fanlight? (m of glass over a door), "
                                            "shape? (round window), clear?: true (back to the defaults)}]; home?: {ceiling?, door?, "
                                            "sill?, window?, slider?, parapet?, parapetGlass? (true: every terrace parapet a glass balustrade)} home-wide "
                                            "heights in m. For this version only; the 3D is rebuilt.",
     "parameters": {"type": "object", "properties": {"openings": {"type": "array", "items": {"type": "object"}},
                                                     "home": {"type": "object"}}}},
    {"name": "set_room", "description": "A room's finishes and settings, this version only: room (its name, as plan_rooms gives it); "
                                        "floor, walls (paint above any tiles), tiles (wall tiles), ceiling: a materials.js name or a "
                                        "colour \"#rrggbb\" (floor also wood | tile | decking); tileHeight (m, 0 = none; wet rooms "
                                        "default to the ceiling); skirting (height in m, 0 = none, or {height, material}); "
                                        "ceilingHeight (m, this room only); floorLevel (m: + a raised platform, - sunken; furniture in "
                                        "it follows); light {brightness: x the default 0-4, warmth: warm | neutral | cool | \"#rrggbb\"}; "
                                        "skylights [{at: [x, y], w, d}]; kind (wet | dry | outdoor); a key set to null goes back to "
                                        "the default; clear: true resets the room.",
     "parameters": {"type": "object", "properties": {"room": {"type": "string"}}, "required": ["room"]}},
    {"name": "set_home", "description": "notes: [{at: [x, y], text}] pinned on the plan (or {at, remove: true}); start: [x, y] where "
                                        "the walk-through starts (null = the front door).",
     "parameters": {"type": "object", "properties": {"notes": {"type": "array", "items": {"type": "object"}},
                                                     "start": {"type": ["array", "null"]}}}},
    {"name": "measure", "description": "Floor area, perimeter and net wall area (doors / windows taken off) per room, or room: one "
                                       "room, for questions and quantities (paint, tiles, flooring, skirting). Changes nothing.",
     "parameters": {"type": "object", "properties": {"room": {"type": "string"}}}},
    {"name": "save_picture", "description": "Keep the user's reference picture `ref` (1 = the first) as a material mat.pic<Name> "
                                            "(name), for a photo in a frame / a print (size 0) or a repeating sample (size = m one "
                                            "repeat covers: a tile, a fabric).",
     "parameters": {"type": "object", "properties": {"ref": {"type": "integer"}, "name": {"type": "string"},
                                                     "size": {"type": "number"}}, "required": ["ref", "name"]}},
    {"name": "find_model", "description": "Search the model library (Poly Haven CC0: sofas, armchairs, tables, beds, cabinets, "
                                          "lamps, chandeliers, vases, clocks, plants, ...) for a real 3D model of a piece instead of "
                                          "boxes: words (e.g. \"armchair mid century\"). Gives id, size (w, h, d m) and the line to use.",
     "parameters": {"type": "object", "properties": {"words": {"type": "string"}}, "required": ["words"]}},
    {"name": "save_progress", "description": "Save what's done so far (checked like a final save), so a big job keeps it if "
                                             "it runs out of time; then carry on. summary: what this part did.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}}},
    {"name": "dxf_query", "description": "Entities of the version's plan DXF inside a box (plan metres), optionally only some layers "
                                        "(1wall, Windows, 3door, 2furni, Glass, _DIM, ISLAK). Gives handles for dxf_edit. What furniture "
                                        "blocks hold is listed too, with a handle INSERT/ENTITY and inside_block: move_piece / resize_piece / "
                                        "set_points / move / delete take it (the block is exploded; the result's handles_remapped gives the new handles).",
     "parameters": {"type": "object", "properties": {"x0": {"type": "number"}, "y0": {"type": "number"}, "x1": {"type": "number"}, "y1": {"type": "number"},
                                                     "layers": {"type": "string", "description": "comma-separated"}},
                    "required": ["x0", "y0", "x1", "y1"]}},
    {"name": "dxf_edit", "description": "Edit the version's plan DXF (plan metres). ops: move {handles,dx,dy}; copy {handles,dx,dy}; delete {handles} (a detail line inside a piece that stays is kept unless detail: true); "
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
                                       "add_opening {at [x,y] on a solid wall, kind: window | glass_slider | door | sliding_door | opening (bare doorway), width?, hinge? (door: the end it hangs from, N/S/E/W or start/end), opens? (door: the side it swings into, N/S/E/W), sill? head? frosted?}: cuts both wall faces, adds jambs and draws it. "
                                       "convert_opening {at [x,y] inside the opening, or handle (a window line, a swing ARC or a 3door INSERT), to: a kind above or wall, width?, shift? (m along the wall), hinge?, opens?, sill? head? frosted?}: empties the opening and redraws it as `to`; also flips a door (to door with the other hinge / opens) and turns a block door into a loose one. "
                                       "remove_opening {at or handle}: walls it up. Heights / glass given here are stored for the 3D like set_openings. "
                                       "More kinds: double_door (1.0-2.6 m, two leaves), pocket_door, barn_door, bifold_door. "
                                       "WALLS (never add_line / delete face lines by hand): add_wall {a, b (centre line), thickness? 0.12, align? centre|left|right, through? [x,y] (a curve), height? (a low wall), glass? (a glass wall)}: "
                                       "ends at an existing wall are joined to it (T-junction), free ends capped; remove_wall {at}: junction to junction, with its doors / windows, the walls it met closed; "
                                       "move_wall {at, dx, dy}: slides across itself, the walls meeting it follow; set_wall_thickness {at, thickness, keep? (the face that stays, N/S/E/W)}; "
                                       "mark_wall {at, height?, glass?}: an existing wall made low / glass (a glass balustrade, a half wall). "
                                       "ROOMS: rename_room {name or at, to}; add_room_label {at, name} (a new room needs one: its kind follows the name). "
                                       "NICHES: add_niche {at on the wall face, width, depth, bottom, top, side?}. "
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


def norm_ops(ops):
    """dxf_edit ops in the one shape edit_ai_dxf.py takes ({"op": ..., ...}), and why any were dropped. Models also send
    {"move_window": {...}}, {"type": "move_piece", ...}, {"delete": [handles]} and {"handle", "dx", "dy"} with no op:
    each cost a step as "unknown op None" (e2e J213 / J218 r3). A zero move or turn changes nothing but read as a plan
    change that kept 2D and 3D "in step" (an armchair turned in 3D only: e2e J206 / J211 r3)."""
    out, dropped = [], []
    for o in ops or []:
        if not isinstance(o, dict):
            dropped.append(f"{str(o)[:60]} isn't an op")
            continue
        if "op" not in o and len(o) == 1 and isinstance(next(iter(o.values())), dict):
            k_, v_ = next(iter(o.items()))
            o = {"op": k_, **v_}
        elif "op" not in o and isinstance(o.get("type"), str) and o["type"] not in ("LINE", "LWPOLYLINE", "ARC", "CIRCLE", "INSERT"):
            o = {"op": o["type"], **{k_: v_ for k_, v_ in o.items() if k_ != "type"}}
        elif "op" not in o and isinstance(o.get("delete"), list):
            o = {"op": "delete", "handles": o["delete"], **{k_: v_ for k_, v_ in o.items() if k_ != "delete"}}
        elif "op" not in o and o.get("handle"):
            o = {"op": "rotate_piece" if "angle" in o else "resize_piece" if any(k_ in o for k_ in ("grow", "x_size", "y_size"))
                 else "move_piece", **o}
        k = o.get("op")
        if k == "delete" and not o.get("handles"):
            dropped.append("a delete with no handles (list the handles to delete)")
            continue
        zero = lambda: abs(float(o.get("dx") or 0)) < 1e-6 and abs(float(o.get("dy") or 0)) < 1e-6
        if (k in ("move", "move_piece") and zero()) or (k in ("rotate", "rotate_piece") and zero() and abs(float(o.get("angle") or 0)) < 1e-6):
            dropped.append(f"{k} {o.get('handle') or o.get('handles')} by nothing (a zero move / turn changes nothing on the plan)")
            continue
        out.append(o)
    return out, dropped


def tool(ws, name, a):
    v = ws.v
    if name == "grep":
        rx = re.compile(a["pattern"], re.I)
        paths = [a["path"]] if a.get("path") else readable(v)
        hits, other = [], 0
        for p in paths:
            if p not in readable(v):
                return f"{p} isn't readable here. Readable: {', '.join(readable(v))}"
            sc_ = version_scope(ws.text(p), v) if p == "furnish.js" else None
            for i, line in enumerate(ws.text(p).splitlines(), 1):
                if rx.search(line):
                    off_ = sc_ is not None and sc_[i - 1] is False  # another version's branch: editing it changes nothing here
                    other += off_
                    hits.append(f"{p}:{i}: {line[:240]}" + (f"   [other versions only: doesn't run for {v}]" if off_ else ""))
                    if len(hits) >= 40:
                        return "\n".join(hits) + "\n[more matches cut; narrow the pattern]"
        if hits and other == len(hits):
            hits.append(f"[every match is in another version's branch: in {v} the piece is built elsewhere, maybe without these "
                        "words (find it with furniture_near at the plan point and read its build)]")
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
                    ps = d.get("points") or ([d["bbox"][:2], d["bbox"][2:]] if d.get("bbox") else [])  # long ones come as a bbox
                    if d["type"] == "LWPOLYLINE" and (len(ps) >= 4 or d.get("n_points", 0) >= 4):
                        xs, ys = [p[0] for p in ps], [p[1] for p in ps]
                        if (max(xs) - min(xs)) * (max(ys) - min(ys)) >= 0.04:
                            boxes.append((min(xs), min(ys), max(xs), max(ys)))
                            pieces.append(f"{d['handle']}: x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}"
                                          + (f" (in block {d['inside_block']})" if d.get("inside_block") else ""))
            except Exception:
                pass
        out, on_box = [], {}
        for i, px, py, line in placed_lines(ws, text):  # near the point, or standing on a plan outline found here
            near = ((px - x) ** 2 + (py - y) ** 2) ** 0.5 <= rad
            on = any(b[0] - 0.15 <= px <= b[2] + 0.15 and b[1] - 0.15 <= py <= b[3] + 0.15 for b in boxes)
            for k_, b in enumerate(boxes):  # which 3D items stand on (the back edge of) each outline
                if b[0] - 0.03 <= px <= b[2] + 0.03 and b[1] - 0.03 <= py <= b[3] + 0.03 and stands_on_floor(text, i, line):
                    on_box.setdefault(k_, []).append(i)
            if near or on:
                out.append(f"furnish.js:{i}: {line.strip()[:240]}")
        # One outline drawn round several 3D pieces (a dressing table and the shoe towers beside it): its size is
        # theirs together, not one piece's.
        smallest = {}
        for k_, ls in on_box.items():
            for i in ls:
                if i not in smallest or (boxes[k_][2] - boxes[k_][0]) * (boxes[k_][3] - boxes[k_][1]) < \
                        (boxes[smallest[i]][2] - boxes[smallest[i]][0]) * (boxes[smallest[i]][3] - boxes[smallest[i]][1]):
                    smallest[i] = k_
        for k_ in range(len(pieces)):
            mine_ = sorted(i for i, kk in smallest.items() if kk == k_)
            if len(mine_) >= 2:
                pieces[k_] += (f" (ONE outline round {len(mine_)} 3D pieces, furnish.js lines {', '.join(map(str, mine_))}: "
                               "each piece's own size is in its build, not this outline's; resizing one of them only has "
                               "the room its neighbours leave, and the outline changes only by what the group's edge does)")
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
        ops_ = []
        for o in m.get("openings", []):
            xs, ys = [q[0] for q in o["outer"]], [q[1] for q in o["outer"]]
            ops_.append({"kind": o["kind"], "centre": [round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3)],
                         "width": round(max(max(xs) - min(xs), max(ys) - min(ys)), 2),
                         **{k: o[k] for k in ("sill", "head", "frosted", "panel") if k in o}})
        return json.dumps({"heights": {k: m[k] for k in ("ceiling", "doorHead", "sill", "winHead", "sliderHead")},
                           "bounds": m["bounds"], "labels": labels, "floor_areas": floors, "openings": ops_})[:9000]
    if name == "set_openings":
        return set_openings(ws, a)
    if name == "set_room":
        return set_room(ws, a)
    if name == "set_home":
        return set_home(ws, a)
    if name == "measure":
        return measure(ws, a)
    if name == "save_picture":
        return save_picture(ws, a, getattr(ws, "refs", []))
    if name == "find_model":
        return find_model(a.get("words", ""))
    if name == "save_progress":
        return save_progress(ws, getattr(ws, "message", ""), a.get("summary", ""))
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
        ops_, dropped_ = norm_ops(a.get("ops"))
        pm_ = {o.get("handle") for o in ops_ if isinstance(o, dict) and o.get("op") in ("move_piece", "resize_piece")}
        dup_ = [o for o in ops_ if isinstance(o, dict) and o.get("op") == "move" and o.get("handles")
                and set(o["handles"]) <= pm_]
        ops_ = [o for o in ops_ if not any(o is d_ for d_ in dup_)]  # the same piece moved twice in one call
        # the same piece moved by the same amount again in this message (the edit's move re-sent in the fix round):
        # the plan keeps every earlier move, so it went twice as far (e2e J229 / J263 r3)
        led_ = getattr(ws, "plan_moves", {})
        again_ = [o for o in ops_ if o.get("op") in ("move", "move_piece") and not o.get("again")
                  and any(abs(float(o.get("dx") or 0) - m_[0]) < 1e-4 and abs(float(o.get("dy") or 0) - m_[1]) < 1e-4
                          for h_ in ([o.get("handle")] if o.get("op") == "move_piece" else o.get("handles") or []) for m_ in led_.get(h_, []))]
        for o in again_:
            hs_ = [o.get("handle")] if o.get("op") == "move_piece" else o.get("handles") or []
            dropped_.append(f"{o['op']} {', '.join(map(str, hs_))} by ({o.get('dx')}, {o.get('dy')}): it was ALREADY moved by exactly that "
                            "earlier in this edit and the plan keeps that move, so sending it again would move it twice as far. "
                            "Leave it (if you really mean a second move on top, send it with \"again\": true)")
        ops_ = [o for o in ops_ if not any(o is d_ for d_ in again_)]
        if not ops_:
            return "nothing changed: " + ("; ".join(dropped_) if dropped_ else "no ops given")
        a = {**a, "ops": ops_}
        if any(o.get("op") == "rotate_piece" for o in ops_ if isinstance(o, dict)):
            ws.rotated = True  # a plan piece turned (the facing check in review())
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
        for o in ops_:  # this message's plan moves, by handle (the ledger above)
            if o.get("op") in ("move", "move_piece"):
                for h_ in ([o.get("handle")] if o.get("op") == "move_piece" else o.get("handles") or []):
                    ws.plan_moves = {**getattr(ws, "plan_moves", {})}
                    ws.plan_moves.setdefault(h_, []).append((float(o.get("dx") or 0), float(o.get("dy") or 0)))
        if "cm FREE that way" in out:
            ws.clamped = True  # the plan stopped a move short: the reply says so (the distance check stands down)
        if dropped_:  # after the JSON, which is read below
            out += "\nNOT DONE (the rest was applied): " + "; ".join(dropped_)
        out_path.replace(ws.dxf())
        ws.write(ws.cfg["dxf"], ws.dxf().read_bytes())
        ws.plan_dirty = True
        try:
            rep_ = json.JSONDecoder().raw_decode(out.lstrip())[0]  # stderr may trail the JSON
            same_ = lambda a_, b_: a_ and b_ and all(abs(u_ - w_) < 0.001 for u_, w_ in zip(a_, b_))
            real_ = [pc for pc in rep_.get("pieces_changed", []) if not same_(pc["old"], pc["new"])]
            noop_ = "pieces_changed" in rep_ and not real_ and not any(
                k_ in ("2furni", "2 furni") for k_ in rep_.get("layer_count_change", {}))
            ws.dxf_furni = ws.dxf_furni or (rep_.get("furniture_changed", False) and not noop_)
            for pc in real_:
                if pc.get("block"):
                    ws.blocks = getattr(ws, "blocks", set()) | {pc["handle"]}
                ws.pieces.setdefault(pc["handle"], pc["old"])
                ws.pieces_now = {**getattr(ws, "pieces_now", {}), pc["handle"]: pc["new"]}
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
            asks_ = [o for o in ops_ if o.get("op") in ("add_opening", "convert_opening", "remove_opening")]
            for o_, ch_ in zip(asks_, rep_.get("openings_changed", [])):
                opening_spec(ws, ch_, o_)
            plan_specs(ws, {**rep_, "walls_changed": [{**w_, **{k_: o_[k_] for k_ in ("height", "glass") if o_.get(k_) is not None}}
                                                      for w_, o_ in zip(rep_.get("walls_changed", []),
                                                                        [o for o in ops_ if o.get("op") in ("add_wall", "remove_wall", "move_wall", "set_wall_thickness", "mark_wall")])]})
        except ValueError:
            pass
        try:  # what hangs in a moved window (sheers, curtains) has to follow it in furnish.js
            for w in json.JSONDecoder().raw_decode(out.lstrip())[0].get("windows_moved", []):
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
        for p in OWN:
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


# --- Opening specs: what the plan doesn't hold (heights, glass, the kind an opening is built as) ------------------------
# They live in the version's tour JSON ("openings", "heights"; DWG coordinates), which build_geometry.py reads, so a
# change stays in this version and the manual build (build_version.py) builds the same.
HOME_HEIGHTS = {"ceiling": (2.2, 4.0), "door": (1.8, 3.0), "sill": (0.0, 2.0), "window": (0.5, 3.5), "slider": (1.8, 3.5),
                "parapet": (0.3, 2.0)}


def dump_tour(t):
    """The tour JSON in its own compact style: one key per line, a list of objects one per line."""
    out = []
    for k, v in t.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            val = "[\n" + ",\n".join("    " + json.dumps(x, ensure_ascii=False) for x in v) + "\n  ]"
        else:
            val = json.dumps(v, ensure_ascii=False)
        out.append(f"  {json.dumps(k)}: {val}")
    return "{\n" + ",\n".join(out) + "\n}\n"


def _tour(ws):
    return json.loads(ws.text(ws.cfg["tour"]))


def _dwg(pt):
    return [round(pt[0] + ORIGIN[0], 4), round(pt[1] + ORIGIN[1], 4)]


def _drop_specs(t, box, pad=0.05, hinges=True):
    """Specs (and shown-as-drawn door hinges) inside a plan box [[x0, y0], [x1, y1]] go: that opening is redone."""
    (x0, y0), (x1, y1) = box
    x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    inb = lambda q, m: x0 - m <= q[0] - ORIGIN[0] <= x1 + m and y0 - m <= q[1] - ORIGIN[1] <= y1 + m
    t["openings"] = [o for o in t.get("openings", []) if not inb(o["at"], pad)]
    if hinges and "doorsAsDrawn" in t:
        t["doorsAsDrawn"] = [h for h in t["doorsAsDrawn"] if not inb(h, 0.25)]
    if not t["openings"]:
        t.pop("openings")


def _spec_fields(o):
    f = {}
    for k in ("sill", "head"):
        if o.get(k) is not None:
            f[k] = round(float(o[k]), 3)
    if o.get("frosted") is not None:
        f["frosted"] = bool(o["frosted"])
    if "sill" in f and "head" in f and f["head"] <= f["sill"] + 0.2:
        raise ValueError(f"head {f['head']} m must be well above sill {f['sill']} m")
    return f


def opening_spec(ws, ch, o):
    """After add / convert / remove_opening: the tour's spec for that opening (kind, heights, panel; a door's hinge
    shown as drawn), any older spec in its place dropped."""
    t = _tour(ws)
    bx = [ch["box"][0], ch["box"][1]] + ([ch["old_box"][0], ch["old_box"][1]] if ch.get("old_box") else [])
    _drop_specs(t, [[min(q[0] for q in bx), min(q[1] for q in bx)], [max(q[0] for q in bx), max(q[1] for q in bx)]])
    f, k = _spec_fields(o), ch["kind"]
    f.update(_look_fields(ws, o))
    door_h = (t.get("heights") or {}).get("door", 2.1)
    slide = lambda style: {"kind": "slider", "panel": "wood", "head": door_h, **({"style": style} if style else {}), **f}
    f = {"window": {"kind": "window", **f}, "glass_slider": {"kind": "slider", "panel": "glass", **f},
         "sliding_door": slide(None), "pocket_door": slide("pocket"), "barn_door": slide("barn"), "bifold_door": slide("bifold"),
         "door": f, "double_door": f}.get(k, {})
    if k != "window":
        f.pop("sill", None)
    if f:
        spec = {"at": _dwg(ch["centre"]), **f}
        if f.get("kind") and ch.get("box"):  # the doorway's own box: the build makes it an opening even if nothing else does
            spec["box"] = [_dwg(ch["box"][0]), _dwg(ch["box"][1])]
        t.setdefault("openings", []).append(spec)
    for h in ch.get("hinges") or ([ch["hinge"]] if ch.get("hinge") else []):
        t.setdefault("doorsAsDrawn", []).append(_dwg(h))
    ws.write(ws.cfg["tour"], dump_tour(t).encode())


LOOKS = {"frame": "material", "leaf": "material", "glass": ("clear", "frosted", "tinted", "bronze", "reflective"),
         "panes": int, "transoms": int, "style": ("flush", "panelled", "glazed", "louvred", "hidden", "bifold", "pocket", "barn"),
         "handle": "material", "arch": bool, "fanlight": float, "shape": ("rect", "round")}
FLOOR_WORDS = ("wood", "tile", "decking")


def material_names(ws):
    """The materials furnish / the specs may name: materials.js's library (this message's version of it)."""
    src = ws.text("materials.js")
    lib = src[src.find("const M = {"):src.find("M.oakVeneer.color")] or src  # the library object, not helper options
    return set(re.findall(r"^\s{4}([A-Za-z]\w*):", lib, re.M))


def check_material(ws, v, what):
    v = str(v).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", v) or v in FLOOR_WORDS or v in material_names(ws) or \
            v in ("brass", "black", "chrome", "nickel", "none"):
        return v
    raise ValueError(f"{what}: {v!r} isn't a material. Use a colour like \"#a3b18a\" or one of materials.js: "
                     f"{', '.join(sorted(material_names(ws)))[:900]}")


def _look_fields(ws, o):
    f = {}
    for k, kind in LOOKS.items():
        if o.get(k) is None:
            continue
        v = o[k]
        if kind == "material":
            f[k] = check_material(ws, v, k)
        elif isinstance(kind, tuple):
            if v not in kind:
                raise ValueError(f"{k} is one of {', '.join(kind)}")
            f[k] = v
        else:
            f[k] = kind(v)
    return f


ROOM_KEYS = {"kind": ("wet", "dry", "outdoor"), "floor": "material", "walls": "material", "tiles": "material",
             "tileHeight": (0.0, 4.0), "skirting": None, "ceiling": "material", "ceilingHeight": (2.0, 4.5),
             "floorLevel": (-0.6, 0.8), "light": None, "skylights": None}


def _room_names(ws):
    s_ = ws.text(ws.cfg["model"])
    m = json.loads(s_[s_.index("{"):s_.rindex("}") + 1])
    return {f["room"] for f in m.get("floor", [])} | {l["text"] for l in m.get("labels", [])}


def set_room(ws, a):
    """The set_room tool: a room's finishes, kind, heights, level, light and skylights, in the tour's "rooms"."""
    if ws.plan_dirty:
        rebuild(ws)
        ws.plan_dirty = False
    names = _room_names(ws)
    name = str(a.get("room") or "").strip().upper().rstrip(".")
    if name not in {n.upper() for n in names}:
        raise ValueError(f"no room {name!r}; rooms: {', '.join(sorted(names))}")
    name = next(n for n in names if n.upper() == name)
    t = _tour(ws)
    rooms = t.setdefault("rooms", {})
    spec = {} if a.get("clear") else dict(rooms.get(name) or {})
    for k, rule in ROOM_KEYS.items():
        if k not in a:
            continue
        v = a[k]
        if v is None:
            spec.pop(k, None)
        elif rule == "material":
            spec[k] = check_material(ws, v, k)
        elif isinstance(rule, tuple) and isinstance(rule[0], str):
            if v not in rule:
                raise ValueError(f"{k} is one of {', '.join(rule)}")
            spec[k] = v
        elif isinstance(rule, tuple):
            if not rule[0] <= float(v) <= rule[1]:
                raise ValueError(f"{k} {v} is outside {rule[0]}..{rule[1]} m")
            home_c = float((t.get("heights") or {}).get("ceiling", 2.6))
            if k == "ceilingHeight" and float(v) > home_c + 0.001:  # walls stop at the home ceiling: a gap above them
                raise ValueError(f"a room's ceiling can only go down from the home's ({home_c} m). For a taller room, "
                                 f"raise the home ceiling (set_openings home ceiling) and set the other rooms' "
                                 f"ceilingHeight back to {home_c}")
            spec[k] = round(float(v), 3)
        elif k == "skirting":  # a height (0 = none) or {height, material}
            spec[k] = round(float(v), 3) if isinstance(v, (int, float)) else \
                {"height": round(float(v.get("height", 0.08)), 3), **({"material": check_material(ws, v["material"], "skirting")} if v.get("material") else {})}
        elif k == "light":
            spec[k] = {kk: (vv if kk == "warmth" else round(max(0.0, min(4.0, float(vv))), 2)) for kk, vv in (v or {}).items()
                       if kk in ("brightness", "warmth")}
        elif k == "skylights":
            spec[k] = [{"at": [round(float(x), 3) for x in sk["at"]], "w": round(float(sk.get("w", 0.8)), 2),
                        "d": round(float(sk.get("d", 0.8)), 2)} for sk in (v or [])]
    finishes = t.get("finishes") or {}
    if spec.get("floor") in FLOOR_WORDS:  # the plain finishes stay where the 2D legend reads them
        finishes[name] = spec.pop("floor")
        t["finishes"] = finishes
    if spec:
        rooms[name] = spec
    else:
        rooms.pop(name, None)
    if not rooms:
        t.pop("rooms")
    ws.write(ws.cfg["tour"], dump_tour(t).encode())
    ws.plan_dirty = True
    ws.model0 = getattr(ws, "model0", ws.read(ws.cfg["model"]))
    return f"{name}: {spec or 'defaults'}" + (f" (floor {finishes[name]})" if name in finishes else "") + \
        " - the 3D is rebuilt when you finish (check rebuilds it now)"


def plan_specs(ws, rep):
    """After a dxf_edit: the tour's specs that follow plan edits (low / glass walls, niches, renamed rooms)."""
    t, touched = _tour(ws), False
    for w in rep.get("walls_changed", []):
        a, b = _dwg(w["a"]), _dwg(w["b"])
        if w["op"] in ("remove_wall", "move_wall", "set_wall_thickness") or w.get("height") is not None or w.get("glass") is not None:
            seg = [(a[0], a[1]), (b[0], b[1])]
            near = lambda o: _seg_dist(seg, o["a"]) < 0.2 and _seg_dist(seg, o["b"]) < 0.2
            before = len(t.get("walls", []))
            t["walls"] = [o for o in t.get("walls", []) if not near(o)]
            touched |= len(t["walls"]) != before
        if w["op"] in ("add_wall", "mark_wall", "move_wall", "set_wall_thickness") and (w.get("height") is not None or w.get("glass")):
            mv = w.get("moved") or [0, 0]
            t.setdefault("walls", []).append({"a": [a[0] + mv[0], a[1] + mv[1]], "b": [b[0] + mv[0], b[1] + mv[1]],
                                              "thickness": w["thickness"], **({"height": float(w["height"])} if w.get("height") is not None else {}),
                                              **({"glass": True} if w.get("glass") else {})})
            touched = True
        if not t.get("walls"):
            t.pop("walls", None)
    for nc in rep.get("niches", []):
        t.setdefault("niches", []).append({"box": [_dwg(z) for z in nc["box"]], "bottom": nc["bottom"], "top": nc["top"]})
        touched = True
    for rn in rep.get("rooms_renamed", []):
        old, new = rn.get("old"), rn["new"]
        if not old:
            continue
        for key in ("rooms", "finishes"):
            for k in list((t.get(key) or {})):
                if k.upper().rstrip(".") == old:
                    t[key][new] = t[key].pop(k)
                    touched = True
        for st in t.get("stops", []):
            if str(st.get("room", "")).upper().rstrip(".") == old:
                st["room"] = new
                touched = True
        for sd in t.get("seeds", []):
            if str(sd.get("name", "")).upper().rstrip(".") == old:
                sd["name"] = new
                touched = True
    if touched:
        ws.write(ws.cfg["tour"], dump_tour(t).encode())


def _seg_dist(seg, pt):
    (x1, y1), (x2, y2) = seg
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy or 1e-9
    k = max(0, min(1, ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / L2))
    return math.hypot(pt[0] - x1 - k * dx, pt[1] - y1 - k * dy)


def set_home(ws, a):
    """The set_home tool: notes pinned on the plan and where the walk-through starts."""
    t, log = _tour(ws), []
    for n in a.get("notes") or []:
        if n.get("remove"):
            before = len(t.get("notes", []))
            t["notes"] = [x for x in t.get("notes", []) if math.dist(_dwg(n["at"]), x["at"]) > 0.4]
            log.append(f"removed {before - len(t['notes'])} note(s) near {n['at']}")
        else:
            t.setdefault("notes", []).append({"at": _dwg(n["at"]), "text": str(n["text"])[:200]})
            log.append(f"note at {n['at']}: {n['text'][:80]}")
    if not t.get("notes"):
        t.pop("notes", None)
    if a.get("start") is not None:
        if a["start"]:
            t["start"] = _dwg(a["start"])
        else:
            t.pop("start", None)
        log.append(f"walk-through starts at {a['start'] or 'the front door'}")
    ws.write(ws.cfg["tour"], dump_tour(t).encode())
    ws.plan_dirty = True
    return "; ".join(log) or "nothing to change"


def _ring_area(r_):
    return abs(sum(r_[i - 1][0] * r_[i][1] - r_[i][0] * r_[i - 1][1] for i in range(len(r_)))) / 2


def _ring_len(r_):
    return sum(math.dist(r_[i - 1], r_[i]) for i in range(len(r_)))


def measure(ws, a):
    """The measure tool: floor area, wall length and paintable / tileable wall area per room (or the whole home),
    with door / window areas taken off, for quantities (paint, tiles, skirting, flooring)."""
    if ws.plan_dirty:
        rebuild(ws)
        ws.plan_dirty = False
    s_ = ws.text(ws.cfg["model"])
    m = json.loads(s_[s_.index("{"):s_.rindex("}") + 1])
    want = str(a.get("room") or "").upper().rstrip(".")
    rooms = {}
    for f in m.get("floor", []):
        r_ = rooms.setdefault(f["room"], {"kind": f["kind"], "floor_m2": 0.0, "perimeter_m": 0.0})
        r_["floor_m2"] += _ring_area(f["outer"]) - sum(_ring_area(h) for h in f.get("holes", []))
        r_["perimeter_m"] += _ring_len(f["outer"])
    out, ch = [], m.get("ceiling", 2.6)
    for name, r_ in sorted(rooms.items()):
        if want and name.upper() != want:
            continue
        spec = (m.get("rooms") or {}).get(name, {})
        h = spec.get("ceilingHeight", ch)
        holes = 0.0
        for o in m.get("openings", []):  # openings on this room's edge: their wall area doesn't get paint / tiles
            if any(min(math.dist(q, z) for z in f["outer"]) < 0.4 for f in m["floor"] if f["room"] == name for q in o["outer"]):
                xs, ys = [q[0] for q in o["outer"]], [q[1] for q in o["outer"]]
                w = max(max(xs) - min(xs), max(ys) - min(ys))
                top = o.get("head", m["doorHead"] if o["kind"] == "door" else m["sliderHead"] if o["kind"] == "slider" else m["winHead"])
                holes += w * (top - (o.get("sill", m["sill"]) if o["kind"] == "window" else 0))
        out.append({"room": name, "kind": r_["kind"], "floor_m2": round(r_["floor_m2"], 2), "perimeter_m": round(r_["perimeter_m"], 2),
                    "ceiling_m": h, "wall_m2_net": round(max(0.0, r_["perimeter_m"] * h - holes), 2)})
    if want and not out:
        raise ValueError(f"no room {want!r}; rooms: {', '.join(sorted(rooms))}")
    tot = {"floor_m2": round(sum(r_["floor_m2"] for r_ in out), 2), "wall_m2_net": round(sum(r_["wall_m2_net"] for r_ in out), 2)}
    return json.dumps({"rooms": out, "total": tot, "notes": m.get("notes", []),
                       "hint": "add ~10% for tile / flooring cuts; paint coverage ~10 m2 per litre per coat"})[:8000]


def save_picture(ws, a, refs):
    """The save_picture tool: one of the user's reference pictures kept as a texture (a photo in a frame, a print,
    a tile or fabric sample) and a material for it in materials.js."""
    k = int(a.get("ref", 1)) - 1
    if not 0 <= k < len(refs):
        raise ValueError(f"there are {len(refs)} reference pictures; ref is 1..{len(refs)}")
    head, b64 = refs[k].split(",", 1)
    ext = "png" if "png" in head else "webp" if "webp" in head else "jpg"
    data = base64.b64decode(b64)
    name = re.sub(r"[^A-Za-z0-9]", "", str(a.get("name") or "picture"))[:24] or "picture"
    key = "pic" + name[0].upper() + name[1:]
    path = f"uploads/{key}-{hashlib.sha1(data).hexdigest()[:8]}.{ext}"
    ws.write(path, data)
    size = float(a.get("size") or 0)  # > 0: a repeating sample (tile / fabric) that wide; 0: one picture fills the surface
    src = ws.text("materials.js")
    line = f"    {key}: std({{ map: picture(\"{path}\", {size}), roughness: 0.8 }}),\n"
    if re.search(rf"^\s{{4}}{key}:", src, re.M):
        src = re.sub(rf"^\s{{4}}{key}:.*\n", line, src, flags=re.M)
    else:
        src = src.replace("    art: [\n", line + "    art: [\n", 1)
    ws.write("materials.js", src.encode())
    return f"saved as mat.{key} ({path}); use it in furnish.js like any material, e.g. on a frame's picture face"


def find_model(words):
    """The find_model tool: library models whose name / categories / tags match the words, best first."""
    lib = json.loads((ROOT / "docs" / "edit-ai" / "model-library.json").read_text())["models"]  # not models/: the function bundle leaves that out
    ws_ = [w for w in re.findall(r"[a-z0-9]+", words.lower()) if len(w) > 1]
    if not ws_:
        raise ValueError("say what to look for, e.g. \"armchair\" or \"ceiling lamp\"")
    hay = lambda m: " ".join([m["id"], m["name"], *m["cat"], *m["tags"]]).lower().replace("_", " ")
    scored = sorted(((sum(w in hay(m) for w in ws_), m) for m in lib), key=lambda x: -x[0])
    hits = [m for sc, m in scored if sc][:12]
    if not hits:
        return "nothing in the library matches; build it from boxes / cylinders as usual"
    return json.dumps([{"id": m["id"], "name": m["name"], "size": m["size"], "use": f'p.model("{m["url"]}", null, 0, 0, 0, '
                        f'{{ size: [{m["size"][0]}, {m["size"][1]}, {m["size"][2]}] }})'} for m in hits]) + \
        ("\nIn an item(...) build: size: [w, h, d] makes it exactly that big (scale the catalogue size to the real piece "
         "the user wants); it stands on y = 0 and its back sits at z = 0. Models may face another way: if its front "
         "doesn't face into the room, wrap it in a group rotated by Math.PI (or +-Math.PI / 2). A new piece gets a 2furni "
         "outline like any piece; a swap in place (this sofa for a real one) keeps the old outline as it is, no dxf_edit: "
         "size the model to that footprint, and an L-shaped piece stays an L (one model along each arm).")


def save_progress(ws, message, reply):
    """The save_progress tool: what's done so far saved now (checked like a final save), so a big job survives the
    time limit; the rest of the work carries on from it."""
    if not ws.changed:
        return "nothing to save yet"
    if ws.plan_dirty:
        rebuild(ws)
        ws.plan_dirty = False
    if (nudge := review(ws, message, reply or "")):
        return "not saved, fix this first: " + nudge[:800]
    if breaks := lock_breaks(ws, message):
        return "not saved: it breaks " + lock_note(breaks)
    res = save(ws, f"(part) {reply or message}"[:300])
    ws.saved_parts = getattr(ws, "saved_parts", 0) + 1
    for p in list(ws.changed):  # the saved state is the new starting point
        ws.orig[p] = ws.read(p)
    ws.changed.clear()
    ws.ops.clear()
    ws.man = latest(ws.v)
    ws.res = resolve(ws.man)
    return f"saved (revision {res['rev']}); keep going from here"


def set_openings(ws, a):
    """The set_openings tool: per-opening heights / glass / kind / panel and home-wide heights, in the tour."""
    if ws.plan_dirty:
        rebuild(ws)  # check `at` against the openings as they are now
        ws.plan_dirty = False
    s_ = ws.text(ws.cfg["model"])
    m = json.loads(s_[s_.index("{"):s_.rindex("}") + 1])
    t, log = _tour(ws), []

    def inside(ring, x, y):
        c = False
        for i in range(len(ring)):
            (x1, y1), (x2, y2) = ring[i], ring[i - 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
        return c
    for o in a.get("openings") or []:
        x, y = map(float, o["at"])
        hit = next((op for op in m.get("openings", []) if inside(op["outer"], x, y)), None)
        if hit is None:  # a point on the opening's edge: the nearest opening within 15 cm
            near = [(min(math.dist((x, y), q) for q in op["outer"]), op) for op in m.get("openings", [])]
            hit = min(near, key=lambda z: z[0])[1] if near and min(near, key=lambda z: z[0])[0] < 0.15 else None
        if hit is None:
            raise ValueError(f"no door / window / slider at {o['at']}: plan_rooms lists every opening's centre")
        xs, ys = [q[0] for q in hit["outer"]], [q[1] for q in hit["outer"]]
        c = [sum(xs) / len(xs), sum(ys) / len(ys)]
        box = [[min(xs), min(ys)], [max(xs), max(ys)]]
        old = next((sp for sp in t.get("openings", []) if inside(hit["outer"], sp["at"][0] - ORIGIN[0], sp["at"][1] - ORIGIN[1])), {})
        _drop_specs(t, box, pad=0, hinges=False)
        if o.get("clear"):
            log.append(f"{hit['kind']} at {[round(v, 3) for v in c]}: back to the defaults")
            continue
        f = {k: v for k, v in old.items() if k != "at"}
        f.update(_spec_fields(o))
        if o.get("kind") in ("window", "slider", "door"):
            f["kind"] = o["kind"]
        if o.get("panel") in ("glass", "wood"):
            f["panel"] = o["panel"]
        f.update(_look_fields(ws, o))
        if "sill" in f and "head" not in f and (f.get("kind") or hit["kind"]) == "window":
            f["head"] = hit.get("head", m.get("sliderHead") if hit["kind"] == "slider" else m.get("winHead"))
        if f:
            t.setdefault("openings", []).append({"at": _dwg(c), **f})
        log.append(f"{hit['kind']} at {[round(v, 3) for v in c]} ({round(max(max(xs) - min(xs), max(ys) - min(ys)), 2)} m): {f}")
    if a.get("home"):
        h = dict(t.get("heights") or {})
        home = dict(a["home"])
        if "parapetGlass" in home:  # every terrace parapet as a glass balustrade (or back to solid)
            if home.pop("parapetGlass"):
                t["parapet"] = {"glass": True}
            else:
                t.pop("parapet", None)
            log.append(f"terrace parapets: {'glass' if t.get('parapet') else 'solid'}")
        for k, v in home.items():
            if k not in HOME_HEIGHTS:
                raise ValueError(f"home heights are {', '.join(HOME_HEIGHTS)}, not {k!r}")
            lo, hi = HOME_HEIGHTS[k]
            if v is None:
                h.pop(k, None)
                continue
            if not lo <= float(v) <= hi:
                raise ValueError(f"{k} {v} m is outside {lo}-{hi} m")
            taller = [n for n, r_ in (t.get("rooms") or {}).items() if k == "ceiling" and float(r_.get("ceilingHeight", 0)) > float(v) + 0.001]
            if taller:  # walls stop at the home ceiling: a room above it would show a gap over its walls
                raise ValueError(f"{', '.join(taller)} has its own ceiling above {v} m; walls stop at the home ceiling. Keep "
                                 f"the home ceiling at least that high (a taller room = home ceiling up, the others' ceilingHeight back down)")
            h[k] = round(float(v), 3)
        t["heights"] = h
        if not h:
            t.pop("heights")
        log.append(f"home heights: {h or 'defaults'}")
    ws.write(ws.cfg["tour"], dump_tour(t).encode())
    ws.plan_dirty = True
    if not hasattr(ws, "model0"):
        ws.model0 = ws.read(ws.cfg["model"])
    return "set (the 3D is rebuilt when you finish; check rebuilds it now):\n" + "\n".join(log)


def lost_openings(ws):
    """A warning when the rebuilt 3D has fewer doors or windows than before this message."""
    if not hasattr(ws, "model0") or ws.cfg["model"] not in ws.changed:
        return None
    a, b = opening_counts(ws.model0), opening_counts(ws.read(ws.cfg["model"]))
    gone = {k: a[k] - b[k] for k in a if b[k] < a[k]}
    if not gone or sum(b.values()) >= sum(a.values()):  # none lost, or one turned into another kind (door -> window)
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
plan's south-west corner; heights in metres above the floor), with item(x, y, facing, build). furnish.js and materials.js \
here are version "{version}"'s own files: nothing you change in them can reach another version, so edit the lines \
directly and never add `version === ...` checks. Some `version === "..."` checks are left over from when the versions \
shared one file; only the branches that run for "{version}" matter, and the others never run here. materials.js holds the \
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
- When the plan (2D) is needed: floor-standing furniture and joinery, wall-fixed pieces reaching ~30 cm+ into the room \
below head height (~1.5 m), walls, doors, windows, new partitions, and any piece that already has a 2furni outline when \
its position or footprint changes. 3D-ONLY (furnish.js only, no DXF edit, no plan match needed): height; colour / \
finish; lights (pendant, sconce, LED cove); thin art / mirrors / TVs; AC units (ac(...)); plaster curtain boxes, AC \
bulkheads, ceiling boxes, soffits and ducted grille faces, i.e. anything whose lowest part stays above head height, \
including making it deeper from the wall (\"make this 1 m from the wall\" on a curtain / AC box = its box z1 and the \
grille faces on its front); pieces with no outline under them (furniture_near shows none). For those, edit furnish.js, \
run check and reply: never invent a 2furni outline for them and never discard because nothing on the plan matches. \
Unsure? read_file docs/edit-ai/when-2d-needed.md and docs/edit-ai/3d-only-patterns.md (project decision notes).
- Keep 3D and 2D together: a piece drawn on the plan (2furni) that you move or resize in furnish.js gets exactly the \
same change in the DXF (furniture_near gives its outline's handle: dxf_edit move_piece / resize_piece), and a DXF \
furniture change gets the same change in furnish.js. A TV, mirror or art that already has a plan outline (even one \
inside a block: handle INSERT/ENTITY) gets that outline resized too; never call a piece "built-in, no outline" without \
checking furniture_near / dxf_query there. A wall-hung piece's width runs along its wall: plan y when it faces E/W, plan \
x when it faces N/S; hit the exact size asked (outline x1-x0 / y1-y0). Move only the pieces asked for (plus their group, below): \
other neighbours stay unless the user wants them to follow, and then they move in both furnish.js and the DXF. A resize that leaves \
a neighbour overlapping or with an odd gap (bedside tables beside a narrower bed) moves that neighbour too, both views. A wall moved in the DXF must keep \
both faces, close its junctions exactly (snap endpoints to existing ones within 0.1 mm), and the furniture against it \
moves with it in furnish.js. A NEW wall or partition is two face lines ~0.11 m apart with short end caps, one end \
on an existing wall's face (unless the user wants it free-standing), clear of furniture outlines and leaving the \
walkways above; dxf_edit warns when it isn't.
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
the piece's current height. Never ignore a clear vertical difference between Mark 1 and Mark 2 on a wall. Move only \
that piece: if a loop places it together with others (`for (const x of [a, b])`), take it out into its own item() \
line and leave the others; if it is a part built inside a bigger piece (a pouf or stool under a dressing table), take \
just that part out into its own item() at Mark 2 and leave the bigger piece and its plan outline where they are.
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
- Doors, drawers, shelves, openables and finishes inside a piece whose outer size and place stay the same are 3D only (the plan outline is the footprint): rewrite the cabinet guts in furnish.js, do not touch the DXF, and do not discard for \"2D vs 3D\" — there is nothing on the plan to update. Same for \"make this cabinet open\", \"left door / right drawers\".
- Height (\"taller\", \"lower\", \"85 cm high\") is 3D only: the plan outline is the footprint and stays as it is. \
A target height is the top of the piece above the floor (\"85 cm high\" = top at 0.85); stretch or shrink the parts \
under the top to suit, and nothing goes below the floor (no box starting under 0).
- Colours and finishes: never change an existing material in materials.js (every piece that uses it \
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
pieces by hand: that removes the opening from the 3D. A door drawn as a block (INSERT): convert_opening it to "door" \
first (it is redrawn as a loose door), then move it.
- Openings of any kind, with dxf_edit (never by hand): add_opening puts a new window, glass sliding door, hinged door, \
solid sliding door or bare doorway into a solid wall; convert_opening turns an existing one into another kind (door to \
window, window to door, hinged to sliding, a terrace slider to a window...), resizes or shifts it, or flips how a door \
opens (hinge = the end it hangs from, opens = the side of the wall it swings into, compass words); remove_opening walls \
one up. Mind the swing: a door must open into clear floor, not into furniture (the result warns).
- Heights and glass: set_openings, never furnish.js boxes over an opening. Per opening: sill and head (windows), head \
(doors, sliders), frosted glass, the kind it is built as (a window between a room and the terrace is a full-height \
slider unless set to "window"), a wooden or glass sliding panel; and home-wide ceiling / door / sill / window / slider / \
parapet heights. "Make the window shorter with wall under it" = set_openings sill (keep its head). "Lower the doors" = \
home door height. All of it is for this version only. How openings look is set_openings too: frame / leaf / handle material or \
colour, glass (frosted, tinted, bronze, reflective), panes and transoms, door style (panelled, glazed, louvred, hidden \
flush), a slider's style (bifold, pocket, barn), arch, a glass fanlight over a door, a round window. "All the doors
white with brass handles" = plan_rooms (it lists every opening), then ONE set_openings call with an entry per door
(at: its centre, leaf: "#ffffff", handle: "brass"); the front door too unless the user leaves it out.
- Walls: only with dxf_edit's wall ops (add_wall, remove_wall, move_wall, set_wall_thickness, mark_wall), never face \
lines by hand: they keep junctions closed. A half / low wall or a glass wall = height / glass on add_wall or mark_wall; a glass \
balustrade round the terrace = set_openings home {{ parapet: height, parapetGlass: true }} (all parapets at once); a curved wall = add_wall through. A wall that splits a room makes a new room: add_room_label it (its name \
sets wet / dry: "BATH", "WC", "KITCHEN", "LAUNDRY" are wet). Mind what the result warns (furniture in the way, ends that \
no longer meet a wall) and fix it. Removing or moving a wall is structural: say the engineer has to confirm it.
- Rooms: rename_room / add_room_label (dxf_edit) for names. set_room for a room's floor (any materials.js name, e.g. \
herringbone, chevron, terrazzo, concrete, carpet, porcelain, cementTile, marbleFloor, oakDark, oakGrey, grass, or \
"#rrggbb"), wall paint ("#rrggbb", wallpaperStripe, wallpaperLeaf, brick, concrete), wall tiles and their height, \
skirting, ceiling colour and height (this room only), a raised / sunken floor (furniture follows), the room light's \
brightness / warmth, skylights, and its kind. Paint a whole room with set_room walls, not panels; a single feature wall \
stays a furnish panel.
- Niches / recesses in a wall (shower niche, TV recess): dxf_edit add_niche (it is cut into the wall in 3D, dashed on \
the plan); then shelves or lights in it in furnish.js if asked.
- Light that lights something: lamp(x, y, h, {{ color, power, beam, target }}) in furnish.js next to the fitting (a \
spot: beam = cone degrees, target = [x, y, h]); a fitting alone only glows. At most 12 lamps in the home.
- The rooms' everyday Arabic names (the plan's labels in brackets): الصالة / الليفنج (LIVING ROOM); الريسبشن (RECEPTION);
السفرة (DINING); المطبخ (KITCHEN); الغسيل / المغسلة (LAUNDRY); المدخل (ENTRANCE); الطرقة / الممر (HALLWAY); أوضة النوم
الرئيسية / الماستر / أوضتي (MASTER BEDROOM); الحمام الكبير / الرئيسي / حمام الماستر / حمام أوضة النوم = the master bath
(TOILET 1, off the master bedroom), whatever its area; الحمام الصغير / حمام الضيوف / التواليت = the guest WC (TOILET 2);
التراس / البلكونة (TERRACE). A request naming a room means that room, not the one in the picture.
- Finishes in Arabic (materials.js names): رخام = marbleFloor (floors) / marbleTop (worktops); باركيه / خشب = oak,
herringbone (هيرنج بون), chevron (شيفرون), oakDark (غامق), oakGrey (رمادي); سيراميك / بورسلين = porcelain or tile;
موزاييك / بلاط ملوّن / بلاط مزخرف = cementTile; تيرازو = terrazzo; خرسانة / أسمنت = concrete; موكيت / سجاد = carpet;
طوب = brick; ورق حائط = wallpaperStripe / wallpaperLeaf; نجيلة = grass. Use the closest one and say which.
- Reply in the user's language and dialect: most users are Egyptian, so an Egyptian Arabic request gets a short
Egyptian Arabic reply (مافيش، عشان، دلوقتي، كده; never Levantine or Gulf words like "ما في" or "هلق"), a formal Arabic
request a formal one; sizes in cm and areas in m2. Say only what the plan shows: two rooms are one space only when
no wall stands between them.
- Questions ("how big is...", "what is the biggest sofa that fits..."): answer the question asked, with the numbers
(measure / plan_rooms / furniture_near), in a sentence or two; if it depends on something, give the answer for the
likely case and say what it depends on.
- Questions ("how big is...", "how much paint / tile do I need?", "where are..."): answer from measure / plan_rooms \
and change nothing. Notes ("mark this door fire-rated", "underfloor heating here") and where the walk-through starts: \
set_home. A photo the user sends for a frame, a print or a tile / fabric sample: save_picture, then use the material. \
A photo of the room: say Generate Photo Spot makes those. Things the 3D can't hold (plumbing, wiring routes): say so \
and offer a note.
- The piece the request NAMES wins over what the circle happens to touch: "the buffet" means the buffet even when the
ring also covers the TV wall or the vanity behind the same wall; if the named piece isn't where the user looks, find it
(furniture_near / plan_rooms) and say where it is. When the version has exactly ONE piece of that name (grep its name /
label), that is the piece, wherever the user stands: change it and say which room it's in. Ask only when the name matches
no piece or several. Never say a piece "isn't in the code" before grep has searched for its name.
- After one clarifying question, the user's answer is final: pick the best match for it in the room they named, make the
change and say which one you changed; don't ask a second question.
- Before answering that a piece can't move ("it's already against the wall"), measure the free distance that way
(furniture_near / measure / dxf_edit's "ONLY n cm FREE") and quote it; with room to go, move it.
- Change only what was asked. Never delete, move or restyle another piece or plan outline to make room or to silence an
overlap (move it only if the user agrees), never edit doors other than the one asked about, and never move a piece the
user only asked to resize, recolour or turn.
- "Towards / away from / next to X": work the direction out from the two pieces' positions (furniture_near), so the
piece really ends nearer to (or further from) X. A table and its chairs go together: move or resize the set. A table
made longer or wider moves the chairs at the ends it grew past out by the growth (both views), so none ends up inside it.
- Before offering choices ("which wall?"), check each option fits (measure / furniture_near) and offer only those that
do; if only one fits, do it and say so. If what is asked already exists (a door on a cupboard), say so and change nothing.
- A colour change keeps the material's kind: a tinted copy of the same material (const beigeBoucle =
mat.boucle.clone(); beigeBoucle.color.set(...)), never another kind (fabric to plaster or stone). A size change says
the old and the new size.
- A piece drawn on the plan (furniture_near shows its outline) is moved, turned or resized in both the 3D and its plan
outline; if the plan can't follow, say so plainly instead of claiming both changed. Resize a drawn symbol (an armchair's
curved back and arms) by scaling its own lines (resize_piece), never by deleting it and drawing a box; keep the line's
// comment as it is (it names the piece in Move and Resize).
- Raising or lowering part of a piece moves everything attached to it by the same amount (its seams, LED strip,
handles); a thing in a niche or on a shelf stays inside it: if it won't fit, say so with the numbers.
- When a move can't be done as asked (no room), measure the candidate spots (measure / furniture_near) and offer the
one that fits, with its free length against the piece's size; never refuse with only "it won't fit".
- "Add X" never removes or replaces an existing piece unless the user says replace.
- First check whether the piece already is as asked (already behind a door, already floating, already faces the TV,
already that size): then change nothing, not even a comment, and say so with the numbers. Lines marked "doesn't run
for this version" describe another version: never answer from them; find this version's own line.
- A whole piece moves through its item(x, y, ...) numbers (and its plan outline), never through p.g.position /
p.g.rotation inside its build: item() sets those after the build runs, so such a "move" does nothing.
- "Turn / rotate / face X" changes the facing (and keeps the piece's middle); it never slides the piece more than a few
cm. If the turn doesn't fit, say which piece is in the way. A rug is resized or moved only when the user names it.
- Before adding a piece, look at what is already at that spot (furniture_near): a new chandelier over the table
replaces the pendants hanging there, a new sofa replaces the old one, a new rug the old rug. Remove or move what it
replaces in the same edit, never leave two things in one place, and say what you took out.
- A real model instead of boxes ("this sofa", "a mid-century armchair", "a chandelier", "a ceiling fan"): find_model,
then p.model(url, null, x, y, z, {{ size: [w, h, d] }}) inside the item's build, sized to the piece. Use find_model first
for any free-standing product or fitting (chandelier, pendant, lamp, sofa, armchair, chair, table, bath, plant); boxes
stay for built-in joinery, or when nothing in the library fits.
- Big jobs (a whole room redone, a style across the home): plan the parts first, do them one at a time and \
save_progress after each finished part, so a time-out keeps what is done; then tell the user what is left.
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


def post(url, body, headers=None, who="OpenAI"):
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
                                 headers=headers or {"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
    try:
        for attempt in (0, 1):  # one slow answer is tried again once, not shown to the user raw (e2e J234 / J244 r3)
            try:
                with urllib.request.urlopen(req, timeout=150) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError:
                raise
            except (TimeoutError, urllib.error.URLError) as e:
                if attempt or not (isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)):
                    raise RuntimeError(f"{who} took too long to answer, so nothing was changed. Try again in a moment.") from e
                print(f"[edit-ai] {who} timed out; trying once more", flush=True)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:300]
        raise RuntimeError(f"{who} said {e.code}: {msg}")


def openai(messages, first=False, model=None):
    """One model turn over the chat-completions style history in `messages`; returns a chat-completions style
    result ({"choices": [{"message": ...}], "usage": ...}) whichever API answered."""
    model = model or MODEL
    tools = [t for t in TOOLS if plan_edits() or not t["name"].startswith("dxf_")]
    if is_claude(model):
        return anthropic(messages, tools, first, model)
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


def _media(url):
    """A chat-style image URL as a Claude image source (data URLs inline as base64)."""
    if url.startswith("data:"):
        head, _, data = url.partition(",")
        return {"type": "base64", "media_type": head[5:].split(";")[0] or "image/png", "data": data}
    return {"type": "url", "url": url}


def anthropic(messages, tools, first, model):
    """The same turn on Anthropic's Messages API. The history stays in chat-completions shape (one loop in chat())
    and is translated every turn: system -> system, image_url -> image blocks, an assistant's tool_calls ->
    tool_use blocks, role "tool" -> tool_result blocks in a user turn (consecutive same-role turns are merged, as
    Claude wants strict user/assistant alternation). Prompt caching: one breakpoint after the system prompt (covers
    the tools too) and one on the newest block, so each tool round re-reads the conversation so far at cache price."""
    system, out = [], []
    def add(role, blocks):
        if out and out[-1]["role"] == role:
            out[-1]["content"] += blocks
        else:
            out.append({"role": role, "content": blocks})
    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":
            system.append(content)
            continue
        if role == "tool":
            add("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": content or "(empty)"}])
            continue
        blocks = []
        if isinstance(content, list):
            for c in content:
                if c.get("type") == "text":
                    blocks.append({"type": "text", "text": c["text"]})
                elif c.get("type") == "image_url":
                    blocks.append({"type": "image", "source": _media(c["image_url"]["url"])})
        elif content:
            blocks.append({"type": "text", "text": content})
        for call in m.get("tool_calls") or []:
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except ValueError:
                args = {}
            blocks.append({"type": "tool_use", "id": call["id"], "name": call["function"]["name"], "input": args})
        if blocks:
            add(role, blocks)
    if out and out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(conversation so far)"}]})
    if out:
        last = out[-1]["content"][-1]
        out[-1]["content"][-1] = {**last, "cache_control": {"type": "ephemeral"}}
    body = {"model": model, "max_tokens": int(os.environ.get("EDIT_AI_MAX_TOKENS", "8192")), "messages": out,
            "system": [{"type": "text", "text": "\n\n".join(system), "cache_control": {"type": "ephemeral"}}] if system else [],
            "tools": [{"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]} for t in tools],
            **({"tool_choice": {"type": "any"}} if first else {})}
    headers = {"x-api-key": anthropic_key() or "", "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        res = post(ANTHROPIC_URL, body, headers, "Claude")
    except RuntimeError as e:
        if not first or "tool_choice" not in str(e):
            raise
        body.pop("tool_choice")  # e.g. thinking on by default: forced tool use isn't allowed, let it choose
        res = post(ANTHROPIC_URL, body, headers, "Claude")
    text, calls = [], []
    for b in res.get("content") or []:
        if b.get("type") == "text":
            text.append(b.get("text", ""))
        elif b.get("type") == "tool_use":
            calls.append({"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}})
    u = res.get("usage") or {}
    read, write = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
    return {"choices": [{"message": {"role": "assistant", "content": "".join(text) or None, "tool_calls": calls or None}}],
            "usage": {"prompt_tokens": (u.get("input_tokens") or 0) + read + write, "completion_tokens": u.get("output_tokens") or 0,
                      "prompt_tokens_details": {"cached_tokens": read, "cache_write_tokens": write}}}


def _price(model, prompt_tokens):
    long_ = next((v for k, v in PRICES_LONG.items() if model.startswith(k)), None)
    if long_ and prompt_tokens > long_[0]:
        return long_[1]
    return next((v for k, v in sorted(PRICES.items(), key=lambda kv: -len(kv[0])) if model.startswith(k)), None)


def cost(usage, total, model=None):
    """Add one call's tokens to the message total, and its dollars (priced per call: Haiku's long-prompt tier)."""
    d = usage.get("prompt_tokens_details") or {}
    one = {"prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0),
           "cached": d.get("cached_tokens", 0) or 0, "cache_write": d.get("cache_write_tokens", 0) or 0}
    for k, v in one.items():
        total[k] = total.get(k, 0) + v
    p = _price(model or MODEL, one["prompt_tokens"])
    if p is None:
        total["unpriced"] = True
    else:
        fresh = one["prompt_tokens"] - one["cached"] - one["cache_write"]
        total["usd"] = total.get("usd", 0.0) + (fresh * p[0] + one["cached"] * p[1] + one["completion_tokens"] * p[2]
                                                + one["cache_write"] * (p[3] if len(p) > 3 else p[0])) / 1e6


def dollars(total, model=None):
    if total.get("unpriced") or "usd" not in total:
        return None if total.get("unpriced") or total.get("prompt_tokens") else 0.0
    return round(total["usd"], 4)


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
    r"\b(hang|hung|mount|fit|fix (a|an|some))\b", r"\b(chandelier|pendant|lamp|light fitting|spotlight|sconce)s?\b",
    r"\b(all|every) (the )?doors?\b", r"\bniche", r"\bsliding\b",
    r"\bswap\b", r"\bopposite (wall|side)\b", r"\b(other|another) wall\b",  # a move + turn + plan symbol (e2e J308 r3)
)]
# Egyptian / standard Arabic (no \b: "والحيطة" = and + the + wall is one word). Adding, building, hanging, swapping or
# turning one thing into another, light fittings, and the plan's walls / windows / doors with a verb that changes them.
_AR_COMPLEX = re.compile(r"ضيف|اضيف|أضيف|اضف|أضف|زود|ركب|ركّب|علق|علّق|(?:^|[\sوف])حط(?:لي|ي|وا|ّ)?(?:\s|$)|اعمل|إعمل|اعملي|ابني|جديد|"
                         r"كل الابواب|كل الأبواب|كل ابواب|كل أبواب|كل باب|الابواب كلها|الأبواب كلها|نيش|سحاب|جرار|منزلق|"
                         r"بدل|استبدل|حول|حوّل|اقلب|نجف|اباليك|أباليك|ابليك|سبوت|لمبة|اضاءة|إضاءة|ينطوي|قابل للطي|بيتفتح|يتفتح|"
                         r"وكمان|وبعدين|كمان")
AR_TEXT = re.compile(r"[\u0600-\u06FF]")  # an Arabic request gets Arabic canned replies
_AR_PLAN = re.compile(r"حيط|حائط|جدار|شباك|شبابيك|نافذ|باب|ابواب|أبواب|عمود|فاصل|فتح")
_AR_PLAN_VERB = re.compile(r"شيل|اشيل|انقل|حرك|حرّك|وسع|وسّع|ضيق|ضيّق|كبر|كبّر|صغر|صغّر|اقفل|قفل|افتح|اهد|هد |اكسر|اقسم|قسم|"
                           r"طول|طوّل|قصر|قصّر|زق|ارفع|نزل|نزّل|امسح")
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
    if any(r.search(m) for r in _COMPLEX_RES) or _AR_COMPLEX.search(m):
        return True
    if _AR_PLAN.search(m) and _AR_PLAN_VERB.search(m) and not re.search(r"لون|دهان|اده|ادهن|بوية|خشب", m):
        return True
    if _PLAN_RE.search(m) and _PLAN_VERB_RE.search(m) and not re.search(r"\b(colou?r|paint|finish)\b", m, re.I):
        return True
    clauses = [c for c in re.split(r"[.;\n]|,\s*(?:and\s+)?|\band\b", m) if len(c.split()) >= 3]
    if len(m.split()) > 30 and len(clauses) >= 3 and not _EASY_RE.search(m):
        return True  # a long multi-clause ask with nothing that reads as a plain tweak
    return False  # short / ambiguous / colour-height-move-rename only: the cheap model


def pick_model(message, refs=()):
    return COMPLEX_MODEL if is_complex_edit(message, refs) else EASY_MODEL


# --- Quality gates: the prompt check before an edit, the review after it ------------------------------------------------
def gates_on():
    return os.environ.get("EDIT_AI_GATES", "1") != "0" and bool(api_key())


def ask_json(model, system, content, max_out=300):
    """One tool-free OpenAI turn that answers with a JSON object; returns (object, chat-style usage)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    res = None
    if not uses_responses(model):
        try:
            res = post(OPENAI_URL, {"model": model, "messages": messages, "response_format": {"type": "json_object"},
                                    "max_completion_tokens": max_out,
                                    **({"reasoning_effort": "none"} if model.startswith(("gpt-5", "gpt-6")) else {"temperature": 0})})
        except RuntimeError as e:
            if "/v1/responses" not in str(e) and "reasoning_effort" not in str(e):
                raise
            _RESPONSES_ONLY.add(model)
    if res is None:
        res = responses(messages, [], False, model)
    text = res["choices"][0]["message"].get("content") or ""
    m = re.search(r"\{.*\}", text, re.S)
    out = json.loads(m[0] if m else text)
    if not isinstance(out, dict):
        raise ValueError(f"expected a JSON object, got {text[:80]!r}")
    return out, res.get("usage") or {}


# Luna, with the view and its red marks at low detail (what the circle covers, how many pieces of a kind are in view).
# What a good request needs, by kind of edit.
PRECHECK_SYSTEM = """You grade a request to an AI that edits a 3D model / 2D plan of a flat, before it runs.
Score 1-5 how likely the request is to get what the user means first time: 5 clear, 4 small guess, 3 a real guess,
2 key detail missing, 1 can't be done as asked. What each kind needs:
move: which piece (a circle counts) and where to (direction + distance, a landmark, or a 2nd mark);
colour/finish: which piece (a circle counts) and the colour or material named;
resize: which piece, which dimension and a size or a clear direction;
add: what, where and roughly how big; remove: which piece.
When the view is attached, judge against it. Circled (red): the circle is the piece (2+ marks: 1 = the piece, 2+ =
where it goes); if the words name a piece the circle doesn't cover, score 2 and say so. Whole view (no circle) must
name the piece: if only one of that kind is in view, naming the kind is enough ("this window"), don't ask which; if
several are, the words must pick one (left / right, nearest, by the sofa...), else score 2 and ask which.
Without the view: naming the kind is enough.
A room or a home-wide thing named in words (kitchen, laundry, living room, terrace, the parapets, all the doors...) is
named even when it isn't in view: this home has one of each, never ask "which". A wall "between" two named rooms is
named too. Egyptian Arabic (e.g. "شيل الحيطة اللي بين المطبخ والغسيل", "حط نجفة فوق السفرة") is as clear as English.
"الحمام الكبير" (the master bath) and "الحمام الصغير" / "حمام الضيوف" (the guest WC) name one bathroom each; a room's
window or door is named by naming the room when it has one ("شباك الحمام الكبير").
A room named in words (kitchen, laundry, living room, terrace...) is named even when it isn't in view: this home has one of each, never ask "which". A wall "between" two named rooms is named too.
A question about the home (sizes, areas, how much paint / tile, what is where) is fine: score 5.
Reply in the request's language.
Answer JSON only: {"score":n,"tip":"what to add, max 15 words; empty when 5"}"""


def precheck(req):
    """POST /api/edit-ai/precheck: Luna's 1-5 grade of the wording and one tip. Never blocks: {"skipped"} on any trouble."""
    message = (req.get("message") or "").strip()[:1000]
    if not message or not gates_on():
        return {"skipped": True}
    c = req.get("context") or {}
    ms = marks_of(c)
    if c.get("wholeView"):
        marked = "Whole view (nothing circled)"
    elif ms:
        marked = f"{len(ms)} separate marks: 1 = the piece, 2+ = where it goes"
    elif c.get("hits") or c.get("highlightBox"):
        h = (c.get("hits") or [{}])[0]
        marked = "1 circle on " + ("a furniture piece" if h.get("furniture") else "architecture" if h else "the plan") \
                 + (f" ({h['material']})" if h.get("material") else "")
    else:
        marked = "nothing circled"
    content = (f"View: {'2D plan' if c.get('showing') == 'drawing' else '3D'}. Marked: {marked}. "
               f"Reference pictures: {int(req.get('refs') or 0)}.\nRequest: {message}")
    image = req.get("image")
    try:
        image = check_image(image, "view") if image else None
    except ValueError:
        image = None  # a bad picture just means the text-only check
    if image:
        inked = not marked.startswith(("Whole", "nothing"))
        content = [{"type": "text", "text": content + ("\nThe view is attached, with the red marks." if inked
                                                       else "\nThe view is attached.")},
                   {"type": "image_url", "image_url": {"url": image, "detail": "low"}}]
    total = {}
    try:
        out, usage = ask_json(PRECHECK_MODEL, PRECHECK_SYSTEM, content, max_out=80)
        cost(usage, total, PRECHECK_MODEL)
        score = max(1, min(5, int(out.get("score"))))
    except Exception as e:
        print(f"[edit-ai] precheck skipped: {type(e).__name__}: {e}", flush=True)
        return {"skipped": True}
    return {"score": score, "tip": str(out.get("tip") or "")[:200], "model": PRECHECK_MODEL,
            "usd": round(total["usd"], 6) if "usd" in total else None, "tokens": total}  # ~$0.0001: 4 places would lose it


REVIEW_SYSTEM = """You are the end-to-end tester of Edit AI, which edits a 3D model of a flat (furnish.js, materials.js,
the plan DXF) from a user's request. Image 1 is the view before the edit, with what the user circled in red (unless they
chose Whole view). You get the request, where the user pointed, the diff of what changed and the editor's reply.
Score 0-10 how well the change does exactly what was asked:
right piece (the circled / named one), right direction and amount, right colour or material, a sensible size and place,
nothing unrelated changed, and the reply truthfully describes the diff.
10 exactly right; 7 right with nitpicks; 4 partly right or a visible mistake; 0 wrong piece or nothing asked for done.
Judge the result, not code style; don't guess at what the diff doesn't show. Check the changed thing is in the room the
user named (the diff says which rooms an opening sits between): the right change on the wrong window scores 2.
When the request names a room or a thing that isn't in the picture ("the big bathroom's window" seen from the
terrace), judge by the words and the diff's room notes, not the picture: the picture only shows where the user stands,
and a change far from it is right when it is in the room they named. Room names: الحمام الكبير / حمام الماستر = TOILET 1
(the master bath); الحمام الصغير / حمام الضيوف = TOILET 2; أوضة النوم / الماستر = MASTER BEDROOM; الصالة = LIVING ROOM;
الريسبشن = RECEPTION; السفرة = DINING; المطبخ = KITCHEN; الغسيل = LAUNDRY; الطرقة = HALLWAY; التراس = TERRACE.
A room taller than the rest needs the home ceiling raised to it and the other rooms' ceilingHeight set back: that is
the right way, not an unneeded change.
Also answer three yes/no checks: "unrelated": a piece, wall or finish the request didn't ask about was changed, moved or
removed (adding X never removes an existing X unless the user said replace); "reply_true": every claim in the editor's
reply (what moved, which way, how far, what stayed) matches the diff; "defect": the result has a visible fault (parts left
behind or floating, something poking through another, a part out of its niche / off its shelf).
Answer JSON only: {"score":n,"unrelated":false,"reply_true":true,"defect":false,"problems":["a fix for the editor, max 25 words"],"summary":"max 20 words"}"""
REVIEW_CAP = 4  # an unrelated change, an untrue reply or a visible defect scores at most this (under REVIEW_KEEP: not saved)


def drawing_same(a, b):
    """Do two drawing-<v>.json contents draw the same strokes and texts (to the mm, in any order)? A DXF rewritten with
    no net op differs only in header stamps and handles, and draws the same."""
    try:
        A, B = json.loads(a), json.loads(b)
    except (TypeError, ValueError):
        return False
    def norm(d):
        st = {c: sorted(tuple(round(float(t), 3) for t in pl) for pl in v_) for c, v_ in (d.get("strokes") or {}).items()}
        return st, sorted(json.dumps(t, sort_keys=True) for t in d.get("texts") or [])
    try:
        return norm(A) == norm(B)
    except (TypeError, ValueError):
        return False


def edit_diff(ws, trace, limit=12000):
    """What changed, for the reviewer: a unified diff of the hand-edited files, the plan edits as their tool calls
    (the DXF and the model / drawing built from it aren't readable as a diff)."""
    built = {ws.cfg.get(k) for k in ("dxf", "model", "drawing")}
    out = []
    for p in sorted(ws.changed):
        if p in built:
            out.append(f"({p}: changed through the plan edits below)" if p == ws.cfg.get("dxf") else f"({p}: rebuilt from the plan)")
            continue
        a = ws.orig[p].decode(errors="replace").splitlines() if p in ws.orig else []
        out += difflib.unified_diff(a, ws.text(p).splitlines(), f"a/{p}", f"b/{p}", n=2, lineterm="")
    # only plan edits that took and weren't thrown away by a later discard: a failed move_door or a discarded wrong-way
    # move read as applied capped right edits at 4 (e2e J207 J215 J221 J222 r3); then each piece's net move
    last_discard = max((i for i, t in enumerate(trace) if t["tool"] == "discard"), default=-1)
    plan = [f"{t['tool']} {t['args']}" for i, t in enumerate(trace)
            if i > last_discard and t["tool"].startswith("dxf_") and t["tool"] not in ("dxf_query", "dxf_find")
            and not re.match(r"\s*(nothing changed|no ops given|As-built|error:)", str(t.get("out", "")))]
    if plan:
        out += ["Plan edits:"] + plan[-10:]
    net = [f"{h}: x {b[0]}..{b[2]}, y {b[1]}..{b[3]} -> " + (f"x {n[0]}..{n[2]}, y {n[1]}..{n[3]}" if n else "deleted")
           for h, b in (ws.pieces or {}).items() if b and (n := getattr(ws, "pieces_now", {}).get(h, b)) != b]
    if net:
        out += ["Net plan pieces after all edits (old -> new, plan metres; this is what the plan now shows):"] + net[:20]
    if ws.cfg["tour"] in ws.changed:  # which rooms an opening spec's point sits between: "at" alone doesn't say
        try:
            t0 = json.loads(ws.orig.get(ws.cfg["tour"], b"{}") or b"{}")
            t1 = json.loads(ws.text(ws.cfg["tour"]))
            s_ = ws.text(ws.cfg["model"])
            floors = json.loads(s_[s_.index("{"):s_.rindex("}") + 1]).get("floor", [])
            old = {json.dumps(o, sort_keys=True) for o in t0.get("openings", [])}
            for o in t1.get("openings", []):
                if json.dumps(o, sort_keys=True) in old:
                    continue
                x, y = o["at"][0] - ORIGIN[0], o["at"][1] - ORIGIN[1]
                near = sorted({f["room"] for f in floors if min(math.dist((x, y), q) for q in f["outer"]) < 1.0
                               or _inside(f["outer"], x, y)})
                out.append(f"Opening spec changed at plan ({round(x, 2)}, {round(y, 2)}): between {' and '.join(near) or 'no named room'}")
        except Exception:
            pass
    text = "\n".join(out)
    return text if len(text) <= limit else text[:limit] + "\n... (diff cut)"


def _inside(ring, x, y):
    c = False
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def review_edit(ws, message, reply, where, image, trace, total):
    """Sol's verdict on the edit as it stands: {"score", "problems", "summary"}, or None when the review couldn't run."""
    scope = ""
    if (ws.ctx or {}).get("wholeView"):  # a piece of that room out of the frame is still in scope (e2e J213 r3)
        scope = (f"\n\nThe user chose Whole view (no circle): the request is about the whole "
                 f"{(ws.ctx or {}).get('room') or 'room they stand in'}, not only what the picture shows. A piece of that room "
                 "out of the frame is the right piece when the words name it.")
    content = [{"type": "text", "text": f"Request: {message}\n\nWhere the user pointed:\n{where}{scope}\n\n"
                                        f"Diff:\n{edit_diff(ws, trace)}\n\nEditor's reply: {reply[:1500]}"},
               {"type": "image_url", "image_url": {"url": image, "detail": "low"}}]
    try:
        out, usage = ask_json(REVIEW_MODEL, REVIEW_SYSTEM, content, max_out=400)
        cost(usage, total, REVIEW_MODEL)
        v = {"score": max(0, min(10, int(out.get("score")))), "summary": str(out.get("summary") or "")[:300],
             "problems": [str(x)[:300] for x in (out.get("problems") or []) if x][:6]}
        # hard checks (e2e r2 J228 J229 J235 J244 J247: a 6-7 with "an unrelated bench moved" / "the reply misstates the
        # change" / "dangling seams" was saved): any of them caps the score, so the fix round runs and a miss isn't saved
        flags = [k for k, bad in (("an unrelated change", out.get("unrelated") is True), ("a reply that doesn't match the change",
                 out.get("reply_true") is False), ("a visible defect", out.get("defect") is True)) if bad]
        if flags and v["score"] > REVIEW_CAP:
            v["score"] = REVIEW_CAP
            v["summary"] = (v["summary"] + f" [capped: {', '.join(flags)}]").strip()
    except Exception as e:
        print(f"[edit-ai] review skipped: {type(e).__name__}: {e}", flush=True)
        trace.append({"tool": "(sol review, skipped)", "args": "", "out": str(e)[:700]})
        return None
    trace.append({"tool": "(sol review)", "args": "", "out": json.dumps(v)[:700]})
    return v


def fix_note(v):
    return (f"An independent reviewer checked your edit against the request and scored it {v['score']}/10 "
            f"({v['summary']}). What to fix:\n" + "\n".join(f"- {p}" for p in v["problems"] or ["(no detail given)"]) +
            "\nFix these in the same edit and keep what is already right. If a point is wrong (the edit already does what "
            "the user asked), leave that part as it is. Check, then reply to the user about the final change compared "
            "with how it was before their request (don't mention the review).")


def usd_sum(*vals):
    return None if any(v is None for v in vals) else round(sum(vals), 4)


_VERSION_LOCKS, _VERSION_LOCKS_GUARD = {}, threading.Lock()


def version_lock(v):
    """This server's lock for one version's revisions: an Undo sent while an Accept of the same version is saving waits
    for it, so neither is written over the other (e2e r2 J178: a lost update left a change nothing could undo). One
    process only: on Vercel each call is its own (the page sends one at a time)."""
    v = plan_version(v)
    with _VERSION_LOCKS_GUARD:
        return _VERSION_LOCKS.setdefault(v, threading.Lock())


def chat(req, emit=None):
    """One edit. `emit(text)`, when given, hears the steps worth showing while it runs (the review, a fix round)."""
    emit = emit or (lambda text: None)
    v = plan_version(req.get("version"))
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    if not ready():
        raise PermissionError("Edit AI isn't switched on yet: set ANTHROPIC_API_KEY (or EDIT_AI_OPENAI_API_KEY) on the server.")
    model = req.get("model")
    if model and model not in ALLOWED_MODELS:
        raise ValueError(f"model {model!r} isn't allowed here")
    message = (req.get("message") or "").strip()[:4000]
    if not message:
        raise ValueError("Say what you want changed.")
    ctx = req.get("context") or {}
    image = check_image(req.get("image"), "the view")
    refs = [check_image(u, f"reference {i + 1}") for i, u in enumerate((req.get("refs") or [])[:MAX_REFS])]
    if req.get("retry"):  # "Try a stronger model" on the done toast: the last edit was undone, and the strong model has a go
        model, route = COMPLEX_MODEL, "retry"
        message = ("Second try: your last attempt at this was undone because it wasn't what I wanted. Start from the files "
                   "as they are now and do it properly. My request: " + message)
    elif model:
        route = "explicit"  # an A/B pick from the client wins
    else:
        model = pick_model(message, refs)
        route = "complex" if model == COMPLEX_MODEL else "easy"
        hist_ = [h for h in (req.get("history") or []) if isinstance(h, dict) and isinstance(h.get("text"), str)]
        if model != COMPLEX_MODEL and hist_ and hist_[-1].get("role") == "assistant" and hist_[-1]["text"].rstrip().endswith(("?", "؟")) \
                and any(h.get("role") == "user" and is_complex_edit(h["text"]) for h in hist_[-4:]):
            # an answer to the strong model's question goes back to it, not the cheap one (Sol offered "make it smaller to
            # fit another wall", Luna then said it can't fit at all: e2e J241 r3)
            model, route = COMPLEX_MODEL, "complex"
    model = live_model(model)  # no Anthropic key yet: the route's OpenAI stand-in
    ws = Workspace(v)
    ws.allow_as_built = v == "as-built"  # only ever reached from the as-built page itself
    ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = False, False, {}, {}, [], []
    ws.pieces_now = {}
    ws.win_moved = []
    sys_prompt = SYSTEM.format(showing="2D drawing" if ctx.get("showing") == "drawing" else "3D model", version=v,
                               marked="" if ctx.get("wholeView") else ", with what the user circled marked in red")
    if not plan_edits():
        sys_prompt += ("\n\nThis server can't edit the plan DXF (walls, windows, doors): only furnish.js, materials.js and the tour. "
                       "If the request needs a wall, window or door moved, say plainly that plan edits are unavailable right now.")
    if (alias := runs_as(ws.text("furnish.js"), v)) != v:
        sys_prompt += (f"\n\nThis version's furnish.js starts with `if (version === \"{v}\") version = \"{alias}\";`: it runs "
                       f"every branch written for \"{alias}\" (those are the lines that build what the user sees) and a "
                       f"`version === \"{v}\"` test never passes in it. Edit the lines that run (furniture_near lists them); "
                       "never add a new `version === ...` gate.")
    messages = [{"role": "system", "content": sys_prompt}]
    for h in (req.get("history") or [])[-8:]:
        if h.get("role") in ("user", "assistant") and isinstance(h.get("text"), str):
            messages.append({"role": h["role"], "content": h["text"][:2000]})
    ws.ctx, ws.aspect = ctx, image_aspect(image)
    ws.refs, ws.message = refs, message
    try:
        sm_ = ws.text(ws.cfg["model"])
        rings_ = [f.get("outer") or [] for f in json.loads(sm_[sm_.index("{"):sm_.rindex("}") + 1]).get("floor", [])]
    except Exception:
        rings_ = []
    where = context_text(ctx, ws.aspect, rings_)
    lang = ("Reply in Egyptian Arabic, as the request is." if AR_TEXT.search(message) else
            "The request is in English: reply in English only (no Arabic or other scripts).")
    content = [{"type": "text", "text": f"{where}\n\nRequest: {message}\n\n({lang})"},
               {"type": "image_url", "image_url": {"url": image, "detail": "high"}}]
    content += [{"type": "image_url", "image_url": {"url": u, "detail": "low"}} for u in refs]
    messages.append({"role": "user", "content": content})
    total, reply, steps, trace = {"prompt_tokens": 0, "completion_tokens": 0, "cached": 0, "cache_write": 0}, "", [], []
    nudged, fixing, verdict, final, edit_usd, before_fix = 0, False, None, None, None, ({}, set(), {}, {}, "")
    review_total = {"prompt_tokens": 0, "completion_tokens": 0, "cached": 0, "cache_write": 0}
    gates = gates_on() and not req.get("noReview")
    try:
        t_start = time.time()
        while True:  # the edit, then (after a low review) one fix round on the same conversation
            limit = FIX_STEPS if fixing else (MAX_STEPS_COMPLEX if route in ("complex", "retry") else MAX_STEPS)
            for step in range(limit):
                # look before answering: no "done" without a tool call (the fix round may answer that it's already right)
                left_ = TIME_LIMIT - (time.time() - t_start)
                if left_ < 12:  # the function's time limit: stop while it can still answer (saved parts stay saved)
                    if ws.changed:
                        trace.append({"tool": "(time)", "args": "", "out": "out of time"})
                        ws.changed.clear()
                    reply = (("خلص الوقت قبل ما أخلّص" + (f"، والـ{ws.saved_parts} جزء اللي حفظتهم موجودين" if getattr(ws, "saved_parts", 0)
                              else "، ومافيش حاجة اتغيّرت") + ". اطلب الباقي تاني، أو جرّب تعديل أصغر.") if AR_TEXT.search(message) else
                             ("I ran out of time before finishing" + (f"; the {ws.saved_parts} part(s) I saved are live" if getattr(ws, "saved_parts", 0)
                              else "; nothing was changed") + ". Ask again for the rest, or try a smaller change."))
                    break
                if left_ < 50 and not getattr(ws, "warned_time", False):
                    ws.warned_time = True
                    messages.append({"role": "user", "content": "Under a minute left. If your edits are done and checked, reply now; "
                                     "otherwise save_progress what is finished and tell the user what is left to do."})
                res = openai(messages, first=step == 0 and not fixing, model=model)
                cost(res.get("usage") or {}, total, model)
                msg = res["choices"][0]["message"]
                messages.append({k: msg[k] for k in ("role", "content", "tool_calls") if msg.get(k) is not None})
                if not msg.get("tool_calls"):
                    reply = msg.get("content") or ""
                    nudge = None if nudged >= 3 or step >= limit - 3 else (review(ws, message, reply) or missing_claim(ws, message, reply))
                    if nudge:  # up to two second looks before saving: 2D and 3D out of step, a lost opening, a give-up with edits left
                        nudged += 1
                        trace.append({"tool": "(review)", "args": "", "out": nudge[:700]})
                        messages.append({"role": "user", "content": nudge})
                        continue
                    if ws.changed and (nudged >= 3 or step >= limit - 3):  # out of second looks: never save 2D and 3D apart
                        last_ = review(ws, message, reply)
                        if last_ and last_.startswith("Check 2D vs 3D") and not ws.dxf_furni and not ws.pieces \
                                and "furnish.js" in ws.orig and three_d_only(ws, ws.orig["furnish.js"].decode(), ws.text("furnish.js")):
                            # Only 3D-only pieces changed (AC, curtain / AC box, bulkhead, high fitting, nothing on the plan):
                            # nothing to keep in step with the 2D, so save the 3D edit instead of throwing it away.
                            trace.append({"tool": "(review, final: 3D-only, kept)", "args": "", "out": last_[:700]})
                        elif last_ and last_.startswith("Check the turn"):
                            trace.append({"tool": "(review, final)", "args": "", "out": last_[:700]})
                            ws.changed.clear()
                            reply = ("ماغيّرتش حاجة: ماقدرتش ألفّها في المخطط والـ3D مع بعض، فسيبتها زي ما كانت." if AR_TEXT.search(message) else
                                     "Nothing was changed: I couldn't turn it on the 2D plan and in the 3D together, so I left it as it was.")
                        elif last_ and last_.startswith(("Check the piece", "Check the direction", "Check the distance", "Check the move")):
                            trace.append({"tool": "(review, final)", "args": "", "out": last_[:700]})
                            ws.changed.clear()
                            reply = ("ماغيّرتش حاجة: ماقدرتش أتأكد إني غيّرت الحتة اللي تقصدها (أو حرّكتها في الاتجاه اللي طلبته). "
                                     "قولّي أنهي حتة وفين، وأنا أجرّب تاني." if AR_TEXT.search(message) else
                                     "Nothing was changed: I couldn't be sure I changed the piece you meant (or moved it the way you "
                                     "asked), so I left everything as it was. Say which piece and where, and I'll try again.")
                        elif last_ and last_.startswith("Check 2D vs 3D") and (stuck_ := next(
                                (m_ for t_ in trace for m_ in [re.search(r"it now touches (.+?) - it was ALREADY touching it", t_.get("out") or "")]
                                 if m_), None)):
                            # the plan said there's no room that way: that is the answer, not "try a smaller change" (e2e J215 r4)
                            trace.append({"tool": "(review, final: already touching)", "args": "", "out": last_[:700]})
                            ws.changed.clear()
                            reply = (f"ماغيّرتش حاجة: مافيش مكان في الاتجاه ده، القطعة لازقة بالفعل في {stuck_[1]}." if AR_TEXT.search(message) else
                                     f"Nothing was changed: there's no room that way, it already touches {stuck_[1]} on the plan.")
                        elif last_ and last_.startswith("Check 2D vs 3D"):
                            trace.append({"tool": "(review, final)", "args": "", "out": last_[:700]})
                            ws.changed.clear()
                            reply = ("ماقدرتش أخلّص التعديل والمخطط والـ3D متطابقين، فسيبتهم زي ما كانوا. جرّب طلب أصغر أو أوضح."
                                     if AR_TEXT.search(message) else
                                     "I couldn't finish this with the 2D plan and the 3D model matching, so I left both as they "
                                     "were. Try a smaller or more specific change.")
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
                if step == limit - 3 and ws.changed:  # don't lose a finished edit to the step limit
                    messages.append({"role": "user", "content": "Only 2 steps left. If your edits are done and the last check "
                                     "passed, reply to the user now (no more tool calls); otherwise call discard and tell the user "
                                     "nothing was changed and what couldn't be finished."})
            else:
                reply = ("خلصت الخطوات قبل ما أخلّص، ومافيش حاجة اتغيّرت. جرّب طلب أضيق." if AR_TEXT.search(message) else
                         "I ran out of steps before finishing; nothing was changed. Try a narrower request.")
                ws.changed.clear()
            if fixing or not gates or not ws.changed or time.time() - t_start > TIME_LIMIT - 70:
                break  # no review when the clock is nearly out
            if ws.changed == {"furnish.js"} and comment_only(ws.orig.get("furnish.js"), ws.text("furnish.js")):
                # it is already so: a comment-only "edit" sent to review scored 0, and the fix round then churned the
                # file (renamed an openable, moved a door) until it passed (e2e J240 / J247 r4)
                trace.append({"tool": "(comment-only edit: no review, not saved)", "args": "", "out": ""})
                break
            emit("Checking the edit")
            verdict = review_edit(ws, message, reply, where, image, trace, review_total)
            if not verdict or verdict["score"] >= REVIEW_PASS:
                break
            fixing, nudged, edit_usd = True, 0, dollars(total, model)
            before_fix = (dict(ws.files), set(ws.changed), dict(ws.orig), {k_: list(v_) for k_, v_ in ws.ops.items()}, reply)
            if model != live_model(COMPLEX_MODEL):  # the cheap model's miss: the strong one fixes it (priced as such)
                model = live_model(COMPLEX_MODEL)
            emit("We found improvements, please wait a moment")
            messages.append({"role": "user", "content": fix_note(verdict)})
        kept_before = False
        if fixing and not ws.changed and before_fix[1] and verdict and verdict["score"] < REVIEW_KEEP:
            # The fix round gave up on an edit the reviewer had already rejected: nothing to keep. Re-reviewing the kept
            # files saw the fix round's ops (rug put back, circle drawn), so a plan rug shrunk to 0.9 m was saved at 10
            # (e2e J202 r4).
            trace.append({"tool": f"(fix round gave up; the edit before it scored {verdict['score']} < {REVIEW_KEEP}: not saved)",
                          "args": "", "out": str(verdict.get("summary"))[:700]})
            why_ = re.sub(r"\s*\[capped:[^\]]*\]", "", str(verdict.get("summary") or "")).strip()
            reply = (("ماغيّرتش حاجة: ماقدرتش أعمل التعديل والمخطط والـ3D متطابقين من غير ما أغيّر حاجة ماطلبتهاش، فسيبت كل حاجة زي ما كانت.")
                     if AR_TEXT.search(message) else
                     ("Nothing was changed: I couldn't make this change with the 2D plan and the 3D matching without also "
                      "changing something you didn't ask for" + (f" ({why_[:300]})" if why_ else "") + ", so I left everything as it was."))
        elif fixing and not ws.changed and before_fix[1]:
            # The fix round gave up (discarded): keep the edit from before it, not nothing (27 Oct 2026: a terrazzo floor
            # asked as mosaic was thrown away with the failed fix, 3 EGP for no change).
            kept_before = True
            ws.files.update(before_fix[0])
            ws.changed, ws.orig = set(before_fix[1]), dict(before_fix[2])
            ws.ops = defaultdict(list, {k_: list(v_) for k_, v_ in before_fix[3].items()})
            if ws.cfg["dxf"] in ws.changed and ws.dxf_path:
                ws.dxf_path.write_bytes(ws.files[ws.cfg["dxf"]])
            ws.plan_dirty = bool(ws.changed & {ws.cfg["dxf"], ws.cfg["tour"]})  # rebuild the model only for a plan / tour edit
            reply = before_fix[4] + (" (حاولت أحسّنه أكتر بس ماقدرتش، فسيبت التعديل ده.)" if AR_TEXT.search(message) else
                                     " (I tried to improve it further but couldn't, so I kept this.)")
            trace.append({"tool": "(fix round gave up: kept the edit before it)", "args": "", "out": ""})
        if fixing and ws.changed and kept_before:
            final = verdict  # what is saved is the edit the first review scored (the trace still holds the fix round's ops)
        elif fixing and ws.changed:  # the fixed edit's score, for the record
            emit("Checking the fix")
            final = review_edit(ws, message, reply, where, image, trace, review_total)
        last_v = final if fixing else verdict
        if ws.changed and last_v and last_v["score"] < REVIEW_KEEP:  # a miss isn't saved: say why, change nothing
            trace.append({"tool": f"(review {last_v['score']} < {REVIEW_KEEP}: not saved)", "args": "", "out": str(last_v.get("summary"))[:700]})
            ws.discard()
            # the reviewer's note, without its internal "[capped: ...]" tag, and only in an English chat: it is written in
            # English (e2e J216 / J229 r3)
            why = re.sub(r"\s*\[capped:[^\]]*\]", "", str(last_v.get("summary") or "")).strip()
            if reply and (GAVE_UP.search(reply) or reply.rstrip().endswith(("?", "؟"))) and not DID_INSTEAD.search(reply):
                # the model itself said it couldn't, or asked: that is the answer, not "the edit didn't do what you
                # asked" (e2e J211 / J221 r3)
                reply = reply if re.match(r"\s*(Nothing was changed|ماغيّرتش|ماتغيّرش|لسه ماتغيّرش)", reply) else \
                    ("ماتغيّرش حاجة. " if AR_TEXT.search(message) else "Nothing was changed. ") + reply
            else:
                reply = (("ماغيّرتش حاجة: التعديل اللي عملته ماكانش هو المطلوب. قولّي بالظبط عايز إيه يتغيّر وفين، وأنا أجرّب تاني.")
                         if AR_TEXT.search(message) else
                         ("Nothing was changed: the edit I made didn't do what you asked" + (f" ({why})" if why else "") +
                          ". Tell me exactly what to change and where, and I'll try again."))
        if ws.changed and not ws.plan_dirty:  # files that ended as they began (a move and its move back; a DXF rewritten with no net op: e2e J229)
            same_ = {p_ for p_ in ws.changed if p_ in ws.orig and ws.files.get(p_) == ws.orig[p_]}
            if "furnish.js" in ws.changed and "furnish.js" not in same_ and comment_only(ws.orig.get("furnish.js"), ws.text("furnish.js")):
                same_.add("furnish.js")  # only a comment changed: nothing the user sees (saved as an edit: e2e J223 / J240 r4)
            dw_ = ws.cfg.get("drawing")
            if dw_ in ws.changed and dw_ not in same_ and dw_ in ws.orig and drawing_same(ws.orig[dw_], ws.files.get(dw_)):
                same_ |= {ws.cfg.get(k) for k in ("dxf", "model", "drawing")} & ws.changed  # only header / handle noise
            if same_ == ws.changed or (ws.changed - same_ <= {ws.cfg.get(k) for k in ("dxf", "model", "drawing")}
                                       and ws.cfg.get("drawing") in same_):
                trace.append({"tool": "(no net change: not saved)", "args": "", "out": ", ".join(sorted(same_))[:700]})
                ws.discard()
        if ws.changed and reply and GAVE_UP.search(reply) and NO_CHANGE.search(reply) and "kept this" not in reply \
                and "فسيبت التعديل" not in reply:
            trace.append({"tool": "(reply says nothing changed: not saved)", "args": "", "out": reply[:700]})
            ws.discard()  # the reply says it couldn't / stayed put: what the user reads is what happens (e2e J229)
        if not ws.changed and reply and not re.match(r"\s*(Nothing was changed|ماغيّرتش|ماتغيّرش|لسه ماتغيّرش)", reply) \
                and (re.search(r"\b(I('ve| have)?|have been) (changed|made|moved|added|removed|replaced|updated|set)\b", reply)
                     or AR_CLAIM.search(reply)):  # Arabic too: "رجّعت عمق ..." with nothing changed (e2e J223 r3)
            reply = ("لسه ماتغيّرش حاجة: " if AR_TEXT.search(message) else "Nothing was changed yet: ") + reply  # claimed, never made
        if ws.changed:  # last gate: a settled design lock (design-locks.json) the request didn't name stays as it is
            if ws.plan_dirty:
                rebuild(ws)
                ws.plan_dirty = False
            if breaks := lock_breaks(ws, message, record=True):
                print(f"[edit-ai] refused, design lock: {lock_note(breaks)}", flush=True)
                ws.discard()
                reply = (("ماتغيّرش حاجة: التعديل ده كان هيلغي قرار اتفقتوا عليه — " + lock_note(breaks) +
                          ". لو عايز تغيّره فعلًا، قول كده واذكره بالاسم (العمود، حيطة التلفزيون، النيش أو البوفيه).")
                         if AR_TEXT.search(message) else
                         ("Nothing was changed: this edit would undo a decision you already settled — " + lock_note(breaks) +
                          ". If you do want to change that, say so and name it (e.g. the column, the TV wall, the niches or the buffet)."))
        if ws.changed:
            emit("Saving your edit")
        if ws.changed:
            with version_lock(v):
                result = save(ws, reply or message)
        else:
            result = None
    finally:
        shutil.rmtree(ws.tmp, ignore_errors=True)
    edit_all = dollars(total, model)
    fix_ = usd_sum(edit_all, -edit_usd) if fixing and edit_usd is not None else None
    costs = {"edit": edit_usd if fixing else edit_all, "fix": fix_,
             "review": dollars(review_total, REVIEW_MODEL) if verdict else None}
    costs["total"] = usd = usd_sum(costs["edit"], *(c for c in (fix_, costs["review"]) if c is not None))  # the page adds the precheck
    fixed = final["score"] if final else "?"
    scores = (f"{verdict['score']} -> {fixed}" if fixing else str(verdict["score"])) if verdict else "-"
    print(f"[edit-ai] {v} ({model}, {route}): {len(steps)} tool calls, {total['prompt_tokens']} in ({total['cached']} cached) / "
          f"{total['completion_tokens']} out tokens, review {scores}, {costs}; changed {sorted(ws.changed) or 'nothing'}", flush=True)
    review_ = verdict and {"score": verdict["score"], "summary": verdict["summary"], "improved": fixing,
                           "final": final and final["score"], "model": REVIEW_MODEL}
    # which check stopped an edit, also without debug: a refusal can be told apart without another paid run (e2e J275 r4)
    why_not = None if ws.changed else next((t_["out"][:400] for t_ in reversed(trace) if t_["tool"].startswith("(review")
                                            or t_["tool"].startswith("(fix round gave up")), None)
    return {"reply": reply or "Done.", "changed": sorted(ws.changed), "rev": result and result["rev"], "model": model,
            "whyNot": why_not,
            "route": route, "tokens": total, "usd": usd, "costs": costs, "review": review_, "steps": len(steps),
            "retryModel": live_model(COMPLEX_MODEL),
            "sync": result and result.get("sync"), **({"trace": trace} if req.get("debug") else {})}


COMPASS = {"north": re.compile(r"\bnorth(wards?)?\b|شمال", re.I), "south": re.compile(r"\bsouth(wards?)?\b|جنوب", re.I),
           "east": re.compile(r"\beast(wards?)?\b|شرق", re.I), "west": re.compile(r"\bwest(wards?)?\b|غرب", re.I)}
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")
GAVE_UP = re.compile(r"\b(couldn'?t|could not|can'?t|cannot|unable|wasn'?t able|not possible|left (it |them |everything )?(as it was|unchanged)|"
                     r"(made|changed) nothing|no changes?( were)? made|didn'?t change)\b", re.I)
AR_CLAIM = re.compile(r"(?:^|[\s،.])(?:و)?(رجّعت|رجعت|غيّرت|غيرت|كبّرت|كبرت|صغّرت|صغرت|وسّعت|وسعت|حرّكت|حركت|نقلت|لفّيت|لفيت|"
                      r"شلت|ضفت|أضفت|خلّيت|خليت|عملت|زوّدت|زودت|قصّرت|قصرت|طوّلت|طولت|عدّلت|عدلت)(?=[\s،.]|$)")
DID_INSTEAD = re.compile(r"\binstead\b|\b(so|but) I(\'ve| have)? (made|set|went|used|put|moved|added|changed|widened|resized)\b", re.I)
NO_CHANGE = re.compile(r"\b(stayed (in place|put|where it (was|is))|left (it |them |everything )?(as it was|in place|unchanged|where it was)|"
                       r"nothing (was |has been )?changed|no changes? (was |were )?made|(made|changed) nothing)\b|ماغيّرتش|ماتغيّرش", re.I)


def stands_on_floor(text, i, line):
    """Whether the item() at line i builds something standing on the floor (a named builder like bed(), or a box /
    cylinder from height 0), not a wall-hung or overhead thing (sheer, art, pendant) that has no plan footprint."""
    if re.search(r"\bitem\([^,]+,[^,]+,\s*\"[NSEW]\"\s*,\s*[A-Za-z_]\w*\s*(\(|\))", line):
        return not re.search(r"\"\s*,\s*(art|tv|mirror|sheer|curtain|pendant|ac|sconce|towelRail|rainHead|showerWall)\w*\b", line, re.I)
    L, blk, dep = text.splitlines(), "", 0
    for k in range(i - 1, min(i + 40, len(L))):
        blk += L[k] + "\n"
        dep += L[k].count("(") - L[k].count(")")
        if dep <= 0:
            break
    return bool(re.search(r"p\.box\([^,]+,[^,]+,\s*0(\.0+)?\s*,|p\.cyl\([^,]+,[^,]+,[^,]+,\s*0(\.0+)?\s*,", blk))


# Size words in a resize ask: which way the user wants the piece to go (a class of asks, not a phrase).
SHRINK = re.compile(r"\b(smaller|shorter|narrower|thinner|slimmer|shallower|less (wide|long|deep)|reduce|shrink|cut down|trim)\b|"
                    r"أصغر|اصغر|أقصر|اقصر|أضيق|اضيق|صغر|قصر", re.I)
GROW = re.compile(r"\b(bigger|larger|wider|longer|deeper|enlarge|extend|stretch|more (wide|long|deep))\b|"
                  r"أكبر|اكبر|أعرض|اعرض|أطول|اطول|كبر|وسع", re.I)
REMOVAL = re.compile(r"\b(remove|delete|close|block|wall up|fill in|get rid)\b|شيل|امسح|اقفل|اقفل|سد", re.I)


PLANT = re.compile(r"\bplant\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*(?:,\s*([\d.]+)\s*)?(?:,\s*([\d.]+)\s*)?(?:,\s*([\d.]+))?")


def footprint(txt):
    """What of a furnish.js snippet decides the plan footprint: where items stand (and their builder's arguments) and
    the across / out extents of its floor carcass boxes, leaving heights, doors, drawers and shelf styling out.
    Equal before and after = height / look / openable-only: the plan outline stays as it is."""
    heads = sorted(re.findall(r"\b(?:item|rug)\(([^;]*?)(?:, p =>|\)\s*;|$)", txt, re.M)) + LOOP.findall(txt)  # loop positions too
    builders = sorted(re.findall(r"\b(bed|wardrobe|vanity|sofa|chair)\(([^)]*)\)", txt))
    ext = []
    for m in re.finditer(r"\bp\.box\(([^;]*?)\)\s*(?:;|\.|$)", txt, re.M):
        a = [x.strip() for x in m[1].split(",")]
        if len(a) < 6:
            continue
        try:
            x0, x1, y0, y1, z0, z1 = (float(eval(a[k], {"__builtins__": {}}, {})) for k in range(6))
        except Exception:
            continue
        # Floor carcass only (sits on / near the floor, deeper than a door leaf): ignore door/drawer/shelf boxes.
        if y0 > 0.2 or (x1 - x0) * max(0.0, z1 - z0) < 0.08:
            continue
        ext.append((x0, x1, z0, z1))
    bb = (round(min(e[0] for e in ext), 3), round(max(e[1] for e in ext), 3), round(min(e[2] for e in ext), 3),
          round(max(e[3] for e in ext), 3)) if ext else None
    return (heads, builders, bb)


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
# Everyday Arabic names of the plan's rooms (the SYSTEM glossary too): a request naming one names that room.
AR_ROOMS = {"LIVING ROOM": ("صالة", "صاله", "ليفنج", "ليفينج"), "RECEPTION": ("ريسبشن", "رسبشن", "ريسيبشن", "استقبال"),
            "DINING": ("سفرة", "سفره", "سفرا"), "KITCHEN": ("مطبخ",), "LAUNDRY": ("غسيل", "مغسلة", "غساله"),
            "ENTRANCE": ("مدخل",), "HALLWAY": ("طرقة", "طرقه", "ممر", "كوريدور"),
            "MASTER BEDROOM": ("أوضة النوم", "اوضة النوم", "أوضه النوم", "اوضه النوم", "غرفة النوم", "الماستر", "أوضتي", "اوضتي"),
            "TOILET 1": ("الحمام الكبير", "الحمام الرئيسي", "حمام الماستر", "حمام أوضة النوم", "حمام اوضة النوم"),
            "TOILET 2": ("الحمام الصغير", "حمام الضيوف", "التواليت"), "TERRACE": ("تراس", "تيراس", "بلكونة", "بلكونه", "روف")}


# Fixtures only one kind of room has: "by the shower" names the bathroom it's in (e2e J225: a hook by the en-suite
# shower was refused because the camera stood in the bedroom).
ROOM_FIXTURES = {"TOILET": re.compile(r"\b(shower|bath(tub)?|basin|sink|vanity|wc|toilet|bidet|towel)\b|دش|شاور|بانيو|حوض|"
                                      r"تواليت|مرحاض|فوط", re.I),
                 "KITCHEN": re.compile(r"\b(oven|hob|cooker|stove|fridge|kitchen sink|extractor)\b|فرن|بوتاجاز|تلاجة|تلاجه", re.I),
                 "LAUNDRY": re.compile(r"\b(washer|washing machine|dryer)\b|غسالة|غساله|نشافة", re.I),
                 "TERRACE": re.compile(r"\b(bbq|barbecue|parapet|planter)\b|شواية", re.I)}


def room_named(name, message):
    """Whether the request names this room: a word of its label (English), one of its Arabic names, or a fixture only
    that kind of room has (the shower: a bathroom)."""
    n = (name or "").upper().rstrip(".")
    msg_l = (message or "").lower()
    return any(w in msg_l for w in n.lower().split() if len(w) > 3) or any(a in (message or "") for a in AR_ROOMS.get(n, ())) \
        or any(n.startswith(k) and rx.search(message or "") for k, rx in ROOM_FIXTURES.items())


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
        # the rooms the user circled into (seen through a doorway: the en-suite from the bedroom) count as pointed at
        aimed = {room_of(float(h["x"]), float(h["y"])) for h in c.get("hits") or [] if h.get("x") is not None and h.get("y") is not None}
        if (b_ := c.get("highlightBox")) and len(b_) == 4 and not c.get("wholeView"):
            aimed.add(room_of((b_[0] + b_[2]) / 2, (b_[1] + b_[3]) / 2))
        for i, px, py, line in added[:4]:
            r = room_of(px, py)
            other = names[r] if 0 <= r < len(names) else ""
            if home >= 0 and r >= 0 and r != home and r not in aimed and not room_named(other, message):
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


def js_num(expr, env):
    """A small JS number expression (literals, consts from env, version === "v" ? a : b, + - * /) as a float; raises if not."""
    e = expr.strip().replace("===", "==").replace("!==", "!=").replace("&&", " and ").replace("||", " or ")
    m = re.fullmatch(r"(.+?)\?(.+?):(.+)", e, re.S)
    if m:
        return js_num(m[2], env) if eval(m[1], {"__builtins__": {}}, env) else js_num(m[3], env)
    return float(eval(e, {"__builtins__": {}}, env))


def item_box(L, i, version):
    """(plan box x0, y0, x1, y1, lowest, deepest) of the item( built inline at 1-based line i of furnish.js lines L,
    from its readable p.box / p.cyl calls (simple consts and version ternaries resolved); None when it can't be read."""
    m = ITEM.search(L[i - 1])
    if not m:
        return None
    x, y, f = float(m[1]), float(m[2]), m[3]
    blk, dep = "", 0
    for k in range(i - 1, min(i + 60, len(L))):
        blk += L[k] + "\n"
        dep += L[k].count("(") - L[k].count(")")
        if dep <= 0:
            break
    env = {"version": version, "M": None}
    for c in re.finditer(r"\bconst (\w+) = ([^;,]+);", blk):
        try:
            env[c[1]] = js_num(c[2], env)
        except Exception:
            pass
    ext = []
    for s_ in PRIM.finditer(blk):
        a = [t.strip() for t in s_[2].split(",")]
        try:
            if s_[1] == "box":
                ext.append((js_num(a[0], env), js_num(a[1], env), js_num(a[2], env), js_num(a[4], env), js_num(a[5], env)))
            else:
                cx, cz, r_ = js_num(a[0], env), js_num(a[1], env), js_num(a[2], env)
                ext.append((cx - r_, cx + r_, js_num(a[3], env), cz - r_, cz + r_))
        except Exception:
            continue
    if not ext:
        return None
    ux, uy = {"S": (1, 0), "N": (-1, 0), "E": (0, 1), "W": (0, -1)}[f]
    fx, fy = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}[f]
    a0, a1 = min(e[0] for e in ext), max(e[1] for e in ext)
    z0, z1 = max(0.0, min(e[3] for e in ext)), max(e[4] for e in ext)
    pts = [(x + ux * u + fx * z, y + uy * u + fy * z) for u in (a0, a1) for z in (z0, z1)]
    return (min(p_[0] for p_ in pts), min(p_[1] for p_ in pts), max(p_[0] for p_ in pts), max(p_[1] for p_ in pts),
            min(e[2] for e in ext), z1)


def resized_off_plan(ws, f0, f1):
    """A note when an existing floor piece's 3D build now runs past the plan outline it stands on, or over the spot
    where a neighbouring piece stands: the 2D and 3D no longer show the same room."""
    if f0 == f1 or not plan_edits():
        return None
    L0, L1 = f0.splitlines(), f1.splitlines()
    old, old_t = {}, {}
    for i, px, py, l in placed_lines(ws, f0):
        if ITEM.search(l):
            old[(px, py)] = i
            old_t.setdefault(ITEM.sub("", l).strip(), i)  # the same line with its position changed
    floor = [(i, px, py, l) for i, px, py, l in placed_lines(ws, f1) if ITEM.search(l) and stands_on_floor(f1, i, l)]
    cur = None
    for i, px, py, line in floor:
        j = old.get((px, py), old_t.get(ITEM.sub("", line).strip()))
        if j is None:
            continue  # a new piece: unplanned() looks after it
        b1, b0 = item_box(L1, i, ws.v), item_box(L0, j, ws.v)
        if not b1 or not b0 or all(abs(u - w) < 0.01 for u, w in zip(b1[:4], b0[:4])) or b1[4] > 0.05:
            continue
        r3 = lambda v_: round(v_, 3)
        where = f"x {r3(b1[0])}..{r3(b1[2])}, y {r3(b1[1])}..{r3(b1[3])}"
        for k, qx, qy, l2 in floor:
            fq = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}[ITEM.search(l2)[3]]
            sx, sy = qx + 0.1 * fq[0], qy + 0.1 * fq[1]  # 10 cm in front of its back: inside that piece
            if k != i and b1[0] + 0.03 < sx < b1[2] - 0.03 and b1[1] + 0.03 < sy < b1[3] - 0.03 \
                    and not (b0[0] < sx < b0[2] and b0[1] < sy < b0[3]):
                return (f"Check 2D vs 3D: furnish.js line {i} ({line.strip()[:90]}) now builds x..y {where}, which runs "
                        f"over line {k} ({l2.strip()[:70]}), standing at ({qx}, {qy}): two pieces in one place. Fit it in "
                        "the room its neighbours leave (or move / resize the neighbour too, in both views) and keep the "
                        "plan outline matching, or put it back and tell the user how much room there is.")
        if cur is None:
            cur = ws.tmp / "plan-resized.dxf"
            cur.write_bytes(ws.read(ws.cfg["dxf"]))
        code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(cur), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                       f"--bbox={px - 0.05},{py - 0.05},{px + 0.05},{py + 0.05}", "--layers=2furni,2 furni", "--limit", "400"],
                      timeout=90)
        try:
            ents = json.loads(q).get("entities", [])
        except ValueError:
            continue
        outs = []
        for d in ents:
            ps = d.get("points") or []
            if d["type"] == "LWPOLYLINE" and len(ps) >= 4:
                c = (min(p_[0] for p_ in ps), min(p_[1] for p_ in ps), max(p_[0] for p_ in ps), max(p_[1] for p_ in ps))
                if (c[2] - c[0]) * (c[3] - c[1]) >= 0.04:
                    outs.append((d["handle"], c))
        lines_ = []
        if not outs:  # drawn as loose lines (the BBQ counter: e2e J228 r3): their extent inside its old box is its outline
            code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(cur), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                           f"--bbox={b0[0] - 0.03},{b0[1] - 0.03},{b0[2] + 0.03},{b0[3] + 0.03}", "--layers=2furni,2 furni", "--limit", "400"],
                          timeout=90)
            try:
                ents = json.loads(q).get("entities", [])
            except ValueError:
                ents = []
            for d in ents:
                ps = d.get("points") or ([d["bbox"][:2], d["bbox"][2:]] if d.get("bbox") else [])
                if ps and d["type"] in ("LINE", "LWPOLYLINE", "ARC") and all(b0[0] - 0.03 <= p_[0] <= b0[2] + 0.03 and b0[1] - 0.03 <= p_[1] <= b0[3] + 0.03 for p_ in ps):
                    lines_.append((d["handle"], ps))
            if len(lines_) < 3:
                continue
            allp = [p_ for _, ps in lines_ for p_ in ps]
            c = (min(p_[0] for p_ in allp), min(p_[1] for p_ in allp), max(p_[0] for p_ in allp), max(p_[1] for p_ in allp))
            if (c[2] - c[0]) < 0.5 * (b0[2] - b0[0]) or (c[3] - c[1]) < 0.5 * (b0[3] - b0[1]):
                continue  # a scrap of linework, not its drawing
            h = "the lines drawn for it (" + ", ".join(t[0] for t in lines_[:8]) + ")"
        else:
            # the outline that is its own footprint: the one best matching its old 3D box, never the rug under it (the
            # largest outline there was the reception rug, so a round coffee table shrank the plan rug: e2e J202 r4)
            rugs_ = [tuple(float(v_) for v_ in m_.groups()) for m_ in RUG.finditer(f0)]
            rugs_ = [(min(r_[0], r_[2]), min(r_[1], r_[3]), max(r_[0], r_[2]), max(r_[1], r_[3])) for r_ in rugs_]
            own_ = [t for t in outs if not any(all(abs(t[1][k] - r_[k]) < 0.05 for k in range(4)) for r_ in rugs_)
                    or _iou(t[1], b0[:4]) >= 0.5]
            if not own_:
                continue  # only the rug is drawn under it: a 3D-only piece standing on the rug
            h, c = max(own_, key=lambda t: (_iou(t[1], b0[:4]), (t[1][2] - t[1][0]) * (t[1][3] - t[1][1])))
        # made smaller in 3D while its drawing kept the old edge: the plan still shows the old size (e2e J228 r3)
        shrank = (b1[0] - b0[0], b1[1] - b0[1], b0[2] - b1[2], b0[3] - b1[3])  # how far each side came in
        kept = (b1[0] - c[0], b1[1] - c[1], c[2] - b1[2], c[3] - b1[3])  # how far the drawing reaches past the new 3D
        if max(min(s_, k_) for s_, k_ in zip(shrank, kept)) > 0.03:
            return (f"Check 2D vs 3D: furnish.js line {i} ({line.strip()[:90]}) now builds {where}, smaller than before, but "
                    f"on the plan {h} still runs x {r3(c[0])}..{r3(c[2])}, y {r3(c[1])}..{r3(c[3])}. Give the plan the same "
                    "change: resize_piece for an outline, or for loose lines dxf_edit \"scale\" on those handles (base = the "
                    "edge that stays, sx / sy = new / old size), so both views show the new size.")
        if lines_:
            continue
        grew = (b0[0] - b1[0], b0[1] - b1[1], b1[2] - b0[2], b1[3] - b0[3])  # how far each side went out
        past = (c[0] - b1[0], c[1] - b1[1], b1[2] - c[2], b1[3] - c[3])
        over = max((min(g_, p_) for g_, p_ in zip(grew, past)), default=0)
        if over > 0.03:
            return (f"Check 2D vs 3D: furnish.js line {i} ({line.strip()[:90]}) now builds {where}, {round(over * 100)} cm past "
                    f"its plan outline {h} (x {r3(c[0])}..{r3(c[2])}, y {r3(c[1])}..{r3(c[3])}). Give the outline the same "
                    "change (dxf_edit resize_piece / move_piece) so 2D and 3D match, or fit the 3D inside it; if there "
                    "isn't room, put it back and tell the user why."
                    + ("".join(f" The outline also holds line {k} ({l2.strip()[:60]}): growing this piece inside it means "
                               "making room there first (move / narrow that piece in both views) or telling the user it "
                               "doesn't fit." for k, qx, qy, l2 in floor[:40] if k != i and c[0] <= qx <= c[2] and c[1] - 0.02 <= qy <= c[3])[:400]))
    return None


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
        if deep is not None and b[2] - b[0] <= 0.45 and b[3] - b[1] <= 0.45:
            continue  # small free-standing decor (a floor lamp, a stool), 3D-only like the plants (e2e J315: a lamp refused)
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


# 3D-only pieces: what the plan (2furni) doesn't draw, so a change to them needs no DXF edit and no 2D vs 3D check.
# See docs/edit-ai/when-2d-needed.md. Head height: a fitting whose lowest part is above it doesn't take floor room.
HEAD_HEIGHT = 1.5
HEAD = re.compile(r"\b(item|rug|plant|art|ac|sconce|pendant)\(|\bfor \(const\b")
OVERHEAD_CALL = re.compile(r"^\s*(?:if \([^)]*\)\s*|else\s+)?(ac|pendant|sconce)\(")  # AC units, ceiling / wall lights
_MV = type("M", (), {"ceiling": 2.6, "winHead": 2.1, "sill": 0.9})()  # rough heights: enough to tell high from low


def _piece_at(L, j, version):
    """(head line no, block text) of the placed piece (item / ac / pendant ... call, or a for-loop of them) whose code
    covers 0-based line j of furnish.js lines L, or None (a builder definition, a const, top-level code)."""
    for h in range(j, max(-1, j - 40), -1):
        if not HEAD.search(L[h]):
            continue
        blk, dep, end = "", 0, h
        for k in range(h, min(h + 60, len(L))):
            blk += L[k] + "\n"
            dep += L[k].count("(") - L[k].count(")") + L[k].count("{") - L[k].count("}")
            end = k
            if dep <= 0:
                break
        return (h + 1, blk) if end >= j else None
    return None


def _lowest(blk, version):
    """The lowest readable height (box y0 / cyl y0) a piece's code builds at, or None."""
    env, low = {"version": version, "M": _MV}, None
    for s_ in PRIM.finditer(blk):
        a = [t.strip() for t in s_[2].split(",")]
        try:
            y0 = js_num(a[2] if s_[1] == "box" else a[3], env)
        except Exception:
            continue
        low = y0 if low is None else min(low, y0)
    return low


def _has_outline(ws, src, blk, version):
    """Whether a 2furni outline lies under the piece's (x, y) in the DXF file src; None if the position can't be read."""
    m = re.search(r"\b(?:item|rug|plant|art|ac|sconce|pendant)\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,", blk)
    try:
        px, py = js_num(m[1], {"version": version}), js_num(m[2], {"version": version})
    except Exception:
        return None
    code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(src), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                   f"--bbox={px - 0.05},{py - 0.05},{px + 0.05},{py + 0.05}", "--layers=2furni,2 furni", "--limit", "400"],
                  timeout=90)
    try:
        ents = json.loads(q).get("entities", [])
    except ValueError:
        return None
    for d in ents:
        ps = d.get("points") or []
        if d["type"] == "LWPOLYLINE" and len(ps) >= 4:
            xs, ys = [p_[0] for p_ in ps], [p_[1] for p_ in ps]
            if min(xs) - 0.15 <= px <= max(xs) + 0.15 and min(ys) - 0.15 <= py <= max(ys) + 0.15 \
                    and (max(xs) - min(xs)) * (max(ys) - min(ys)) >= 0.04:
                return True
    return False


def three_d_only(ws, f0, f1):
    """True when every furnish.js piece this message changed is one the plan doesn't draw: an AC unit, pendant or
    sconce; a fitting whose lowest part stays above head height before and after (plaster curtain / AC boxes,
    bulkheads, ceiling grilles, coves, high shelves); or a piece with no 2furni outline under it. Such edits (depth
    from the wall, height, finish) are 3D-only. False when any changed piece is drawn on the plan, a builder or
    shared const changed, or the change can't be read."""
    if f0 == f1:
        return False
    def bare(l):
        return re.sub(r"\s+", "", re.sub(r"\s//.*$", "", l))
    L0, L1 = f0.splitlines(), f1.splitlines()
    pairs = []  # (old 0-based line, new 0-based line) of each changed code line
    for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0, L1, autojunk=False).get_opcodes():
        if tag_ in ("replace", "delete"):
            pairs += [(i, j0 + min(i - i0, max(0, j1 - j0 - 1)) if j1 > j0 else None) for i in range(i0, i1)
                      if bare(L0[i]) and (tag_ == "delete" or bare(L0[i]) not in {bare(n_) for n_ in L1[j0:j1]})]
        elif tag_ == "insert":
            pass  # a new line on its own is a new piece: unplanned() looks after it
    if not pairs:
        return False
    src, seen = None, set()
    for i, j in pairs:
        old = _piece_at(L0, i, ws.v)
        if not old:
            return False  # a builder / const / shared code: many pieces may change
        if old[0] in seen:
            continue
        seen.add(old[0])
        head = L0[old[0] - 1]
        if OVERHEAD_CALL.search(head):
            continue
        new = _piece_at(L1, j, ws.v) if j is not None else None
        lo0, lo1 = _lowest(old[1], ws.v), (_lowest(new[1], ws.v) if new else None)
        if lo0 is not None and lo0 >= HEAD_HEIGHT and (new is None or (lo1 is not None and lo1 >= HEAD_HEIGHT)):
            continue  # stays overhead: a curtain / AC box, bulkhead, grille, cove
        if lo0 is not None and lo0 >= HEAD_HEIGHT and lo1 is not None and lo1 < HEAD_HEIGHT:
            return False  # came down below head height: it now takes room the plan should show
        if not plan_edits():
            return False
        if src is None:
            src = ws.tmp / "plan-3d-only.dxf"
            src.write_bytes(ws.orig.get(ws.cfg["dxf"]) or ws.read(ws.cfg["dxf"]))
        if _has_outline(ws, src, old[1], ws.v) is not False:
            return False  # drawn on the plan (or position unreadable): keep 2D and 3D in step
    return True


def lock_breaks(ws, message, record=False):
    """Design locks (design-locks.json) this edit would newly break and the request doesn't name: [(lock, problems)].
    record: when the only breaks are ones the request names, mark those locks suspended in the edit's design-locks.json."""
    import check_locks
    locks = [l for l in check_locks.load_locks(ws.read) if l.get("version") in (None, ws.v) and not l.get("suspended")]
    named = []
    if not locks:
        return []
    paths = {"furnish.js"} | {l["model"] for l in locks if "model" in l}
    before = {p: (ws.orig.get(p) or ws.read(p)).decode() for p in paths}
    after = {p: ws.read(p).decode() for p in paths}
    out = []
    for lock in locks:
        def probs(files):
            try:
                return check_locks.check(lock, files)
            except Exception as e:  # noqa: BLE001
                return [f"check failed: {e}"]
        now = probs(after)
        if now and not probs(before):
            if check_locks.named(lock, message):
                named.append(lock)  # on purpose: saved, and the lock is suspended below so pushes and later edits go on
            else:
                out.append((lock, now))
    if named and not out and record:
        data = json.loads(ws.read("design-locks.json"))
        ids = {l["id"] for l in named}
        for l in data["locks"]:
            if l["id"] in ids:
                l["suspended"] = {"by_request": (message or "")[:200], "date": time.strftime("%Y-%m-%d"),
                                  "note": "changed on purpose through Edit AI; set the new numbers here and drop 'suspended' to re-lock"}
        ws.write("design-locks.json", (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())
    return out


def lock_note(breaks):
    return "; ".join(f"{l['what']} (decided by {l.get('decided_by')}, {l.get('date')}): {', '.join(p)}" for l, p in breaks)


def footprint_at(L, i, line, version):
    """The plan box (x0, y0, x1, y1) a furnish.js line places: a rug's rectangle (its placing point is a corner, not its
    middle: e2e J214), an inline item's build; None when it can't be read (a helper like vanity(...))."""
    if (m := RUG.search(line)):
        a = [float(t) for t in m.groups()]
        return (min(a[0], a[2]), min(a[1], a[3]), max(a[0], a[2]), max(a[1], a[3]))
    b = item_box(L, i, version) if 0 < i <= len(L) else None
    return b and tuple(b[:4])


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _iou(a, b):
    i_ = _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))
    return i_ / (_area(a) + _area(b) - i_) if i_ else 0.0


def block_end(L, i):
    """The last line (1-based) of the call that opens at line i: its parentheses close again."""
    dep = 0
    for k in range(i - 1, min(i + 120, len(L))):
        dep += L[k].count("(") - L[k].count(")")
        if dep <= 0:
            return k + 1
    return i


PIECE_STOP = set("""make move moved shrink widen bigger smaller wider narrower longer shorter taller raise lower change colour
color turn rotate closer toward towards away from with the and into onto more less little please add remove delete swap
centre center left right north south east west floating deep deeper high higher tall wide long round black white this that
them those these its put place set new also just bit slightly side next beside near nearer over under above below behind
front back the for your my our their other same than then there here what where which each every both all only keep
inch metre metres meter meters about some one two three four five six seven eight nine ten face facing make sure piece
pieces thing things area room""".split())


def plan_symbol_at(ws, x, y, facing):
    """(handle, box) of the smallest 2furni outline or furniture block (as the plan before this message drew it) under
    the front of an item whose back-centre is at x, y facing `facing`; None when it isn't drawn on the plan."""
    fx, fy = {"S": (0, -1), "N": (0, 1), "E": (1, 0), "W": (-1, 0)}[facing]
    px, py = x + 0.25 * fx, y + 0.25 * fy
    src = ws.tmp / "plan-sym.dxf"
    src.write_bytes(ws.orig.get(ws.cfg["dxf"]) or ws.read(ws.cfg["dxf"]))
    try:
        code, q = run([dwg_python(), str(ROOT / "edit_ai_dxf.py"), "query", str(src), f"--origin={ORIGIN[0]},{ORIGIN[1]}",
                       f"--bbox={px - 0.1},{py - 0.1},{px + 0.1},{py + 0.1}", "--layers=2furni,2 furni", "--limit", "200", "--blocks"],
                      timeout=90)
        ents = json.JSONDecoder().raw_decode(q.lstrip())[0].get("entities", [])
    except Exception:
        return None
    rugs = [(min(t[0], t[2]), min(t[1], t[3]), max(t[0], t[2]), max(t[1], t[3]))
            for m_ in RUG.finditer(ws.text("furnish.js")) for t in [[float(v_) for v_ in m_.groups()]]]
    hits = []
    for d in ents:
        ps = d.get("points") or ([d["bbox"][:2], d["bbox"][2:]] if d.get("bbox") else [])
        if not ps or not (d["type"] == "INSERT" or d["type"] == "LWPOLYLINE" and (len(ps) >= 4 or d.get("n_points", 0) >= 4)):
            continue
        b = [min(p[0] for p in ps), min(p[1] for p in ps), max(p[0] for p in ps), max(p[1] for p in ps)]
        if any(all(abs(b[k] - r_[k]) < 0.06 for k in range(4)) for r_ in rugs):
            continue  # the rug it stands on isn't its symbol
        if b[0] <= px <= b[2] and b[1] <= py <= b[3] and 0.04 <= _area(b) <= 6:
            hits.append((d["handle"], [round(t, 3) for t in b]))
    return min(hits, key=lambda h: _area(h[1])) if hits else None


NOT_FOUND = re.compile(r"\b(isn'?t present|not present|couldn'?t find|can'?t find|could not find|cannot find|doesn'?t exist|"
                       r"does not exist|isn'?t in (the|this)|no \w+( \w+)? in the|which (one|desk|piece|\w+) did you mean)\b", re.I)


def missing_claim(ws, message, reply):
    """A give-up that says the named piece isn't there, when this version's furnish file names exactly one piece so
    (Karim's one flip desk: "its builder isn't present" / "which desk did you mean?"; e2e J266 r3). A message, or None."""
    if ws.changed or not reply or not NOT_FOUND.search(reply) or getattr(ws, "found_warned", False) or AR_TEXT.search(message):
        return None
    text = ws.text("furnish.js")
    sc = version_scope(text, ws.v)
    toks = re.findall(r"[a-z]+", message.lower())
    for a_, b_ in zip(toks, toks[1:]):
        if a_ in PIECE_STOP or b_ in PIECE_STOP or len(a_) < 3 or len(b_) < 3:
            continue
        rx = re.compile(r'(?:label\(\s*"|named\([^,]+,\s*"|//\s*)[^"\n]*\b' + re.escape(f"{a_} {b_}") + r"\b", re.I)
        hits = [i for i, l in enumerate(text.splitlines(), 1) if rx.search(l) and sc[i - 1] is not False]
        if hits and len({text.splitlines()[i - 1].strip() for i in hits}) == 1:
            ws.found_warned = True
            return (f"Check: you said the {a_} {b_} isn't there, but furnish.js line {hits[0]} builds it in this version "
                    f"({text.splitlines()[hits[0] - 1].strip()[:120]}); it is the only one, so it is the piece the user means, "
                    "wherever they stand. Read its build and make the change (both views if it's on the plan), then say which "
                    "room it's in.")
    return None


def piece_checks(ws, message, f0, f1, tail):
    """The piece the request names, and the way it asked a piece to go, against what the edit changed (deterministic,
    not just the prompt: e2e r2 J202 J207 J244 J264 J266). A message to send back, or None."""
    if f0 == f1 or AR_TEXT.search(message):
        return None
    L0, L1 = f0.splitlines(), f1.splitlines()
    placed = [(i, px, py, line) for i, px, py, line in placed_lines(ws, f0)]
    spans = {i: block_end(L0, i) for i, _, _, _ in placed}
    def owner(k):  # the innermost placed block holding f0 line k (1-based)
        hold = [i for i, _, _, _ in placed if i <= k <= spans[i]]
        return max(hold) if hold else None
    changed, pairs = set(), []
    for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0, L1, autojunk=False).get_opcodes():
        if tag_ == "equal":
            continue
        for k in range(i0 + 1, i1 + 1):
            if (o := owner(k)) is not None and L0[k - 1].strip():
                changed.add(o)
        if tag_ == "replace" and i1 - i0 == j1 - j0:
            pairs += list(zip(range(i0 + 1, i1 + 1), L1[j0:j1]))
    if not changed:
        return None  # only new pieces / materials: nothing named was missed
    text_of = {i: "\n".join(L0[i - 1:spans[i]]).lower() for i, _, _, _ in placed}
    at = {i: (px, py) for i, px, py, _ in placed}
    # the piece to change is the verb's object, before any reference word: "move the chairs closer to the table, keep the
    # table where it is" names the table only as a landmark (the gate made the model move it: e2e J235 / J250 r3)
    head = re.split(r"\b(?:to|towards?|closer|nearer|next|beside|besides|near|from|away|above|below|over|under|underneath|"
                    r"behind|front|than|between|against|keep|leave|facing|opposite|by|with|without)\b|[,;.]", message.lower())[0]
    toks = re.findall(r"[a-z]+", head)
    hb = (ws.ctx or {}).get("highlightBox")
    in_ring = lambda i: bool(hb) and len(hb) == 4 and hb[0] - 0.3 <= at[i][0] <= hb[2] + 0.3 and hb[1] - 0.3 <= at[i][1] <= hb[3] + 0.3
    room = (ws.ctx or {}).get("room")
    try:
        sm_ = ws.text(ws.cfg["model"])
        rr_ = [f["outer"] for f in json.loads(sm_[sm_.index("{"):sm_.rindex("}") + 1]).get("floor", []) if f.get("room") == room]
    except Exception:
        rr_ = []
    in_room = lambda i: any(_inside([q[:2] for q in r_], *at[i]) for r_ in rr_)
    def tell(phrase, want, got):
        w_, g_ = want[0], sorted(got)[0]
        return (f"Check the piece: the user named the {phrase}, which furnish.js builds at line {w_} ({L0[w_ - 1].strip()[:90]}), "
                f"but what you changed is the piece at line {g_} ({L0[g_ - 1].strip()[:90]}), a different one. Call discard "
                f"and change the {phrase} itself (and its plan outline if it has one); if you're not sure which one they mean, "
                "ask instead of editing." + tail)
    # a two-word name ("flip desk") that some piece carries: one of the changed pieces must carry it
    for a_, b_ in zip(toks, toks[1:]):
        if a_ in PIECE_STOP or b_ in PIECE_STOP or len(a_) < 3 or len(b_) < 3:
            continue
        ph = f"{a_} {b_}"
        has = [i for i in text_of if ph in text_of[i]]
        if not has:
            continue
        if not any(ph in text_of[i] for i in changed):
            return tell(ph, has, changed)
        if room and rr_ and (ws.ctx or {}).get("wholeView") and not any(in_room(i) for i in changed if ph in text_of[i]) \
                and (mine := [i for i in has if in_room(i)]):
            return tell(f"{ph} in the {room} (where the user is)", mine, changed)
        break
    else:  # one word ("buffet"): only when a piece carrying it is in the circle the user drew
        for w in toks:
            if len(w) < 4 or w in PIECE_STOP:
                continue
            rx = re.compile(r"\b" + re.escape(w) + r"(e?s)?\b")
            has = [i for i in text_of if rx.search(text_of[i])]
            if has and not any(rx.search(text_of[i]) for i in changed) and (mine := [i for i in has if in_ring(i)]):
                return tell(w, mine, changed)
    # "toward / closer to / away from X": the moved piece's distance to X must go the asked way
    m = re.search(r"\b(towards?|closer to|nearer( to)?|away from)\s+(?:the |my |our )?([a-z]+)", message.lower())
    if m and m[3] not in PIECE_STOP:
        rx = re.compile(r"\b" + re.escape(m[3]) + r"(e?s)?\b")
        marks = [at[i] for i in text_of if rx.search(text_of[i]) and i not in changed]
        moved = []
        for k, new in pairs:
            a0, a1 = PLACE.search(L0[k - 1]), PLACE.search(new)
            if a0 and a1 and (float(a0[1]), float(a0[2])) != (float(a1[1]), float(a1[2])):
                moved.append(((float(a0[1]), float(a0[2])), (float(a1[1]), float(a1[2])), L0[k - 1].strip()[:80]))
        if marks and moved:
            cx, cy = sum(p_[0] for p_ in marks) / len(marks), sum(p_[1] for p_ in marks) / len(marks)
            away = m[1] == "away from"
            gain = lambda o_, n_: math.dist(o_, (cx, cy)) - math.dist(n_, (cx, cy))  # > 0: it went closer
            wrong = [(o_, n_, l_) for o_, n_, l_ in moved if (gain(o_, n_) > -0.01 if away else gain(o_, n_) < 0.01)]
            if len(wrong) == len(moved):
                o_, n_, l_ = wrong[0]
                return (f"Check the direction: the user asked for it {m[1]} the {m[3]} (plan ({round(cx, 2)}, {round(cy, 2)}), "
                        f"the middle of what furnish.js builds as {m[3]}), but you moved {l_} from ({o_[0]}, {o_[1]}) to "
                        f"({n_[0]}, {n_[1]}), which is {'closer to' if away else 'no closer to'} it. Undo that (call discard) and "
                        "move it the asked way (both views), or tell the user why it can't go that way." + tail)
    return None


def review(ws, message, reply):
    """What to point out to the model before its edits are saved, or None."""
    if not ws.changed:
        return None
    if GAVE_UP.search(reply or "") and not DID_INSTEAD.search(reply or ""):
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
    if breaks := lock_breaks(ws, message):
        return ("Your edit breaks a settled design decision the user didn't ask to change, so it can't be saved: "
                f"{lock_note(breaks)}. Put those numbers back (keep the rest of your edit), check, then reply; or call "
                "discard if the request can't be done without it.")
    tail = (" Then reply to the user as you normally would, about the change itself compared with how it was before their "
            "request (a piece you added is \"added\", not \"moved\"; don't mention this check).")
    f0 = ws.orig["furnish.js"].decode() if "furnish.js" in ws.orig else ws.text("furnish.js")
    f1 = ws.text("furnish.js")
    # A whole-piece move written as p.g.position / rotation inside the build: item() overwrites both after the build runs,
    # so it did nothing, saved at review 10 as "moved 20 cm left" (e2e J304 r4).
    gpos_ = re.compile(r"\bp\.g\.(position|rotation)\b[^;\n]*?(=|\.set\(|\.(add|sub)\w*\()")
    new_g = [l_.strip() for l_ in set(f1.splitlines()) - set(f0.splitlines()) if gpos_.search(l_)]
    if new_g:
        return (f"Check the move: `{new_g[0][:100]}` sets the piece's group position / rotation inside its build, but item() "
                "sets both after the build runs, so nothing moves. Change the item(x, y, facing, ...) numbers instead (and "
                "move its plan outline the same with dxf_edit move_piece), and remove that line." + tail)
    # An existing material changed in place: every piece using it would change.
    if not ALL_VERSIONS.search(message):
        hit_ = mats_changed(ws)
        if hit_:
            uses = len(re.findall(r"\bmat\." + re.escape(hit_[0]) + r"\b", f1))
            return (f"Check the material: you changed the existing material {hit_[0]} in materials.js, which {uses} place(s) in "
                    "furnish.js use (other pieces too). Put it back as it was, add a new material next to it "
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
    # A distance the user named for a move, and the plan piece moved a different distance (the sofa: 3D 30 cm, plan 9 cm,
    # reply "30 cm"; e2e J201 r3). Said once; a move the plan clamped ("ONLY n cm FREE") is told to the user instead.
    dm_ = re.search(r"(\d+(?:\.\d+)?)\s*(cm|centimet|سم|سنتي)", message, re.I)
    mv_ = [math.hypot(*m_) for m_ in ws.moves if math.hypot(*m_) > 0.01]
    if dm_ and mv_ and MOVE_ASK.search(message) and not SHRINK.search(message) and not GROW.search(message) \
            and not getattr(ws, "clamped", False) and not getattr(ws, "dist_warned", False):
        want_d = float(dm_[1]) / 100
        if not any(abs(d_ - want_d) <= 0.02 for d_ in mv_):
            ws.dist_warned = True
            return (f"Check the distance: the user asked for {dm_[1]} cm, but on the plan the piece moved "
                    f"{', '.join(f'{round(d_ * 100)} cm' for d_ in mv_[:3])}. Move the plan piece by exactly the asked distance "
                    "(move_piece dx / dy from where it stands now, not to line it up with the 3D), give the 3D the same move "
                    "from where it stood, or tell the user why it can't go that far." + tail)
    if (pc_ := piece_checks(ws, message, f0, f1, tail)):
        return pc_
    # "Turn it to face the TV": the new facing letter must point at the TV nearest the piece (the armchair turned N, away
    # from the TV to its west, saved at review 10: e2e J206 r4). Said once.
    if f0 != f1 and TURN_ASK.search(message) and TV_WORD.search(message) and not getattr(ws, "face_warned", False):
        L0f, L1f = f0.splitlines(), f1.splitlines()
        # each TV's wall spot and the way its screen faces (a viewer faces the other way): its box often can't be read
        tvs = [(px_, py_, ft_[1]) for _, px_, py_, l_ in placed_lines(ws, f1)
               if re.search(r"\bTV\b", l_) and (ft_ := ITEM_FACING.search(l_))]
        opp_ = {"N": "S", "S": "N", "E": "W", "W": "E"}
        for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0f, L1f, autojunk=False).get_opcodes():
            if tag_ != "replace" or i1 - i0 != j1 - j0 or not tvs:
                continue
            for k_ in range(i1 - i0):
                fa_, fb_ = ITEM_FACING.search(L0f[i0 + k_]), ITEM_FACING.search(L1f[j0 + k_])
                b1_ = item_box(L1f, j0 + k_ + 1, ws.v)
                if not (fa_ and fb_ and fa_[1] != fb_[1] and b1_):
                    continue
                cx_, cy_ = (b1_[0] + b1_[2]) / 2, (b1_[1] + b1_[3]) / 2
                tx_, ty_, tf_ = min(tvs, key=lambda c_: math.dist((cx_, cy_), c_[:2]))
                if math.dist((cx_, cy_), (tx_, ty_)) > 6:
                    continue  # that TV is in another room (one it can't read, the living room's: no word)
                want_f = opp_[tf_]
                if fb_[1] != want_f:
                    ws.face_warned = True
                    return (f"Check the direction: the user asked to turn it toward the TV. The nearest TV is on the wall at plan "
                            f"({tx_}, {ty_}), its screen facing \"{tf_}\", so a piece looking at it faces \"{want_f}\"; you "
                            f"gave it \"{fb_[1]}\", which looks away. Use \"{want_f}\" (north = +y, east = +x), keep the piece's "
                            "middle where it was and turn its plan symbol the same way, or call discard and tell the user why "
                            "it can't face the TV." + tail)
    # A piece turned in the 3D (its facing letter) while nothing on the plan turned (e2e J206 / J301). Advice the first
    # time; after that a gate when the plan does draw it (its outline or block under its front): a turn in 3D only, saved
    # at review 10 with "its plan footprint is unchanged", left the plan armchair facing the old way (e2e J206 / J301 r3).
    if f0 != f1 and not getattr(ws, "rotated", False):
        L0t, L1t = f0.splitlines(), f1.splitlines()
        for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0t, L1t, autojunk=False).get_opcodes():
            if tag_ != "replace" or i1 - i0 != j1 - j0:
                continue
            for k_, (a_, b_) in enumerate(zip(L0t[i0:i1], L1t[j0:j1])):
                fa_ = ITEM_FACING.search(a_)
                fb_ = ITEM_FACING.search(b_)
                if not (fa_ and fb_ and fa_[1] != fb_[1]):
                    continue
                if not getattr(ws, "turn_warned", False):
                    ws.turn_warned = True
                    return (f"Check 2D vs 3D: you turned {b_.strip()[:100]} in the 3D (facing {fa_[1]} -> {fb_[1]}) but nothing on the "
                            "plan turned. If it is drawn there (furniture_near shows its outline or block), turn that too with "
                            "dxf_edit rotate_piece about the piece's centre (it turns blocks as well). A new facing letter swings the "
                            "item about its back-centre, so also move its x, y so the piece's centre stays where it was. If it isn't "
                            "drawn on the plan, keep your 3D edit: you're done." + tail)
                pm_ = PLACE.search(a_)
                sym_ = pm_ and plan_symbol_at(ws, float(pm_[1]), float(pm_[2]), fa_[1])
                if sym_:
                    return (f"Check the turn: {b_.strip()[:100]} turned in the 3D, but its plan symbol {sym_[0]} (x {sym_[1][0]}.."
                            f"{sym_[1][2]}, y {sym_[1][1]}..{sym_[1][3]}) still faces the old way. Turn it with dxf_edit rotate_piece "
                            f"(handle {sym_[0]}, the same angle, about its centre), or call discard and tell the user the turn "
                            "couldn't be made on the plan. Never say the plan is unchanged for a turn." + tail)
    # A pure turn ("turn it to face the TV") keeps the piece's middle where it was: a new facing letter alone swings it
    # about its back-centre (the armchair's middle went 40 cm: e2e J301 r3). Said once.
    if f0 != f1 and not MOVE_ASK.search(re.sub(r"\b(turn|rotate|face|facing)\b.*", "", message, flags=re.I)) \
            and not getattr(ws, "centre_warned", False):
        L0c, L1c = f0.splitlines(), f1.splitlines()
        for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0c, L1c, autojunk=False).get_opcodes():
            if tag_ != "replace" or i1 - i0 != j1 - j0:
                continue
            for k_ in range(i1 - i0):
                fa_ = ITEM_FACING.search(L0c[i0 + k_])
                fb_ = ITEM_FACING.search(L1c[j0 + k_])
                if not (fa_ and fb_ and fa_[1] != fb_[1]):
                    continue
                b0_, b1_ = item_box(L0c, i0 + k_ + 1, ws.v), item_box(L1c, j0 + k_ + 1, ws.v)
                if b0_ and b1_:
                    c0_ = ((b0_[0] + b0_[2]) / 2, (b0_[1] + b0_[3]) / 2)
                    c1_ = ((b1_[0] + b1_[2]) / 2, (b1_[1] + b1_[3]) / 2)
                    if math.dist(c0_, c1_) > 0.05:
                        ws.centre_warned = True
                        return (f"Check the turn: turning {L1c[j0 + k_].strip()[:100]} moved its middle from ({round(c0_[0], 3)}, "
                                f"{round(c0_[1], 3)}) to ({round(c1_[0], 3)}, {round(c1_[1], 3)}), {round(math.dist(c0_, c1_) * 100)} cm, "
                                "but the user only asked to turn it. Shift its x, y so the middle stays where it was (and turn its "
                                "plan symbol about that same middle)." + tail)
    # A resize the user asked to go one way (shorter / wider) while a plan outline went the other: 2D and 3D disagree.
    want_ = -1 if SHRINK.search(message) and not GROW.search(message) else 1 if GROW.search(message) and not SHRINK.search(message) else 0
    if want_ and ws.pieces:
        wrong_ = []
        for h, b0 in ws.pieces.items():
            b1 = getattr(ws, "pieces_now", {}).get(h)
            if not b0 or not b1:
                continue
            dws = [((b1[2] - b1[0]) - (b0[2] - b0[0]), "x"), ((b1[3] - b1[1]) - (b0[3] - b0[1]), "y")]
            moved_ = [(d_, ax_) for d_, ax_ in dws if abs(d_) > 0.005]
            if moved_ and all(d_ * want_ < 0 for d_, _ in moved_):
                wrong_.append(f"{h} ({', '.join(f'{ax_} {round(d_ * 100):+d} cm' for d_, ax_ in moved_)})")
        if wrong_:
            return (f"Check 2D vs 3D: the user asked for it {'smaller' if want_ < 0 else 'bigger'}, but on the plan "
                    f"{'; '.join(wrong_)} got {'BIGGER' if want_ < 0 else 'SMALLER'}. In resize_piece grow, a positive value "
                    "pushes that edge OUT (bigger) and a negative one pulls it IN (smaller). Redo the outline the right way "
                    "(the same change as the 3D piece), so the plan and the 3D agree." + tail)
    if want_ and f0 != f1:  # and the 3D: a builder's size arguments (bed(1.9, 2.15)) all went the other way
        def args_(line, text):
            m = re.search(r'\bitem\([^,]+,[^,]+,\s*"[NSEW]"\s*,\s*(\w+)\(([^()]*)\)', line)
            if not m:
                return None
            d = re.search(r"\bconst " + m[1] + r" = \(([^)]*)\) =>", text)
            defs = [a.split("=")[1].strip() if "=" in a else None for a in d[1].split(",")] if d else []
            got = [a.strip() for a in m[2].split(",")] if m[2].strip() else []
            out = []
            for k in range(max(len(defs), len(got))):
                v = got[k] if k < len(got) else (defs[k] if k < len(defs) else None)
                try:
                    out.append(float(v))
                except (TypeError, ValueError):
                    out.append(None)
            return m[1], out
        L0d, L1d = f0.splitlines(), f1.splitlines()
        for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0d, L1d, autojunk=False).get_opcodes():
            if tag_ != "replace" or i1 - i0 != j1 - j0:
                continue
            for a_, b_ in zip(L0d[i0:i1], L1d[j0:j1]):
                o_, n_ = args_(a_, f0), args_(b_, f1)
                if not o_ or not n_ or o_[0] != n_[0]:
                    continue
                ds = [y - x for x, y in zip(o_[1], n_[1]) if x is not None and y is not None and abs(y - x) > 0.005]
                if ds and all(d_ * want_ < 0 for d_ in ds):
                    return (f"Check 2D vs 3D: the user asked for it {'smaller' if want_ < 0 else 'bigger'}, but in the 3D "
                            f"{b_.strip()[:100]} makes {n_[0]}() {'BIGGER' if want_ < 0 else 'SMALLER'} than before "
                            f"({', '.join(str(x) for x in o_[1] if x is not None)} -> {', '.join(str(y) for y in n_[1] if y is not None)}). "
                            "Redo the 3D the way the user asked, the same change as the plan outline, so both agree." + tail)
    # furnish.js edits that only touch lines which never run for this version.
    if f0 != f1:
        sc0, sc1 = version_scope(f0, ws.v), version_scope(f1, ws.v)
        L0, L1_ = f0.splitlines(), f1.splitlines()
        touched = []
        for tag_, i0, i1, j0, j1 in difflib.SequenceMatcher(None, L0, L1_, autojunk=False).get_opcodes():
            if tag_ == "equal":
                continue
            touched += [sc1[j] for j in range(j0, j1) if L1_[j].strip()] + [sc0[i] for i in range(i0, i1) if L0[i].strip() and tag_ in ("delete", "replace")]
        if touched and all(t_ is False for t_ in touched):
            return (f"Check the version: every line you changed in furnish.js sits in a branch that never runs here "
                    f"(a leftover `if (version === ...)` block for another version), so nothing changes in what the user sees. "
                    f"Find the line that builds this piece for \"{ws.v}\" (furniture_near lists only the ones that run here), "
                    "put the change there instead and revert the edit you made." + tail)
    def bare(l):  # a line's code, without its trailing // comment or spacing (a comment-only edit isn't a change)
        return re.sub(r"\s+", "", re.sub(r"\s//.*$", "", l))
    now = {bare(l) for l in f1.splitlines()}
    # A plan piece moved / resized: the 3D line(s) standing on it must have changed too.
    L0_, L1b = f0.splitlines(), f1.splitlines()
    def build_changed(i, line):  # an inline build whose size changed under an unchanged item( line
        j = next((k for k, l2 in enumerate(L1b, 1) if bare(l2) == bare(line)), None)
        if j and [bare(l_) for l_ in L0_[i - 1:block_end(L0_, i)]] != [bare(l_) for l_ in L1b[j - 1:block_end(L1b, j)]]:
            return True  # its build was rewritten (a round table's body): changed, even where its box can't be read (e2e J202)
        b0_, b1_ = item_box(L0_, i, ws.v), (item_box(L1b, j, ws.v) if j else None)
        return bool(b0_ and b1_ and any(abs(u - w) > 0.01 for u, w in zip(b0_[:4], b1_[:4])))
    for h, b in ws.pieces.items():
        nb = getattr(ws, "pieces_now", {}).get(h, False)
        if not b:
            continue  # a new outline: unplanned() checks it has its 3D piece
        if nb and all(abs(u - w) < 0.002 for u, w in zip(nb, b)):
            continue  # put back where it was: nothing to match
        if nb is None and any(not ws.pieces.get(h2) and n2 and all(abs(u - w) < 0.01 for u, w in zip(n2, b))
                              for h2, n2 in getattr(ws, "pieces_now", {}).items()):
            continue  # deleted, then drawn again in the same place under a new handle: put back (e2e J213 r4)
        on = lambda px, py: b[0] - 0.15 <= px <= b[2] + 0.15 and b[1] - 0.15 <= py <= b[3] + 0.15
        loops = [(i, ls) for i, px, py, ls in loop_placed(ws, f0) if on(px, py)]  # e.g. one of two bedside tables
        def on_b(i, px, py, line):
            fp_ = footprint_at(L0_, i, line, ws.v)
            if RUG.search(line) and fp_ and _iou(fp_, b) < 0.5:
                return False  # the rug under a chair / table isn't that piece's 3D line (e2e J210 / J206 r4)
            if fp_ and _area(fp_) > 1e-4 and _area(b) > 1e-4:  # its footprint, not its placing point (a rug's corner: J213)
                return _area((max(fp_[0], b[0]), max(fp_[1], b[1]), min(fp_[2], b[2]), min(fp_[3], b[3]))) >= 0.3 * min(_area(fp_), _area(b))
            return on(px, py)
        lines = [(i, [line]) for i, px, py, line in placed_lines(ws, f0) if on_b(i, px, py, line)] + loops
        if lines and all(bare(l) in now for _, ls in lines for l in ls) \
                and not any(build_changed(i, ls[-1]) for i, ls in lines if len(ls) == 1):
            return (f"Check 2D vs 3D: you changed plan piece {h} (was x {b[0]}..{b[2]}, y {b[1]}..{b[3]}) but its 3D line(s) in "
                    "furnish.js didn't change: " + "; ".join(f"line {i}: {ls[-1].strip()[:160]}" for i, ls in lines[:4])
                    + (" (placed by the loop above it together with other pieces: take this one out of the loop into its own "
                       "item() line and leave the others where they are)" if loops else "")
                    + ". Give the 3D piece exactly the same move / resize (for this version only), or put the plan piece "
                      "back if it wasn't meant to change." + tail)
    # A 3D piece moved / resized: the plan outline it stands on must have changed too.
    ops = [o for o in ws.ops.get("furnish.js") or []
           if Counter(NUMBER.findall(o["old"])) != Counter(NUMBER.findall(o["new"]))
           and not (o["new"].startswith(o["old"]) or o["new"].endswith(o["old"]))  # not a pure addition
           and footprint(o["old"]) != footprint(o["new"])]  # height / look only: the plan outline is the footprint
    if (off_ := resized_off_plan(ws, f0, f1)):  # a resized 3D piece now past its outline or over its neighbour
        return off_ + tail
    in_window = lambda px, py: any(abs(px - wx) <= hw and abs(py - wy) <= 0.3 for wx, wy, hw in getattr(ws, "win_moved", []))
    only3d = bool(ops) and not ws.dxf_furni and three_d_only(ws, f0, f1)  # AC / curtain box / bulkhead / no outline: no 2D
    gone = [] if only3d else [(i, px, py, line) for i, px, py, line in placed_lines(ws, f0)
            if bare(line) not in now and not in_window(px, py) and any(len(seg.strip()) > 8 and seg.strip() in line for o in ops for seg in o["old"].splitlines())]
    if gone and plan_edits():
        src = ws.tmp / "plan-before.dxf"
        src.write_bytes(ws.orig.get(ws.cfg["dxf"]) or ws.read(ws.cfg["dxf"]))
        for i, px, py, line in gone:
            if any(b and b[0] - 0.15 <= px <= b[2] + 0.15 and b[1] - 0.15 <= py <= b[3] + 0.15 for b in ws.pieces.values()):
                continue  # its own outline changed in this edit; a big outline round it (an L-bench) isn't its footprint
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
                    inner = any(o_ and o_[0] - 0.01 <= min(xs) and max(xs) <= o_[2] + 0.01 and o_[1] - 0.01 <= min(ys)
                                and max(ys) <= o_[3] + 0.01 for o_ in ws.pieces.values())  # moved with a changed piece
                    if min(xs) - 0.15 <= px <= max(xs) + 0.15 and min(ys) - 0.15 <= py <= max(ys) + 0.15 \
                            and (max(xs) - min(xs)) * (max(ys) - min(ys)) >= 0.04 and not inner:
                        hits.append((d["handle"], [min(xs), min(ys), max(xs), max(ys)]))
            fp_ = footprint_at(L0_, i, line, ws.v)
            if hits and fp_ and _area(fp_) > 1e-4:  # the outline that is its footprint, else none: a 3D-only piece (J214)
                best_ = max(hits, key=lambda t: _iou(fp_, t[1]))
                hits = [best_] if _iou(fp_, best_[1]) >= 0.3 else []
            elif hits:  # a part drawn inside a bigger outline here (a medicine cabinet in its vanity) isn't the piece:
                # the same test as the part check below, so the two never name different outlines (e2e J221)
                hits = [t for t in hits if not any(t2 is not t and _area(t2[1]) > 2 * _area(t[1]) + 0.05 and t2[1][0] - 0.01 <= t[1][0]
                                                   and t[1][2] <= t2[1][2] + 0.01 and t2[1][1] - 0.01 <= t[1][1] and t[1][3] <= t2[1][3] + 0.01
                                                   for t2 in hits)] or hits
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
    if loop_ops and not ws.dxf_furni and not gone and not only3d and not getattr(ws, "loop_warned", False):
        ws.loop_warned = True  # advice, given once: a 3D-only change the model kept after it is saved (e2e J208)
        return ("Check 2D vs 3D: you moved or resized furniture in furnish.js but nothing on the plan (2furni). If the "
                "piece is drawn on the plan (furniture_near lists the outlines there), give its outline exactly the same "
                "change now with dxf_edit move_piece / resize_piece; things not drawn on the plan, and changes of height or "
                "look only (taller, lower, colour: the outline is the footprint), need nothing: keep your 3D edit as it is, "
                "you're done, reply to the user. If dxf_edit says there's no room that way, put the 3D back too and tell "
                "the user why: both views always show the same room." + tail)
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
    # ...unless it is a piece of its own: a furniture block (the armchair inside the reception group), or a part with a
    # name the user said (the flip desk drawn inside the coffee corner: e2e J216 r3)
    named_part = any(l_.lower() in message.lower() for l_ in re.findall(r'\.label\(\s*"([^"]{3,})"', f0))
    if not named_part and f0 != f1:  # or the 3D edit is inside a labelled part's block: the part was meant, in any language
        # ("خلي الدرج القلاب أعرض" never matched the English label "flip desk": e2e J216 r4)
        L1n = f1.splitlines()
        hit_ = {j for tag_, _, _, j0, j1 in difflib.SequenceMatcher(None, f0.splitlines(), L1n, autojunk=False).get_opcodes()
                if tag_ != "equal" for j in range(j0 + 1, j1 + 1)}
        named_part = any(i_ <= j <= block_end(L1n, i_) for i_, l_ in enumerate(L1n, 1) if re.search(r'\.label\(\s*"', l_) for j in hit_)
    if ws.pieces and not named_part:
        for h, b in list(ws.pieces.items())[:6]:
            if h in getattr(ws, "blocks", set()):
                continue
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
    hits = [c for cs in ws.clashes.values() for c in cs if not c.get("was")]  # was: an overlap it had before this edit
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
    for p in OWN:
        if p in ws.changed and (err := js_check(ws, p)):
            raise RuntimeError(f"the edit left {p} broken, so nothing was saved:\n{err}")
    if ws.plan_dirty or ws.cfg["tour"] in ws.changed:
        rebuild(ws)
    derived_from = ws.cfg["dxf"] if ws.cfg["dxf"] in ws.changed else None
    files = {}
    for path, (status, e, _) in resolve(ws.man).items():  # what stays live from before (conflicts kept for edit_ai_pull.py)
        if status in ("live", "replayed", "conflict"):
            files[path] = e
    for name in ws.changed:  # stored, committed and listed under the version's own file names (own())
        path = own(ws.v, name)
        prev = ws.res.get(path)
        dep = deployed(path)
        data = ws.files[name]
        e = {"sha": sha(data), "url": store(data, path), "base": sha(dep), "base_url": store(dep, path) if dep else None}
        pre = ws.orig.get(name)  # what the version showed before this edit: Undo's target (see undo())
        if pre is not None and pre != dep:
            e["pre_url"] = store(pre, path)
        if path.endswith((".js", ".json")) and name in ws.ops and path not in (ws.cfg["model"], ws.cfg["drawing"]):
            e["ops"] = (prev[1].get("ops") or [] if prev and prev[0] in ("live", "replayed") else []) + ws.ops[name]
        if path in (ws.cfg["model"], ws.cfg["drawing"]) and derived_from:
            e["derived"] = derived_from
        if e["sha"] == e["base"]:
            files.pop(path, None)  # back to what is deployed
        else:
            files[path] = e
    return write_rev(ws.v, files, summary, sorted(own(ws.v, p) for p in ws.changed),
                     {own(ws.v, p): ws.files[p] for p in ws.changed})


def write_rev(v, files, summary, changed, contents, undoes=None):
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{int(time.time() * 1000) % 1000:03d}"
    rev = f"{stamp}-{secrets.token_hex(3)}"
    prev = revisions(v)
    man = {"version": v, "rev": rev, "parent": prev[-1] if prev else None, "summary": summary[:300],
           "changed": changed, "files": files, "at": int(time.time())}
    if undoes:  # an Undo: the revision it took back (undo_target steps past both)
        man["undoes"] = f"{LIVE}/{v}/rev-{undoes}.json"
    put(f"{LIVE}/{v}/rev-{rev}.json", json.dumps(man).encode(), "application/json")
    man["sync"] = git_sync(v, contents, summary)
    return man


def unapply(path, edited, pre, dep):
    """An edit (pre -> edited) taken back off the deployed file: `pre` when git has nothing newer than the edit, later
    commits kept when they merge, `pre` as it was when they don't."""
    if dep in (edited, pre) or not path.endswith((".js", ".json")):
        return pre
    try:
        t = merge3(edited.decode(), pre.decode(), dep.decode())
    except Exception as err:
        print(f"[edit-ai] undo merge {path}: {err}", flush=True)
        t = None
    return t.encode() if t is not None else pre


def is_undo(man):
    """Is this revision an Undo? Its parent is then the revision it took back (`undoes`; older ones: by the summary)."""
    return bool(man) and (bool(man.get("undoes")) or str(man.get("summary", "")).startswith("Undo: "))


def undo_target(man):
    """The change the next Undo takes back: the latest revision, past every Undo and the change it took back (an Undo
    is a stack: change A, change B, Undo, Undo -> before A; it used to undo the Undo, i.e. re-apply B: e2e 28 Oct 2026,
    J244 / J277 / J286). None when there's nothing left to undo."""
    for _ in range(200):
        if not man or not man.get("changed"):
            return None
        if not is_undo(man):
            return man
        undone = man.get("undoes") or man.get("parent")
        undone = json.loads(get(undone)) if undone else None
        man = json.loads(get(undone["parent"])) if undone and undone.get("parent") else None
    return None


def undo(req):
    """Put the version back as it was before its last Edit AI change not undone yet (a new revision, so it can be
    redone by hand). Undo again takes back the change before that, and so on."""
    v = plan_version(req.get("version"))
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    head = latest(v)
    cur = undo_target(head)
    if not cur:
        raise ValueError("there is no Edit AI change to undo here")
    if set(cur["changed"]) & set(OWN):
        raise ValueError("that change was made before each version got its own files (26 Oct 2026), so it can't be "
                         "undone from here; ask for the opposite change instead")
    before = json.loads(get(cur["parent"])) if cur.get("parent") else None
    res_before = resolve(before)
    files = {p: e for p, (st, e, _) in resolve(head).items() if st in ("live", "replayed", "conflict")}
    contents, shas = {}, {}  # shas: what the page must show after the reload, so the client can tell a no-op Undo
    for path in cur["changed"]:
        e = cur["files"].get(path)
        dep = deployed(path)  # what the page loads now: the reference for keeping an override
        head = fresh(path)  # git main now: what "later commits" really are (the bundle can be a lagging build of an
        # earlier edit; taking the edit off it brought that earlier, undone edit back, 27 Oct 2026: white doors)
        data = None
        if path in res_before and res_before[path][0] in ("live", "replayed"):
            data = live_content(path, res_before[path])
            if e and sha(data) == e["sha"]:
                data = None  # the parent replayed onto a deployed file that already has this edit: that's no undo
        if data is None and e and (e.get("pre_url") or e.get("base_url")):
            # The file the edit started from. Never plain deployed(): once git_sync has pushed the edit, the deployed
            # file IS the edit, and "restoring" it changes nothing (26 Oct: 0dfc896, an empty Undo of the black armchair).
            data = unapply(path, get(e["url"]), get(e.get("pre_url") or e["base_url"]), head)
        if data is None:
            data = head
        if sha(data) == sha(dep):
            files.pop(path, None)
        else:
            files[path] = {"sha": sha(data), "url": store(data, path), "base": sha(dep), "base_url": store(dep, path) if dep else None}
        contents[path] = data
        shas[path] = {"from": e and e["sha"], "to": sha(data), "live": path in files}
    if all(cur["files"].get(p) and sha(d) == cur["files"][p]["sha"] for p, d in contents.items()):
        raise ValueError("Undo found nothing to go back to: every file would stay exactly as the last edit left it")
    man = write_rev(v, files, f"Undo: {cur.get('summary', '')}", sorted(contents), contents, undoes=cur["rev"])
    return {"rev": man["rev"], "changed": sorted(contents), "sync": man.get("sync"), "shas": shas,
            "summary": man["summary"], "more": undo_target(man) is not None}


def reset(req):
    """Drop every live Edit AI override for a version: it shows exactly what is deployed (a new, empty revision).

    Live overrides are the user's edits that may not be in git yet (on Vercel without EDIT_AI_GITHUB_TOKEN they are
    in Blob only), so this refuses while any remain unless the caller names the revision it is throwing away
    ({"discard": "<rev>"}). Bring them into git first: python3 edit_ai_pull.py <version>, commit, push."""
    v = plan_version(req.get("version"))
    if v not in VERSIONS:
        raise ValueError(f"unknown version {v!r}")
    cur = latest(v)
    left = sorted(p for p, (st, _, _) in resolve(cur).items() if st != "synced")
    if left and req.get("discard") != cur["rev"]:
        raise ValueError(f"refusing to reset {v}: revision {cur['rev']} still has live edits not in the deployed files "
                         f"({', '.join(left)}). Run `python3 edit_ai_pull.py {v}` and commit them first, or pass "
                         f"discard={cur['rev']!r} to throw them away.")
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


def git_sync_status():
    """What git_sync would do now, for GET /api/edit-ai/status. No token value, no GitHub call."""
    if os.environ.get("EDIT_AI_GIT_SYNC", "1") == "0":
        return "off"
    if ON_VERCEL or BLOB:
        if not os.environ.get("EDIT_AI_GITHUB_TOKEN"):
            return "off (no EDIT_AI_GITHUB_TOKEN): live in Blob only"
        return "on: GitHub API -> %s@%s" % (os.environ.get("EDIT_AI_GITHUB_REPO", "karimtaamer/karim-home-3d"),
                                             os.environ.get("EDIT_AI_GITHUB_BRANCH", "main"))
    return "on: local git commit + push"


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
    if new_tree == tree:  # the files are already in git like this: no empty commit (0dfc896 was one, an Undo that undid nothing)
        return "nothing to commit: git already has these files"
    commit = gh("POST", "/git/commits", {"message": msg, "tree": new_tree, "parents": [head]})["sha"]
    gh("PATCH", f"/git/refs/heads/{branch}", {"sha": commit})
    for path, data in contents.items():  # what main now holds, for the next edit's fresh() reads
        _fresh[path] = (time.time(), data)
    return f"committed {commit[:7]}"


# --- HTTP ---------------------------------------------------------------------------------------------------------------
_hits = defaultdict(deque)


def limited(ip, rate=None):
    q, now = _hits[ip], time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= (rate or RATE):
        return True
    q.append(now)
    return False


class Handler(photogen.Handler):
    def stream(self, run):
        """NDJSON while an edit runs: {"phase": text} lines, then {"done": result} or {"error": message[, "code"]}.
        Where the platform buffers the body the lines all arrive at the end, and the page reads them the same way."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        gone = []

        def line(obj):  # a closed tab stops the writing, not the edit: it saves (or not) on its own merits (e2e J314 / J315 r3)
            if gone:
                return
            try:
                self.wfile.write((json.dumps(obj) + "\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                gone.append(True)
                print("[edit-ai] chat: the page went away; the edit carries on", flush=True)
        try:
            line({"done": run(lambda text: line({"phase": text}))})
        except PermissionError as e:
            line({"error": str(e), "code": "no-key"})
        except Exception as e:
            print(f"[edit-ai] chat: {type(e).__name__}: {e}", flush=True)
            line({"error": str(e)})

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
                return self.reply(200, {"ready": ready(), "model": live_model(MODEL), "api": "anthropic" if is_claude(live_model(MODEL)) else "responses" if uses_responses(live_model(MODEL)) else "chat",
                                        "models": sorted(ALLOWED_MODELS), "planEdits": plan_edits(), "gitSync": git_sync_status(),
                                        "gates": {"precheck": PRECHECK_MODEL, "review": REVIEW_MODEL, "pass": REVIEW_PASS} if gates_on() else None})
            if act == "patches":
                return self.reply(200, patches(q.get("version", ["main"])[0]))
        except Exception as e:
            print(f"[edit-ai] {act}: {e}", flush=True)
            return self.reply(400 if isinstance(e, ValueError) else 502, {"error": str(e)})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        act, _ = self.edit_action()  # (Accept / Undo / reset hold their version's lock: see version_lock)
        if not act:
            return super().do_POST()
        routes = {"chat": chat, "precheck": precheck, "undo": undo, "reset": reset,
                  "transform": lambda r: __import__("move_tool").transform(r)}
        if act not in routes:
            return self.reply(404, {"error": "not found"})
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        if act == "chat" and limited(ip):
            return self.reply(429, {"error": f"That's {RATE} edits this hour from here; try again later."})
        if act == "transform" and limited("move:" + ip, 120):
            return self.reply(429, {"error": "That's a lot of moves this hour from here; try again later."})
        if act == "precheck" and limited("check:" + ip, 120):
            return self.reply(200, {"skipped": True})  # the check only advises: past its limit, edits go straight on
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 16_000_000:
                return self.reply(413, {"error": "too much to send at once; fewer or smaller pictures"})
            req = json.loads(self.rfile.read(n))
            if act == "chat" and req.get("stream"):
                return self.stream(lambda emit: chat(req, emit))
            if act in ("undo", "reset", "transform"):
                with version_lock(req.get("version")):
                    out = routes[act](req)
                return self.reply(200, out)
            self.reply(200, routes[act](req))
        except PermissionError as e:
            self.reply(503, {"error": str(e), "code": "no-key"})
        except Exception as e:
            print(f"[edit-ai] {act}: {type(e).__name__}: {e}", flush=True)
            self.reply(400 if isinstance(e, (ValueError, KeyError)) else 502, {"error": str(e)})


if __name__ == "__main__":
    port = next((int(a) for a in sys.argv[1:] if a.isdigit()), 8000)
    print(f"Serving http://127.0.0.1:{port}  ·  Edit AI: {live_model(EASY_MODEL)} / {live_model(COMPLEX_MODEL)}"
          f"{f', check {PRECHECK_MODEL}, review {REVIEW_MODEL}' if gates_on() else ''}"
          f"{'' if ready() else '  (no ANTHROPIC_API_KEY or EDIT_AI_OPENAI_API_KEY: editing is off)'}", flush=True)
    ThreadingHTTPServer.request_queue_size = 128  # the page asks for ~60 textures / models at once; the default 5 resets some
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
