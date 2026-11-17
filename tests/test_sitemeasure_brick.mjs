// sitemeasure.js on New As-built's model and drawing: openings run brick to brick, faces add up, earlier ids map.
// Run: node tests/test_sitemeasure_brick.mjs (no browser, no server).
import { readFileSync } from "fs";
import assert from "assert/strict";
const root = new URL("..", import.meta.url).pathname;
const window = {};
new Function("window", readFileSync(`${root}model-new-asbuilt.js`, "utf8"))(window);
const M = window.MODEL, data = JSON.parse(readFileSync(`${root}drawing-new-asbuilt.json`, "utf8"));
const { segmentWalls, aliasOf } = await import(`${root}sitemeasure.js`);
const rings = [], segs = segmentWalls(M, data, rings), byId = Object.fromEntries(segs.map(s => [s.id, s]));
const L = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
let n = 0;
const test = (name, f) => { f(); n++; console.log("ok", name); };

test("ids unique; one width per opening", () => {
  assert.equal(new Set(segs.map(s => s.id)).size, segs.length);
  assert.equal(segs.filter(s => s.opening != null).length, M.openings.length);
});
test("Toilet 1 window: 66.8 brick to brick, with its heights", () => {
  const w = byId["window:TOILET-1:147,902-214,902"];
  assert.ok(w && Math.abs(w.drawn - 66.8) < 0.05 && w.brick);
  assert.deepEqual(w.parts.map(id => byId[id].kind), ["sill", "height", "above"]);
});
test("doors run past the frame to the brick (Toilet 2 95.4, entrance 95.7)", () => {
  assert.ok(Math.abs(segs.find(s => s.kind === "door" && s.room === "TOILET 2").drawn - 95.4) < 0.05);
  assert.ok(Math.abs(segs.find(s => s.kind === "door" && s.room === "ENTRANCE").drawn - 95.7) < 0.05);
});
test("no piece left inside an opening's brick span", () => {
  for (const o of segs.filter(s => s.opening != null)) for (const s of segs) {
    if (s.vertical || s === o || s.room !== o.room) continue;
    const u = [(o.b[0] - o.a[0]) / L(o.a, o.b), (o.b[1] - o.a[1]) / L(o.a, o.b)];
    const t = p => (p[0] - o.a[0]) * u[0] + (p[1] - o.a[1]) * u[1], off = p => Math.abs((p[0] - o.a[0]) * u[1] - (p[1] - o.a[1]) * u[0]);
    const inside = p => t(p) > 0.01 && t(p) < L(o.a, o.b) - 0.01 && off(p) < 0.02;
    assert.ok(!(inside(s.a) && inside(s.b)), `${s.id} inside ${o.id}`);
  }
});
test("round each ring the pieces join (≤5 mm), so a face's pieces add up to the face", () => {
  for (const { room, pieces } of rings) pieces.forEach((p, i) => {
    assert.ok(L(p.b, pieces[(i + 1) % pieces.length].a) <= 0.0051, `${room} gap after piece ${i}`);
  });
});
test("earlier ids: live ones map, frame nibs don't", () => {
  assert.equal(aliasOf("window:TOILET-1:147,902-213,902", segs), "window:TOILET-1:147,902-214,902");
  assert.equal(aliasOf("window:TOILET-1:147,902-213,902#sill", segs), "window:TOILET-1:147,902-214,902#sill");
  assert.ok(byId["wall:TOILET-1:56,747-56,881"] && byId["wall:MASTER-BEDROOM:236,599-236,902"]);
  assert.equal(aliasOf("door:TOILET-2:1310,696-1397,696", segs), segs.find(s => s.kind === "door" && s.room === "TOILET 2").id);
  assert.equal(aliasOf("nib:TOILET-2:1304,696-1310,696", segs), null);
});
console.log(`${n} tests OK`);
