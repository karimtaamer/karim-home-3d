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
  bar.querySelector(".accept").onclick = () => (pel ? acceptPlan() : accept());
  bar.querySelector(".cancel").onclick = () => (pel ? setPlanDraft(null) : discard());
  const ray = new THREE.Raycaster();
  // sel: the picked object, its plan box, the pose it had (the draft previews over it) and the drill-in path
  // (outermost piece first). draft: the plan box it should get and how far it's turned (degrees, + = anticlockwise
  // on the plan, about the box's centre) and its height span z = [low, high] (m; null: as it is), until Accept or Cancel.
  let active = false, sel = null, drag = null, draft = null, busy = false, where = null, furnishText = null, lastDown = null;
  // Like AutoCAD's ortho: "x" / "y" keeps a drag on that plan axis (X / Y keys toggle it; holding Shift locks a drag to
  // whichever axis it mostly runs along). A draft with del: true deletes the piece on Accept (Delete / Backspace).
  let axis = null, under = [];

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
  function describe(o, near = true) {  // near: the neighbours' plan boxes too (only a request needs them)
    const host = isPart(o) ? hostOf(o) : null, item = host || o, pb = planBox(o);
    const d = {
      kind: host ? "part" : "item", label: nameOf(o), x: item.userData.piece.x, y: item.userData.piece.y,
      facing: item.userData.piece.facing, lines: item.userData.piece.lines, scale: [r4(item.scale.x), r4(item.scale.z)],
      box: pb.box.map(r4), low: r4(pb.low), high: r4(pb.high),
      hasParts: item.children.some(c => c.userData.part) && !host,
      anchor: [r4(item.position.x), r4(-item.position.z)], moved: !!item.userData.piece.moved, twins: twinsOf(item), twin: item.userData.piece.twin || 0,
      rot: r4(o.rotation.y),
      sy: r4(item.scale.y), py: r4(item.position.y),  // its height frame: world height = py + sy · its own
      // the plan boxes of the floor pieces round it: plan lines inside a smaller one are that piece's, not this one's
      others: !near ? [] : root.children.filter(c => c !== item && c.userData.piece && visible(c)).map(planBox)
        .filter(c => c.low < HEAD && c.box[0] < pb.box[2] + 0.3 && c.box[2] > pb.box[0] - 0.3 && c.box[1] < pb.box[3] + 0.3 && c.box[3] > pb.box[1] - 0.3)
        .map(c => c.box.map(r4)),
    };
    if (host) {
      Object.assign(d, { part: o.userData.label, pos: [r4(o.position.x), r4(o.position.z)], pscale: [r4(o.scale.x), r4(o.scale.z)],
        posY: r4(o.position.y), pscaleY: r4(o.scale.y),
        hostBox: planBox(host).box.map(r4), hostLabel: "the " + nameOf(host) });
      // A part inside another part: where its parent group sits in the piece's frame (move_tool.py works in that frame).
      if (o.parent !== host) {
        host.updateMatrixWorld(true);
        const m = new THREE.Matrix4().copy(host.matrixWorld).invert().multiply(o.parent.matrixWorld);
        const t = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
        m.decompose(t, q, s);
        d.frame = { pos: [r4(t.x), r4(t.z)], scale: [r4(s.x), r4(s.z)], posY: r4(t.y), scaleY: r4(s.y), turned: Math.abs(q.y) > 1e-3 || Math.abs(q.x) > 1e-3 || Math.abs(q.z) > 1e-3 };
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
    // what stands on the floor first (it's what the plan draws; a pendant light hangs over the nightstand), then the rest
    // below head height, then above it; smallest first within each. Tab cycles through them (see the keys below).
    const tier = c => (c.low < 0.3 ? 0 : c.low < HEAD ? 1 : 2), size = c => (c.box[2] - c.box[0]) * (c.box[3] - c.box[1]);
    return hits.sort((a, b) => tier(a) - tier(b) || size(a) - size(b)).map(c => c.o);
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
    group = [];
    if (pel) { pel = pdraft = null; bar.hidden = true; }
    sel = o && { o, ...planBox(o), path: pathTo(o), pos0: o.position.clone(), scale0: o.scale.clone(), rot0: o.rotation.y };
    if (sel) sel.first = firstOf(nameOf(o), sel.box) || { box: sel.box, rot: sel.rot0 };
    if (sel) sel.h = Math.min(sel.high, Math.max(sel.low, 0.9));
    showChips();
    onChange?.();
  }
  // Chips: the drill-in trail (Whole coffee bar › espresso machine) to climb back out, and the parts one level in.
  function showChips() {
    const parts = [];
    if (sel) sel.o.traverse(c => c !== sel.o && pickable(c) && outerOf(c) === sel.o && visible(c) && parts.push(c));
    const trail = sel ? sel.path : [];
    if (!sel) return chips.replaceChildren();
    const del = Object.assign(document.createElement("button"), { textContent: "Delete", className: "del", title: "Delete (Del): Accept removes it from the 3D and the plan" });
    del.onpointerdown = e => e.stopPropagation();
    del.onclick = e => { e.stopPropagation(); markDelete(); };
    if (trail.length < 2 && !parts.length) return chips.replaceChildren(del);
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
      ...parts.slice(0, 6).map(c => chip(c, "+ " + nameOf(c), "part")), del);
  }

  // --- A group: Shift-click adds a piece to the selection or takes it out (AutoCAD / Figma). The group moves, nudges and
  // deletes together and saves as one change (one Undo); resizing and turning stay one piece at a time.
  let group = [];
  function toggleMember(o) {
    o = o && (isPiece(o) ? o : hostOf(o));
    if (!sel || !o || !isPiece(sel.o) || o === sel.o) return false;
    if (draft) discard(true);
    const i = group.findIndex(m => m.o === o);
    if (i >= 0) group.splice(i, 1);
    else group.push({ o, ...planBox(o), pos0: o.position.clone() });
    onChange?.();
    return true;
  }
  // The draft's shift of the selection's box, put on every member (hidden for a delete); no draft: back where they were.
  const groupShift = () => {
    const b = sel.box, n = draft && !draft.del ? draft.box : b;
    return [(n[0] + n[2] - b[0] - b[2]) / 2, (n[1] + n[3] - b[1] - b[3]) / 2];
  };
  function previewGroup() {
    const [dx, dy] = groupShift();
    for (const m of group) {
      m.o.visible = !draft?.del;
      const w = m.o.parent.localToWorld(m.pos0.clone()).add(new THREE.Vector3(dx, 0, -dy));
      m.o.position.copy(m.o.parent.worldToLocal(w));
    }
  }
  const memberBox = m => { const [dx, dy] = groupShift(); return [m.box[0] + dx, m.box[1] + dy, m.box[2] + dx, m.box[3] + dy]; };
  const inGroup = p => group.some(m => { const c = corners(memberBox(m), hNow()); return !c.some(q => !q) && inPoly(p, c); });

  // --- Where a piece started: its box and turn before its first Accept (move_tool.py keeps move-origins-<v>.json) -----
  let origins = [];
  function loadOrigins() {
    const f = `move-origins-${version === "main" ? "kareems-changes" : version}.json`;
    fetch(live.url(f), { cache: "no-store" }).then(r => (r.ok ? r.json() : [])).then(j => (origins = Array.isArray(j) ? j : [])).catch(() => {});
  }
  // The entry for the piece with this label whose box is now centred within 5 cm of b's centre (as move_tool.py finds it).
  function firstOf(name, b) {
    const c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
    let best = null, bd = 0.05;
    for (const e of origins) {
      const d = Math.hypot(e.at[0] - c[0], e.at[1] - c[1]);
      if (e.label === name && d <= bd) { best = e; bd = d; }
    }
    return best;
  }

  // --- The draft: a preview in place, saved only on Accept -----------------------------------------------------------
  const shown = () => draft?.box || sel.box;
  const turn = () => draft?.rot || 0;
  const heightNow = () => draft?.z || [sel.low, sel.high];
  // The height the overlay is drawn at: the piece's own, carried up or down with a lift.
  const hNow = () => sel.h + heightNow()[0] - sel.low;
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
  function preview(box, rot = 0, z = null) {
    const o = sel.o;
    o.position.copy(sel.pos0);
    o.scale.copy(sel.scale0);
    o.rotation.y = sel.rot0;
    if (!box) return;
    if (z) lift(o, z);
    if (rot) {
      const b = sel.box, c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
      const w = o.parent.localToWorld(o.position.clone());
      const [[x, y]] = spin([[w.x, -w.z]], c, rot);
      w.set(x + (box[0] + box[2] - b[0] - b[2]) / 2, w.y, -(y + (box[1] + box[3] - b[1] - b[3]) / 2));
      o.position.copy(o.parent.worldToLocal(w));
      o.rotation.y = sel.rot0 + rot * Math.PI / 180;
      return;
    }
    plan(o, box);
  }
  // Its height to z = [low, high]: scaled from its base, then raised or lowered so its lowest point is at z[0].
  function lift(o, z) {
    const k = (z[1] - z[0]) / Math.max(1e-6, sel.high - sel.low);
    if (Math.abs(k - 1) > 1e-4) o.scale.y *= k;
    o.updateMatrixWorld(true);
    const w = o.parent.localToWorld(o.position.clone());
    w.y += z[0] - planBox(o).low;
    o.position.copy(o.parent.worldToLocal(w));
  }
  function plan(o, box) {
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
  // What the piece / draft is, in words: its size (and what it was), how far it has moved and turned since it started
  // (its first position, not the last Accept).
  function draftText() {
    let b = sel.first.box;
    const n = shown(), w = n[2] - n[0], d = n[3] - n[1];
    const size = `${Math.round(w * 100)} × ${Math.round(d * 100)} cm`;
    const r = Math.round((((turn() + (sel.rot0 - sel.first.rot) * 180 / Math.PI) % 360 + 540) % 360 - 180) * 10) / 10;
    if (r && !(draft && !same(sizeOf(n), sizeOf(sel.box)))) {
      const c = [(n[0] + n[2] - b[0] - b[2]) / 2, (n[1] + n[3] - b[1] - b[3]) / 2];
      const moved = Math.abs(c[0]) >= 0.005 || Math.abs(c[1]) >= 0.005;
      return `${nameOf(sel.o)} · turned ${Math.abs(r)}° ${r > 0 ? "↺" : "↻"}${moved ? " · moved " + dirText(c) : ""}${heightText()}`;
    }
    if (r) b = sel.box;  // a turned piece being resized: its size against how it stands now
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
    return `${nameOf(sel.o)} · ${bits.join(" · ")}${heightText()}`;
  }
  // Its height against where it started: " · 85 cm tall (was 75)" or " · 10 cm up"; "" when it's as it was.
  function heightText() {
    const z0 = sel.first.z || [sel.low, sel.high], z = heightNow(), t = z[1] - z[0], t0 = z0[1] - z0[0];
    if (Math.abs(t - t0) >= 0.005) return ` · ${Math.round(t * 100)} cm tall (was ${Math.round(t0 * 100)})`;
    return Math.abs(z[0] - z0[0]) >= 0.005 ? ` · ${cm(z[0] - z0[0])} ${z[0] > z0[0] ? "up" : "down"}` : "";
  }
  const dirText = d => [Math.abs(d[0]) >= 0.005 && `${cm(d[0])} ${d[0] > 0 ? "E" : "W"}`, Math.abs(d[1]) >= 0.005 && `${cm(d[1])} ${d[1] > 0 ? "N" : "S"}`]
    .filter(Boolean).join(" · ") || "0 cm";
  function sideText(b, n) {
    const g = { N: n[3] - b[3], S: b[1] - n[1], E: n[2] - b[2], W: b[0] - n[0] };
    return Object.entries(g).filter(([, v]) => Math.abs(v) >= 0.005).map(([k, v]) => `${v > 0 ? "+" : "−"}${cm(v)} ${k}`).join(", ");
  }
  function setDraft(box, rot = turn(), z = draft?.z || null) {
    rot = ((rot % 360) + 540) % 360 - 180;  // -180..180
    if (Math.abs(rot) < 0.05) rot = 0;
    if (z && same(z, [sel.low, sel.high], 0.0025)) z = null;
    draft = same(box, sel.box, 0.0025) && !rot && !z ? null : { box: box.map(r4), rot: Math.round(rot * 100) / 100, z: z && z.map(r4) };
    preview(draft?.box, draft?.rot, draft?.z);
    bar.hidden = !draft;
    if (draft) bar.querySelector(".what").textContent = draftText();
    if (group.length) previewGroup();
    onChange?.();
  }
  // Cancel: back where it was, nothing saved. quiet: from a new selection (no need to redraw).
  function discard(quiet) {
    drag = null;
    if (sel) sel.o.visible = true;  // a delete draft hid it
    if (sel) preview(null);
    draft = null;
    if (group.length) previewGroup();
    bar.hidden = true;
    if (!quiet) onChange?.();
  }
  // Delete: a draft like any other; the piece hides until Accept deletes it (Cancel, Esc or a tap brings it back).
  function markDelete() {
    if (!sel || busy) return;
    if (draft) discard(true);
    draft = { box: [...sel.box], rot: 0, z: null, del: true };
    sel.o.visible = false;
    if (group.length) previewGroup();
    bar.hidden = false;
    bar.querySelector(".what").textContent = group.length ? `Delete these ${group.length + 1} pieces?` : `Delete the ${nameOf(sel.o)}?`;
    onChange?.();
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
  // The height handles, in Walk only (Top and the drawing look straight down: PageUp / PageDown there): a stalk up from
  // the middle of the box to its top, a square there to make it taller or shorter, and a dot above that to raise or
  // lower it. u: the screen direction of "up" there, px: screen pixels per metre up.
  function zHandles(b) {
    if (is2D() || mode() !== "walk") return null;
    const c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], z = heightNow();
    const base = toScreen(c[0], c[1], hNow()), top = toScreen(c[0], c[1], z[1]), up = toScreen(c[0], c[1], z[1] + 1);
    if (!base || !top || !up) return null;
    const px = Math.hypot(up[0] - top[0], up[1] - top[1]);
    if (px < 20) return null;
    const u = [(up[0] - top[0]) / px, (up[1] - top[1]) / px];
    // a low piece seen from above: its top is its middle on screen, so the square sits a little above it
    const lift = Math.hypot(top[0] - base[0], top[1] - base[1]) < 24 ? 24 : 0;
    const size = [top[0] + u[0] * lift, top[1] + u[1] * lift];
    return { base, size, lift: [size[0] + u[0] * ROT_PX, size[1] + u[1] * ROT_PX], u, px };
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
    if (pel) return renderPlan();
    if (!active || !sel || (showing() !== "model" && !is2D())) { svg.innerHTML = ""; label.hidden = true; chips.hidden = true; return; }
    const b = shown(), c = corners(b, hNow(), turn());
    if (c.some(p => !p)) { svg.innerHTML = ""; label.hidden = true; return; }
    const pts = c.map(p => p.join(",")).join(" ");
    let s = "";
    if (draft) s += `<polygon class="was" points="${corners(sel.box, sel.h).map(p => p?.join(",")).join(" ")}"/>`;
    s += `<polygon class="halo" points="${pts}"/><polygon points="${pts}"/>`;
    for (const m of group) {
      const mc = corners(memberBox(m), hNow());
      if (!mc.some(q => !q)) s += `<polygon class="halo" points="${mc.map(q => q.join(",")).join(" ")}"/><polygon points="${mc.map(q => q.join(",")).join(" ")}"/>`;
    }
    if (!busy && !turn() && !group.length) for (const [k, p] of Object.entries(handles(b, hNow()))) s += `<circle class="${k.length > 1 ? "corner" : ""}" cx="${p[0]}" cy="${p[1]}" r="${k.length > 1 ? 5 : 6.5}"/>`;
    const rh = !busy && !group.length && turnable() && rotHandle(b, hNow());
    if (rh) s += `<line class="rot" x1="${rh[1][0]}" y1="${rh[1][1]}" x2="${rh[0][0]}" y2="${rh[0][1]}"/><circle class="rot" cx="${rh[0][0]}" cy="${rh[0][1]}" r="7"/>`;
    const zh = !busy && !group.length && zHandles(b);  // heights: one piece at a time
    if (zh) s += `<line class="z" x1="${zh.base[0]}" y1="${zh.base[1]}" x2="${zh.lift[0]}" y2="${zh.lift[1]}"/>`
      + `<rect class="z" x="${zh.size[0] - 5.5}" y="${zh.size[1] - 5.5}" width="11" height="11"/><circle class="z" cx="${zh.lift[0]}" cy="${zh.lift[1]}" r="7"/>`;
    svg.innerHTML = s;
    label.hidden = false;
    label.style.left = `${(c[0][0] + c[2][0]) / 2}px`;
    label.style.top = `${Math.min(...c.map(p => p[1]))}px`;
    const many = group.length && `${group.length + 1} pieces`, d = group.length && groupShift();
    label.textContent = busy ? "Saving… (3D and plan)" : draft?.del ? `Delete ${many ? "these " + many : "the " + nameOf(sel.o)}? Accept deletes ${many ? "them" : "it"} (3D and plan)`
      : (many ? `${many} · ${Math.abs(d[0]) >= 0.005 || Math.abs(d[1]) >= 0.005 ? "moved " + dirText(d) : "Shift-click adds or drops one"}` : draftText())
        + (axis ? ` · ${axis.toUpperCase()} only` : "");
    label.classList.toggle("draft", !!draft);
    chips.hidden = !chips.childElementCount || busy;
    chips.style.left = label.style.left;
    chips.style.top = `${Math.max(...c.map(p => p[1])) + 14}px`;
  }

  // --- Walls, doors and windows on the drawing (like AutoCAD): a tap with no piece under it picks the wall, door or
  // window there. A wall drags across itself (the walls meeting it follow); a door or window slides along its wall and
  // its end dots pull it wider or narrower; Delete removes the wall or walls the opening up; arrows nudge 1 cm (Shift
  // 10). Accept changes the plan and the 3D is rebuilt from it (move_tool.py plan_element): no 3D preview before that.
  let pel = null, pdraft = null, pdrag = null;  // the picked wall / opening; its draft {s: m along, w: width, del}
  const NAMES = { window: "Window", slider: "Glass slider", door: "Door" };
  function planHit(x, y, tol) {
    const M = globalThis.MODEL || {};
    for (const o of M.openings || []) {
      const xs = o.outer.map(q => q[0]), ys = o.outer.map(q => q[1]);
      const box = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
      if (box[0] - tol <= x && x <= box[2] + tol && box[1] - tol <= y && y <= box[3] + tol) {
        const u = box[2] - box[0] >= box[3] - box[1] ? [1, 0] : [0, 1];
        return { type: "opening", kind: o.kind, box: box.map(r4), at: [r4((box[0] + box[2]) / 2), r4((box[1] + box[3]) / 2)], u };
      }
    }
    for (const w of M.walls || []) {
      if (!inPoly([x, y], w.outer) || (w.holes || []).some(h => inPoly([x, y], h))) continue;
      let best = null;  // its direction: the wall face nearest the point
      for (const ring of [w.outer, ...(w.holes || [])]) for (let i = 0; i < ring.length; i++) {
        const a = ring[i], b = ring[(i + 1) % ring.length], L = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (L < 0.05) continue;
        const t = Math.max(0, Math.min(1, ((x - a[0]) * (b[0] - a[0]) + (y - a[1]) * (b[1] - a[1])) / (L * L)));
        const d = Math.hypot(a[0] + t * (b[0] - a[0]) - x, a[1] + t * (b[1] - a[1]) - y);
        if (!best || d < best.d) best = { d, u: [(b[0] - a[0]) / L, (b[1] - a[1]) / L] };
      }
      const u = best ? best.u : [1, 0];
      return { type: "wall", at: [r4(x), r4(y)], u, n: [-u[1], u[0]], run: null };
    }
    return null;
  }
  function planSelect(hit) {
    pel = hit;
    pdraft = null;
    bar.hidden = true;
    if (!hit) return onChange?.(), null;
    const del = Object.assign(document.createElement("button"), { textContent: "Delete", className: "del" });
    del.onpointerdown = e => e.stopPropagation();
    del.onclick = e => { e.stopPropagation(); setPlanDraft({ del: true }); };
    chips.replaceChildren(del);
    if (hit.type === "wall")  // its run (ends, thickness) from the plan, to draw it whole
      call("transform", { version, op: "wall", at: hit.at, info: true }).then(r => {
        if (pel !== hit) return;
        const L = Math.hypot(r.b[0] - r.a[0], r.b[1] - r.a[1]) || 1, u = [(r.b[0] - r.a[0]) / L, (r.b[1] - r.a[1]) / L];
        if (!pdraft) Object.assign(hit, { u, n: [-u[1], u[0]] });
        hit.run = r;
        onChange?.();
      }).catch(() => {});
    onChange?.();
    return hit;
  }
  // A tap on the drawing with no piece under it: the wall / opening there, and a press-drag starts moving it at once.
  function planPick(e, p) {
    const f = drawingFrame(), [x, y] = f.toWorld(...p), tol = 4 / Math.max(1, Math.abs(f.toScreen([1, 0])[0] - f.toScreen([0, 0])[0]));
    const hit = planHit(x, y, tol);
    if (!hit) { if (pel) planSelect(null); return false; }
    planSelect(hit);
    e.stopImmediatePropagation();
    e.preventDefault();
    pdrag = { id: e.pointerId, type: "move", from: p, at: [x, y], base: { ...(pdraft || {}) }, moved: false };
    return true;
  }
  const along = () => (pel.type === "wall" ? pel.n : pel.u);
  function planShape(d = pdraft) {
    const s = d?.s || 0;
    if (pel.type === "opening") {
      const b = pel.box, al = pel.u[0] ? 0 : 1, w0 = b[al + 2] - b[al], w = d?.w ?? w0, c = (b[al] + b[al + 2]) / 2 + s, nb = [...b];
      nb[al] = c - w / 2;
      nb[al + 2] = c + w / 2;
      return [[nb[0], nb[1]], [nb[2], nb[1]], [nb[2], nb[3]], [nb[0], nb[3]]];
    }
    const r = pel.run, n = pel.n, o = [n[0] * s, n[1] * s];
    const [a, b, h] = r ? [r.a, r.b, r.thickness / 2] : [[pel.at[0] - pel.u[0] * 0.2, pel.at[1] - pel.u[1] * 0.2], [pel.at[0] + pel.u[0] * 0.2, pel.at[1] + pel.u[1] * 0.2], 0.06];
    return [[a[0] + n[0] * h, a[1] + n[1] * h], [b[0] + n[0] * h, b[1] + n[1] * h], [b[0] - n[0] * h, b[1] - n[1] * h], [a[0] - n[0] * h, a[1] - n[1] * h]]
      .map(([x, y]) => [x + o[0], y + o[1]]);
  }
  // An opening's two end dots (to make it wider or narrower), on the plan.
  function planEnds() {
    if (pel.type !== "opening" || pdraft?.del) return [];
    const q = planShape(), al = pel.u[0] ? 0 : 1, mid = (i, j) => [(q[i][0] + q[j][0]) / 2, (q[i][1] + q[j][1]) / 2];
    return al === 0 ? [mid(0, 3), mid(1, 2)] : [mid(0, 1), mid(2, 3)];
  }
  function planText() {
    if (!pel) return "";
    const s = pdraft?.s || 0, dir = v => (pel.type === "wall" ? (Math.abs(pel.n[0]) > Math.abs(pel.n[1]) ? (v * pel.n[0] > 0 ? "E" : "W") : (v * pel.n[1] > 0 ? "N" : "S"))
      : pel.u[0] ? (v > 0 ? "E" : "W") : (v > 0 ? "N" : "S"));
    if (pel.type === "wall") {
      const r = pel.run, L = r ? Math.hypot(r.b[0] - r.a[0], r.b[1] - r.a[1]) : 0;
      if (pdraft?.del) return "Remove this wall? Accept removes it with its doors and windows (plan and 3D)";
      return `Wall${r ? ` · ${Math.round(L * 100)} cm long · ${Math.round(r.thickness * 100)} cm thick` : ""}${Math.abs(s) >= 0.005 ? ` · moved ${cm(s)} ${dir(s)}` : " · drag it across"}`;
    }
    const name = NAMES[pel.kind] || "Opening", b = pel.box, al = pel.u[0] ? 0 : 1, w0 = b[al + 2] - b[al], w = pdraft?.w ?? w0;
    if (pdraft?.del) return `Wall up this ${name.toLowerCase()}? Accept fills it with wall (plan and 3D)`;
    return `${name} · ${Math.round(w * 100)} cm wide${Math.abs(w - w0) >= 0.005 ? ` (was ${Math.round(w0 * 100)})` : ""}${Math.abs(s) >= 0.005 ? ` · moved ${cm(s)} ${dir(s)}` : ""}`;
  }
  function setPlanDraft(d) {
    if (d && !d.del) {
      d.s = Math.round((d.s || 0) * 1000) / 1000;
      if (d.w != null) d.w = Math.round(Math.max(0.3, d.w) * 1000) / 1000;
      const b = pel.box, w0 = b && b[(pel.u[0] ? 0 : 1) + 2] - b[pel.u[0] ? 0 : 1];
      if (Math.abs(d.s) < 0.001 && (d.w == null || Math.abs(d.w - w0) < 0.001)) d = null;
    }
    pdraft = d;
    bar.hidden = !pdraft;
    if (pdraft) bar.querySelector(".what").textContent = planText();
    onChange?.();
  }
  function renderPlan() {
    if (!active || !is2D()) { planSelect(null); svg.innerHTML = ""; label.hidden = true; chips.hidden = true; return; }
    const sc = q => toScreen(q[0], q[1], 0), pts = q => q.map(sc).map(v => v.join(",")).join(" ");
    let h = pdraft ? `<polygon class="was" points="${pts(planShape(null))}"/>` : "";
    const now = planShape();
    if (!pdraft?.del) h += `<polygon class="halo" points="${pts(now)}"/><polygon points="${pts(now)}"/>`;
    for (const q of planEnds()) { const v = sc(q); h += `<circle cx="${v[0]}" cy="${v[1]}" r="6.5"/>`; }
    svg.innerHTML = h;
    const c = now.map(sc);
    label.hidden = false;
    label.textContent = busy ? "Saving… (plan, then 3D)" : planText();
    label.classList.toggle("draft", !!pdraft);
    label.style.left = `${(Math.min(...c.map(v => v[0])) + Math.max(...c.map(v => v[0]))) / 2}px`;
    label.style.top = `${Math.min(...c.map(v => v[1]))}px`;
    chips.hidden = busy;
    chips.style.left = label.style.left;
    chips.style.top = `${Math.max(...c.map(v => v[1])) + 14}px`;
  }
  function planKey(e) {
    const k = e.key, stop = () => { e.preventDefault(); e.stopImmediatePropagation(); };
    if (k === "Escape") { stop(); return pdraft ? setPlanDraft(null) : planSelect(null); }
    if (k === "Enter" && pdraft) { stop(); return acceptPlan(); }
    if (k === "Delete" || k === "Backspace") { stop(); return setPlanDraft({ del: true }); }
    const v = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[k];
    if (!v || pdraft?.del) return;
    stop();
    const a = along(), dot = v[0] * a[0] + v[1] * a[1];
    if (Math.abs(dot) < 0.5) return;  // across a door's wall / along a wall: nothing to nudge
    setPlanDraft({ ...(pdraft || {}), s: (pdraft?.s || 0) + Math.sign(dot) * (e.shiftKey ? 0.1 : 0.01) });
  }
  addEventListener("pointerdown", e => {  // ahead of the piece picking below: a press on the picked wall / opening drags it
    if (!pel || !ours(e) || e.button !== 0) return;
    const p = [e.clientX, e.clientY], r = (e.pointerType !== "mouse" ? HANDLE_TOUCH_PX : HANDLE_PX) + 2;
    const end = planEnds().findIndex(q => { const v = toScreen(q[0], q[1], 0); return Math.hypot(v[0] - p[0], v[1] - p[1]) < r; });
    const on = end >= 0 || (!pdraft?.del && inPoly(p, planShape().map(q => toScreen(q[0], q[1], 0))));
    if (!on) { planSelect(null); return; }  // elsewhere: let the piece picking have it
    e.stopImmediatePropagation();
    e.preventDefault();
    pdrag = { id: e.pointerId, type: end >= 0 ? `end${end}` : "move", from: p, at: drawingFrame().toWorld(...p), base: { ...(pdraft || {}) }, moved: false };
  }, true);
  addEventListener("pointermove", e => {
    if (!pdrag || e.pointerId !== pdrag.id) return;
    e.stopImmediatePropagation();
    if (!pdrag.moved && Math.hypot(e.clientX - pdrag.from[0], e.clientY - pdrag.from[1]) < DRAG_PX) return;
    pdrag.moved = true;
    const q = drawingFrame().toWorld(e.clientX, e.clientY), a = along();
    const m = Math.round(((q[0] - pdrag.at[0]) * a[0] + (q[1] - pdrag.at[1]) * a[1]) * 200) / 200;  // 5 mm steps
    const b = pdrag.base, s0 = b.s || 0;
    if (pdrag.type === "move") return setPlanDraft({ ...b, del: false, s: s0 + m });
    const bx = pel.box, al = pel.u[0] ? 0 : 1, w0 = b.w ?? (bx[al + 2] - bx[al]), sg = pdrag.type === "end1" ? 1 : -1;
    const w = Math.max(0.3, w0 + sg * m);  // that end follows the pointer, the other stays
    setPlanDraft({ ...b, del: false, w, s: s0 + sg * (w - w0) / 2 });
  }, true);
  const planUp = e => { if (pdrag && e.pointerId === pdrag.id) { e.stopImmediatePropagation(); pdrag = null; } };
  addEventListener("pointerup", planUp, true);
  addEventListener("pointercancel", planUp, true);
  async function acceptPlan() {
    if (!pel || !pdraft || busy) return;
    const s = pdraft.s || 0, body = { version, rev: live.rev, op: pel.type, at: pel.at };
    if (pel.type === "opening") Object.assign(body, { kind: pel.kind, box: pel.box });
    if (pdraft.del) body.del = true;
    else if (pel.type === "wall") Object.assign(body, { dx: r4(pel.n[0] * s), dy: r4(pel.n[1] * s) });
    else Object.assign(body, { shift: r4(s) }, pdraft.w != null ? { width: r4(pdraft.w) } : {});
    busy = true;
    bar.classList.add("busy");
    bar.querySelector(".what").textContent = "Saving… (plan, then 3D)";
    onChange?.();
    try {
      const res = await call("transform", body);
      store.setItem("move-applied", JSON.stringify({ version, text: res.summary, notes: res.notes || [] }));
      store.setItem("move-on", version);
      lastResult = res;
      reload();
    } catch (err) {
      busy = false;
      bar.classList.remove("busy");
      bar.querySelector(".what").textContent = planText();
      toast(err.message, true);
      lastResult = { error: err.message };
      onChange?.();
    }
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
    const b = shown(), c = corners(b, hNow(), turn());
    const zh = !group.length && zHandles(b), R = (touch ? HANDLE_TOUCH_PX : HANDLE_PX) + 2;
    if (zh && Math.hypot(zh.lift[0] - p[0], zh.lift[1] - p[1]) < R) return { type: "lift", zh };
    if (zh && Math.hypot(zh.size[0] - p[0], zh.size[1] - p[1]) < R) return { type: "height", zh };
    const rh = turnable() && rotHandle(b, hNow());
    if (rh && Math.hypot(rh[0][0] - p[0], rh[0][1] - p[1]) < (touch ? HANDLE_TOUCH_PX : HANDLE_PX) + 2) return { type: "turn" };
    // A small piece on screen: the handles reach less far, so its middle still drags it.
    const side = c.some(q => !q) ? 0 : Math.min(...c.map((q, i) => Math.hypot(q[0] - c[(i + 1) % 4][0], q[1] - c[(i + 1) % 4][1])));
    const hs = handles(b, hNow()), r = Math.max(5, Math.min(touch ? HANDLE_TOUCH_PX : HANDLE_PX, side * 0.3));
    let best = r * r, grab = null;
    for (const [k, q] of Object.entries(hs)) {
      const d2 = q ? (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 : Infinity;
      if (d2 < best) { best = d2; grab = k; }
    }
    // A thin piece (a curtain, a panel): its middle is within reach of the side handles, so the middle drags it.
    const ctr = toScreen((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, hNow());
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
    if (draft?.del) discard();  // a tap anywhere drops a delete draft (Accept deletes)
    if (e.shiftKey && sel && !double && !grabAt(p, touch) && toggleMember(firstPick(pickAt(...p)) || null)) {  // Shift-click
      e.stopImmediatePropagation();
      e.preventDefault();
      return;
    }
    if (sel) g = grabAt(p, touch);
    if (!g && group.length && inGroup(p)) g = { type: "move" };
    if (g && group.length) g = { type: "move" };
    if (!g) {
      const cands = pickAt(...p);
      if (draft) discard();  // a tap away from the draft throws it away
      if (!cands.length) {  // the floor / a wall: on the drawing a wall, door or window is picked; else pan or look as ever
        if (sel) select(null);
        if (is2D()) planPick(e, p);
        return;
      }
      const o = firstPick(cands);
      if (!sel || o !== sel.o) select(o);
      under = cands;  // Tab cycles through what's under the tap
      g = { type: "move" };
    }
    e.stopImmediatePropagation();
    e.preventDefault();
    freeMouse?.();
    const at = toPlan(...p, hNow());
    if (!at && !g.zh) return;
    drag = { ...g, id: e.pointerId, from: p, at, base: [...shown()], rot: turn(), z: [...heightNow()], z0: draft?.z || null, moved: false };
  }, true);
  addEventListener("pointermove", e => {
    if (!drag || e.pointerId !== drag.id) return;
    e.stopImmediatePropagation();
    if (!drag.moved && Math.hypot(e.clientX - drag.from[0], e.clientY - drag.from[1]) < DRAG_PX) return;
    drag.moved = true;
    if (drag.zh) {  // up / down the screen's vertical through the piece, in 5 mm steps
      const { u, px } = drag.zh, z = drag.z;
      const m = Math.round(((e.clientX - drag.from[0]) * u[0] + (e.clientY - drag.from[1]) * u[1]) / px * 200) / 200;
      setDraft(drag.base, drag.rot, drag.type === "lift" ? [z[0] + m, z[1] + m] : [z[0], Math.max(z[0] + 0.01, z[1] + m)]);
      return;
    }
    const q = toPlan(e.clientX, e.clientY, hNow());
    if (!q) return;
    const d = [Math.round((q[0] - drag.at[0]) * 200) / 200, Math.round((q[1] - drag.at[1]) * 200) / 200];  // 5 mm steps
    const b = drag.base;
    if (drag.type === "turn") {  // the angle the pointer swept round the centre, in 15° steps (Shift: 1°)
      const c = [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], a = v => Math.atan2(v[1] - c[1], v[0] - c[0]) * 180 / Math.PI;
      const step = e.shiftKey ? 1 : 15;
      setDraft(b, Math.round((drag.rot + a(q) - a(drag.at)) / step) * step);
    } else if (drag.type === "move") {
      const lock = axis || (e.shiftKey ? (Math.abs(d[0]) >= Math.abs(d[1]) ? "x" : "y") : null);
      if (lock === "x") d[1] = 0;
      if (lock === "y") d[0] = 0;
      setDraft([b[0] + d[0], b[1] + d[1], b[2] + d[0], b[3] + d[1]]);
    }
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
    if (e.type === "pointercancel" && g.moved) setDraft(g.base, g.rot, g.z0);
  };
  addEventListener("pointerup", up, true);
  addEventListener("pointercancel", up, true);
  function cancelDrag() {
    if (drag && sel) setDraft(drag.base, drag.rot, drag.z0);
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
    if ((e.key === "PageUp" || e.key === "PageDown") && sel && !drag && !group.length) {  // raise / lower 1 cm (Shift 10); Alt: taller / shorter
      e.preventDefault();
      const d = (e.key === "PageUp" ? 1 : -1) * (e.shiftKey ? 0.1 : 0.01), z = heightNow();
      setDraft([...shown()], turn(), e.altKey ? [z[0], Math.max(z[0] + 0.01, z[1] + d)] : [z[0] + d, z[1] + d]);
      return;
    }
    if (e.key !== "Escape") return;
    if (drag) cancelDrag();
    else if (draft) discard();
    else if (sel?.path.length > 1) select(sel.path[sel.path.length - 2]);  // one level out
    else if (sel) select(null);
    else setActive(false);
  });

  // AutoCAD-style keys, ahead of the drawing's and Walk's own (capture): X / Y lock a drag to that plan axis (again: free),
  // the arrows nudge the piece 1 cm (Shift 10 cm) on the drawing and in Top, Delete / Backspace marks it for deletion.
  addEventListener("keydown", e => {
    if (pel && active && !busy && !pdrag && !/input|textarea/i.test(e.target?.tagName || "")) return planKey(e);
    if (!active || busy || !sel || drag || e.metaKey || e.ctrlKey || e.altKey || /input|textarea/i.test(e.target?.tagName || "")) return;
    const k = e.key, stop = () => { e.preventDefault(); e.stopImmediatePropagation(); onChange?.(); };
    if (/^[xy]$/i.test(k)) { axis = axis === k.toLowerCase() ? null : k.toLowerCase(); return stop(); }
    if (k === "Tab" && under.length > 1 && under.includes(sel.o)) {  // selection cycling: the next piece under the last tap
      select(under[(under.indexOf(sel.o) + (e.shiftKey ? under.length - 1 : 1)) % under.length]);
      return stop();
    }
    if (k === "Delete" || k === "Backspace") { markDelete(); return stop(); }
    const step = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[k];
    if (!step || draft?.del || (!is2D() && mode() === "walk")) return;
    const s = e.shiftKey ? 0.1 : 0.01, b = shown();
    if (axis === "x") step[1] = 0;
    if (axis === "y") step[0] = 0;
    setDraft([b[0] + step[0] * s, b[1] + step[1] * s, b[2] + step[0] * s, b[3] + step[1] * s]);
    stop();
  }, true);

  // --- Saving (Accept) -------------------------------------------------------------------------------------------------
  async function call(action, body) {
    const r = await fetch(`${API}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({ error: `${r.status} ${r.statusText}` }));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  // The draft as the request move_tool.py takes: a move when the size is the same, else a resize to the new box.
  function request() {
    if (group.length) {  // each piece described where it stands now, not where the preview put it; one batch
      const keep = draft, all = [sel.o, ...group.map(m => m.o)], [dx, dy] = groupShift();
      sel.o.visible = true;
      preview(null);
      draft = null;
      previewGroup();
      const items = all.map(o => ({ op: keep.del ? "delete" : "move", piece: describe(o), ...(keep.del ? {} : { dx: r4(dx), dy: r4(dy) }) }));
      draft = keep;
      if (keep.del) sel.o.visible = false;
      else preview(keep.box, keep.rot, keep.z);
      previewGroup();
      return { version, rev: live.rev, op: "batch", items };
    }
    if (draft.del) {
      sel.o.visible = true;
      const piece = describe(sel.o);
      sel.o.visible = false;
      return { version, rev: live.rev, op: "delete", piece };
    }
    const b = sel.box, n = draft.box, z = draft.z, z0 = [sel.low, sel.high];
    const taller = z && Math.abs((z[1] - z[0]) - (z0[1] - z0[0])) >= 0.001;
    const resized = !same([n[2] - n[0], n[3] - n[1]], [b[2] - b[0], b[3] - b[1]]) || taller;
    preview(null);  // describe the piece where it is, not where the preview put it
    const piece = describe(sel.o);
    preview(n, draft.rot, z);
    piece.box = b.map(r4);
    piece.low = r4(sel.low);
    piece.high = r4(sel.high);
    const body = { version, rev: live.rev, op: resized ? "resize" : "move", piece };
    if (resized) Object.assign(body, { box: n.map(r4) }, z ? { z: z.map(r4) } : {});
    else Object.assign(body, { dx: r4((n[0] + n[2] - b[0] - b[2]) / 2), dy: r4((n[1] + n[3] - b[1] - b[3]) / 2) },
      z ? { dz: r4(z[0] - z0[0]) } : {}, draft.rot ? { rotate: draft.rot } : {});
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
      store.setItem("move-applied", JSON.stringify({ version, text: res.summary, notes: res.notes || [], res }));
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
    if (on) loadOrigins();
    if (on && furnishText === null) {
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
    get applied() { return applied; },  // the last Accept's answer from the server, kept over the reload (tests)
    setActive, render, resume,
    debugSelect(x, y, part) {
      const o = find(x, y, part);
      if (o) select(o);
      return o && describe(o);
    },
    debugPlanPick(x, y) { if (sel) select(null); return planSelect(planHit(x, y, 0.01)) && this.state().plan; },
    planScreen(k) { return pel && planShape().map(q => toScreen(q[0], q[1], 0)); },  // the picked wall / opening's corners on screen
    debugAdd(x, y) { return toggleMember(find(x, y)); },  // Shift-click, for the tests
    debugList() {
      const out = [];
      root.traverse(o => pickable(o) && visible(o) && out.push({ ...describe(o, false), depth: pathTo(o).length }));
      return out;
    },
    // The i-th of debugList(), selected (twins at one x, y can't be told apart by debugSelect).
    debugPick(i) {
      const all = [];
      root.traverse(o => pickable(o) && visible(o) && all.push(o));
      if (all[i]) select(all[i]);
      return all[i] && describe(all[i]);
    },
    // A draft as a drag or the keys would make it: the plan box, the turn, the height span [low, high].
    debugDraft(box, rot = 0, z = null) { if (sel) setDraft(box, rot, z); return !!draft; },
    async ready() {
      if (furnishText === null) { setActive(true); setActive(false); }
      for (let i = 0; i < 100 && !furnishText; i++) await new Promise(r => setTimeout(r, 100));
      return !!furnishText;
    },
    state() {
      return {
        plan: pel && { type: pel.type, kind: pel.kind || null, at: pel.at, box: pel.box || null, run: pel.run, draft: pdraft, text: planText() },
        active, busy, selected: sel && nameOf(sel.o), path: sel ? sel.path.map(nameOf) : [], box: sel && sel.box.map(r4),
        draft: draft && draft.box, rot: turn(), z: draft?.z || null, low: sel && r4(sel.low), high: sel && r4(sel.high), zh: sel && zHandles(shown()), text: sel && draftText(), bar: !bar.hidden, chips: [...chips.querySelectorAll("button")].map(b => b.textContent),
        request: draft && sel ? request() : null, result: lastResult, axis, del: !!draft?.del, group: group.map(m => nameOf(m.o)), hidden: !!sel && !sel.o.visible,
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
    // boxNear's piece with its height: {box, low, high}.
    pieceNear(x, y, part) {
      let best = null, bd = Infinity;
      root.traverse(o => {
        if (!(part ? o.userData.part && o.userData.label === part : isPiece(o)) || !visible(o)) return;
        const pb = planBox(o), b = pb.box, d = Math.hypot((b[0] + b[2]) / 2 - x, (b[1] + b[3]) / 2 - y);
        if (d < bd) { bd = d; best = { box: b.map(r4), low: r4(pb.low), high: r4(pb.high), label: nameOf(o) }; }
      });
      return best;
    },
    screenOf(x, y, h) { return toScreen(x, y, h ?? (sel ? hNow() : 0.5)); },  // default: where the outline is drawn
    accept, discard: () => discard(),
  };
}
