"""Run Main's furnish-<version>.js in node against a box-recording three.js stand-in (same idea as check_furnish.py)
and return every box: (material, x0, x1, y0, y1, h0, h1, label) in plan metres (model.js frame)."""
import json, re, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def boxes(repo, version="kareems-changes"):
    sys.path.insert(0, str(repo))
    import check_furnish as cf
    run = cf.RUN.replace(
        'const material = name => ({ name, transparent: false, opacity: 1, userData: {}, color: { setRGB() {} },',
        'const PX = new Proxy(function(){}, {get:(t,k)=>k===Symbol.toPrimitive?()=>0:k==="then"?undefined:PX, set:()=>true, apply:()=>PX, construct:()=>PX});\n'
        'const material = name => ({ name, transparent: false, opacity: 1, userData: {}, color: PX, emissive: PX, map: PX,')
    src = (Path(repo) / f"furnish-{version}.js").read_text()
    src = re.sub(r'from "three[^"]*"', 'from "./three.mjs"', src)
    with tempfile.TemporaryDirectory() as d:
        Path(d, "three.mjs").write_text(cf.MOCK)
        Path(d, "furnish.mjs").write_text(src)
        Path(d, "run.mjs").write_text(run)
        r = subprocess.run(["node", str(Path(d, "run.mjs")), str(Path(repo) / f"model-{version}.js"), version],
                           capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr[-2000:])
    return [b for b in json.loads(r.stdout) if None not in b]

if __name__ == "__main__":
    B = boxes(sys.argv[1]); print(len(B))
    json.dump(B, open(sys.argv[2], "w"))
