// Auto-names for new photo spots: the furniture piece the camera looks at, as one word ("bed", "dresser").
// furnish.js builds each piece as an unnamed group placed with its back-centre on a plan point, so the words
// live here, keyed by that point (plan metres), not in furnish.js. Rays fanned across the frame hit pieces;
// each hit counts for the word at its group's point (more near the middle), and the most-hit word wins.
// A piece moved more than NEAR in furnish.js loses its word until its point here is updated; with no word
// at all, photogen.py names the spot from the generated image instead.

const NEAR = 0.15;  // metres between a group's position and a point here that still count as the same piece

// [x, y, word, plan version (all if absent)]. Pieces built by helpers (art, rugs, plants, sconces) are left out.
export const WORDS = [
  // Living room
  [0, 0, "sofa"], [4.645, 2.529, "coffee table"], [6.15, 2.25, "TV"], [6.16, 2.25, "TV"],
  [2.94, 2.0, "window"], [2.94, 3.59, "window"],
  // Master suite, Main
  [4.13, 7.62, "bed", "main"], [4.13, 8.8, "bed", "main"], [4.13, 6.45, "bed", "main"],
  [1.72, 9.02, "window", "main"], [3.2, 9.02, "window", "main"], [6.37, 6.06, "shoes", "main"],
  [4.22, 7.3, "vanity", "main"], [6.24, 7.3, "toilet", "main"],
  [6.24, 8.62, "shower", "main"], [5.25, 9.02, "shower", "main"], [5.25, 8.06, "shower", "main"],
  // Master suite, Bigger Master Bedroom (v9)
  [3.185, 9.015, "bed", "bigger-bedroom"], [2.02, 9.015, "bed", "bigger-bedroom"], [4.35, 9.015, "bed", "bigger-bedroom"],
  [2.395, 9.02, "window", "bigger-bedroom"], [6.245, 6.363, "vanity", "bigger-bedroom"], [6.245, 7.3, "toilet", "bigger-bedroom"],
  [6.245, 8.62, "shower", "bigger-bedroom"], [5.25, 9.02, "shower", "bigger-bedroom"],
  // Main and v9 share the west and south walls
  [0.56, 6.75, "wardrobe", "main"], [2.36, 4.55, "dresser", "main"], [3.36, 4.55, "shoes", "main"],
  [0.56, 6.75, "wardrobe", "bigger-bedroom"], [2.36, 4.55, "dresser", "bigger-bedroom"], [3.36, 4.55, "shoes", "bigger-bedroom"],
  // Master suite, Shifted Bedroom (v12)
  [2.159, 7.511, "bed", "shifted-bedroom"], [2.162, 7.511, "bed", "shifted-bedroom"], [2.159, 6.231, "bed", "shifted-bedroom"],
  [2.159, 8.79, "bed", "shifted-bedroom"], [2.95, 9.02, "window", "shifted-bedroom"], [5.37, 9.02, "window", "shifted-bedroom"],
  [6.367, 7.336, "wardrobe", "shifted-bedroom"], [1.564, 4.55, "wardrobe", "shifted-bedroom"], [0.556, 5.561, "cupboard", "shifted-bedroom"],
  [3.517, 4.55, "dresser", "shifted-bedroom"], [0.556, 6.68, "vanity", "shifted-bedroom"], [0.556, 7.58, "toilet", "shifted-bedroom"],
  [0.836, 8.5033, "shower", "shifted-bedroom"], [2.041, 8.745, "shower", "shifted-bedroom"], [0.836, 8.7792, "shower", "shifted-bedroom"],
  // Master suite, Nagham's Changes: added below as a copy of Shifted Bedroom's
  // Guest bathroom
  [12.324, 8.05, "bath"], [12.767, 9.18, "bath"], [14.66, 7.75, "vanity"], [13.642, 9.18, "toilet"],
  // Kitchen: the runs (west with the hob, north with the sink), the dishwasher column and the fridge
  [6.48, 7.38, "hob"], [8.04, 9.09, "sink"], [7.54, 5.67, "counter"], [10.21, 8.764, "counter"],
  [10.21, 8.1265, "dishwasher"], [10.21, 7.3235, "fridge"],
  // Nagham's Changes: the south run's tall units
  [7.5276, 5.6604, "oven", "naghams-changes"], [8.2721, 5.6604, "pantry", "naghams-changes"],
  // Laundry
  [10.32, 7.9215, "cupboards"], [11.236, 9.18, "counter"], [11.835, 9.18, "washer"],
  // Entrance: the console by the door, the mirror wall facing it, the door
  [0, 3.6001, "console"], [8.512, 5.55, "mirror"], [9.365, 5.55, "mirror"], [9.28, 5.55, "mirror"], [8.48, 3.72, "door"],
  // Reception
  [17.25, 3.67, "TV"], [18.86, 2.103, "sofa"], [21.027, 4.165, "sofa"], [19.1, 5.95, "armchair"],
  [19.008, 4.206, "coffee table"], [20.341, 2.687, "side table"],
  // Dining: table, chairs and lanterns all name the table
  [18.4, 7.6, "table"], [17.6, 7.6, "table"], [19.2, 7.6, "table"], [16.95, 7.6, "table"], [19.85, 7.6, "table"],
  ...[17.6, 18.4, 19.2].flatMap(x => [[x, 6.55, "table"], [x, 8.65, "table"]]),
  [14.79, 8.0, "buffet"], [20.474, 9.5, "coffee bar"],
  // Terrace
  [25.14, 3.6, "bench"], [23.42, 1.78, "bench"], [23.4, 3.4, "bench"],
  [24.76, 7.1, "lounge"], [22.1, 6.3, "lounge"], [22.1, 7.9, "lounge"], [23.35, 7.1, "lounge"], [23.115, 9.27, "BBQ"],
];
// Nagham's Changes starts as a copy of Shifted Bedroom: the same master-suite words.
WORDS.push(...WORDS.filter(w => w[3] === "shifted-bedroom").map(([x, y, word]) => [x, y, word, "naghams-changes"]));

