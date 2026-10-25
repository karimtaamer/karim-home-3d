// Furniture, joinery and fittings, room by room. Positions are plan metres in model.js's frame
// (x east, y north, origin at the DWG plan's corner): taken from the DWG furniture layer where
// it has the piece, otherwise standard sizes fitted to the room as the Notion renders show it.
// Heights are metres above the floor.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

// Fixtures modelled from the renders (image-to-3D with Meshy, in models/). Single-material pieces
// are pre-scaled to real size and take a library material (so the render's baked lighting doesn't
// come along); mixed-material pieces keep their own textures and are fitted to size on load.
const gltf = new GLTFLoader();
const scenes = new Map();
function loadScene(url) {
  if (!scenes.has(url)) scenes.set(url, gltf.loadAsync(url).then(g => {
    g.scene.traverse(o => o.isMesh && !o.geometry.attributes.normal && o.geometry.computeVertexNormals());
    return g.scene;
  }));
  return scenes.get(url);
}

// UVs in metres, projected along each face's main axis, so textures keep their real scale.
function metreUVs(g) {
  const p = g.attributes.position, n = g.attributes.normal, uv = [];
  for (let i = 0; i < p.count; i++) {
    const ax = Math.abs(n.getX(i)), ay = Math.abs(n.getY(i)), az = Math.abs(n.getZ(i));
    if (ax >= ay && ax >= az) uv.push(p.getZ(i), p.getY(i));
    else if (ay >= az) uv.push(p.getX(i), p.getZ(i));
    else uv.push(p.getX(i), p.getY(i));
  }
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  return g;
}

const FACING = { S: 0, E: Math.PI / 2, N: Math.PI, W: -Math.PI / 2 };

