// Move and Resize browser e2e: real pointer drags in 3D (Top and Walk) and on the 2D drawing, Accept / Cancel, Undo,
// and Figma-style drill-in. Run against a SANDBOX copy served by edit_ai.py with no Blob token and EDIT_AI_GIT_SYNC=0
// (never the live site): every accepted change is undone before the next case.
//
//   node tests/move_e2e.mjs http://127.0.0.1:8852 [out.json] [case-filter]
// Needs puppeteer-core (MOVE_E2E_PUPPETEER: its package.json) and Chrome (MOVE_E2E_CHROME, default /usr/bin/google-chrome).
import { createRequire } from "module";
import fs from "fs";
const require = createRequire(process.env.MOVE_E2E_PUPPETEER || "/workspace/apartment-architect/compare-3d/shot/package.json");
const puppeteer = require("puppeteer-core");

const [BASE, OUT = "/tmp/move_e2e.json", FILTER = ""] = process.argv.slice(2);
const V = "kareems-changes";  // the only version this suite ever writes to
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const check = (c, name, ok, info = "") => {
  results.push({ case: c, name, ok: !!ok, info });
  console.log(ok ? "PASS" : "FAIL", c, "·", name, info ? "· " + (typeof info === "string" ? info : JSON.stringify(info)) : "");
};
const near = (a, b, tol = 0.012) => a && b && a.every((v, i) => Math.abs(v - b[i]) <= tol);

const browser = await puppeteer.launch({ executablePath: process.env.MOVE_E2E_CHROME || "/usr/bin/google-chrome", headless: "new",
  args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] });
let page;
async function fresh() {  // a new tab: after a crash or a detached frame, the next case still runs
  await page?.close().catch(() => {});
  page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  page.on("pageerror", e => console.log("  pageerror:", e.message));
}
await fresh();

async function open(q) {
  await page.goto(`${BASE}/?v=${V}&debug&${q}`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await settle();
}
async function settle() {
  await page.waitForFunction(() => window.__move, { timeout: 60000 });
  await page.evaluate(() => window.__move.ready());
  await sleep(700);
}
const M = (fn, ...a) => page.evaluate((fn, a) => window.__move[fn](...a), fn, a);
const state = () => page.evaluate(() => window.__move.state());
const rev = () => page.evaluate(async v => (await (await fetch(`api/edit-ai/patches?version=${v}`)).json()).rev, V);
const furnish = () => page.evaluate(async v => {
  const name = `furnish-${v}.js`;  // the version's own file (26 Oct 2026)
  const p = await (await fetch(`api/edit-ai/patches?version=${v}`)).json(), f = p.files[name];
  return f ? (f.content ?? await (await fetch(f.url)).text()) : await (await fetch(name)).text();
}, V);
async function on() {
  if (!(await page.evaluate(() => window.__move.active))) {
    await page.evaluate(() => (document.body.classList.contains("drawing") ? document.querySelector("#drawing [data-tool=move]") : document.getElementById("move")).click());
    await sleep(200);
  }
}
async function drag(a, b, steps = 10) {
  await page.mouse.move(...a);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) { await page.mouse.move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps); await sleep(25); }
  await page.mouse.up();
  await sleep(250);
}
const mid = b => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
// Pull the selection's body by (dx, dy) plan metres, or one of its handles.
async function dragPlan(box, dx, dy, side) {
  const at = side ? handleAt(box, side) : mid(box);
  const a = await M("screenOf", ...at), b = await M("screenOf", at[0] + dx, at[1] + dy);
  await drag(a, b);
}
function handleAt(b, s) {
  const [mx, my] = mid(b);
  return { N: [mx, b[3]], S: [mx, b[1]], E: [b[2], my], W: [b[0], my], NE: [b[2], b[3]] }[s];
}
// Accept: the page reloads with the change, or (the plan has no room) an error toast shows and the draft stays.
async function acceptAndReload() {
  const nav = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 120000 }).then(() => "saved");
  const bad = page.waitForSelector("#move-toast.bad", { timeout: 120000 }).then(() => "refused");
  await page.click("#move-accept .accept");
  const how = await Promise.race([nav, bad]);
  if (how === "refused") return { refused: await page.$eval("#move-toast span", e => e.textContent) };
  await settle();
  return {};
}
async function undo(c) {
  await page.waitForSelector("#move-toast button", { timeout: 15000 }).catch(() => {});
  const text = await page.$eval("#move-toast span", e => e.textContent).catch(() => "");
  const btn = await page.$$("#move-toast button");
  if (!btn.length) { check(c, "Undo button after Accept", false, text); return false; }
  const nav = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 120000 });
  await btn[0].click();
  await nav;
  await settle();
  return true;
}

