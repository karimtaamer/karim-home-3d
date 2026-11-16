// Site measurements (New As-built only, 16 Nov 2026): tap a wall piece on the plan and type what the tape says on
// site. segmentWalls() splits every room's wall faces (the model's floor outlines) at each window / door / slider
// jamb, column or nib edge and corner, so a tap picks the smallest piece: corner → jamb, window width, pier, column
// face... Openings also offer their heights (sill, opening, above) and each room its ceiling height.
// Saved on the device at once (localStorage) and synced to /api/measurements (site_measurements.py, Vercel Blob), so
// the phone on site and the laptop see the same numbers. index.html loads this for ?v=new-asbuilt only.

const PROBE = [0.02, 0.04, 0.07];  // how far out from a room's face (m) to look for the wall or opening behind it
const STEP = 0.01;  // sampling along a face (m)
const MIN_PIECE = 0.03;  // pieces shorter than this (m) are drafting noise, folded into a neighbour
const SNAP = 0.015;  // a split within this of a wall / opening corner moves onto it
const FLAG_CM = 3;  // |measured − drawn| above this is flagged
const OPEN_NAME = { window: "Window", door: "Door", slider: "Slider" };

const inRing = ([x, y], ring) => {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
};
const inPoly = (p, poly) => inRing(p, poly.outer) && !(poly.holes || []).some(h => inRing(p, h));
const area = ring => ring.reduce((s, [x, y], i) => { const [u, v] = ring[(i + 1) % ring.length]; return s + x * v - u * y; }, 0) / 2;
const len = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const unit = p => { const L = len(p.a, p.b) || 1; return [(p.b[0] - p.a[0]) / L, (p.b[1] - p.a[1]) / L]; };
const dot = (u, v) => u[0] * v[0] + u[1] * v[1];
const slug = s => String(s || "room").toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "");
const cmKey = ([x, y]) => `${Math.round(x * 100)},${Math.round(y * 100)}`;
export const fmt = v => (Math.round(v * 10) / 10).toFixed(1).replace(/\.0$/, "");

// What is just behind a room face at p (outward normal n): an opening's index, "wall", or "open" (another room, void).
function behind(M, p, n) {
  for (const d of PROBE) {
    const q = [p[0] + n[0] * d, p[1] + n[1] * d];
    const o = M.openings.findIndex(o => inRing(q, o.outer));
    if (o >= 0) return o;
    if (M.walls.some(w => inPoly(q, w))) return "wall";
  }
  // Nothing behind it: a floor that runs into an opening's recess (the terrace up to the glass) stands in the opening.
  const q = [p[0] - n[0] * 0.01, p[1] - n[1] * 0.01], o = M.openings.findIndex(o => inRing(q, o.outer));
  return o >= 0 ? o : "open";
}

// Every wall / opening corner near the line a→b, as distances along it: where a split should land exactly.
function corners(M, a, b) {
  const L = len(a, b), u = [(b[0] - a[0]) / L, (b[1] - a[1]) / L], out = [];
  for (const ring of [...M.walls.flatMap(w => [w.outer, ...(w.holes || [])]), ...M.openings.map(o => o.outer)])
    for (const p of ring) {
      const dx = p[0] - a[0], dy = p[1] - a[1], t = dx * u[0] + dy * u[1];
      if (t > 0 && t < L && Math.abs(dx * u[1] - dy * u[0]) < 0.35) out.push(t);
    }
  return out;
}

// One room face (edge a→b, outward normal n) split into runs of what lies behind it.
function runs(M, a, b, n) {
  const L = len(a, b), cells = Math.max(1, Math.round(L / STEP)), out = [];
  for (let i = 0; i < cells; i++) {
    const t = (i + 0.5) * L / cells, cls = behind(M, [a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L], n);
    const last = out[out.length - 1];
    if (last && last.cls === cls) last.t1 = (i + 1) * L / cells;
    else out.push({ cls, t0: i * L / cells, t1: (i + 1) * L / cells });
  }
  // Fold slivers into the longer neighbour, then snap each split onto a nearby drawn corner.
  for (let i = 0; out.length > 1 && i < out.length;) {
    const r = out[i];
    if (r.t1 - r.t0 >= MIN_PIECE) { i++; continue; }
    const prev = out[i - 1], next = out[i + 1];
    const into = !prev ? next : !next ? prev : (prev.t1 - prev.t0 >= next.t1 - next.t0 ? prev : next);
    if (into === prev) prev.t1 = r.t1; else next.t0 = r.t0;
    out.splice(i, 1);
    if (prev && next && prev.cls === next.cls && out.includes(prev) && out.includes(next)) { prev.t1 = next.t1; out.splice(out.indexOf(next), 1); }
  }
  if (out.length > 1) {
    const cs = corners(M, a, b);
    for (let i = 1; i < out.length; i++) {
      const t = out[i].t0, c = cs.reduce((best, c) => Math.abs(c - t) < Math.abs(best - t) ? c : best, Infinity);
      if (Math.abs(c - t) <= SNAP) out[i - 1].t1 = out[i].t0 = c;
    }
  }
  const at = t => [a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L];
  return out.map(r => ({ cls: r.cls, a: at(r.t0), b: at(r.t1) }));
}

