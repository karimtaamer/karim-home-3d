// Move and Resize e2e on Karim's version (karims-version) ONLY, against a LOCAL sandbox copy served by edit_ai.py with no
// Blob token and EDIT_AI_GIT_SYNC=0 (never the live site). Real pointer drags on the 2D drawing and in 3D Top; Accept;
// checks the 3D box after the reload AND the 2D drawing's linework; Undo after every saved case.
//   node tests/move_e2e_karim.mjs http://127.0.0.1:8853 [out.json] [case-filter]   (tests/run_move_e2e_karim.py runs all)
// Needs puppeteer-core (MOVE_E2E_PUPPETEER: its package.json) and Chrome (MOVE_E2E_CHROME, default the macOS app).
import { createRequire } from "module";
import fs from "fs";
const require = createRequire(process.env.MOVE_E2E_PUPPETEER || "/tmp/mre2/node/package.json");
const puppeteer = require("puppeteer-core");

const [BASE, OUT = "/tmp/move_e2e_karim.json", FILTER = ""] = process.argv.slice(2);
const V = "karims-version", URLV = "kareems-changes";  // ?v=kareems-changes is Karim's version; its data files are karims-version
const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [];
const check = (c, name, ok, info = "") => {
  results.push({ case: c, name, ok: !!ok, info });
  console.log(ok ? "PASS" : "FAIL", c, "·", name, info ? "· " + (typeof info === "string" ? info : JSON.stringify(info)) : "");
};
const near = (a, b, tol = 0.012) => a && b && a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= tol);
const mid = b => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
const grow = (b, d) => [b[0] - d, b[1] - d, b[2] + d, b[3] + d];

