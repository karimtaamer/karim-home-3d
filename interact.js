// Openable cabinets in Walk: face one within reach and a soft glowing circle sits on it; tap / click it (or press E,
// or click with the mouse captured) to open its doors, again to close them.
//
// furnish.js marks a cabinet's Group (everything in it counts as the cabinet when aimed at) with:
//   g.userData.openable = {
//     id, label,                                        // label: shown on hover ("Medicine cabinet")
//     leaves: [{ obj, axis: "y", open: rad }            // a hinged leaf: obj turns `open` radians about its own axis
//            | { obj, slide: Vector3 }],                //   or a sliding one: obj moves by `slide` (its parent's frame)
//     anchor: Vector3,                                  // where the cue sits, in g's frame (the doors' centre, a little out)
//     reach: 1.8, duration: 0.6,                        // plan metres from the anchor to offer it; seconds to open
//     peek: 1.0, peekAt: Vector3,                       // optional, low cabinets: crouch to this eye height on opening,
//   };                                                  //   turned to peekAt (g's frame; default the anchor)
// createInteract() collects them from the scene; call update() every frame. Leaves start from their built pose (closed).
// See README §5 "Openable cabinets".

const REACH = 1.8;     // metres (in plan) from the cue that count as standing at the cabinet
const CONE = 13;       // degrees off the view centre the cue may be and still count as looking at it
const CHECK = 0.1;     // seconds between aim checks (one raycast against the openables)