// Pieces of one ring of a room's floor, merged along straight runs, in order round the room.
function ringPieces(M, ring, roomLeft) {
  const pts = ring.filter((p, i) => len(p, ring[(i + 1) % ring.length]) > 0.002);
  const pieces = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length], L = len(a, b);
    if (L < 1e-4) continue;
    const u = [(b[0] - a[0]) / L, (b[1] - a[1]) / L], n = roomLeft ? [u[1], -u[0]] : [-u[1], u[0]];
    for (const r of runs(M, a, b, n)) pieces.push({ ...r, n });
  }
  // A gap of a few cm with nothing behind it (a door frame's drafting gap) counts as wall.
  for (const p of pieces) if (p.cls === "open" && len(p.a, p.b) < 0.1) p.cls = "wall";
  // Merge neighbours with the same thing behind them that carry on in a straight line.
  const straight = (p, q) => {
    const L = len(p.a, q.b);
    if (L < 1e-6) return false;
    const off = Math.abs((q.a[0] - p.a[0]) * (q.b[1] - p.a[1]) - (q.a[1] - p.a[1]) * (q.b[0] - p.a[0])) / L;
    const dir = (p.b[0] - p.a[0]) * (q.b[0] - q.a[0]) + (p.b[1] - p.a[1]) * (q.b[1] - q.a[1]);
    return off < 0.004 && dir > 0;
  };
  for (let again = true; again && pieces.length > 1;) {
    again = false;
    for (let i = 0; i < pieces.length && pieces.length > 1; i++) {
      const p = pieces[i], q = pieces[(i + 1) % pieces.length];
      if (p.cls === q.cls && straight(p, q)) {
        p.b = q.b;
        pieces.splice((i + 1) % pieces.length, 1);
        again = true;
        i--;
      }
    }
  }
  return pieces.filter(p => len(p.a, p.b) >= MIN_PIECE);
}

// Turn at the joint p→q, for a ring with the room on its left: > 0 turns into the room (an inside corner), < 0 turns
// out (a column, nib or reveal edge standing into the room).
const turn = (p, q, roomLeft) => {
  const c = (p.b[0] - p.a[0]) * (q.b[1] - q.a[1]) - (p.b[1] - p.a[1]) * (q.b[0] - q.a[0]);
  return roomLeft ? c : -c;
};

// All the measurable pieces of the version's model: wall faces, openings (width and heights) and ceiling heights.
export function segmentWalls(M) {
  const segs = [], ids = new Set(), seenOpening = new Map();
  const add = s => {
    let id = s.id;
    for (let k = 2; ids.has(id); k++) id = `${s.id}~${k}`;
    ids.add(id);
    segs.push({ ...s, id });
    return segs[segs.length - 1];
  };
  const keyOf = (kind, room, a, b) => `${kind}:${slug(room)}:${[cmKey(a), cmKey(b)].sort().join("-")}`;
  // Indoor rooms first, so an opening's width is filed under the room it is measured from inside.
  const floors = [...M.floor].sort((f, g) => (f.kind === "outdoor") - (g.kind === "outdoor"));
  for (const f of floors) {
    const room = f.room || "Room";
    for (const [ri, ring] of [f.outer, ...(f.holes || [])].entries()) {
      const roomLeft = (area(ring) > 0) === (ri === 0);
      const ps = ringPieces(M, ring, roomLeft);
      ps.forEach((p, i) => {
        p.prev = ps[(i - 1 + ps.length) % ps.length];
        p.next = ps[(i + 1) % ps.length];
      });
      const endName = (p, q, start) => {  // what one end of wall piece p is, q the piece beyond it
        if (q.cls === "open") return "open end";
        if (typeof q.cls === "number") return `${(M.openings[q.cls].kind || "opening")} jamb`;
        const t = start ? turn(q, p, roomLeft) : turn(p, q, roomLeft);
        if (t < 0) return isReveal(q) ? `${revealOf(q)} jamb` : "column / nib edge";
        return "corner";
      };
      const opNeighbour = p => [p.prev, p.next].find(q => typeof q.cls === "number");
      // A short return beside an opening, square to it: the reveal (jamb depth).
      const isReveal = p => {
        const q = p.cls === "wall" && len(p.a, p.b) <= 0.3 && opNeighbour(p);
        return !!q && Math.abs(dot(unit(p), unit(q))) < 0.2;
      };
      const revealOf = p => M.openings[opNeighbour(p).cls].kind || "opening";
      for (const p of ps) {
        const L = len(p.a, p.b), inward = [-p.n[0], -p.n[1]];
        if (p.cls === "open") continue;
        if (typeof p.cls === "number") {
          const o = M.openings[p.cls], kind = o.kind || "door";
          if (seenOpening.has(p.cls)) continue;  // its width once, from the first room that sees it
          const s = add({ id: keyOf(kind, room, p.a, p.b), room, kind, label: `${OPEN_NAME[kind] || "Opening"} width`,
            a: p.a, b: p.b, n: inward, drawn: L * 100, from: `${kind} jamb`, to: `${kind} jamb`, opening: p.cls });
          seenOpening.set(p.cls, s);
          continue;
        }
        const from = endName(p, p.prev, true), to = endName(p, p.next, false);
        let kind = "wall", label = "Wall";
        if (isReveal(p)) { kind = "reveal"; label = `${OPEN_NAME[revealOf(p)] || "Opening"} reveal (wall depth)`; }
        else if (L < 0.15 && from !== to) { kind = "nib"; label = "Nib / frame step"; }
        else if (/jamb/.test(from) && /jamb/.test(to)) { kind = "pier"; label = "Pier between openings"; }
        else if (L < 0.6 && /column/.test(from) && /column/.test(to)) { kind = "column"; label = "Column / nib face"; }
        else if (/jamb|column/.test(from + to) && L < 0.6) { kind = "pier"; label = "Pier"; }
        add({ id: keyOf(kind, room, p.a, p.b), room, kind, label, a: p.a, b: p.b, n: inward, drawn: L * 100, from, to });
      }
    }
  }
  // Heights: each opening's (from the model's sill / head, as index.html builds them) and each room's ceiling.
  for (const [i, s] of seenOpening) {
    const o = M.openings[i], kind = s.kind;
    const head = o.head ?? (kind === "window" ? M.winHead : kind === "slider" ? M.sliderHead : M.doorHead);
    const sill = kind === "window" ? o.sill ?? M.sill : 0;
    const v = (part, label, cmv, from, to) => add({ id: `${s.id}#${part}`, room: s.room, kind: part, label, a: s.a, b: s.b,
      n: s.n, drawn: cmv * 100, from, to, parent: s.id, vertical: true });
    s.parts = [];
    if (sill > 0) s.parts.push(v("sill", `${OPEN_NAME[kind]} sill height`, sill, "floor", "sill").id);
    s.parts.push(v("height", `${OPEN_NAME[kind] || "Opening"} height`, head - sill, sill > 0 ? "sill" : "floor", "head").id);
    s.parts.push(v("above", `Wall above ${kind}`, M.ceiling - head, "head", "ceiling").id);
  }
  for (const f of floors) {
    if (f.kind === "outdoor" || segs.some(s => s.kind === "ceiling" && s.room === f.room)) continue;
    const c = centroid(f.outer);
    add({ id: `ceiling:${slug(f.room)}`, room: f.room, kind: "ceiling", label: "Ceiling height", a: c, b: c, n: [0, 0],
      drawn: M.ceiling * 100, from: "floor", to: "ceiling", vertical: true });
  }
  return segs;
}