const launch = () => puppeteer.launch({ executablePath: process.env.MOVE_E2E_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: "new",
  args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
let browser = await launch(), page;
async function fresh() {  // a new tab; a new browser when Chrome itself went away
  await page?.close().catch(() => {});
  if (!browser.connected) browser = await launch();
  page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  page.on("pageerror", e => console.log("  pageerror:", e.message));
  page.on("error", e => console.log("  page crashed:", e.message));
  page.on("requestfailed", r => !/\/renders\//.test(r.url()) && console.log("  reqfail:", r.url().replace(BASE, ""), r.failure()?.errorText));
}
await fresh();

async function settle() {  // the page may reload itself once more (a live change landing): wait out a detached frame
  for (let i = 0; ; i++) {
    try {
      await page.waitForFunction(() => window.__move, { timeout: 120000 });
      await page.evaluate(() => window.__move.ready());
      break;
    } catch (e) {
      if (i >= 2 || !/detached|context was destroyed|Target closed|Frame/i.test(e.message)) throw e;
      await sleep(1500);
    }
  }
  await sleep(700);
}
async function open(q) {
  await page.goto(`${BASE}/?v=${URLV}&debug&${q}`, { waitUntil: "domcontentloaded", timeout: 120000 });
  await settle();
}
// Reads from the page; a page that reloads itself once more after a save (a live change landing) is waited out once.
const FLAKY = /detached|context was destroyed|Target closed|__move/i;
async function again(f) {
  try { return await f(); } catch (e) {
    if (!FLAKY.test(e.message)) throw e;
    await sleep(1500);
    await settle();
    return f();
  }
}
const M = (fn, ...a) => again(() => page.evaluate((fn, a) => window.__move[fn](...a), fn, a));
const state = () => again(() => page.evaluate(() => window.__move.state()));
const rev = () => page.evaluate(async v => (await (await fetch(`api/edit-ai/patches?version=${v}`)).json()).rev, V);
const liveFile = name => page.evaluate(async (v, name) => {
  const p = await (await fetch(`api/edit-ai/patches?version=${v}`)).json(), f = p.files[name];
  return f ? (f.content ?? await (await fetch(f.url)).text()) : await (await fetch(name, { cache: "no-store" })).text();
}, V, name);
const furnish = () => liveFile(`furnish-${V}.js`);
const drawing = async () => JSON.parse(await liveFile(`drawing-${V}.json`));
async function on() {
  if (!(await page.evaluate(() => window.__move.active))) {
    await page.evaluate(() => (document.body.classList.contains("drawing") ? document.querySelector("#drawing [data-tool=move]") : document.getElementById("move")).click());
    await sleep(200);
  }
}
async function drag(a, b, steps = 10, keys = []) {
  await page.mouse.move(...a);
  await page.mouse.down();
  for (const k of keys) await page.keyboard.down(k);
  for (let i = 1; i <= steps; i++) { await page.mouse.move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps); await sleep(25); }
  await page.mouse.up();
  for (const k of keys) await page.keyboard.up(k);
  await sleep(250);
}
function handleAt(b, s) {
  const [mx, my] = mid(b);
  return { N: [mx, b[3]], S: [mx, b[1]], E: [b[2], my], W: [b[0], my], NE: [b[2], b[3]], NW: [b[0], b[3]], SE: [b[2], b[1]], SW: [b[0], b[1]] }[s];
}
async function dragPlan(box, dx, dy, side, keys) {
  const at = side ? handleAt(box, side) : mid(box);
  const a = await M("screenOf", ...at), b = await M("screenOf", at[0] + dx, at[1] + dy);
  await drag(a, b, 10, keys);
}
// Bring a plan box to the middle of the drawing (middle-button pan) and zoom so it's ~300 px across, as a person would.
async function focus(box) {
  const c = await M("screenOf", ...mid(box), 0);
  await page.mouse.move(...c); await page.mouse.down({ button: "middle" });
  for (let i = 1; i <= 8; i++) { await page.mouse.move(c[0] + (640 - c[0]) * i / 8, c[1] + (400 - c[1]) * i / 8); await sleep(20); }
  await page.mouse.up({ button: "middle" }); await sleep(150);
  const a = await M("screenOf", box[0], box[1], 0), b = await M("screenOf", box[2], box[3], 0);
  const size = Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]), 1), f = Math.max(1, Math.min(12, 300 / size));
  await page.mouse.move(...(await M("screenOf", ...mid(box), 0)));
  await page.mouse.wheel({ deltaY: -Math.log(f) / 0.0015 }); await sleep(200);
}
async function acceptAndReload() {
  const nav = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 120000 }).then(() => "saved");
  const bad = page.waitForSelector("#move-toast.bad", { timeout: 120000 }).then(() => "refused");
  await page.evaluate(() => document.querySelector("#move-accept .accept").click()).catch(() => {});  // it navigates: no element click
  const how = await Promise.race([nav, bad]);
  if (how === "refused") return { refused: await page.$eval("#move-toast span", e => e.textContent) };
  await settle();
  return {};
}
async function undo(c) {
  await page.waitForSelector("#move-toast button", { timeout: 15000 }).catch(() => {});
  const btn = await page.$$("#move-toast button");
  if (!btn.length) { check(c, "Undo button after Accept", false); return false; }
  const nav = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 120000 });
  await page.evaluate(() => document.querySelector("#move-toast button").click()).catch(() => {});
  await nav;
  await settle();
  return true;
}
// The drawing's linework that changed: bbox of the lines that went and of the lines that came.
function lineDiff(d0, d1, region) {
  // a rebuild re-rounds some unrelated lines by a millimetre: a line counts as the same when one in the other drawing
  // has the same colour and points within 2 mm
  const dot = l => l.every((v, i) => Math.abs(v - l[i % 2]) <= 0.002);  // a zero-length stub draws nothing; rebuilds drop some
  const FURNI = "#00ff00";  // the 2furni layer's colour in the drawing: walls and doors are other colours
  const list = d => Object.entries(d.strokes).filter(([c]) => c === FURNI).flatMap(([c, ls]) => ls.filter(l => !dot(l)).map(l => ({ c, l })));
  const a = list(d0), b = list(d1);
  const key = ({ c, l }) => c + ":" + l.length + ":" + Math.round(l[0] * 20) + ":" + Math.round(l[1] * 20);
  const index = xs => { const m = new Map(); for (const x of xs) for (const dx of [-1, 0, 1]) for (const dy of [-1, 0, 1]) {
    const k = x.c + ":" + x.l.length + ":" + (Math.round(x.l[0] * 20) + dx) + ":" + (Math.round(x.l[1] * 20) + dy);
    (m.get(k) || m.set(k, []).get(k)).push(x); } return m; };
  const ia = index(a), ib = index(b);
  const has = (m, x) => (m.get(key(x)) || []).some(y => y.l.every((v, i) => Math.abs(v - x.l[i]) <= 0.002));
  // only lines round the piece (where it was and where it went): elsewhere a rebuild re-orders wall outlines' points
  const near_ = x => !region || (() => { const X = x.l.filter((_, i) => i % 2 === 0), Y = x.l.filter((_, i) => i % 2 === 1);
    return Math.max(...X) >= region[0] && Math.min(...X) <= region[2] && Math.max(...Y) >= region[1] && Math.min(...Y) <= region[3]; })();
  const gone = a.filter(x => !has(ib, x) && near_(x)), came = b.filter(x => !has(ia, x) && near_(x));
  const bb = xs => {
    if (!xs.length) return null;
    const X = xs.flatMap(x => x.l.filter((_, i) => i % 2 === 0)), Y = xs.flatMap(x => x.l.filter((_, i) => i % 2 === 1));
    return [Math.min(...X), Math.min(...Y), Math.max(...X), Math.max(...Y)].map(v => +v.toFixed(4));
  };
  return { gone: bb(gone), came: bb(came), n: [gone.length, came.length] };
}