// One move or resize, start to finish. sel: [x, y, part] of the item() call; view: query; op: {dx, dy} | {side, d}.
async function run(c, { view, sel, op, plan2D, expectRefuse }) {
  if (FILTER && !new RegExp(FILTER).test(c)) return;
  try {
    await open(view);
    await on();
    const d0 = await M("debugSelect", ...sel);
    if (!d0) return check(c, "piece found", false, sel);
    const box0 = d0.box, rev0 = await rev(), f0 = await furnish();
    if (plan2D) {  // pick it the way a person does on the drawing: tap its middle
      await page.keyboard.press("Escape"); await page.keyboard.press("Escape"); await on();
      const p = await M("screenOf", ...mid(box0), 0);
      await page.mouse.click(...p); await sleep(250);
      const s = await state();
      check(c, "2D tap picks it", s.box && near(s.box, box0, 0.003), s.selected);
      if (!s.box || !near(s.box, box0, 0.003)) await M("debugSelect", ...sel);
    }
    if (op.side) await dragPlan(box0, op.side.includes("E") ? op.d : op.side.includes("W") ? -op.d : 0, op.side.includes("N") ? op.d : op.side.includes("S") ? -op.d : 0, op.side);
    else await dragPlan(box0, op.dx, op.dy);
    let s = await state();
    const want = op.side ? (() => { const b = [...box0]; if (op.side.includes("E")) b[2] += op.d; if (op.side.includes("W")) b[0] -= op.d; if (op.side.includes("N")) b[3] += op.d; if (op.side.includes("S")) b[1] -= op.d; return b; })()
      : [box0[0] + op.dx, box0[1] + op.dy, box0[2] + op.dx, box0[3] + op.dy];
    check(c, "drag makes a draft (Accept bar)", s.draft && s.bar, s.text);
    check(c, "draft box is what was dragged", near(s.draft, want, 0.011), { draft: s.draft, want });
    check(c, "live label shows cm", /\d+ × \d+ cm/.test(s.text || ""), s.text);
    await sleep(300);
    check(c, "no save before Accept (rev unchanged)", (await rev()) === rev0);
    const acc = await acceptAndReload();
    if (acc.refused) {  // a refusal is a pass only when nothing was saved and the draft is still there to adjust
      s = await state();
      check(c, "refused cleanly (draft kept, nothing saved)", s.draft && (await rev()) === rev0 && expectRefuse, acc.refused);
      return;
    }
    s = await state();
    const after = await M("boxNear", ...mid(want)), f1 = await furnish();
    const res = await page.$eval("#move-toast span", e => e.textContent).catch(() => "");
    check(c, "Accept saved one revision", (await rev()) !== rev0 && f1 !== f0, res);
    // the plan may clamp it to the free span: then the note says so and the 3D matches what the plan did
    const clamped = /only had room/.test(res) && after && after.some((v, i) => Math.abs(v - box0[i]) > 0.004);
    check(c, clamped ? "3D box after reload (plan clamped it, note shown)" : "3D box after reload", near(after, want, 0.015) || clamped, { after, want, note: res });
    if (await undo(c)) {
      const back = await M("boxOf", ...sel);
      check(c, "Undo puts it back", near(back, box0, 0.004) && (await furnish()) === f0, { back, box0 });
    }
  } catch (e) {
    check(c, "ran", false, e.message);
    await fresh();
  }
}