// The word for a furniture group (a direct child of furnish's root) in this plan version, or null.
export function wordFor(group, version) {
  const x = group.position.x, y = -group.position.z;
  let best = null, dist = NEAR;
  for (const [wx, wy, word, v] of WORDS) {
    if (v && v !== version) continue;
    const d = Math.hypot(wx - x, wy - y);
    if (d <= dist) { best = word; dist = d; }
  }
  return best;
}

// The piece the camera frames: rays on a grid across the 3:2 frame (lens hfov x vfov, degrees) up to the first
// wall or named piece; a hit counts far more the nearer the middle it is (a wardrobe filling one side
// loses to the dresser you aim at). -> word or null.
export function framedWord({ THREE, camera, root, solids, version, hfov, vfov }) {
  const meshes = [];
  root.traverse(o => o.isMesh && o.visible && meshes.push(o));
  const walls = new Set(solids), targets = [...solids, ...meshes];
  const ray = new THREE.Raycaster(), score = new Map();
  const th = Math.tan(THREE.MathUtils.degToRad(hfov) / 2), tv = Math.tan(THREE.MathUtils.degToRad(vfov) / 2);
  camera.updateMatrixWorld();
  for (let i = -4; i <= 4; i++) for (let j = -3; j <= 3; j++) {
    const u = i / 4.5, v = j / 3.5;  // inside the frame's edges
    const dir = new THREE.Vector3(u * th, v * tv, -1).normalize().transformDirection(camera.matrixWorld);
    ray.set(camera.position, dir);
    ray.far = 15;
    for (const hit of ray.intersectObjects(targets, false)) {
      if (walls.has(hit.object)) break;
      let g = hit.object;
      while (g.parent && g.parent !== root) g = g.parent;
      const word = g.parent === root && wordFor(g, version);
      if (!word) continue;  // a rug, a plant, art: look past it
      score.set(word, (score.get(word) || 0) + Math.exp(-(u * u + v * v) / 0.05));  // what you aim at, not what fills the sides
      break;
    }
  }
  return [...score].sort((a, b) => b[1] - a[1])[0]?.[0] || null;
}

// "<Room caption> <word>", or "... <word> 2" and on when the room has one already (taken: its captions).
export function uniqueName(caption, word, taken) {
  const have = new Set(taken.map(t => t.toLowerCase()));
  const base = `${caption} ${word}`;
  if (!have.has(base.toLowerCase())) return base;
  for (let n = 2; ; n++) if (!have.has(`${base} ${n}`.toLowerCase())) return `${base} ${n}`;
}