// isActive(): Walk, free to look (no tween, measure, dialog); isLocked(): the mouse is captured, so a click toggles too;
// occluders: meshes (walls) that hide a cabinet behind them.
export function createInteract({ THREE, camera, scene, renderer, isActive, isLocked = () => false, occluders = [] }) {
  const bare = new URLSearchParams(location.search).has("clean");  // screenshots of the bare model stay bare
  const style = document.createElement("style");
  style.textContent = `
    #interact-cue { position: fixed; left: 0; top: 0; z-index: 2; width: 52px; height: 52px; margin: -26px 0 0 -26px; padding: 0; border: 0;
      border-radius: 50%; background: none; cursor: pointer; opacity: 0; pointer-events: none; transition: opacity .2s;
      -webkit-tap-highlight-color: transparent; touch-action: manipulation; }
    #interact-cue.on { opacity: 1; pointer-events: auto; }
    #interact-cue:focus { outline: none; }
    #interact-cue .glow { position: absolute; inset: 0; border-radius: 50%; pointer-events: none;
      background: radial-gradient(circle, #fffaf3f2 0 30%, #fff1dc99 46%, #ffe9cc00 70%); box-shadow: 0 0 16px 4px #fff2df40;
      animation: interact-breathe 2s ease-in-out infinite; }
    #interact-cue svg { position: absolute; left: 16px; top: 16px; width: 20px; height: 20px; fill: none; stroke: #7a6553; stroke-width: 1.7;
      stroke-linecap: round; stroke-linejoin: round; opacity: .85; pointer-events: none; }
    #interact-cue::after { content: attr(data-label); position: absolute; left: 50%; top: 100%; transform: translate(-50%, 4px); white-space: nowrap;
      font: 500 10.5px Inter, sans-serif; letter-spacing: .06em; color: #fff; text-shadow: 0 1px 6px #000a; opacity: 0; transition: opacity .2s; }
    @media (hover: hover) and (pointer: fine) { #interact-cue:hover::after { opacity: .9; } }
    @keyframes interact-breathe { 0%, 100% { opacity: .55; transform: scale(.94); } 50% { opacity: .85; transform: scale(1); } }
    @media (prefers-reduced-motion: reduce) { #interact-cue .glow { animation: none; opacity: .7; } }`;
  document.head.appendChild(style);
  const cue = document.createElement("button");
  cue.id = "interact-cue";
  cue.innerHTML = `<span class="glow"></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5z"/><path d="M12 4v16"/><path d="M10 11v2M14 11v2"/></svg>`;
  document.body.appendChild(cue);

  // The openables in the scene, each leaf with its closed pose, and the cue's spot in the world.
  const list = [];
  function refresh() {
    list.length = 0;
    scene.updateMatrixWorld(true);
    scene.traverse(g => {
      const d = g.userData.openable;
      if (!d) return;
      list.push({
        ...d, root: g, reach: d.reach ?? REACH, duration: d.duration ?? 0.6, t: 0, to: 0,
        at: g.localToWorld(d.anchor.clone()), look: g.localToWorld((d.peekAt || d.anchor).clone()),
        leaves: d.leaves.map(l => ({ ...l, axis: l.axis || "y", rot: l.obj.rotation[l.axis || "y"], pos: l.obj.position.clone() })),
      });
    });
  }
  refresh();

  const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
  function pose(o) {
    const e = ease(o.t);
    for (const l of o.leaves) {
      if (l.slide) l.obj.position.copy(l.pos).addScaledVector(l.slide, e);
      else l.obj.rotation[l.axis] = l.rot + l.open * e;
    }
  }
  function toggle(o = target) {
    if (!o) return;
    o.to = o.to ? 0 : 1;
    if (o.peek && o.to && !crouch) kneel(o);
    else if (crouch?.o === o && !o.to) rise();
    label();
  }

  // Low cabinets (peek: eye height) are seen into by crouching to it as they open, turned to the inside; you stand
  // back up when they close or you step out of reach. Only the eye height moves: walking and looking carry on.
  let crouch = null;  // { o, stand, y0, y1, t, aim0, aim1 }
  function kneel(o) {
    const aim0 = camera.getWorldPosition(new THREE.Vector3()).add(camera.getWorldDirection(new THREE.Vector3()));
    crouch = { o, stand: camera.position.y, y0: camera.position.y, y1: o.peek, t: 0, aim0, aim1: o.look };
  }
  function rise() {
    if (!crouch || crouch.y1 === crouch.stand) return;
    Object.assign(crouch, { y0: camera.position.y, y1: crouch.stand, t: 0, aim0: null });
  }
  function bob(dt) {
    if (!crouch || crouch.t >= 1) return;
    crouch.t = Math.min(1, crouch.t + dt / crouch.o.duration);
    const e = ease(crouch.t);
    camera.position.y = crouch.y0 + (crouch.y1 - crouch.y0) * e;
    if (crouch.aim0) camera.lookAt(crouch.aim0.clone().lerp(crouch.aim1, e));
    if (crouch.t >= 1 && crouch.y1 === crouch.stand) crouch = null;
  }
  const label = () => target && (cue.dataset.label = `${target.to ? "Close" : "Open"} ${target.label.toLowerCase()} · E`);
  cue.setAttribute("aria-label", "Open or close");
  cue.addEventListener("pointerdown", e => e.stopPropagation());
  cue.addEventListener("click", e => { e.stopPropagation(); toggle(); });
  // With the mouse captured the cursor is the view centre, which is what the cue answers to; E works either way.
  document.addEventListener("click", e => target && isLocked() && e.target !== cue && toggle());
  addEventListener("keydown", e => e.code === "KeyE" && !e.repeat && target && !/INPUT|TEXTAREA/.test(e.target.tagName) && toggle());

  // What you are looking at: the first openable the view centre's ray hits, else one whose cue is near the
  // centre, within reach and with no wall in between.
  const ray = new THREE.Raycaster(), eye = new THREE.Vector3(), dir = new THREE.Vector3(), to = new THREE.Vector3();
  const clear = (d, far) => { ray.set(eye, d); ray.far = far; return !ray.intersectObjects(occluders, false).length; };
  function aimed() {
    camera.getWorldPosition(eye);
    camera.getWorldDirection(dir);
    const near = list.filter(o => Math.hypot(o.at.x - eye.x, o.at.z - eye.z) <= o.reach);
    if (!near.length) return null;
    ray.set(eye, dir);
    ray.far = 4;
    const hit = ray.intersectObjects(near.map(o => o.root), true)[0];
    if (hit) {
      let o = null;
      for (let p = hit.object; p && !o; p = p.parent) o = near.find(n => n.root === p);
      if (o && clear(dir, hit.distance)) return o;
    }
    let best = null, bestAngle = THREE.MathUtils.degToRad(CONE);
    for (const o of near) {
      const a = dir.angleTo(to.subVectors(o.at, eye));
      if (a < bestAngle && clear(to.clone().normalize(), to.length() - 0.05)) { best = o; bestAngle = a; }
    }
    return best;
  }

  let target = null, wait = 0, last = performance.now();
  const v = new THREE.Vector3();
  function update() {
    // Real time, not the loop's capped step: a swing takes `duration` even on a slow phone.
    const now = performance.now(), dt = (now - last) / 1000;
    last = now;
    for (const o of list) {
      if (o.t === o.to) continue;
      o.t = o.to ? Math.min(1, o.t + dt / o.duration) : Math.max(0, o.t - dt / o.duration);
      pose(o);
    }
    if (crouch && (bare || !isActive() || Math.hypot(crouch.o.at.x - camera.position.x, crouch.o.at.z - camera.position.z) > crouch.o.reach)) rise();
    bob(dt);
    if (bare || !list.length || !isActive()) { wait = 0; return show(null); }
    if ((wait -= dt) <= 0) { wait = CHECK; show(aimed()); }
    if (!target) return;
    v.copy(target.at).project(camera);
    if (v.z > 1) return show(null);
    const r = renderer.domElement.getBoundingClientRect();
    cue.style.transform = `translate(${r.left + (v.x + 1) / 2 * r.width}px, ${r.top + (1 - v.y) / 2 * r.height}px)`;
  }
  function show(o) {
    if (o === target) return;
    target = o;
    cue.classList.toggle("on", !!o);
    label();
  }

  return { update, refresh, toggle: id => toggle(list.find(o => o.id === id) || null), get target() { return target?.id ?? null; }, list };
}
