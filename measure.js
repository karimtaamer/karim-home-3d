// Tape measure for the 3D views: click / tap two surfaces, or drag from one to the other, to get the distance in cm.
// Lines and labels are drawn on an SVG/HTML overlay so they stay crisp and readable over the scene.
// In the top view it measures in plan instead, snapping to the DWG's points exactly as the drawing does.
import * as THREE from "three";
import { cm, SNAP_PX } from "./drawing.js";

const CLICK_PX = 5;
const AXES = [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 0, 1)];
const FLOOR = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

// plan(): measure in plan (top view); snaps: promise of drawing.json's [x, y, kind, ...] in plan metres.
export function createMeasure({ camera, renderer, scene, cutPlane, capMaterial, paused, onChange, plan, snaps }) {
  const el = renderer.domElement;
  const overlay = document.createElement("div");
  overlay.className = "measure-overlay";
  overlay.innerHTML = `<svg></svg><div class="labels"></div>`;
  document.body.appendChild(overlay);
  const svg = overlay.querySelector("svg"), labels = overlay.querySelector(".labels");

  const ray = new THREE.Raycaster();
  const done = [];  // [a, b] world points
  let active = false, start = null, hover = null, hoverKind, lock = false, mouse = null, press = null, lastAim = null;
  let snapList = null;
  snaps?.then(s => (snapList = s));

  // Only what is actually drawn: visible all the way up, not faded out, and below the wall cut.
  function shown(o) {
    for (let p = o; p; p = p.parent) if (!p.visible) return false;
    const m = Array.isArray(o.material) ? o.material[0] : o.material;
    return m && m.visible !== false && !(m.transparent && m.opacity < 0.05);
  }
  function aim(x, y) {
    const r = el.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1), camera);
  }
  function surfaceAt(x, y) {
    aim(x, y);
    const targets = [];
    scene.traverse(o => o.isMesh && targets.push(o));
    const cut = cutPlane.constant < 999 ? cutPlane.constant : Infinity;
    for (const h of ray.intersectObjects(targets, false)) {
      if (!shown(h.object)) continue;
      const m = Array.isArray(h.object.material) ? h.object.material[0] : h.object.material;
      if (m.clippingPlanes?.length && h.point.y > cut + 1e-3) continue;
      // The ink cap of a cut wall is really the wall's far inside face; measure on the cut instead.
      if (m === capMaterial) return ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -cut), new THREE.Vector3()) || h.point;
      return h.point.clone();
    }
    return null;
  }
  function floorAt(x, y) {
    aim(x, y);
    return ray.ray.intersectPlane(FLOOR, new THREE.Vector3());
  }
  // In plan: the nearest DWG snap point within reach (screen px), else the floor under the pointer.
  function planAt(x, y, reach) {
    const p = floorAt(x, y);
    if (!p || !snapList) return { p };
    const r = floorAt(x + reach, y)?.distanceTo(p) ?? 0, s = snapList;
    let best = -1, bd = r * r;
    for (let i = 0; i < s.length; i += 3) {
      const d = (s[i] - p.x) ** 2 + (s[i + 1] + p.z) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
    return best < 0 ? { p } : { p: new THREE.Vector3(s[best], 0, -s[best + 1]), kind: s[best + 2] };
  }
  const pointAt = (x, y, reach) => (plan?.() ? planAt(x, y, reach) : { p: surfaceAt(x, y) });

  // Shift squares the second point up with the first along whichever axis it is mostly along.
  function constrain(p) {
    if (!start || !p || !lock) return p;
    const d = p.clone().sub(start);
    const axis = AXES.reduce((a, b) => (Math.abs(d.dot(b)) > Math.abs(d.dot(a)) ? b : a));
    return start.clone().addScaledVector(axis, d.dot(axis));
  }

  function setActive(on) {
    active = on;
    start = hover = press = null;
    el.style.cursor = on ? "crosshair" : "";
    onChange?.();
  }
  function pick(x, y, reach) {
    const p = constrain(pointAt(x, y, reach).p);
    if (!p) return;
    if (!start) start = p;
    else {
      if (p.distanceTo(start) > 1e-4) done.push([start, p]);
      start = null;
      onChange?.();
    }
    hover = null;
    lastAim = null;
  }

  // With the tape on, one finger (or the left button) measures: pressing sets A, or presses B, which follows
  // the pointer until it lifts; a press dragged off A ends at B on lift. A second finger drops the point under way.
  const pointers = new Set();
  function drop() {
    if (press?.a) start = null;
    press = hover = lastAim = null;
  }
  function follow(x, y) {
    const h = pointAt(x, y, press.reach);
    hover = constrain(h.p);
    hoverKind = hover === h.p ? h.kind : undefined;
  }
  el.addEventListener("pointerdown", e => {
    pointers.add(e.pointerId);
    if (pointers.size > 1) return drop();
    if (!active || e.button !== 0 || paused()) return;
    press = { id: e.pointerId, x: e.clientX, y: e.clientY, reach: e.pointerType === "mouse" ? SNAP_PX.mouse : SNAP_PX.touch, a: !start };
    if (!press.a) return follow(e.clientX, e.clientY);
    start = pointAt(e.clientX, e.clientY, press.reach).p;
    if (!start) press = null;  // nothing under the pointer to start from
  });
  el.addEventListener("pointermove", e => {
    if (active && e.pointerType === "mouse") mouse = [e.clientX, e.clientY];
    if (press?.id !== e.pointerId || paused()) return;
    if (Math.hypot(e.clientX - press.x, e.clientY - press.y) > CLICK_PX) press.moved = true;
    if (!press.a || press.moved) follow(e.clientX, e.clientY);  // the live B, snapped
  });
  const release = e => {
    pointers.delete(e.pointerId);
    if (press?.id !== e.pointerId) return;
    if (e.type !== "pointerup" || paused()) return drop();
    // Lifting fixes B; a press that set A only ends the measurement if it was dragged off A.
    if (start && (!press.a || press.moved)) pick(e.clientX, e.clientY, press.reach);
    press = null;
  };
  el.addEventListener("pointerup", release);
  el.addEventListener("pointercancel", release);
  el.addEventListener("pointerleave", e => { if (e.pointerType === "mouse") { mouse = null; if (!press) hover = null; } });
  addEventListener("keydown", e => {
    if (paused() || !active) return;
    if (e.key === "Shift") lock = true;
    else if (e.key === "Escape") start = press = null;
    else if (e.key === "Backspace" || e.key === "Delete") { start ? (start = press = null) : done.pop(); onChange?.(); }
  });
  addEventListener("keyup", e => { if (e.key === "Shift") lock = false; });

  // World point -> view space; segments are clipped at the near plane so lines behind you behave.
  const toView = p => p.clone().applyMatrix4(camera.matrixWorldInverse);
  function toScreen(v) {
    const r = el.getBoundingClientRect();
    const n = v.clone().applyMatrix4(camera.projectionMatrix);
    return [r.left + ((n.x + 1) / 2) * r.width, r.top + ((1 - n.y) / 2) * r.height];
  }
  function segment(a, b) {
    let va = toView(a), vb = toView(b);
    const z = -camera.near - 1e-3;
    if (va.z > z && vb.z > z) return null;
    if (va.z > z) va = va.lerp(vb, (z - va.z) / (vb.z - va.z));
    if (vb.z > z) vb = vb.clone().lerp(va, (z - vb.z) / (va.z - vb.z));
    return [toScreen(va), toScreen(vb), toView(a).z <= z, toView(b).z <= z];
  }

  function render() {
    // Re-aim only when the mouse, the camera or the axis lock has changed since the last frame.
    const aimed = active && mouse && !paused() && [...mouse, ...camera.matrixWorld.elements, lock, !!start, !!plan?.()].join();
    if (aimed && aimed !== lastAim) {
      const h = pointAt(...mouse, SNAP_PX.mouse);
      hover = constrain(h.p);
      hoverKind = hover === h.p ? h.kind : undefined;  // squared up off the snap: no snap marker
    }
    lastAim = aimed;
    let lines = "", tags = "";
    const draw = (a, b, live) => {
      const s = segment(a, b);
      if (!s) return;
      const [[ax, ay], [bx, by], ina, inb] = s;
      const dash = live ? ' stroke-dasharray="7 5"' : "";
      lines += `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" class="halo"/><line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}"${dash}/>`;
      if (ina) lines += `<circle cx="${ax}" cy="${ay}" r="4"/>`;
      if (inb) lines += `<circle cx="${bx}" cy="${by}" r="4"/>`;
      tags += `<div style="left:${(ax + bx) / 2}px;top:${(ay + by) / 2}px">${cm(a.distanceTo(b))}</div>`;
    };
    for (const [a, b] of done) draw(a, b);
    if (active && start && hover) draw(start, hover, true);
    else if (active && start) { const s = segment(start, start); if (s) lines += `<circle cx="${s[0][0]}" cy="${s[0][1]}" r="4"/>`; }
    if (active && hover && !start) { const s = segment(hover, hover); if (s) lines += `<circle cx="${s[0][0]}" cy="${s[0][1]}" r="5" class="hover"/>`; }
    if (active && hover && hoverKind !== undefined) {  // the drawing's snap markers: end, mid, centre
      const s = segment(hover, hover), [x, y] = s ? s[0] : [];
      if (s) lines += hoverKind === 0 ? `<rect x="${x - 6}" y="${y - 6}" width="12" height="12" class="snap"/>`
        : hoverKind === 1 ? `<polygon points="${x},${y - 7} ${x + 7},${y + 5} ${x - 7},${y + 5}" class="snap"/>`
        : `<circle cx="${x}" cy="${y}" r="7" class="snap"/>`;
    }
    svg.innerHTML = lines;
    labels.innerHTML = tags;
  }

  return {
    get active() { return active; },
    get count() { return done.length; },
    setActive,
    clear() { done.length = 0; start = press = null; onChange?.(); },
    render,
  };
}
