// Electrical, lighting and low-current points (electrical-<version>.json, written by build_electrical.py; only Main has
// one so far). One file drives both views:
//   3D (index.html): buildElectrical() adds a faceplate / fitting for each point (ceiling spots and fans go in the
//      furniture's ceilingBits, so they show with the ceilings), and createElectricalUI() names whatever the pointer is
//      on: hover (or, with the mouse captured in Walk, look at it), tap / click to pin the card. The "Electrical" button
//      in the bar adds see-through markers on every point, hidden ones too, in Walk and Top.
//   2D (drawing.js): drawElectrical() draws the layer over the DWG; pickElectrical() finds the point under the pointer.
// Point fields: type, room, x, y (plan metres), h (metres from the slab), facing (the way the plate looks: N/E/S/W),
// label, status (plan / adapted / added / existing), note; switches add gangs (one line per rocker) and two_way.

const cache = new Map();
export function loadElectrical(url) {
  if (!cache.has(url)) cache.set(url, fetch(url, { cache: "no-cache" }).then(r => (r.ok && r.headers.get("content-type")?.includes("json") ? r.json() : null)).catch(() => null));
  return cache.get(url);
}

// What each kind is, said plainly (the card's first line), its colour and its 2D glyph.
export const KINDS = {
  spot:         { what: "This is a ceiling spot light (6 W).", col: "#f2b134", glyph: "spot" },
  pendant:      { what: "This is a pendant light.", col: "#f2b134", glyph: "pendant" },
  walllight:    { what: "This is a wall light.", col: "#f2b134", glyph: "wall" },
  led:          { what: "This is an indirect LED strip.", col: "#f2b134", glyph: "led" },
  switch:       { what: "This is a light switch bank.", col: "#ff6b6b", glyph: "S" },
  acctl:        { what: "This is an AC controller (thermostat).", col: "#ff6b6b", glyph: "AC" },
  socket:       { what: "This is a socket.", col: "#5aa9ff", glyph: "socket" },
  power:        { what: "This is a dedicated power point for an appliance.", col: "#ff9f43", glyph: "P" },
  wp:           { what: "This is a weatherproof outdoor socket.", col: "#5aa9ff", glyph: "WP" },
  multi:        { what: "This is a combined media plate.", col: "#46d39a", glyph: "M" },
  data:         { what: "This is a data point (Cat6 network socket).", col: "#46d39a", glyph: "D" },
  phone:        { what: "This is a phone point.", col: "#46d39a", glyph: "T" },
  tv:           { what: "This is a TV / antenna point.", col: "#46d39a", glyph: "TV" },
  sound:        { what: "This is the sound-system control screen.", col: "#c58cff", glyph: "SO" },
  intercom:     { what: "This is an intercom screen: see and answer whoever is at the front door.", col: "#c58cff", glyph: "IN" },
  intercom_out: { what: "This is the outdoor intercom unit (camera and call button).", col: "#c58cff", glyph: "IN" },
  doorbell:     { what: "This is the doorbell button.", col: "#c58cff", glyph: "B" },
  chime:        { what: "This is the doorbell chime.", col: "#c58cff", glyph: "CH" },
  fan:          { what: "This is an exhaust fan.", col: "#c58cff", glyph: "F" },
  db:           { what: "This is the distribution board (DB): the main breaker panel for the whole flat.", col: "#c58cff", glyph: "DB" },
  lcp:          { what: "This is the low-current panel: internet fibre, network, TV and intercom cables meet here.", col: "#c58cff", glyph: "LC" },
  router:       { what: "This is the Wi-Fi router.", col: "#c58cff", glyph: "R" },
};
const PARTS = { D: "data (Cat6)", H: "HDMI", TV: "TV / antenna", "2S": "double socket", S: "socket" };
const STATUS = {
  plan: "From the Samra electrical plan.",
  adapted: "From the Samra plan, adapted to Main's layout.",
  added: "Added for Main (not on the Samra plan).",
  existing: "Already in the model.",
};
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const cmH = h => `${Math.round(h * 100)} cm`;

