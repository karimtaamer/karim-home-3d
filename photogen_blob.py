"""Vercel Blob for photogen.py on Vercel, where the files it keeps in renders/ can't be written.

The same paths as on disk (renders/drafts/..., renders/ai-...png, renders/refs/...) go to the public Blob store
whose token is in BLOB_READ_WRITE_TOKEN; vercel.json rewrites /renders/* to the store, so the page's links work
unchanged. Plain urllib on the Blob HTTP API, as @vercel/blob uses it, so the function needs no packages.
"""
import json, os, urllib.parse, urllib.request

API = "https://vercel.com/api/blob"
VERSION = "13"  # @vercel/blob 2.8's BLOB_API_VERSION


def token():
    return os.environ.get("BLOB_READ_WRITE_TOKEN")


def base():
    # vercel_blob_rw_<storeId>_<secret>: the store id names the public host.
    return f"https://{token().split('_')[3].lower()}.public.blob.vercel-storage.com/"


def call(query, method="GET", body=None, headers=None):
    req = urllib.request.Request(f"{API}/?{urllib.parse.urlencode(query)}", data=body, method=method, headers={
        "authorization": f"Bearer {token()}", "x-api-version": VERSION, **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)


def put(path, data, mime, overwrite=False):
    """Store data at path (renders/...) and return its public URL."""
    return call({"pathname": path}, "PUT", data, {
        "x-vercel-blob-access": "public", "x-content-type": mime, "x-add-random-suffix": "0",
        "x-allow-overwrite": "1" if overwrite else "0", "x-content-length": str(len(data)),
        # Drafts and spots are written once under new names, so they can be cached for good.
        "x-cache-control-max-age": "31536000"})["url"]


def get(path):
    with urllib.request.urlopen(base() + urllib.parse.quote(path), timeout=120) as res:
        return res.read()


def names(prefix):
    """Every stored path under prefix."""
    out, cursor = [], None
    while True:
        page = call({"prefix": prefix, "limit": "1000", **({"cursor": cursor} if cursor else {})})
        out += [b["pathname"] for b in page["blobs"]]
        cursor = page.get("cursor")
        if not page.get("hasMore"):
            return out
