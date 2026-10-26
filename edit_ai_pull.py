#!/usr/bin/env python3
"""Bring the live Edit AI edits (Vercel Blob) into this working tree, so a git push can't hide or wipe them.

    python3 edit_ai_pull.py [version ...]     # default: every version; then review `git diff`, commit, push

On Vercel without EDIT_AI_GITHUB_TOKEN an Edit AI change lives in Blob only. Run this BEFORE committing anything that
touches a version's furnish-<v>.js / materials-<v>.js / tour / plan, and never POST /api/edit-ai/reset to "see" a push: once
the edits are in git the override is "synced" and drops out by itself. Needs no token: it reads the latest revision
through the public API and store. Each file is three-way merged (the file the edit started from -> the live file, laid
onto the file here); a clash is left as git conflict markers to resolve by hand.
"""
import json, subprocess, sys, tempfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = "https://karim-home-3d.vercel.app"
STORE = next(r["destination"].split("/edit-ai-live/")[0] for r in json.loads((ROOT / "vercel.json").read_text())["rewrites"]
             if r["source"].startswith("/edit-ai-live"))
# Main loads kareems-changes (2026-10-25), "Karim's version" its own karims-version (26 Oct); Bigger / Shifted Bedroom are retired.
VERSIONS = ["kareems-changes", "karims-version", "naghams-changes", "as-built"]
OWN = ["furnish.js", "materials.js"]
# The pre-split shared furnish.js overrides already in git (edit_ai.py PULLED; kept here so this needs no Edit AI imports).
PULLED = {"kareems-changes": {"9924d0735c024e622ba3", "c3d4ac30615a61048d3a"}, "naghams-changes": {"99b962fa671a0b66c38a"}}


def own(v, path):
    """The version's own file for furnish.js / materials.js (edit_ai.py own())."""
    return path.replace(".js", f"-{v}.js") if path in OWN else path


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def pull(v):
    rev = json.loads(fetch(f"{SITE}/api/edit-ai/patches?version={v}"))["rev"]
    if not rev:
        return print(f"{v}: no Edit AI revisions")
    man = json.loads(fetch(f"{STORE}/edit-ai-live/{v}/rev-{rev}.json"))
    if not man["files"]:
        return print(f"{v}: {rev} has no live edits")
    for path, e in man["files"].items():
        if e["sha"] in PULLED.get(v, ()):
            print(f"{v}: {path} {e['sha']} was pulled with the split")
            continue
        path = own(v, path)  # stored as furnish.js / materials.js before each version got its own (26 Oct 2026)
        here = ROOT / path
        live = fetch(f"{STORE}/{e['url']}")
        cur = here.read_bytes() if here.exists() else b""
        if cur == live:
            print(f"{v}: {path} already has the live edit")
            continue
        committed = subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True).stdout
        if committed == live:  # Edit AI's git sync already committed it: what differs here is newer local work, keep it
            print(f"{v}: {path} live edit already committed; local changes kept")
            continue
        base = fetch(f"{STORE}/{e['base_url']}") if e.get("base_url") else b""
        if cur == base or not cur:
            here.write_bytes(live)
            print(f"{v}: {path} <- live {e['sha']}")
            continue
        if not path.endswith((".js", ".json", ".md")):
            Path(f"{here}.live").write_bytes(live)
            print(f"{v}: {path} changed both here and live; live copy at {path}.live (not merged)")
            continue
        with tempfile.TemporaryDirectory() as t:
            b, l = Path(t, "base"), Path(t, "live")
            b.write_bytes(base); l.write_bytes(live)
            code = subprocess.run(["git", "merge-file", "-L", "here", "-L", "edit-ai base", "-L", f"edit-ai live {rev}",
                                   str(here), str(b), str(l)]).returncode
        print(f"{v}: {path} merged" + (f" with {code} conflict(s): resolve the <<<<<<< markers" if code else ""))


if __name__ == "__main__":
    for v in sys.argv[1:] or VERSIONS:
        pull(v)