// The card for a point (HTML). byId: id -> point, for the two-way partners.
export function describeHTML(p, byId = {}) {
  const k = KINDS[p.type] || { what: "" };
  const rows = [];
  if (p.h != null && !["spot", "fan", "led"].includes(p.type)) rows.push(`${cmH(p.h)} from the floor slab`);
  else if (p.type === "spot" || p.type === "fan") rows.push("In the ceiling");
  if (p.room) rows.push(p.room);
  let body = "";
  if (p.gangs?.length) body += `<ol>${p.gangs.map(g => `<li>${esc(g)}</li>`).join("")}</ol>`;
  if (p.parts?.length) body += `<div class="el-sub">On the plate: ${p.parts.map(x => PARTS[x] || x).join(" · ")}</div>`;
  if (p.two_way) {
    const others = String(p.two_way).split(",").map(id => byId[id]).filter(Boolean)
      .map(o => o.label.replace(/^\d-gang switch — /, ""));
    if (others.length) body += `<div class="el-sub">Also switched from: ${others.map(esc).join("; ")}</div>`;
  }
  if (p.appliance) body += `<div class="el-sub">For: ${esc(p.appliance)}</div>`;
  if (p.note) body += `<div class="el-note">${esc(p.note[0].toUpperCase() + p.note.slice(1))}.</div>`;
  return `<div class="el-what">${esc(k.what)}</div><div class="el-title">${esc(p.label)}</div>`
    + `<div class="el-sub">${rows.map(esc).join(" · ")}</div>${body}<div class="el-status s-${p.status}">${esc(STATUS[p.status] || "")}</div>`;
}

const CSS = `
  .el-card { position: fixed; z-index: 6; max-width: 300px; padding: 10px 12px; border-radius: 10px; background: #1f1b18ee; color: #f6efe6;
    font: 12px/1.4 Inter, sans-serif; box-shadow: 0 6px 22px #0005; pointer-events: none; }
  .el-card.pinned { pointer-events: auto; }
  .el-card .el-what { font-weight: 600; font-size: 12.5px; margin-bottom: 2px; }
  .el-card .el-title { color: #f2d3a4; }
  .el-card .el-sub { color: #cbbfb2; margin-top: 3px; }
  .el-card ol { margin: 5px 0 2px 18px; padding: 0; }
  .el-card .el-note { margin-top: 5px; color: #b9ada0; font-size: 11.5px; }
  .el-card .el-status { margin-top: 6px; font-size: 10.5px; letter-spacing: .04em; color: #9d9185; text-transform: uppercase; }
  .el-card .el-status.s-added { color: #8fd6b3; } .el-card .el-status.s-adapted { color: #f2c27a; }
  .el-card .el-x { position: absolute; right: 6px; top: 4px; border: 0; background: none; color: #f6efe6; font-size: 16px; cursor: pointer; display: none; }
  .el-card.pinned .el-x { display: block; }`;
