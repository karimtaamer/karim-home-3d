// The DWG itself as a flat drawing (drawing.json, from build_drawing.py): pan, zoom and measure,
// with AutoCAD-style object snaps (endpoint, midpoint, centre) and ortho.

const BG = "#212830";
const MEASURE = "#ff8a3d";
const SNAP = "#f5e14b";
const STRAIGHT = "#4fd8b5";  // a line locked level / plumb
const CLICK_PX = 5;  // a press that moves further than this is a pan, not a pick
const PULSE_MS = 250;  // the flash when a line locks straight

export const cm = d => `${(d * 100).toFixed(1)} cm`;
export const SNAP_PX = { mouse: 12, touch: 26 };  // object snap reach (screen px)
// Soft ortho: a line within deg of level / plumb, or within px of the axis (finger wobble is in pixels; the band is
// capped at 2·deg so a short line isn't pulled straight from far off), locks straight. Beyond that it measures free.
const SOFT = { mouse: { deg: 6, px: 10 }, touch: { deg: 10, px: 24 } };
const HIT_PX = { mouse: 6, touch: 14 };  // how near a finished line a press picks it (screen px)

// drawing.json (or a plan version's drawing), fetched once and shared with the 3D tape measure (its snaps in the top view).
const drawings = new Map();
export function loadDrawing(url) {
  if (!drawings.has(url)) drawings.set(url, fetch(url).then(r => r.json()));
  return drawings.get(url);
}