// --- Accept is required: Cancel, Esc and a tap away leave the server alone ---------------------------------------------
async function acceptRequired() {
  const c = "accept-required";
  if (FILTER && !new RegExp(FILTER).test(c)) return;
  await open("view=top");
  check(c, "3D button says Move and Resize", (await page.$eval("#move", e => e.textContent.trim())) === "Move and Resize");
  check(c, "2D button says Move and Resize", (await page.$eval("#drawing [data-tool=move]", e => e.textContent.trim())) === "Move and Resize");
  await on();
  const sel = [19.008, 4.206], d0 = await M("debugSelect", ...sel), rev0 = await rev();
  await dragPlan(d0.box, 0.2, 0);
  check(c, "piece previews where it was dragged", near(await M("boxOf", ...sel), [d0.box[0] + 0.2, d0.box[1], d0.box[2] + 0.2, d0.box[3]], 0.011));
  await page.click("#move-accept .cancel"); await sleep(250);
  let s = await state();
  check(c, "Cancel: draft gone, piece back", !s.draft && !s.bar && near(await M("boxOf", ...sel), d0.box, 0.002));
  await dragPlan(d0.box, 0, 0.15);
  await page.keyboard.press("Escape"); await sleep(250);
  s = await state();
  check(c, "Esc: draft gone, piece back, still selected", !s.draft && s.selected && near(await M("boxOf", ...sel), d0.box, 0.002));
  await dragPlan(d0.box, -0.1, 0);
  await dragPlan([d0.box[0] - 0.1, d0.box[1], d0.box[2] - 0.1, d0.box[3]], -0.1, 0);
  s = await state();
  check(c, "two drags add up in one draft", near(s.draft, [d0.box[0] - 0.2, d0.box[1], d0.box[2] - 0.2, d0.box[3]], 0.011), s.draft);
  const far = await M("screenOf", 18.0, 7.5); await page.mouse.click(...far); await sleep(300);  // tap something else
  s = await state();
  check(c, "tap away discards the draft", !s.draft && near(await M("boxOf", ...sel), d0.box, 0.002), s.selected);
  await sleep(500);
  check(c, "server rev unchanged after all that", (await rev()) === rev0);
}

// --- Drill-in: tap = whole piece, double-tap = the part under the pointer, chips climb back out --------------------
async function drill(c, { cam, sel, part, at, h, resize }) {
  if (FILTER && !new RegExp(FILTER).test(c)) return;
  try {
    await open(`cam=${cam}`);
    await on();
    const whole = await M("debugSelect", ...sel), dp = await M("debugSelect", ...sel, part);
    if (!whole || !dp) return check(c, "pieces found", false);
    await page.keyboard.press("Escape"); await page.keyboard.press("Escape"); await sleep(150);
    const p = await M("screenOf", at[0], at[1], h);
    await page.mouse.click(...p); await sleep(250);
    let s = await state();
    check(c, "tap selects the whole piece", s.path.length === 1 && near(s.box, whole.box, 0.003), s.path);
    await page.mouse.click(...p); await sleep(120); await page.mouse.click(...p); await sleep(250);  // double tap
    s = await state();
    check(c, `double-tap drills into ${part}`, s.selected === part && s.path.length === 2, s.path);
    check(c, "trail chips show Whole › part", s.chips.some(t => t.startsWith("Whole")) && s.chips.some(t => t.includes(part)), s.chips);
    await page.keyboard.press("Escape"); await sleep(150);
    s = await state();
    check(c, "Esc climbs back to the whole piece", s.path.length === 1, s.path);
    await page.mouse.click(...p); await sleep(120); await page.mouse.click(...p); await sleep(250);
    if (!resize) return;
    const rev0 = await rev(), f0 = await furnish(), host0 = await M("boxOf", ...sel);
    s = await state();
    await dragPlan(s.box, resize.side === "N" ? 0 : resize.side === "E" ? resize.d : -resize.d, resize.side === "N" ? resize.d : 0, resize.side);
    s = await state();
    check(c, "part resize is a draft", s.draft && (await rev()) === rev0, s.text);
    const acc = await acceptAndReload();
    if (acc.refused) return check(c, "part resize saved", false, acc.refused);
    const f1 = await furnish(), note = await page.$eval("#move-toast span", e => e.textContent).catch(() => "");
    const pb = await M("boxNear", ...mid(dp.box), part);
    const grew = resize.side === "N" ? pb[3] - dp.box[3] : resize.side === "E" ? pb[2] - dp.box[2] : dp.box[0] - pb[0];
    check(c, `${part} grew by ${resize.d * 100} cm`, Math.abs(grew - resize.d) < 0.012, { grew, note });
    check(c, "only that part changed (piece anchor same)", (await page.evaluate((x, y) => window.__move.debugSelect(x, y).anchor, ...sel)).every((v, i) => Math.abs(v - sel[i]) < 0.002));
    check(c, "furnish.js changed", f1 !== f0, note);
    if (resize.src) check(c, `edit is in \`${resize.src}\`, Kareem's branch only`, new RegExp(resize.src).test(f1.split("\n").find((l, i) => l !== f0.split("\n")[i]) || ""));
    if (await undo(c)) check(c, "Undo restores furnish.js", (await furnish()) === f0);
  } catch (e) {
    check(c, "ran", false, e.message);
    await fresh();
  }
}

