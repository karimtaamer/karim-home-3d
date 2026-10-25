#!/usr/bin/env python3
"""Build one plan version's model and drawing with the flags in build_flags.json (the same ones Edit AI uses),
then check design-locks.json.

    ~/.dwg-tools/bin/python build_version.py kareems-changes
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    cfgs = {k: v for k, v in json.loads((ROOT / "build_flags.json").read_text()).items() if not k.startswith("_")}
    if len(sys.argv) != 2 or sys.argv[1] not in cfgs:
        sys.exit(f"usage: build_version.py {{{','.join(cfgs)}}}")
    c = cfgs[sys.argv[1]]
    py = sys.executable
    subprocess.run([py, "build_geometry.py", c["dxf"], "--out", c["model"], "--tour", c["tour"], *c["flags"]], cwd=ROOT, check=True)
    subprocess.run([py, "build_drawing.py", c["dxf"], "--model", c["model"], "--out", c["drawing"]], cwd=ROOT, check=True)
    return subprocess.run([py, "check_locks.py"], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
