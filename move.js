// Move and Resize: the button beside Measure. Tap a piece (in Walk, Top or the 2D drawing) to pick it, drag it to
// move it, pull an edge / corner handle to resize it, or swing the round handle above it to turn it (15° steps, Shift
// for 1°; R turns it 90° clockwise, Shift+R anticlockwise). Nothing is saved while you adjust: the piece previews in
// place with its size and how far it moved, and Accept saves it (Cancel, Esc or a tap elsewhere throws the draft
// away). Accept sends one change to move_tool.py (POST api/edit-ai/transform, no AI model), which makes it in
// furnish.js and, when the piece is drawn on the plan, in the DXF, so the 3D and the 2D always agree; then the page
// reloads on the same view, like an Edit AI change, and Edit AI's Undo takes it back.
// In 3D a tap picks the whole piece; a double-tap on it goes one level in, to the named part under the pointer (the
// coffee bar's espresso machine, a TV-wall niche), like a group in Figma. The chips under it climb back out.
import * as THREE from "three";

const API = "api/edit-ai";
const DRAG_PX = 4, HANDLE_PX = 12, HANDLE_TOUCH_PX = 22, HEAD = 1.5, DOUBLE_MS = 400, DOUBLE_PX = 10, ROT_PX = 30;
const SIDES = { N: [0, 1], S: [0, -1], E: [1, 0], W: [-1, 0], NE: [1, 1], NW: [-1, 1], SE: [1, -1], SW: [-1, -1] };
const NAME = "Move and Resize";
const store = sessionStorage;
const r4 = v => Math.round(v * 10000) / 10000;
const cm = v => `${Math.round(Math.abs(v) * 100)} cm`;
const same = (a, b, tol = 0.003) => a.every((v, i) => Math.abs(v - b[i]) < tol);