export function makeCard() {
  if (!document.getElementById("el-css")) document.head.append(Object.assign(document.createElement("style"), { id: "el-css", textContent: CSS }));
  const el = Object.assign(document.createElement("div"), { className: "el-card" });
  el.hidden = true;
  document.body.append(el);
  const card = {
    el, point: null, pinned: false,
    show(p, x, y, byId, pinned = false) {
      if (card.pinned && !pinned) return;
      if (p !== card.point || pinned !== card.pinned) {
        el.innerHTML = describeHTML(p, byId) + `<button class="el-x" aria-label="Close">×</button>`;
        el.querySelector(".el-x").onclick = () => card.hide(true);
      }
      card.point = p; card.pinned = pinned;
      el.classList.toggle("pinned", pinned);
      el.hidden = false;
      const w = el.offsetWidth, h = el.offsetHeight;
      el.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, x + 18))}px`;
      el.style.top = `${Math.max(8, Math.min(innerHeight - h - 8, y + 18))}px`;
    },
    hide(force = false) {
      if (card.pinned && !force) return;
      card.pinned = false; card.point = null; el.hidden = true;
    },
  };
  return card;
}

// ------------------------------------------------------------------------------------------------ 3D
const FACING = { S: 0, E: Math.PI / 2, N: Math.PI, W: -Math.PI / 2 };
const CEILING_KINDS = new Set(["spot", "fan"]);
const NEAR = 5;  // metres: in Walk the see-through markers show only this close

export function buildElectrical({ THREE, scene, ceilingBits, data, ceiling = 2.6, materials = {} }) {
  const group = new THREE.Group(), markers = new THREE.Group(), picks = [];
  group.name = "electrical"; markers.name = "electrical-markers";
  markers.visible = false;
  scene.add(group, markers);
  const M = {
    plate: new THREE.MeshStandardMaterial({ color: 0xf7f5f0, roughness: 0.45 }),
    rocker: new THREE.MeshStandardMaterial({ color: 0xeceae4, roughness: 0.35 }),
    hole: new THREE.MeshStandardMaterial({ color: 0x3a3632, roughness: 0.8 }),
    glass: new THREE.MeshStandardMaterial({ color: 0x15171a, roughness: 0.15, metalness: 0.2 }),
    metal: new THREE.MeshStandardMaterial({ color: 0x9aa0a6, roughness: 0.4, metalness: 0.6 }),
    grey: new THREE.MeshStandardMaterial({ color: 0xc9c8c3, roughness: 0.6 }),
    red: new THREE.MeshStandardMaterial({ color: 0xd23b2f, emissive: 0x5a0d08, roughness: 0.5 }),
    led: new THREE.MeshStandardMaterial({ color: 0xfff1d6, emissive: 0xffe2b0, emissiveIntensity: 1.2 }),
    ring: new THREE.MeshStandardMaterial({ color: 0xe9e6df, roughness: 0.35, metalness: 0.2 }),
    spot: materials.downlight || new THREE.MeshStandardMaterial({ color: 0xfff6e8, emissive: 0xfff0d8, emissiveIntensity: 1.5 }),
    pick: new THREE.MeshBasicMaterial({ visible: false }),
  };
  const box = (g, x0, x1, y0, y1, z0, z1, m) => {
    const b = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0), m);
    b.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    g.add(b); return b;
  };
  const cyl = (g, x, y, r, z0, z1, m, seg = 16) => {
    const c = new THREE.Mesh(new THREE.CylinderGeometry(r, r, z1 - z0, seg), m);
    c.rotation.x = Math.PI / 2; c.position.set(x, y, (z0 + z1) / 2);
    g.add(c); return c;
  };
  // One socket module centred at (x, y): two round pin holes.
  const socketFace = (g, x, y) => { cyl(g, x - 0.011, y, 0.0035, 0.009, 0.0105, M.hole, 8); cyl(g, x + 0.011, y, 0.0035, 0.009, 0.0105, M.hole, 8); cyl(g, x, y, 0.019, 0.009, 0.0095, M.rocker, 20); };
  const plate = (g, w, h, y, d = 0.009) => box(g, -w / 2, w / 2, y - h / 2, y + h / 2, 0, d, M.plate);
  const MOD = 0.06;  // one module across a plate
  const modulePart = (g, kind, x, y) => {
    if (kind === "S") socketFace(g, x, y);
    else if (kind === "D") box(g, x - 0.008, x + 0.008, y - 0.007, y + 0.007, 0.009, 0.0105, M.hole);
    else if (kind === "H") box(g, x - 0.009, x + 0.009, y - 0.004, y + 0.004, 0.009, 0.0105, M.hole);
    else if (kind === "TV") { cyl(g, x, y, 0.006, 0.009, 0.014, M.metal, 12); }
    else if (kind === "T") box(g, x - 0.006, x + 0.006, y - 0.005, y + 0.005, 0.009, 0.0105, M.hole);
  };
  const modular = (g, parts, y) => {
    const mods = parts.flatMap(p => (p === "2S" ? ["S", "S"] : [p]));
    const w = 0.026 + mods.length * MOD;
    plate(g, w, 0.086, y);
    mods.forEach((m, i) => modulePart(g, m, -w / 2 + 0.013 + MOD * (i + 0.5), y));
  };

  const built = { group, markers, picks, items: [] };
  const byId = Object.fromEntries(data.points.map(p => [p.id, p]));
  built.byId = byId;

  function wallPart(p) {
    const g = new THREE.Group(), y = p.h ?? 1.2;
    switch (p.type) {
      case "socket": modular(g, Array(p.gang || 1).fill("S"), y); break;
      case "power": modular(g, ["S"], y); box(g, -0.008, 0.008, y + 0.026, y + 0.034, 0.009, 0.011, M.red); break;
      case "multi": modular(g, p.parts, y); break;
      case "data": modular(g, ["D"], y); break;
      case "phone": modular(g, ["T"], y); break;
      case "tv": modular(g, ["TV"], y); break;
      case "wp":
        box(g, -0.05, 0.05, y - 0.055, y + 0.055, 0, 0.045, M.grey);
        box(g, -0.044, 0.044, y - 0.045, y + 0.05, 0.045, 0.052, M.grey);
        break;
      case "switch": {
        const n = p.gangs?.length || 1, w = Math.max(0.086, 0.026 + n * 0.04);
        plate(g, w, 0.086, y);
        for (let i = 0; i < n; i++) { const x = -w / 2 + 0.013 + 0.04 * (i + 0.5) + (w - 0.026 - n * 0.04) / 2; box(g, x - 0.017, x + 0.017, y - 0.03, y + 0.03, 0.009, 0.014, M.rocker); }
        break;
      }
      case "acctl": plate(g, 0.086, 0.086, y); box(g, -0.028, 0.028, y - 0.006, y + 0.026, 0.009, 0.011, M.glass); break;
      case "sound": case "intercom": plate(g, 0.13, 0.11, y); box(g, -0.055, 0.055, y - 0.04, y + 0.045, 0.009, 0.012, M.glass); break;
      case "intercom_out": box(g, -0.055, 0.055, y - 0.11, y + 0.11, 0, 0.03, M.metal); cyl(g, 0, y + 0.07, 0.012, 0.03, 0.034, M.glass); cyl(g, 0, y - 0.06, 0.013, 0.03, 0.036, M.glass); break;
      case "doorbell": box(g, -0.03, 0.03, y - 0.045, y + 0.045, 0, 0.012, M.metal); cyl(g, 0, y, 0.013, 0.012, 0.02, M.ring); break;
      case "chime": box(g, -0.08, 0.08, y - 0.05, y + 0.05, 0, 0.04, M.plate); break;
      case "db": {
        const w = p.w || 0.45, hh = p.hh || 0.6;
        box(g, -w / 2, w / 2, y - hh / 2, y + hh / 2, -0.004, 0.018, M.grey);
        box(g, -w / 2 + 0.02, w / 2 - 0.02, y - hh / 2 + 0.02, y + hh / 2 - 0.02, 0.018, 0.021, M.plate);
        box(g, w / 2 - 0.06, w / 2 - 0.04, y - 0.04, y + 0.04, 0.021, 0.03, M.metal);
        break;
      }
      case "lcp": {
        const w = p.w || 0.35, hh = p.hh || 0.45;
        box(g, -w / 2, w / 2, y - hh / 2, y + hh / 2, -0.004, 0.016, M.plate);
        box(g, -w / 2 + 0.03, w / 2 - 0.03, y + hh / 2 - 0.07, y + hh / 2 - 0.04, 0.016, 0.019, M.grey);
        box(g, w / 2 - 0.05, w / 2 - 0.035, y - 0.03, y + 0.03, 0.016, 0.024, M.metal);
        break;
      }
      case "router":
        box(g, -0.11, 0.11, y - 0.012, y + 0.012, 0, 0.12, M.grey);              // little wall shelf
        box(g, -0.1, 0.1, y + 0.012, y + 0.052, 0.01, 0.13, M.plate);           // the router on it
        for (const x of [-0.07, 0.07]) { const a = new THREE.Mesh(new THREE.CylinderGeometry(0.005, 0.006, 0.13, 8), M.hole); a.position.set(x, y + 0.115, 0.02); g.add(a); }
        cyl(g, -0.06, y + 0.032, 0.0025, 0.13, 0.132, M.led, 6);
        break;
      default: return null;
    }
    return g;
  }

  for (const p of data.points) {
    const world = new THREE.Vector3(p.x, p.h ?? ceiling, -p.y);
    let obj = null;
    if (p.type === "spot") {
      obj = new THREE.Group();
      const r = new THREE.Mesh(new THREE.RingGeometry(0.032, 0.045, 20), M.ring); r.rotation.x = Math.PI / 2; obj.add(r);
      const d = new THREE.Mesh(new THREE.CircleGeometry(0.032, 20), M.spot); d.rotation.x = Math.PI / 2; d.position.y = 0.001; obj.add(d);
      obj.position.set(p.x, ceiling - 0.002, -p.y);
      ceilingBits.add(obj);
    } else if (p.type === "fan") {
      obj = new THREE.Group();
      const b = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.01, 0.22), M.plate); obj.add(b);
      for (let i = -3; i <= 3; i++) { const s = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.012, 0.008), M.grey); s.position.set(0, -0.001, i * 0.022); obj.add(s); }
      obj.position.set(p.x, ceiling - 0.006, -p.y);
      ceilingBits.add(obj);
    } else if (p.status !== "existing") {  // existing ones are modelled by furnish: only their pick target and marker here
      obj = wallPart(p);
      if (obj) {
        obj.position.set(p.x, 0, -p.y);
        obj.rotation.y = FACING[p.facing] ?? 0;
        group.add(obj);
      }
    }
    // Pick target: a little larger than the part, so small plates are easy to land on.
    const big = { db: 0.36, lcp: 0.28, router: 0.16, spot: 0.09, fan: 0.15, pendant: 0.16, walllight: 0.14, intercom_out: 0.13 }[p.type] || 0.075;
    const pick = new THREE.Mesh(new THREE.SphereGeometry(big, 8, 6), M.pick);
    pick.position.copy(world);
    if (p.facing && !CEILING_KINDS.has(p.type)) {  // just in front of the wall
      const a = FACING[p.facing] ?? 0;
      pick.position.x += Math.sin(a) * 0.02; pick.position.z += Math.cos(a) * 0.02;
    }
    pick.userData.elec = p;
    (CEILING_KINDS.has(p.type) ? ceilingBits : group).add(pick);
    picks.push(pick);
    built.items.push({ p, obj, pick });
    markers.add(marker(THREE, p, world));
  }
  for (const l of data.lines || []) {
    const len = Math.hypot(l.x1 - l.x0, l.y1 - l.y0), mid = new THREE.Vector3((l.x0 + l.x1) / 2, l.h, -(l.y0 + l.y1) / 2);
    const ang = Math.atan2(-(l.y1 - l.y0), l.x1 - l.x0);
    if (l.status !== "existing") {
      const s = new THREE.Mesh(new THREE.BoxGeometry(len, 0.012, 0.02), M.led);
      s.position.copy(mid); s.rotation.y = -ang; ceilingBits.add(s);
    }
    const pick = new THREE.Mesh(new THREE.BoxGeometry(len, 0.12, 0.14), M.pick);
    pick.position.copy(mid); pick.rotation.y = -ang;
    const p = { ...l, type: "led", facing: null };
    pick.userData.elec = p;
    group.add(pick); picks.push(pick);
    markers.add(marker(THREE, p, mid));
  }
  built.setXray = on => (markers.visible = on);
  return built;
}

const spriteMats = new Map();
function marker(THREE, p, at) {
  const k = KINDS[p.type] || KINDS.socket;
  const key = p.type;
  if (!spriteMats.has(key)) {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const g = c.getContext("2d");
    g.fillStyle = k.col; g.strokeStyle = "#1b1815"; g.lineWidth = 5;
    g.beginPath(); g.arc(32, 32, 26, 0, Math.PI * 2); g.fill(); g.stroke();
    const t = k.glyph.length <= 2 ? k.glyph : "";
    if (t) { g.fillStyle = "#1b1815"; g.font = `700 ${t.length > 1 ? 24 : 30}px Inter, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(t, 32, 34); }
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    spriteMats.set(key, new THREE.SpriteMaterial({ map: tex, depthTest: false, depthWrite: false, sizeAttenuation: false, toneMapped: false }));
  }
  const s = new THREE.Sprite(spriteMats.get(key));
  const sz = p.type === "spot" ? 0.016 : ["db", "lcp", "router"].includes(p.type) ? 0.03 : 0.022;
  s.scale.set(sz, sz, 1);
  s.userData.size = sz;
  s.position.copy(at);
  s.renderOrder = 10;
  s.userData.elec = p;
  return s;
}

