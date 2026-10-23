#!/usr/bin/env python3
"""dwgtool: inspect a plan DWG/DXF and render cropped, marked-up PNGs (libredwg + ezdxf + matplotlib).

Run with the DWG venv: ~/.dwg-tools/bin/python dwgtool.py <command> FILE ...
Adapted from the Apartment Architect bot's toolkit; DWG -> DXF uses libredwg's dwg2dxf instead of ODA.

Commands:
  convert  FILE.dwg                      -> DXF next to it (cached; rebuilt when the DWG is newer)
  info     FILE                          units, extents, layers, blocks, entity counts
  text     FILE [--grep REGEX]           TEXT/MTEXT/ATTRIB content with centre coordinates
  dims     FILE                          dimensions with measured values
  render   FILE -o out.png [options]     full or cropped PNG/PDF/SVG

Render options (all coordinates in DWG model-space metres):
  --bbox x1,y1,x2,y2      crop window
  --label REGEX           crop around a text label (first match, or --nth N); --radius R half-size (default 3)
  --layers L1,L2          show only these layers   --hide L1,L2  hide these layers
  --box x1,y1,x2,y2       red mark-up rectangle (repeatable)
  --circle x,y,r          red mark-up circle (repeatable)
  --note "x,y,TEXT"       red mark-up note (repeatable)
  --mark-label REGEX      red circle around every matching text label
  --grid                  coordinate axes and grid (to pick bboxes)
  --all                   true extents (default: robust extents; stray 3door content lies hundreds of metres away)
  --mono                  all lines black
  --dpi N  --width-in W   output resolution (default 200 dpi, 16 in wide)
"""
import argparse, os, re, shutil, subprocess, sys
import ezdxf
from ezdxf import bbox as ebbox, recover

UNITS = {0: 'unitless', 1: 'in', 2: 'ft', 4: 'mm', 5: 'cm', 6: 'm'}


def to_dxf(path):
    if path.lower().endswith('.dxf'):
        return path
    out = os.path.splitext(path)[0] + '.dxf'
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(path):
        return out
    if not shutil.which('dwg2dxf'):
        sys.exit('dwg2dxf not installed (brew install libredwg)')
    subprocess.run(['dwg2dxf', '-y', '-o', out, path], timeout=300, capture_output=True)
    if not os.path.exists(out):
        sys.exit('dwg2dxf conversion failed (no DXF produced)')
    return out


def load(path):
    # libredwg output has small structural faults, so always go through recover
    doc, _ = recover.readfile(to_dxf(path))
    return doc


def text_of(e):
    if e.dxftype() == 'MTEXT':
        return e.plain_text()
    return e.dxf.get('text', '')


def iter_texts(doc):
    msp = doc.modelspace()
    for e in msp.query('TEXT MTEXT'):
        yield e, text_of(e), e.dxf.insert
    for ins in msp.query('INSERT'):
        for a in ins.attribs:
            yield a, a.dxf.text, a.dxf.insert


def text_center(e, p):
    try:
        b = ebbox.extents([e])
        if b.has_data:
            return ((b.extmin.x + b.extmax.x) / 2, (b.extmin.y + b.extmax.y) / 2)
    except Exception:
        pass
    return (p.x, p.y)


def _center(e):
    try:
        b = ebbox.extents([e], fast=True)
    except Exception:
        return None
    if not b.has_data:
        return None
    return ((b.extmin.x + b.extmax.x) / 2, (b.extmin.y + b.extmax.y) / 2)


def robust_extents(msp, q=0.02, margin=0.05):
    import numpy as np
    cs = [c for c in (_center(e) for e in msp) if c]
    a = np.array(cs)
    lo, hi = np.quantile(a, q, axis=0), np.quantile(a, 1 - q, axis=0)
    span = hi - lo
    lo2, hi2 = lo - span * 0.5, hi + span * 0.5
    # the 3door dynamic blocks expand to every state, far off the plan: keep them out of the extents
    keep = [e for e in msp if e.dxf.layer != '3door' and (c := _center(e))
            and lo2[0] <= c[0] <= hi2[0] and lo2[1] <= c[1] <= hi2[1]]
    b = ebbox.extents(keep)
    w, h = b.extmax.x - b.extmin.x, b.extmax.y - b.extmin.y
    return (b.extmin.x - w * margin, b.extmin.y - h * margin, b.extmax.x + w * margin, b.extmax.y + h * margin)