await acceptRequired();
// Move / resize across rooms in 3D Top view.
const T = "view=top";
const cases = [
  ["reception coffee table · move", { view: T, sel: [19.008, 4.206], op: { dx: 0.1, dy: 0 } }],
  ["reception coffee table · resize E", { view: T, sel: [19.008, 4.206], op: { side: "E", d: 0.1 } }],
  ["reception armchair · move", { view: T, sel: [19.1, 5.95], op: { dx: -0.1, dy: 0 } }],
  ["reception sofa (east) · move N into the coffee-table outline (plan refuses)", { view: T, sel: [21.027, 4.165], op: { dx: 0, dy: 0.1 }, expectRefuse: true }],
  ["reception sofa (east) · move S", { view: T, sel: [21.027, 4.165], op: { dx: 0, dy: -0.1 } }],
  ["reception side table · move", { view: T, sel: [20.7945, 2.45], op: { dx: -0.1, dy: 0 } }],
  ["dining table · move", { view: T, sel: [18.4, 7.6], op: { dx: 0.1, dy: 0 } }],
  ["dining chair (loop) · move", { view: T, sel: [18.4, 6.55], op: { dx: 0.1, dy: 0 } }],
  ["dining table · resize N", { view: T, sel: [18.4, 7.6], op: { side: "N", d: 0.1 } }],
  ["living coffee table · move", { view: T, sel: [4.645, 2.529], op: { dx: 0, dy: 0.1 } }],
  ["living rug · resize W", { view: T, sel: [4.65, 2.45], op: { side: "W", d: 0.1 } }],
  ["bedroom nightstand · move", { view: T, sel: [2.299, 6.231], op: { dx: 0, dy: -0.1 } }],
  ["wardrobe (cupboard by bath door) · resize N", { view: T, sel: [0.556, 5.561], op: { side: "N", d: 0.1 } }],
  ["laundry washer/dryer · move", { view: T, sel: null, op: { dx: 0, dy: -0.1 }, find: "washer" }],
  ["master vanity · move (boxed in on the plan: refused, nothing saved)", { view: T, sel: [0.556, 6.7276], op: { dx: 0, dy: -0.1 }, expectRefuse: true }],
  ["living curtain (loop) · move", { view: T, sel: [2.94, 2.0], op: { dx: 0, dy: 0.1 } }],
  ["terrace potted plant (loop) · move", { view: T, sel: [21.8, 4.75], op: { dx: 0.1, dy: 0 } }],
  // 2D drawing: pick by tapping the outline, drag, Accept, check the 3D after the reload.
  ["2D coffee table · move", { view: "view=top&show=drawing", sel: [19.008, 4.206], op: { dx: 0.1, dy: 0 }, plan2D: true }],
  ["2D armchair · resize E", { view: "view=top&show=drawing", sel: [19.1, 5.95], op: { side: "E", d: 0.1 }, plan2D: true }],
  ["2D dining table · move", { view: "view=top&show=drawing", sel: [18.4, 7.6], op: { dx: 0, dy: -0.1 }, plan2D: true }],
];
const all = JSON.parse(fs.readFileSync(process.env.MOVE_E2E_PIECES || "/tmp/mre/pieces.json", "utf8"));
for (const [c, o] of cases) {
  if (!o.sel) {
    const p = all.find(p => p.kind === "item" && p.label.toLowerCase().includes(o.find));
    if (!p) { check(c, "piece found", false, o.find); continue; }
    o.sel = [p.x, p.y];
  }
  await run(c, o);
}
// Drill-in: the TV wall's south tall niche, the buffet niche, the coffee bar's espresso machine (Walk view, real taps).
await drill("drill TV-wall niche + resize", { cam: "19.9,2.31,1.3,17.3,2.31,1.3,60", sel: [17.25, 3.67], part: "south tall niche", at: [17.38, 2.31], h: 1.5,
  resize: { side: "N", d: 0.04, src: "const tall" } });
await drill("drill buffet niche + resize", { cam: "17.2,7.4,1.4,14.8,7.4,1.3,60", sel: [14.79, 8.0], part: "tall niche", at: [15.0, 7.18], h: 1.6,
  resize: { side: "N", d: 0.04, src: "const niche" } });
await drill("drill coffee bar espresso + resize", { cam: "20.6,7.6,1.5,20.6,9.4,1.0,60", sel: [20.474, 9.5], part: "espresso machine", at: [20.82, 9.26], h: 1.15,
  resize: { side: "W", d: 0.05 } });

await browser.close();
fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
const pass = results.filter(r => r.ok).length;
console.log(`\n${pass}/${results.length} checks passed`);
