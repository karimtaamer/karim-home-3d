#!/usr/bin/env python3
"""Site measurements (New As-built's sitemeasure.js): what Karim's tape said for each wall piece, shared by the phone
on site and the laptop.

    GET  /api/measurements?version=new-asbuilt              -> {"version", "entries": {id: {value, note, updated, ...}}}
    POST /api/measurements?version=new-asbuilt {"entries"}  -> merged, saved, the same answer

Last write wins per piece, by its `updated` (ms, the device's clock); a cleared piece is kept with value null so the
clear reaches the other device. Stored in Vercel Blob (photogen_blob, BLOB_READ_WRITE_TOKEN) as revisions written once
under their own names, site-measurements/<version>/<ms>-<hash>.json, so no read is ever served stale from the Blob CDN;
a read merges the newest few, so two saves at once both survive. Without a token (locally) the same files go on disk.

    python3 site_measurements.py [port]     # serves the site with this API (http://127.0.0.1:8000)
"""
import hashlib, json, os, sys, time, urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import photogen_blob

ROOT = Path(__file__).resolve().parent
PREFIX = "site-measurements"
VERSIONS = {"new-asbuilt"}  # the plan versions with the tool
READ = 5  # revisions merged on a read
KEEP = 30  # revisions kept; older ones are deleted after a save
MAX_BODY = 1_000_000
MAX_ENTRIES = 5000


def blob():
    return bool(photogen_blob.token())


def names(v):
    """The version's revisions, oldest first (their names start with the time)."""
    pre = f"{PREFIX}/{v}/"
    if blob():
        out = photogen_blob.names(pre)
    else:
        d = ROOT / pre
        out = [f"{pre}{p.name}" for p in d.glob("*.json")] if d.is_dir() else []
    return sorted(n for n in out if n.endswith(".json"))


def read(path):
    return json.loads(photogen_blob.get(path) if blob() else (ROOT / path).read_bytes())


def write(path, data):
    if blob():
        photogen_blob.put(path, data, "application/json")
    else:
        (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / path).write_bytes(data)


def drop(paths):
    if blob():
        photogen_blob.delete(paths)
    else:
        for p in paths:
            (ROOT / p).unlink(missing_ok=True)


def version(v):
    if v not in VERSIONS:
        raise ValueError(f"no site measurements for version {v!r}")
    return v


def clean(entries):
    """The entries a request may store: {id: {value: cm | None, note, updated, room?, kind?, drawn?}}."""
    if not isinstance(entries, dict) or len(entries) > MAX_ENTRIES:
        raise ValueError("entries must be an object of at most %d pieces" % MAX_ENTRIES)
    out = {}
    for k, e in entries.items():
        if not isinstance(k, str) or not 0 < len(k) <= 200 or not isinstance(e, dict):
            raise ValueError(f"bad piece {k!r}")
        val, upd = e.get("value"), e.get("updated")
        if val is not None and (isinstance(val, bool) or not isinstance(val, (int, float)) or not 0 < val < 5000):
            raise ValueError(f"{k}: value must be cm (0-5000) or null")
        if isinstance(upd, bool) or not isinstance(upd, (int, float)) or upd <= 0:
            raise ValueError(f"{k}: updated must be a time in ms")
        c = {"value": val, "note": str(e.get("note") or "")[:500], "updated": upd}
        for f in ("room", "kind"):
            if isinstance(e.get(f), str):
                c[f] = e[f][:80]
        if isinstance(e.get("drawn"), (int, float)) and not isinstance(e.get("drawn"), bool):
            c["drawn"] = e["drawn"]
        out[k] = c
    return out


def merge(a, b):
    """b's pieces over a's where b's is newer (last write wins per piece)."""
    out = dict(a)
    for k, e in b.items():
        if k not in out or e.get("updated", 0) > out[k].get("updated", 0):
            out[k] = e
    return out


def load(v, have=None):
    entries = {}
    for n in (names(v) if have is None else have)[-READ:]:
        try:
            entries = merge(entries, read(n).get("entries", {}))
        except Exception as e:  # noqa: BLE001 - one unreadable revision doesn't lose the rest
            print(f"[measurements] {n}: {e}", flush=True)
    return {"version": v, "entries": entries}


def save(v, incoming):
    incoming = clean(incoming)
    have = names(v)
    doc = load(v, have)
    doc["entries"] = merge(doc["entries"], incoming)
    # Names sort by time: strictly after the newest, even within the same ms.
    last = int(have[-1].rsplit("/", 1)[1].split("-")[0]) if have else 0
    doc["saved"] = max(int(time.time() * 1000), last + 1)
    data = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode()
    write(f"{PREFIX}/{v}/{doc['saved']:013d}-{hashlib.sha256(data).hexdigest()[:10]}.json", data)
    old = names(v)[:-KEEP]
    if old:
        try:
            drop(old)
        except Exception as e:  # noqa: BLE001 - pruning can wait for the next save
            print(f"[measurements] prune: {e}", flush=True)
    return doc


class Handler(SimpleHTTPRequestHandler):
    """/api/measurements on Vercel (api/measurements.py); locally it also serves the site."""

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path.rstrip("/") != "/api/measurements":
            return None
        return urllib.parse.parse_qs(url.query).get("version", [""])[0]

    def do_GET(self):
        v = self.api()
        if v is None:
            return super().do_GET()
        try:
            self.reply(200, load(version(v)))
        except ValueError as e:
            self.reply(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            print(f"[measurements] GET: {e}", flush=True)
            self.reply(502, {"error": str(e)})

    def do_POST(self):
        v = self.api()
        if v is None:
            return self.reply(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self.reply(413, {"error": "too much at once"})
            self.reply(200, save(version(v), json.loads(self.rfile.read(n) or b"{}").get("entries", {})))
        except ValueError as e:  # bad JSON included
            self.reply(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            print(f"[measurements] POST: {e}", flush=True)
            self.reply(502, {"error": str(e)})


if __name__ == "__main__":
    port = next((int(a) for a in sys.argv[1:] if a.isdigit()), 8000)
    print(f"Serving http://127.0.0.1:{port}  ·  site measurements in {'Vercel Blob' if blob() else ROOT / PREFIX}", flush=True)
    ThreadingHTTPServer.request_queue_size = 128
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