def cmd_info(a):
    from collections import Counter
    doc = load(a.file); msp = doc.modelspace(); h = doc.header
    print('DXF version:', doc.dxfversion, '| codepage:', h.get('$DWGCODEPAGE'), '| units:', UNITS.get(h.get('$INSUNITS', 0), h.get('$INSUNITS')))
    b = ebbox.extents(msp)
    print('true extents: (%.2f, %.2f) - (%.2f, %.2f)' % (b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y))
    r = robust_extents(msp)
    print('main drawing extents: (%.2f, %.2f) - (%.2f, %.2f)  size %.2f x %.2f' % (r[0], r[1], r[2], r[3], r[2] - r[0], r[3] - r[1]))
    lc = Counter(e.dxf.layer for e in msp)
    print('layers (entities in modelspace):')
    for l in doc.layers:
        print('  %-22s color=%-3s %s%s n=%d' % (l.dxf.name, l.color, 'OFF ' if l.is_off() else '', 'FROZEN ' if l.is_frozen() else '', lc.get(l.dxf.name, 0)))
    print('entity types:', dict(Counter(e.dxftype() for e in msp).most_common()))
    print('block inserts:', dict(Counter(e.dxf.name for e in msp.query('INSERT')).most_common()))


def cmd_text(a):
    doc = load(a.file)
    rx = re.compile(a.grep, re.I) if a.grep else None
    for e, t, p in iter_texts(doc):
        if rx and not rx.search(t):
            continue
        c = text_center(e, p)
        print('%-10s %-12s center (%.2f, %.2f)  %s' % (e.dxftype(), e.dxf.layer, c[0], c[1], t.strip()))


def cmd_dims(a):
    doc = load(a.file)
    for e in doc.modelspace().query('DIMENSION'):
        try:
            m = e.get_measurement()
        except Exception:
            m = None
        p = e.dxf.defpoint
        print('%-8s m=%s override=%r at (%.2f, %.2f)' % (e.dxf.layer, '%.3f' % m if isinstance(m, float) else m, e.dxf.get('text', ''), p.x, p.y))


def _xy(s, n):
    v = [float(x) for x in s.split(',')[:n]]
    if len(v) != n:
        raise SystemExit('bad coords: ' + s)
    return v


def _darken(entity, props):
    """Light colours (yellow, cyan, light green) are unreadable on white: darken them."""
    c = props.color
    if not c or not c.startswith('#') or len(c) < 7:
        return
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if lum > 0.55:
        k = 0.55 / lum
        props.color = '#%02x%02x%02x' % (int(r * k), int(g * k), int(b * k)) + c[7:]


