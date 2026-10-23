// Furniture, joinery and fittings, room by room. Positions are plan metres in model.js's frame
// (x east, y north, origin at the DWG plan's corner): taken from the DWG furniture layer where
// it has the piece, otherwise standard sizes fitted to the room as the Notion renders show it.
// Heights are metres above the floor.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

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

export function furnish(scene, M, mat) {
  const root = new THREE.Group();
  const ceilingBits = new THREE.Group();  // shown only with the ceiling (downlights, grilles)
  scene.add(root, ceilingBits);

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
    parent.add(g);
    return g;
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
    };
    return api;
  }

  // --- Reusable pieces ----------------------------------------------------------------------
  // Potted olive-style tree: a few branches, each carrying a spray of small leaves (one merged mesh).
  const plant = (x, y, h = 1.4, pot = 0.22, base = 0) => item(x, y, "S", p => {
    p.g.position.y = base;
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
  });
  const rug = (x0, y0, x1, y1, m = mat.rug) => item((x0 + x1) / 2, (y0 + y1) / 2, "S", p => p.box(-(x1 - x0) / 2, (x1 - x0) / 2, 0.003, 0.016, -(y1 - y0) / 2, (y1 - y0) / 2, m, 0.006));
  const art = (x, y, facing, w, h, zc, k, light = true) => item(x, y, facing, p => {
    p.box(-w / 2 - 0.025, w / 2 + 0.025, zc - h / 2 - 0.025, zc + h / 2 + 0.025, 0, 0.03, mat.walnut);
    p.face(-w / 2, w / 2, zc - h / 2, zc + h / 2, 0.031, mat.art[k % mat.art.length]);
    if (light) {
      p.box(-0.015, 0.015, zc + h / 2 + 0.06, zc + h / 2 + 0.14, 0, 0.1, mat.brass);
      p.box(-w * 0.25, w * 0.25, zc + h / 2 + 0.04, zc + h / 2 + 0.08, 0.06, 0.13, mat.brass, 0.015);
    }
  });
  const ac = (x, y, facing) => item(x, y, facing, p => p.box(-0.45, 0.45, 2.2, 2.5, 0, 0.22, mat.applianceWhite, 0.04));
  const sconce = (x, y, facing, z = 1.8) => item(x, y, facing, p => {
    p.box(-0.04, 0.04, z - 0.14, z + 0.14, 0, 0.03, mat.brass);
    p.cyl(0, 0.08, 0.05, z - 0.1, z + 0.12, mat.lampShade, 20);
  });
  const pendant = (x, y, drop, shape = "globe") => item(x, y, "S", p => {
    p.cyl(0, 0, 0.004, drop, M.ceiling, shape === "globe" ? mat.brass : mat.blackSteel, 6);
    if (shape === "globe") {
      const s = mesh(new THREE.SphereGeometry(0.1, 24, 16), mat.lampShade, p.g);
      s.position.y = drop - 0.08;
    } else {
      p.cyl(0, 0, 0.14, drop - 0.24, drop, mat.lampShade, 10, 0.14);
    }
  });
  function sofa(p, w, depth, fabric, cushions = []) {
    p.box(-w / 2 + 0.04, w / 2 - 0.04, 0.04, 0.2, 0.02, depth - 0.04, mat.walnut, 0.02);
    p.box(-w / 2 + 0.16, w / 2 - 0.16, 0.2, 0.44, 0.2, depth, fabric, 0.06);
    p.box(-w / 2, w / 2, 0.2, 0.86, 0, 0.24, fabric, 0.08);
    for (const s of [-1, 1]) p.box(s * w / 2 - (s > 0 ? 0.18 : 0), s * w / 2 + (s < 0 ? 0.18 : 0), 0.2, 0.62, 0, depth, fabric, 0.07);
    cushions.forEach((c, k) => {
      const cx = -w / 2 + 0.45 + k * ((w - 0.9) / Math.max(1, cushions.length - 1));
      const m = p.box(cx - 0.22, cx + 0.22, 0.45, 0.88, 0.24, 0.38, c, 0.08);
      m.rotation.x = -0.18;
    });
  }
  function chair(p, fabric = mat.oatmeal, legs = mat.walnut) {
    for (const [lx, lz] of [[-0.2, 0.08], [0.2, 0.08], [-0.2, 0.42], [0.2, 0.42]]) p.cyl(lx, lz, 0.018, 0, 0.45, legs, 8);
    const seat = p.cyl(0, 0.27, 0.27, 0.42, 0.54, fabric, 28); seat.scale.z = 0.95;
    const back = p.box(-0.27, 0.27, 0.5, 0.9, 0.0, 0.12, fabric, 0.06); back.rotation.x = -0.12;
    for (const sx of [-1, 1]) { const arm = p.box(sx * 0.27 - 0.06, sx * 0.27 + 0.06, 0.5, 0.74, 0.02, 0.36, fabric, 0.05); arm.rotation.y = sx * 0.25; }
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

  // --- Living room (TV room): L-sofa under the west window, TV wall opposite -------------------
  item(2.94, 2.85, "E", p => sofa(p, 2.7, 0.95, mat.greige, [mat.linenBlush, mat.linenSage, mat.linenSlate, mat.cushionMustard]));
  item(3.87, 0.56, "N", p => sofa(p, 1.86, 0.95, mat.greige, [mat.linenSage]));
  rug(3.7, 0.9, 5.6, 3.9, mat.boucle);
  item(2.94, 2.8, "E", p => p.box(-1.05, 1.05, 2.5, 2.52, 0.02, 0.2, mat.ledStrip));
  item(4.65, 2.52, "S", p => {  // DWG coffee table 0.71 x 1.23
    p.box(-0.355, 0.355, 0.36, 0.42, -0.615, 0.615, mat.stoneTable, 0.03);
    for (const z of [-0.35, 0.35]) p.cyl(0, z, 0.12, 0, 0.36, mat.walnut, 24);
  });
  item(6.15, 2.32, "W", p => p.box(-1.75, 1.75, 0, M.ceiling, 0, 0.012, mat.limewashTaupe));
  item(6.16, 2.25, "W", p => {  // DWG TV unit on the east wall
    p.box(-0.87, 0.87, 0.45, 0.72, 0, 0.4, mat.walnut);
    fronts(p, -0.87, 0.87, 0.45, 0.72, 0.4, 0.58);
    p.box(-0.87, 0.87, 0.72, 0.75, 0, 0.42, mat.stoneTable);
    p.box(-0.87, 0.87, 0.43, 0.45, 0.05, 0.36, mat.ledStrip);
    p.box(-0.8, 0.8, 1.1, 1.95, 0, 0.05, mat.screen);
    for (const s of [-1, 1]) { p.box(s * 1.15 - 0.015, s * 1.15 + 0.015, 1.05, 1.95, 0, 0.03, mat.brass); p.box(s * 1.15 - 0.012, s * 1.15 + 0.012, 1.08, 1.92, 0.03, 0.045, mat.ledStrip); }
  });
  plant(5.85, 0.85, 1.5); plant(5.85, 3.65, 1.4);
  art(2.94, 1.15, "E", 0.7, 1.05, 1.55, 1);
  art(5.2, 0.56, "N", 0.8, 1.05, 1.5, 2);
  ac(4.6, 4.44, "S");
  for (const y of [2.05, 3.54]) item(2.94, y, "E", p => { const m = mesh(curtainGeometry(0.45, 2.45), mat.curtain, p.g); m.position.set(0, 1.27, 0.06); });

  // --- Master bedroom ----------------------------------------------------------------------------
  item(4.13, 7.62, "W", p => {  // king bed, headboard on the bathroom wall (DWG bed outline)
    for (const k of [-1, 0, 1]) p.box(k * 0.92 - 0.45, k * 0.92 + 0.45, 0.25, 1.25, 0, 0.1, mat.boucle, 0.04);
    p.box(-0.95, 0.95, 0.06, 0.32, 0.08, 2.15, mat.oakVeneer, 0.02);
    p.box(-0.92, 0.92, 0.32, 0.56, 0.12, 2.1, mat.sheet, 0.06);
    p.box(-0.94, 0.94, 0.5, 0.6, 0.85, 2.13, mat.linenSage, 0.04);
    p.box(-0.95, 0.95, 0.54, 0.62, 1.55, 1.9, mat.boucle, 0.03);
    for (const [x, c, z, w] of [[-0.48, mat.sheet, 0.14, 0.3], [0.48, mat.sheet, 0.14, 0.3], [-0.45, mat.linenBlush, 0.3, 0.27], [0.45, mat.linenBlush, 0.3, 0.27], [0, mat.boucle, 0.42, 0.22]]) {
      const m = p.box(x - w, x + w, 0.56, 0.86 - (z > 0.4 ? 0.1 : 0), z, z + 0.16, c, 0.07);
      m.rotation.x = -0.25;
    }
    p.box(-0.96, 0.96, 0.6, 0.63, 1.3, 1.65, mat.boucle, 0.01);
  });
  for (const y of [8.8, 6.45]) {
    item(4.13, y, "W", p => {
      p.box(-0.24, 0.24, 0.22, 0.55, 0, 0.42, mat.walnut);
      p.box(-0.22, 0.22, 0.37, 0.374, 0.42, 0.423, mat.grille);
      for (const [lx, lz] of [[-0.2, 0.05], [0.2, 0.05], [-0.2, 0.37], [0.2, 0.37]]) p.cyl(lx, lz, 0.014, 0, 0.22, mat.walnut, 6);
    });
    pendant(3.95, y, 1.15);
  }
  art(4.13, 7.62, "W", 1.6, 0.95, 1.85, 0);
  rug(1.56, 6.22, 3.9, 9.0);
  item(0.56, 6.75, "E", p => {  // DWG wardrobe: smoked-glass sliding doors in a gypsum frame
    p.box(-2.16, 2.16, 0, M.ceiling, 0, 0.6, mat.whiteLacquer);
    p.box(-2.08, 2.08, 0.08, 2.5, 0.6, 0.62, mat.bronzeGlass);
    for (const x of [-2.08, -1.04, 0, 1.04, 2.08]) p.box(x - 0.015, x + 0.015, 0.08, 2.5, 0.62, 0.635, mat.walnut);
  });
  item(2.36, 4.55, "N", p => {  // dressing table with the backlit oval mirror
    p.box(-0.53, 0.53, 0.72, 0.76, 0, 0.5, mat.walnut);
    p.box(-0.53, -0.18, 0, 0.72, 0, 0.48, mat.walnut);
    for (const y of [0.24, 0.48]) p.box(-0.52, -0.19, y - 0.002, y + 0.002, 0.48, 0.483, mat.grille);
    p.box(0.2, 0.53, 0, 0.72, 0, 0.48, mat.walnut);
    for (let k = 0; k < 8; k++) p.cyl(0.22 + k * 0.042, 0.48, 0.012, 0.03, 0.7, mat.walnut, 6);
    p.oval(0, 1.38, 0.52, 0.4, 0.012, mat.mirror, true);
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
  for (const x of [1.72, 3.2]) item(x, 9.02, "S", p => {
    const m = mesh(curtainGeometry(0.55, 2.45), mat.curtain, p.g); m.position.set(0, 1.27, 0.12);
  });
  // Master suite lobby: tall lit shoe cabinet (DWG 0.41 x 0.80)
  item(6.37, 6.06, "W", p => {
    p.box(-0.4, 0.4, 0, 2.4, 0, 0.41, mat.walnut);
    for (let k = 0; k < 7; k++) p.box(-0.37, 0.37, 0.3 + k * 0.3, 0.31 + k * 0.3, 0.05, 0.38, mat.ledStrip);
    p.box(-0.37, 0.37, 0.1, 2.32, 0.39, 0.41, mat.smokedGlass);
  });

  // --- Master bathroom: vanity west, WC east, arched shower opening to the north ----------------
  item(4.22, 7.3, "E", p => {  // DWG vanity 0.51 x 1.40, round basin
    p.box(-0.7, 0.7, 0, M.ceiling, 0, 0.02, mat.oakSlats);
    vanityDrawers(p, -0.68, 0.2, 0.3, 0.82, 0.48);
    p.box(0.2, 0.68, 0.3, 0.33, 0, 0.48, mat.walnut); p.box(0.66, 0.68, 0.3, 0.82, 0, 0.48, mat.walnut);
    p.box(0.2, 0.68, 0.55, 0.57, 0, 0.48, mat.walnut);
    for (const [x, y] of [[0.32, 0.33], [0.52, 0.33], [0.42, 0.57]]) { const t = p.cyl(x, 0.25, 0.08, y, y + 0.16, mat.sheet, 16); t.rotation.x = Math.PI / 2; t.position.set(x, y + 0.08, 0.25); }
    p.box(-0.7, 0.7, 0.82, 0.86, 0, 0.52, mat.marbleTop);
    p.box(-0.68, 0.68, 0.27, 0.29, 0.05, 0.44, mat.ledStrip);
    p.cyl(0.08, 0.28, 0.19, 0.86, 0.98, mat.ceramic, 32, 0.15);
    p.cyl(0.08, 0.05, 0.012, 0.86, 1.15, mat.chrome, 8);
    p.box(-0.5, 0.62, 1.15, 2.0, 0.02, 0.05, mat.ledStrip, 0.12);
    p.box(-0.47, 0.59, 1.18, 1.97, 0.03, 0.06, mat.mirror, 0.12);
  });
  item(6.24, 7.3, "W", p => {  // wall-hung WC on a slatted wall, cabinet above
    p.box(-0.55, 0.55, 0, M.ceiling, 0, 0.02, mat.oakSlats);
    p.box(-0.55, 0.55, 0, 1.1, 0.02, 0.2, mat.oakSlats);
    p.box(-0.19, 0.19, 0.3, 0.42, 0.2, 0.75, mat.ceramic, 0.12);
    p.box(-0.19, 0.19, 0.42, 0.45, 0.22, 0.75, mat.ceramic, 0.012);
    p.box(-0.12, 0.12, 1.0, 1.08, 0.2, 0.21, mat.brass);
    p.box(-0.55, 0.55, 1.65, 2.45, 0, 0.32, mat.oakVeneer);
    p.box(-0.53, 0.53, 1.62, 1.64, 0.02, 0.3, mat.ledStrip);
  });
  item(4.52, 8.0, "S", p => {  // towel radiator on the shower partition
    for (const s of [-1, 1]) p.box(s * 0.2 - 0.01, s * 0.2 + 0.01, 0.95, 1.75, 0.03, 0.06, mat.brass);
    for (let k = 0; k < 8; k++) p.box(-0.2, 0.2, 1.0 + k * 0.1, 1.012 + k * 0.1, 0.035, 0.05, mat.brass);
  });
  item(6.24, 8.62, "W", p => {  // shower: lit niche shelves and a fold-down teak seat
    for (const y of [1.05, 1.45]) {
      p.box(-0.38, 0.38, y - 0.02, y, 0, 0.16, mat.stoneWall);
      p.box(-0.38, 0.38, y + 0.3, y + 0.31, 0, 0.12, mat.ledStrip);
    }
    p.box(-0.3, 0.3, 0.45, 0.48, 0.02, 0.38, mat.oakSlats);
  });
  item(5.25, 9.02, "S", p => {  // rain head
    p.cyl(0, 0.38, 0.12, 2.18, 2.2, mat.chrome, 24);
    p.box(-0.01, 0.01, 2.2, M.ceiling, 0.37, 0.39, mat.chrome);
  });
  item(5.25, 8.06, "N", p => {  // arch over the shower opening (dashed in the DWG)
    const s = new THREE.Shape();
    s.moveTo(-0.43, 1.85); s.absarc(0, 1.85, 0.43, Math.PI, 0, true); s.lineTo(0.43, M.ceiling); s.lineTo(-0.43, M.ceiling); s.lineTo(-0.43, 1.85);
    const m = mesh(new THREE.ExtrudeGeometry(s, { depth: 0.1, bevelEnabled: false, curveSegments: 24 }), mat.stoneWall, p.g);
    m.position.z = -0.05;
  });

  // --- Guest bathroom: bath-shower west, vanity east, WC under the window ----------------------
  item(12.5, 8.05, "E", p => {
    p.box(-1.08, 1.08, 0, M.ceiling, 0, 0.02, mat.oakSlats);
    p.box(-0.85, 0.85, 0, 0.55, 0.02, 0.75, mat.stoneWall);
    p.box(-0.78, 0.78, 0.52, 0.56, 0.08, 0.7, mat.ceramic);
    p.box(-0.02, 0.85, 0.56, 2.0, 0.75, 0.76, mat.clearGlass);
    p.box(-0.03, 0.86, 1.98, 2.0, 0.74, 0.77, mat.blackSteel);
    p.box(-0.03, -0.01, 0.56, 2.0, 0.74, 0.77, mat.blackSteel);
    p.box(-0.2, 0.2, 2.15, 2.17, 0.15, 0.55, mat.chrome);
  });
  item(14.66, 7.75, "W", p => {  // floating stone vanity, vessel basin (DWG circle), rounded mirror
    p.box(-0.8, 0.8, 0, M.ceiling, 0, 0.02, mat.oakSlats);
    vanityDrawers(p, -0.75, 0.75, 0.32, 0.5, 0.45);
    p.box(-0.8, 0.8, 0.68, 0.8, 0, 0.5, mat.stoneTable, 0.01);
    p.box(-0.75, 0.75, 0.3, 0.32, 0.05, 0.42, mat.ledStrip);
    p.cyl(0, 0.27, 0.2, 0.8, 0.94, mat.ceramic, 32, 0.15);
    p.box(-0.42, 0.42, 1.15, 1.95, 0.02, 0.05, mat.bronze, 0.1);
    p.box(-0.4, 0.4, 1.17, 1.93, 0.04, 0.06, mat.mirror, 0.09);
  });
  item(13.95, 9.18, "S", p => {
    p.box(-0.19, 0.19, 0.3, 0.42, 0.02, 0.57, mat.ceramic, 0.12);
    p.box(-0.12, 0.12, 1.0, 1.08, 0, 0.02, mat.brass);
  });
  for (const x of [13.0, 13.25]) item(x, 9.18, "S", p => {  // two tall lit niches between bath and window
    for (const s of [-1, 1]) p.box(s * 0.11 - 0.02, s * 0.11 + 0.02, 0.9, 2.1, 0, 0.2, mat.stoneWall);
    p.box(-0.13, 0.13, 0.86, 0.9, 0, 0.2, mat.stoneWall); p.box(-0.13, 0.13, 2.1, 2.14, 0, 0.2, mat.stoneWall);
    p.box(-0.09, 0.09, 0.9, 2.1, 0, 0.01, mat.oakVeneer);
    for (let k = 0; k < 4; k++) p.box(-0.09, 0.09, 1.15 + k * 0.28, 1.17 + k * 0.28, 0, 0.19, mat.oakVeneer);
    p.box(-0.09, 0.09, 2.08, 2.09, 0.02, 0.17, mat.ledStrip);
  });

  // --- Kitchen: U of white flat-panel units, oak uppers, tall oven tower and black fridge -------
  const K = { x0: 6.48, x1: 10.21, y0: 5.67, y1: 9.09, front: 0.6 };
  function run(x, y, facing, len, { sink = -1, hob = -1, uppers = true, window } = {}) {
    item(x, y, facing, p => {
      p.box(-len / 2, len / 2, 0, 0.1, 0.06, K.front - 0.06, mat.darkTop);
      p.box(-len / 2, len / 2, 0.02, 0.04, K.front - 0.08, K.front - 0.06, mat.ledStrip);
      p.box(-len / 2, len / 2, 0.1, 0.88, 0, K.front, mat.greyLacquer);
      for (const y of [0.4, 0.62]) p.box(-len / 2, len / 2, y - 0.002, y + 0.002, K.front, K.front + 0.003, mat.grille);
      const n = Math.max(1, Math.round(len / 0.6));
      for (let k = 1; k < n; k++) p.box(-len / 2 + k * len / n - 0.002, -len / 2 + k * len / n + 0.002, 0.12, 0.86, K.front, K.front + 0.003, mat.grille);
      p.box(-len / 2, len / 2, 0.88, 0.92, 0, K.front + 0.01, mat.marbleTop);
      p.box(-len / 2, len / 2, 0.88, 0.92, K.front + 0.01, K.front + 0.02, mat.darkTop);
      if (window) for (let k = 0; k < 24; k++) p.box(window[0] + 0.05, window[1] - 0.05, 1.0 + k * 0.045, 1.012 + k * 0.045, -0.06, -0.03, mat.planter);
      const spans = window ? [[-len / 2, window[0]], [window[1], len / 2]] : [[-len / 2, len / 2]];
      for (const [a, b] of spans) if (b - a > 0.05) p.box(a, b, 0.92, 1.58, 0, 0.015, mat.marbleTop);
      if (sink >= 0) {
        p.box(sink - 0.35, sink + 0.35, 0.921, 0.925, 0.12, 0.5, mat.blackSteel);
        p.cyl(sink, 0.08, 0.015, 0.92, 1.25, mat.chrome, 8);
      }
      if (hob >= 0) {
        p.box(hob - 0.38, hob + 0.38, 0.921, 0.93, 0.06, 0.56, mat.blackGlass);
        p.box(hob - 0.45, hob + 0.45, 1.5, 1.62, 0, 0.5, mat.chrome);
      }
      if (uppers) {
        for (const [a, b] of spans) {
          if (b - a < 0.05) continue;
          p.box(a, b, 1.6, 2.25, 0, 0.35, mat.oakVeneer);
          p.box(a, b, 1.58, 1.6, 0.05, 0.3, mat.ledStrip);
          p.box(a, b, 2.25, M.ceiling, 0, 0.35, mat.whiteLacquer);
        }
      }
    });
  }
  run(K.x0, (6.27 + K.y1 - K.front) / 2, "E", K.y1 - K.front - 6.27, { hob: 0.1 });  // west run, hob
  run((K.x0 + 9.6) / 2, K.y1, "S", 9.6 - K.x0, { sink: 8.1 - (K.x0 + 9.6) / 2, window: [7.45 - (K.x0 + 9.6) / 2, 8.75 - (K.x0 + 9.6) / 2] });
  run((K.x0 + 8.6) / 2, K.y0, "N", 8.6 - K.x0, { uppers: false });                   // south run
  item(K.x1, 8.12, "W", p => {  // DWG tall units 0.61 x 1.94: oven tower then the fridge
    p.box(0.25, 0.97, 0, M.ceiling, 0, 0.6, mat.whiteLacquer);
    p.box(0.33, 0.89, 0.85, 1.45, 0.6, 0.62, mat.blackGlass);
    p.box(0.36, 0.86, 1.5, 1.88, 0.6, 0.62, mat.blackGlass);
    p.box(-0.67, 0.25, 0, 1.9, 0.02, 0.6, mat.blackSteel, 0.01);
    p.box(-0.22, -0.2, 0.9, 1.4, 0.6, 0.62, mat.chrome);
    p.box(-0.67, 0.25, 1.9, M.ceiling, 0, 0.6, mat.whiteLacquer);
    p.box(-0.97, -0.67, 0, M.ceiling, 0, 0.6, mat.whiteLacquer);
  });

  // --- Laundry: full-height oak joinery on the left, counter and stacked machines ahead ---------
  item(10.33, 8.03, "E", p => {
    p.box(-1.1, 1.1, 0, M.ceiling - 0.05, 0, 0.6, mat.oakVeneer);
    fronts(p, -1.1, 1.1, 0.05, 2.5, 0.6, 0.55);
    for (const x of [-0.6, -0.05, 0.5]) {
      p.box(x - 0.24, x + 0.24, 0.08, 0.45, 0.78, 0.8, mat.oakVeneer);
      p.box(x - 0.2, x + 0.2, 0.12, 0.42, 0.6, 0.78, mat.applianceWhite, 0.02);
    }
  });
  item(11.35, 9.18, "S", p => {
    p.box(-0.42, 0.42, 0.1, 0.88, 0, 0.6, mat.oakVeneer);
    for (const y of [0.36, 0.62]) p.box(-0.41, 0.41, y - 0.002, y + 0.002, 0.6, 0.603, mat.walnut);
    p.box(-0.42, 0.42, 0.88, 0.92, 0, 0.62, mat.marbleTop);
    p.box(-0.42, 0.42, 1.6, 2.5, 0, 0.35, mat.oakVeneer);
    p.box(-0.42, 0.42, 1.58, 1.6, 0.05, 0.3, mat.ledStrip);
  });
  item(12.06, 9.18, "S", p => {
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

  // --- Entrance: lit bench niche + shoe unit beside the front door, oval mirror, gallery ---------
  item(9.2, 3.66, "N", p => {  // shoe cabinet next to the door
    p.box(-0.19, 0.19, 0, 1.0, 0, 0.4, mat.whiteLacquer);
    p.box(-0.19, 0.19, 1.0, 1.03, 0, 0.42, mat.oakVeneer);
  });
  item(10.04, 3.76, "N", p => {  // bench niche: arched oak surround, glowing back, hooks
    p.box(-0.6, 0.6, 0, 2.4, 0, 0.04, mat.oakVeneer);
    p.box(-0.5, 0.5, 0.42, 2.1, 0.04, 0.05, mat.limewash);
    for (const s of [-1, 1]) p.box(s * 0.5 - 0.012, s * 0.5 + 0.012, 0.5, 2.08, 0.05, 0.07, mat.ledStrip);
    p.box(-0.48, 0.48, 2.08, 2.09, 0.05, 0.08, mat.ledStrip);
    p.box(-0.02, 0.38, 0.85, 1.85, 0.05, 0.07, mat.ledStrip, 0.18);
    p.box(0.0, 0.36, 0.87, 1.83, 0.06, 0.08, mat.mirror, 0.17);
    p.box(-0.5, 0.5, 0.42, 0.5, 0, 0.45, mat.boucle, 0.04);
    p.box(-0.5, 0.5, 0.05, 0.42, 0, 0.42, mat.oakVeneer);
    p.box(-0.5, 0.5, 0.04, 0.06, 0.05, 0.38, mat.ledStrip);
    p.box(-0.5, 0.5, 2.1, 2.4, 0, 0.45, mat.oakVeneer);
    for (const s of [-1, 1]) p.box(s * 0.55 - 0.05, s * 0.55 + 0.05, 0, 2.1, 0, 0.45, mat.oakVeneer);
    for (let k = 0; k < 4; k++) p.box(-0.35 + k * 0.12, -0.33 + k * 0.12, 1.6, 1.62, 0.05, 0.1, mat.brass);
    p.box(-0.3, -0.05, 0.5, 0.75, 0.08, 0.2, mat.linenBlush, 0.08);
  });
  item(7.2, 5.55, "S", p => {  // organic backlit mirror over an upholstered bench
    p.oval(0, 1.35, 0.42, 0.78, 0.015, mat.mirror, true);
    p.box(-0.65, 0.65, 0.05, 0.45, 0.05, 0.45, mat.boucle, 0.12);
    p.box(0.55, 0.85, 1.0, 1.03, 0, 0.18, mat.oakVeneer);
  });
  sconce(8.25, 5.55, "S"); sconce(6.15, 5.55, "S"); sconce(9.0, 3.66, "N", 1.75);
  item(8.48, 3.72, "N", p => {  // front door: arched walnut leaf, surround and long brass pull
    p.arch(-0.56, 0.56, 0, 2.25, -0.02, 0.05, mat.walnut);
    p.arch(-0.46, 0.46, 0, 2.12, 0.03, 0.02, mat.oakVeneer);
    p.box(0.3, 0.33, 0.7, 1.5, 0.06, 0.09, mat.brass);
  });
  plant(6.8, 3.88, 1.6, 0.24);
  [[3.85, 0.36, 0.48, 1.75], [4.3, 0.36, 0.36, 1.45], [3.95, 0.3, 0.3, 1.2]].forEach(([y, w, h, z], k) => art(6.51, y, "E", w, h, z, k));
  rug(6.9, 3.95, 9.8, 5.15, mat.linenBlush);

  // --- Reception: TV wall with lit arched niches, two sofas, armchair ---------------------------
  item(17.25, 3.67, "E", p => {  // 30 cm deep feature wall: arched niches either side, a lit slot under the TV
    const D = 0.3, wall = new THREE.Shape([new THREE.Vector2(-1.7, 0), new THREE.Vector2(1.7, 0), new THREE.Vector2(1.7, M.ceiling), new THREE.Vector2(-1.7, M.ceiling)]);
    const hole = (x0, x1, y0, y1, r) => {
      const h = new THREE.Path();
      h.moveTo(x0, y0); h.lineTo(x1, y0); h.lineTo(x1, y1 - r);
      if (r) h.absarc((x0 + x1) / 2, y1 - r, r, 0, Math.PI, false); else h.lineTo(x1, y1), h.lineTo(x0, y1);
      h.lineTo(x0, y0);
      return h;
    };
    for (const s of [-1, 1]) wall.holes.push(hole(s * 1.3 - 0.27, s * 1.3 + 0.27, 0.6, 2.2, 0.27));
    wall.holes.push(hole(-0.95, 0.95, 0.42, 0.66, 0));
    mesh(new THREE.ExtrudeGeometry(wall, { depth: D, bevelEnabled: false, curveSegments: 20 }), mat.limewash, p.g);
    for (const s of [-1, 1]) {
      p.arch(s * 1.3 - 0.27, s * 1.3 + 0.27, 0.6, 2.2, 0.005, 0.02, mat.oakVeneer);
      for (let k = 0; k < 4; k++) {
        p.box(s * 1.3 - 0.27, s * 1.3 + 0.27, 0.6 + k * 0.36, 0.625 + k * 0.36, 0, D, mat.oakVeneer);
        p.box(s * 1.3 - 0.25, s * 1.3 + 0.25, 0.94 + k * 0.36, 0.95 + k * 0.36, 0.05, D - 0.04, mat.ledStrip);
      }
      p.cyl(s * 1.3 + 0.08, 0.15, 0.05, 0.98, 1.2, mat.linenSlate, 16);
      p.box(s * 1.3 - 0.2, s * 1.3 - 0.05, 1.33, 1.55, 0.06, 0.22, mat.linenBlush);
    }
    p.box(-0.95, 0.95, 0.42, 0.44, 0, D, mat.oakVeneer);
    p.box(-0.93, 0.93, 0.645, 0.655, 0.05, D - 0.04, mat.ledStrip);
    p.box(-0.85, 0.85, 1.0, 1.95, D, D + 0.04, mat.screen);
  });
  item(18.9, 1.95, "N", p => sofa(p, 2.2, 0.95, mat.boucle, [mat.linenSlate, mat.linenBlush, mat.linenSlate]));
  item(21.15, 3.85, "W", p => sofa(p, 2.0, 0.92, mat.boucle, [mat.linenSlate, mat.linenBlush]));
  item(19.1, 5.55, "S", p => {  // DWG armchair: walnut frame, slate cushions
    for (const s of [-1, 1]) p.box(s * 0.36 - 0.03, s * 0.36 + 0.03, 0.05, 0.62, 0.05, 0.75, mat.walnut, 0.015);
    p.box(-0.33, 0.33, 0.3, 0.44, 0.08, 0.72, mat.linenSlate, 0.05);
    const b = p.box(-0.33, 0.33, 0.44, 0.88, 0.05, 0.18, mat.linenSlate, 0.05); b.rotation.x = -0.2;
  });
  rug(17.9, 2.4, 20.5, 5.0);
  item(19.0, 3.7, "S", p => {  // oval marble coffee table on two walnut drums
    const top = p.cyl(0, 0, 0.55, 0.36, 0.42, mat.stoneTable, 40); top.scale.z = 0.55;
    for (const x of [-0.25, 0.25]) p.cyl(x, 0, 0.15, 0, 0.36, mat.walnut, 24);
  });
  item(20.45, 2.15, "S", p => { p.cyl(0, 0, 0.25, 0.52, 0.56, mat.marbleTop, 32); p.cyl(0, 0, 0.13, 0, 0.52, mat.walnut, 24); });
  plant(17.6, 2.25, 1.6, 0.24);
  art(18.0, 1.95, "N", 0.7, 1.0, 1.6, 0); art(18.85, 1.95, "N", 0.7, 1.0, 1.6, 1);
  ac(20.1, 1.95, "N");
  for (const [y0, y1] of [[2.78, 4.24], [6.34, 8.08]]) {  // curtains either side of each slider
    for (const y of [y0 - 0.15, y1 + 0.15]) item(21.22, y, "W", p => {
      const m = mesh(curtainGeometry(0.45, 2.5), mat.curtain, p.g); m.position.set(0, 1.3, 0.1);
    });
    item(21.22, (y0 + y1) / 2, "W", p => { const m = mesh(curtainGeometry(y1 - y0, 2.45), mat.sheer, p.g); m.position.set(0, 1.25, 0.2); });
  }

  // --- Dining: walnut table for six, tub chairs, lantern pendants; coffee bar and desk ---------
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
  item(14.78, 8.2, "E", p => {  // DWG unit: walnut sideboard under an organic backlit mirror
    p.box(-1.0, 1.0, 0.12, 0.8, 0, 0.44, mat.walnut);
    fronts(p, -1.0, 1.0, 0.12, 0.8, 0.44, 0.5);
    p.box(-1.0, 1.0, 0.8, 0.83, 0, 0.45, mat.stoneTable);
    p.oval(0, 1.55, 0.42, 0.55, 0.02, mat.mirror, true);
  });
  plant(14.85 + 0.25, 9.2, 1.0, 0.16);
  item(20.55, 9.38, "S", p => {  // coffee station: walnut base, white top, lit floating shelves
    p.box(-0.67, 0.67, 0.1, 0.88, 0, 0.55, mat.walnut);
    fronts(p, -0.67, 0.67, 0.1, 0.88, 0.55, 0.45);
    p.box(-0.67, 0.67, 0.88, 0.92, 0, 0.57, mat.marbleTop);
    for (const y of [1.4, 1.8]) { p.box(-0.67, 0.67, y, y + 0.035, 0, 0.28, mat.oakVeneer); p.box(-0.65, 0.65, y - 0.012, y, 0.03, 0.26, mat.ledStrip); }
    p.box(-0.45, -0.15, 0.92, 1.3, 0.08, 0.38, mat.blackSteel);
  });
  art(19.4, 9.38, "S", 0.55, 1.1, 1.55, 2);
  item(16.95, 9.5, "S", p => p.box(-1.0, 1.0, 2.5, 2.52, 0.02, 0.22, mat.ledStrip));
  plant(21.0, 5.9, 1.7, 0.25);

  // --- Terrace: decking, pergola, terracotta canopy, L bench, lounge set, BBQ counter ----------
  const T = { x0: 21.47, x1: 24.76, y0: 1.78, y1: 9.4 };
  for (let x = T.x0 + 0.2; x < T.x1; x += 0.55) item(x, 5.6, "N", p => {
    p.box(-0.04, 0.04, 2.55, 2.75, 0, T.y1 - 5.6, mat.walnut);
    p.box(-0.015, 0.015, 2.54, 2.55, 0.1, T.y1 - 5.7, mat.ledStrip);
  });
  for (const y of [5.6, 9.4]) item((T.x0 + T.x1) / 2, y, "S", p => {
    p.box(-(T.x1 - T.x0) / 2, (T.x1 - T.x0) / 2, 2.4, 2.55, -0.06, 0.06, mat.walnut);
    p.box(-(T.x1 - T.x0) / 2, (T.x1 - T.x0) / 2, 2.385, 2.4, -0.03, 0.03, mat.ledStrip);
  });
  for (const x of [T.x0 + 0.1, T.x1 - 0.1]) item(x, 5.6, "S", p => p.box(-0.07, 0.07, 0, 2.4, -0.07, 0.07, mat.walnut));
  item(T.x0, 3.5, "E", p => {  // tiled canopy over the south slider
    const roof = p.box(-1.1, 1.1, 0, 0.06, 0, 1.0, mat.roofTiles);
    roof.position.y = 2.75; roof.rotation.x = 0.35;
    p.box(-1.1, 1.1, 2.55, 2.75, 0, 0.12, mat.render);
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
  for (const [x0, x1, y] of [[17.9, 20.4, 4.9], [16.6, 19.2, 6.2], [16.6, 19.2, 9.0]]) {
    const g = mesh(new THREE.BoxGeometry(x1 - x0, 0.01, 0.08), mat.grille, ceilingBits);
    g.position.set((x0 + x1) / 2, M.ceiling - 0.006, -y);
  }

  // Fade in with the finished rooms (materials are shared, so this is global).
  const mats = [...new Set([...collect(root), ...collect(ceilingBits)])];
  for (const m of mats) m.userData.baseOpacity ??= m.opacity;
  function setReveal(t) {
    root.visible = t > 0.01;
    for (const m of mats) {
      const want = t < 0.999 || m.userData.baseOpacity < 1;
      if (m.transparent !== want) { m.transparent = want; m.needsUpdate = true; }
      m.opacity = m.userData.baseOpacity * t;
    }
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

// A gathered curtain: a vertical sheet with soft folds, `w` wide and `h` tall, centred at 0.
function curtainGeometry(w, h) {
  const folds = Math.max(3, Math.round(w / 0.12));
  const g = new THREE.PlaneGeometry(w, h, folds * 6, 1);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin((p.getX(i) / w) * folds * Math.PI * 2) * 0.035);
  g.computeVertexNormals();
  return g;
}