// The sandbox back to the deployed files: undo whatever a crashed case left saved.
async function clean() {
  for (let i = 0; i < 5; i++) {
    const p = await (await fetch(`${BASE}/api/edit-ai/patches?version=${V}`)).json();
    if (!Object.keys(p.files).length) return;
    console.log("  cleaning up a leftover change:", p.summary);
    await fetch(`${BASE}/api/edit-ai/undo`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ version: V }) });
  }
}

// One change start to finish. sel: [x, y, part?]; op: {dx, dy} | {side, d} | {del: true}; plan2D: pick and drag on the
// drawing; planOutline: the piece is drawn on the plan (its linework must change the same way).
async function run(c, { view, sel, op, plan2D, planOutline, expectRefuse, keys, want: wantFn }) {
  if (FILTER && !new RegExp(FILTER).test(c)) return;
  try {
    await clean();
    await open(view);
    await on();
    const d0 = await M("debugSelect", ...sel);
    if (!d0) return check(c, "piece found", false, sel);
    const box0 = d0.box, rev0 = await rev(), f0 = await furnish(), dr0 = await drawing();
    if (plan2D) {  // pick it the way a person does on the drawing: tap its middle
      await page.keyboard.press("Escape"); await page.keyboard.press("Escape"); await on();
      await focus(box0);
      const p = await M("screenOf", ...mid(box0), 0);
      await page.mouse.click(...p); await sleep(250);
      const s = await state();
      check(c, "2D tap picks it", s.box && near(s.box, box0, 0.003), s.selected);
      if (!s.box || !near(s.box, box0, 0.003)) await M("debugSelect", ...sel);
    }
    let want;
    if (op.del) {
      await page.keyboard.press("Delete"); await sleep(250);
      const s = await state();
      check(c, "Delete makes a draft (Accept bar)", s.del && s.bar, s.text);
      check(c, "piece hidden in the preview", s.hidden && s.del, s);
    } else if (op.nudge) {  // arrow keys: [key, shift] pairs
      for (const [k, sh] of op.nudge) {
        if (sh) await page.keyboard.down("Shift");
        await page.keyboard.press(k);
        if (sh) await page.keyboard.up("Shift");
        await sleep(80);
      }
      const s = await state();
      want = [box0[0] + op.dx, box0[1] + op.dy, box0[2] + op.dx, box0[3] + op.dy];
      check(c, "arrows make a draft", s.draft && s.bar, s.text);
      check(c, "draft box is what the arrows said", near(s.draft, want, 0.002), { draft: s.draft, want });
    } else {
      for (const k of op.press || []) { await page.keyboard.press(k); await sleep(80); }
      if (op.press) check(c, `axis locked to ${op.lock}`, (await state()).axis === op.lock, (await state()).text);
      if (op.side) await dragPlan(box0, op.side.includes("E") ? op.d : op.side.includes("W") ? -op.d : 0, op.side.includes("N") ? op.d : op.side.includes("S") ? -op.d : 0, op.side, keys);
      else await dragPlan(box0, op.drag ? op.drag[0] : op.dx, op.drag ? op.drag[1] : op.dy, null, keys);
      const s = await state();
      want = wantFn ? wantFn(box0) : op.side ? (() => { const b = [...box0]; if (op.side.includes("E")) b[2] += op.d; if (op.side.includes("W")) b[0] -= op.d; if (op.side.includes("N")) b[3] += op.d; if (op.side.includes("S")) b[1] -= op.d; return b; })()
        : [box0[0] + op.dx, box0[1] + op.dy, box0[2] + op.dx, box0[3] + op.dy];
      check(c, "drag makes a draft (Accept bar)", s.draft && s.bar, s.text);
      check(c, "draft box is what was dragged", near(s.draft, want, 0.011), { draft: s.draft, want });
      check(c, "piece previews there", near(await M("boxOf", ...sel), want, 0.011));
    }
    await sleep(300);
    check(c, "no save before Accept", (await rev()) === rev0);
    const acc = await acceptAndReload();
    if (acc.refused) {
      const s = await state();
      check(c, expectRefuse ? "refused cleanly (draft kept, nothing saved)" : "Accept saved", expectRefuse && s.draft && (await rev()) === rev0, acc.refused);
      return;
    }
    const f1 = await furnish(), dr1 = await drawing();
    const note = await page.$eval("#move-toast span", e => e.textContent).catch(() => "");
    check(c, "Accept saved a revision", (await rev()) !== rev0 && f1 !== f0, note);
    if (op.del) {
      check(c, "3D: piece gone after reload", !(await M("boxNear", ...mid(box0))) || !near(await M("boxNear", ...mid(box0)), box0, 0.02), await M("boxNear", ...mid(box0)));
      if (planOutline) {
        const ld = lineDiff(dr0, dr1, grow(box0, 0.05));
        check(c, "2D: its outline is gone", ld.gone && !ld.came && Math.abs(mid(ld.gone)[0] - mid(box0)[0]) < 0.3 && Math.abs(mid(ld.gone)[1] - mid(box0)[1]) < 0.3, ld);
      }
    } else {
      const after = await M("boxNear", ...mid(want));
      const clamped = /only had room/.test(note);
      check(c, clamped ? "3D box after reload (plan clamped it)" : "3D box after reload", near(after, want, 0.015) || clamped, { after, want, note });
      const ld = lineDiff(dr0, dr1, grow([Math.min(box0[0], want[0]), Math.min(box0[1], want[1]), Math.max(box0[2], want[2]), Math.max(box0[3], want[3])], 0.05));
      if (planOutline) {
        const dx = mid(after)[0] - mid(box0)[0], dy = mid(after)[1] - mid(box0)[1];
        // a resize: the outline grows by the same cm, or (a drawn symbol bigger than the piece) in the same proportion
        const W = b => [b[2] - b[0], b[3] - b[1]];
        const ok = ld.gone && ld.came && (op.side
          ? near(W(ld.came).map((v, i) => v - W(ld.gone)[i]), W(after).map((v, i) => v - W(box0)[i]), 0.015)
            || near(W(ld.came).map((v, i) => v / W(ld.gone)[i]), W(after).map((v, i) => v / W(box0)[i]), 0.01)
          : near([ld.came[0] - ld.gone[0], ld.came[1] - ld.gone[1]], [dx, dy], 0.015));
        check(c, "2D outline changed the same as the 3D", ok, { ...ld, d3: [+dx.toFixed(3), +dy.toFixed(3)] });
      } else check(c, "2D linework untouched (3D-only piece)", !ld.gone && !ld.came, ld);
    }
    if (await undo(c)) {
      const back = await M("boxOf", ...sel);
      check(c, "Undo puts it back (3D, furnish.js, drawing)", near(back, box0, 0.004) && (await furnish()) === f0 && !lineDiff(dr0, await drawing(), grow(box0, 0.3)).gone, { back, box0 });
    }
  } catch (e) {
    check(c, "ran", false, e.message);
    await fresh();
  }
}