def cmd_render(a):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Circle
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy, LineweightPolicy

    doc = load(a.file); msp = doc.modelspace()
    show = set(a.layers.split(',')) if a.layers else None
    hide = set(a.hide.split(',')) if a.hide else set()

    def ff(e):
        lay = e.dxf.get('layer', '0')
        if lay in hide:
            return False
        if show is not None and e.dxftype() != 'INSERT' and lay not in show and lay != '0':
            return False
        if show is not None and e.dxftype() == 'INSERT' and lay not in show:
            return False
        return True

    texts = list(iter_texts(doc))
    if a.bbox:
        x1, y1, x2, y2 = _xy(a.bbox, 4)
    elif a.label:
        rx = re.compile(a.label, re.I)
        hits = [text_center(e, p) for e, t, p in texts if rx.search(t)]
        if not hits:
            sys.exit('label not found: ' + a.label)
        cx, cy = hits[min(a.nth, len(hits) - 1)]
        x1, y1, x2, y2 = cx - a.radius, cy - a.radius, cx + a.radius, cy + a.radius
    elif a.all:
        b = ebbox.extents(msp); x1, y1, x2, y2 = b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y
    else:
        x1, y1, x2, y2 = robust_extents(msp)
    x1, x2 = min(x1, x2), max(x1, x2); y1, y2 = min(y1, y2), max(y1, y2)

    cfg = Configuration(background_policy=BackgroundPolicy.WHITE,
                        color_policy=ColorPolicy.BLACK if a.mono else ColorPolicy.COLOR_SWAP_BW,
                        lineweight_policy=LineweightPolicy.ABSOLUTE,
                        min_lineweight=a.minlw)
    w_in = a.width_in
    h_in = max(2.0, w_in * (y2 - y1) / (x2 - x1))
    fig = plt.figure(figsize=(w_in, h_in))
    ax = fig.add_axes([0.04, 0.04, 0.94, 0.94] if a.grid else [0, 0, 1, 1])
    fe = Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg)
    if not a.mono:
        fe.push_property_override_function(_darken)
    fe.draw_layout(msp, finalize=True, filter_func=ff)
    fig.set_size_inches(w_in, h_in)
    ax.set_xlim(x1, x2); ax.set_ylim(y1, y2); ax.set_aspect('equal')
    if a.grid:
        ax.axis('on'); ax.set_frame_on(True)
        ax.xaxis.set_visible(True); ax.yaxis.set_visible(True)
        ax.grid(True, lw=0.4, alpha=0.6, color='#3399ff'); ax.tick_params(labelsize=9)
        ax.minorticks_on(); ax.grid(True, which='minor', lw=0.2, alpha=0.3, color='#3399ff')
    for s in a.box or []:
        bx1, by1, bx2, by2 = _xy(s, 4)
        ax.add_patch(Rectangle((min(bx1, bx2), min(by1, by2)), abs(bx2 - bx1), abs(by2 - by1), fill=False, ec='red', lw=3, zorder=1000))
    for s in a.circle or []:
        cx, cy, r = _xy(s, 3)
        ax.add_patch(Circle((cx, cy), r, fill=False, ec='red', lw=3, zorder=1000))
    if a.mark_label:
        rx = re.compile(a.mark_label, re.I)
        r = max(abs(x2 - x1) * 0.04, 0.4)
        for e, t, p in texts:
            if rx.search(t):
                ax.add_patch(Circle(text_center(e, p), r, fill=False, ec='red', lw=3, zorder=1000))
    for s in a.note or []:
        x, y, txt = s.split(',', 2)
        ax.text(float(x), float(y), txt, color='red', fontsize=14, weight='bold', zorder=1001,
                bbox=dict(fc='white', ec='red', alpha=0.85))
    fig.savefig(a.output, dpi=a.dpi, facecolor='white')
    print('wrote', a.output, 'window (%.2f, %.2f)-(%.2f, %.2f)' % (x1, y1, x2, y2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest='cmd', required=True)
    for n in ('convert', 'info', 'text', 'dims', 'render'):
        s = sp.add_parser(n); s.add_argument('file')
        if n == 'text':
            s.add_argument('--grep')
        if n == 'render':
            s.add_argument('-o', '--output', required=True)
            s.add_argument('--bbox'); s.add_argument('--label'); s.add_argument('--nth', type=int, default=0)
            s.add_argument('--radius', type=float, default=3.0)
            s.add_argument('--layers'); s.add_argument('--hide')
            s.add_argument('--box', action='append'); s.add_argument('--circle', action='append')
            s.add_argument('--note', action='append'); s.add_argument('--mark-label')
            s.add_argument('--grid', action='store_true'); s.add_argument('--all', action='store_true')
            s.add_argument('--mono', action='store_true')
            s.add_argument('--dpi', type=int, default=200); s.add_argument('--width-in', type=float, default=16)
            s.add_argument('--minlw', type=float, default=0.25)
    a = p.parse_args()
    if a.cmd == 'convert':
        print(to_dxf(a.file))
    else:
        globals()['cmd_' + a.cmd](a)


if __name__ == '__main__':
    main()
