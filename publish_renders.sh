#!/bin/sh
# Copy the photo spots' renders to the site's Vercel Blob store, so the live site shows them and Generate Photo
# Spot on Vercel can send them as references (vercel.json points /renders/* at the store): each render, its
# reference copy at photogen.py's REF_PX and the material board. Run again after adding a render or swatch;
# files already online at the same size are skipped. Needs the Vercel CLI, logged in and linked (vercel link).
set -e
cd "$(dirname "$0")"
BASE=https://ezauif7vtmi92gwt.public.blob.vercel-storage.com
# The store's read-write token, from .env.local (vercel env pull writes it there; git and Vercel ignore the file).
token() { sed -n 's/^BLOB_READ_WRITE_TOKEN=//p' .env.local 2>/dev/null | tr -d "\"'"; }
[ -n "$(token)" ] || vercel env pull .env.local --environment=development --yes >/dev/null
TOKEN=$(token)
[ -n "$TOKEN" ] || { echo "No BLOB_READ_WRITE_TOKEN in .env.local"; exit 1; }
PX=$(sed -n 's/^REF_PX = \([0-9]*\).*/\1/p' photogen.py)
fails=0

online() { curl -sI "$BASE/$1" | tr -d '\r' | sed -n 's/^content-length: //Ip'; }
up() {
  # The CLI can exit non-zero after a good upload, so the store is checked instead.
  size=$(wc -c < "$1" | tr -d ' ')
  if [ "$(online "$1")" = "$size" ]; then echo "already online $1"; return; fi
  vercel blob put "$1" --access public --pathname "$1" --allow-overwrite --no-multipart --rw-token "$TOKEN" >/dev/null 2>&1 || true
  if [ "$(online "$1")" = "$size" ]; then echo "uploaded $1"; else echo "FAILED $1"; fails=$((fails + 1)); fi
}

mkdir -p renders/drafts/refs
# Every photo a spots file lists (designer renders and approved generated spots), once each.
for f in $(python3 -c 'import glob, json; print("\n".join(sorted({s["photo"] for p in glob.glob("spots*.json") for s in (lambda d: d if isinstance(d, list) else d.get("spots", []))(json.load(open(p)))})))'); do
  [ -f "$f" ] || continue
  ref="renders/drafts/refs/$(basename "${f%.*}")-$PX.jpg"
  [ -f "$ref" ] || sips -Z "$PX" -s format jpeg "$f" --out "$ref" >/dev/null
  up "$f"
  up "$ref"
done
board=$(python3 -c 'import photogen; b = photogen.board(); print(b.relative_to(photogen.ROOT) if b else "")')
[ -n "$board" ] && up "$board"
echo "done, $fails failed"
