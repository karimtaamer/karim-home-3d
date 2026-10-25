#!/usr/bin/env python3
"""suite_merge: BASE plan everywhere except the master suite, which comes from SUITE.

Run with the DWG venv: ~/.dwg-tools/bin/python suite_merge.py BASE.dxf SUITE.dxf OUT.dxf [--dry]
  e.g. after a shared-room edit in dwg/kareems-changes.dxf: BASE = dwg/kareems-changes.dxf, SUITE = OUT = dwg/naghams-changes.dxf.
       suite_merge.py --check dwg/*.dxf   lists entities that differ between the files outside the suite
                                              (skips dwg/as-built*.dxf, the survey of the flat as it stands).

Inside the suite zone (DWG x 190.6 to 196.78, y -117.25 to -112.15) SUITE's entities replace BASE's. Entities
touching the zone edge that differ between the two files (wall faces running out of the suite) are swapped too
and listed. --dry only lists them. Blocks with the same name are kept from BASE (check they match).
"""
import os
import sys
from collections import Counter
from ezdxf import recover, xref, bbox as ebbox

ZONE = (190.6, -117.25, 196.78, -112.15)


def sig(e):
    """Geometry signature for matching entities between files (3 mm)."""
    t, d = e.dxftype(), e.dxf
    try:
        if t == 'LINE':
            g = tuple(round(v, 3) for v in (d.start.x, d.start.y, d.end.x, d.end.y))
        elif t == 'LWPOLYLINE':
            g = tuple(round(v, 3) for p in e.get_points('xy') for v in p)
        elif t in ('ARC', 'CIRCLE'):
            g = (round(d.center.x, 3), round(d.center.y, 3), round(d.radius, 3))
        elif t == 'INSERT':
            g = (d.name, round(d.insert.x, 3), round(d.insert.y, 3), round(d.get('rotation', 0), 2))
        elif t in ('TEXT', 'MTEXT'):
            g = (d.get('text', ''), round(d.insert.x, 2), round(d.insert.y, 2))
        else:
            g = ()
    except Exception:
        g = ()
    return t, d.layer, g


def box(e):
    if e.dxftype() == 'INSERT' and e.dxf.layer == '3door':  # dynamic door blocks hold every state: use the insert point
        p = e.dxf.insert
        return p.x, p.y, p.x, p.y
    try:
        b = ebbox.extents([e])
        return (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y) if b.has_data else None
    except Exception:
        return None


def inside(b):
    return b and b[0] >= ZONE[0] and b[1] >= ZONE[1] and b[2] <= ZONE[2] and b[3] <= ZONE[3]


def touches(b):
    return b and not (b[2] < ZONE[0] or b[0] > ZONE[2] or b[3] < ZONE[1] or b[1] > ZONE[3]) \
        and max(b[2] - b[0], b[3] - b[1]) < 30  # skip door-block clutter hundreds of metres long


def outside(doc):
    """Signatures of the entities clear of the suite zone and its edge."""
    return Counter(sig(e) for e in doc.modelspace() if not inside(b := box(e)) and not touches(b))


def check(paths):
    # The as-built survey (dwg/as-built*.dxf) is the flat as it stands, not a design version: it isn't compared.
    paths = [p for p in paths if not os.path.basename(p).startswith('as-built')]
    ref = outside(recover.readfile(paths[0])[0])
    bad = 0
    for p in paths[1:]:
        o = outside(recover.readfile(p)[0])
        for k, n in sorted(((ref - o) + (o - ref)).items(), key=str):
            print(f'  {p}: {k[0]} {k[1]} {k[2]} x{n} ({"missing" if ref[k] > o[k] else "extra"} vs {paths[0]})')
            bad += 1
    print('outside the suite:', 'identical' if not bad else f'{bad} differences')
    return 1 if bad else 0


def main():
    if sys.argv[1] == '--check':
        sys.exit(check(sys.argv[2:]))
    base_p, suite_p, out = sys.argv[1:4]
    t, _ = recover.readfile(base_p)
    s, _ = recover.readfile(suite_p)
    T, S = Counter(sig(e) for e in t.modelspace()), Counter(sig(e) for e in s.modelspace())
    drop, take = [], set()
    for doc, other, mine, name in ((t, S, drop, 'base'), (s, T, take, 'suite')):
        for e in doc.modelspace():
            b = box(e)
            edge = not inside(b) and touches(b) and other.get(sig(e), 0) == 0
            if edge:
                print(f'  {name} edge entity {e.dxf.handle} {e.dxftype()} {e.dxf.layer}', [round(v, 3) for v in b])
            if inside(b) or edge:
                mine.append(e) if name == 'base' else mine.add(e.dxf.handle)
    print(f'drop {len(drop)} from base, take {len(take)} from suite')
    if '--dry' in sys.argv:
        return
    before = Counter(e.dxf.layer for e in t.modelspace())
    for e in drop:
        t.modelspace().delete_entity(e)
    xref.load_modelspace(s, t, filter_fn=lambda e: e.dxf.handle in take, conflict_policy=xref.ConflictPolicy.KEEP)
    print('audit errors:', len(t.audit().errors))
    after = Counter(e.dxf.layer for e in t.modelspace())
    for L in sorted(set(before) | set(after)):
        if before[L] != after[L]:
            print(f'  {L}: {before[L]} -> {after[L]} ({after[L] - before[L]:+d})')
    t.saveas(out)


if __name__ == '__main__':
    main()
