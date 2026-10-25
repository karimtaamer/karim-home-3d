#!/usr/bin/env python3
"""Bring the live Edit AI edits (Vercel Blob) into this working tree, so a git push can't hide or wipe them.

    python3 edit_ai_pull.py [version ...]     # default: every version; then review `git diff`, commit, push

On Vercel without EDIT_AI_GITHUB_TOKEN an Edit AI change lives in Blob only. Run this BEFORE committing anything that
touches furnish.js / materials.js / a tour / a plan version, and never POST /api/edit-ai/reset to "see" a push: once
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
VERSIONS = ["main", "bigger-bedroom", "shifted-bedroom", "naghams-changes", "kareems-changes", "as-built"]


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
        here = ROOT / path
        live = fetch(f"{STORE}/{e['url']}")
        cur = here.read_bytes() if here.exists() else b""
        if cur == live:
            print(f"{v}: {path} already has the live edit")
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
