// Move and Resize up and down (Z), with real input, Karim's version: in Walk the height handles (the dot raises or
// lowers, the square makes it taller or shorter) and PageUp / PageDown (Shift: 10 cm, Alt: height); in Top and on the
// drawing the keys. Each Accept reloads; the 3D is checked after it, the plan is left alone (it has no heights), and
// Undo (the toast's button) puts it back. Against a SANDBOX served by edit_ai.py (no Blob token, EDIT_AI_GIT_SYNC=0).
//
//   node tests/move_z_e2e.mjs http://127.0.0.1:8852 [out.json]
import { createRequire } from "module";
import fs from "fs";
const require = createRequire(process.env.MOVE_E2E_PUPPETEER || "/tmp/mre/node/package.json");
const puppeteer = require("puppeteer-core");

const [BASE, OUT = "/tmp/move_z_e2e.json"] = process.argv.slice(2);
const V = "karims-version", PAGE_V = "kareems-changes";
const CHROME = process.env.MOVE_E2E_CHROME || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome"].find(fs.existsSync);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const near = (a, b, tol) => a && b && a.every((v, i) => Math.abs(v - b[i]) <= tol);
const results = [];
const check = (c, name, ok, info = "") => {
  results.push({ case: c, name, ok: !!ok, info });
  console.log(ok ? "PASS" : "FAIL", c, "·", name, info ? "· " + (typeof info === "string" ? info : JSON.stringify(info)) : "");
};
const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", protocolTimeout: 120000,
  args: ["--no-sandbox", "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage();
await page.setViewport({ width: 1100, height: 760 });
page.on("pageerror", e => console.log("  pageerror:", e.message));
const M = (fn, ...a) => page.evaluate((fn, a) => window.__move[fn](...a), fn, a);
const state = () => page.evaluate(() => window.__move.state());
const rev = () => page.evaluate(async v => (await (await fetch(`api/edit-ai/patches?version=${v}`)).json()), V);
async function open(q) {
  await page.goto(`${BASE}/?v=${PAGE_V}&debug&${q}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await settle();
}
async function settle() {
  await page.waitForFunction(() => window.__move, { timeout: 90000 });
  await page.evaluate(() => window.__move.ready());
  await sleep(1500);
}
async function on() {
  if (!(await page.evaluate(() => window.__move.active))) {
    await page.evaluate(() => (document.body.classList.contains("drawing") ? document.querySelector("#drawing [data-tool=move]") : document.getElementById("move")).click());
    await sleep(200);
  }
}
async function drag(a, b, steps = 12) {
  await page.mouse.move(...a);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) { await page.mouse.move(a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps); await sleep(30); }
  await page.mouse.up();
  await sleep(250);
}
async function key(k, mods = []) {
  for (const m of mods) await page.keyboard.down(m);
  await page.keyboard.press(k);
  for (const m of mods.reverse()) await page.keyboard.up(m);
  await sleep(120);
}
// Accept, wait for the reload, return the piece's {box, low, high} near (x, y) and the files before / after.
async function acceptAndCheck(c, at, want) {
  const p0 = await rev();
  const nav = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 150000 }).then(() => "saved");
  const bad = page.waitForSelector("#move-toast.bad", { timeout: 150000 }).then(() => "refused");
  await page.click("#move-accept .accept");
  if ((await Promise.race([nav, bad])) === "refused") return check(c, "Accept saved", false, await page.$eval("#move-toast span", e => e.textContent));
  await settle();
  const p1 = await rev(), got = await M("pieceNear", ...at);
  const note = await page.$eval("#move-toast span", e => e.textContent).catch(() => "");
  check(c, "Accept saved one revision", p1.rev !== p0.rev, note);
  check(c, "3D after the reload: box and height as dragged", near(got.box, want.box, 0.012) && near([got.low, got.high], want.z, 0.012), { got, want });
  const dxf = f => f.files["dwg/karims-version.dxf"]?.url;
  const planMoved = (want.box.some((v, i) => Math.abs(v - want.box0[i]) > 0.002));
  check(c, planMoved ? "plan changed with the plan move" : "plan left alone (no heights on it)", planMoved || dxf(p1) === dxf(p0), note);
  // Undo: the toast's button
  await page.waitForSelector("#move-toast button", { timeout: 20000 }).catch(() => {});
  const btn = (await page.$$("#move-toast button"))[0];
  if (!btn) return check(c, "Undo button", false);
  const nav2 = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 150000 });
  await btn.click();
  await nav2;
  await settle();
  const back = await M("pieceNear", ...at), p2 = await rev();
  check(c, "Undo: files and 3D back", JSON.stringify(p2.files) === JSON.stringify(p0.files) && near(back.box, want.box0, 0.004) && near([back.low, back.high], want.z0, 0.004), { back });
}

// --- 1. Walk: the terrace plant from the photo (21.8, 4.75), by its handles ---------------------------------------
let c = "walk plant: lift handle + height square";
await open("cam=24.4,4.75,1.6,21.8,4.75,1.25,60");
await on();
let s0 = await M("screenOf", 21.8, 4.75, 0.3);
await page.mouse.click(...s0); await sleep(300);
let s = await state();
check(c, "click picks the potted plant", s.selected === "potted plant", s.selected);
if (s.selected !== "potted plant") await M("debugSelect", 21.8, 4.75);
s = await state();
const box0 = s.box, z0 = [s.low, s.high];
check(c, "height handles shown in Walk", !!s.zh, s.zh);
if (s.zh) {
  const { lift, u, px } = s.zh;
  await drag(lift, [lift[0] + u[0] * px * 0.06, lift[1] + u[1] * px * 0.06]);  // 6 cm up the screen's vertical (stays on screen)
  s = await state();
  check(c, "lift dot raises it ~6 cm, plan box unchanged", s.z && Math.abs(s.z[0] - z0[0] - 0.06) < 0.01 && Math.abs((s.z[1] - s.z[0]) - (z0[1] - z0[0])) < 0.002 && near(s.draft, box0, 0.002), s.z);
  check(c, "label says how far up", /cm up/.test(s.text), s.text);
  const zh = s.zh;
  await drag(zh.size, [zh.size[0] + zh.u[0] * zh.px * 0.1, zh.size[1] + zh.u[1] * zh.px * 0.1]);  // 10 cm taller
  s = await state();
  const z1 = s.z;
  check(c, "square makes it ~10 cm taller, bottom stays", z1 && Math.abs((z1[1] - z1[0]) - (z0[1] - z0[0]) - 0.1) < 0.01 && Math.abs(z1[0] - s.z[0]) < 0.002 && Math.abs(z1[0] - z0[0] - 0.06) < 0.01, z1);
  check(c, "label says how tall", /cm tall \(was/.test(s.text), s.text);
  await key("Escape");
  s = await state();
  check(c, "Esc drops the height draft", !s.draft && !s.z, s.z);
  // again, and Accept
  await drag(s.zh.lift, [s.zh.lift[0] - s.zh.u[0] * s.zh.px * 0.05, s.zh.lift[1] - s.zh.u[1] * s.zh.px * 0.05]);  // 5 cm down
  s = await state();
  check(c, "lift dot lowers it ~5 cm", s.z && Math.abs(s.z[0] - z0[0] + 0.05) < 0.01, s.z);
  if (!s.draft) await key("PageDown");
  s = await state();
  await acceptAndCheck(c, [21.8, 4.75], { box: s.draft, box0, z: s.z, z0 });
}

// --- 2. Walk: keys, and a plan move in the same draft ---------------------------------------------------------------
c = "walk plant: PageUp ×3 (Shift) + Alt+PageDown + drag east";
await open("cam=24.4,4.75,1.6,21.8,4.75,1.25,60");
await on();
await M("debugSelect", 21.8, 4.75);
s = await state();
await key("PageUp", ["Shift"]); await key("PageUp", ["Shift"]); await key("PageUp");
s = await state();
check(c, "PageUp ×2 with Shift + 1: 21 cm up", s.z && Math.abs(s.z[0] - z0[0] - 0.21) < 0.001, s.z);
await key("PageDown", ["Alt"]); await key("PageDown", ["Alt", "Shift"]);
s = await state();
check(c, "Alt+PageDown: 11 cm shorter, bottom stays", s.z && Math.abs((s.z[1] - s.z[0]) - (z0[1] - z0[0]) + 0.11) < 0.001 && Math.abs(s.z[0] - z0[0] - 0.21) < 0.001, s.z);
const mid = [(box0[0] + box0[2]) / 2, (box0[1] + box0[3]) / 2];
const a = await M("screenOf", mid[0], mid[1]), b = await M("screenOf", mid[0], mid[1] + 0.3);
await drag(a, b);
s = await state();
check(c, "plan drag keeps the height draft", s.z && Math.abs(s.z[0] - z0[0] - 0.21) < 0.001 && s.draft && Math.abs(s.draft[1] - box0[1]) > 0.1, { z: s.z, draft: s.draft });
await acceptAndCheck(c, [21.8, 4.75], { box: s.draft, box0, z: s.z, z0 });

// --- 3. Top view: keys only (no height handles looking down) --------------------------------------------------------
c = "top coffee table: PageUp";
await open("view=top");
await on();
const ct = await M("debugSelect", 4.645, 2.529);
s = await state();
check(c, "no height handles in Top", !s.zh);
await key("PageUp", ["Shift"]);
s = await state();
check(c, "PageUp+Shift: 10 cm up", s.z && Math.abs(s.z[0] - ct.low - 0.1) < 0.001, s.z);
await acceptAndCheck(c, [4.645, 2.529], { box: s.draft, box0: ct.box, z: s.z, z0: [ct.low, ct.high] });

// --- 4. The drawing: keys, the plan untouched ------------------------------------------------------------------------
c = "2D coffee table: Alt+PageUp (taller)";
await open("view=top&show=drawing");
await on();
const ct2 = await M("debugSelect", 4.645, 2.529);
await key("PageUp", ["Alt", "Shift"]);
s = await state();
check(c, "Alt+Shift+PageUp: 10 cm taller", s.z && Math.abs((s.z[1] - s.z[0]) - (ct2.high - ct2.low) - 0.1) < 0.001, s.z);
await acceptAndCheck(c, [4.645, 2.529], { box: s.draft, box0: ct2.box, z: s.z, z0: [ct2.low, ct2.high] });

await browser.close();
fs.writeFileSync(OUT, JSON.stringify(results, null, 1));
console.log(`\n${results.filter(r => r.ok).length}/${results.length} checks passed`);
