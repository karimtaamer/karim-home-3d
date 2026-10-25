// Move / Resize: the Move button beside Measure. Tap a piece (in Walk, Top or the 2D drawing) to pick it, drag it to
// move it, or pull an edge / corner handle to resize it. On release move_tool.py (POST api/edit-ai/transform, no AI
// model) makes the same change in furnish.js and, when the piece is drawn on the plan, in the DXF, so the 3D and the
// 2D always agree; then the page reloads on the same view, like an Edit AI change, and Edit AI's Undo takes it back.
// A part inside a piece (the espresso machine on the coffee bar) is offered as a chip beside the whole piece.
import * as THREE from "three";

const API = "api/edit-ai";
const DRAG_PX = 4, HANDLE_PX = 12, HANDLE_TOUCH_PX = 22, HEAD = 1.5;
const SIDES = { N: [0, 1], S: [0, -1], E: [1, 0], W: [-1, 0], NE: [1, 1], NW: [-1, 1], SE: [1, -1], SW: [-1, -1] };
const store = sessionStorage;
const r4 = v => Math.round(v * 10000) / 10000;
const cm = v => `${Math.round(Math.abs(v) * 100)} cm`;

export function createMove({ camera, renderer, scene, root, cutPlane, live, version, showing, mode, drawingFrame, drawingRoot,
  onChange, reload, freeMouse }) {
  const el = renderer.domElement;
  const overlay = document.createElement("div");
  overlay.className = "move-overlay";
  overlay.innerHTML = `<svg></svg><div class="move-label" hidden></div><div class="move-chips" hidden></div>`;
  document.body.appendChild(overlay);
  const svg = overlay.querySelector("svg"), label = overlay.querySelector(".move-label"), chips = overlay.querySelector(".move-chips");
  const ray = new THREE.Raycaster();
  let active = false, sel = null, drag = null, busy = false, where = null, furnishText = null;

  // --- What a piece is: its plan box, height, the code that placed it -------------------------------------------------
  const isPiece = o => o.userData.piece && o.parent === root;
  const isPart = o => o.userData.part && hostOf(o);
  function hostOf(o) {
    for (let p = o.parent; p; p = p.parent) if (isPiece(p)) return p;
    return null;
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
      if (m && !/^Move tool/.test(m[1])) return tidy(m[1]);
    }
    for (const n of ns) {
      const m = (L[n - 1] || "").match(/item\([^,]+,[^,]+,\s*"[NSEW]",\s*([a-zA-Z]\w*)\(/);
      if (m && !/^(p|part)$/.test(m[1])) return m[1].replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
    }
    for (const n of ns) {
      const m = (L[n - 2] || "").match(/\/\/\s*(.+)$/);
      if (m) return tidy(m[1]);
    }
    return null;
  }
  function nameOf(o) {
    return o.userData.label || (isPiece(o) && lineLabel(o)) || "piece";
  }
  function describe(o) {
    const host = isPart(o) ? hostOf(o) : null, item = host || o, pb = planBox(o);
    const d = {
      kind: host ? "part" : "item", label: nameOf(o), x: item.userData.piece.x, y: item.userData.piece.y,
      facing: item.userData.piece.facing, lines: item.userData.piece.lines, scale: [r4(item.scale.x), r4(item.scale.z)],
      box: pb.box.map(r4), low: r4(pb.low), high: r4(pb.high),
      hasParts: !host && item.children.some(c => c.userData.part),
    };
    if (host) Object.assign(d, { part: o.userData.label, pos: [r4(o.position.x), r4(o.position.z)], pscale: [r4(o.scale.x), r4(o.scale.z)],
      hostBox: planBox(host).box.map(r4), hostLabel: "the " + nameOf(host) });
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
  // the part it belongs to. In 2D: the pieces whose plan box holds the point, smallest first; above head height only
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
      for (let p = h.object; p; p = p.parent) if (isPiece(p) || isPart(p)) out.push(p);
      return out;  // innermost first; [] when it's a wall or the floor
    }
    return [];
  }
  let all = null;
  function pick2D(sx, sy) {
    const [x, y] = drawingFrame().toWorld(sx, sy), tol = 4 / Math.max(1, Math.abs(drawingFrame().toScreen([1, 0])[0] - drawingFrame().toScreen([0, 0])[0]));
    if (!all) {
      all = [];
      root.traverse(o => (isPiece(o) || isPart(o)) && visible(o) && all.push(o));
    }
    const hits = all.map(o => ({ o, ...planBox(o) })).filter(c => c.box[0] - tol <= x && x <= c.box[2] + tol && c.box[1] - tol <= y && y <= c.box[3] + tol
      && (c.box[2] - c.box[0]) * (c.box[3] - c.box[1]) < 40);
    const low = hits.filter(c => c.low < HEAD);
    return (low.length ? low : hits).sort((a, b) => (a.box[2] - a.box[0]) * (a.box[3] - a.box[1]) - (b.box[2] - b.box[0]) * (b.box[3] - b.box[1])).map(c => c.o);
  }
  function select(o, cands = []) {
    sel = o && { o, ...planBox(o), cands: cands.length > 1 ? cands : [] };
    if (sel) sel.h = Math.min(sel.high, Math.max(sel.low, 0.9));
    chips.hidden = !sel?.cands.length;
    if (sel?.cands.length) {
      chips.replaceChildren(...sel.cands.slice(0, 4).map(c => {
        const b = document.createElement("button");
        b.textContent = (isPart(c) ? "" : "Whole ") + nameOf(c);
        b.classList.toggle("on", c === o);
        b.onpointerdown = e => e.stopPropagation();
        b.onclick = e => { e.stopPropagation(); select(c, sel.cands); };
        return b;
      }));
    }
    onChange?.();
  }

  // --- Overlay ----------------------------------------------------------------------------------------------------
  function corners(b, h) {
    return [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]].map(([x, y]) => toScreen(x, y, h));
  }
  function handles(b, h) {
    const mx = (b[0] + b[2]) / 2, my = (b[1] + b[3]) / 2, out = {};
    const at = { N: [mx, b[3]], S: [mx, b[1]], E: [b[2], my], W: [b[0], my], NE: [b[2], b[3]], NW: [b[0], b[3]], SE: [b[2], b[1]], SW: [b[0], b[1]] };
    for (const [k, [x, y]] of Object.entries(at)) out[k] = toScreen(x, y, h);
    return out;
  }
  function render() {
    const now = showing() + mode();
    if (where && now !== where && sel && !busy) { cancelDrag(); select(null); }
    where = now;
    if (!active || !sel || (showing() !== "model" && !is2D())) { svg.innerHTML = ""; label.hidden = true; return; }
    const b = drag?.box || sel.box, c = corners(b, sel.h);
    if (c.some(p => !p)) { svg.innerHTML = ""; return; }
    const pts = c.map(p => p.join(",")).join(" ");
    let s = `<polygon class="halo" points="${pts}"/><polygon points="${pts}"/>`;
    if (!busy) for (const [k, p] of Object.entries(handles(b, sel.h))) s += `<circle class="${k.length > 1 ? "corner" : ""}" cx="${p[0]}" cy="${p[1]}" r="${k.length > 1 ? 5 : 6.5}"/>`;
    svg.innerHTML = s;
    const top = c.reduce((a, p) => (p[1] < a[1] ? p : a));
    label.hidden = false;
    label.style.left = `${(c[0][0] + c[2][0]) / 2}px`;
    label.style.top = `${Math.min(...c.map(p => p[1]))}px`;
    const w = b[2] - b[0], d = b[3] - b[1];
    label.textContent = busy ? "Saving… (3D and plan)" : drag?.moved && drag.type === "move"
      ? `${nameOf(sel.o)} · ${dirText(drag.d)}` : `${nameOf(sel.o)} · ${Math.round(w * 100)} × ${Math.round(d * 100)} cm`;
    chips.style.left = label.style.left;
    chips.style.top = `${Math.max(...c.map(p => p[1])) + 14}px`;
    void top;
  }
  const dirText = d => [Math.abs(d[0]) >= 0.005 && `${cm(d[0])} ${d[0] > 0 ? "E" : "W"}`, Math.abs(d[1]) >= 0.005 && `${cm(d[1])} ${d[1] > 0 ? "N" : "S"}`]
    .filter(Boolean).join(" · ") || "0 cm";

  // --- Pointer: pick, drag, pull a handle -----------------------------------------------------------------------------
  function inPoly(p, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
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
    const p = [e.clientX, e.clientY], touch = e.pointerType !== "mouse";
    let type = null, grab = null;
    if (sel) {
      // A small piece on screen: the handles reach less far, so its middle still drags it.
      const c0 = corners(sel.box, sel.h), side = c0.some(q => !q) ? 0 : Math.min(...c0.map((q, i) => Math.hypot(q[0] - c0[(i + 1) % 4][0], q[1] - c0[(i + 1) % 4][1])));
      const hs = handles(sel.box, sel.h), r = Math.max(5, Math.min(touch ? HANDLE_TOUCH_PX : HANDLE_PX, side * 0.3));
      let best = r * r;
      for (const [k, q] of Object.entries(hs)) {
        const d2 = q ? (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2 : Infinity;
        if (d2 < best) { best = d2; grab = k; type = "edge"; }
      }
      const c = corners(sel.box, sel.h);
      if (!type && !c.some(q => !q) && inPoly(p, c)) type = "move";
      if (!type && !is2D()) { const hit = pick3D(...p); if (hit.includes(sel.o)) type = "move"; }
    }
    if (!type) {
      const cands = is2D() ? pick2D(...p) : pick3D(...p);
      if (!cands.length) { if (sel) select(null); return; }  // the floor / a wall: pan or look as ever
      select(cands[0], cands);
      type = "move";
    }
    e.stopImmediatePropagation();
    e.preventDefault();
    freeMouse?.();
    const at = toPlan(...p, sel.h);
    if (!at) return;
    drag = { type, side: grab, id: e.pointerId, from: p, at, box: [...sel.box], moved: false, d: [0, 0], pos: sel.o.position.clone() };
  }, true);
  addEventListener("pointermove", e => {
    if (!drag || e.pointerId !== drag.id) return;
    e.stopImmediatePropagation();
    if (!drag.moved && Math.hypot(e.clientX - drag.from[0], e.clientY - drag.from[1]) < DRAG_PX) return;
    drag.moved = true;
    const q = toPlan(e.clientX, e.clientY, sel.h);
    if (!q) return;
    const d = [Math.round((q[0] - drag.at[0]) * 200) / 200, Math.round((q[1] - drag.at[1]) * 200) / 200];  // 5 mm steps
    const b = sel.box;
    if (drag.type === "move") {
      drag.d = d;
      drag.box = [b[0] + d[0], b[1] + d[1], b[2] + d[0], b[3] + d[1]];
      // Preview: the piece itself follows the pointer.
      const w = sel.o.parent.localToWorld(drag.pos.clone()).add(new THREE.Vector3(d[0], 0, -d[1]));
      sel.o.position.copy(sel.o.parent.worldToLocal(w));
    } else {
      const [sx, sy] = SIDES[drag.side], nb = [...b], MIN = 0.03;
      if (sx > 0) nb[2] = Math.max(b[0] + MIN, b[2] + d[0]);
      if (sx < 0) nb[0] = Math.min(b[2] - MIN, b[0] + d[0]);
      if (sy > 0) nb[3] = Math.max(b[1] + MIN, b[3] + d[1]);
      if (sy < 0) nb[1] = Math.min(b[3] - MIN, b[1] + d[1]);
      drag.box = nb;
    }
  }, true);
  const up = e => {
    pointers.delete(e.pointerId);
    if (!drag || e.pointerId !== drag.id) return;
    e.stopImmediatePropagation();
    const g = drag;
    drag = null;
    if (!g.moved || e.type === "pointercancel") { sel.o.position.copy(g.pos); return; }
    if (g.type === "move" && Math.abs(g.d[0]) < 0.005 && Math.abs(g.d[1]) < 0.005) { sel.o.position.copy(g.pos); return; }
    if (g.type === "edge" && g.box.every((v, i) => Math.abs(v - sel.box[i]) < 0.003)) return;
    commit(g);
  };
  addEventListener("pointerup", up, true);
  addEventListener("pointercancel", up, true);
  function cancelDrag() {
    if (drag && sel) sel.o.position.copy(drag.pos);
    drag = null;
  }
  addEventListener("keydown", e => {
    if (!active || e.key !== "Escape" || busy) return;
    if (drag) cancelDrag();
    else if (sel) select(null);
    else setActive(false);
  });

  // --- Saving ------------------------------------------------------------------------------------------------------
  async function call(action, body) {
    const r = await fetch(`${API}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({ error: `${r.status} ${r.statusText}` }));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  async function commit(g) {
    if (g.type === "move") sel.o.position.copy(g.pos);  // describe the piece where it was, not where the preview put it
    const piece = describe(sel.o);
    piece.box = sel.box.map(r4);
    const body = { version, rev: live.rev, op: g.type === "move" ? "move" : "resize", piece };
    if (g.type === "move") Object.assign(body, { dx: g.d[0], dy: g.d[1] });
    else body.box = g.box.map(r4);
    busy = true;
    if (g.type === "move") sel.o.position.copy(sel.o.parent.worldToLocal(sel.o.parent.localToWorld(g.pos.clone()).add(new THREE.Vector3(g.d[0], 0, -g.d[1]))));
    drag = { ...g, moved: g.type === "move" };  // keep the preview drawn while it saves
    try {
      const res = await call("transform", body);
      store.setItem("move-applied", JSON.stringify({ version, text: res.summary, notes: res.notes || [] }));
      store.setItem("move-on", version);
      reload();
    } catch (e) {
      busy = false;
      drag = null;
      sel.o.position.copy(g.pos);
      toast(e.message, true);
    }
  }
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
    if (!on) { cancelDrag(); select(null); }
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
    const text = applied.undone ? "Move undone." : `${applied.text}.${applied.notes?.length ? " Note: " + applied.notes.join("; ") + "." : ""}`;
    setTimeout(() => toast(text, false, !applied.undone), 600);
  }
  const resume = store.getItem("move-on") === version;
  store.removeItem("move-on");
  return {
    get active() { return active; }, get selected() { return sel && describe(sel.o); }, get busy() { return busy; },
    setActive, render, resume,
    // For the tests: select the piece placed at plan (x, y) (or its part named `part`).
    debugSelect(x, y, part) {
      let found = null;
      root.traverse(o => { if (!found && isPiece(o) && Math.abs(o.userData.piece.x - x) < 0.002 && Math.abs(o.userData.piece.y - y) < 0.002) found = o; });
      if (found && part) found.traverse(o => { if (o.userData.part && o.userData.label === part) found = o; });
      if (found) select(found, [found, ...(isPart(found) ? [hostOf(found)] : [])]);
      return found && describe(found);
    },
    screenOf(x, y) { return sel && toScreen(x, y, sel.h); },
  };
}