// Hover / look-at / tap names the point; the Electrical button shows the markers.
// isActive(): free to look (no tween, measuring, moving); isLocked(): Walk with the mouse captured (aim = screen centre).
export function createElectricalUI({ THREE, camera, renderer, built, occluders = [], isActive, isLocked, isWalk, bar }) {
  const card = makeCard();
  const ray = new THREE.Raycaster(); ray.camera = camera;
  const ndc = new THREE.Vector2();
  let mouse = null, last = 0, xray = false;
  const dom = renderer.domElement;
  dom.addEventListener("pointermove", e => { if (e.pointerType === "mouse") mouse = [e.clientX, e.clientY]; });
  dom.addEventListener("pointerleave", () => { mouse = null; card.hide(); });
  let press = null;
  dom.addEventListener("pointerdown", e => (press = [e.clientX, e.clientY, performance.now()]));
  dom.addEventListener("pointerup", e => {
    if (!press || !isActive() || (isWalk() && isLocked())) return (press = null);
    const moved = Math.hypot(e.clientX - press[0], e.clientY - press[1]), quick = performance.now() - press[2] < 500;
    press = null;
    if (moved > 6 || !quick) return;
    // Walk on a desktop: the click captures the mouse (index.html); only touch and Top pin a card.
    if (isWalk() && e.pointerType === "mouse") return;
    const hit = pick(e.clientX, e.clientY);
    if (hit) card.show(hit, e.clientX, e.clientY, built.byId, true);
    else card.hide(true);
  });
  const visibleChain = o => { for (; o; o = o.parent) if (!o.visible) return false; return true; };
  function pick(sx, sy) {
    ndc.set(sx / innerWidth * 2 - 1, -(sy / innerHeight) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const walk = isWalk();
    ray.far = walk ? 7 : Infinity;
    if (xray) {  // markers: nearest to the pointer on screen wins
      let best = null, bd = 14;
      const v = new THREE.Vector3();
      for (const m of built.markers.children) {
        v.copy(m.position).project(camera);
        if (v.z > 1 || v.z < -1) continue;
        const d = Math.hypot((v.x + 1) / 2 * innerWidth - sx, (1 - v.y) / 2 * innerHeight - sy);
        if (!m.visible) continue;
        if (d < bd) { bd = d; best = m.userData.elec; }
      }
      return best;
    }
    const hits = ray.intersectObjects(built.picks.filter(visibleChain), false);
    if (!hits.length) return null;
    const wall = walk && ray.intersectObjects(occluders, false)[0];  // Top view: the walls are cut, nothing hides
    const h = hits[0];
    if (wall && wall.distance < h.distance - 0.12) return null;  // behind a wall
    return h.object.userData.elec;
  }
  const btn = Object.assign(document.createElement("button"), { id: "elec", className: "tool", title: "Show every electrical, lighting and low-current point (hover one to see what it is)" });
  btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>Electrical`;
  btn.onclick = () => ui.setXray(!xray);
  bar?.after(btn);
  const ui = {
    card, button: btn,
    get xray() { return xray; },
    setXray(on) { xray = on; btn.classList.toggle("on", on); built.setXray(on); },
    update() {
      if (xray) {  // markers keep one size on screen whatever the lens (Top's is 2°), and in Walk only the ones near you show
        const k = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / Math.tan(THREE.MathUtils.degToRad(35)), walk = isWalk();
        for (const m of built.markers.children) {
          m.scale.setScalar(m.userData.size * k);
          m.visible = !walk || m.position.distanceTo(camera.position) < NEAR;
        }
      }
      if (!isActive()) { if (!card.pinned) card.hide(); return; }
      const now = performance.now();
      if (now - last < 90) return;
      last = now;
      const locked = isWalk() && isLocked();
      const at = locked ? [innerWidth / 2, innerHeight / 2] : mouse;
      if (!at) return card.hide();
      const p = pick(at[0], at[1]);
      if (p) card.show(p, at[0], at[1], built.byId);
      else card.hide();
    },
  };
  return ui;
}

// ------------------------------------------------------------------------------------------------ 2D
// Symbols in screen space, sized with the zoom (s = px per metre). hover: the point under the pointer.
export function drawElectrical(ctx, toScreen, s, data, hover = null) {
  const r = Math.max(3, Math.min(9, s * 0.09));
  ctx.save();
  ctx.lineWidth = 1.4;
  for (const l of data.lines || []) {
    const [ax, ay] = toScreen([l.x0, l.y0]), [bx, by] = toScreen([l.x1, l.y1]);
    ctx.strokeStyle = KINDS.led.col; ctx.setLineDash([6, 4]); ctx.lineWidth = hover === l ? 3 : 1.6;
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
  }
  ctx.setLineDash([]);
  const showH = s > 70;
  ctx.font = `${Math.max(8, Math.min(11, s * 0.1))}px Inter, sans-serif`;
  ctx.textBaseline = "middle";
  for (const p of data.points) {
    const k = KINDS[p.type] || KINDS.socket, [x, y] = toScreen([p.x, p.y]);
    const rr = p.type === "spot" ? r * 0.75 : r;
    ctx.strokeStyle = k.col; ctx.fillStyle = k.col; ctx.lineWidth = 1.4;
    ctx.beginPath();
    if (k.glyph === "spot") {
      ctx.arc(x, y, rr, 0, Math.PI * 2); ctx.stroke();
      ctx.moveTo(x - rr * 0.7, y - rr * 0.7); ctx.lineTo(x + rr * 0.7, y + rr * 0.7);
      ctx.moveTo(x + rr * 0.7, y - rr * 0.7); ctx.lineTo(x - rr * 0.7, y + rr * 0.7); ctx.stroke();
    } else if (k.glyph === "pendant") {
      ctx.arc(x, y, rr * 1.1, 0, Math.PI * 2); ctx.stroke(); ctx.beginPath(); ctx.arc(x, y, rr * 0.45, 0, Math.PI * 2); ctx.fill();
    } else if (k.glyph === "wall") {
      ctx.arc(x, y, rr, 0, Math.PI); ctx.closePath(); ctx.fill();
    } else if (k.glyph === "socket") {
      ctx.arc(x, y, rr, 0, Math.PI * 2); ctx.stroke();
      if ((p.gang || 1) > 1) { ctx.beginPath(); ctx.moveTo(x - rr, y); ctx.lineTo(x + rr, y); ctx.stroke(); }
    } else {
      const sq = ["DB", "LC", "R"].includes(k.glyph) ? r * 1.5 : r * 1.05;
      ctx.fillStyle = "#212830"; ctx.fillRect(x - sq, y - sq, 2 * sq, 2 * sq);
      ctx.strokeRect(x - sq, y - sq, 2 * sq, 2 * sq);
      if (r >= 5) {
        ctx.fillStyle = k.col; ctx.textAlign = "center";
        const f = Math.max(7, Math.min(11, sq * (k.glyph.length > 1 ? 0.95 : 1.3)));
        ctx.font = `600 ${f}px Inter, sans-serif`;
        ctx.fillText(p.type === "switch" ? String(p.gangs?.length || 1) : k.glyph, x, y + 0.5);
        ctx.font = `${Math.max(8, Math.min(11, s * 0.1))}px Inter, sans-serif`;
      }
    }
    if (hover === p) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, rr + 4, 0, Math.PI * 2); ctx.stroke(); }
    if (showH && p.h != null && !["spot", "fan", "pendant"].includes(p.type)) {
      ctx.fillStyle = "#e8e2d8b0"; ctx.textAlign = "left";
      ctx.fillText(Math.round(p.h * 100), x + r + 2, y - r);
    }
  }
  ctx.restore();
}

export function pickElectrical(data, toScreen, sx, sy, reach = 10) {
  let best = null, bd = reach;
  for (const p of data.points) {
    const [x, y] = toScreen([p.x, p.y]), d = Math.hypot(x - sx, y - sy);
    if (d < bd) { bd = d; best = p; }
  }
  if (best) return best;
  for (const l of data.lines || []) {
    const [ax, ay] = toScreen([l.x0, l.y0]), [bx, by] = toScreen([l.x1, l.y1]);
    const vx = bx - ax, vy = by - ay, t = Math.max(0, Math.min(1, ((sx - ax) * vx + (sy - ay) * vy) / (vx * vx + vy * vy || 1)));
    if (Math.hypot(ax + vx * t - sx, ay + vy * t - sy) < reach * 0.6) return l;
  }
  return null;
}
