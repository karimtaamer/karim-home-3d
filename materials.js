// Material library for the finished flat. Looks follow the Notion renders (warm oak, limewash,
// beige stone, white flat-panel joinery); textures are Poly Haven scans (CC0) in textures/.
// UVs are in metres (floors use plan x/y, extruded sides use length/height), so `size` is the
// real-world width one texture tile covers.
import * as THREE from "three";

const loader = new THREE.TextureLoader();
const cache = new Map();

function map(file, size, srgb, rotate = 0) {
  const key = `${file}|${size}|${rotate}`;
  if (!cache.has(key)) {
    const t = loader.load(`textures/${file}`);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(1 / size, 1 / size);
    t.rotation = rotate;
    t.anisotropy = 8;
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    cache.set(key, t);
  }
  return cache.get(key);
}

// A scanned surface: colour from the scan (tinted), plus its normal and roughness maps.
function scanned(id, size, { tint = 0xffffff, normal = 1, rotate = 0, colour = true, ...rest } = {}) {
  return new THREE.MeshStandardMaterial({
    color: tint,
    map: colour ? map(`${id}_diff.jpg`, size, true, rotate) : null,
    normalMap: map(`${id}_nor.jpg`, size, false, rotate),
    normalScale: new THREE.Vector2(normal, normal),
    roughnessMap: map(`${id}_rough.jpg`, size, false, rotate),
    ...rest,
  });
}

// Polished marble: warm white with soft grey veins (worktops, splashbacks, side tables).
function marbleTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 512;
  const g = c.getContext("2d");
  g.fillStyle = "#e6ddd2";
  g.fillRect(0, 0, 512, 512);
  let s = 7;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  g.filter = "blur(1.5px)";
  for (let k = 0; k < 26; k++) {
    g.strokeStyle = `rgba(${150 + rnd() * 30},${138 + rnd() * 25},${125 + rnd() * 25},${0.1 + rnd() * 0.2})`;
    g.lineWidth = 0.5 + rnd() * 1.5;
    g.beginPath();
    let x = rnd() * 512, y = rnd() * 512;
    g.moveTo(x, y);
    for (let i = 0; i < 6; i++) g.bezierCurveTo(x + rnd() * 160 - 40, y + rnd() * 120 - 60, x + rnd() * 200, y + rnd() * 160 - 80, (x += 60 + rnd() * 80), (y += rnd() * 80 - 40));
    g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1 / 1.6, 1 / 1.6);
  t.anisotropy = 8;
  return t;
}

// Large-format honed stone tiles (60 x 120 cm), pale warm beige with fine grout, as in the bathrooms.
function stoneTileTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 1024;  // 2.4 m square: 4 tiles across, 2 up
  const g = c.getContext("2d");
  g.fillStyle = "#e2cdb4";
  g.fillRect(0, 0, 1024, 1024);
  let s = 3;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  for (let k = 0; k < 9000; k++) {
    g.fillStyle = `rgba(${150 + rnd() * 80},${130 + rnd() * 70},${100 + rnd() * 60},${rnd() * 0.12})`;
    g.fillRect(rnd() * 1024, rnd() * 1024, 1 + rnd() * 5, 1 + rnd() * 5);
  }
  g.fillStyle = "#c6b096";
  for (let i = 0; i <= 4; i++) g.fillRect(i * 256 - 1, 0, 2, 1024);
  for (let j = 0; j <= 2; j++) g.fillRect(0, j * 512 - 1, 1024, 2);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1 / 2.4, 1 / 2.4);
  t.anisotropy = 8;
  return t;
}

// Slatted timber: `pitch` m boards with dark grooves, as a bump map (boards run horizontally).
function slatBump(pitch = 0.04, groove = 3) {
  const c = document.createElement("canvas");
  c.width = 8; c.height = 256;  // 8 slats
  const g = c.getContext("2d");
  g.fillStyle = "#fff";
  g.fillRect(0, 0, 8, 256);
  g.fillStyle = "#000";
  for (let k = 0; k < 8; k++) g.fillRect(0, k * 32, 8, groove);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1 / (8 * pitch), 1 / (8 * pitch));
  return t;
}

