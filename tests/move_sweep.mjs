// Move and Resize sweep, Karim's version only: every piece and part you can pick, moved along X, Y and Z and resized
// along X, Y and Z through move.js itself (a draft, Accept, the page reload), then Undo. After each Accept: the 3D box
// and height after the reload are what the draft asked for; the 2D plan (DXF) moved / stretched the piece's outline or
// lines by the same metres when it is drawn there, and stayed untouched when it isn't (or the change is a height);
// Undo restores every file and the piece. A refusal is retried the other way (a wardrobe against a wall grows the
// other side) and counts as a failure only when every way is refused.
// Run against a SANDBOX copy served by edit_ai.py with no Blob token and EDIT_AI_GIT_SYNC=0, never the live site.
//
//   node tests/move_sweep.mjs http://127.0.0.1:8852 out.json [start] [end] [ops: x,y,z,rx,ry,rz]
// Needs puppeteer-core (MOVE_E2E_PUPPETEER: its package.json), Chrome (MOVE_E2E_CHROME) and the DWG python
// (MOVE_DWG_PYTHON, default ~/.dwg-tools/bin/python) for the plan checks.
import { createRequire } from "module";
import { execFileSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
const require = createRequire(process.env.MOVE_E2E_PUPPETEER || "/tmp/mre/node/package.json");
const puppeteer = require("puppeteer-core");

const [BASE, OUT = "/tmp/move_sweep.json", START = "0", END = "100000", OPS = "x,y,z,rx,ry,rz"] = process.argv.slice(2);
const V = "karims-version", PAGE_V = "kareems-changes";  // the plan version, and the page's ?v= for it
const HERE = path.dirname(new URL(import.meta.url).pathname);
const PY = process.env.MOVE_DWG_PYTHON || path.join(os.homedir(), ".dwg-tools/bin/python");
const CHROME = process.env.MOVE_E2E_CHROME || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome"].find(fs.existsSync);
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "move-sweep-"));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const near = (a, b, tol) => a && b && a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= tol);
const results = fs.existsSync(OUT) ? JSON.parse(fs.readFileSync(OUT, "utf8")) : [];
const done = new Set(results.map(r => `${r.i}:${r.op}`));
let ipN = 0, owed = null;

const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", protocolTimeout: 120000,
  args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] });
let page;
async function fresh() {
  await page?.close().catch(() => {});
  page = await browser.newPage();
  await page.setViewport({ width: +(process.env.MOVE_SWEEP_W || 480), height: +(process.env.MOVE_SWEEP_H || 320) });  // small: software GL renders every frame
  page.on("pageerror", e => console.log("  pageerror:", e.message));
}
await fresh();
async function open() {
  // a new "client" each time: the server's per-IP move limit is for the public site, not this sweep
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": `10.9.${(ipN >> 8) & 255}.${ipN++ & 255}` });
  for (let k = 0; ; k++) {  // a busy machine can stall a load: one more try before it counts
    try {
      await page.goto(`${BASE}/?v=${PAGE_V}&debug&view=top`, { waitUntil: "domcontentloaded", timeout: 90000 });
      return await settle();
    } catch (e) {
      if (k) throw e;
      await fresh();
    }
  }
}
async function settle() {
  await page.waitForFunction(() => window.__move, { timeout: 90000 });
  await page.evaluate(() => window.__move.ready());
  await sleep(400);
  // no more frames: the checks read the scene, not pixels, and software GL drawing every frame starves the server
  if (!process.env.MOVE_SWEEP_RENDER) await page.evaluate(() => { window.requestAnimationFrame = () => 0; });
}
const M = (fn, ...a) => page.evaluate((fn, a) => window.__move[fn](...a), fn, a);
const patches = () => page.evaluate(async v => await (await fetch(`api/edit-ai/patches?version=${v}`)).json(), V);
const files = p => Object.fromEntries(Object.entries(p.files).map(([k, f]) => [k, f.url]));
async function on() {
  if (!(await page.evaluate(() => window.__move.active))) { await page.evaluate(() => document.getElementById("move").click()); await sleep(150); }
}
// The plan file a revision serves, saved locally for the plan checks.
const dxfCache = new Map();
async function dxfOf(p) {
  const url = p.files["dwg/karims-version.dxf"]?.url || "dwg/karims-version.dxf";
  if (!dxfCache.has(url)) {
    const f = path.join(TMP, `${dxfCache.size}.dxf`);
    fs.writeFileSync(f, Buffer.from(await (await fetch(`${BASE}/${url}`)).arrayBuffer()));
    dxfCache.set(url, f);
  }
  return [url, dxfCache.get(url)];
}
const plan = (dxf, box, handles = []) => JSON.parse(execFileSync(PY, [path.join(HERE, "move_sweep_plan.py"), dxf, box.join(","), ...handles],
  { encoding: "utf8", timeout: 90000 }));
