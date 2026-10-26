"""Compare two piece lists (tests/move_e2e list output, one per furnish.js) item by item: same pieces, same plan boxes.
Proves Move and Resize's furnish.js instrumentation (MOVED table, labelled niches) changes nothing on screen.

    python3 tests/move_same_scene.py before.json after.json
"""
import json, sys

a, b = (json.load(open(p)) for p in sys.argv[1:3])
key = lambda p: (round(p["x"], 4), round(p["y"], 4), str(p["facing"]))
A = {key(p): p for p in a if p["kind"] == "item"}
B = {key(p): p for p in b if p["kind"] == "item"}
bad = [k for k in A.keys() | B.keys() if k not in A or k not in B or
       any(abs(u - v) > 1e-4 for u, v in zip(A[k]["box"] + [A[k]["low"], A[k]["high"]], B[k]["box"] + [B[k]["low"], B[k]["high"]]))]
print(f"{len(A)} / {len(B)} items; {len(bad)} differ")
for k in bad[:20]:
    print("  ", k, A.get(k, {}).get("box"), B.get(k, {}).get("box"))
sys.exit(1 if bad else 0)