export function furnish(scene, M, mat, version = "main") {
  const root = new THREE.Group();
  const ceilingBits = new THREE.Group();  // shown only with the ceiling (downlights, grilles)
  scene.add(root, ceilingBits);
  if (version === "as-built") return { root, ceilingBits, setReveal() {} };  // the empty flat as it stands today

  // Make the existing master-bedroom entry leaf interactive without altering its opening.
  if (version === "kareems-changes") {
    const s = (M.swings || []).find(s => Math.hypot(s.hinge[0] - 5.5724, s.hinge[1] - 5.6626) < 0.15);
    if (s) {
      const [hx, hy] = s.hinge;
      const leaf = scene.children.find(o => o.isMesh && o.geometry?.type === "BoxGeometry" &&
        Math.abs(o.geometry.parameters.width - (s.r - 0.02)) < 0.001 &&
        Math.abs(o.geometry.parameters.height - (M.doorHead - 0.01)) < 0.001 &&
        Math.abs(Math.hypot(o.position.x - hx, o.position.z + hy) - s.r / 2) < 0.03);
      if (leaf) {
        const a0 = Math.atan2(s.closed[1] - hy, s.closed[0] - hx);
        const current = leaf.rotation.y;
        const swing = Math.atan2(Math.sin(current - a0), Math.cos(current - a0));
        const c = new THREE.Group(), hinge = new THREE.Group();
        root.add(c); c.add(hinge);
        hinge.position.set(hx, 0, -hy);
        hinge.rotation.y = a0;
        hinge.add(leaf);
        leaf.position.set(s.r / 2, (M.doorHead - 0.01) / 2, 0);
        leaf.rotation.set(0, 0, 0);
        c.userData.openable = {
          id: "master-bedroom-entry-door", label: "Bedroom door",
          leaves: [{ obj: hinge, axis: "y", open: Math.abs(swing) > 0.1 ? swing : -Math.PI / 2 }],
          anchor: new THREE.Vector3(hx + (s.closed[0] - hx) * 0.75, 1.05, -hy - (s.closed[1] - hy) * 0.75),
          reach: 2.2, duration: 0.7
        };
      }
    }
  }

  function mesh(geo, material, parent, uv = true) {
    if (uv) metreUVs(geo);
    const m = new THREE.Mesh(geo, material);
    m.castShadow = !material.transparent;
    m.receiveShadow = true;
    parent.add(m);
    return m;
  }

  // An item is built in its own frame (x across, y up, z out from the wall it backs onto, back
  // at z = 0), then placed with its back-centre on a plan point, facing N/E/S/W into the room.
  function item(x, y, facing, build, parent = root) {
    const g = new THREE.Group();
    build(part(g));
    g.position.set(x, 0, -y);
    g.rotation.y = typeof facing === "number" ? facing : FACING[facing];
    // For the Move tool (move.js / move_tool.py): where this item( call sits in furnish.js and what it was given.
    g.userData.piece = { x, y, facing, lines: callLines() };
    parent.add(g);
    return g;
  }
  // Move tool resizes: sized(item(...), across, out) scales an item in its own frame (height untouched).
  const sized = (g, sx, sz) => (g.scale.set(sx, 1, sz), g);
  // furnish.js line numbers on the call stack (item()'s own frame left out), e.g. a helper's line and its caller's.
  const ME = import.meta.url.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  function callLines() {
    const rx = new RegExp(ME + ":(\\d+):\\d+", "g");
    const out = [];
    for (const m of String(new Error().stack || "").matchAll(rx)) out.push(+m[1]);
    return out.slice(2);  // [0] callLines, [1] item
  }
  // Materials that arrive with loaded models join the shared cut plane and the fade-in.
  const late = [];
  let revealT = 1;
  function adopt(m) {
    if (m.userData.adopted) return;
    m.userData.adopted = true;
    m.clippingPlanes = mat.ceramic.clippingPlanes;
    m.userData.baseOpacity = m.opacity;
    late.push(m);
    fade(m, revealT);
  }
  function fade(m, t) {
    const want = t < 0.999 || m.userData.baseOpacity < 1;
    if (m.transparent !== want) { m.transparent = want; m.needsUpdate = true; }
    m.opacity = m.userData.baseOpacity * t;
  }

  function part(g) {
    const api = {
      g,
      box(x0, x1, y0, y1, z0, z1, material, r = 0) {
        const w = x1 - x0, h = y1 - y0, d = z1 - z0;
        const geo = r > 0 ? new RoundedBoxGeometry(w, h, d, 3, Math.min(r, w / 2, h / 2, d / 2) * 0.999) : new THREE.BoxGeometry(w, h, d);
        const m = mesh(geo, material, g);
        m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
        return m;
      },
      cyl(x, z, r, y0, y1, material, seg = 32, r2 = r) {
        const m = mesh(new THREE.CylinderGeometry(r, r2, y1 - y0, seg), material, g);
        m.position.set(x, (y0 + y1) / 2, z);
        return m;
      },
      // A flat panel on the item's front plane (z), e.g. art, mirrors, screens.
      face(x0, x1, y0, y1, z, material, uv = false) {
        const m = mesh(new THREE.PlaneGeometry(x1 - x0, y1 - y0), material, g, uv);
        m.position.set((x0 + x1) / 2, (y0 + y1) / 2, z);
        return m;
      },
      // Arch-topped panel (doors, niches, shower opening), extruded `d` deep from z0.
      arch(x0, x1, y0, y1, z0, d, material) {
        const w = x1 - x0, r = w / 2, s = new THREE.Shape();
        s.moveTo(x0, y0); s.lineTo(x1, y0); s.lineTo(x1, y1 - r);
        s.absarc(x0 + r, y1 - r, r, 0, Math.PI, false);
        s.lineTo(x0, y0);
        const m = mesh(new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false, curveSegments: 24 }), material, g);
        m.position.z = z0;
        return m;
      },
      // Panel with only its top corners rounded (doors, as the renders draw them), `d` deep from z0.
      roundTop(x0, x1, y0, y1, r, z0, d, material) {
        const s = new THREE.Shape();
        s.moveTo(x0, y0); s.lineTo(x1, y0); s.lineTo(x1, y1 - r); s.absarc(x1 - r, y1 - r, r, 0, Math.PI / 2, false);
        s.lineTo(x0 + r, y1); s.absarc(x0 + r, y1 - r, r, Math.PI / 2, Math.PI, false); s.lineTo(x0, y0);
        const m = mesh(new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false, curveSegments: 16 }), material, g);
        m.position.z = z0;
        return m;
      },
      // Pebble-shaped mirror w x h centred on (x, y), optionally glowing round its edge.
      pebble(x, y, w, h, z, material, halo) {
        const pts = [[-1, -0.15], [-0.75, -0.85], [0.05, -1], [0.85, -0.75], [1, 0.05], [0.7, 0.8], [-0.1, 1], [-0.8, 0.72]]
          .map(([u, v]) => new THREE.Vector3(u * w / 2, v * h / 2, 0));
        const outline = new THREE.CatmullRomCurve3(pts, true).getPoints(64).map(v => new THREE.Vector2(v.x, v.y));
        const add = (k, m, dz) => {
          const o = mesh(new THREE.ShapeGeometry(new THREE.Shape(outline)), m, g, false);
          o.scale.set(k, k, 1); o.position.set(x, y, z + dz);
        };
        if (halo) add(1 + 0.07 / Math.min(w, h), mat.ledStrip, -0.004);
        add(1, material, 0);
      },
      // A modelled fixture from models/, back at z, base at height y. material: library material,
      // or null to keep the model's own textures. fit: { size: [w, h, d] } or { width } / { height }
      // (uniform) to scale it on load; cross: also a copy turned 90 degrees (flat foliage cut-outs).
      model(url, material, x, y, z, { size, width, height, cross = false } = {}) {
        const holder = new THREE.Group();
        holder.position.set(x, y, z);
        g.add(holder);
        loadScene(url).then(src => {
          const o = src.clone(true);
          o.traverse(m => {
            if (!m.isMesh) return;
            if (material) m.material = material;
            else adopt(m.material);
            m.castShadow = m.receiveShadow = true;
          });
          if (size || width || height) {
            const s = new THREE.Box3().setFromObject(o).getSize(new THREE.Vector3());
            if (size) o.scale.set(size[0] / s.x, size[1] / s.y, size[2] / s.z);
            else o.scale.setScalar(width ? width / s.x : height / s.y);
          }
          if (!size && !width && !height && !cross) return void holder.add(o);  // pre-fitted (parts keep their alignment)
          const copies = cross ? [0, Math.PI / 2] : [0];
          for (const turn of copies) {
            const c = turn ? o.clone(true) : o, wrap = new THREE.Group();
            wrap.add(c);
            wrap.rotation.y = turn;
            wrap.updateMatrixWorld(true);
            const b = new THREE.Box3().setFromObject(c);
            c.position.set(-(b.min.x + b.max.x) / 2, -b.min.y, cross ? -(b.min.z + b.max.z) / 2 : -b.min.z);
            holder.add(wrap);
          }
        });
        return holder;
      },
      // Oval or organic mirror: a flat ellipse, optionally glowing round its edge.
      oval(x, y, rx, ry, z, material, halo) {
        if (halo) {
          const h = mesh(new THREE.CircleGeometry(1, 48), mat.ledStrip, g, false);
          h.scale.set(rx + 0.035, ry + 0.035, 1);
          h.position.set(x, y, z - 0.004);
        }
        const m = mesh(new THREE.CircleGeometry(1, 48), material, g, false);
        m.scale.set(rx, ry, 1);
        m.position.set(x, y, z);
        return m;
      },
      // A named part, built by build(p) in a child group at the item's origin: Generate Photo Spot lists what the
      // view shows by these names (and by spotnames.js words), so the image model knows what each grey shape is.
      label(text, build) {
        const c = new THREE.Group();
        c.userData.label = text;
        c.userData.part = true;  // the Move tool can pick it on its own
        g.add(c);
        build(part(c));
        return c;
      },
    };
    return api;
  }
  // The same for a whole item (the helpers below): its name in Generate Photo Spot's list.
  const named = (g, text) => ((g.userData.label = text), g);

  // --- Reusable pieces ----------------------------------------------------------------------
  // Warm grey veined stone (kitchen splashback, guest vanity top) and soft shadow gaps between fronts.
  const greyStone = mat.marbleTop.clone();
  greyStone.color.setRGB(0.72, 0.67, 0.62);
  greyStone.clippingPlanes = mat.marbleTop.clippingPlanes;
  const shadowGap = mat.greyLacquer.clone();
  shadowGap.color.setRGB(0.12, 0.11, 0.1);
  shadowGap.clippingPlanes = mat.greyLacquer.clippingPlanes;
  // Paler honey oak for lit niche linings: the renders' niches glow light against the plaster.
  const honeyOak = mat.oakVeneer.clone();
  honeyOak.color.setRGB(1.55, 1.3, 1.0);
  honeyOak.clippingPlanes = mat.oakVeneer.clippingPlanes;
  // Potted olive-style tree: a few branches, each carrying a spray of small leaves (one merged mesh).
  // base: height the pot stands on (set after item(), which places items on the floor).
  const plant = (x, y, h = 1.4, pot = 0.22, base = 0) => { const g = item(x, y, "S", p => {
    p.cyl(0, 0, pot, 0, pot * 1.6, mat.planter, 24, pot * 0.8);
    let s = Math.abs(Math.round(x * 97 + y * 13)) + 1;
    const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
    const leaves = [], spread = 0.28 * (h / 1.4);
    for (let b = 0; b < 5; b++) {
      const a = rnd() * Math.PI * 2, top = new THREE.Vector3(Math.cos(a) * spread * 0.5, h * (0.7 + rnd() * 0.3), Math.sin(a) * spread * 0.5);
      const stem = new THREE.Vector3(0, pot * 1.6, 0);
      const twig = mesh(new THREE.CylinderGeometry(0.008, 0.014, top.distanceTo(stem), 5), mat.walnut, p.g);
      twig.position.copy(stem).lerp(top, 0.5);
      twig.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), top.clone().sub(stem).normalize());
      const size = Math.min(1, 0.55 + h / 4);
      for (let k = 0; k < 110; k++) {
        const l = new THREE.SphereGeometry(1, 5, 3);
        l.scale(0.05 * size, 0.012 * size, 0.02 * size);
        l.rotateY(rnd() * Math.PI * 2); l.rotateZ((rnd() - 0.5) * 1.6);
        const r = spread * Math.cbrt(rnd()), u = rnd() * Math.PI * 2, v = Math.acos(2 * rnd() - 1);
        l.translate(top.x + r * Math.sin(v) * Math.cos(u), top.y - 0.12 + r * 0.8 * Math.cos(v), top.z + r * Math.sin(v) * Math.sin(u));
        leaves.push(l);
      }
    }
    mesh(mergeGeometries(leaves), mat.leaf, p.g, false);
  }); g.position.y = base; return named(g, base > 0.3 ? "small potted plant" : "potted plant"); };
  const rug = (x0, y0, x1, y1, m = mat.rug) => named(item((x0 + x1) / 2, (y0 + y1) / 2, "S", p => p.box(-(x1 - x0) / 2, (x1 - x0) / 2, 0.003, 0.016, -(y1 - y0) / 2, (y1 - y0) / 2, m, 0.006)), "rug");
  const art = (x, y, facing, w, h, zc, k, light = true) => named(item(x, y, facing, p => {
    p.box(-w / 2 - 0.025, w / 2 + 0.025, zc - h / 2 - 0.025, zc + h / 2 + 0.025, 0, 0.03, mat.walnut);
    p.face(-w / 2, w / 2, zc - h / 2, zc + h / 2, 0.031, mat.art[k % mat.art.length]);
    if (light) {
      p.box(-0.015, 0.015, zc + h / 2 + 0.06, zc + h / 2 + 0.14, 0, 0.1, mat.brass);
      p.box(-w * 0.25, w * 0.25, zc + h / 2 + 0.04, zc + h / 2 + 0.08, 0.06, 0.13, mat.brass, 0.015);
    }
  }), light ? "framed artwork with a picture light" : "framed artwork");
  // Wall-mounted split AC: w wide, h tall, d deep, top at `top`; `vane` adds the louvre slot along the underside front.
  const ac = (x, y, facing, top = 2.5, w = 0.9, h = 0.3, d = 0.22, vane = false) => named(item(x, y, facing, p => {
    p.box(-w / 2, w / 2, top - h, top, 0, d, mat.applianceWhite, 0.04);
    if (vane) p.box(-w / 2 + 0.06, w / 2 - 0.06, top - h + 0.025, top - h + 0.06, d - 0.004, d + 0.002, mat.grille);
  }), "wall-mounted split AC unit");
  const sconce = (x, y, facing, z = 1.8) => named(item(x, y, facing, p => {
    p.box(-0.04, 0.04, z - 0.14, z + 0.14, 0, 0.03, mat.brass);
    p.cyl(0, 0.08, 0.05, z - 0.1, z + 0.12, mat.lampShade, 20);
  }), "wall sconce");
  const pendant = (x, y, drop, shape = "globe") => named(item(x, y, "S", p => {
    p.cyl(0, 0, 0.004, drop, M.ceiling, shape === "globe" ? mat.brass : mat.blackSteel, 6);
    if (shape === "globe") {
      const s = mesh(new THREE.SphereGeometry(0.1, 24, 16), mat.lampShade, p.g);
      s.position.y = drop - 0.08;
    } else {
      p.cyl(0, 0, 0.14, drop - 0.24, drop, mat.lampShade, 10, 0.14);
    }
  }), "pendant light");
  function sofa(p, w, depth, fabric, cushions = [], plinth = mat.walnut) {
    p.box(-w / 2 + 0.04, w / 2 - 0.04, 0.04, 0.2, 0.02, depth - 0.04, plinth, 0.02);
    p.box(-w / 2 + 0.16, w / 2 - 0.16, 0.2, 0.44, 0.2, depth, fabric, 0.06);
    p.box(-w / 2, w / 2, 0.2, 0.86, 0, 0.24, fabric, 0.08);
    for (const s of [-1, 1]) p.box(s * w / 2 - (s > 0 ? 0.18 : 0), s * w / 2 + (s < 0 ? 0.18 : 0), 0.2, 0.62, 0, depth, fabric, 0.07);
    cushions.forEach((c, k) => {
      const cx = -w / 2 + 0.45 + k * ((w - 0.9) / Math.max(1, cushions.length - 1));
      const m = p.box(cx - 0.22, cx + 0.22, 0.45, 0.88, 0.24, 0.38, c, 0.08);
      m.rotation.x = -0.18;
    });
  }
  function chair(p, fabric = mat.oatmeal, legs = mat.walnut) {  // tub chair: curved shell back, splayed walnut legs
    for (const [lx, lz] of [[-0.18, 0.1], [0.18, 0.1], [-0.18, 0.42], [0.18, 0.42]]) p.cyl(lx, lz, 0.017, 0, 0.45, legs, 8, 0.012).rotation.set((lz - 0.26) * 0.5, 0, -lx * 0.6);
    const seat = p.cyl(0, 0.27, 0.24, 0.42, 0.52, fabric, 28); seat.scale.z = 0.92;
    const a = 1.6, shell = new THREE.Shape();  // shape v = -z, so the arc wraps the back of the seat
    shell.absarc(0, -0.27, 0.26, Math.PI / 2 - a, Math.PI / 2 + a, false);
    shell.absarc(0, -0.27, 0.205, Math.PI / 2 + a, Math.PI / 2 - a, true);
    const geo = new THREE.ExtrudeGeometry(shell, { depth: 0.3, bevelEnabled: true, bevelThickness: 0.02, bevelSize: 0.02, bevelSegments: 3, curveSegments: 24 });
    geo.rotateX(-Math.PI / 2);
    mesh(geo, fabric, p.g).position.y = 0.52;
  }
  // Groove lines between door fronts on a run of joinery (front face at z).
  function fronts(p, x0, x1, y0, y1, z, width = 0.6) {
    const n = Math.max(1, Math.round((x1 - x0) / width));
    for (let k = 1; k < n; k++) p.box(x0 + k * (x1 - x0) / n - 0.002, x0 + k * (x1 - x0) / n + 0.002, y0 + 0.01, y1 - 0.01, z, z + 0.003, mat.grille);
  }
  function vanityDrawers(p, x0, x1, y0, y1, depth, wood = mat.walnut) {
    p.box(x0, x1, y0, y1, 0, depth, wood);
    const n = Math.max(1, Math.round((x1 - x0) / 0.6));
    for (let k = 1; k < n; k++) p.box(x0 + k * (x1 - x0) / n - 0.002, x0 + k * (x1 - x0) / n + 0.002, y0 + 0.02, y1 - 0.02, depth, depth + 0.003, mat.darkTop);
  }

  // --- Living room (TV room), per the living-room renders: one L corner sofa backing onto the west
  // window wall, its return (chaise) along the south wall on the left as you face it, the TV wall
  // opposite, framed art on both side walls, the split AC high on the north (door) wall by the window.
  item(0, 0, "S", p => {  // DWG corner sofa: west run x 2.95-3.98, y 0.58-4.22; return x 3.98-4.80, y 0.58-1.61
    const B = (x0, x1, y0, y1, h0, h1, m, r = 0) => p.box(x0, x1, h0, h1, -y1, -y0, m, r);
    const X0 = 2.95, X1 = 3.98, XC = 4.80, Y0 = 0.58, YC = 1.606, Y1 = 4.219, fab = mat.greige;
    B(X0 + 0.03, X1 - 0.03, Y0 + 0.03, Y1 - 0.03, 0, 0.08, shadowGap);  // recessed plinth
    B(X1 - 0.03, XC - 0.03, Y0 + 0.03, YC - 0.03, 0, 0.08, shadowGap);
    for (const [a, b] of [[Y0, YC], [1.602, 2.428], [2.424, 3.249], [3.245, 4.045]])  // seat modules
      B(X0 + 0.15, X1, a + (a === Y0 ? 0.15 : 0.005), b - 0.005, 0.08, 0.44, fab, 0.07);
    B(X1, XC, Y0 + 0.15, YC, 0.08, 0.44, fab, 0.07);  // the return (chaise) seat, open end
    B(X0, X0 + 0.16, Y0, Y1, 0.08, 0.72, fab, 0.06);  // low backs along both walls
    B(X0, XC, Y0, Y0 + 0.16, 0.08, 0.72, fab, 0.06);
    B(X0, X1, 4.045, Y1, 0.08, 0.6, fab, 0.07);  // arm at the north end
    for (const [a, b] of [[Y0 + 0.16, YC], [1.606, 2.428], [2.428, 3.249], [3.249, 4.045]])  // back cushions
      B(X0 + 0.14, X0 + 0.36, a + 0.01, b - 0.01, 0.42, 0.84, fab, 0.09).rotation.z = 0.12;
    B(X1 + 0.01, XC - 0.01, Y0 + 0.14, Y0 + 0.36, 0.42, 0.84, fab, 0.09).rotation.x = 0.12;
    // Scatter cushions as rendered: blush and sage in the corner, sage, slate and mustard along the run.
    const cushion = (x, y, m, along) => B(x - (along ? 0.07 : 0.21), x + (along ? 0.07 : 0.21), y - (along ? 0.21 : 0.07), y + (along ? 0.21 : 0.07), 0.44, 0.84, m, 0.08);
    cushion(3.55, Y0 + 0.42, mat.linenBlush, false); cushion(X0 + 0.42, 1.25, mat.linenSage, true);
    cushion(X0 + 0.42, 2.45, mat.linenSage, true); cushion(X0 + 0.42, 3.05, mat.linenSlate, true); cushion(X0 + 0.42, 3.6, mat.cushionMustard, true);
    B(X1 + 0.05, X1 + 0.55, Y0 + 0.4, YC - 0.05, 0.44, 0.47, mat.linenSage, 0.012);  // sage throw over the chaise
    B(2.937, X1, 4.219, 4.442, 0, 0.55, mat.walnut, 0.02);  // DWG end table between the arm and the north wall
  });
  rug(3.75, 0.95, 5.55, 3.95, mat.rug);  // cream shaggy rug
  item(2.94, 2.8, "E", p => p.box(-1.75, 1.75, 2.5, 2.52, 0.02, 0.2, mat.ledStrip));  // cove light over the window wall
  item(4.645, 2.529, "S", p => {  // DWG coffee table 0.72 x 1.23: light stone top on two round walnut pedestals
    p.box(-0.36, 0.36, 0.36, 0.42, -0.617, 0.617, mat.stoneTable, 0.03);
    for (const z of [-0.33, 0.33]) p.cyl(0, z, 0.13, 0, 0.36, mat.walnut, 24);
    p.cyl(-0.05, -0.15, 0.1, 0.42, 0.47, mat.walnut, 20, 0.06);  // fruit bowl, vase, books, candle
    p.cyl(0.05, 0.12, 0.05, 0.42, 0.6, mat.planter, 16, 0.04);
    p.box(0.02, 0.22, 0.42, 0.48, 0.3, 0.48, mat.oatmeal);
  });
  item(6.15, 2.25, "W", p => p.box(-1.75, 1.75, 0, M.ceiling, 0, 0.012, mat.limewashTaupe));
  item(6.16, 2.25, "W", p => {  // DWG TV unit on the east wall: floating walnut console, 3 drawers, light top
    p.box(-0.87, 0.87, 0.45, 0.72, 0, 0.4, mat.walnut);
    fronts(p, -0.87, 0.87, 0.45, 0.72, 0.4, 0.58);
    p.box(-0.87, 0.87, 0.72, 0.75, 0, 0.42, mat.stoneTable);
    p.box(-0.87, 0.87, 0.43, 0.45, 0.05, 0.36, mat.ledStrip);
    p.box(-0.8, 0.8, 1.1, 1.95, 0, 0.05, mat.screen);
    for (const s of [-1, 1]) {  // thin vertical sconces either side of the TV
      p.box(s * 1.15 - 0.012, s * 1.15 + 0.012, 1.15, 1.9, 0, 0.03, mat.brass);
      p.box(s * 1.15 - 0.01, s * 1.15 + 0.01, 1.17, 1.88, 0.03, 0.04, mat.ledStrip);
      p.cyl(s * 1.15, 0.035, 0.035, 1.5, 1.52, mat.brass, 16);
    }
    p.cyl(0.62, 0.2, 0.06, 0.75, 0.93, mat.planter, 16, 0.045);  // vases on the console
    p.cyl(-0.62, 0.2, 0.05, 0.75, 0.88, mat.planter, 16, 0.04);
  });
  if (version !== "kareems-changes") plant(5.12, 0.84, 1.8, 0.24);  // tall olive by the end of the chaise (removed on Kareem's via Edit AI)
  plant(5.9, 1.08, 1.35, 0.2);   // beside the TV console
  art(3.62, 0.548, "N", 0.9, 1.25, 1.62, 0);  // large abstracts on both side walls, picture lights above
  art(4.35, 4.443, "S", 0.75, 1.0, 1.48, 1);
  ac(2.945, 1.2, "E", 2.38);  // split AC high on the window wall, between the south wall and the left curtain, under the cove
  for (const y of [2.0, 3.59]) item(2.94, y, "E", p => { const m = mesh(curtainGeometry(0.5, 2.45), mat.curtain, p.g); m.position.set(0, 1.27, 0.06); });

  // --- Master bedroom and bathroom: the same pieces in both plan versions, placed per version -----
  // King bed, built against its headboard wall: w wide, l long from the wall (headboard included),
  // headboard panels head wide in all (wider than the bed in Main and v9, inside the outline in v12).
  const bed = (w = 1.9, l = 2.15, head = 2.76) => p => {
    const h = w / 2, pitch = head / 3;
    for (const k of [-1, 0, 1]) p.box(k * pitch - pitch / 2 + 0.01, k * pitch + pitch / 2 - 0.01, 0.25, 1.25, 0, 0.1, mat.boucle, 0.04);
    p.box(-h, h, 0.06, 0.32, 0.08, l, mat.oakVeneer, 0.02);
    p.box(-h + 0.03, h - 0.03, 0.32, 0.56, 0.12, l - 0.05, mat.sheet, 0.06);
    p.box(-h + 0.01, h - 0.01, 0.5, 0.6, 0.85, l - 0.02, mat.linenSage, 0.04);
    p.box(-h, h, 0.54, 0.62, l - 0.6, l - 0.25, mat.boucle, 0.03);
    for (const [x, c, z, w] of [[-0.48, mat.sheet, 0.14, 0.3], [0.48, mat.sheet, 0.14, 0.3], [-0.45, mat.linenBlush, 0.3, 0.27], [0.45, mat.linenBlush, 0.3, 0.27], [0, mat.boucle, 0.42, 0.22]]) {
      const m = p.box(x - w, x + w, 0.56, 0.86 - (z > 0.4 ? 0.1 : 0), z, z + 0.16, c, 0.07);
      m.rotation.x = -0.25;
    }
    p.box(-h, h, 0.6, 0.63, l - 0.85, l - 0.5, mat.boucle, 0.01);
  };
  const nightstand = (w = 0.48, d = 0.42) => p => {  // w across, d deep
    p.box(-w / 2, w / 2, 0.22, 0.55, 0, d, mat.walnut);
    p.box(-w / 2 + 0.02, w / 2 - 0.02, 0.37, 0.374, d, d + 0.003, mat.grille);
    for (const [lx, lz] of [[-w / 2 + 0.04, 0.05], [w / 2 - 0.04, 0.05], [-w / 2 + 0.04, d - 0.05], [w / 2 - 0.04, d - 0.05]]) p.cyl(lx, lz, 0.014, 0, 0.22, mat.walnut, 6);
  };
  // centred: trough, mixer and mirror on the vanity's centreline (Nagham's Changes); otherwise 6 cm off it, as in the renders.
  // d: depth from the wall face; above: what hangs over the basin in place of the backlit mirror (Kareem's cabinet);
  // body: builds the floating body in place of the modelled one (Kareem's openable under-sink cabinet).
  const vanity = (w = 1.4, centred = false, d = 0.52, above = null, body = null) => p => {  // DWG vanity 0.51 deep, w long (1.40 in Main and v9), round basin
    const h = w / 2, c = centred ? 0 : 0.06, t = centred ? 0.2365 : h - 0.34, r = h - 0.14;
    p.box(-h, h, 0, M.ceiling, 0, 0.02, mat.oakSlats);
    if (body) body(p, w, d);
    else p.model("models/mbath-vanity.glb", null, 0, 0.3, 0.02, { size: [w - 0.02, 0.56, d - 0.02] });  // from the renders
    p.box(-h + 0.02, h - 0.02, 0.27, 0.29, 0.05, d - 0.08, mat.ledStrip);
    p.box(c - t, c + t, 0.855, 0.862, 0.12, 0.42, mat.ceramic, 0.003);  // integrated trough
    p.box(c - 0.04, c + 0.04, 1.0, 1.06, 0.02, 0.06, mat.chrome);               // wall mixer
    p.box(centred ? -0.015 : 0.04, centred ? 0.015 : 0.07, 1.02, 1.04, 0.06, 0.2, mat.chrome);  // spout
    p.model("models/plant-vase.glb", null, centred ? -h + 0.16 : -h + 0.2, 0.86, 0.12, { height: 0.38, cross: true });
    if (above) return above(p);
    p.box(c - r, c + r, 1.15, 2.0, 0.02, 0.05, mat.ledStrip, 0.12);
    p.box(c - r + 0.03, c + r - 0.03, 1.18, 1.97, 0.03, 0.06, mat.mirror, 0.12);
  };
  // Mirrored medicine cabinet (Kareem's Changes), w wide from y0 to y1, hung on the 2 cm battens and 0.30 out from
  // them: an oak carcass with 25 cm clear inside, `shelves` glass shelves evenly spaced, and two mirrored leaves
  // hinged at the outer edges, meeting in the middle (opened `open` degrees; 0 = closed). A soft LED halo round the
  // edge on the battens and a strip under the front, onto the basin. Its own group, marked openable (interact.js):
  // the leaves swing out 105 degrees, clear of the side walls, to show the shelves.
  const medCabinet = (w = 0.8, y0 = 1.32, y1 = 2.07, shelves = 3, open = 0) => vanityPart => {
    const c = new THREE.Group(), p = part(c), leaves = [];
    vanityPart.g.add(c);
    const h = w / 2, b = 0.02, f = 0.285, t = 0.018;  // back on the battens, carcass front edge, board
    p.box(-h - 0.02, h + 0.02, y0 - 0.02, y1 + 0.02, b, b + 0.006, mat.ledStrip, 0.02);  // halo
    p.box(-h, h, y0, y1, b, b + 0.012, honeyOak);                                          // back, 25.3 cm to the front edge
    for (const s of [-1, 1]) p.box(s < 0 ? -h : h - t, s < 0 ? -h + t : h, y0, y1, b, f, mat.oakVeneer);  // sides
    for (const y of [y0, y1 - t]) p.box(-h, h, y, y + t, b, f, mat.oakVeneer);              // bottom and top
    const bay = (y1 - y0 - 2 * t) / (shelves + 1);
    for (let k = 0; k <= shelves; k++) {
      const y = y0 + t + k * bay;  // the bottom, then each 8 mm glass shelf
      if (k) p.box(-h + t, h - t, y - 0.008, y, b + 0.012, f - 0.01, mat.clearGlass);
      p.model("models/mbath-bottles.glb", null, k % 2 ? 0.1 : -0.1, y, b + 0.05, { width: 0.3 });
    }
    p.box(-h + 0.03, h - 0.03, y0 - 0.006, y0, f - 0.05, f - 0.02, mat.ledStrip);           // under-cabinet strip
    for (const s of [-1, 1]) {  // leaves: 26 mm oak-edged board with a 6 mm mirror, 3 mm clear of the carcass
      const g = new THREE.Group(), q = part(g);
      g.position.set(s * h, 0, f + 0.003);
      g.rotation.y = s * open * Math.PI / 180;
      p.g.add(g);
      q.box(s < 0 ? 0 : -h + 0.0015, s < 0 ? h - 0.0015 : 0, y0, y1, 0, 0.026, mat.oakVeneer);
      q.box(s < 0 ? 0.003 : -h + 0.0045, s < 0 ? h - 0.0045 : -0.003, y0 + 0.003, y1 - 0.003, 0.026, 0.032, mat.mirror);
      leaves.push({ obj: g, axis: "y", open: s * 105 * Math.PI / 180 });  // the same sign as `open`: free edges swing out (+z)
    }
    c.userData.openable = { id: "medicine-cabinet", label: "Medicine cabinet", leaves, anchor: new THREE.Vector3(0, (y0 + y1) / 2, f + 0.06),
      reach: 1.8, duration: 0.6 };
  };
  // Kareem's floating vanity body, w x d, 0.30 to the 0.86 counter, in place of the modelled one: a mid-oak carcass under a
  // pale oak counter, two handle-less doors hinged at the outer ends on their front corners (they meet the side walls
  // 1 cm off, so they stop at 88 degrees), marked openable (interact.js). Inside: an instant electric water heater flat on
  // the left side panel (as you face it: local -x), its hoses to angle valves on the back, a socket, and the trough's trap.
  const heaterVanity = (p0, w, d) => {
    const c = new THREE.Group(), p = part(c), leaves = [];
    p0.g.add(c);
    const H = w / 2 - 0.01, t = 0.018, F = d - 0.02, y0 = 0.3, y1 = 0.8;  // half width, board, carcass front, body
    const body = mat.oakVeneer.clone(); body.color.setRGB(0.78, 0.55, 0.36); body.clippingPlanes = mat.oakVeneer.clippingPlanes;
    const white = mat.applianceWhite.clone(); white.roughness = 0.75; white.clippingPlanes = mat.applianceWhite.clippingPlanes;
    const top = mat.marbleTop;
    p.box(-H, H, y1, 0.86, 0.02, d, top);                                             // porcelain countertop (Edit AI)
    for (const s of [-1, 1]) p.box(s < 0 ? -H : H - t, s < 0 ? -H + t : H, y0, y1, 0.02, F, body);  // sides
    p.box(-H, H, y0, y0 + t, 0.02, F, body);                                          // bottom
    p.box(-H, H, y1 - t, y1, 0.02, F, body);                                          // top under the counter
    p.box(-H + t, H - t, y0 + t, y1 - t, 0.02, 0.032, honeyOak);                      // back, pale so the inside reads
    const B = 0.032;  // back panel face
    for (const s of [-1, 1]) {  // doors: 20 mm, meeting with a 3 mm gap
      const g = new THREE.Group(), q = part(g);
      g.position.set(s * H, 0, d);
      p.g.add(g);
      q.box(s < 0 ? 0 : -H + 0.0015, s < 0 ? H - 0.0015 : 0, y0, y1, -0.02, 0, body);
      leaves.push({ obj: g, axis: "y", open: s * 88 * Math.PI / 180 });  // the same sign as medCabinet's: free edges swing out (+z)
    }
    // An axis-aligned run of pipe or hose from a to b ([x, y, z]).
    const run = (a, b, r, m) => {
      const k = [0, 1, 2].find(i => a[i] !== b[i]), L = Math.abs(b[k] - a[k]);
      const o = p.cyl(0, 0, r, -L / 2, L / 2, m, 12);
      o.position.set((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2);
      if (k === 0) o.rotation.z = Math.PI / 2;
      if (k === 2) o.rotation.x = Math.PI / 2;
    };
    const path = (pts, r, m) => pts.slice(1).forEach((b, i) => run(pts[i], b, r, m));
    // Instant water heater (Purity / Cemsan SPEED 7.5 kW: 37 x 24 x 10.5 cm), back on the left panel, its face to the middle.
    const x0 = -H + t, x1 = x0 + 0.105, hy0 = 0.37, hy1 = 0.74, hz = 0.3;
    p.box(x0, x1, hy0, hy1, hz - 0.12, hz + 0.12, white, 0.012);
    p.box(x1, x1 + 0.004, 0.53, 0.66, hz - 0.06, hz + 0.06, mat.greyLacquer, 0.003);  // control panel
    const dial = p.cyl(0, 0, 0.022, -0.006, 0.006, mat.grille, 24);                   // temperature dial on the panel
    dial.position.set(x1 + 0.01, 0.6, hz);
    dial.rotation.z = Math.PI / 2;
    p.box(x1 + 0.004, x1 + 0.007, 0.548, 0.554, hz + 0.035, hz + 0.041, mat.downlight);  // power LED
    // Hoses from its bottom (cold in, hot out) to two angle valves on the back panel.
    for (const [hzz, vx, hy] of [[hz - 0.04, -0.36, 0.35], [hz + 0.04, -0.27, 0.33]]) {
      const hx = x0 + 0.05;
      path([[hx, hy0, hzz], [hx, hy, hzz], [hx, hy, 0.075], [vx, hy, 0.075], [vx, 0.4, 0.075]], 0.006, mat.brushedNickel);
      run([vx, 0.42, B], [vx, 0.42, 0.075], 0.012, mat.chrome);                       // valve body
      p.cyl(vx, B + 0.003, 0.022, 0.417, 0.423, mat.chrome, 24).rotation.x = Math.PI / 2;  // rosette
      p.box(vx - 0.006, vx + 0.006, 0.432, 0.46, 0.05, 0.062, mat.chrome, 0.003);     // quarter-turn handle
      run([vx, 0.4, 0.075], [vx, 0.42, 0.075], 0.008, mat.chrome);
    }
    // White socket on the back panel, the heater's cable up and across to it.
    p.box(-0.29, -0.21, 0.62, 0.7, B, B + 0.01, white, 0.004);
    for (const x of [-0.262, -0.238]) p.box(x - 0.003, x + 0.003, 0.655, 0.665, B + 0.01, B + 0.011, shadowGap);
    path([[x0 + 0.05, hy1, hz], [x0 + 0.05, 0.765, hz], [x0 + 0.05, 0.765, 0.06], [-0.25, 0.765, 0.06], [-0.25, 0.68, 0.06], [-0.25, 0.68, B + 0.012]],
      0.004, white);
    // Trough waste: tail down from the counter, a chrome bottle trap, and the arm back into the wall.
    run([0, y1 - t, 0.27], [0, 0.6, 0.27], 0.016, mat.chrome);
    p.cyl(0, 0.27, 0.032, 0.48, 0.62, mat.chrome, 24, 0.032);
    run([0, 0.57, 0.27], [0, 0.57, B], 0.016, mat.chrome);
    p.cyl(0, B + 0.003, 0.03, 0.564, 0.576, mat.chrome, 24).rotation.x = Math.PI / 2;
    // Under the 0.86 counter the inside can't be seen from standing eye height: opening it crouches you to 0.95, turned
    // a little towards the heater.
    c.userData.openable = { id: "vanity-cabinet", label: "Vanity cabinet", leaves, anchor: new THREE.Vector3(0, (y0 + y1) / 2, d + 0.06),
      reach: 1.8, duration: 0.6, peek: 0.95, peekAt: new THREE.Vector3(-0.15, 0.5, 0.3) };
  };
  // DWG wardrobe w long. Default: smoked-glass sliding doors in a gypsum frame. `white`: plain white lacquer
  // leaves with a recessed vertical finger-pull between them (hidden handle), no walnut mullions.
  const wardrobe = (w, door = 1.04, white = false, tinted = false) => p => {
    const h = w / 2, n = Math.max(1, Math.round((w - 0.16) / door));
    p.box(-h, h, 0, M.ceiling, 0, 0.6, mat.whiteLacquer);
    if (tinted) {
      p.box(-h, h, 0, M.ceiling, 0.6, 0.625, mat.masterBronzeFrame);
      const span = (w - 0.08) / n;
      for (let k = 0; k < n; k++) {
        const x0 = -h + 0.04 + k * span;
        p.box(x0 + 0.012, x0 + span - 0.012, 0.045, M.ceiling - 0.045, 0.625, 0.645, mat.masterBronzeReflective);
      }
    } else if (white) {
      const span = (w - 0.16) / n, z0 = 0.6, z1 = 0.62;
      for (let k = 0; k < n; k++) {
        const x0 = -h + 0.08 + k * span, x1 = x0 + span;
        p.box(x0 + 0.002, x1 - 0.002, 0.08, 2.5, z0, z1, mat.whiteLacquer);  // leaf
      }
      for (let k = 1; k < n; k++) {  // recessed pull between leaves: a shallow dark groove, no protruding handle
        const x = -h + 0.08 + k * span;
        p.box(x - 0.007, x + 0.007, 0.35, 1.85, z1 - 0.014, z1, mat.walnut);
      }
    } else {
      p.box(-h + 0.08, h - 0.08, 0.08, 2.5, 0.6, 0.62, mat.bronzeGlass);
      for (let k = 0; k <= n; k++) {
        const x = -h + 0.08 + k * (w - 0.16) / n;
        p.box(x - 0.015, x + 0.015, 0.08, 2.5, 0.62, 0.635, mat.walnut);
      }
    }
  };
  // Plain wall-mounted bidet mixer (no hose or spray gun): round body out from the wall, lever on top, short spout
  // down. Body centre at height y, x across, mounted on the face at z.
  const bidetMixer = (p, x, y, z, metal) => {
    p.cyl(x, z + 0.005, 0.03, y - 0.005, y + 0.005, metal, 32).rotation.x = Math.PI / 2;  // rosette
    p.cyl(x, z + 0.045, 0.025, y - 0.035, y + 0.035, metal, 32).rotation.x = Math.PI / 2;  // body, 7 cm out
    p.box(x - 0.005, x + 0.005, y + 0.022, y + 0.032, z + 0.03, z + 0.1, metal, 0.004);   // lever, pointing out
    p.cyl(x, z + 0.06, 0.007, y - 0.13, y - 0.02, metal, 16);                              // spout, 11 cm down
  };
  const wc = (x0, x1, cabinet, o = {}) => p => {  // wall-hung WC on a slatted wall and ledge running x0..x1, cabinet above
    const d = o.box ?? 0.2, b1 = o.boxTo ?? x1;  // flush-box (ledge) depth from the wall; the box and cabinet end at b1
    p.box(x0, x1, 0, M.ceiling, 0, 0.02, mat.oakSlats);
    p.box(x0, b1, 0, 1.1, 0.02, d, mat.oakSlats);
    p.model("models/wc-wallhung.glb", mat.ceramic, 0, 0.1, d, o.pan ? { size: o.pan } : {});
    bidetMixer(p, -0.3, 0.55, d, mat.chrome);  // on the ledge front, shower side (where the spray gun was), chrome like the master taps
    p.box(-0.12, 0.12, 1.0, 1.08, d, d + 0.01, mat.brass);
    if (cabinet) {
      const c = o.box ? d : 0.32;  // a deep flush box takes a cabinet flush with its front
      const [c0, c1] = o.cab ?? [1.65, 2.45];  // cabinet bottom and top
      p.box(x0, b1, c0, c1, 0, c, mat.oakVeneer);
      p.box(x0 + 0.02, b1 - 0.02, c0 - 0.03, c0 - 0.01, 0.02, c - 0.02, mat.ledStrip);
    }
  };
  const towelRail = p => {  // towel radiator with a hanging towel, clear of the vanity top
    p.model("models/mbath-towel-rail.glb", mat.brushedNickel, 0, 0.95, 0.0);
    p.model("models/mbath-towel.glb", mat.sheet, 0, 0.95, 0.0);
  };
  const showerWall = p => {  // lit niche shelves and a fold-down teak seat
    for (const y of [1.05, 1.45]) {
      p.box(-0.38, 0.38, y - 0.02, y, 0, 0.16, mat.stoneWall);
      p.box(-0.38, 0.38, y + 0.3, y + 0.31, 0, 0.12, mat.ledStrip);
      p.model("models/mbath-bottles.glb", null, 0, y, 0.02, { width: 0.7 });
    }
    p.model("models/mbath-seat-teak.glb", mat.oakVeneer, 0, 0.42, 0.0);
    p.model("models/mbath-seat-brackets.glb", mat.brushedNickel, 0, 0.42, 0.0);
  };
  const rainHead = p => {
    p.cyl(0, 0.38, 0.12, 2.18, 2.2, mat.chrome, 24);
    p.box(-0.01, 0.01, 2.2, M.ceiling, 0.37, 0.39, mat.chrome);
  };

  if (version === "bigger-bedroom") {
    // Bigger Master Bedroom (master-bed-v9.dwg): the bathroom wall moves 0.8 m east, the bed turns to
    // the window wall, and the suite lobby becomes the bathroom's vanity end, entered from the bedroom.
    item(3.185, 9.015, "S", bed());  // DWG bed outline, headboard on the north wall
    for (const x of [2.02, 4.35]) {  // DWG bedside tables
      item(x, 9.015, "S", nightstand());
      pendant(x, 8.83, 1.15);
    }
    rug(1.905, 6.453, 4.465, 8.503);  // DWG rug
    item(2.395, 9.02, "S", p => {  // sheer in the reveal of the window over the bed (as rendered)
      const m = mesh(curtainGeometry(1.1, 1.15), mat.sheer, p.g); m.position.set(0, 1.5, -0.06);
    });
    item(6.245, 6.363, "W", vanity());                // DWG vanity on the east wall, by the door
    item(6.245, 7.3, "W", wc(-0.69, 0.23, false));    // WC between the vanity and the shower
    item(5.015, 7.35, "E", towelRail);                // on the bedroom wall, opposite the WC
    item(6.245, 8.62, "W", showerWall);
    item(5.25, 9.02, "S", rainHead);                  // the shower opening stays open to the ceiling, as rendered
  } else if (version === "shifted-bedroom" || version === "naghams-changes" || version === "kareems-changes") {  // Nagham's Changes: a copy of it for now
    // Shifted Bedroom (master-v12.dwg): the bathroom moves to the west end, the bed's headboard goes on
    // its partition, the wardrobe runs along the kitchen wall and a desk sits on the south wall.
    // Nagham's Changes: the bathroom partition (the headboard wall) sits 14 cm further east, so the bed and
    // bedside tables do too (bed foot 1.40 from the wardrobe).
    const NC = version === "naghams-changes" || version === "kareems-changes", hb = NC ? 2.299 : 2.159;
    item(hb, 7.511, "E", bed(2.101, 1.991, 2.101));  // DWG bed outline 2.10 wide x 1.99 long, headboard inside it
    for (const y of [6.231, 8.79]) {  // DWG bedside tables 0.47 x 0.52 deep
      item(hb, y, "E", nightstand(0.466, 0.516));
      pendant(hb + 0.181, y, 1.15);
    }
    art(hb + 0.003, 7.511, "E", 1.6, 0.95, 1.85, 0);
    for (const x of [2.95, 5.37]) item(x, 9.02, "S", p => {  // curtains either side of the 2.18 m window
      const m = mesh(curtainGeometry(0.55, 2.45), mat.curtain, p.g); m.position.set(0, 1.27, 0.12);
    });
    if (version === "kareems-changes") {
      // Three-gang switch moved to the circled wall spot.
      item(4.516, 5.585, "W", p => {
        p.box(-0.043, 0.043, 1.265, 1.351, 0, 0.008, mat.whiteLacquer);
        for (const x of [-0.025, 0, 0.025]) {
          p.box(x - 0.011, x + 0.011, 1.276, 1.34, 0.008, 0.012, mat.whiteLacquer);
        }
      });
    }
    // Kareem's Changes: white lacquer sliding doors with recessed hidden pulls (other versions keep smoked glass).
    item(6.367, 7.336, "W", wardrobe(3.36, 1.04, version === "kareems-changes", version === "kareems-changes"));  // DWG wardrobe on the kitchen wall
    item(1.564, 4.55, "N", wardrobe(1.895, 0.45, version === "kareems-changes"));  // DWG wardrobe on the south wall, 20 cm shorter for the dresser: four ~43 cm sliding doors
    item(0.556, 5.561, "E", wardrobe(0.872, 1.04, version === "kareems-changes"));  // DWG cupboard by the bathroom door (0.87 long, its end overlaps the south wardrobe front as drawn)
    // DWG dresser 2.00 x 0.45 x 0.75, east end on the lobby wall. Facing it (local -x = east = your left): three
    // drawers under a lit open shelf column, knee space with one shallow drawer and a pouf, fluted cabinet with a
    // glass-topped jewellery tray. Walnut body, pale oak top; backlit pebble mirror over the knee space.
    item(3.517, 4.55, "N", p => {
      const front = (x0, x1, y0, y1) => {  // drawer front with a slim brass pull
        p.box(x0 + 0.002, x1 - 0.002, y0 + 0.002, y1 - 0.002, 0.43, 0.45, mat.walnut);
        p.box((x0 + x1) / 2 - 0.06, (x0 + x1) / 2 + 0.06, y1 - 0.03, y1 - 0.02, 0.45, 0.46, mat.brass);
      };
      for (const [x0, x1] of [[-0.98, -0.52], [0.42, 0.98]]) p.box(x0, x1, 0, 0.05, 0.02, 0.4, shadowGap);  // recessed plinths
      p.box(-1, -0.5, 0.05, 0.72, 0, 0.43, mat.walnut);              // drawer stack carcass
      for (let k = 0; k < 3; k++) front(-1, -0.5, 0.05 + k * 0.2233, 0.05 + (k + 1) * 0.2233);
      p.box(-0.5, 0.4, 0, 0.62, 0, 0.02, mat.walnut);                // knee space back panel
      p.box(-0.5, 0.4, 0.62, 0.72, 0, 0.43, mat.walnut);             // shallow drawer over the knee space
      front(-0.5, 0.4, 0.62, 0.72);
      p.box(0.4, 1, 0.05, 0.6, 0, 0.43, mat.walnut);                 // fluted cabinet
      for (let x = 0.42; x < 0.975; x += 0.025) p.box(x, x + 0.02, 0.07, 0.58, 0.43, 0.45, mat.walnut, 0.008);
      p.box(0.4, 1, 0.6, 0.72, 0, 0.02, mat.walnut);                 // jewellery tray: walnut sides, oak lining, glass front
      for (const x of [0.4, 0.98]) p.box(x, x + 0.02, 0.6, 0.72, 0, 0.45, mat.walnut);
      p.box(0.42, 0.98, 0.6, 0.62, 0.02, 0.45, honeyOak);
      p.box(0.43, 0.97, 0.705, 0.715, 0.03, 0.05, mat.ledStrip);
      for (let x = 0.47; x < 0.95; x += 0.08) p.box(x, x + 0.04, 0.62, 0.635, 0.12, 0.3, mat.brass, 0.005);  // jewellery
      p.box(0.42, 0.98, 0.6, 0.72, 0.44, 0.45, mat.clearGlass);
      p.box(-1, 0.45, 0.72, 0.75, 0, 0.45, mat.oakVeneer);            // pale oak top, glass over the tray
      p.box(0.95, 1, 0.72, 0.75, 0, 0.45, mat.oakVeneer);
      p.box(0.45, 0.95, 0.72, 0.75, 0, 0.05, mat.oakVeneer);
      p.box(0.45, 0.95, 0.72, 0.75, 0.4, 0.45, mat.oakVeneer);
      p.box(0.45, 0.95, 0.735, 0.745, 0.05, 0.4, mat.clearGlass);
      // Open shelf column on the drawer stack, 0.32 wide x 0.30 deep, counter to 2.45: walnut frame, oak lining, lit shelves
      p.box(-1, -0.68, 0.75, 2.45, 0, 0.01, honeyOak);
      for (const x of [-1, -0.7]) p.box(x, x + 0.02, 0.75, 2.45, 0, 0.3, mat.walnut);
      p.box(-1, -0.68, 2.43, 2.45, 0, 0.3, mat.walnut);
      for (const y of [1.09, 1.43, 1.77, 2.11]) p.box(-0.98, -0.7, y - 0.02, y, 0.01, 0.3, mat.walnut);
      for (const y of [1.07, 1.41, 1.75, 2.09, 2.43]) p.box(-0.97, -0.71, y - 0.012, y - 0.002, 0.24, 0.26, mat.ledStrip);
      p.model("models/mbath-bottles.glb", null, -0.84, 0.75, 0.04, { width: 0.24 });
      p.model("models/mbath-bottles.glb", null, -0.84, 1.43, 0.04, { width: 0.22 });
      p.model("models/plant-vase.glb", null, -0.84, 1.77, 0.08, { height: 0.3, cross: true });
      p.model("models/plant-vase.glb", null, -0.58, 0.75, 0.1, { height: 0.4, cross: true });  // on the top, by the column
      p.model("models/mbath-bottles.glb", null, 0.62, 0.75, 0.06, { width: 0.28 });
      p.pebble(-0.05, 1.35, 1.1, 0.75, 0.012, mat.mirror, true);   // 1.10 wide x 0.75 tall, 0.98 to 1.73
      p.cyl(-0.05, 0.25, 0.225, 0, 0.43, mat.boucle, 32);           // pouf 45 x 45, pushed in to 2.5 cm off the back panel
      p.cyl(-0.05, 0.25, 0.215, 0.43, 0.45, mat.boucle, 32, 0.225);
    });
    ac(3.567, 4.55, "N");  // over the mirror (knee-space centre)
    if (NC) {
    const champagne = mat.brass.clone(); champagne.color.setRGB(0.78, 0.67, 0.51); champagne.roughness = 0.5;  // brushed champagne bronze
    champagne.clippingPlanes = mat.brass.clippingPlanes;
    // Nagham's Changes en-suite (DWG): shower in the north-west corner, 0.84 wide x 1.29 deep in front of a 0.21
    // solid build-out on the north wall (burying the column) that carries the concealed mixer, rain arm and hand
    // shower; a 20 cm solid partition (stone-lined, with one wide shelf niche) between it and the basin, and a 2 cm
    // clear glass panel (with its channel) 0.69 long from the build-out face to 0.90 from the north wall, leaving a
    // 0.60 walk-in gap. Fold-up teak seat on the west wall by the partition. WC bay 0.776 wide on the north wall: a
    // concealed-cistern build-out 0.30 deep across the bay, 1.12 high under the 0.60 x 0.60 frosted window (sill 1.50, head 2.10,
    // build --window),
    // porcelain-clad with a porcelain top ledge and a flush plate; wall-hung pan 0.54 long, centred.
    // Vanity 1.153 on the west wall, from its old south end to the partition, bowl centred.
    // Kareem's Changes: the bathroom door sits 0.16 further east, so the vanity runs the whole wall (1.185, south wall
    // to the partition) and is 0.60 deep; the backlit mirror becomes a 0.80 x 0.75 mirrored medicine cabinet, 0.30
    // out from the battens, bottom 1.32 (0.46 over the counter), three glass shelves, all centred on the bowl.
    if (version === "kareems-changes") item(0.556, 6.7276, "E", vanity(1.185, true, 0.6, medCabinet(), heaterVanity));  // centre DWG y -114.8856
    else item(0.556, 6.7435, "E", vanity(1.153, true));  // centre DWG y -114.8697, bowl, mixer and mirror on it
    item(1.8037, 9.0201, "S", p => {  // WC bay 1.416..2.192 (local +x east)
      const h = 0.3878, d = 0.3, top = 1.12;
      p.box(-h, h, 0, top - 0.02, 0, d - 0.01, mat.stoneWall);                      // framed build-out, tiled
      p.box(-h, h, top - 0.02, top, 0, d, mat.stoneWall, 0.004);                    // porcelain top ledge
      p.box(-0.12, 0.12, 0.92, 1.08, d - 0.01, d, mat.brass, 0.005);               // flush plate on the face
      p.model("models/wc-wallhung.glb", mat.ceramic, 0, 0.1, d, { size: [0.36, 0.33, 0.54] });  // pan 0.54 long, as the DWG block
      bidetMixer(p, -0.3, 0.55, d, mat.chrome);
      p.box(-0.335, 0.335, top, 1.5, 0, 0.01, mat.stoneWall);                       // porcelain under the window (0.60 + 3 cm reveals), ledge to sill
    });
    item(1.4059, 8.8101, "S", p => {  // DWG glass: 2 cm with its channel, from the shower build-out face to 0.90 from the north wall, 2.00 tall
      p.box(-0.005, 0.005, 0.01, 2.0, 0, 0.69, mat.clearGlass);
      p.box(-0.01, 0.01, 0, 2.0, 0, 0.02, mat.chrome);
      p.box(-0.01, 0.01, 0, 0.01, 0, 0.69, mat.chrome);
    });
    // Towel radiator on the east wall, 0.29 south of the pan front (DWG y -113.725..-114.175), and three
    // champagne-bronze towel hooks at 1.30 on the 0.61 of plain wall between it and the open door leaf.
    item(2.192, 7.6632, "W", towelRail);
    for (const y of [-114.33, -114.48, -114.63]) item(2.192, y + 121.6132, "W", p => {
      p.cyl(0, 0.014, 0.018, 1.296, 1.304, champagne, 32).rotation.x = Math.PI / 2;  // rosette on the lining
      p.cyl(0, 0.045, 0.006, 1.27, 1.33, champagne, 16).rotation.x = Math.PI / 2;    // arm, 6 cm out
      p.cyl(0, 0.075, 0.009, 1.3, 1.325, champagne, 16);                              // upturned tip
    });
    // Niche in the shower face of the 0.20 solid partition (DWG dashed), centred on the 0.84 width: cut 0.70 wide x
    // 0.15 deep rough (0.05 of wall left behind it on the vanity side), finished 0.67 x 0.135 in porcelain. Three
    // 4 cm porcelain slab shelves with 25.5 cm clear: finished floors 0.895 / 1.19 / 1.485, niche top 1.74, a warm
    // LED under each top. The model carves the rough slot full height (build --cut); the 1 cm stone lining plus
    // 5 mm porcelain here finish it, and porcelain fills it below, between and above (5 mm into the lining).
    item(0.976, 7.5201, "N", p => {
      const floors = [0.895, 1.19, 1.485], top = 1.74, t = 0.04, w = 0.335, d = 0.135, D = 0.155;
      p.box(-w - 0.02, w + 0.02, 0, floors[0], -D, 0, mat.stoneWall);                        // solid below the first floor
      for (const y of floors.slice(1)) p.box(-w - 0.02, w + 0.02, y - t, y, -D, 0, mat.stoneWall); // slab shelves
      p.box(-w - 0.02, w + 0.02, top, M.ceiling, -D, 0, mat.stoneWall);                       // above the top
      for (const x of [-1, 1]) p.box(x < 0 ? -w - 0.02 : w, x < 0 ? -w : w + 0.02, floors[0], top, -D, 0, mat.stoneWall);  // side linings to 0.67
      p.box(-w, w, floors[0], top, -D, -d, mat.stoneWall);                                    // back lining to 0.135
      for (const y of [...floors.slice(1).map(y => y - t), top]) p.box(-w + 0.03, w - 0.03, y - 0.015, y - 0.005, -d + 0.02, -d + 0.04, mat.ledStrip);
      for (const [x, y] of [[-0.18, floors[0]], [0.16, floors[1]], [-0.1, floors[2]]]) p.model("models/mbath-bottles.glb", null, x, y, -d + 0.03, { width: 0.2 });
    });
    // Shower set on the 0.21 north build-out face: concealed thermostatic mixer and diverter on the shower's
    // centreline (east of the column, where the build-out is a full 0.21 deep), rain arm 0.42 out, and the
    // hand-shower outlet and holder at the west end, in front of the buried column.
    item(0.976, 8.8101, "S", p => {
      p.cyl(0, 0.03, 0.075, 1.0, 1.02, mat.chrome, 32).rotation.x = Math.PI / 2;  // thermostatic mixer
      p.cyl(0, 0.045, 0.03, 1.0, 1.07, mat.chrome, 24).rotation.x = Math.PI / 2;
      p.cyl(0, 0.03, 0.06, 1.2, 1.22, mat.chrome, 32).rotation.x = Math.PI / 2;    // 3-way diverter
      p.cyl(0, 0.045, 0.025, 1.2, 1.26, mat.chrome, 24).rotation.x = Math.PI / 2;
      p.box(-0.02, 0.02, 2.1, 2.14, 0, 0.42, mat.chrome);                            // concealed riser, wall arm 0.42 out
      p.cyl(0, 0.42, 0.13, 2.08, 2.1, mat.chrome, 32);                                // rain head
      const hx = -0.28;                                                               // hand shower, west end (column zone)
      p.cyl(hx, 0.01, 0.022, 0.91, 0.93, mat.chrome, 24).rotation.x = Math.PI / 2;
      p.box(hx - 0.008, hx + 0.008, 0.905, 0.935, 0.01, 0.043, mat.chrome);
      p.cyl(hx, 0.035, 0.008, 0.87, 0.92, mat.chrome, 12);
      p.cyl(hx, 0.01, 0.025, 1.07, 1.09, mat.chrome, 24).rotation.x = Math.PI / 2;
      p.box(hx - 0.008, hx + 0.008, 1.07, 1.09, 0.01, 0.045, mat.chrome);
      p.cyl(hx, 0.045, 0.016, 1.06, 1.1, mat.chrome, 16);
      p.cyl(hx, 0.045, 0.011, 0.97, 1.25, mat.chrome, 16);
      p.cyl(hx, 0.045, 0.015, 1.22, 1.27, mat.chrome, 24);
    });
    // Fold-up shower seat on the west wall (DWG dashed), shown open: 0.45 along the wall from 0.05 off the
    // partition face, 0.35 deep, top 0.45; teak-tone slats on brushed champagne-bronze brackets.
    item(0.556, 7.7951, "E", p => {
      const teak = mat.oakVeneer.clone(); teak.color.setRGB(0.85, 0.58, 0.36); teak.clippingPlanes = mat.oakVeneer.clippingPlanes;
      for (let k = 0; k < 5; k++) { const z0 = 0.01 + k * 0.068; p.box(-0.225, 0.225, 0.42, 0.45, z0, z0 + 0.058, teak, 0.004); }  // slats
      for (const x of [-0.19, 0.19]) {
        p.box(x - 0.012, x + 0.012, 0.25, 0.42, 0, 0.012, champagne);                // wall plate
        p.box(x - 0.012, x + 0.012, 0.405, 0.42, 0, 0.33, champagne);                // arm under the slats
        p.box(x - 0.008, x + 0.008, 0.33, 0.345, 0.15 - 0.165, 0.15 + 0.165, champagne).rotation.x = -Math.atan2(0.135, 0.3);  // stay, wall 0.27 to arm end 0.405
      }
    });
    } else {
    // Master bathroom: vanity and WC on the west wall, shower at the north end behind a glass screen
    item(0.556, 6.68, "E", vanity(1.03));             // DWG vanity 0.52 x 1.03
    item(0.556, 7.58, "E", wc(-0.387, 0.416, true, { box: 0.34, pan: [0.36, 0.33, 0.47], cab: [1.4, 2.2] }));  // flush box 34 deep to 1.10; cabinet 1.40-2.20 flush above (30 cm inside, shelves 1.67 and 1.93), vanity to partition; pan 36 x 47 as the DWG block
    item(2.052, 7.113, "W", towelRail);               // east wall south of the WC, clear of the open door leaf and the shower entry
    // Shower (DWG): 1.22 wide x 0.92 deep behind a 10 cm partition on the west, open 0.61 entry on the east. The back
    // (west) wall is built out 28 cm, flush with the column's inner face, from the column to the partition: the 3-way
    // set on the wall centreline (rain arm, thermostatic mixer and diverter), a hand shower on a fixed holder 11 cm
    // clear of the mixer on the partition side, and a stack of lit niches 10 cm clear of the mixer on the column side.
    item(0.836, 8.5033, "E", p => {
      p.cyl(0, 0.03, 0.075, 1.0, 1.02, mat.chrome, 32).rotation.x = Math.PI / 2;  // thermostatic mixer
      p.cyl(0, 0.045, 0.03, 1.0, 1.07, mat.chrome, 24).rotation.x = Math.PI / 2;
      p.cyl(0, 0.03, 0.06, 1.2, 1.22, mat.chrome, 32).rotation.x = Math.PI / 2;    // 3-way diverter
      p.cyl(0, 0.045, 0.025, 1.2, 1.26, mat.chrome, 24).rotation.x = Math.PI / 2;
      p.box(-0.012, 0.012, 1.3, 2.12, 0.04, 0.06, mat.chrome);                      // riser to the arm
      p.box(-0.02, 0.02, 2.1, 2.14, 0, 0.42, mat.chrome);                            // wall arm, 0.42 out
      p.cyl(0, 0.42, 0.13, 2.08, 2.1, mat.chrome, 32);                                // rain head
      const hx = -0.21;                                                               // hand shower, partition side
      p.cyl(hx, 0.01, 0.022, 0.91, 0.93, mat.chrome, 24).rotation.x = Math.PI / 2;   // wall outlet, elbow down
      p.box(hx - 0.008, hx + 0.008, 0.905, 0.935, 0.01, 0.043, mat.chrome);
      p.cyl(hx, 0.035, 0.008, 0.87, 0.92, mat.chrome, 12);
      p.cyl(hx, 0.01, 0.025, 1.07, 1.09, mat.chrome, 24).rotation.x = Math.PI / 2;   // fixed holder
      p.box(hx - 0.008, hx + 0.008, 1.07, 1.09, 0.01, 0.045, mat.chrome);
      p.cyl(hx, 0.045, 0.016, 1.06, 1.1, mat.chrome, 16);
      p.cyl(hx, 0.045, 0.011, 0.97, 1.25, mat.chrome, 16);                           // slim handset
      p.cyl(hx, 0.045, 0.015, 1.22, 1.27, mat.chrome, 24);
      // Hose hanging in a loop: a U at the bottom, one side up to the outlet, the other to the handset
      const r = 0.045, yU = 0.62;
      const u = mesh(new THREE.TorusGeometry(r, 0.006, 8, 24, Math.PI), mat.chrome, p.g);
      u.position.set(hx, yU, 0.035); u.rotation.z = Math.PI;
      for (const [x0, y1] of [[-r, 0.87], [r, 0.97]]) {
        const L = Math.hypot(x0, y1 - yU);
        p.cyl(hx + x0 / 2, 0.035, 0.006, (yU + y1 - L) / 2, (yU + y1 + L) / 2, mat.chrome, 8).rotation.z = Math.atan2(x0, y1 - yU);
      }
    });
    item(2.041, 8.745, "W", p => {  // teak fold-down seat on the east wall at the back, shown open: 0.45 wide x 0.35 deep, top 0.45 (DWG dashed)
      p.model("models/mbath-seat-teak.glb", mat.oakVeneer, 0, 0.35, 0, { size: [0.45, 0.1, 0.35] });
      p.model("models/mbath-seat-brackets.glb", mat.brushedNickel, 0, 0.35, 0, { size: [0.45, 0.1, 0.35] });
    });
    // Niche stack in the back-wall build-out (DWG dashed), column side, 3 cm tile return to the column: four
    // niches 0.20 wide x 0.15 deep x 0.25 clear, floors 0.95 / 1.28 / 1.61 / 1.94 with 8 cm stone bands, a warm LED
    // under each top (sills laid with a slight fall inward). The model carves a slot 1 cm oversize full height (build
    // --cut) so the stone lining finishes it at 20 x 15; stone fills it below, between and above.
    item(0.836, 8.7792, "E", p => {
      const floors = [0.95, 1.28, 1.61, 1.94], c = 0.25;
      p.box(-0.105, 0.105, 0, floors[0], -0.155, 0, mat.stoneWall);  // 5 mm into the lining: no shared faces
      for (const y of floors.slice(1)) p.box(-0.105, 0.105, y - 0.08, y, -0.155, 0, mat.stoneWall);
      p.box(-0.105, 0.105, floors[3] + c, M.ceiling, -0.155, 0, mat.stoneWall);
      for (const y of floors) {
        p.box(-0.08, 0.08, y + c - 0.015, y + c - 0.005, -0.14, -0.12, mat.ledStrip);
        p.model("models/mbath-bottles.glb", null, 0, y, -0.14, { width: 0.16 });
      }
    });
    }
  } else {
    item(4.13, 7.62, "W", bed());  // headboard on the bathroom wall (DWG bed outline)
    for (const y of [8.8, 6.45]) {
      item(4.13, y, "W", nightstand());
      pendant(3.95, y, 1.15);
    }
    art(4.13, 7.62, "W", 1.6, 0.95, 1.85, 0);
    rug(1.56, 6.22, 3.9, 9.0);
    for (const x of [1.72, 3.2]) item(x, 9.02, "S", p => {
      const m = mesh(curtainGeometry(0.55, 2.45), mat.curtain, p.g); m.position.set(0, 1.27, 0.12);
    });
    // Master suite lobby: tall lit shoe cabinet (DWG 0.41 x 0.80)
    item(6.37, 6.06, "W", p => {
      p.box(-0.4, 0.4, 0, 2.4, 0, 0.41, mat.walnut);
      for (let k = 0; k < 7; k++) p.box(-0.37, 0.37, 0.3 + k * 0.3, 0.31 + k * 0.3, 0.05, 0.38, mat.ledStrip);
      p.box(-0.37, 0.37, 0.1, 2.32, 0.39, 0.41, mat.smokedGlass);
    });
    // Master bathroom: vanity west, WC east, arched shower opening to the north
    item(4.22, 7.3, "E", vanity());
    item(6.24, 7.3, "W", wc(-0.55, 0.55, true));
    item(4.52, 8.0, "S", towelRail);  // on the shower partition
    item(6.24, 8.62, "W", showerWall);
    item(5.25, 9.02, "S", rainHead);
    item(5.25, 8.06, "N", p => {  // arch over the shower opening (dashed in the DWG)
      const s = new THREE.Shape();
      s.moveTo(-0.43, 1.85); s.absarc(0, 1.85, 0.43, Math.PI, 0, true); s.lineTo(0.43, M.ceiling); s.lineTo(-0.43, M.ceiling); s.lineTo(-0.43, 1.85);
      const m = mesh(new THREE.ExtrudeGeometry(s, { depth: 0.1, bevelEnabled: false, curveSegments: 24 }), mat.stoneWall, p.g);
      m.position.z = -0.05;
    });
  }
  // The wardrobe, dressing table and shoe display stay on the west and south walls in Main and v9.
  if (version !== "shifted-bedroom" && version !== "naghams-changes" && version !== "kareems-changes") {
    item(0.56, 6.75, "E", wardrobe(4.32));
    item(2.36, 4.55, "N", p => {  // dressing table with the backlit oval mirror
      p.box(-0.53, 0.53, 0.72, 0.76, 0, 0.5, mat.walnut);
      p.box(-0.53, -0.18, 0, 0.72, 0, 0.48, mat.walnut);
      for (const y of [0.24, 0.48]) p.box(-0.52, -0.19, y - 0.002, y + 0.002, 0.48, 0.483, mat.grille);
      p.box(0.2, 0.53, 0, 0.72, 0, 0.48, mat.walnut);
      for (let k = 0; k < 8; k++) p.cyl(0.22 + k * 0.042, 0.48, 0.012, 0.03, 0.7, mat.walnut, 6);
      p.pebble(0, 1.42, 1.04, 0.78, 0.012, mat.mirror, true);
      p.cyl(0, 0.75, 0.2, 0, 0.45, mat.boucle, 24);
    });
    item(3.36, 4.55, "N", p => {  // two lit shoe-display towers
      for (const s of [-1, 1]) {
        const x0 = s < 0 ? -0.47 : 0.01, x1 = s < 0 ? -0.01 : 0.47;
        p.box(x0, x1, 0, 0.12, 0, 0.4, mat.walnut);
        p.box(x0, x1, 2.32, 2.4, 0, 0.4, mat.walnut);
        p.box(x0, x0 + 0.03, 0, 2.4, 0, 0.4, mat.walnut); p.box(x1 - 0.03, x1, 0, 2.4, 0, 0.4, mat.walnut);
        p.box(x0, x1, 0, 2.4, 0, 0.02, mat.walnut);
        for (let k = 0; k < 7; k++) {
          const y = 0.3 + k * 0.29;
          p.box(x0 + 0.03, x1 - 0.03, y - 0.015, y, 0.02, 0.38, mat.walnut);
          p.box(x0 + 0.03, x1 - 0.03, y + 0.24, y + 0.25, 0.3, 0.32, mat.ledStrip);
          for (const sx of [-0.1, 0.1]) p.box((x0 + x1) / 2 + sx - 0.05, (x0 + x1) / 2 + sx + 0.05, y, y + 0.09, 0.08, 0.34, k % 2 ? mat.sheet : mat.oatmeal, 0.03);
        }
        p.box(x0 + 0.03, x1 - 0.03, 0.12, 2.32, 0.38, 0.4, mat.displayGlass);
      }
    });
    ac(1.6, 4.55, "N");
  }

  // --- Guest bathroom: bath-shower west, vanity east, WC under the window (renders 08, 09) -----
  // Outside the master suite every version follows master-v12.dwg (bath 0.90 m deep, wall to end wall).
  const travertine = mat.stoneTable.clone();
  travertine.color.setRGB(0.8, 0.77, 0.73);
  travertine.clippingPlanes = mat.stoneTable.clippingPlanes;
  const charcoal = mat.greige.clone();
  charcoal.color.setRGB(0.24, 0.23, 0.22);
  charcoal.clippingPlanes = mat.greige.clippingPlanes;
  // Local +x is north. The door is at the south end, so the opening is there (0.80) and the fixed screen covers the
  // north end by the WC. Rain shower over the screen end; the grooved plank wall and the niche end leave no clean
  // run for a hand-shower rail, so a low brass mixer with a bath spout sits mid-wall, in reach from the opening.
  const bath = item(12.324, 8.05, "E", p => {  // wood-look plank wall, stone-clad bath, framed screen at the WC end
    p.box(-1.08, 1.08, 0, M.ceiling, 0, 0.02, mat.woodTile);
    p.box(-0.85, 0.85, 0, 0.55, 0.02, 0.75, mat.stoneWall);
    p.box(-0.78, 0.78, 0.52, 0.56, 0.08, 0.7, mat.ceramic);
    const g0 = -0.05, g1 = 0.85, z = 0.73;  // fixed screen on the rim, black frame all round
    p.box(g0, g1, 0.56, 2.3, z, z + 0.01, mat.clearGlass);
    for (const [a, b, c, d] of [[g0, g1, 2.28, 2.31], [g0, g1, 0.55, 0.58], [g0, g0 + 0.025, 0.55, 2.31], [g1 - 0.025, g1, 0.55, 2.31]])
      p.box(a, b, c, d, z - 0.012, z + 0.022, mat.blackSteel);
    p.cyl(0.45, 0.38, 0.008, 2.44, M.ceiling, mat.chrome, 8);  // ceiling rain head, 30 cm round, inside the screen
    p.cyl(0.45, 0.38, 0.15, 2.425, 2.44, mat.chrome, 32);
    const mx = 0.118;  // low thermostatic mixer and bath spout, on the DWG tap symbol
    p.cyl(mx, 0.02, 0.055, 0.8, 0.82, mat.brass, 32).rotation.x = Math.PI / 2;
    const knob = p.cyl(mx, 0.04, 0.025, 0.79, 0.83, mat.brass, 16); knob.rotation.x = Math.PI / 2; knob.position.y = 0.81;
    p.box(mx - 0.02, mx + 0.02, 0.66, 0.69, 0.02, 0.17, mat.brass, 0.008);
    for (const x of [0.2, 0.5]) {  // towels hung on the screen
      p.box(x - 0.1, x + 0.1, 1.2, 1.85, z + 0.025, z + 0.05, mat.boucle, 0.01);
      p.box(x - 0.012, x + 0.012, 1.84, 1.9, z + 0.02, z + 0.05, mat.blackSteel);
    }
  });
  bath.scale.z = 0.9 / 0.812;  // modelled 0.81 m deep; the DWG bath is 0.90
  item(14.66, 7.75, "W", p => {  // battened oak wall, thick stone slab (DWG counter 0.60 x 2.30), open shelf over walnut drawers, rounded mirror
    const n = -1.425, s = 0.855;  // wall to wall: slab and unit run between the 1 cm stone linings (plan y 9.175 to 6.895)
    p.box(n - 0.01, s + 0.01, 0, M.ceiling, 0, 0.03, mat.oakBattens);  // battens face to face of the walls
    p.box(n, s, 0.2, 0.5, 0.03, 0.55, mat.walnut);  // floating drawer unit, its top an open shelf
    for (let k = 1; k < 5; k++) { const x = n + k * (s - n) / 5; p.box(x - 0.003, x + 0.003, 0.215, 0.44, 0.55, 0.553, shadowGap); }
    p.box(n + 0.02, s - 0.02, 0.44, 0.445, 0.55, 0.553, shadowGap);
    p.box(n + 0.04, s - 0.04, 0.18, 0.2, 0.06, 0.51, mat.ledStrip);
    p.box(n, s, 0.72, 0.85, 0.03, 0.6, travertine, 0.01);
    p.box(n + 0.04, s - 0.04, 0.705, 0.72, 0.05, 0.1, mat.ledStrip);
    p.box(-0.6, -0.3, 0.5, 0.6, 0.1, 0.38, charcoal, 0.02); p.box(-0.15, 0.15, 0.5, 0.58, 0.1, 0.38, charcoal, 0.02);
    p.box(-1.2, -0.9, 0.5, 0.6, 0.1, 0.38, charcoal, 0.02);  // a third basket at the WC end
    for (const x of [0.38, 0.47, 0.56]) { const r = p.cyl(x, 0.24, 0.04, 0.46, 0.74, mat.oatmeal, 16); r.rotation.x = Math.PI / 2; r.position.y = 0.545; }
    const basin = p.cyl(0, 0.3, 0.2, 0.85, 0.96, mat.ceramic, 48, 0.15); basin.scale.x = 1.5;  // wide low vessel
    p.box(-0.02, 0.02, 1.02, 1.05, 0.03, 0.18, mat.brass, 0.008);  // wall spout and two handles
    for (const x of [-0.11, 0.11]) { const k = p.cyl(x, 0.07, 0.022, 1.0, 1.06, mat.brass, 16); k.rotation.x = Math.PI / 2; k.position.y = 1.035; }
    const rr = (x0, x1, y0, y1, r, z0, d, m) => {
      const o = mesh(new THREE.ExtrudeGeometry(roundRect(new THREE.Shape(), x0, x1, y0, y1, r), { depth: d, bevelEnabled: false, curveSegments: 16 }), m, p.g);
      o.position.z = z0;
    };
    rr(-0.52, 0.52, 1.12, 2.0, 0.14, 0.03, 0.025, mat.bronze);  // rounded mirror, thin dark frame
    rr(-0.5, 0.5, 1.14, 1.98, 0.12, 0.04, 0.02, mat.mirror);
    p.cyl(0.55, 0.3, 0.05, 0.85, 1.05, mat.planter, 16, 0.04);  // styling: vase, bottles
    for (const [x, h] of [[-0.45, 0.16], [-0.52, 0.12], [-0.6, 0.18]]) p.cyl(x, 0.3, 0.025, 0.85, 0.85 + h, mat.ceramic, 12);
  });
  item(13.642, 9.18, "S", p => {  // wall-hung WC (DWG), centred 42.5 cm from the bath ledge and the vanity front; brass bidet mixer left, roll holder right
    p.model("models/wc-wallhung.glb", mat.ceramic, 0, 0.1, 0.02);
    bidetMixer(p, -0.3, 0.55, 0, mat.brass);
    p.box(0.22, 0.36, 0.6, 0.72, 0, 0.1, mat.brass, 0.03);
    p.cyl(0.29, 0.07, 0.055, 0.58, 0.7, mat.whiteLacquer, 20).rotation.z = Math.PI / 2;
    // Walnut flush panel with a brass plate on the WC centreline, under the 0.90 window sill (low under-window cistern frame)
    p.box(-0.12, 0.12, 0.68, 0.84, 0, 0.015, mat.walnut, 0.005);
    p.box(-0.06, 0.06, 0.74, 0.78, 0.015, 0.025, mat.brass, 0.005);
  });
  item(12.767, 9.18, "S", p => {  // stone build-out at the bath end with two recessed walnut-lined niches
    const H = M.ceiling, D = 0.28, niches = [[-0.18, 0.02], [0.1, 0.3]], y0 = 0.9, y1 = 2.1;
    const face = new THREE.Shape([new THREE.Vector2(-0.42, 0), new THREE.Vector2(0.42, 0), new THREE.Vector2(0.42, H), new THREE.Vector2(-0.42, H)]);
    for (const [a, b] of niches) face.holes.push(new THREE.Path([new THREE.Vector2(a, y0), new THREE.Vector2(b, y0), new THREE.Vector2(b, y1), new THREE.Vector2(a, y1)]));
    mesh(new THREE.ExtrudeGeometry(face, { depth: D, bevelEnabled: false }), mat.stoneWall, p.g);
    for (const [a, b] of niches) {  // liner centred in its hole, 1 mm shy all round (no face on the stone jambs), 20 cm deep
      const t = 0.012, l = a + 0.001, r = b - 0.001, lo = y0 + 0.001, hi = y1 - 0.001, back = D - 0.2;
      p.box(l, r, lo, hi, 0, back, mat.walnut);
      for (const s of [l, r - t]) p.box(s, s + t, lo, hi, back, D, mat.walnut);
      p.box(l + t, r - t, lo, lo + t, back, D, mat.walnut); p.box(l + t, r - t, hi - t, hi, back, D, mat.walnut);
      for (let k = 1; k < 6; k++) p.box(l + t, r - t, y0 + k * 0.2, y0 + k * 0.2 + 0.015, back, D - 0.01, mat.walnut);  // shelves between the sides
      p.box(l + t + 0.008, r - t - 0.008, hi - t - 0.01, hi - t, back + 0.02, D - 0.03, mat.ledStrip);
    }
  });

  // --- Kitchen: U of white flat-panel units, oak uppers, wide black fridge ---------------------
  const K = { x0: 6.48, x1: 10.21, y0: 5.67, y1: 9.09, front: 0.6 };
  // sink / hob: centre along the run (null = none), sinkW / hobW: their widths (the hood matches the hob).
  // up / splash: [start, end] extensions of the uppers and the stone splash past the run's ends (corner units).
  function run(x, y, facing, len, { sink = null, sinkW = 0.7, hob = null, hobW = 0.9, uppers = true, window, up = [0, 0], splash = [0, 0] } = {}) {
    item(x, y, facing, p => {
      p.box(-len / 2, len / 2, 0, 0.1, 0.06, K.front - 0.06, mat.darkTop);
      p.box(-len / 2, len / 2, 0.02, 0.04, K.front - 0.08, K.front - 0.06, mat.ledStrip);
      p.box(-len / 2, len / 2, 0.1, 0.88, 0, K.front, mat.greyLacquer);
      for (const y of [0.4, 0.62]) p.box(-len / 2, len / 2, y - 0.002, y + 0.002, K.front, K.front + 0.003, shadowGap);
      const n = Math.max(1, Math.round(len / 0.6));
      for (let k = 1; k < n; k++) p.box(-len / 2 + k * len / n - 0.002, -len / 2 + k * len / n + 0.002, 0.12, 0.86, K.front, K.front + 0.003, shadowGap);
      p.box(-len / 2, len / 2, 0.88, 0.92, 0, K.front + 0.01, mat.marbleTop);
      p.box(-len / 2, len / 2, 0.88, 0.92, K.front + 0.01, K.front + 0.02, mat.darkTop);
      if (window) for (let k = 0; k < 24; k++) p.box(window[0] + 0.05, window[1] - 0.05, 1.0 + k * 0.045, 1.012 + k * 0.045, -0.06, -0.03, mat.planter);
      const spans = window ? [[-len / 2, window[0]], [window[1], len / 2]] : [[-len / 2, len / 2]];
      const ext = ([a, b], [s0, s1]) => [a === -len / 2 ? a - s0 : a, b === len / 2 ? b + s1 : b];
      for (const sp of spans) { const [a, b] = ext(sp, splash); if (b - a > 0.05) p.box(a, b, 0.92, 1.58, 0, 0.015, greyStone); }
      if (sink !== null) {
        p.box(sink - sinkW / 2, sink + sinkW / 2, 0.921, 0.925, 0.09, 0.55, mat.blackSteel);
        p.cyl(sink, 0.06, 0.015, 0.92, 1.25, mat.chrome, 8);
      }
      if (hob !== null) {
        p.box(hob - hobW / 2, hob + hobW / 2, 0.921, 0.93, 0.06, 0.56, mat.blackGlass);
        p.box(hob - hobW / 2, hob + hobW / 2, 1.5, 1.62, 0, 0.5, mat.chrome);
      }
      if (uppers) {
        for (const sp of spans) {
          const [a, b] = ext(sp, up);
          if (b - a < 0.05) continue;
          p.box(a, b, 1.6, 2.25, 0, 0.35, mat.oakVeneer);
          p.box(a, b + (b > len / 2 ? 0.05 : 0), 1.58, 1.6, 0.05, 0.3, mat.ledStrip);  // into a corner: on to the next run's strip
          p.box(a, b, 2.25, M.ceiling, 0, 0.35, mat.whiteLacquer);
        }
      }
    });
  }
  // West run, hob: DWG hob block 0.924 wide centred at y 7.376. North run, sink: DWG sink block 0.877 wide at x 8.193.
  // Nagham's Changes closes the upper corners: the west uppers (oak, LED, white to the ceiling) run on 0.25 to the
  // north uppers' front (y 8.74) and start at the pantry front (y 6.2604); the north uppers run on 0.26 past x 9.6
  // to the east run's upper front (x 9.86). The stone splash wraps both corners to the adjoining run's splash.
  const KNC = version === "naghams-changes" || version === "kareems-changes", UD = 0.35;
  run(K.x0, (6.27 + K.y1 - K.front) / 2, "E", K.y1 - K.front - 6.27, { hob: 7.376 - (6.27 + K.y1 - K.front) / 2, hobW: 0.924,
    ...(KNC && { up: [6.27 - 6.2604, K.front - UD], splash: [0, K.front - 0.015] }) });
  run((K.x0 + 9.6) / 2, K.y1, "S", 9.6 - K.x0, { sink: 8.193 - (K.x0 + 9.6) / 2, sinkW: 0.877, window: [7.45 - (K.x0 + 9.6) / 2, 8.75 - (K.x0 + 9.6) / 2],
    ...(KNC && { up: [0, K.x1 - UD - 9.6], splash: [0, K.x1 - 0.015 - 9.6] }) });
  if (version === "naghams-changes" || version === "kareems-changes") {
    // Nagham's Changes: the whole south run (DWG x 196.8797 west wall face to 198.9716) becomes floor-to-ceiling
    // joinery, 0.60 deep off the DWG wall face (y 5.6604): a 1.192 pantry from the west wall, then a 0.90
    // appliance tower (microwave over oven) at the east end. The hob run ends against the pantry's front.
    const fin = mat.whiteLacquer;  // cream-white finish for the tower and pantry
    const XW = 6.4747, XJ = 7.0776, XT = 7.6666, XE = 8.5666, WY = 5.6604, D = 0.6, f = 0.018, H = M.ceiling;
    const tall = (hw, build) => p => {               // carcass, recessed plinth, then the fronts from build
      for (const s of [-1, 1]) p.box(s > 0 ? hw - f : -hw, s > 0 ? hw : -hw + f, 0, H, 0, D, fin);
      p.box(-hw + f, hw - f, 0.1, H, 0, 0.02, fin);
      p.box(-hw + f, hw - f, 0, 0.1, 0.06, D - 0.06, mat.darkTop);
      p.box(-hw + f, hw - f, 0.02, 0.04, D - 0.08, D - 0.06, mat.ledStrip);
      build(p, hw - f);
    };
    const doors = (p, a, b, y0, y1, n) => {          // flat white handleless fronts, n across, shadow gaps between
      p.box(a, b, y0, y1, D - f, D, fin);
      p.box(a, b, y1 - 0.002, y1 + 0.002, D, D + 0.003, shadowGap);
      for (let k = 1; k < n; k++) { const x = a + k * (b - a) / n; p.box(x - 0.002, x + 0.002, y0, y1, D, D + 0.003, shadowGap); }
    };
    item((XT + XE) / 2, WY, "N", tall(0.45, (p, w) => {
      // Owner's stack (cm from the floor): plinth 0-10, 90 pan drawer 10-66.5, oven 66.5-122.5, trim
      // frame 122.5-164 (4.5 rail under a 59.5 x 37 niche, 127-164) holding a countertop microwave 127-159.6
      // (turntable ~130), lift-up flaps 164-225 and 225-260. Single full-width fronts (no centre split), so the
      // only vertical joints are at the tower's edges.
      const O0 = 0.665, O1 = 1.225, N0 = 1.27, N1 = 1.64, MH = 0.326;
      doors(p, -w, w, 0.1, O0, 1);                    // 90 pan drawer under the oven
      // Oven: Purity 90 built-in, 89.5 W x 56 H x 60 D, centred; its fascia overlaps the carcass sides.
      const ow = 0.4475;
      p.box(-w, w, O0, O1, 0.02, D - 0.02, mat.blackSteel);                          // body in the carcass
      p.box(-ow, ow, O0, O1, D - 0.02, D + 0.002, mat.blackGlass);                   // fascia
      p.box(-ow + 0.07, ow - 0.07, O0 + 0.06, O0 + 0.40, D + 0.002, D + 0.004, mat.smokedGlass);  // its window
      p.box(-0.36, 0.36, O0 + 0.43, O0 + 0.445, D + 0.002, D + 0.035, mat.chrome);   // bar handle
      p.box(-ow, ow, O1 - 0.075, O1 - 0.005, D + 0.002, D + 0.004, mat.blackSteel);  // control strip
      p.box(-0.04, 0.04, O1 - 0.048, O1 - 0.033, D + 0.004, D + 0.005, mat.ledStrip);
      // Trim frame: one front panel 122.5-164 with the 59.5 x 37 niche cut out (4.5 rail below it, the
      // oven clear of the microwave), a lined niche to the carcass back, ~2 side / 4.4 top for ventilation.
      const nw = 0.2975;
      p.box(-w, w, O1, N0, D - f, D, fin);                              // rail / bottom of the frame
      for (const s of [-1, 1]) p.box(s > 0 ? nw : -w, s > 0 ? w : -nw, N0, N1, D - f, D, fin);  // frame sides
      for (const s of [-1, 1]) p.box(s > 0 ? nw : -nw - f, s > 0 ? nw + f : -nw, N0, N1, 0.02, D - f, fin);  // niche sides
      p.box(-nw, nw, N0 - f, N0, 0.02, D - f, fin);                    // niche shelf at 127
      p.box(-nw, nw, N1, N1 + f, 0.02, D, fin);                        // niche top
      // Countertop microwave 55.3 W x 32.6 H x 44 D on the shelf, centred, front 1.5 behind the frame face.
      const mw = 0.2765, mz = D - 0.015;
      p.box(-mw, mw, N0, N0 + MH, mz - 0.44, mz - 0.02, mat.blackSteel);            // cabinet
      p.box(-mw, mw, N0, N0 + MH, mz - 0.02, mz, mat.blackGlass);                   // door
      p.box(-mw + 0.03, mw - 0.16, N0 + 0.03, N0 + MH - 0.03, mz, mz + 0.002, mat.smokedGlass);
      p.box(mw - 0.13, mw - 0.03, N0 + MH - 0.05, N0 + MH - 0.035, mz, mz + 0.002, mat.ledStrip);  // display
      for (const y of [O0, O1, N1]) p.box(-w, w, y - 0.002, y + 0.002, D, D + 0.003, shadowGap);
      doors(p, -w, w, N1, 2.25, 1);                   // lift-up flaps to the ceiling,
      doors(p, -w, w, 2.25, H, 1);                    // jointed in line with the oak uppers
      for (const s of [-1, 1]) p.box(s * 0.45 - 0.003, s * 0.45 + 0.003, 0.1, H, D - 0.004, D + 0.003, shadowGap);  // the joints at its edges
    }));
    // Pantry: its west 0.603 (to XJ, the hob run's front line) sits behind the hob run's end, so that part is a
    // fixed flush panel (blind corner, reached through the door, e.g. a corner pull-out); the east 0.589 opens:
    // a tall door 0.10-2.25 and a top door 2.25-2.60. Local x runs opposite to plan x (facing N).
    item((XW + XT) / 2, WY, "N", tall((XT - XW) / 2, (p, w) => {
      const j = (XW + XT) / 2 - XJ;                   // the joint, in local x
      p.box(j, w, 0.1, H, D - f, D, fin); // blind panel
      p.box(j - 0.002, j + 0.002, 0.1, H, D, D + 0.003, shadowGap);
      doors(p, -w, j, 0.1, 2.25, 1);
      doors(p, -w, j, 2.25, H, 1);
    }));
  } else {
    run((K.x0 + 8.6) / 2, K.y0, "N", 8.6 - K.x0, { uppers: false });                 // south run
  }
  // Tall column in the DWG dishwasher block (0.623 wide, y 7.815 to 8.438), floor to ceiling, as in
  // the designer's render: recessed plinth, base front to 0.6, raised dishwasher 0.6-1.42, open
  // dish-rack niche 1.42-1.82, flush cupboards to the ceiling. Fronts at F, flush with the fridge surround.
  const dishwasher = p => {
    const H = M.ceiling, F = K.front + 0.02, hw = 0.3115, t = 0.018, w = hw - t;  // w: inside the carcass sides
    for (const s of [-1, 1]) p.box(s > 0 ? w : -hw, s > 0 ? hw : -w, 0, H, 0, F, mat.whiteLacquer);  // carcass sides
    p.box(-w, w, 0.1, H, 0, 0.02, mat.whiteLacquer);                              // back (seen in the niche)
    p.box(-w, w, 0, 0.1, 0.06, K.front - 0.06, mat.darkTop);                       // plinth, in line with the runs'
    p.box(-w, w, 0.02, 0.04, K.front - 0.08, K.front - 0.06, mat.ledStrip);
    p.box(-w, w, 0.1, 0.6, 0.02, F, mat.whiteLacquer);                             // base cupboard
    p.box(-w, w, 0.6, 1.42, 0.02, F - 0.01, mat.blackSteel);                       // dishwasher body
    p.box(-w + 0.002, w - 0.002, 0.602, 1.418, F - 0.01, F, mat.blackGlass);      // dark glass front
    p.box(-w + 0.002, w - 0.002, 1.37, 1.418, F, F + 0.002, mat.blackSteel);      // control strip
    p.box(-0.05, 0.05, 1.388, 1.4, F + 0.002, F + 0.003, mat.ledStrip);           // its display
    p.box(-0.2, 0.2, 1.335, 1.347, F, F + 0.018, mat.chrome);                     // slim pull
    p.box(-w, w, 1.42, 1.438, 0.02, F, mat.whiteLacquer);                          // niche floor
    p.box(-w + 0.03, w - 0.03, 1.44, 1.45, 0.08, F - 0.06, mat.chrome);           // wire rack: tray and rails
    for (const [y, z] of [[1.52, 0.1], [1.52, F - 0.08], [1.6, 0.1]]) p.box(-w + 0.03, w - 0.03, y, y + 0.008, z, z + 0.008, mat.chrome);
    for (let k = 0; k < 7; k++) p.cyl(-0.18 + k * 0.035, 0.3, 0.11, 1.554, 1.566, mat.ceramic, 20).rotation.z = Math.PI / 2;  // plates on edge
    for (const x of [0.12, 0.2]) p.cyl(x, 0.45, 0.04, 1.45, 1.55, mat.ceramic, 12);  // cups
    p.box(-w, w, 1.82, H, 0.02, F, mat.whiteLacquer);                              // cupboards to the ceiling
    p.box(-w, w, 2.248, 2.252, F, F + 0.003, shadowGap);                          // joint in line with the oak uppers
  };
  // East run per the DWG: the fridge fills the 0.991 m fridge block (y 6.828 to 7.819), then the
  // dishwasher column (0.623), then the counter only from the column to the corner: past the north
  // run's front (y 8.49) just a 0.05 m filler shows, closed by the column's side panel.
  run(K.x1, (8.438 + K.y1) / 2, "W", K.y1 - 8.438);
  item(K.x1, 8.1265, "W", dishwasher);
  item(K.x1, 7.3235, "W", p => {
    p.box(-0.4955, 0.4955, 0, 1.9, 0.02, 0.6, mat.blackSteel, 0.01);         // fridge
    for (const x of [-0.03, 0.01]) p.box(x, x + 0.02, 0.9, 1.4, 0.6, 0.62, mat.chrome);  // pulls of the two doors
    p.box(0.4775, 0.4975, 0, M.ceiling, 0, K.front + 0.02, mat.whiteLacquer);  // tall surround (the column's side on the other)
    p.box(-0.4915, 0.4775, 1.9, M.ceiling, 0, K.front + 0.02, mat.whiteLacquer);  // cupboards over it
    p.box(-0.009, -0.005, 1.92, M.ceiling - 0.02, K.front + 0.02, K.front + 0.023, shadowGap);  // between the two doors
  });

  // --- Laundry: full-height oak joinery on the left, counter and stacked machines ahead ---------
  item(10.32, 7.9215, "E", p => {  // DWG joinery 2.069 long x 0.617 deep (y 6.887 to 8.956)
    p.box(-1.0345, 1.0345, 0, M.ceiling - 0.05, 0, 0.617, mat.oakVeneer);
    fronts(p, -1.0345, 1.0345, 0.05, 2.5, 0.617, 0.55);
    for (const x of [-0.6, -0.05, 0.5]) {
      p.box(x - 0.24, x + 0.24, 0.08, 0.45, 0.78, 0.8, mat.oakVeneer);
      p.box(x - 0.2, x + 0.2, 0.12, 0.42, 0.6, 0.78, mat.applianceWhite, 0.02);
    }
  });
  const cw = 0.299;  // counter between the joinery and the machines (half-width): x 10.937 to 11.535
  item(10.937 + cw, 9.18, "S", p => {
    p.box(-cw, cw, 0.1, 0.88, 0, 0.6, mat.oakVeneer);
    for (const y of [0.36, 0.62]) p.box(-cw + 0.01, cw - 0.01, y - 0.002, y + 0.002, 0.6, 0.603, mat.walnut);
    p.box(-cw, cw, 0.88, 0.92, 0, 0.62, mat.marbleTop);
    p.box(-cw, cw, 1.6, 2.5, 0, 0.35, mat.oakVeneer);
    p.box(-cw, cw, 1.58, 1.6, 0.05, 0.3, mat.ledStrip);
  });
  item(11.835, 9.18, "S", p => {  // DWG stacked washer and dryer 0.60 x 0.60 (x 11.535 to 12.135)
    p.box(-0.3, 0.3, 0, 0.42, 0, 0.6, mat.oakVeneer);
    p.box(-0.25, 0.25, 0.1, 0.36, 0.45, 0.62, mat.applianceWhite, 0.02);
    for (const y0 of [0.45]) {
      p.box(-0.3, 0.3, y0, y0 + 0.84, 0.02, 0.6, mat.applianceWhite, 0.02);
      const ring = mesh(new THREE.TorusGeometry(0.17, 0.025, 10, 40), mat.chrome, p.g);
      ring.position.set(0, y0 + 0.4, 0.615);
      const door = mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.02, 32), mat.smokedGlass, p.g);
      door.rotation.x = Math.PI / 2; door.position.set(0, y0 + 0.4, 0.61);
    }
    p.box(-0.3, 0.3, 1.6, 2.5, 0, 0.6, mat.oakVeneer);
  });

  // --- Entrance: built-in console beside the front door, bench and pebble mirror facing it, gallery --------
  // DWG L (2furni): a shallow piece on the column's face (x 9.819 to 10.2585, 0.26 deep) and the console beside it
  // (x 10.2585 to 11.3486, wall to side wall, 0.42 deep), both fronts on y 4.0201. As the entrance render: the column
  // piece is a low cream cabinet with a vase and books on it, walnut fluting above, a downlight in its oak header;
  // the console is an oak frame with an LED cove round its inside, a cream seat on a drawer, a lit open shoe shelf
  // under it, brass hooks and a tall backlit rounded mirror on the wall.
  const cream = mat.whiteLacquer.clone();
  cream.color.setRGB(0.93, 0.87, 0.78);
  cream.clippingPlanes = mat.whiteLacquer.clippingPlanes;
  const rust = mat.linenBlush.clone();
  rust.color.setRGB(0.72, 0.38, 0.27);
  rust.clippingPlanes = mat.linenBlush.clippingPlanes;
  const coveWall = mat.limewash.clone();  // the wall inside the frame, warmed by the cove
  coveWall.emissive = new THREE.Color(0xff9d55);
  coveWall.emissiveIntensity = 0.3;
  coveWall.clippingPlanes = mat.limewash.clippingPlanes;
  item(0, 3.6001, "N", p => {  // local x = -plan x, z = plan y - 3.6001 (the wall face)
    const W = 3.6001, C = 3.7597, F = 4.0201, XA = 9.819, XB = 10.2585, XE = 11.3486, H = 2.35, HB = 2.17, T = 0.045;
    const B = (x0, x1, y0, y1, h0, h1, m, r = 0) => p.box(-x1, -x0, h0, h1, y0 - W, y1 - W, m, r);
    const rounded = (x0, x1, h0, h1, r) => {  // rectangle with all four corners rounded, in local x
      const s = new THREE.Shape(), a = -x1, b = -x0;
      s.moveTo(a + r, h0); s.lineTo(b - r, h0); s.absarc(b - r, h0 + r, r, -Math.PI / 2, 0, false);
      s.lineTo(b, h1 - r); s.absarc(b - r, h1 - r, r, 0, Math.PI / 2, false);
      s.lineTo(a + r, h1); s.absarc(a + r, h1 - r, r, Math.PI / 2, Math.PI, false);
      s.lineTo(a, h0 + r); s.absarc(a + r, h0 + r, r, Math.PI, Math.PI * 1.5, false);
      return s;
    };
    // Column piece, 0.44 wide: oak post on the door side, cream cabinet to 0.90 under an oak top, walnut fluting
    // up to the oak header, downlight and LED strip in the header washing the fluting.
    B(XA, XA + 0.035, C, F, 0, H, mat.oakVeneer);
    B(XA + 0.035, XB, C + 0.02, F - 0.03, 0, 0.05, shadowGap);  // recessed plinth
    B(XA + 0.035, XB, C, F, 0.05, 0.865, cream);
    B(XA + 0.035, XB, F, F + 0.003, 0.83, 0.834, shadowGap);  // finger pull under the top
    B(XA + 0.035, XB, C, F, 0.865, 0.9, mat.oakVeneer);
    B(XA + 0.035, XB, C, C + 0.012, 0.9, HB, mat.walnut);
    for (let x = XA + 0.045; x + 0.018 <= XB; x += 0.03) B(x, x + 0.018, C + 0.012, C + 0.03, 0.9, HB, mat.oakVeneer);
    B(XA + 0.035, XB, C, F, HB, H, mat.oakVeneer);
    B(XA + 0.045, XB - 0.01, C + 0.035, C + 0.05, HB - 0.008, HB, mat.ledStrip);
    p.cyl(-(XA + XB) / 2, F - 0.08 - W, 0.03, HB - 0.004, HB, mat.downlight, 16);
    B(9.87, 10.03, C + 0.04, C + 0.2, 0.9, 0.92, mat.sheet, 0.003);  // small books
    B(9.88, 10.02, C + 0.05, C + 0.19, 0.92, 0.94, mat.oatmeal, 0.003);
    // Console, 1.09 wide, wall to side wall: oak posts and header 4.5 cm thick, the full 0.42 deep.
    B(XB, XB + T, W, F, 0, H, mat.oakVeneer);
    B(XE - T, XE, W, F, 0, H, mat.oakVeneer);
    B(XB + T, XE - T, W, F, HB, H, mat.oakVeneer);
    B(XB + T, XE - T, W, F, 0, 0.05, mat.oakVeneer);  // shoe shelf base
    B(XB + T, XE - T, W, W + 0.015, 0.05, 0.28, honeyOak);  // and its lit back lining
    B(XB + T, XE - T, W + 0.015, W + 0.03, 0.268, 0.28, mat.ledStrip);  // LED strips along the back and under the drawer
    B(XB + T, XE - T, F - 0.06, F - 0.04, 0.27, 0.278, mat.ledStrip);
    const shoes = [[10.42, mat.walnut], [10.66, mat.sheet], [10.9, mat.walnut], [11.14, mat.linenBlush]];
    for (const [x, m] of shoes) for (const dx of [-0.055, 0.055]) {  // pairs, toes out: sole, low toe, higher heel
      B(x + dx - 0.042, x + dx + 0.042, W + 0.08, W + 0.34, 0.05, 0.065, m === mat.sheet ? mat.oatmeal : shadowGap, 0.006);
      B(x + dx - 0.04, x + dx + 0.04, W + 0.22, W + 0.34, 0.06, 0.1, m, 0.035);
      B(x + dx - 0.04, x + dx + 0.04, W + 0.08, W + 0.23, 0.06, 0.14, m, 0.035);
    }
    B(XB + T, XE - T, W, F, 0.28, 0.39, cream);  // drawer, two fronts
    B((XB + XE) / 2 - 0.002, (XB + XE) / 2 + 0.002, F, F + 0.003, 0.29, 0.38, shadowGap);
    B(XB + T + 0.005, XE - T - 0.005, W + 0.005, F, 0.39, 0.46, mat.boucle, 0.03);  // upholstered seat, top at 0.46
    B(10.33, 10.72, W + 0.05, W + 0.17, 0.46, 0.82, rust, 0.06).rotation.x = -0.22;  // terracotta cushion
    // LED cove round the inside, set back against the wall, and the wall it lights.
    p.face(-(XE - T), -(XB + T), 0.46, HB, 0.002, coveWall, true);
    B(XB + T, XE - T, W + 0.005, W + 0.03, HB - 0.006, HB, mat.ledStrip);
    for (const x of [XB + T, XE - T - 0.006]) B(x, x + 0.006, W + 0.005, W + 0.03, 0.46, HB, mat.ledStrip);
    // Tall mirror with rounded corners (0.46 x 1.20, 0.75 to 1.95) on the door side, glowing round its edge.
    const mx0 = 10.36, mx1 = 10.82;
    mesh(new THREE.ShapeGeometry(rounded(mx0 - 0.025, mx1 + 0.025, 0.725, 1.975, 0.105)), mat.ledStrip, p.g, false).position.z = 0.008;
    const glass = mesh(new THREE.ExtrudeGeometry(rounded(mx0, mx1, 0.75, 1.95, 0.08), { depth: 0.01, bevelEnabled: false, curveSegments: 12 }), mat.mirror, p.g, false);
    glass.position.z = 0.012;
    // Three brass hooks beside it, a linen scarf on the first and a bag on the third.
    for (const x of [10.95, 11.07, 11.19]) {
      B(x - 0.007, x + 0.007, W, W + 0.06, 1.6, 1.614, mat.brass);
      B(x - 0.007, x + 0.007, W + 0.05, W + 0.064, 1.6, 1.64, mat.brass, 0.005);
    }
    B(10.89, 11.01, W + 0.03, W + 0.06, 1.0, 1.61, mat.oatmeal, 0.015);
    B(11.08, 11.3, W + 0.03, W + 0.11, 1.2, 1.4, mat.walnut, 0.02);  // leather bag on the third
    for (const x of [11.12, 11.26]) B(x - 0.006, x + 0.006, W + 0.065, W + 0.075, 1.4, 1.6, mat.walnut);
  });
  plant(10.13, 3.89, 0.5, 0.07, 0.9);  // cream vase of olive branches on the column piece
  // Facing the front door, as the entrance render: tall pebble mirror (0.78 x 1.55, thin oak frame, warm LED glow
  // behind) just above a cream boucle bench (DWG 1.20 x 0.40, 0.45 high) on two rounded block legs, a dusty-pink throw
  // over its right end; one brass and opal pill sconce right of the mirror over a rounded oak shelf (DWG 0.40 x 0.18).
  const dustyPink = mat.linenBlush.clone();
  dustyPink.color.setRGB(0.74, 0.5, 0.45);
  dustyPink.clippingPlanes = mat.linenBlush.clippingPlanes;
  item(8.512, 5.55, "S", p => {
    const w = 0.78, h = 1.55, yc = 0.5 + h / 2;  // bottom 5 cm above the bench
    // Pebble outline grown (dz > 0) or shrunk by about dz all round: narrower top leaning left, fuller lower right
    const outline = dz => new THREE.CatmullRomCurve3([[-0.5, 0.95], [0.1, 1], [0.6, 0.85], [0.92, 0.35], [1, -0.3], [0.9, -0.86],
      [0.5, -1], [-0.5, -1], [-0.9, -0.86], [-0.98, -0.3], [-0.88, 0.45]]
      .map(([u, v]) => new THREE.Vector3(u * (w / 2 + dz), v * (h / 2 + dz), 0)), true).getPoints(80).map(v => new THREE.Vector2(v.x, v.y));
    mesh(new THREE.ShapeGeometry(new THREE.Shape(outline(0.05))), mat.ledStrip, p.g, false).position.set(0, yc, 0.004);  // glow on the wall
    const ring = new THREE.Shape(outline(0));
    ring.holes.push(new THREE.Path(outline(-0.022)));
    mesh(new THREE.ExtrudeGeometry(ring, { depth: 0.03, bevelEnabled: false, curveSegments: 4 }), mat.oakVeneer, p.g).position.set(0, yc, 0.012);
    mesh(new THREE.ShapeGeometry(new THREE.Shape(outline(-0.02))), mat.mirror, p.g, false).position.set(0, yc, 0.03);
    p.box(-0.6, 0.6, 0.26, 0.45, 0, 0.4, mat.boucle, 0.09);  // seat slab
    for (const s of [-1, 1]) {  // block legs, open between
      p.box(s > 0 ? 0.38 : -0.6, s > 0 ? 0.6 : -0.38, 0.025, 0.3, 0, 0.4, mat.boucle, 0.09);
      p.box(s > 0 ? 0.39 : -0.59, s > 0 ? 0.59 : -0.39, 0, 0.025, 0.01, 0.39, mat.oakVeneer, 0.01);
    }
    p.box(0.08, 0.42, 0.45, 0.462, 0.02, 0.41, dustyPink, 0.004);   // throw over the seat
    p.box(0.08, 0.42, 0.07, 0.462, 0.41, 0.422, dustyPink, 0.004);  // hanging down the front
    for (let x = 0.095; x < 0.42; x += 0.02) p.box(x - 0.003, x + 0.003, 0.02, 0.07, 0.414, 0.418, dustyPink);  // fringe
  });
  item(9.365, 5.55, "S", p => {  // DWG shelf 0.40 x 0.18, rounded front corners, top at 1.02; books, reed diffuser
    const s = new THREE.Shape(), r = 0.08;
    s.moveTo(-0.2, 0); s.lineTo(0.2, 0); s.lineTo(0.2, 0.18 - r); s.absarc(0.2 - r, 0.18 - r, r, 0, Math.PI / 2, false);
    s.lineTo(-0.2 + r, 0.18); s.absarc(-0.2 + r, 0.18 - r, r, Math.PI / 2, Math.PI, false); s.lineTo(-0.2, 0);
    const geo = new THREE.ExtrudeGeometry(s, { depth: 0.05, bevelEnabled: false, curveSegments: 12 });
    geo.rotateX(Math.PI / 2);
    mesh(geo, mat.oakVeneer, p.g).position.y = 1.02;
    p.box(-0.17, -0.02, 1.02, 1.04, 0.03, 0.14, mat.sheet, 0.003);  // small books
    p.box(-0.16, -0.03, 1.04, 1.06, 0.035, 0.135, mat.oatmeal, 0.003);
    p.cyl(-0.095, 0.085, 0.025, 1.06, 1.15, mat.bronzeGlass, 16);  // reed diffuser
    for (const a of [-0.25, -0.1, 0.05, 0.2]) p.cyl(-0.095 + Math.sin(a) * 0.06, 0.085, 0.002, 1.12, 1.36, mat.walnut, 4).rotation.z = -a;  // reeds fanning out
  });
  plant(9.465, 5.46, 0.5, 0.065, 1.02);  // cream vase of olive branches on the shelf
  item(9.28, 5.55, "S", p => {  // brass and opal pill sconce, right of the mirror
    p.box(-0.025, 0.025, 1.42, 1.64, 0, 0.012, mat.brass, 0.012);
    p.box(-0.008, 0.008, 1.5, 1.516, 0.012, 0.07, mat.brass);
    p.cyl(0, 0.07, 0.034, 1.51, 1.57, mat.brass, 24);
    mesh(new THREE.CapsuleGeometry(0.042, 0.2, 8, 20), mat.lampShade, p.g, false).position.set(0, 1.71, 0.07);
  });
  sconce(7.63, 3.6, "N", 1.75); sconce(9.33, 3.6, "N", 1.75);
  item(8.48, 3.72, "N", p => {  // front door per render 29: walnut leaf with rounded top corners, deep surround, long brass pull
    p.roundTop(-0.56, 0.56, 0, 2.25, 0.3, -0.02, 0.06, mat.walnut);
    p.roundTop(-0.46, 0.46, 0, 2.14, 0.22, 0.04, 0.02, mat.oakVeneer);
    p.box(0.3, 0.33, 0.7, 1.5, 0.06, 0.09, mat.brass);
  });
  plant(11.1, 4.72, 1.6, 0.24); plant(7.64, 5.3, 1.75, 0.2);  // olives on the side wall clear of the console seat, and left of the bench
  art(7.0, 3.6, "N", 0.75, 1.05, 1.45, 0); art(6.72, 3.62, "N", 0.5, 0.5, 1.3, 1, false);
  [[3.85, 0.36, 0.48, 1.75], [4.3, 0.36, 0.36, 1.45], [3.95, 0.3, 0.3, 1.2]].forEach(([y, w, h, z], k) => art(6.51, y, "E", w, h, z, k));
  rug(7.1, 4.3, 10.9, 5.1, mat.art[1]);

  // --- Reception: TV wall with lit oak niches, two sofas, armchair -----------------------------
  item(17.25, 3.67, "E", p => {  // per render 10: a plaster TV box standing proud of a built-out run
    // holding two tall rounded oak-lined niches (south), and a lit rounded oak recess under the TV.
    // North end (local x 1.72) meets the reception column at plan y 5.3914 — keep that edge flat/flush.
    const H = M.ceiling, edge = -0.46, D0 = 0.28, D1 = 0.36;  // run depth, TV box depth
    const KC = version === "kareems-changes";
    // Kareem's: TV 166.8 x 95.8 x 7.7 cm in a flat rectangular opening centred over the niche (render).
    const TW = KC ? 1.668 : 1.50, TH = KC ? 0.958 : 0.85, TD = KC ? 0.077 : 0.03;
    const slab = (x0, x1, d, holes) => {
      const s = new THREE.Shape([new THREE.Vector2(x0, 0), new THREE.Vector2(x1, 0), new THREE.Vector2(x1, H), new THREE.Vector2(x0, H)]);
      for (const h of holes) s.holes.push(roundRect(new THREE.Path(), ...h));
      mesh(new THREE.ExtrudeGeometry(s, { depth: d, bevelEnabled: false, curveSegments: 12 }), mat.limewash, p.g);
    };
    const lined = (x0, x1, y0, y1, r, d) => {  // oak lining and back for a rounded opening d deep
      const ring = roundRect(new THREE.Shape(), x0, x1, y0, y1, r);
      ring.holes.push(roundRect(new THREE.Path(), x0 + 0.018, x1 - 0.018, y0 + 0.018, y1 - 0.018, r - 0.018));
      mesh(new THREE.ExtrudeGeometry(ring, { depth: d, bevelEnabled: false, curveSegments: 12 }), honeyOak, p.g);
      mesh(new THREE.ExtrudeGeometry(roundRect(new THREE.Shape(), x0, x1, y0, y1, r), { depth: 0.01, bevelEnabled: false, curveSegments: 12 }), honeyOak, p.g);
    };
    const tall = [[-1.59, -1.25], [-1.11, -0.77]], low = [-0.4, 1.38, 0.33, 0.69, 0.1];
    const tcx = (low[0] + low[1]) / 2;
    const tvX0 = tcx - TW / 2, tvX1 = tcx + TW / 2;
    const tvY0 = KC ? 0.83 : 0.92, tvY1 = tvY0 + TH;
    // Opening slightly larger than the TV so the set sits in a flat plaster pocket (render).
    const open = KC ? [tvX0 - 0.025, tvX1 + 0.025, tvY0 - 0.025, tvY1 + 0.025, 0.02] : null;
    slab(-1.72, edge, D0, tall.map(([x0, x1]) => [x0, x1, 0.42, 2.2, 0.13]));
    slab(edge, 1.72, D1, open ? [low, open] : [low]);
    // A splayed return instead of a square step between the run and the TV box: 0.08 m out over 0.2 m.
    const splay = 0.2, L = Math.hypot(splay, D1 - D0), a = Math.atan2(D1 - D0, splay);
    const wedge = new THREE.Shape([new THREE.Vector2(edge - splay, -D0), new THREE.Vector2(edge, -D0), new THREE.Vector2(edge, -D1)]);
    const wedgeGeo = new THREE.ExtrudeGeometry(wedge, { depth: H, bevelEnabled: false });
    wedgeGeo.rotateX(-Math.PI / 2);  // shape v = -z, extruded up the wall
    mesh(wedgeGeo, mat.limewash, p.g);
    lined(...low, D1);
    p.box(low[0] + 0.1, low[1] - 0.1, 0.665, 0.675, 0.05, D1 - 0.03, mat.ledStrip);
    for (const [x0, x1] of tall) {
      lined(x0, x1, 0.42, 2.2, 0.13, D0);
      for (const y of [0.86, 1.3, 1.74]) {
        p.box(x0 + 0.015, x1 - 0.015, y, y + 0.025, 0.01, D0, honeyOak);
        p.box(x0 + 0.03, x1 - 0.03, y - 0.012, y, 0.04, D0 - 0.03, mat.ledStrip);
      }
      p.box(x0 + 0.06, x1 - 0.06, 2.1, 2.112, 0.04, D0 - 0.03, mat.ledStrip);
    }
    // Shelf styling as rendered: vases, books, a bowl.
    p.cyl(-1.42, 0.15, 0.045, 1.765, 1.97, mat.linenSage, 16, 0.065); p.cyl(-0.94, 0.15, 0.035, 1.765, 1.99, mat.linenSlate, 16, 0.06);
    for (const [x, y] of [[-1.47, 1.325], [-0.99, 0.885], [-1.0, 1.325]]) for (let k = 0; k < 4; k++) p.box(x + k * 0.03, x + k * 0.03 + 0.025, y, y + 0.2 - (k % 2) * 0.03, 0.06, 0.24, k % 2 ? mat.linenBlush : mat.walnut);
    p.cyl(-1.42, 0.15, 0.05, 0.445, 0.6, mat.planter, 16);
    p.box(0.95, 1.15, 0.345, 0.4, 0.08, 0.26, mat.whiteLacquer);
    p.cyl(0.2, 0.15, 0.05, 0.345, 0.52, mat.clearGlass, 16);
    // TV centred over the niche; on Kareem's it sits in the opening so the face reads flat with the plaster.
    const z0 = KC ? D1 - TD : D1, z1 = KC ? D1 : D1 + TD;
    p.box(tvX0, tvX1, tvY0, tvY1, z0, z1, mat.blackSteel);
    p.face(tvX0 + 0.01, tvX1 - 0.01, tvY0 + 0.01, tvY1 - 0.01, z1 + 0.001, mat.screen);
    p.box(-1.72, edge - splay, 0, 0.08, D0, D0 + 0.012, mat.oakVeneer);
    p.box(edge, 1.72, 0, 0.08, D1, D1 + 0.012, mat.oakVeneer);
    const skirt = p.box(-L / 2, L / 2, 0, 0.08, -0.006, 0.006, mat.oakVeneer);
    skirt.position.set(edge - splay / 2 - Math.sin(a) * 0.006, 0.04, (D0 + D1) / 2 + Math.cos(a) * 0.006);
    skirt.rotation.y = -a;
  });
  // Kareem's Changes: sofa, prints and split AC centred on the south wall's visible face, x 17.53 (TV-wall run)
  // to 21.222 (east wall), so x 19.376; side table and plant each mid-way in the 0.82 m left either side.
  const KC = version === "kareems-changes", SC = 19.376;
  item(KC ? SC : 18.86, 2.103, "N", p => sofa(p, 2.05, 1.02, mat.boucle, [mat.linenSlate, mat.linenBlush, mat.linenSlate]));  // DWG, clear of the pier
  item(21.027, 4.165, "W", p => sofa(p, 2.0, 0.92, mat.boucle, [mat.linenSlate, mat.linenBlush]));  // centred on the DWG sofa, back on its back line, clear of the curtains
  item(19.1, 5.95, "S", p => {  // DWG armchair, as rendered: open walnut lounge frame, slate cushions, blush pillow
    for (const s of [-1, 1]) {
      const x = s * 0.36;
      p.box(x - 0.025, x + 0.025, 0.56, 0.6, 0.04, 0.8, mat.walnut, 0.012);  // arm
      p.box(x - 0.025, x + 0.025, 0, 0.58, 0.68, 0.73, mat.walnut, 0.012).rotation.x = -0.1;  // front leg
      p.box(x - 0.025, x + 0.025, 0, 0.66, 0.06, 0.11, mat.walnut, 0.012).rotation.x = 0.15;  // back leg
      p.box(x - 0.02, x + 0.02, 0.2, 0.25, 0.1, 0.74, mat.walnut, 0.01);  // seat rail
    }
    p.box(-0.33, 0.33, 0.25, 0.39, 0.14, 0.74, mat.linenSlate, 0.05).rotation.x = -0.08;
    p.box(-0.33, 0.33, 0.36, 0.88, 0.07, 0.21, mat.linenSlate, 0.05).rotation.x = -0.32;
    p.box(-0.06, 0.24, 0.46, 0.74, 0.2, 0.33, mat.linenBlush, 0.07).rotation.set(-0.3, 0, 0.2);
  });
  rug(17.9, 2.906, 20.5, 5.506);  // centred on the coffee table
  item(19.008, 4.206, "W", p => {  // DWG coffee table 1.03 x 0.62, long side along the sofa: oval marble top on two walnut drums
    const top = p.cyl(0, 0, 0.515, 0.36, 0.42, mat.marbleTop, 40); top.scale.z = 0.6;
    for (const x of [-0.25, 0.25]) p.cyl(x, 0, 0.15, 0, 0.36, mat.walnut, 24);
  });
  // DWG side table (Kareem's: in the east corner, 0.10 clear of the curtain stack at y 2.76)
  item(...(KC ? [SC + 1.436, 2.45] : [20.341, 2.687]), "S", p => { p.cyl(0, 0, 0.205, 0.52, 0.56, mat.marbleTop, 32); p.cyl(0, 0, 0.11, 0, 0.52, mat.walnut, 24); });
  if (KC) plant(SC - 1.436, 2.45, 1.6, 0.24);  // clear of the TV-wall run (x 17.53)
  else plant(17.6, 2.33, 1.6, 0.24);
  // Two 1.05 x 1.30 m framed prints as in render 11, 0.30 m apart and centred over the sofa, on the south
  // wall's built-out face (y 2.0705, flush with the pier: the recesses either side are filled to it).
  // Kareem's: under the centred AC (bottom 2.21) 1.25 m tall prints can't clear both it and the sofa back
  // (0.86), so 1.00 x 0.90: frame 1.02 to 1.97, picture lights to 2.085, 0.125 under the AC.
  if (KC) for (const x of [SC - 0.665, SC + 0.665]) art(x, 2.0705, "N", 1.0, 0.9, 1.495, x < SC ? 0 : 1);
  else for (const x of [18.195, 19.525]) art(x, 2.0705, "N", 1.0, 1.25, 1.62, x < 19 ? 0 : 1);
  // Curtains either side of each slider (the sofa one 2.00 m, centred on the sofa): sheer on the track nearest
  // the glass, curtains stacked in front, both clear of the sofa back (x 21.027).
  for (const [y0, y1] of [[3.135, 5.195], [6.34, 8.08]]) {
    for (const y of [y0 - 0.15, y1 + 0.15]) item(21.22, y, "W", p => {
      const m = mesh(curtainGeometry(0.45, 2.5), mat.curtain, p.g); m.position.set(0, 1.3, 0.14);
    });
    item(21.22, (y0 + y1) / 2, "W", p => { const m = mesh(curtainGeometry(y1 - y0, 2.45), mat.sheer, p.g); m.position.set(0, 1.25, 0.06); });
  }
  const NCAC = version === "naghams-changes" || version === "kareems-changes";  // Nagham's Changes: wall-mounted splits, no ducted AC
  if (NCAC) {
    // Slim ceiling-fixed double track over each slider (sheer and curtain runs), as long as the curtain stacks.
    for (const [y0, y1] of [[3.135, 5.195], [6.34, 8.08]]) item(21.222, (y0 + y1) / 2, "W", p =>
      p.box(-(y1 - y0) / 2 - 0.375, (y1 - y0) / 2 + 0.375, M.ceiling - 0.03, M.ceiling, 0.02, 0.18, mat.applianceWhite, 0.005));
    // 1.5 hp split on the south wall's built-out face, east of the right-hand print (frame edge x 20.05),
    // 0.20 short of the east wall and clear of the curtain stack (y 2.76): 0.85 W x 0.29 H x 0.22 D, top 2.40.
    // Kareem's: centred on the wall over the sofa and prints, top raised to 2.50 (0.10 under the ceiling).
    if (KC) ac(SC, 2.0705, "N", 2.5, 0.85, 0.29, 0.22, true);
    else ac(20.6, 2.0705, "N", 2.4, 0.85, 0.29, 0.22, true);
  } else {
    // One plaster curtain box along the whole east wall. The ACs are concealed (ducted) units in metal
    // boxes on the terrace over each slider (see Terrace), each feeding a linear grille in the box face.
    item(21.222, (1.94 + 9.5) / 2, "W", p => p.box(-3.78, 3.78, 2.1, M.ceiling, 0, 0.3, mat.limewash));
    for (const [y0, y1] of [[3.165, 5.165], [6.34, 8.08]]) item(21.222, (y0 + y1) / 2, "W", p => {
      p.box(-(y1 - y0) / 2 + 0.1, (y1 - y0) / 2 - 0.1, 2.3, 2.36, 0.3, 0.302, mat.grille);
      for (let k = 1; k < 3; k++) p.box(-(y1 - y0) / 2 + 0.1, (y1 - y0) / 2 - 0.1, 2.3 + k * 0.02 - 0.002, 2.3 + k * 0.02, 0.302, 0.304, mat.applianceWhite);
    });
  }

  // --- Dining: walnut table for six, tub chairs, lantern pendants; buffet wall and coffee bar ----
  item(18.4, 7.6, "S", p => {
    p.box(-1.2, 1.2, 0.72, 0.76, -0.5, 0.5, mat.walnut, 0.01);
    for (const x of [-0.75, 0.75]) p.box(x - 0.05, x + 0.05, 0, 0.72, -0.3, 0.3, mat.walnut);
  });
  for (const x of [17.6, 18.4, 19.2]) {
    item(x, 6.55, "N", p => chair(p));
    item(x, 8.65, "S", p => chair(p));
    pendant(x, 7.6, 1.75, "lantern");
  }
  item(16.95, 7.6, "E", p => chair(p)); item(19.85, 7.6, "W", p => chair(p));
  rug(16.6, 6.3, 20.2, 8.9);
  for (const y of [9.5]) {
    for (const x of [16.2, 17.71]) item(x, y, "S", p => { const m = mesh(curtainGeometry(0.4, 2.5), mat.curtain, p.g); m.position.set(0, 1.3, 0.1); });
    item(16.95, y, "S", p => { const m = mesh(curtainGeometry(1.15, 2.45), mat.sheer, p.g); m.position.set(0, 1.25, 0.18); });
  }
  // Buffet wall per the DWG and the dining render (15): a plaster mass with a tall lit oak niche (south),
  // splayed back into the wall like the TV wall, then a walnut sideboard under a backlit pebble mirror.
  item(14.79, 8.0, "E", p => {  // local x = plan y - 8, z = plan x - 14.79
    const H = M.ceiling, F = 0.462, P = 0.062;  // mass front (x 15.25), wall panel face (x 14.85)
    const S = -1.213, C = -1.013, E = -0.347, K = 0.103, N = 1.477;  // y 6.79, corner, 7.65, 8.10 (45 cm splay), 9.48
    const niche = [-0.883, -0.474, 0.45, 2.25, 0.13], deep = 0.25;
    const face = new THREE.Shape([new THREE.Vector2(C, 0), new THREE.Vector2(E, 0), new THREE.Vector2(E, H), new THREE.Vector2(C, H)]);
    face.holes.push(roundRect(new THREE.Path(), ...niche));
    mesh(new THREE.ExtrudeGeometry(face, { depth: F, bevelEnabled: false, curveSegments: 12 }), mat.limewash, p.g);
    p.box(S, C, 0, H, 0, F - 0.2, mat.limewash);
    p.cyl(C, F - 0.2, 0.2, 0, H, mat.limewash, 32);  // the DWG's rounded front corner
    const plan = new THREE.Shape([[E, 0], [E, -F], [K, -P], [N, -P], [N, 0]].map(([x, v]) => new THREE.Vector2(x, v)));
    const splay = new THREE.ExtrudeGeometry(plan, { depth: H, bevelEnabled: false });
    splay.rotateX(-Math.PI / 2);  // shape v = -z, extruded up the wall
    mesh(splay, mat.limewash, p.g);
    const [x0, x1, y0, y1, r] = niche;  // oak lining, back and lit shelves
    const ring = roundRect(new THREE.Shape(), x0, x1, y0, y1, r);
    ring.holes.push(roundRect(new THREE.Path(), x0 + 0.018, x1 - 0.018, y0 + 0.018, y1 - 0.018, r - 0.018));
    mesh(new THREE.ExtrudeGeometry(ring, { depth: F, bevelEnabled: false, curveSegments: 12 }), honeyOak, p.g);
    mesh(new THREE.ExtrudeGeometry(roundRect(new THREE.Shape(), x0, x1, y0, y1, r), { depth: F - deep, bevelEnabled: false, curveSegments: 12 }), honeyOak, p.g);
    for (const y of [0.85, 1.25, 1.65, 1.95]) {
      p.box(x0 + 0.015, x1 - 0.015, y, y + 0.025, F - deep, F - 0.01, honeyOak);
      p.box(x0 + 0.03, x1 - 0.03, y - 0.012, y, F - deep + 0.03, F - 0.03, mat.ledStrip);
    }
    p.box(x0 + 0.06, x1 - 0.06, 2.14, 2.152, F - deep + 0.03, F - 0.03, mat.ledStrip);
    p.cyl(-0.76, F - 0.12, 0.05, 0.875, 1.08, mat.linenSage, 16, 0.065); p.cyl(-0.6, F - 0.12, 0.04, 1.275, 1.42, mat.planter, 16);
    for (let k = 0; k < 4; k++) p.box(-0.8 + k * 0.03, -0.775 + k * 0.03, 1.675, 1.86 - (k % 2) * 0.03, F - 0.2, F - 0.04, k % 2 ? mat.linenBlush : mat.walnut);
    // Walnut sideboard from the mass to the corner, front in line with the mass (DWG x 15.25).
    p.box(E, N - 0.02, 0.12, 0.8, P, F, mat.walnut);
    fronts(p, E, N - 0.02, 0.12, 0.8, F, 0.45);
    p.box(E + 0.03, N - 0.05, 0, 0.12, P, F - 0.06, mat.darkTop);
    p.box(E, N - 0.02, 0.8, 0.83, P, F + 0.01, mat.walnut);
    p.pebble((K + N) / 2, 1.6, 0.92, 0.8, P + 0.012, mat.mirror, true);
    p.cyl(0.15, 0.3, 0.07, 0.83, 1.02, mat.planter, 16, 0.05); p.cyl(1.3, 0.28, 0.06, 0.83, 1.0, mat.stoneTable, 16, 0.045);
    p.cyl(1.05, 0.3, 0.045, 0.83, 0.88, mat.blackSteel, 16);
  });
  plant(15.04, 8.15, 0.5, 0.06, 0.83);
  // 2.25 hp split on the buffet wall panel (x 14.852), centred on the pebble mirror (y 8.79): 1.05 W x 0.30 H
  // x 0.23 D, top 2.42, its underside 0.12 over the mirror top (2.00) and 0.18 under the ceiling.
  if (NCAC) ac(14.852, 8.79, "E", 2.42, 1.05, 0.3, 0.23, true);
  item(20.474, 9.5, "S", p => {  // coffee corner (DWG, 0.60 deep), column to wall: walnut base, white top, lit shelves
    // Two bays: left = one swinging door over a single shelf (water dispenser sits on the top above it);
    // right = drawer stack top to bottom. Opens with a tap / E in Walk.
    const c = new THREE.Group(), q = part(c), leaves = []; p.g.add(c);
    const F = 0.58, mid = 0.0;  // front face; split at centre
    q.box(-0.75, 0.75, 0.1, 0.88, 0, version === "kareems-changes" ? 0.015 : F - 0.02, mat.walnut);  // carcass (Kareem's: back only, interior visible when opened)
    q.box(-0.75, 0.75, 0.1, 0.12, 0, F, mat.walnut);  // plinth shelf
    q.box(-0.02, 0.02, 0.12, 0.88, 0, F - 0.02, mat.walnut);  // centre divider
    // Left bay: one shelf at mid-height, open behind the door.
    q.box(-0.73, -0.02, 0.48, 0.505, 0.02, F - 0.04, mat.oakVeneer);
    const dL = new THREE.Group(); dL.position.set(-0.75, 0, F); c.add(dL);
    part(dL).box(0, 0.73, 0.12, 0.88, 0, 0.02, mat.walnut);
    leaves.push({ obj: dL, axis: "y", open: -100 * Math.PI / 180 });
    // Right bay: three drawers, top to bottom.
    const rh = [[0.12, 0.36], [0.36, 0.60], [0.60, 0.88]];
    rh.forEach(([y0, y1], k) => {
      const d = new THREE.Group(); d.position.set(0.02, 0, F); c.add(d);
      part(d).box(0, 0.73, y0, y1, 0, 0.02, mat.walnut);
      part(d).box(0.28, 0.45, (y0 + y1) / 2 - 0.01, (y0 + y1) / 2 + 0.01, 0.02, 0.025, mat.blackSteel);  // pull
      leaves.push({ obj: d, slide: new THREE.Vector3(0, 0, 0.35) });
    });
    c.userData.openable = { id: "coffee-corner", label: "Coffee corner", leaves,
      anchor: new THREE.Vector3(0, 0.5, F + 0.06), reach: 1.8, duration: 0.6 };
    p.box(-0.75, 0.75, 0.88, 0.92, 0, 0.6, mat.marbleTop);
    p.label("two lit floating shelves", p => {
      for (const y of [1.55, 1.8]) { p.box(-0.75, 0.75, y, y + 0.035, 0, 0.28, mat.oakVeneer); p.box(-0.73, 0.73, y - 0.012, y, 0.03, 0.26, mat.ledStrip); }
    });
    // Espresso machine: steel body over a recessed brew bay, group head, portafilter, steam wand, cup
    p.label("espresso machine", p => {
      p.box(0.2, 0.5, 0.92, 0.95, 0.06, 0.42, mat.blackSteel, 0.008);
      p.box(0.2, 0.5, 0.95, 1.12, 0.06, 0.2, mat.chrome, 0.015);
      p.box(0.2, 0.5, 1.12, 1.34, 0.06, 0.4, mat.chrome, 0.02);
      p.face(0.24, 0.3, 1.2, 1.28, 0.401, mat.blackGlass);
      for (const x of [0.38, 0.42, 0.46]) p.box(x - 0.012, x + 0.012, 1.22, 1.25, 0.4, 0.41, mat.blackSteel, 0.004);
      p.cyl(0.35, 0.3, 0.035, 1.07, 1.12, mat.chrome, 20);
      p.box(0.335, 0.365, 1.05, 1.075, 0.3, 0.5, mat.blackSteel, 0.012);
      p.cyl(0.46, 0.34, 0.005, 0.99, 1.12, mat.chrome, 8);
      p.cyl(0.35, 0.3, 0.032, 0.95, 1.01, mat.whiteLacquer, 16, 0.026);
    });
    // Fresh 2-tap countertop water dispenser, 31.5 W x 54 H x 42.5 D cm, at the column end (over the left bay)
    p.label("two-tap countertop water dispenser", p => {
      p.box(-0.694, -0.379, 0.92, 1.46, 0, 0.425, mat.blackSteel, 0.03);
      p.box(-0.6, -0.47, 1.32, 1.38, 0.425, 0.43, mat.blackGlass);
      for (const x of [-0.6, -0.48]) p.box(x - 0.02, x + 0.02, 1.13, 1.2, 0.41, 0.45, mat.chrome);
      p.box(-0.68, -0.39, 0.93, 0.95, 0.3, 0.44, mat.chrome);
    });
  });
  item(16.95, 9.5, "S", p => p.box(-1.0, 1.0, 2.5, 2.52, 0.02, 0.22, mat.ledStrip));
  if (version === "kareems-changes") item(18.55, 9.502, "S", p => {
    const c = new THREE.Group(), q = part(c), leaves = []; p.g.add(c);
    // Shallow wall-mounted box: clear monitor cavity and bottom-hinged worktop.
    q.box(-0.42, 0.42, 0.75, 1.425, 0, 0.025, mat.limewash);
    for (const x of [-0.42, 0.395]) q.box(x, x + 0.025, 0.75, 1.425, 0.025, 0.23, mat.limewash);
    q.box(-0.42, 0.42, 1.4, 1.425, 0.025, 0.23, mat.limewash);
    q.box(-0.42, 0.42, 0.725, 0.75, 0, 0.23, mat.limewash);
    q.box(-0.39, 0.39, 0.775, 1.4, 0.025, 0.04, mat.oakVeneer);
    q.box(-0.32, 0.32, 0.98, 1.355, 0.055, 0.095, mat.blackSteel);
    q.box(-0.30, 0.30, 1.0, 1.335, 0.095, 0.099, mat.screen);
    const d = new THREE.Group(); d.position.set(0, 0.75, 0.23); c.add(d);
    part(d).box(-0.42, 0.42, 0, 0.65, 0, 0.025, mat.limewash);
    part(d).box(-0.395, 0.395, 0.025, 0.625, -0.008, 0, mat.oakVeneer);
    leaves.push({ obj: d, axis: "x", open: Math.PI / 2 });
    c.userData.openable = { id: "dining-window-fold-desk", label: "Fold-down monitor desk", leaves, anchor: new THREE.Vector3(0, 1.08, 0.3), reach: 1.8, duration: 0.7 };
  });
  if (version === "kareems-changes") item(32.33, 6.912, "S", p => {
    const w = 0.42, h = 0.62, back = 0.015, front = 0.23;
    const c = new THREE.Group(), q = part(c), leaves = []; p.g.add(c);
    q.box(-w, w, 1.05, 1.05 + h, back, front - 0.035, mat.limewash);
    q.box(-w + 0.025, w - 0.025, 1.075, 1.075 + h - 0.05, back + 0.01, back + 0.025, mat.whiteLacquer);
    q.box(-w + 0.025, w - 0.025, 1.075, 1.075 + h - 0.05, front - 0.06, front - 0.035, mat.limewash);
    q.box(-w + 0.025, -w + 0.05, 1.075, 1.075 + h - 0.05, back + 0.025, front - 0.06, mat.limewash);
    q.box(w - 0.05, w - 0.025, 1.075, 1.075 + h - 0.05, back + 0.025, front - 0.06, mat.limewash);
    q.box(-w + 0.05, w - 0.05, 1.075, 1.09, back + 0.025, front - 0.06, mat.limewash);
    q.box(-w + 0.05, w - 0.05, 1.075 + h - 0.065, 1.075 + h - 0.05, back + 0.025, front - 0.06, mat.limewash);
    q.box(-0.3, 0.3, 1.3, 1.32, 0.12, 0.17, mat.blackSteel);
    q.box(-0.285, 0.285, 1.32, 1.59, 0.12, 0.14, mat.blackGlass);
    q.box(-w, w, 1.05, 1.075, front - 0.025, front, mat.limewash);
    const door = new THREE.Group(); door.position.set(0, 1.05, front - 0.025); c.add(door);
    part(door).box(-w, w, 0, 0.025, 0, 0.025, mat.limewash);
    leaves.push({ obj: door, axis: "x", open: -105 * Math.PI / 180 });
    c.userData.openable = { id: "dining-fold-down-desk", label: "Fold-down desk", leaves, anchor: new THREE.Vector3(0, 1.38, front + 0.06), reach: 1.8, duration: 0.6 };
  });
  plant(20.75, 5.77, 1.7, 0.25);  // in the pier between the sofa window and the slider, between their curtain stacks

  // --- Terrace: decking, L bench, lounge set, BBQ counter ----------
  const T = { x0: 21.47, x1: 24.76, y0: 1.78, y1: 9.4 };  // no pergola, per the client
  // Concealed AC in a 60 x 60 cm louvred box over each slider, finished in the wall colour: its bottom
  // 30 cm over the door head (doors read 2.10 m), its top 30 cm above it (2.70 m), as wide as the opening.
  if (!NCAC) for (const [y0, y1] of [[2.81, 4.214], [6.34, 8.08]]) item(T.x0, (y0 + y1) / 2, "E", p => {
    const w = (y1 - y0) / 2, b0 = 2.1, b1 = 2.7, D = 0.6;
    p.box(-w, w, b0, b1, 0, D - 0.04, mat.limewash);
    for (const [y, t] of [[b0, 0.025], [b1 - 0.025, 0.025]]) p.box(-w, w, y, y + t, 0, D, mat.limewash);
    for (const s of [-1, 1]) p.box(s * w - (s > 0 ? 0.025 : 0), s * w + (s < 0 ? 0.025 : 0), b0, b1, 0, D, mat.limewash);
    for (let y = b0 + 0.045; y < b1 - 0.04; y += 0.05) p.box(-w + 0.025, w - 0.025, y, y + 0.03, D - 0.04, D - 0.005, mat.limewash).rotation.x = -0.5;
  });
  item(25.14, 3.6, "W", p => {  // L-shaped built-in bench, east and south
    p.box(-1.65, 1.65, 0, 0.42, 0, 0.6, mat.walnut);
    p.box(-1.65, 1.65, 0.42, 0.55, 0.02, 0.6, mat.boucle, 0.04);
    p.box(-1.65, 1.65, 0.55, 0.95, 0, 0.18, mat.boucle, 0.06);
    p.box(-1.62, 1.62, 0.02, 0.04, 0.55, 0.6, mat.ledStrip);
    [mat.linenSage, mat.linenBlush, mat.linenSlate, mat.cushionMustard, mat.linenBlush].forEach((c, k) => { const m = p.box(-1.3 + k * 0.62 - 0.22, -1.3 + k * 0.62 + 0.22, 0.55, 0.95, 0.18, 0.32, c, 0.08); m.rotation.x = -0.15; });
  });
  item(23.42, T.y0, "N", p => {
    p.box(-1.1, 1.1, 0, 0.42, 0, 0.6, mat.walnut);
    p.box(-1.1, 1.1, 0.42, 0.55, 0.02, 0.6, mat.boucle, 0.04);
    p.box(-1.1, 1.1, 0.55, 0.95, 0, 0.18, mat.boucle, 0.06);
    [mat.linenSlate, mat.cushionMustard, mat.linenSage].forEach((c, k) => { const m = p.box(-0.7 + k * 0.7 - 0.22, -0.7 + k * 0.7 + 0.22, 0.55, 0.95, 0.18, 0.32, c, 0.08); m.rotation.x = -0.15; });
  });
  item(23.4, 3.4, "S", p => p.cyl(0, 0, 0.45, 0, 0.38, mat.stoneTable, 40));
  item(T.x1, 7.1, "W", p => sofa(p, 2.1, 0.9, mat.boucle, [mat.linenSage, mat.linenBlush, mat.linenSlate]));
  for (const y of [6.3, 7.9]) item(22.1, y, "E", p => {
    p.box(-0.4, 0.4, 0.05, 0.6, 0, 0.8, mat.walnut, 0.02);
    p.box(-0.3, 0.3, 0.3, 0.45, 0.15, 0.78, mat.boucle, 0.05);
    p.box(-0.3, 0.3, 0.45, 0.8, 0.12, 0.3, mat.linenSage, 0.06);
  });
  item(23.35, 7.1, "S", p => p.box(-0.35, 0.35, 0, 0.4, -0.45, 0.45, mat.walnut, 0.02));
  item((T.x0 + T.x1) / 2, 9.27, "S", p => {  // DWG BBQ counter, front at y 8.80 (no sink, per the client)
    const len = T.x1 - T.x0;
    p.box(-len / 2, len / 2, 0.08, 0.9, 0, 0.47, mat.walnut);
    p.box(-len / 2, len / 2, 0, 0.08, 0.04, 0.43, mat.darkTop);
    fronts(p, -len / 2, len / 2, 0.08, 0.9, 0.47, 0.55);
    p.box(-len / 2, len / 2, 0.9, 0.94, 0, 0.49, mat.stoneTable);
    p.box(-len / 2, len / 2, 0.94, 1.3, 0, 0.02, mat.stoneTable);
    p.box(-len / 2 + 0.05, len / 2 - 0.05, 1.28, 1.3, 0.02, 0.05, mat.ledStrip);
    p.box(-0.9, -0.1, 0.94, 1.12, 0.05, 0.45, mat.chrome, 0.02);
    p.box(-0.9, -0.1, 1.12, 1.18, 0.05, 0.4, mat.blackSteel, 0.02);
  });
  for (const [x, y, h] of [[21.8, 4.75, 1.9], [24.5, 5.75, 1.8], [24.45, 8.45, 1.7]]) plant(x, y, h, 0.28);
  for (const y of [5.0, 8.6]) sconce(T.x0, y, "E", 2.0);
  item(23.3, 1.42, "N", p => p.box(-1.85, 1.85, 1.1, 1.35, 0, 0.36, mat.render));  // planter troughs on the parapets
  item(25.4, 3.5, "W", p => p.box(-1.9, 1.9, 1.1, 1.35, 0, 0.36, mat.render));
  for (let x = 21.7; x < 25.0; x += 0.45) plant(x, 1.6, 1.2, 0.1, 1.2);
  for (let y = 2.0; y < 5.4; y += 0.45) plant(25.22, y, 1.2, 0.1, 1.2);
  plant(21.85, 2.2, 1.9, 0.3);

  // --- Ceilings: downlights in every indoor room, linear AC grilles in the living spaces ---------
  const rooms = {};
  for (const f of M.floor) if (f.kind !== "outdoor") (rooms[f.room] ??= []).push(f.outer);
  for (const [name, rings] of Object.entries(rooms)) {
    for (const ring of rings) {
      const xs = ring.map(p => p[0]), ys = ring.map(p => p[1]);
      const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
      const nx = Math.max(1, Math.round((x1 - x0) / 1.4)), ny = Math.max(1, Math.round((y1 - y0) / 1.4));
      for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
        const x = x0 + (i + 0.5) * (x1 - x0) / nx, y = y0 + (j + 0.5) * (y1 - y0) / ny;
        if (!inRing([x, y], ring) || nearEdge([x, y], ring, 0.35)) continue;
        const d = mesh(new THREE.CircleGeometry(0.045, 20), mat.downlight, ceilingBits, false);
        d.rotation.x = Math.PI / 2;
        d.position.set(x, M.ceiling - 0.002, -y);
      }
    }
  }
  if (!NCAC) for (const [x0, x1, y] of [[17.9, 20.4, 4.9], [16.6, 19.2, 6.2], [16.6, 19.2, 9.0]]) {
    const g = mesh(new THREE.BoxGeometry(x1 - x0, 0.01, 0.08), mat.grille, ceilingBits);
    g.position.set((x0 + x1) / 2, M.ceiling - 0.006, -y);
  }

  // Fade in with the finished rooms (materials are shared, so this is global).
  const mats = [...new Set([...collect(root), ...collect(ceilingBits)])];
  for (const m of mats) m.userData.baseOpacity ??= m.opacity;
  function setReveal(t) {
    revealT = t;
    root.visible = t > 0.01;
    for (const m of mats) fade(m, t);
    for (const m of late) fade(m, t);
  }
  return { root, ceilingBits, setReveal };
}

