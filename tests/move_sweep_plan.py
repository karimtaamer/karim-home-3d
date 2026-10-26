"""Plan boxes for tests/move_sweep.mjs: the extent of each handle (a block member's "INSERT/ENTITY" too), found with
edit_ai_dxf.py query round a box. Run with the DWG python (ezdxf).

    python tests/move_sweep_plan.py file.dxf x0,y0,x1,y1 H1 [H2 ...]   -> {"H1": [x0, y0, x1, y1] | null, ...}
    python tests/move_sweep_plan.py file.dxf x0,y0,x1,y1               -> [[handle, box], ...] every 2furni entity there
"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "190.4049651574427,-121.6132067325871"


def ebox(d):
    if d.get("bbox"):
        return d["bbox"]
    if d.get("points"):
        xs, ys = [p[0] for p in d["points"]], [p[1] for p in d["points"]]
        return [min(xs), min(ys), max(xs), max(ys)]
    if d.get("centre") and d.get("radius"):
        (cx, cy), r = d["centre"], d["radius"]
        return [cx - r, cy - r, cx + r, cy + r]
    return None


dxf, b = sys.argv[1], [float(v) for v in sys.argv[2].split(",")]
out = subprocess.run([sys.executable, str(ROOT / "edit_ai_dxf.py"), "query", dxf, f"--origin={ORIGIN}",
                      f"--bbox={b[0] - 0.6},{b[1] - 0.6},{b[2] + 0.6},{b[3] + 0.6}", "--layers=2furni,2 furni", "--limit", "3000",
                      "--blocks"], capture_output=True, text=True, timeout=80).stdout
ents = json.JSONDecoder().raw_decode(out)[0]["entities"]
if len(sys.argv) > 3:
    print(json.dumps({h: next((ebox(d) for d in ents if d["handle"] == h), None) for h in sys.argv[3:]}))
else:
    print(json.dumps([[d["handle"], ebox(d)] for d in ents if ebox(d)]))