function centroid(ring) {
  let a = 0, x = 0, y = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
    a += f; x += (ring[j][0] + ring[i][0]) * f; y += (ring[j][1] + ring[i][1]) * f;
  }
  return [x / (3 * a), y / (3 * a)];
}

// --- Saved measurements: { id: { value (cm) | null when cleared, note, updated (ms) } }, last write wins per id ------
export function mergeEntries(a = {}, b = {}) {
  const out = { ...a };
  for (const [id, e] of Object.entries(b)) if (!out[id] || (e.updated || 0) > (out[id].updated || 0)) out[id] = e;
  return out;
}
export const diffOf = (s, e) => (e && e.value != null ? e.value - s.drawn : null);
export const stateOf = (s, e) => (!e || e.value == null ? "todo" : Math.abs(diffOf(s, e)) > FLAG_CM ? "off" : "ok");
const signed = d => `${d > 0 ? "+" : d < 0 ? "−" : "±"}${fmt(Math.abs(d))}`;

const BG = "#212830";
const COL = { todo: "#8d97a3", ok: "#3ddc84", off: "#ff9d2e", bad: "#ff5c5c", sel: "#4fd8ff" };
const colourOf = (s, e) => { const st = stateOf(s, e); return st === "off" && Math.abs(diffOf(s, e)) > 10 ? COL.bad : COL[st]; };
const CSS = `
#sm-open { position: fixed; z-index: 4; top: 132px; right: 22px; border: 0; border-radius: 999px; min-height: 44px; padding: 0 16px;
  font: 600 13px Inter, sans-serif; color: #fffaf3; background: linear-gradient(180deg, #2f6b4f, #1d3f30); box-shadow: 0 3px 12px #0003, 0 0 0 1px #7fe0b040 inset; cursor: pointer; }
@media (max-width: 760px) { #sm-open { top: 54px; right: 12px; } }
#sm { position: fixed; inset: 0; z-index: 30; background: ${BG}; color: #f3eee5; font: 14px Inter, system-ui, sans-serif; }
#sm[hidden], #sm [hidden] { display: none !important; }
#sm canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; touch-action: none; }
#sm button { font: inherit; color: inherit; cursor: pointer; }
#sm .top { position: absolute; top: 0; left: 0; right: 0; display: flex; align-items: center; gap: 8px; padding: 8px 10px; padding-top: max(8px, env(safe-area-inset-top));
  background: #161b21e8; backdrop-filter: blur(8px); box-shadow: 0 1px 0 #ffffff14; }
#sm .top .ttl { flex: 1; min-width: 0; line-height: 1.2; }
#sm .top .ttl b { display: block; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#sm .top .ttl small { font-size: 12px; color: #c9d1d9; }
#sm .btn { min-width: 44px; min-height: 44px; border: 0; border-radius: 12px; padding: 0 12px; background: #ffffff14; }
#sm .btn:active { background: #ffffff2a; }
#sm .btn.pri { background: #3ddc84; color: #10241a; font-weight: 700; }
#sm .sync { font-size: 11.5px; padding: 3px 8px; border-radius: 999px; background: #ffffff14; white-space: nowrap; }
#sm .sync.ok { color: #3ddc84; } #sm .sync.busy { color: #c9d1d9; } #sm .sync.off { color: #ff9d2e; } #sm .sync.local { color: #c9d1d9; }
#sm .menu { position: absolute; right: 10px; top: 60px; display: flex; flex-direction: column; gap: 4px; padding: 8px; border-radius: 14px; background: #161b21f4; box-shadow: 0 8px 30px #0008; }
#sm .menu .btn { text-align: left; }
#sm .help { position: absolute; left: 50%; transform: translateX(-50%); bottom: 18px; padding: 8px 14px; border-radius: 999px; background: #161b21e0; font-size: 12.5px; color: #c9d1d9; white-space: nowrap; pointer-events: none; }
#sm .sheet { position: absolute; left: 0; right: 0; bottom: 0; padding: 12px 14px; padding-bottom: max(14px, env(safe-area-inset-bottom)); background: #161b21f6;
  border-radius: 18px 18px 0 0; box-shadow: 0 -8px 30px #0007; display: flex; flex-direction: column; gap: 10px; }
@media (min-width: 761px) { #sm .sheet { left: 16px; right: auto; bottom: 16px; width: 400px; border-radius: 18px; } }
#sm .sheet .hd { display: flex; align-items: flex-start; gap: 8px; }
#sm .sheet .hd > div { flex: 1; min-width: 0; }
#sm .sheet .room { font-size: 12px; letter-spacing: .06em; color: #c9d1d9; }
#sm .sheet .kind { font-size: 17px; font-weight: 700; }
#sm .sheet .desc { font-size: 13px; color: #c9d1d9; }
#sm .chips { display: flex; gap: 6px; flex-wrap: wrap; }
#sm .chip { min-height: 44px; padding: 0 14px; border-radius: 999px; border: 1px solid #ffffff2a; background: none; font-size: 13px; }
#sm .chip.on { background: #f3eee5; color: #161b21; border-color: #f3eee5; font-weight: 600; }
#sm .chip i { font-style: normal; margin-left: 5px; }
#sm .val { display: flex; align-items: center; gap: 10px; }
#sm input { min-height: 48px; border-radius: 12px; border: 1px solid #ffffff30; background: #0e1216; color: #fff; padding: 0 12px; font: 16px Inter, sans-serif; box-sizing: border-box; }
#sm input.num { width: 140px; font-size: 22px; font-weight: 600; }
#sm input.note { width: 100%; }
#sm .diff { font-size: 15px; font-weight: 700; }
#sm .row { display: flex; gap: 8px; }
#sm .row .btn { flex: 1; }
#sm .list { position: absolute; left: 0; right: 0; bottom: 0; top: 64px; background: #161b21fa; border-radius: 18px 18px 0 0; display: flex; flex-direction: column; }
@media (min-width: 761px) { #sm .list { left: auto; width: 420px; top: 72px; right: 12px; bottom: 12px; border-radius: 18px; } }
#sm .list .lh { padding: 12px 14px 8px; display: flex; flex-direction: column; gap: 8px; }
#sm .bar { height: 6px; border-radius: 3px; background: #ffffff1a; overflow: hidden; }
#sm .bar i { display: block; height: 100%; background: #3ddc84; }
#sm .list .body { flex: 1; overflow-y: auto; padding: 0 8px 20px; -webkit-overflow-scrolling: touch; touch-action: pan-y; }
#sm .list h4 { margin: 14px 6px 6px; font-size: 12px; letter-spacing: .08em; color: #c9d1d9; display: flex; justify-content: space-between; }
#sm .item { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 48px; padding: 6px 8px; border: 0; border-radius: 10px; background: none; text-align: left; }
#sm .item:active, #sm .item.sel { background: #ffffff14; }
#sm .item .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
#sm .item .t { flex: 1; min-width: 0; }
#sm .item .t b { display: block; font-size: 13.5px; font-weight: 600; }
#sm .item .t small { color: #aab3bd; font-size: 12px; }
#sm .item .n { text-align: right; font-size: 13px; white-space: nowrap; }
#sm .item .n small { display: block; color: #aab3bd; font-size: 11.5px; }
`;