export function createDrawing(root, url) {
  root.innerHTML = `
    <canvas></canvas>
    <div class="dbar">
      <button data-tool="measure"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17 17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/></svg>Measure</button>
      <button data-tool="clear" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>Clear</button>
    </div>
    <div class="dstatus"><span class="xy"></span><span class="dist"></span></div>
    <div class="dhelp"></div>`;
  const canvas = root.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const xy = root.querySelector(".xy"), dist = root.querySelector(".dist"), clear = root.querySelector("[data-tool=clear]");
  const touchy = matchMedia("(pointer: coarse)").matches;
  const helpText = () => (root.querySelector(".dhelp").textContent = touchy
    ? (measuring
      ? "Tap or drag to measure · two fingers pan / zoom · near-level lines snap straight · tap a line or its label to move its ends, × deletes it"
      : "Drag to pan · pinch to zoom · tap Measure to measure")
    : measuring
      ? "Wheel to zoom · click or drag to measure · near-level lines snap straight · click a line or its label to drag its ends · right / middle / Space-drag pans · Shift / F8 ortho · Esc cancels · Delete removes the selected · Backspace undoes"
      : "Wheel to zoom · drag to pan · click Measure to measure");

  let data = null, paths = null;
  let shown = false, dpr = 1, W = 0, H = 0;
  const view = { s: 40, tx: 0, ty: 0 };  // screen = (tx + x·s, ty − y·s)
  const done = [];  // finished measurements: [[ax, ay], [bx, by]]
  let start = null, cursor = null, snap = null, ortho = false, shift = false, space = false, measuring = false;
  let lock = null, pulse = -Infinity;  // the live line's axis ("h" / "v") and when it locked
  let sel = -1, hover = -1, hits = [], delBtn = null;  // the selected / hovered measurement; labels and × as drawn
  let queued = false;
  helpText();

  const toScreen = ([x, y]) => [view.tx + x * view.s, view.ty - y * view.s];
  const toWorld = (sx, sy) => [(sx - view.tx) / view.s, (view.ty - sy) / view.s];

  async function load() {
    data = await loadDrawing(url);
    paths = { strokes: [], fills: [] };
    for (const [col, lines] of Object.entries(data.strokes)) {
      const p = new Path2D();
      for (const l of lines) {
        p.moveTo(l[0], l[1]);
        for (let i = 2; i < l.length; i += 2) p.lineTo(l[i], l[i + 1]);
      }
      paths.strokes.push([col, p]);
    }
    for (const [col, shapes] of Object.entries(data.fills)) {
      const p = new Path2D();
      for (const loops of shapes) for (const l of loops) {
        p.moveTo(l[0], l[1]);
        for (let i = 2; i < l.length; i += 2) p.lineTo(l[i], l[i + 1]);
        p.closePath();
      }
      paths.fills.push([col, p]);
    }
    fit();
  }

  function fit() {
    const [bw, bh] = data.bounds;
    view.s = Math.min(W / bw, (H - 120) / bh) * 0.94;
    view.tx = (W - bw * view.s) / 2;
    view.ty = (H + bh * view.s) / 2 + 20;
    redraw();
  }

  function resize() {
    dpr = Math.min(devicePixelRatio, 2);
    W = innerWidth; H = innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    redraw();
  }

  function redraw() {
    if (shown && !queued) { queued = true; requestAnimationFrame(draw); }
  }

  function nearestSnap(wx, wy, reach) {
    const r = reach / view.s, s = data.snaps;
    let best = null, bd = r * r;
    for (let i = 0; i < s.length; i += 3) {
      const d = (s[i] - wx) ** 2 + (s[i + 1] - wy) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
    return best === null ? null : { p: [s[best], s[best + 1]], kind: s[best + 2], d: Math.sqrt(bd) * view.s };
  }

  // Is from → p near enough level ("h") or plumb ("v") to lock straight (see SOFT)?
  function softAxis(from, p, kind) {
    const { deg, px } = SOFT[kind];
    const dx = Math.abs(p[0] - from[0]) * view.s, dy = Math.abs(p[1] - from[1]) * view.s, len = Math.hypot(dx, dy);
    if (len < px) return null;  // too short to tell
    const t = Math.tan(deg * Math.PI / 180), tol = Math.max(len * t, Math.min(px, len * 2 * t));
    return dx >= dy ? (dy <= tol ? "h" : null) : (dx <= tol ? "v" : null);
  }

  // Where a pick lands: the nearest snap point in reach, then ortho squares it up from the fixed point (A, or the
  // other end of a measurement being edited). Shift / F8 always lock; otherwise only the pointer's direction decides:
  // near-straight locks and the snap is projected onto the axis, so wall to wall measures straight, while a clearly
  // angled drag keeps the snap as-is (a near-level snap alone never pulls a diagonal straight).
  function target(sx, sy, kind, from = start) {
    const [wx, wy] = toWorld(sx, sy);
    snap = nearestSnap(wx, wy, SNAP_PX[kind]);
    let p = snap ? snap.p : [wx, wy], axis = null;
    if (from) {
      axis = ortho || shift
        ? (Math.abs(p[0] - from[0]) >= Math.abs(p[1] - from[1]) ? "h" : "v")
        : softAxis(from, [wx, wy], kind);
      if (axis === "h") p = [p[0], from[1]];
      else if (axis === "v") p = [from[0], p[1]];
    }
    if (axis && axis !== lock) pulse = performance.now();
    lock = axis;
    return p;
  }

  const segDist = (px, py, [ax, ay], [bx, by]) => {
    const dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy;
    const t = l2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0;
    return Math.hypot(px - ax - t * dx, py - ay - t * dy);
  };

  // What a press on the finished measurements hits: the selected one's × (part "del"), its end handles (0 / 1,
  // within snap reach) or its line (2); any one's label (2); another one's line (2) only away from its ends and with
  // no snap point nearer than the line, so a press on a corner or wall end still starts a new measurement.
  function hitTest(sx, sy, kind) {
    const reach = SNAP_PX[kind], band = HIT_PX[kind], pad = kind === "touch" ? 6 : 2;
    if (sel >= 0) {
      if (delBtn && Math.hypot(sx - delBtn[0], sy - delBtn[1]) <= delBtn[2] + pad) return { i: sel, part: "del" };
      const [a, b] = done[sel].map(toScreen);
      const da = Math.hypot(sx - a[0], sy - a[1]), db = Math.hypot(sx - b[0], sy - b[1]);
      if (Math.min(da, db) <= reach) return { i: sel, part: da <= db ? 0 : 1 };
    }
    for (const { i, cx, cy, ang, w } of hits) {
      const x = (sx - cx) * Math.cos(ang) + (sy - cy) * Math.sin(ang), y = (sy - cy) * Math.cos(ang) - (sx - cx) * Math.sin(ang);
      if (Math.abs(x) <= w / 2 + pad && y >= -24 - pad && y <= -4 + pad) return { i, part: 2 };
    }
    let best = null, bd = band;
    done.forEach(([a, b], i) => {
      const sa = toScreen(a), sb = toScreen(b), d = segDist(sx, sy, sa, sb);
      if (d > bd) return;
      if (i !== sel && Math.min(Math.hypot(sx - sa[0], sy - sa[1]), Math.hypot(sx - sb[0], sy - sb[1])) <= reach) return;
      best = { i, part: 2 }; bd = d;
    });
    if (best && best.i !== sel && (nearestSnap(...toWorld(sx, sy), reach)?.d ?? Infinity) < bd) return null;
    return best;
  }

  function draw() {
    queued = false;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, W, H);
    if (!data) return;
    ctx.setTransform(dpr * view.s, 0, 0, -dpr * view.s, dpr * view.tx, dpr * view.ty);
    ctx.lineWidth = 1 / view.s;
    ctx.lineJoin = ctx.lineCap = "round";
    for (const [col, p] of paths.fills) { ctx.fillStyle = col; ctx.fill(p, "evenodd"); }
    for (const [col, p] of paths.strokes) { ctx.strokeStyle = col; ctx.stroke(p); }

    // Text in screen space, so small heights stay crisp at any zoom.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    for (const t of data.texts) {
      const px = t.h * view.s;
      if (px < 3) continue;
      const [sx, sy] = toScreen([t.x, t.y]);
      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(-t.r);
      ctx.font = `${px}px Inter, sans-serif`;
      ctx.fillStyle = t.c;
      ctx.textAlign = ["left", "center", "right"][t.a];
      ctx.textBaseline = t.b;
      ctx.fillText(t.t, 0, 0);
      ctx.restore();
    }

    hits = []; delBtn = null;
    const live = (start || edit?.end < 2) && lock;  // the line under way, or the end being dragged, locked straight
    done.forEach(([a, b], i) => {
      const end = edit?.i === i && edit.end < 2 ? edit.end : -1;
      dimension(a, b, { i, axis: end >= 0 ? live : null, tip: end ? b : a });
    });
    if (start && cursor) dimension(start, cursor, { dash: true, axis: live, tip: cursor });

    if (snap && live) {  // a snap projected onto the axis: a dotted tie from the snap to where B landed
      const [sx, sy] = toScreen(snap.p), [tx, ty] = toScreen(edit ? done[edit.i][edit.end] : cursor);
      if (Math.hypot(sx - tx, sy - ty) > 1) {
        ctx.strokeStyle = SNAP;
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(tx, ty); ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    if (snap) {
      const [sx, sy] = toScreen(snap.p);
      ctx.strokeStyle = SNAP;
      ctx.lineWidth = 2;
      ctx.beginPath();
      if (snap.kind === 0) ctx.rect(sx - 6, sy - 6, 12, 12);
      else if (snap.kind === 1) { ctx.moveTo(sx, sy - 7); ctx.lineTo(sx + 7, sy + 5); ctx.lineTo(sx - 7, sy + 5); ctx.closePath(); }
      else ctx.arc(sx, sy, 7, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (cursor && !touchy) {  // the crosshair and pick box
      const [sx, sy] = toScreen(cursor);
      ctx.strokeStyle = "#ffffff70";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, sy + 0.5); ctx.lineTo(W, sy + 0.5);
      ctx.moveTo(sx + 0.5, 0); ctx.lineTo(sx + 0.5, H);
      ctx.stroke();
      ctx.strokeStyle = "#ffffffc0";
      ctx.strokeRect(sx - 4.5, sy - 4.5, 9, 9);
    }
    if (live && performance.now() - pulse < PULSE_MS) redraw();  // only while the lock pulse plays
  }

  // A measured line: ticked ends and its length in cm, written along the line and kept upright. Locked straight
  // (axis) it turns STRAIGHT with an axis guide and an H / V badge at the moving end (tip), and pulses as it locks;
  // finished level / plumb lines keep square end ticks. The selected one gets a halo, end handles and a ×.
  function dimension(a, b, { i = -1, dash = false, axis = null, tip = b } = {}) {
    const [ax, ay] = toScreen(a), [bx, by] = toScreen(b);
    const k = Math.min(1, (performance.now() - pulse) / PULSE_MS);  // 0 → 1 through the pulse
    if (i >= 0 && (i === sel || i === hover)) {
      ctx.strokeStyle = i === sel ? "#ff8a3d55" : "#ff8a3d30";
      ctx.lineWidth = i === sel ? 10 : 7;
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    }
    if (axis) {
      ctx.strokeStyle = STRAIGHT + Math.round(90 + 120 * (1 - k)).toString(16);
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 5]);
      ctx.beginPath();
      if (axis === "h") { ctx.moveTo(0, ay); ctx.lineTo(W, ay); } else { ctx.moveTo(ax, 0); ctx.lineTo(ax, H); }
      ctx.stroke();
    }
    ctx.strokeStyle = ctx.fillStyle = axis ? STRAIGHT : MEASURE;
    ctx.lineWidth = axis ? 3 + 3 * (1 - k) : 2;
    ctx.setLineDash(dash ? [6, 4] : []);
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    ctx.setLineDash([]);
    for (const [x, y] of [[ax, ay], [bx, by]]) { ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill(); }
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (d < 1e-4) return;
    if (!dash && !axis && (a[0] === b[0] || a[1] === b[1])) {
      const nx = a[0] === b[0] ? 6 : 0, ny = 6 - nx;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (const [x, y] of [[ax, ay], [bx, by]]) { ctx.moveTo(x - nx, y - ny); ctx.lineTo(x + nx, y + ny); }
      ctx.stroke();
    }
    let ang = Math.atan2(by - ay, bx - ax);
    if (ang > Math.PI / 2 || ang < -Math.PI / 2) ang += Math.PI;
    const label = cm(d), cx = (ax + bx) / 2, cy = (ay + by) / 2;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(ang);
    ctx.font = "500 12px Inter, sans-serif";
    const w = ctx.measureText(label).width + 14;
    ctx.fillStyle = "#2b2622";
    ctx.beginPath(); ctx.roundRect(-w / 2, -24, w, 20, 10); ctx.fill();
    ctx.fillStyle = "#f3eee5";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(label, 0, -14);
    if (i >= 0 && i === sel) {  // × just past the label
      const r = touchy ? 11 : 9, x = w / 2 + r + 4;
      ctx.fillStyle = "#c2412d";
      ctx.beginPath(); ctx.arc(x, -14, r, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.8;
      ctx.beginPath(); ctx.moveTo(x - 4, -18); ctx.lineTo(x + 4, -10); ctx.moveTo(x + 4, -18); ctx.lineTo(x - 4, -10); ctx.stroke();
      delBtn = [cx + x * Math.cos(ang) + 14 * Math.sin(ang), cy + x * Math.sin(ang) - 14 * Math.cos(ang), r];
    }
    ctx.restore();
    if (i >= 0) hits.push({ i, cx, cy, ang, w });
    if (i >= 0 && i === sel) {
      ctx.fillStyle = "#fff";
      ctx.strokeStyle = axis ? STRAIGHT : MEASURE;
      ctx.lineWidth = 2.5;
      for (const [x, y] of [[ax, ay], [bx, by]]) { ctx.beginPath(); ctx.arc(x, y, touchy ? 9 : 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); }
    }
    if (axis) {
      const [tx, ty] = toScreen(tip);
      if (k < 1) {  // the lock pulse: a ring opening out from the moving end
        ctx.strokeStyle = STRAIGHT + Math.round(255 * (1 - k)).toString(16).padStart(2, "0");
        ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(tx, ty, 8 + 18 * k, 0, Math.PI * 2); ctx.stroke();
      }
      // The badge, clear of the finger on touch: a double arrow and H / V.
      const x = Math.min(W - 26, Math.max(26, tx + (touchy ? 20 : 16))), y = Math.max(16, ty - (touchy ? 54 : 30));
      ctx.fillStyle = "#17322cee";
      ctx.strokeStyle = STRAIGHT;
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.roundRect(x - 20, y - 11, 40, 22, 11); ctx.fill(); ctx.stroke();
      ctx.beginPath();
      if (axis === "h") {
        ctx.moveTo(x - 14, y); ctx.lineTo(x, y);
        ctx.moveTo(x - 10, y - 4); ctx.lineTo(x - 14, y); ctx.lineTo(x - 10, y + 4);
        ctx.moveTo(x - 4, y - 4); ctx.lineTo(x, y); ctx.lineTo(x - 4, y + 4);
      } else {
        ctx.moveTo(x - 7, y - 7); ctx.lineTo(x - 7, y + 7);
        ctx.moveTo(x - 11, y - 3); ctx.lineTo(x - 7, y - 7); ctx.lineTo(x - 3, y - 3);
        ctx.moveTo(x - 11, y + 3); ctx.lineTo(x - 7, y + 7); ctx.lineTo(x - 3, y + 3);
      }
      ctx.stroke();
      ctx.fillStyle = STRAIGHT;
      ctx.font = "600 12px Inter, sans-serif";
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(axis.toUpperCase(), x + 9, y + 0.5);
    }
  }

  function status() {
    clear.disabled = !done.length && !start;  // only when there is a measurement (or one under way) to clear
    xy.textContent = cursor ? `X ${cursor[0].toFixed(3)}  Y ${cursor[1].toFixed(3)} m` : "";
    const m = start && cursor ? [start, cursor] : done[sel >= 0 ? sel : done.length - 1];
    if (!m) { dist.textContent = ""; return; }
    const [a, b] = m;
    dist.textContent = `Distance ${cm(Math.hypot(b[0] - a[0], b[1] - a[1]))} · ΔX ${cm(Math.abs(b[0] - a[0]))} · ΔY ${cm(Math.abs(b[1] - a[1]))}`;
  }

  // --- Pointer: with Measure on, one finger (or the left button) measures: pressing sets A, or presses B,
  // which follows the pointer until it lifts; a press dragged off A ends at B on lift. Two fingers, the
  // middle / right button or Space-drag pan (any drag does with Measure off); wheel / pinch zooms. A press on a
  // finished measurement (see hitTest) selects it instead: dragging an end handle moves that end, the line moves
  // it all; a tap elsewhere deselects (a drag there measures as usual). ----
  const pointers = new Map();
  let press = null, gesture = null, lastMiddle = 0;  // gesture: the measuring press ({ id, kind, a: it set A, desel })
  let edit = null;  // dragging the selected measurement: { id, i, end: 0 / 1 / 2 (the line), kind, orig, off }

  // A second finger, a cancelled pointer or Esc drops the point under way (A if this press set it), or puts back
  // the measurement being dragged.
  function dropGesture() {
    if (edit) { done[edit.i] = edit.orig; edit = null; }
    lock = null;
    if (!gesture) return;
    if (gesture.a) start = null;
    cursor = start;
    gesture = snap = null;
  }
  function remove(i) {
    done.splice(i, 1);
    sel = sel === i ? -1 : sel - (sel > i);
    hover = -1;
  }
  const pointerKind = e => (e.pointerType === "mouse" ? "mouse" : "touch");

  // Drag the selected measurement: an end follows the pointer (kept where it was grabbed from), with the same snaps
  // and ortho as a new one from its other end; the line moves whole, snapping whichever end is nearer a snap point.
  function dragEdit(sx, sy) {
    const m = done[edit.i];
    if (edit.end < 2) {
      m[edit.end] = cursor = target(sx + edit.off[0], sy + edit.off[1], edit.kind, m[1 - edit.end]);
      return;
    }
    const [x0, y0] = toWorld(press.x, press.y), [x1, y1] = toWorld(sx, sy);
    let [a, b] = edit.orig.map(p => [p[0] + x1 - x0, p[1] + y1 - y0]);
    const sa = nearestSnap(...a, SNAP_PX[edit.kind]), sb = nearestSnap(...b, SNAP_PX[edit.kind]);
    snap = sa && (!sb || sa.d <= sb.d) ? sa : sb;
    if (snap) {
      const [dx, dy] = [0, 1].map(k => snap.p[k] - (snap === sa ? a : b)[k]);
      [a, b] = [a, b].map(p => [p[0] + dx, p[1] + dy]);
    }
    done[edit.i] = [a, b];
    lock = null;
  }
  const zoomAt = (sx, sy, f) => {
    const s0 = view.s;
    view.s = Math.min(4000, Math.max(2, s0 * f));
    const k = view.s / s0;
    view.tx = sx - (sx - view.tx) * k;
    view.ty = sy - (sy - view.ty) * k;
  };

  canvas.addEventListener("pointerdown", e => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 1) {
      press = { x: e.clientX, y: e.clientY, button: e.button, moved: false };
      if (measuring && data && e.button === 0 && !space) {
        const kind = pointerKind(e), hit = start ? null : hitTest(e.clientX, e.clientY, kind);
        if (hit?.part === "del") { remove(sel); press = null; }
        else if (hit) {
          sel = hit.i;
          const m = done[sel], off = hit.part < 2 ? toScreen(m[hit.part]).map((v, k) => v - [e.clientX, e.clientY][k]) : [0, 0];
          edit = { id: e.pointerId, i: sel, end: hit.part, kind, orig: m.map(p => [...p]), off };
          snap = null;
        } else {
          gesture = { id: e.pointerId, kind, a: !start, desel: sel >= 0 };
          sel = hover = -1;
          cursor = target(e.clientX, e.clientY, kind);
          if (gesture.a) start = cursor;
        }
      }
    } else {
      press = null;  // a second finger: pan / pinch, never a measurement
      dropGesture();
    }
    status();
    redraw();
    if (e.button === 1) {
      e.preventDefault();
      if (performance.now() - lastMiddle < 350) fit();  // double-click the wheel: zoom extents
      lastMiddle = performance.now();
    }
  });
  canvas.addEventListener("pointermove", e => {
    const prev = pointers.get(e.pointerId);
    if (prev && pointers.size === 2) {
      const [o] = [...pointers].filter(([id]) => id !== e.pointerId).map(([, p]) => p);
      const before = Math.hypot(prev[0] - o[0], prev[1] - o[1]);
      const now = Math.hypot(e.clientX - o[0], e.clientY - o[1]);
      view.tx += (e.clientX - prev[0]) / 2;
      view.ty += (e.clientY - prev[1]) / 2;
      if (before > 0) zoomAt((e.clientX + o[0]) / 2, (e.clientY + o[1]) / 2, now / before);
    } else if (prev && press) {
      if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > CLICK_PX || press.button === 1) press.moved = true;
      if (gesture) cursor = target(e.clientX, e.clientY, gesture.kind);  // the live B, snapped
      else if (edit) { if (press.moved) dragEdit(e.clientX, e.clientY); }
      else if (press.moved) { view.tx += e.clientX - prev[0]; view.ty += e.clientY - prev[1]; }
    }
    if (prev) pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (data && e.pointerType === "mouse" && !gesture && !edit) {
      cursor = target(e.clientX, e.clientY, "mouse");
      hover = measuring && !start && !prev ? hitTest(e.clientX, e.clientY, "mouse")?.i ?? -1 : -1;
    }
    status();
    redraw();
  });
  const release = e => {
    if (!pointers.delete(e.pointerId)) return;
    if (edit?.id === e.pointerId) {
      const [a, b] = done[edit.i];
      if (e.type !== "pointerup" || Math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-4) dropGesture();
      edit = null;
      lock = null;
      status();
      redraw();
    }
    if (gesture?.id === e.pointerId) {
      // Lifting fixes B; a press that set A only ends the measurement if it was dragged off A (a tap that only
      // deselected sets no A).
      if (e.type !== "pointerup") dropGesture();
      else if (start && (!gesture.a || press?.moved)) {
        const p = target(e.clientX, e.clientY, gesture.kind);
        if (Math.hypot(p[0] - start[0], p[1] - start[1]) > 1e-4) done.push([start, p]);
        start = null;
        cursor = p;
      } else if (gesture.a && gesture.desel) start = null;
      gesture = null;
      lock = null;
      status();
      redraw();
    }
    if (!pointers.size) press = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") { cursor = start ? cursor : null; snap = null; hover = -1; redraw(); } });
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0015)));
    if (data && !edit) cursor = target(e.clientX, e.clientY, "mouse");
    redraw();
  }, { passive: false });
  canvas.addEventListener("contextmenu", e => e.preventDefault());

  addEventListener("keydown", e => {
    if (!shown) return;
    if (e.key === "Shift") { shift = true; }
    else if (e.key === " ") { e.preventDefault(); space = true; return; }  // Space-drag pans
    else if (e.key === "Escape") { start ? (start = gesture = null) : (sel = -1); lock = null; }
    else if (e.key === "Backspace" || e.key === "Delete") {  // the half-made one, else the selected, else the last
      if (edit) return;
      if (start) start = gesture = null;
      else if (sel >= 0) remove(sel);
      else if (done.length) remove(done.length - 1);
      lock = null;
    }
    else if (e.key === "F8") { e.preventDefault(); setOrtho(!ortho); }
    else return;
    status();
    redraw();
  });
  addEventListener("keyup", e => {
    if (e.key === "Shift") { shift = false; redraw(); }
    else if (e.key === " " && shown) { e.preventDefault(); space = false; }
  });

  const button = t => root.querySelector(`[data-tool=${t}]`);
  const setOrtho = on => (ortho = on);  // F8 (or hold Shift); no button
  // Measure is off whenever the drawing opens; only its button turns it on (and off again).
  function setMeasuring(on) {
    measuring = on;
    button("measure").classList.toggle("on", measuring);
    if (!measuring) { dropGesture(); start = null; sel = hover = -1; }
    helpText();
    status();
    redraw();
  }
  button("measure").onclick = () => setMeasuring(!measuring);
  clear.onclick = () => { dropGesture(); done.length = 0; start = null; sel = hover = -1; status(); redraw(); };
  addEventListener("resize", () => shown && resize());

  return {
    async show() {
      shown = true;
      root.hidden = false;
      setMeasuring(false);
      resize();
      if (!data) await load();
    },
    hide() { shown = false; root.hidden = true; shift = space = false; },
    frame: () => ({ toWorld, toScreen }),  // screen px <-> plan metres, for Edit AI's highlight
  };
}