// Wood-look porcelain planks: 12 cm boards with hairline joints, panel ends every 1.2 m.
function plankBump() {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 128;  // 1.2 x 0.24 m: two boards
  const g = c.getContext("2d");
  g.fillStyle = "#fff";
  g.fillRect(0, 0, 256, 128);
  g.fillStyle = "#777";
  for (const y of [0, 64]) g.fillRect(0, y, 256, 1);
  g.fillRect(0, 0, 1, 128);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(1 / 1.2, 1 / 0.24);
  return t;
}

// Abstract art like the canvases in the renders: soft overlapping arcs in blush, slate and sage.
function artTexture(seed, palette) {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 340;
  const g = c.getContext("2d");
  let s = seed;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  g.fillStyle = "#efe4d6";
  g.fillRect(0, 0, c.width, c.height);
  for (let k = 0; k < 7; k++) {
    g.fillStyle = palette[k % palette.length];
    g.globalAlpha = 0.75 + rnd() * 0.25;
    g.beginPath();
    g.ellipse(rnd() * 256, rnd() * 340, 50 + rnd() * 90, 60 + rnd() * 110, rnd() * 3, 0, Math.PI * 2);
    g.fill();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function makeMaterials(clip) {
  const std = o => new THREE.MeshStandardMaterial(o);
  const glow = (hex, strength = 2.5) => new THREE.MeshStandardMaterial({ color: 0x000000, emissive: hex, emissiveIntensity: strength });
  const M = {
    // Floors
    oak: scanned("laminate_floor_02", 1.7, { tint: 0xffd5a8, normal: 0.6 }),
    stone: std({ map: stoneTileTexture(), roughness: 0.45 }),
    deck: scanned("laminate_floor_02", 1.4, { tint: 0xa8907a, normal: 1.2 }),
    // Walls: limewash (flat colour, plaster relief from the scan)
    limewash: scanned("beige_wall_001", 3, { colour: false, tint: 0xeee2d2, normal: 1.4 }),
    stoneWall: std({ map: stoneTileTexture(), roughness: 0.5 }),
    render: scanned("beige_wall_002", 3, { colour: false, tint: 0xe8d3b8, normal: 1.6 }),
    roofTiles: scanned("clay_roof_tiles_02", 1.25),
    // Joinery and surfaces
    oakVeneer: scanned("laminate_floor_02", 1.7, { tint: 0xffdcb4, roughness: 0.55, rotate: Math.PI / 2, normal: 0.3 }),
    oakSlats: std({ color: 0xf2d6b8, map: map("oak_veneer_01_diff.jpg", 1.2, true, Math.PI / 2), bumpMap: slatBump(), bumpScale: 6, roughness: 0.6 }),
    oakBattens: std({ color: 0xf0cfa8, map: map("oak_veneer_01_diff.jpg", 1.2, true, Math.PI / 2), bumpMap: slatBump(0.05, 5), bumpScale: 9, roughness: 0.6 }),
    woodTile: std({ color: 0xf3cf9e, map: map("oak_veneer_01_diff.jpg", 1.2, true, Math.PI / 2), bumpMap: plankBump(), bumpScale: 1.5, roughness: 0.5 }),
    walnut: scanned("laminate_floor_02", 1.7, { tint: 0x9c8070, roughness: 0.5, rotate: Math.PI / 2, normal: 0.3 }),
    whiteLacquer: std({ color: 0xf2eee8, roughness: 0.35 }),
    greyLacquer: std({ color: 0x968d84, roughness: 0.4 }),
    bronzeGlass: std({ color: 0xb08f78, metalness: 0.6, roughness: 0.05, envMapIntensity: 2.4 }),
    masterBronzeReflective: std({ color: 0x705345, metalness: 0.92, roughness: 0.045, envMapIntensity: 2.6 }),
    masterChampagneReflective: std({ color: 0xc9bdb0, metalness: 0.92, roughness: 0.045, envMapIntensity: 2.6 }),
    masterBronzeFrame: std({ color: 0x30241e, metalness: 0.75, roughness: 0.24 }),
    bronze: std({ color: 0x6b5440, metalness: 0.8, roughness: 0.35 }),
    marbleTop: std({ map: marbleTexture(), roughness: 0.2 }),
    darkTop: std({ color: 0x2a2724, roughness: 0.3 }),
    // Fabrics (woven relief from a fabric scan, colour set per piece)
    boucle: scanned("fabric_pattern_07", 0.2, { colour: false, tint: 0xe6dccd, roughness: 1 }),
    greige: scanned("fabric_pattern_07", 0.2, { colour: false, tint: 0xbfb2a3, roughness: 1 }),
    oatmeal: scanned("fabric_pattern_07", 0.2, { colour: false, tint: 0xd9cbb6, roughness: 1 }),
    linenSage: scanned("fabric_pattern_07", 0.2, { colour: false, tint: 0xa9b39c, roughness: 1 }),
    linenBlush: scanned("fabric_pattern_07", 0.2, { colour: false, tint: 0xd9a596, roughness: 1 }),
    linenSlate: scanned("fabric_pattern_07", 0.2, { colour: false, tint: 0x9fb0bd, roughness: 1 }),
    cushionMustard: scanned("fabric_pattern_07", 0.2, { colour: false, tint: 0xd8bb7a, roughness: 1 }),
    sheet: std({ color: 0xf5f1ea, roughness: 0.95 }),
    rug: scanned("fabric_pattern_07", 0.15, { colour: false, tint: 0xe9e0d2, roughness: 1, normal: 2 }),
    curtain: std({ color: 0xd9c4a8, roughness: 1, side: THREE.DoubleSide }),
    sheer: std({ color: 0xfaf6ef, roughness: 1, transparent: true, opacity: 0.55, side: THREE.DoubleSide, depthWrite: false }),
    // Metals, glass, appliances
    brass: std({ color: 0xc9a46a, metalness: 1, roughness: 0.35 }),
    chrome: std({ color: 0xdddddd, metalness: 1, roughness: 0.15 }),
    brushedNickel: std({ color: 0xc8c2b8, metalness: 1, roughness: 0.32 }),
    blackSteel: std({ color: 0x1d1c1b, metalness: 0.6, roughness: 0.35 }),
    blackGlass: std({ color: 0x0c0c0d, metalness: 0.2, roughness: 0.08 }),
    chairBlack: std({ color: 0x161514, metalness: 0.05, roughness: 0.42 }),
    chairBlackFabric: std({ color: 0x1e1e20, metalness: 0, roughness: 0.95 }),
    smokedGlass: std({ color: 0x3b2b22, metalness: 0.3, roughness: 0.08, transparent: true, opacity: 0.85 }),
    displayGlass: std({ color: 0x8a6a52, metalness: 0.2, roughness: 0.05, transparent: true, opacity: 0.22 }),
    mirror: std({ color: 0xe9e5de, metalness: 0.65, roughness: 0.14, envMapIntensity: 1.6 }),
    clearGlass: new THREE.MeshPhysicalMaterial({ color: 0xe8f2f2, transparent: true, opacity: 0.18, roughness: 0.05 }),
    ceramic: std({ color: 0xf7f5f0, roughness: 0.15 }),
    applianceWhite: std({ color: 0xf4f4f2, roughness: 0.3 }),
    terracotta: std({ color: 0xc99a7c, roughness: 0.9 }),
    stoneTable: scanned("beige_wall_002", 0.8, { colour: false, tint: 0xd8c6ad, normal: 2 }),
    leaf: std({ color: 0x6f7d4e, roughness: 0.8, side: THREE.DoubleSide }),
    planter: std({ color: 0xd9cfc2, roughness: 0.95 }),
    screen: std({ color: 0x111214, roughness: 0.2 }),
    // Light sources (bloom picks these up)
    ledStrip: glow(0xffb361, 3.2),
    downlight: glow(0xfff1d6, 4),
    lampShade: std({ color: 0xe2c9a8, emissive: 0xffa95c, emissiveIntensity: 0.9, roughness: 0.9 }),
    limewashTaupe: scanned("beige_wall_001", 3, { colour: false, tint: 0xd9c6b4, normal: 1.4 }),
    grille: std({ color: 0x3a3836, roughness: 0.6 }),
    art: [
      artTexture(11, ["#e6a58f", "#97a9b8", "#f1c7b3", "#c7826e"]),
      artTexture(29, ["#d89b8a", "#b9c4ad", "#efd2c0", "#8fa3b4"]),
      artTexture(47, ["#c98d7a", "#a9b59a", "#e9c9b2", "#d8b7a2"]),
    ].map(t => std({ map: t, roughness: 0.9 })),
  };
  // The renders' joinery is pale honey oak; the scan reads darker, so lift it past white.
  M.oakVeneer.color.setRGB(1.3, 1.1, 0.86);
  M.oakSlats.color.setRGB(1.2, 1.02, 0.82);
  for (const m of Object.values(M).flat()) m.clippingPlanes = clip;
  return M;
}