// The measuring screen. M: the version's model; loadDrawing / drawingUrl: the 2D linework (drawing.js); version: the
// plan version whose measurements these are.
export function createSiteMeasure({ M, loadDrawing, drawingUrl, version, open: openNow = false }) {
  const KEY = `sitemeasure:${version}`, API = `/api/measurements?version=${encodeURIComponent(version)}`;
  const segs = segmentWalls(M), byId = Object.fromEntries(segs.map(s => [s.id, s]));
  const plan = segs.filter(s => !s.vertical), ceilings = segs.filter(s => s.kind === "ceiling");
  // List order: room by room (as the model lists them), each opening's heights straight after its width.
  const rooms = [...new Set(segs.map(s => s.room))];
  const order = rooms.flatMap(r => segs.filter(s => s.room === r && !s.parent).flatMap(s => [s, ...(s.parts || []).map(id => byId[id])]));
  const measurable = order.length;

  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { /* a broken store starts empty */ }
  let entries = saved.entries || {};
  const dirty = new Set(saved.dirty || []);
  const persist = () => { try { localStorage.setItem(KEY, JSON.stringify({ entries, dirty: [...dirty] })); } catch { /* full: the sync still has it */ } };

  document.head.append(Object.assign(document.createElement("style"), { textContent: CSS }));
  const openBtn = Object.assign(document.createElement("button"), { id: "sm-open", type: "button", textContent: "📏 Site measurements" });
  openBtn.title = "Tap a wall on the plan and record the real site measurement";
  document.body.append(openBtn);
  const root = Object.assign(document.createElement("div"), { id: "sm", hidden: true });
  root.innerHTML = `
    <canvas></canvas>
    <div class="top">
      <button class="btn" data-a="close" aria-label="Close site measurements">✕</button>
      <div class="ttl"><b>Site measurements</b><small class="prog"></small></div>
      <span class="sync"></span>
      <button class="btn" data-a="list">List</button>
      <button class="btn" data-a="more" aria-label="More">⋯</button>
    </div>
    <div class="menu" hidden>
      <button class="btn" data-a="fit">Fit plan</button>
      <button class="btn" data-a="csv">Export CSV</button>
      <button class="btn" data-a="json">Export JSON</button>
      <button class="btn" data-a="import">Import JSON…</button>
      <input type="file" accept="application/json,.json" hidden>
    </div>
    <div class="help">Tap a wall · pinch to zoom · zoom in for ceilings</div>
    <div class="sheet" hidden>
      <div class="hd"><div><div class="room"></div><div class="kind"></div><div class="desc"></div></div>
        <button class="btn" data-a="deselect" aria-label="Close">✕</button></div>
      <div class="chips parts"></div>
      <div class="val"><input class="num" inputmode="decimal" enterkeyhint="done" autocomplete="off" placeholder="cm" aria-label="Measured, cm">
        <span>cm</span><span class="diff"></span></div>
      <input class="note" type="text" placeholder="Note (optional)" aria-label="Note">
      <div class="row"><button class="btn" data-a="clear">Clear</button><button class="btn" data-a="next" title="The next piece with no measurement">Next ›</button>
        <button class="btn pri" data-a="save">Save</button></div>
    </div>
    <div class="list" hidden>
      <div class="lh"><div style="display:flex;align-items:center;gap:8px"><b class="lcount" style="flex:1"></b>
        <button class="btn" data-a="closelist" aria-label="Close list">✕</button></div>
        <div class="bar"><i></i></div>
        <div class="chips filt"><button class="chip on" data-f="all">All</button><button class="chip" data-f="todo">Missing</button>
          <button class="chip" data-f="done">Done</button><button class="chip" data-f="off">Off &gt; ${FLAG_CM} cm</button></div></div>
      <div class="body"></div>
    </div>`;
  document.body.append(root);
  const $ = s => root.querySelector(s);
  const canvas = $("canvas"), ctx = canvas.getContext("2d");
  const sheet = $(".sheet"), num = $(".num"), note = $(".note"), list = $(".list"), menu = $(".menu");
  // Keys typed here are not the walk's (index.html listens on the window).
  root.addEventListener("keydown", e => {
    e.stopPropagation();
    if (e.key === "Enter" && (e.target === num || e.target === note)) save();
    if (e.key === "Escape") select(null);
  });
  root.addEventListener("keyup", e => e.stopPropagation());

  let data = null, shown = false, queued = false, W = 0, H = 0, dpr = 1, sel = null, filter = "all";
  const view = { s: 40, tx: 0, ty: 0 };  // screen = (tx + x·s, ty − y·s)
  const toScreen = ([x, y]) => [view.tx + x * view.s, view.ty - y * view.s];
  const toWorld = (sx, sy) => [(sx - view.tx) / view.s, (view.ty - sy) / view.s];
  const touchy = matchMedia("(pointer: coarse)").matches;
  const sheetH = () => (sheet.hidden || innerWidth > 760 ? 0 : sheet.offsetHeight);

  function fit() {
    const [bw, bh] = M.bounds, top = 64, bottom = 20 + sheetH();
    view.s = Math.min(W / bw, (H - top - bottom) / bh) * 0.94;
    view.tx = (W - bw * view.s) / 2;
    view.ty = top + (H - top - bottom + bh * view.s) / 2;
    redraw();
  }
  // Centre a piece in the free part of the screen, zoomed so it reads (a room's ceiling: its room).
  function focus(s) {
    const p = s.parent ? byId[s.parent] : s, L = Math.max(len(p.a, p.b), 0.8);
    const top = 64, bottom = sheetH() + 20, free = H - top - bottom;
    view.s = Math.max(Math.min(W, free) * 0.45 / L, Math.min(view.s, 600));
    view.s = Math.min(view.s, 600);
    const mx = (p.a[0] + p.b[0]) / 2, my = (p.a[1] + p.b[1]) / 2;
    view.tx = W / 2 - mx * view.s;
    view.ty = top + free / 2 + my * view.s;
    redraw();
  }
  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = innerWidth; H = innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    redraw();
  }
  const redraw = () => { if (shown && !queued) { queued = true; requestAnimationFrame(draw); } };

  let paths = null;
  function buildPaths() {
    paths = { strokes: [], fills: [] };
    for (const [col, lines] of Object.entries(data.strokes)) {
      const p = new Path2D();
      for (const l of lines) { p.moveTo(l[0], l[1]); for (let i = 2; i < l.length; i += 2) p.lineTo(l[i], l[i + 1]); }
      paths.strokes.push([col, p]);
    }
    for (const [col, shapes] of Object.entries(data.fills || {})) {
      const p = new Path2D();
      for (const loops of shapes) for (const l of loops) { p.moveTo(l[0], l[1]); for (let i = 2; i < l.length; i += 2) p.lineTo(l[i], l[i + 1]); p.closePath(); }
      paths.fills.push([col, p]);
    }
  }

  // A piece's line on screen, 4 px into its room so the two faces of a wall stay apart.
  const onScreen = s => {
    const [ax, ay] = toScreen(s.a), [bx, by] = toScreen(s.b), o = 4;
    return [[ax + s.n[0] * o, ay - s.n[1] * o], [bx + s.n[0] * o, by - s.n[1] * o]];
  };
  const selPlan = () => sel && (sel.parent ? byId[sel.parent] : sel);
  const markers = () => view.s >= 35;  // px per metre

  function draw() {
    queued = false;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, W, H);
    if (!data) return;
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * view.tx, dpr * view.ty);
    ctx.lineWidth = 1 / view.s;
    for (const [col, p] of paths.fills) { ctx.fillStyle = col; ctx.fill(p, "evenodd"); }
    for (const [col, p] of paths.strokes) { ctx.strokeStyle = col; ctx.stroke(p); }
    ctx.restore();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Room names and ceiling-height markers, once zoomed in enough for them not to cover the walls.
    ctx.font = "600 11px Inter, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    if (markers() || ceilings.includes(sel)) for (const c of ceilings) {
      if (!markers() && c !== sel) continue;
      const [x, y] = toScreen(c.a), e = entries[c.id], on = sel === c;
      ctx.fillStyle = "#f3eee5b0";
      ctx.fillText(c.room, x, y - 22);
      ctx.beginPath(); ctx.arc(x, y, on ? 15 : 12, 0, Math.PI * 2);
      ctx.fillStyle = on ? COL.sel : colourOf(c, e); ctx.fill();
      ctx.fillStyle = "#161b21"; ctx.fillText(e?.value != null ? fmt(e.value) : "H", x, y + 0.5);
    }
    const hi = selPlan();
    for (const s of plan) {
      const [a, b] = onScreen(s), e = entries[s.id];
      if (s === hi) {
        ctx.strokeStyle = COL.sel + "55"; ctx.lineWidth = 14; ctx.lineCap = "round";
        ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
      }
      const parts = (s.parts || []).map(id => entries[id]).filter(e => e?.value != null).length;
      ctx.strokeStyle = s === hi ? COL.sel : colourOf(s, e);
      ctx.lineWidth = s === hi ? 5 : e?.value != null || parts ? 4 : 2.5;
      ctx.lineCap = "butt";
      ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
      // End ticks, so neighbouring pieces read as separate.
      const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, nx = -(b[1] - a[1]) / L * 5, ny = (b[0] - a[0]) / L * 5;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (const [x, y] of [a, b]) { ctx.moveTo(x - nx, y - ny); ctx.lineTo(x + nx, y + ny); }
      ctx.stroke();
      if (e?.value != null || s === hi) label(s, a, b, e, s === hi);
    }
    status();
  }
  // The value beside a piece, inside its room: measured (and ± the drawing) or, selected, the drawn length.
  function label(s, a, b, e, on) {
    const d = diffOf(s, e), text = e?.value != null ? `${fmt(e.value)}${Math.abs(d) > 0.05 ? ` (${signed(d)})` : ""}` : `${fmt(s.drawn)} drawn`;
    let ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    if (ang > Math.PI / 2 || ang < -Math.PI / 2) ang += Math.PI;
    const cx = (a[0] + b[0]) / 2 + s.n[0] * 13, cy = (a[1] + b[1]) / 2 - s.n[1] * 13;
    ctx.save();
    ctx.translate(cx, cy); ctx.rotate(ang);
    ctx.font = "600 11.5px Inter, sans-serif";
    const w = ctx.measureText(text).width + 12;
    ctx.fillStyle = on ? COL.sel : e?.value != null ? colourOf(s, e) : "#3a434d";
    ctx.beginPath(); ctx.roundRect(-w / 2, -9, w, 18, 9); ctx.fill();
    ctx.fillStyle = on || e?.value != null ? "#10161b" : "#f3eee5";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, 0, 0.5);
    ctx.restore();
  }

  // The piece under a tap: the nearest wall line within reach (generous on touch), or a room's ceiling marker.
  function pick(sx, sy, kind) {
    let best = null, bd = kind === "touch" ? 32 : 16;
    if (markers()) for (const c of ceilings) {
      const [x, y] = toScreen(c.a), d = Math.hypot(sx - x, sy - y);
      if (d <= Math.min(bd, kind === "touch" ? 22 : 15)) { bd = d; best = c; }
    }
    for (const s of plan) {
      const [a, b] = onScreen(s), dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
      const t = l2 ? Math.max(0, Math.min(1, ((sx - a[0]) * dx + (sy - a[1]) * dy) / l2)) : 0;
      const d = Math.hypot(sx - a[0] - t * dx, sy - a[1] - t * dy);
      if (d < bd) { bd = d; best = s; }
    }
    return best;
  }

  // --- The input sheet ---------------------------------------------------------------------------------------------
  function select(s, { zoom = false } = {}) {
    sel = s;
    menu.hidden = true;
    sheet.hidden = !s;
    $(".help").hidden = !!s;
    if (s) {
      const p = s.parent ? byId[s.parent] : s, e = entries[s.id];
      $(".room").textContent = s.room;
      $(".kind").textContent = s.label;
      $(".desc").textContent = `${s.from} → ${s.to} · drawn ${fmt(s.drawn)} cm`;
      const parts = p.parts ? [p.id, ...p.parts] : [];
      const name = { sill: "Sill", height: "Height", above: "Above" };
      $(".parts").innerHTML = parts.map(id => {
        const q = byId[id], st = stateOf(q, entries[id]);
        return `<button class="chip${id === s.id ? " on" : ""}" data-part="${id}">${q.parent ? name[q.kind] : "Width"}<i>${st === "todo" ? "" : st === "ok" ? "✓" : "!"}</i></button>`;
      }).join("");
      $(".parts").hidden = !parts.length;
      num.value = e?.value != null ? fmt(e.value) : "";
      note.value = e?.note || "";
      showDiff();
      if (zoom) focus(s);
      if (!touchy) num.focus();
    }
    redraw();
  }
  function showDiff() {
    const v = parse(num.value), d = sel && v != null ? v - sel.drawn : null;
    $(".diff").textContent = d == null ? "" : `${signed(d)} cm`;
    $(".diff").style.color = d == null ? "" : Math.abs(d) > 10 ? COL.bad : Math.abs(d) > FLAG_CM ? COL.off : COL.ok;
  }
  const parse = t => {
    const v = parseFloat(String(t).replace(",", ".").trim());
    return Number.isFinite(v) && v > 0 && v < 5000 ? Math.round(v * 10) / 10 : null;
  };
  num.addEventListener("input", showDiff);
  $(".parts").addEventListener("click", e => { const b = e.target.closest("[data-part]"); if (b) select(byId[b.dataset.part]); });

  function record(id, value, text) {
    const s = byId[id];
    entries[id] = { value, note: text || "", updated: Date.now(), room: s.room, kind: s.kind, drawn: Math.round(s.drawn * 10) / 10 };
    dirty.add(id);
    persist();
    sync();
  }
  function save() {
    if (!sel) return;
    const v = parse(num.value);
    if (v == null) { num.focus(); num.style.borderColor = COL.bad; setTimeout(() => (num.style.borderColor = ""), 900); return; }
    record(sel.id, v, note.value.trim());
    // Straight on to this opening's next height, else stay (the value now shows on the plan).
    const p = sel.parent ? byId[sel.parent] : sel, parts = p.parts ? [p.id, ...p.parts] : [];
    const nextPart = parts.slice(parts.indexOf(sel.id) + 1).find(id => entries[id]?.value == null);
    select(nextPart ? byId[nextPart] : sel);
    if (!nextPart && touchy) num.blur();
    renderList();
  }
  function clear() {
    if (!sel || entries[sel.id]?.value == null) { num.value = ""; note.value = ""; showDiff(); return; }
    record(sel.id, null, "");
    select(sel);
    renderList();
  }
  function nextMissing() {
    const from = sel ? order.indexOf(sel) : -1;
    const n = [...order.slice(from + 1), ...order.slice(0, from + 1)].find(s => entries[s.id]?.value == null);
    if (n) select(n, { zoom: true });
  }

  // --- The list: progress, room by room, filtered ---------------------------------------------------------------
  const done = () => order.filter(s => entries[s.id]?.value != null).length;
  function renderList() {
    if (list.hidden) return;
    const n = done();
    $(".lcount").textContent = `${n} of ${measurable} measured`;
    $(".bar i").style.width = `${(100 * n / measurable).toFixed(1)}%`;
    const keep = s => {
      const st = stateOf(s, entries[s.id]);
      return filter === "all" || (filter === "todo" ? st === "todo" : filter === "done" ? st !== "todo" : st === "off");
    };
    const esc = t => String(t).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    $(".list .body").innerHTML = rooms.map(r => {
      const all = order.filter(s => s.room === r), rows = all.filter(keep);
      if (!rows.length) return "";
      const m = all.filter(s => entries[s.id]?.value != null).length;
      return `<h4><span>${esc(r)}</span><span>${m} / ${all.length}</span></h4>` + rows.map(s => {
        const e = entries[s.id], d = diffOf(s, e);
        return `<button class="item${s === sel ? " sel" : ""}" data-id="${esc(s.id)}"><span class="dot" style="background:${colourOf(s, e)}"></span>
          <span class="t"><b>${esc(s.label)}</b><small>${esc(s.from)} → ${esc(s.to)}${e?.note ? ` · ${esc(e.note)}` : ""}</small></span>
          <span class="n">${e?.value != null ? `${fmt(e.value)} <span style="color:${colourOf(s, e)}">${signed(d)}</span>` : "—"}<small>drawn ${fmt(s.drawn)}</small></span></button>`;
      }).join("");
    }).join("") || `<p style="padding:20px;color:#aab3bd">Nothing here.</p>`;
  }
  const setList = on => {
    list.hidden = !on; menu.hidden = true;
    if (on) { sheet.hidden = $(".help").hidden = true; renderList(); } else select(sel);
  };
  $(".list .body").addEventListener("click", e => {
    const b = e.target.closest("[data-id]");
    if (!b) return;
    list.hidden = true;
    select(byId[b.dataset.id], { zoom: true });
  });
  $(".filt").addEventListener("click", e => {
    const b = e.target.closest("[data-f]");
    if (!b) return;
    filter = b.dataset.f;
    for (const c of root.querySelectorAll(".filt .chip")) c.classList.toggle("on", c === b);
    renderList();
  });

  // --- Export / import ---------------------------------------------------------------------------------------------
  const rowsOut = () => order.map(s => {
    const e = entries[s.id], d = diffOf(s, e);
    return { id: s.id, room: s.room, kind: s.kind, label: s.label, from: s.from, to: s.to, drawn_cm: Math.round(s.drawn * 10) / 10,
      measured_cm: e?.value ?? null, diff_cm: d == null ? null : Math.round(d * 10) / 10, note: e?.note || "",
      updated: e?.updated ? new Date(e.updated).toISOString() : "" };
  });
  const download = (name, text, type) => {
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([text], { type })), download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  const stamp = () => new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  function exportCSV() {
    const rows = rowsOut(), cols = ["id", "room", "kind", "label", "from", "to", "drawn_cm", "measured_cm", "diff_cm", "note", "updated"];
    const cell = v => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    download(`site-measurements-${version}-${stamp()}.csv`, [cols.join(","), ...rows.map(r => cols.map(c => cell(r[c])).join(","))].join("\n"), "text/csv");
  }
  function exportJSON() {
    download(`site-measurements-${version}-${stamp()}.json`,
      JSON.stringify({ version, exported: new Date().toISOString(), total: measurable, measured: done(), segments: rowsOut(), entries }, null, 1), "application/json");
  }
  // A file from Export JSON (its entries) or any { entries } / { segments: [{ id, measured_cm, note, updated }] }.
  function importJSON(text) {
    const doc = JSON.parse(text);
    let inc = doc.entries;
    if (!inc && Array.isArray(doc.segments)) inc = Object.fromEntries(doc.segments.filter(r => r.id && r.measured_cm != null)
      .map(r => [r.id, { value: +r.measured_cm, note: r.note || "", updated: Date.parse(r.updated) || Date.now() }]));
    if (!inc || typeof inc !== "object") throw new Error("no measurements in that file");
    const before = entries;
    entries = mergeEntries(entries, inc);
    for (const id of Object.keys(inc)) if (entries[id] !== before[id]) dirty.add(id);
    persist(); sync(); redraw(); renderList();
    return Object.keys(inc).filter(id => byId[id]).length;
  }
  const file = $("input[type=file]");
  file.addEventListener("change", async () => {
    const f = file.files[0];
    file.value = "";
    if (!f) return;
    try { const n = importJSON(await f.text()); alert(`Imported ${n} measurement${n === 1 ? "" : "s"} (newest kept per piece).`); }
    catch (e) { alert(`Couldn't import: ${e.message}`); }
  });

  // --- Sync: localStorage first, then the server (last write wins per piece) -----------------------------------------
  let syncing = false, again = false, state = "busy";
  const syncEl = $(".sync");
  function setSync(s) {
    state = s;
    syncEl.className = `sync ${s}`;
    syncEl.textContent = { ok: "✓ Synced", busy: "Saving…", off: "Offline · on this device", local: "On this device" }[s];
    syncEl.title = { ok: "Saved on this device and online", busy: "Saving online…",
      off: "Saved on this device; it goes online when the connection is back", local: "Saved on this device (no online store here)" }[s];
  }
  async function sync() {
    if (syncing) { again = true; return; }
    syncing = true; again = false;
    const sent = Object.fromEntries([...dirty].filter(id => entries[id]).map(id => [id, entries[id]]));
    setSync("busy");
    try {
      const r = await fetch(API, Object.keys(sent).length
        ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ entries: sent }) }
        : { cache: "no-store" });
      if (r.status === 404 || r.status === 405 || r.status === 501 || !(r.headers.get("content-type") || "").includes("json")) setSync("local");
      else if (!r.ok) throw new Error(`HTTP ${r.status}`);
      else {
        const doc = await r.json();
        entries = mergeEntries(entries, doc.entries || {});
        for (const [id, e] of Object.entries(sent)) if ((entries[id]?.updated || 0) >= e.updated) dirty.delete(id);
        persist();
        setSync(dirty.size ? "busy" : "ok");
        redraw(); renderList();
        if (sel) { const v = entries[sel.id]; if (document.activeElement !== num && document.activeElement !== note) { num.value = v?.value != null ? fmt(v.value) : ""; showDiff(); } }
      }
    } catch { setSync("off"); }
    syncing = false;
    if (again || (dirty.size && state === "ok")) sync();
  }
  addEventListener("online", () => sync());
  setInterval(() => { if (dirty.size && state !== "local" && navigator.onLine !== false) sync(); }, 20000);
  setInterval(() => { if (shown && !dirty.size && state === "ok" && !document.hidden) sync(); }, 60000);  // the laptop sees the phone's
  document.addEventListener("visibilitychange", () => { if (!document.hidden && shown) sync(); });

  function status() {
    $(".prog").textContent = `${done()} of ${measurable} measured`;
  }

  // --- Pointer: drag pans, two fingers pinch, a tap picks; wheel zooms ----------------------------------------------
  const pointers = new Map();
  let press = null;
  const zoomAt = (sx, sy, f) => {
    const s0 = view.s;
    view.s = Math.min(1500, Math.max(5, s0 * f));
    const k = view.s / s0;
    view.tx = sx - (sx - view.tx) * k;
    view.ty = sy - (sy - view.ty) * k;
  };
  canvas.addEventListener("pointerdown", e => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    press = pointers.size === 1 ? { x: e.clientX, y: e.clientY, moved: false, kind: e.pointerType === "mouse" ? "mouse" : "touch" } : null;
    menu.hidden = true;
  });
  canvas.addEventListener("pointermove", e => {
    const prev = pointers.get(e.pointerId);
    if (!prev) return;
    if (pointers.size === 2) {
      const [o] = [...pointers].filter(([id]) => id !== e.pointerId).map(([, p]) => p);
      const before = Math.hypot(prev[0] - o[0], prev[1] - o[1]), now = Math.hypot(e.clientX - o[0], e.clientY - o[1]);
      view.tx += (e.clientX - prev[0]) / 2; view.ty += (e.clientY - prev[1]) / 2;
      if (before > 0) zoomAt((e.clientX + o[0]) / 2, (e.clientY + o[1]) / 2, now / before);
    } else if (press) {
      if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > 8) press.moved = true;
      if (press.moved) { view.tx += e.clientX - prev[0]; view.ty += e.clientY - prev[1]; }
    }
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    redraw();
  });
  const release = e => {
    if (!pointers.delete(e.pointerId)) return;
    if (e.type === "pointerup" && press && !press.moved) {
      const s = pick(e.clientX, e.clientY, press.kind);
      if (s) select(s);
      else if (sel) select(null);
    }
    if (!pointers.size) press = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("wheel", e => { e.preventDefault(); zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0015))); redraw(); }, { passive: false });

  root.addEventListener("click", e => {
    const a = e.target.closest("[data-a]")?.dataset.a;
    if (!a) return;
    ({ close: hide, list: () => setList(list.hidden), closelist: () => setList(false), more: () => (menu.hidden = !menu.hidden),
      fit: () => { menu.hidden = true; fit(); }, csv: () => { menu.hidden = true; exportCSV(); }, json: () => { menu.hidden = true; exportJSON(); },
      import: () => { menu.hidden = true; file.click(); }, deselect: () => select(null), save, clear, next: nextMissing })[a]?.();
  });
  addEventListener("resize", () => shown && resize());

  async function show() {
    shown = true;
    root.hidden = false;
    openBtn.hidden = true;
    resize();
    if (!data) { data = await loadDrawing(drawingUrl); buildPaths(); fit(); }
    redraw();
    sync();
  }
  function hide() {
    shown = false;
    root.hidden = true;
    openBtn.hidden = false;
    num.blur(); note.blur();
  }
  openBtn.onclick = show;
  setSync(dirty.size ? "off" : "busy");
  if (openNow) show();
  return { show, hide, segments: segs, get entries() { return entries; }, select: id => select(byId[id] || null, { zoom: true }), importJSON,
    frame: () => ({ toScreen, toWorld }) };  // screen px <-> plan metres (tests)
}
