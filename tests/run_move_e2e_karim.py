"""Run every Move and Resize e2e case (tests/move_e2e_karim.mjs), two per node process, each capped at 178 s, and print
one summary. Local sandbox only (see README §9):  python3 tests/run_move_e2e_karim.py [case-regex]
MOVE_E2E_BASE: the sandbox server (default http://127.0.0.1:8853)."""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = os.environ.get("MOVE_E2E_BASE", "http://127.0.0.1:8853")
src = (HERE / "move_e2e_karim.mjs").read_text()
names = re.findall(r'^  \["([^"]+)",', src, re.M) + re.findall(r'^await run(?:Plan|Group)\("([^"]+)"', src, re.M)
names = ["2D accept-required"] + names
only = sys.argv[1] if len(sys.argv) > 1 else ""
names = [n for n in names if re.search(only, n)]
out = []
for i in range(0, len(names), 2):
    pair = names[i:i + 2]
    rx = "|".join("^" + re.escape(n) + "$" for n in pair)
    f = os.path.join(tempfile.gettempdir(), f"move-e2e-karim-{i:02d}.json")
    if os.path.exists(f): os.remove(f)
    p = subprocess.run(["timeout", "178", "node", str(HERE / "move_e2e_karim.mjs"), BASE, f, rx], capture_output=True, text=True)
    res = json.load(open(f)) if os.path.exists(f) else []
    for n in pair:
        rs = [r for r in res if r["case"] == n]
        bad = [r for r in rs if not r["ok"]]
        line = f"{'PASS' if rs and not bad else 'FAIL'} {n} ({len(rs) - len(bad)}/{len(rs)})" + ("" if rs else " - no result (timed out at 178 s)")
        for r in bad: line += f"\n     ✗ {r['name']}: {str(r['info'])[:300]}"
        print(line, flush=True)
        out.append({"case": n, "checks": len(rs), "failed": len(bad), "bad": bad})
print(f"\n{sum(1 for o in out if o['checks'] and not o['failed'])}/{len(out)} cases pass, {sum(o['checks'] for o in out)} checks")
