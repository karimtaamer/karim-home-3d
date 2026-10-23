// The DWG itself as a flat drawing (drawing.json, from build_drawing.py): pan, zoom and measure,
// with AutoCAD-style object snaps (endpoint, midpoint, centre) and ortho.

const BG = "#212830";
const MEASURE = "#ff8a3d";
const SNAP = "#f5e14b";
const CLICK_PX = 5;  // a press that moves further than this is a pan, not a pick

export const cm = d => `${(d * 100).toFixed(1)} cm`;
export const SNAP_PX = { mouse: 12, touch: 26 };  // object snap reach (screen px)

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
      <button data-tool="measure" class="on"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17 17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/></svg>Measure</button>
      <button data-tool="clear" disabled><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>Clear</button>
    </div>
    <div class="dstatus"><span class="xy"></span><span class="dist"></span></div>
    <div class="dhelp"></div>`;
  const canvas = root.querySelector("canvas");
  const ctx = canvas.getContext("2d");
  const xy = root.querySelector(".xy"), dist = root.querySelector(".dist"), clear = root.querySelector("[data-tool=clear]");
  const touchy = matchMedia("(pointer: coarse)").matches;
  root.querySelector(".dhelp").textContent = touchy
    ? "Drag to pan · pinch to zoom · tap two points to measure"
    : "Wheel to zoom · drag to pan · click two points to measure · Shift / F8 ortho · Esc cancels · Backspace undoes";

  let data = null, paths = null;
  let shown = false, dpr = 1, W = 0, H = 0;
  const view = { s: 40, tx: 0, ty: 0 };  // screen = (tx + x·s, ty − y·s)
  const done = [];  // finished measurements: [[ax, ay], [bx, by]]
  let start = null, cursor = null, snap = null, ortho = false, shift = false, measuring = true;
  let queued = false;

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

  // Where a pick lands: the nearest snap point in reach, then ortho squares it up from the first point.
  function target(sx, sy, reach) {
    const [wx, wy] = toWorld(sx, sy);
    const r = reach / view.s, s = data.snaps;
    let best = null, bd = r * r;
    for (let i = 0; i < s.length; i += 3) {
      const d = (s[i] - wx) ** 2 + (s[i + 1] - wy) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
    snap = best === null ? null : { p: [s[best], s[best + 1]], kind: s[best + 2] };
    let p = snap ? snap.p : [wx, wy];
    if (start && (ortho || shift)) {
      p = Math.abs(p[0] - start[0]) >= Math.abs(p[1] - start[1]) ? [p[0], start[1]] : [start[0], p[1]];
    }
    return p;
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

    for (const [a, b] of done) dimension(a, b);
    if (start && cursor) dimension(start, cursor, true);

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
  }

  // A measured line: ticked ends and its length in cm, written along the line and kept upright.
  function dimension(a, b, live) {
    const [ax, ay] = toScreen(a), [bx, by] = toScreen(b);
    ctx.strokeStyle = MEASURE;
    ctx.lineWidth = 2;
    ctx.setLineDash(live ? [6, 4] : []);
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = MEASURE;
    for (const [x, y] of [[ax, ay], [bx, by]]) { ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill(); }
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (d < 1e-4) return;
    let ang = Math.atan2(by - ay, bx - ax);
    if (ang > Math.PI / 2 || ang < -Math.PI / 2) ang += Math.PI;
    const label = cm(d);
    ctx.save();
    ctx.translate((ax + bx) / 2, (ay + by) / 2);
    ctx.rotate(ang);
    ctx.font = "500 12px Inter, sans-serif";
    const w = ctx.measureText(label).width + 14;
    ctx.fillStyle = "#2b2622";
    ctx.beginPath(); ctx.roundRect(-w / 2, -24, w, 20, 10); ctx.fill();
    ctx.fillStyle = "#f3eee5";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(label, 0, -14);
    ctx.restore();
  }

  function status() {
    clear.disabled = !done.length && !start;  // only when there is a measurement (or one under way) to clear
    xy.textContent = cursor ? `X ${cursor[0].toFixed(3)}  Y ${cursor[1].toFixed(3)} m` : "";
    const m = start && cursor ? [start, cursor] : done[done.length - 1];
    if (!m) { dist.textContent = ""; return; }
    const [a, b] = m;
    dist.textContent = `Distance ${cm(Math.hypot(b[0] - a[0], b[1] - a[1]))} · ΔX ${cm(Math.abs(b[0] - a[0]))} · ΔY ${cm(Math.abs(b[1] - a[1]))}`;
  }

  function pick(sx, sy, reach) {
    const p = target(sx, sy, reach);
    if (!start) start = p;
    else {
      if (Math.hypot(p[0] - start[0], p[1] - start[1]) > 1e-4) done.push([start, p]);
      start = null;
    }
    cursor = p;
  }

  // --- Pointer: drag pans (middle button always), wheel / pinch zooms, a click or tap picks ----
  const pointers = new Map();
  let press = null, lastMiddle = 0;
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
    if (pointers.size === 1) press = { x: e.clientX, y: e.clientY, button: e.button, moved: false };
    else press = null;  // a second finger: pinch, never a pick
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
      if (press.moved) { view.tx += e.clientX - prev[0]; view.ty += e.clientY - prev[1]; }
    }
    if (prev) pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (data && e.pointerType === "mouse") cursor = target(e.clientX, e.clientY, SNAP_PX.mouse);
    status();
    redraw();
  });
  const release = e => {
    if (!pointers.delete(e.pointerId)) return;
    if (e.type === "pointerup" && press && !press.moved && press.button === 0 && measuring && data) {
      pick(e.clientX, e.clientY, e.pointerType === "mouse" ? SNAP_PX.mouse : SNAP_PX.touch);
      status();
      redraw();
    }
    if (!pointers.size) press = null;
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") { cursor = start ? cursor : null; snap = null; redraw(); } });
  canvas.addEventListener("wheel", e => {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * (e.deltaMode ? 0.05 : 0.0015)));
    if (data) cursor = target(e.clientX, e.clientY, SNAP_PX.mouse);
    redraw();
  }, { passive: false });
  canvas.addEventListener("contextmenu", e => e.preventDefault());

  addEventListener("keydown", e => {
    if (!shown) return;
    if (e.key === "Shift") { shift = true; }
    else if (e.key === "Escape") { start = null; }
    else if (e.key === "Backspace" || e.key === "Delete") { start ? (start = null) : done.pop(); }
    else if (e.key === "F8") { e.preventDefault(); setOrtho(!ortho); }
    else return;
    status();
    redraw();
  });
  addEventListener("keyup", e => { if (e.key === "Shift") { shift = false; redraw(); } });

  const button = t => root.querySelector(`[data-tool=${t}]`);
  const setOrtho = on => (ortho = on);  // F8 (or hold Shift); no button
  button("measure").onclick = () => {
    measuring = !measuring;
    button("measure").classList.toggle("on", measuring);
    if (!measuring) start = null;
    status();
    redraw();
  };
  clear.onclick = () => { done.length = 0; start = null; status(); redraw(); };
  addEventListener("resize", () => shown && resize());

  return {
    async show() {
      shown = true;
      root.hidden = false;
      resize();
      if (!data) await load();
    },
    hide() { shown = false; root.hidden = true; shift = false; },
  };
}