// A group: tap one piece, Shift-click the others, then drag (or Delete); Accept saves one change, one Undo takes it back.
async function runGroup(c, { sels, op }) {
  if (FILTER && !new RegExp(FILTER).test(c)) return;
  try {
    await clean();
    await open("view=top&show=drawing");
    await on();
    const boxes = [];
    for (const sel of sels) boxes.push((await M("debugSelect", ...sel)).box);
    await page.keyboard.press("Escape"); await page.keyboard.press("Escape"); await on();
    const rev0 = await rev(), f0 = await furnish(), dr0 = await drawing();
    await focus(boxes.reduce((a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]));
    await page.mouse.click(...(await M("screenOf", ...mid(boxes[0]), 0))); await sleep(250);
    for (const b of boxes.slice(1)) {
      await page.keyboard.down("Shift");
      await page.mouse.click(...(await M("screenOf", ...mid(b), 0)));
      await page.keyboard.up("Shift");
      await sleep(250);
    }
    let s = await state();
    check(c, `Shift-click builds a group of ${sels.length}`, s.group.length === sels.length - 1, { selected: s.selected, group: s.group });
    if (op.del) {
      await page.keyboard.press("Delete"); await sleep(250);
      s = await state();
      check(c, "Delete: one draft for the group, all hidden", s.del && s.bar && s.hidden, s.text);
    } else {
      await dragPlan(boxes[0], op.dx, op.dy);
      s = await state();
      check(c, "drag moves the whole group (preview)", (await Promise.all(sels.map(sel => M("boxOf", ...sel)))).every((b, i) => near(b, [boxes[i][0] + op.dx, boxes[i][1] + op.dy, boxes[i][2] + op.dx, boxes[i][3] + op.dy], 0.011)), s.text);
    }
    check(c, "the request is one batch", s.request && s.request.op === "batch" && s.request.items.length === sels.length, s.request && s.request.op);
    const acc = await acceptAndReload();
    if (acc.refused) return check(c, "Accept saved", false, acc.refused);
    const note = await page.$eval("#move-toast span", e => e.textContent).catch(() => "");
    const f1 = await furnish(), dr1 = await drawing();
    check(c, "Accept saved one revision", (await rev()) !== rev0 && f1 !== f0, note);
    for (let i = 0; i < sels.length; i++) {
      const b = boxes[i], want = op.del ? null : [b[0] + op.dx, b[1] + op.dy, b[2] + op.dx, b[3] + op.dy];
      const after = await M("boxNear", ...mid(want || b));
      check(c, `3D piece ${i + 1} ${op.del ? "gone" : "moved"}`, op.del ? !after || !near(after, b, 0.02) : near(after, want, 0.015), { after, want });
      const ld = lineDiff(dr0, dr1, grow(want ? [Math.min(b[0], want[0]), Math.min(b[1], want[1]), Math.max(b[2], want[2]), Math.max(b[3], want[3])] : b, 0.05));
      check(c, `2D outline ${i + 1} ${op.del ? "gone" : "moved the same"}`, op.del ? ld.gone && !ld.came
        : ld.gone && ld.came && near([ld.came[0] - ld.gone[0], ld.came[1] - ld.gone[1]], [op.dx, op.dy], 0.015), ld);
    }
    if (await undo(c)) {
      const back = await Promise.all(sels.map(sel => M("boxOf", ...sel)));
      check(c, "one Undo puts every piece back", back.every((b, i) => near(b, boxes[i], 0.004)) && (await furnish()) === f0, back);
    }
  } catch (e) {
    check(c, "ran", false, e.message);
    await fresh();
  }
}