// The sandbox's API from here (no page): GET, or POST with a body.
const rest = async (what, body) => (await fetch(`${BASE}/api/edit-ai/${what}`, body ? { method: "POST",
  headers: { "Content-Type": "application/json", "X-Forwarded-For": "10.8.0.1" }, body: JSON.stringify(body) } : {})).json();
const union = bs => bs.length && [Math.min(...bs.map(b => b[0])), Math.min(...bs.map(b => b[1])), Math.max(...bs.map(b => b[2])), Math.max(...bs.map(b => b[3]))];

// What each op asks for: [plan box, height span] from the piece now (d: metres, + = east / north / up / bigger).
function target(p, op, d) {
  const b = [...p.box], z = [p.low, p.high];
  if (op === "x") return [[b[0] + d, b[1], b[2] + d, b[3]], null];
  if (op === "y") return [[b[0], b[1] + d, b[2], b[3] + d], null];
  if (op === "z") return [b, [z[0] + d, z[1] + d]];
  if (op === "rx") return [d > 0 ? [b[0], b[1], b[2] + d, b[3]] : [b[0] + d, b[1], b[2], b[3]], null];  // + grows E, - grows W
  if (op === "ry") return [d > 0 ? [b[0], b[1], b[2], b[3] + d] : [b[0], b[1] + d, b[2], b[3]], null];
  if (op === "rz") return [b, [z[0], Math.max(z[0] + 0.02, z[1] + d)]];
}
const TRIES = { x: [0.1, -0.1], y: [0.1, -0.1], z: [0.05, -0.05], rx: [0.05, -0.05], ry: [0.05, -0.05], rz: [0.05, -0.05] };

// The 2D side of one saved change: what the plan should have done, and what it did.
async function planCheck(p, j, want, p0, p1) {
  const [u0, f0] = await dxfOf(p0), [u1, f1] = await dxfOf(p1);
  const box = p.box, nb = want, dx = (nb[0] + nb[2] - box[0] - box[2]) / 2, dy = (nb[1] + nb[3] - box[1] - box[3]) / 2;
  if (!j.plan) return { ok: u0 === u1 && !(j.changed || []).includes("drawing-karims-version.json"), why: "plan untouched" };
  if (!(j.changed || []).includes("drawing-karims-version.json")) return { ok: false, why: "drawing not rebuilt" };
  if (j.lines) {  // drawn as several lines: their extent moves / stretches with the 3D box
    const real = j.lines.filter(h => !h.includes("/"));
    const before = Object.values(plan(f0, box, real)).filter(Boolean), after = Object.values(plan(f1, nb, real)).filter(Boolean);
    const kx = (nb[2] - nb[0]) / (box[2] - box[0]), ky = (nb[3] - nb[1]) / (box[3] - box[1]), u = union(before);
    const exp = [nb[0] + (u[0] - box[0]) * kx, nb[1] + (u[1] - box[1]) * ky, nb[0] + (u[2] - box[0]) * kx, nb[1] + (u[3] - box[1]) * ky];
    return { ok: before.length === after.length && near(union(after), exp, 0.006), why: "lines", before: u, after: union(after), exp };
  }
  const ob = plan(f0, box, [j.outline])[j.outline];
  if (!ob) return { ok: false, why: `outline ${j.outline} not found before` };
  const kx = (nb[2] - nb[0]) / (box[2] - box[0]), ky = (nb[3] - nb[1]) / (box[3] - box[1]);
  const exp = j.op === "move" ? [ob[0] + dx, ob[1] + dy, ob[2] + dx, ob[3] + dy]
    : j.drawn === "block"  // a block stretches as the 3D box does; an outline's sides move as far as the box's
      ? [nb[0] + (ob[0] - box[0]) * kx, nb[1] + (ob[1] - box[1]) * ky, nb[0] + (ob[2] - box[0]) * kx, nb[1] + (ob[3] - box[1]) * ky]
      : [ob[0] + nb[0] - box[0], ob[1] + nb[1] - box[1], ob[2] + nb[2] - box[2], ob[3] + nb[3] - box[3]];
  const hit = plan(f1, nb).find(([, b]) => near(b, exp, 0.006));
  return { ok: !!hit, why: "outline", before: ob, exp, found: hit?.[0] };
}