function collect(obj) {
  const out = [];
  obj.traverse(o => o.material && out.push(o.material));
  return out;
}

function inRing([x, y], ring) {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

function nearEdge([x, y], ring, d) {
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [ax, ay] = ring[j], [bx, by] = ring[i];
    const L = (bx - ax) ** 2 + (by - ay) ** 2;
    const t = L ? Math.max(0, Math.min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / L)) : 0;
    if (Math.hypot(x - ax - t * (bx - ax), y - ay - t * (by - ay)) < d) return true;
  }
  return false;
}

// A rectangle with every corner rounded to r, traced into a THREE.Shape or THREE.Path.
function roundRect(s, x0, x1, y0, y1, r) {
  s.moveTo(x0 + r, y0); s.lineTo(x1 - r, y0); s.absarc(x1 - r, y0 + r, r, -Math.PI / 2, 0, false);
  s.lineTo(x1, y1 - r); s.absarc(x1 - r, y1 - r, r, 0, Math.PI / 2, false);
  s.lineTo(x0 + r, y1); s.absarc(x0 + r, y1 - r, r, Math.PI / 2, Math.PI, false);
  s.lineTo(x0, y0 + r); s.absarc(x0 + r, y0 + r, r, Math.PI, Math.PI * 1.5, false);
  return s;
}

// A gathered curtain: a vertical sheet with soft folds, `w` wide and `h` tall, centred at 0.
function curtainGeometry(w, h) {
  const folds = Math.max(3, Math.round(w / 0.12));
  const g = new THREE.PlaneGeometry(w, h, folds * 6, 1);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin((p.getX(i) / w) * folds * Math.PI * 2) * 0.035);
  g.computeVertexNormals();
  return g;
}