// Walls, doors and windows on the drawing: tap one (no piece there), drag it / pull an end / Delete, Accept; the plan
// changes and the rebuilt 3D (window.MODEL) follows; Undo puts it back.
const openings = () => page.evaluate(() => (window.MODEL.openings || []).map(o => {
  const xs = o.outer.map(q => q[0]), ys = o.outer.map(q => q[1]);
  return { kind: o.kind, box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)].map(v => Math.round(v * 1000) / 1000) };
}));
async function runPlan(c, { at, kind, op, want }) {
  if (FILTER && !new RegExp(FILTER).test(c)) return;
  try {
    await clean();
    await open("view=top&show=drawing");
    await on();
    const rev0 = await rev(), o0 = await openings(), dr0 = await drawing();
    await focus([at[0] - 0.6, at[1] - 0.6, at[0] + 0.6, at[1] + 0.6]);
    await page.mouse.click(...(await M("screenOf", ...at, 0))); await sleep(400);
    let s = await state();
    check(c, `tap picks the ${kind}`, s.plan && (kind === "wall" ? s.plan.type === "wall" : s.plan.kind === kind), s.plan);
    if (!s.plan) return;
    if (kind === "wall") { for (let i = 0; i < 40 && !(await state()).plan?.run; i++) await sleep(250); s = await state(); check(c, "the wall's run is shown", !!s.plan.run, s.plan.run); }
    const p0 = s.plan;
    if (op.del) { await page.keyboard.press("Delete"); await sleep(250); }
    else {
      const q = await M("planScreen"), a = op.end === undefined ? [(q[0][0] + q[2][0]) / 2, (q[0][1] + q[2][1]) / 2]
        : null;
      let from = a;
      if (op.end !== undefined) {  // an opening's end dot: the middle of its short side, as planEnds() puts it
        const b = p0.box, al = b[2] - b[0] >= b[3] - b[1] ? 0 : 1, my = (b[1] + b[3]) / 2, mx = (b[0] + b[2]) / 2;
        const pt = al === 0 ? [op.end ? b[2] : b[0], my] : [mx, op.end ? b[3] : b[1]];
        from = await M("screenOf", ...pt, 0);
      }
      const w0 = await page.evaluate(() => window.__move.state().plan.at);
      const to = await M("screenOf", ...[0, 0], 0), unit = await M("screenOf", 1, 1, 0);
      const px = [unit[0] - to[0], unit[1] - to[1]];  // screen px per plan metre (x, y)
      await drag(from, [from[0] + op.d[0] * px[0], from[1] + op.d[1] * px[1]]);
    }
    s = await state();
    check(c, "a draft with the Accept bar", s.plan?.draft && s.bar, s.plan?.text);
    if (op.draft) check(c, "the draft is what was dragged", op.draft(s.plan.draft), s.plan.draft);
    check(c, "nothing saved before Accept", (await rev()) === rev0);
    const acc = await acceptAndReload();
    if (acc.refused) return check(c, "Accept saved", false, acc.refused);
    const note = await page.$eval("#move-toast span", e => e.textContent).catch(() => "");
    check(c, "Accept saved a revision", (await rev()) !== rev0, note);
    const o1 = await openings(), dr1 = await drawing();
    check(c, "3D (rebuilt model) changed as asked", await want(o0, o1), { note, gone: o0.filter(x => !o1.some(y => near(x.box, y.box, 0.003))), came: o1.filter(x => !o0.some(y => near(x.box, y.box, 0.003))) });
    const changed = JSON.stringify(dr0.strokes) !== JSON.stringify(dr1.strokes);
    check(c, "2D drawing changed", changed);
    if (await undo(c)) check(c, "Undo puts the plan and 3D back", JSON.stringify(await openings()) === JSON.stringify(o0) && (await rev()) !== rev0);
  } catch (e) {
    check(c, "ran", false, e.message);
    await fresh();
  }
}