async function one(i, op, label) {
  const tried = [];
  for (const d of TRIES[op]) {
    await open();
    await on();
    if (owed) {  // the last change's Undo, in 3D
      const back = await M("debugPick", owed.i);
      owed.t.undo3d = near(back?.box, owed.p.box, 0.004) && near([back?.low, back?.high], [owed.p.low, owed.p.high], 0.004);
      if (!owed.t.undo3d) console.log("  UNDO 3D FAILED for", owed.i, JSON.stringify(back), JSON.stringify(owed.p.box));
      owed = null;
    }
    const p = await M("debugPick", i);
    if (!p || p.label !== label) return { ok: false, tried, why: `piece ${i} is now ${p?.label}` };
    const [box, z] = target(p, op, d);
    await M("debugDraft", box, 0, z);
    const s = await M("state");
    const p0 = await patches();
    const res = page.waitForResponse(r => r.url().includes("/api/edit-ai/transform"), { timeout: 150000 });
    const nav = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 150000 }).then(() => "saved");
    const bad = page.waitForSelector("#move-toast.bad", { timeout: 150000 }).then(() => "refused");
    await page.click("#move-accept .accept");
    const j = await (await res).json().catch(() => ({}));
    const how = await Promise.race([nav, bad]);
    if (how === "refused") { tried.push({ d, refused: j.error }); continue; }
    await settle();
    const p1 = await patches(), after = await M("debugPick", i);
    Object.assign(j, await page.evaluate(() => window.__move.applied?.res || {}));  // the answer, read over the reload
    const zWant = z || [p.low, p.high];
    const t = { d, summary: j.summary, notes: j.notes, plan: j.plan, outline: j.outline, lines: j.lines?.length, label: s.text,
      draftOk: !!(s.draft && s.bar), box3d: near(after?.box, box, 0.012), z3d: near([after?.low, after?.high], zWant, 0.012),
      after: after && [after.box, after.low, after.high], want: [box, zWant],
      saved: p1.rev !== p0.rev && JSON.stringify(files(p1)) !== JSON.stringify(files(p0)) };
    t.plan2d = await planCheck(p, j, box, p0, p1);
    // Undo (the toast's button does the same call): every file as it was. The 3D going back is checked on the next
    // page load (owed), which the next change needs anyway.
    await page.evaluate(v => fetch("api/edit-ai/undo", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version: v }) }), V);
    const p2 = await patches();
    t.undo = JSON.stringify(files(p2)) === JSON.stringify(files(p0));
    owed = { i, p, t };
    tried.push(t);
    return { ok: t.draftOk && t.box3d && t.z3d && t.saved && t.plan2d.ok && t.undo, tried };
  }
  return { ok: false, tried, why: "refused every way" };
}

await open();
const base = await patches();
if (base.rev && !results.length) {  // a change left over (a killed run): every "before" would be wrong
  console.log(`the sandbox already has live edits (rev ${base.rev}); start from a clean copy`);
  process.exit(2);
}
const list = await M("debugList");
const ops = OPS.split(",");
console.log(`${list.length} pieces and parts; ${ops.length} ops each`);
for (let i = +START; i < Math.min(+END, list.length); i++) {
  for (const op of ops) {
    if (done.has(`${i}:${op}`)) continue;
    const t0 = Date.now(), rev0 = (await rest(`patches?version=${V}`)).rev;
    let r;
    try {
      r = await one(i, op, list[i].label);
    } catch (e) {
      r = { ok: false, why: "error: " + e.message.slice(0, 300) };
      owed = null;
      // a change saved before the error (a page timing out on a busy machine): undo back to where this one started
      for (let k = 0; k < 4 && (await rest(`patches?version=${V}`)).rev !== rev0; k++) await rest("undo", { version: V });
      await fresh();
    }
    results.push({ i, op, label: list[i].label, kind: list[i].kind, x: list[i].x, y: list[i].y, s: Math.round((Date.now() - t0) / 1000), ...r });
    const last = r.tried?.at(-1) || {};
    console.log(r.ok ? "PASS" : "FAIL", i, list[i].label.slice(0, 28), op, `${Math.round((Date.now() - t0) / 1000)}s`,
      r.ok ? (last.summary || "") : JSON.stringify({ why: r.why, ...last }).slice(0, 400));
    fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
  }
}
await browser.close();
const pass = results.filter(r => r.ok).length;
console.log(`\n${pass}/${results.length} passed`);