export function createMove({ camera, renderer, scene, root, cutPlane, live, version, showing, mode, drawingFrame, drawingRoot,
  onChange, reload, freeMouse }) {
  const el = renderer.domElement;
  const overlay = document.createElement("div");
  overlay.className = "move-overlay";
  overlay.innerHTML = `<svg></svg><div class="move-label" hidden></div><div class="move-chips" hidden></div>`;
  document.body.appendChild(overlay);
  const svg = overlay.querySelector("svg"), label = overlay.querySelector(".move-label"), chips = overlay.querySelector(".move-chips");
  // Accept / Cancel for the draft: nothing is saved until Accept.
  const bar = Object.assign(document.createElement("div"), { id: "move-accept", className: "ui", hidden: true });
  bar.innerHTML = `<span class="what"></span><button class="cancel ghost">Cancel</button><button class="accept">Accept</button>`;
  document.body.appendChild(bar);
  for (const b of bar.querySelectorAll("button")) b.onpointerdown = e => e.stopPropagation();
  bar.querySelector(".accept").onclick = () => accept();
  bar.querySelector(".cancel").onclick = () => discard();
  const ray = new THREE.Raycaster();
  // sel: the picked object, its plan box, the pose it had (the draft previews over it) and the drill-in path
  // (outermost piece first). draft: the plan box it should get and how far it's turned (degrees, + = anticlockwise
  // on the plan, about the box's centre), until Accept or Cancel.
  let active = false, sel = null, drag = null, draft = null, busy = false, where = null, furnishText = null, lastDown = null;

  // --- What a piece is: its plan box, height, the code that placed it -------------------------------------------------
  const isPiece = o => o.userData.piece && o.parent === root;
  const isPart = o => o.userData.part && hostOf(o);
  const pickable = o => isPiece(o) || isPart(o);
  function hostOf(o) {
    for (let p = o.parent; p; p = p.parent) if (isPiece(p)) return p;
    return null;
  }
  // The pickable thing o sits in (a part's parent part, or its piece); null for a piece.
  function outerOf(o) {
    for (let p = o.parent; p && p !== root; p = p.parent) if (pickable(p)) return p;
    return null;
  }
  // Outermost first: the piece, then each part down to o.
  function pathTo(o) {
    const out = [];
    for (let p = o; p; p = outerOf(p)) out.unshift(p);
    return out;
  }
  function visible(o) {
    for (let p = o; p; p = p.parent) if (!p.visible) return false;
    return true;
  }
  function planBox(o) {
    const b = new THREE.Box3().setFromObject(o);
    return { box: [b.min.x, -b.max.z, b.max.x, -b.min.z], low: b.min.y, high: b.max.y };
  }
  // A piece with no name of its own: the comment on its furnish.js line, else what builds it (nightstand() -> "nightstand"),
  // else the comment on the line above (a loop's).
  function lineLabel(o) {
    if (!furnishText) return null;
    const L = furnishText.split("\n"), tidy = t => t.split(/[(:;,.]| - /)[0].trim().slice(0, 40) || null;
    const ns = o.userData.piece.lines || [];
    for (const n of ns) {
      const m = (L[n - 1] || "").match(/\/\/\s*(.+)$/);
      if (m && !/^(Move|---|local )/.test(m[1])) return tidy(m[1]);
    }
    for (const n of ns) {
      const m = (L[n - 1] || "").match(/item\([^,]+,[^,]+,\s*"[NSEW]",\s*(?:p\s*=>\s*)?([a-zA-Z]\w*)\(/);
      if (m && !/^(p|part)$/.test(m[1])) return m[1].replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
    }
    for (const n of ns) {
      const m = (L[n - 2] || "").match(/\/\/\s*(.+)$/);
      if (m && !/^(Move|---|local )/.test(m[1])) return tidy(m[1]);
    }
    return null;
  }
  function nameOf(o) {
    return o.userData.label || (isPiece(o) && lineLabel(o)) || "piece";
  }
  // Pieces placed with the same x, y, facing (move_tool.py can't tell them apart when no line of code is their own).
  const keyOf = p => `${+(+p.x).toFixed(4)},${+(+p.y).toFixed(4)},${p.facing}`;
  function twinsOf(item) {
    const k = keyOf(item.userData.piece);
    return root.children.filter(c => c.userData.piece && keyOf(c.userData.piece) === k).length;
  }
  function describe(o) {
    const host = isPart(o) ? hostOf(o) : null, item = host || o, pb = planBox(o);
    const d = {
      kind: host ? "part" : "item", label: nameOf(o), x: item.userData.piece.x, y: item.userData.piece.y,
      facing: item.userData.piece.facing, lines: item.userData.piece.lines, scale: [r4(item.scale.x), r4(item.scale.z)],
      box: pb.box.map(r4), low: r4(pb.low), high: r4(pb.high),
      hasParts: item.children.some(c => c.userData.part) && !host,
      anchor: [r4(item.position.x), r4(-item.position.z)], moved: !!item.userData.piece.moved, twins: twinsOf(item),
    };
    if (host) {
      Object.assign(d, { part: o.userData.label, pos: [r4(o.position.x), r4(o.position.z)], pscale: [r4(o.scale.x), r4(o.scale.z)],
        hostBox: planBox(host).box.map(r4), hostLabel: "the " + nameOf(host) });
      // A part inside another part: where its parent group sits in the piece's frame (move_tool.py works in that frame).
      if (o.parent !== host) {
        host.updateMatrixWorld(true);
        const m = new THREE.Matrix4().copy(host.matrixWorld).invert().multiply(o.parent.matrixWorld);
        const t = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
        m.decompose(t, q, s);
        d.frame = { pos: [r4(t.x), r4(t.z)], scale: [r4(s.x), r4(s.z)], turned: Math.abs(q.y) > 1e-3 || Math.abs(q.x) > 1e-3 || Math.abs(q.z) > 1e-3 };
      }
      if (o.userData.param) d.param = o.userData.param;  // a part drawn from numbers in its piece's code (a niche): those change
    }
    return d;
  }

  // --- Screen <-> plan ---------------------------------------------------------------------------------------------
  const is2D = () => showing() === "drawing";
  function toScreen(x, y, h) {
    if (is2D()) return drawingFrame().toScreen([x, y]);
    const v = new THREE.Vector3(x, h, -y).project(camera);
    if (v.z > 1) return null;
    const r = el.getBoundingClientRect();
    return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height];
  }
  function aim(sx, sy) {
    const r = el.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((sx - r.left) / r.width) * 2 - 1, -((sy - r.top) / r.height) * 2 + 1), camera);
  }
  function toPlan(sx, sy, h) {
    if (is2D()) return drawingFrame().toWorld(sx, sy);
    aim(sx, sy);
    const p = ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -h), new THREE.Vector3());
    return p && [p.x, -p.z];
  }

  // --- Picking ------------------------------------------------------------------------------------------------------
  // In 3D: what the pointer hits first (walls and all count, so nothing is picked through a wall), and the piece and
  // the parts it sits in. In 2D: the pieces whose plan box holds the point, smallest first; above head height only
  // when nothing at floor level is there.
  function pick3D(sx, sy) {
    aim(sx, sy);
    const targets = [];
    scene.traverse(o => o.isMesh && targets.push(o));
    const cut = cutPlane.constant < 999 ? cutPlane.constant : Infinity;
    for (const h of ray.intersectObjects(targets, false)) {
      if (!visible(h.object)) continue;
      const m = Array.isArray(h.object.material) ? h.object.material[0] : h.object.material;
      if (!m || m.visible === false || (m.transparent && m.opacity < 0.05)) continue;
      if (m.clippingPlanes?.length && h.point.y > cut + 1e-3) continue;
      const out = [];
      for (let p = h.object; p; p = p.parent) if (pickable(p)) out.push(p);
      return out;  // innermost first; [] when it's a wall or the floor
    }
    return [];
  }
  let all = null;
  function pick2D(sx, sy) {
    const [x, y] = drawingFrame().toWorld(sx, sy), tol = 4 / Math.max(1, Math.abs(drawingFrame().toScreen([1, 0])[0] - drawingFrame().toScreen([0, 0])[0]));
    if (!all) {
      all = [];
      root.traverse(o => pickable(o) && visible(o) && all.push(o));
    }
    const hits = all.map(o => ({ o, ...planBox(o) })).filter(c => c.box[0] - tol <= x && x <= c.box[2] + tol && c.box[1] - tol <= y && y <= c.box[3] + tol
      && (c.box[2] - c.box[0]) * (c.box[3] - c.box[1]) < 40);
    const low = hits.filter(c => c.low < HEAD);
    return (low.length ? low : hits).sort((a, b) => (a.box[2] - a.box[0]) * (a.box[3] - a.box[1]) - (b.box[2] - b.box[0]) * (b.box[3] - b.box[1])).map(c => c.o);
  }
  const pickAt = (sx, sy) => (is2D() ? pick2D(sx, sy) : pick3D(sx, sy));
  // A first tap: in 3D the whole piece (drill in for its parts); in 2D the smallest outline under the point.
  const firstPick = cands => (is2D() ? cands[0] : cands[cands.length - 1]);
  // A double tap on the selection: the next level in under the pointer.
  function drillTarget(cands) {
    const inner = cands.filter(c => outerOf(c) === sel.o);
    return inner.length ? inner[0] : null;
  }

  function select(o) {
    if (draft) discard(true);
    sel = o && { o, ...planBox(o), path: pathTo(o), pos0: o.position.clone(), scale0: o.scale.clone(), rot0: o.rotation.y };
    if (sel) sel.h = Math.min(sel.high, Math.max(sel.low, 0.9));
    showChips();
    onChange?.();
  }
  // Chips: the drill-in trail (Whole coffee bar › espresso machine) to climb back out, and the parts one level in.
  function showChips() {
    const parts = [];
    if (sel) sel.o.traverse(c => c !== sel.o && pickable(c) && outerOf(c) === sel.o && visible(c) && parts.push(c));
    const trail = sel ? sel.path : [];
    if (!sel || (trail.length < 2 && !parts.length)) return chips.replaceChildren();
    const chip = (c, text, cls) => {
      const b = document.createElement("button");
      b.textContent = text;
      b.className = cls;
      b.classList.toggle("on", c === sel.o);
      b.onpointerdown = e => e.stopPropagation();
      b.onclick = e => { e.stopPropagation(); select(c); };
      return b;
    };
    chips.replaceChildren(...trail.map((c, i) => chip(c, (i ? "› " : "Whole ") + nameOf(c), "crumb")),
      ...parts.slice(0, 6).map(c => chip(c, "+ " + nameOf(c), "part")));
  }

  // --- The draft: a preview in place, saved only on Accept -----------------------------------------------------------
  const shown = () => draft?.box || sel.box;
  const turn = () => draft?.rot || 0;
  // Only a whole piece turns (a part sits in its piece's frame).
  const turnable = () => sel && isPiece(sel.o) && !(draft && !same(sizeOf(draft.box), sizeOf(sel.box)));
  const sizeOf = b => [b[2] - b[0], b[3] - b[1]];
  // Plan points p turned by deg about c.
  function spin(ps, c, deg) {
    const t = deg * Math.PI / 180, co = Math.cos(t), si = Math.sin(t);
    return ps.map(([x, y]) => [c[0] + (x - c[0]) * co - (y - c[1]) * si, c[1] + (x - c[0]) * si + (y - c[1]) * co]);
  }
  // Put the selection where box says: scaled in its own frame (height untouched), then shifted so its plan box lines up.
  // Turned: swung round the centre of its plan box, then moved as far as the box moved.
  function preview(box, rot = 0) {
    const o = sel.o;
    o.position.copy(sel.pos0);
    o.scale.copy(sel.scale0);
    o.rotation.y = sel.rot0;
    if (!box) return;
    if (rot) {
      const b = sel.box, c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
      const w = o.parent.localToWorld(o.position.clone());
      const [[x, y]] = spin([[w.x, -w.z]], c, rot);
      w.set(x + (box[0] + box[2] - b[0] - b[2]) / 2, w.y, -(y + (box[1] + box[3] - b[1] - b[3]) / 2));
      o.position.copy(o.parent.worldToLocal(w));
      o.rotation.y = sel.rot0 + rot * Math.PI / 180;
      return;
    }
    const b = sel.box, k = [(box[2] - box[0]) / Math.max(1e-6, b[2] - b[0]), (box[3] - box[1]) / Math.max(1e-6, b[3] - b[1])];
    if (Math.abs(k[0] - 1) > 1e-4 || Math.abs(k[1] - 1) > 1e-4) {
      o.updateMatrixWorld(true);
      const ax = new THREE.Vector3(1, 0, 0).transformDirection(o.matrixWorld);  // the object's x along plan x or plan y
      const [kx, kz] = Math.abs(ax.x) >= Math.abs(ax.z) ? k : [k[1], k[0]];
      o.scale.x *= kx;
      o.scale.z *= kz;
    }
    o.updateMatrixWorld(true);
    const now = planBox(o).box;
    const shift = new THREE.Vector3((box[0] + box[2] - now[0] - now[2]) / 2, 0, -(box[1] + box[3] - now[1] - now[3]) / 2);
    const w = o.parent.localToWorld(o.position.clone()).add(shift);
    o.position.copy(o.parent.worldToLocal(w));
  }
  // What the draft does, in words: its size (and what it was), how far it moved.
  function draftText() {
    const b = sel.box, n = shown(), w = n[2] - n[0], d = n[3] - n[1];
    const size = `${Math.round(w * 100)} × ${Math.round(d * 100)} cm`;
    if (!draft) return `${nameOf(sel.o)} · ${size}`;
    if (draft.rot) {
      const c = [(n[0] + n[2] - b[0] - b[2]) / 2, (n[1] + n[3] - b[1] - b[3]) / 2], r = Math.round(draft.rot * 10) / 10;
      const moved = Math.abs(c[0]) >= 0.005 || Math.abs(c[1]) >= 0.005;
      return `${nameOf(sel.o)} · turned ${Math.abs(r)}° ${r > 0 ? "↺" : "↻"}${moved ? " · moved " + dirText(c) : ""}`;
    }
    const resized = !same([w, d], [b[2] - b[0], b[3] - b[1]]);
    const c = [(n[0] + n[2] - b[0] - b[2]) / 2, (n[1] + n[3] - b[1] - b[3]) / 2];
    const bits = [];
    if (resized) bits.push(`${size} (was ${Math.round((b[2] - b[0]) * 100)} × ${Math.round((b[3] - b[1]) * 100)})`);
    else bits.push(size);
    if (!resized && (Math.abs(c[0]) >= 0.005 || Math.abs(c[1]) >= 0.005)) bits.push("moved " + dirText(c));
    else if (resized) {
      const grew = sideText(b, n);
      if (grew) bits.push(grew);
    }
    return `${nameOf(sel.o)} · ${bits.join(" · ")}`;
  }
  const dirText = d => [Math.abs(d[0]) >= 0.005 && `${cm(d[0])} ${d[0] > 0 ? "E" : "W"}`, Math.abs(d[1]) >= 0.005 && `${cm(d[1])} ${d[1] > 0 ? "N" : "S"}`]
    .filter(Boolean).join(" · ") || "0 cm";
  function sideText(b, n) {
    const g = { N: n[3] - b[3], S: b[1] - n[1], E: n[2] - b[2], W: b[0] - n[0] };
    return Object.entries(g).filter(([, v]) => Math.abs(v) >= 0.005).map(([k, v]) => `${v > 0 ? "+" : "−"}${cm(v)} ${k}`).join(", ");
  }
  function setDraft(box, rot = turn()) {
    rot = ((rot % 360) + 540) % 360 - 180;  // -180..180
    if (Math.abs(rot) < 0.05) rot = 0;
    draft = same(box, sel.box, 0.0025) && !rot ? null : { box: box.map(r4), rot: Math.round(rot * 100) / 100 };
    preview(draft?.box, draft?.rot);
    bar.hidden = !draft;
    if (draft) bar.querySelector(".what").textContent = draftText();
    onChange?.();
  }
  // Cancel: back where it was, nothing saved. quiet: from a new selection (no need to redraw).
  function discard(quiet) {
    drag = null;
    if (sel) preview(null);
    draft = null;
    bar.hidden = true;
    if (!quiet) onChange?.();
  }

  // --- Overlay ----------------------------------------------------------------------------------------------------
  function corners(b, h, rot = 0) {
    const ps = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]];
    return (rot ? spin(ps, [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], rot) : ps).map(([x, y]) => toScreen(x, y, h));
  }
  // The turn handle: ROT_PX beyond the middle of the (turned) north side, on screen. [handle, side middle] or null.
  function rotHandle(b, h) {
    const c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], [m] = spin([[c[0], b[3]]], c, turn());
    const sc = toScreen(c[0], c[1], h), sm = toScreen(m[0], m[1], h);
    if (!sc || !sm) return null;
    const d = Math.hypot(sm[0] - sc[0], sm[1] - sc[1]) || 1;
    return [[sm[0] + (sm[0] - sc[0]) / d * ROT_PX, sm[1] + (sm[1] - sc[1]) / d * ROT_PX], sm];
  }
  function handles(b, h) {
    const mx = (b[0] + b[2]) / 2, my = (b[1] + b[3]) / 2, out = {};
    const at = { N: [mx, b[3]], S: [mx, b[1]], E: [b[2], my], W: [b[0], my], NE: [b[2], b[3]], NW: [b[0], b[3]], SE: [b[2], b[1]], SW: [b[0], b[1]] };
    for (const [k, [x, y]] of Object.entries(at)) out[k] = toScreen(x, y, h);
    return out;
  }
  function render() {
    const now = showing() + mode();
    if (where && now !== where && sel && !busy) { discard(); select(null); }
    where = now;
    if (!active || !sel || (showing() !== "model" && !is2D())) { svg.innerHTML = ""; label.hidden = true; chips.hidden = true; return; }
    const b = shown(), c = corners(b, sel.h, turn());
    if (c.some(p => !p)) { svg.innerHTML = ""; label.hidden = true; return; }
    const pts = c.map(p => p.join(",")).join(" ");
    let s = "";
    if (draft) s += `<polygon class="was" points="${corners(sel.box, sel.h).map(p => p?.join(",")).join(" ")}"/>`;
    s += `<polygon class="halo" points="${pts}"/><polygon points="${pts}"/>`;
    if (!busy && !turn()) for (const [k, p] of Object.entries(handles(b, sel.h))) s += `<circle class="${k.length > 1 ? "corner" : ""}" cx="${p[0]}" cy="${p[1]}" r="${k.length > 1 ? 5 : 6.5}"/>`;
    const rh = !busy && turnable() && rotHandle(b, sel.h);
    if (rh) s += `<line class="rot" x1="${rh[1][0]}" y1="${rh[1][1]}" x2="${rh[0][0]}" y2="${rh[0][1]}"/><circle class="rot" cx="${rh[0][0]}" cy="${rh[0][1]}" r="7"/>`;
    svg.innerHTML = s;
    label.hidden = false;
    label.style.left = `${(c[0][0] + c[2][0]) / 2}px`;
    label.style.top = `${Math.min(...c.map(p => p[1]))}px`;
    label.textContent = busy ? "Saving… (3D and plan)" : draftText();
    label.classList.toggle("draft", !!draft);
    chips.hidden = !chips.childElementCount || busy;
    chips.style.left = label.style.left;
    chips.style.top = `${Math.max(...c.map(p => p[1])) + 14}px`;
  }

  // --- Pointer: pick, drag, pull a handle, double-tap to drill in ------------------------------------------------------
  function inPoly(p, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  // The handle (N, SE, ...) or the body of the selection under p, or null.
  function grabAt(p, touch) {
    const b = shown(), c = corners(b, sel.h, turn());
    const rh = turnable() && rotHandle(b, sel.h);
    if (rh && Math.hypot(rh[0][0] - p[0], rh[0][1] - p[1]) < (touch ? HANDLE_TOUCH_PX : HANDLE_PX) + 2) return { type: "turn" };
    // A small piece on screen: the handles reach less far, so its middle still drags it.
    const side = c.some(q => !q) ? 0 : Math.min(...c.map((q, i) => Math.hypot(q[0] - c[(i + 1) % 4][0], q[1] - c[(i + 1) % 4][1])));
    const hs = handles(b, sel.h), r = Math.max(5, Math.min(touch ? HANDLE_TOUCH_PX : HANDLE_PX, side * 0.3));
    let best = r * r, grab = null;
    for (const [k, q] of Object.entries(hs)) {
      const d2 = q ? (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 : Infinity;
      if (d2 < best) { best = d2; grab = k; }
    }
    // A thin piece (a curtain, a panel): its middle is within reach of the side handles, so the middle drags it.
    const ctr = toScreen((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, sel.h);
    if (grab && ctr && (ctr[0] - p[0]) ** 2 + (ctr[1] - p[1]) ** 2 < best) grab = null;
    if (grab && !turn()) return { type: "edge", side: grab };
    grab = null;
    if (!c.some(q => !q) && inPoly(p, c)) return { type: "move" };
    if (!is2D() && pick3D(...p).includes(sel.o)) return { type: "move" };
    return null;
  }
  const pointers = new Set();
  function ours(e) {
    if (!active || busy) return false;
    if (showing() === "model") return e.target === el;
    return is2D() && e.target === drawingRoot.querySelector("canvas");
  }
  addEventListener("pointerdown", e => {
    if (!ours(e)) return;
    pointers.add(e.pointerId);
    if (pointers.size > 1) { cancelDrag(); return; }  // a second finger: pan / pinch / look as ever
    if (e.button !== 0) return;
    const p = [e.clientX, e.clientY], touch = e.pointerType !== "mouse", t = performance.now();
    const double = lastDown && t - lastDown.t < DOUBLE_MS && Math.hypot(p[0] - lastDown.p[0], p[1] - lastDown.p[1]) < DOUBLE_PX;
    lastDown = double ? null : { t, p };
    let g = null;
    if (sel && double && !draft) {  // double tap on the selection: one level in
      const inner = drillTarget(pickAt(...p));
      if (inner) {
        e.stopImmediatePropagation();
        e.preventDefault();
        select(inner);
        return;
      }
    }
    if (sel) g = grabAt(p, touch);
    if (!g) {
      const cands = pickAt(...p);
      if (draft) discard();  // a tap away from the draft throws it away
      if (!cands.length) { if (sel) select(null); return; }  // the floor / a wall: pan or look as ever
      const o = firstPick(cands);
      if (!sel || o !== sel.o) select(o);
      g = { type: "move" };
    }
    e.stopImmediatePropagation();
    e.preventDefault();
    freeMouse?.();
    const at = toPlan(...p, sel.h);
    if (!at) return;
    drag = { ...g, id: e.pointerId, from: p, at, base: [...shown()], rot: turn(), moved: false };
  }, true);
  addEventListener("pointermove", e => {
    if (!drag || e.pointerId !== drag.id) return;
    e.stopImmediatePropagation();
    if (!drag.moved && Math.hypot(e.clientX - drag.from[0], e.clientY - drag.from[1]) < DRAG_PX) return;
    drag.moved = true;
    const q = toPlan(e.clientX, e.clientY, sel.h);
    if (!q) return;
    const d = [Math.round((q[0] - drag.at[0]) * 200) / 200, Math.round((q[1] - drag.at[1]) * 200) / 200];  // 5 mm steps
    const b = drag.base;
    if (drag.type === "turn") {  // the angle the pointer swept round the centre, in 15° steps (Shift: 1°)
      const c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], a = v => Math.atan2(v[1] - c[1], v[0] - c[0]) * 180 / Math.PI;
      const step = e.shiftKey ? 1 : 15;
      setDraft(b, Math.round((drag.rot + a(q) - a(drag.at)) / step) * step);
    } else if (drag.type === "move") setDraft([b[0] + d[0], b[1] + d[1], b[2] + d[0], b[3] + d[1]]);
    else {
      const [sx, sy] = SIDES[drag.side], nb = [...b], MIN = 0.03;
      if (sx > 0) nb[2] = Math.max(b[0] + MIN, b[2] + d[0]);
      if (sx < 0) nb[0] = Math.min(b[2] - MIN, b[0] + d[0]);
      if (sy > 0) nb[3] = Math.max(b[1] + MIN, b[3] + d[1]);
      if (sy < 0) nb[1] = Math.min(b[3] - MIN, b[1] + d[1]);
      setDraft(nb);
    }
  }, true);
  // Letting go keeps the draft (nothing is saved): Accept saves it.
  const up = e => {
    pointers.delete(e.pointerId);
    if (!drag || e.pointerId !== drag.id) return;
    e.stopImmediatePropagation();
    const g = drag;
    drag = null;
    if (e.type === "pointercancel" && g.moved) setDraft(g.base, g.rot);
  };
  addEventListener("pointerup", up, true);
  addEventListener("pointercancel", up, true);
  function cancelDrag() {
    if (drag && sel) setDraft(drag.base, drag.rot);
    drag = null;
  }
  addEventListener("keydown", e => {
    if (!active || busy || /input|textarea/i.test(e.target?.tagName || "")) return;
    if (e.key === "Enter" && draft && !drag) { e.preventDefault(); accept(); return; }
    if ((e.key === "r" || e.key === "R") && !e.metaKey && !e.ctrlKey && !drag && turnable()) {  // 90° clockwise; Shift: anticlockwise
      e.preventDefault();
      setDraft([...shown()], turn() + (e.shiftKey ? 90 : -90));
      return;
    }
    if (e.key !== "Escape") return;
    if (drag) cancelDrag();
    else if (draft) discard();
    else if (sel?.path.length > 1) select(sel.path[sel.path.length - 2]);  // one level out
    else if (sel) select(null);
    else setActive(false);
  });

  // --- Saving (Accept) -------------------------------------------------------------------------------------------------
  async function call(action, body) {
    const r = await fetch(`${API}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({ error: `${r.status} ${r.statusText}` }));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  // The draft as the request move_tool.py takes: a move when the size is the same, else a resize to the new box.
  function request() {
    const b = sel.box, n = draft.box;
    const resized = !same([n[2] - n[0], n[3] - n[1]], [b[2] - b[0], b[3] - b[1]]);
    preview(null);  // describe the piece where it is, not where the preview put it
    const piece = describe(sel.o);
    preview(n, draft.rot);
    piece.box = b.map(r4);
    const body = { version, rev: live.rev, op: resized ? "resize" : "move", piece };
    if (resized) body.box = n.map(r4);
    else Object.assign(body, { dx: r4((n[0] + n[2] - b[0] - b[2]) / 2), dy: r4((n[1] + n[3] - b[1] - b[3]) / 2) }, draft.rot ? { rotate: draft.rot } : {});
    return body;
  }
  async function accept() {
    if (!draft || busy) return;
    const body = request();
    busy = true;
    bar.classList.add("busy");
    bar.querySelector(".what").textContent = "Saving… (3D and plan)";
    onChange?.();
    try {
      const res = await call("transform", body);
      store.setItem("move-applied", JSON.stringify({ version, text: res.summary, notes: res.notes || [] }));
      store.setItem("move-on", version);
      lastResult = res;
      reload();
    } catch (e) {
      busy = false;
      bar.classList.remove("busy");
      bar.querySelector(".what").textContent = draftText();
      toast(e.message, true);
      lastResult = { error: e.message };
      onChange?.();
    }
  }
  let lastResult = null;
  function toast(text, bad, undo) {
    document.getElementById("move-toast")?.remove();
    const t = Object.assign(document.createElement("div"), { id: "move-toast", className: "ui" + (bad ? " bad" : "") });
    t.append(Object.assign(document.createElement("span"), { textContent: text }));
    const btn = (txt, fn, ghost) => {
      const b = Object.assign(document.createElement("button"), { textContent: txt, className: ghost ? "ghost" : "" });
      b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { b.disabled = false; t.firstChild.textContent = e.message; } };
      t.append(b);
    };
    if (undo) btn("Undo", async () => {
      await call("undo", { version });
      store.setItem("move-applied", JSON.stringify({ version, text: "Undone.", undone: true }));
      store.setItem("move-on", version);
      reload();
    });
    btn("×", () => t.remove(), true);
    document.body.append(t);
    if (!bad && !undo) setTimeout(() => t.remove(), 4000);
  }

  // --- On / off ------------------------------------------------------------------------------------------------------
  function setActive(on) {
    if (on === active) return;
    active = on;
    if (!on) { discard(true); select(null); }
    else if (furnishText === null) {
      furnishText = "";
      fetch(live.url("furnish.js")).then(r => r.text()).then(t => (furnishText = t)).catch(() => {});
    }
    all = null;
    document.body.classList.toggle("moving", on);
    onChange?.();
  }
  const applied = JSON.parse(store.getItem("move-applied") || "null");
  store.removeItem("move-applied");
  if (applied?.version === version) {
    const text = applied.undone ? `${NAME}: undone.` : `${applied.text}.${applied.notes?.length ? " Note: " + applied.notes.join("; ") + "." : ""}`;
    setTimeout(() => toast(text, false, !applied.undone), 600);
  }
  const resume = store.getItem("move-on") === version;
  store.removeItem("move-on");

  // For the tests (index.html exposes this as window.__move with ?debug).
  function find(x, y, part) {
    let found = null;
    root.traverse(o => { if (!found && isPiece(o) && Math.abs(o.userData.piece.x - x) < 0.002 && Math.abs(o.userData.piece.y - y) < 0.002) found = o; });
    if (found && part) {
      let p = null;
      found.traverse(o => { if (!p && o.userData.part && o.userData.label === part) p = o; });
      found = p;
    }
    return found;
  }
  return {
    get active() { return active; }, get selected() { return sel && describe(sel.o); }, get busy() { return busy; },
    get pending() { return !!draft; },
    setActive, render, resume,
    debugSelect(x, y, part) {
      const o = find(x, y, part);
      if (o) select(o);
      return o && describe(o);
    },
    debugList() {
      const out = [];
      root.traverse(o => pickable(o) && visible(o) && out.push({ ...describe(o), depth: pathTo(o).length }));
      return out;
    },
    async ready() {
      if (furnishText === null) { setActive(true); setActive(false); }
      for (let i = 0; i < 100 && !furnishText; i++) await new Promise(r => setTimeout(r, 100));
      return !!furnishText;
    },
    state() {
      return {
        active, busy, selected: sel && nameOf(sel.o), path: sel ? sel.path.map(nameOf) : [], box: sel && sel.box.map(r4),
        draft: draft && draft.box, rot: turn(), text: sel && draftText(), bar: !bar.hidden, chips: [...chips.querySelectorAll("button")].map(b => b.textContent),
        request: draft && sel ? request() : null, result: lastResult,
      };
    },
    // The live box of an object at (x, y) [part], as the scene has it now (to check a preview or a reload).
    boxOf(x, y, part) { const o = find(x, y, part); return o && planBox(o).box.map(r4); },
    // The box of the piece (or the part named `part`) whose plan box centre is nearest (x, y): a moved piece's item(x, y) changes.
    boxNear(x, y, part) {
      let best = null, bd = Infinity;
      root.traverse(o => {
        if (!(part ? o.userData.part && o.userData.label === part : isPiece(o)) || !visible(o)) return;
        const b = planBox(o).box, d = Math.hypot((b[0] + b[2]) / 2 - x, (b[1] + b[3]) / 2 - y);
        if (d < bd) { bd = d; best = b; }
      });
      return best && best.map(r4);
    },
    screenOf(x, y, h) { return toScreen(x, y, h ?? sel?.h ?? 0.5); },
    accept, discard: () => discard(),
  };
}