// Cancel / Esc / tap-away save nothing (2D).
async function acceptRequired() {
  const c = "2D accept-required";
  if (FILTER && !new RegExp(FILTER).test(c)) return;
  await open("view=top&show=drawing");
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
  check(c, "Esc: draft gone, piece back", !s.draft && near(await M("boxOf", ...sel), d0.box, 0.002));
  await sleep(300);
  check(c, "server rev unchanged", (await rev()) === rev0);
}

await acceptRequired();
const T = "view=top", D = "view=top&show=drawing";
const cases = [
  // 2D drawing: the user's complaint. X only, Y only, both, resize edges and a corner.
  ["2D coffee table · move X", { view: D, sel: [19.008, 4.206], op: { dx: 0.1, dy: 0 }, plan2D: true, planOutline: true }],
  ["2D coffee table · move Y", { view: D, sel: [19.008, 4.206], op: { dx: 0, dy: -0.1 }, plan2D: true, planOutline: true }],
  ["2D coffee table · move X+Y", { view: D, sel: [19.008, 4.206], op: { dx: 0.1, dy: 0.1 }, plan2D: true, planOutline: true }],
  ["2D armchair · resize E", { view: D, sel: [18.33, 4.59], op: { side: "E", d: 0.1 }, plan2D: true, planOutline: true }],
  ["2D living coffee table · resize N", { view: D, sel: [4.645, 2.529], op: { side: "N", d: 0.1 }, plan2D: true, planOutline: true }],
  ["2D side table · resize NE corner", { view: D, sel: [20.7945, 2.45], op: { side: "NE", d: 0.05 }, plan2D: true, planOutline: true }],
  ["2D nightstand · move S", { view: D, sel: [2.299, 6.231], op: { dx: 0, dy: -0.05 }, plan2D: true, planOutline: true }],
  ["2D wardrobe (south wall) · resize W", { view: D, sel: [1.564, 4.55], op: { side: "W", d: -0.1 }, plan2D: true, planOutline: true }],
  ["2D washer/dryer · move W", { view: D, sel: [11.835, 9.18], op: { dx: -0.05, dy: 0 }, plan2D: true, planOutline: true }],
  ["2D bed · move N", { view: D, sel: [2.299, 7.511], op: { dx: 0, dy: 0.05 }, plan2D: true, planOutline: true }],
  ["2D BBQ counter · resize W", { view: D, sel: [23.115, 9.27], op: { side: "W", d: -0.2 }, plan2D: true, planOutline: true }],
  ["2D terrace sofa · move W", { view: D, sel: [24.76, 7.1], op: { dx: -0.1, dy: 0 }, plan2D: true }],
  // AutoCAD-style: X / Y lock, Shift-drag straight, arrow nudges.
  ["2D coffee table · X lock (diagonal drag stays on X)", { view: D, sel: [19.008, 4.206], op: { press: ["x"], lock: "x", drag: [0.1, 0.08], dx: 0.1, dy: 0 }, plan2D: true, planOutline: true }],
  ["2D armchair · Y lock (diagonal drag stays on Y)", { view: D, sel: [18.33, 4.59], op: { press: ["y"], lock: "y", drag: [0.06, -0.1], dx: 0, dy: -0.1 }, plan2D: true, planOutline: true }],
  ["2D side table · Shift-drag goes straight", { view: D, sel: [20.7945, 2.45], op: { drag: [-0.1, 0.03], dx: -0.1, dy: 0 }, keys: ["Shift"], plan2D: true, planOutline: true }],
  ["2D nightstand · arrow nudges", { view: D, sel: [2.299, 6.231], op: { nudge: [["ArrowDown"], ["ArrowDown"], ["ArrowDown"], ["ArrowLeft", true]], dx: -0.1, dy: -0.03 }, plan2D: true, planOutline: true }],
  // Delete: from the 3D and the plan; Undo brings both back.
  ["2D side table · delete", { view: D, sel: [20.7945, 2.45], op: { del: true }, plan2D: true, planOutline: true }],
  ["2D coffee table · delete", { view: D, sel: [19.008, 4.206], op: { del: true }, plan2D: true, planOutline: true }],
  ["2D potted plant (3D-only) · delete", { view: D, sel: [17.8895, 2.45], op: { del: true }, plan2D: true }],
  ["3D dining chair (loop) · delete", { view: T, sel: [17.6, 6.55], op: { del: true } }],
  // 3D Top: the same edits reflect on the plan.
  ["3D coffee table · move", { view: T, sel: [19.008, 4.206], op: { dx: 0.1, dy: 0 }, planOutline: true }],
  ["3D dining chair (loop) · move", { view: T, sel: [17.6, 6.55], op: { dx: 0.1, dy: 0 } }],
  ["3D living coffee table · resize S", { view: T, sel: [4.645, 2.529], op: { side: "S", d: 0.1 }, planOutline: true }],
];
for (const [c, o] of cases) await run(c, o);
const sameExcept = (o0, o1, from, to) => o0.filter(x => !near(x.box, from, 0.003)).every(x => o1.some(y => near(x.box, y.box, 0.003)))
  && (to ? o1.some(y => near(y.box, to, 0.012)) : true) && !o1.some(y => near(y.box, from, 0.003));
await runPlan("2D window (living, west) · slide 20 cm N", { at: [2.814, 2.795], kind: "window", op: { d: [0, 0.2], draft: d => Math.abs(d.s - 0.2) < 0.011 },
  want: (o0, o1) => sameExcept(o0, o1, [2.689, 2.22, 2.939, 3.369], [2.689, 2.42, 2.939, 3.569]) });
await runPlan("2D window (kitchen) · pull east end 20 cm wider", { at: [8.103, 9.18], kind: "window", op: { end: 1, d: [0.2, 0], draft: d => Math.abs(d.w - 1.38) < 0.011 },
  want: (o0, o1) => sameExcept(o0, o1, [7.513, 9.09, 8.693, 9.269], [7.513, 9.09, 8.893, 9.269]) });
await runPlan("2D door (bedroom corridor) · slide 10 cm W", { at: [5.572, 4.49], kind: "door", op: { d: [-0.1, 0], draft: d => Math.abs(d.s + 0.1) < 0.011 },
  // a block door is redrawn as a loose one, whose jambs make the gap a little different: centre within 1.5 cm, width within 3
  want: (o0, o1) => sameExcept(o0, o1, [5.166, 4.437, 5.979, 4.55], null) && o1.some(y => y.kind === "door" && Math.abs((y.box[0] + y.box[2]) / 2 - 5.4725) < 0.015
    && Math.abs((y.box[2] - y.box[0]) - 0.813) < 0.03 && Math.abs(y.box[1] - 4.437) < 0.01) });
await runPlan("2D window (guest WC) · delete = walled up", { at: [13.766, 9.23], kind: "window", op: { del: true },
  want: (o0, o1) => sameExcept(o0, o1, [13.276, 9.186, 14.256, 9.269], null) && o1.length === o0.length - 1 });
await runPlan("2D wall (living / entrance) · move 5 cm E", { at: [6.22, 2.0], kind: "wall", op: { d: [0.05, 0], draft: d => Math.abs(Math.abs(d.s) - 0.05) < 0.011 },
  want: async () => { const r = await page.evaluate(async () => { const p = window.__move.debugPlanPick(6.27, 2.0); for (let i = 0; i < 40 && !window.__move.state().plan?.run; i++) await new Promise(r => setTimeout(r, 250)); return window.__move.state().plan?.run; });
    return r && Math.abs(r.a[0] - 6.2684) < 0.012; } });
await runPlan("2D wall (living / entrance) · delete", { at: [6.22, 2.0], kind: "wall", op: { del: true },
  want: async () => !(await page.evaluate(() => window.__move.debugPlanPick(6.22, 2.0)))?.type });
await runGroup("2D group · coffee table + side table move E together", { sels: [[19.008, 4.206], [20.7945, 2.45]], op: { dx: 0.1, dy: 0 } });
await runGroup("2D group · coffee table + side table delete together", { sels: [[19.008, 4.206], [20.7945, 2.45]], op: { del: true } });

await browser.close();
fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
const pass = results.filter(r => r.ok).length;
console.log(`\n${pass}/${results.length} checks passed`);
