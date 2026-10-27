// Move and Resize vs a page that's a revision behind, Karim's version (27 Oct 2026: an Edit AI test loop on the live
// site bumped the rev every 30 s and every Accept said "This page is behind"). With a live rev when the page loads:
// 1) a newer revision that leaves the furnish file alone (finishes) must not block Accept;
// 2) someone else's furniture change since the page loaded must (the piece's line numbers may be stale).
// Against a SANDBOX copy served by edit_ai.py (no Blob token, EDIT_AI_GIT_SYNC=0):
//   node tests/move_stale_e2e.mjs http://127.0.0.1:<port> <sandbox dir>
import { createRequire } from "module";
import { execFileSync } from "child_process";
import fs from "fs";
const require = createRequire(process.env.MOVE_E2E_PUPPETEER || "/tmp/mre/node/package.json");
const puppeteer = require("puppeteer-core");
const [B, SB] = process.argv.slice(2), BUMP = new URL("move_stale_bump.py", import.meta.url).pathname;
const CHROME = process.env.MOVE_E2E_CHROME || ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome"].find(fs.existsSync);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage(); await page.setViewport({ width: 900, height: 600 });
const M = (fn, ...a) => page.evaluate((fn, a) => window.__move[fn](...a), fn, a);
async function open() { await page.goto(`${B}/?v=kareems-changes&debug&view=top`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction(() => window.__move, { timeout: 90000 }); await page.evaluate(() => window.__move.ready()); await sleep(800); }
async function accept() {
  const nav = page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 60000 }).then(() => "saved");
  const bad = page.waitForSelector("#move-toast.bad", { timeout: 60000 }).then(async () => "refused: " + await page.$eval("#move-toast span", e => e.textContent));
  await page.evaluate(() => document.querySelector("#move-accept .accept").click());
  return Promise.race([nav, bad]);
}
console.log("before load (a live rev exists, as on the site):", execFileSync("python3", [BUMP, SB], { encoding: "utf8" }).trim());
await open();
console.log("page rev:", await page.evaluate(() => fetch('api/edit-ai/patches?version=karims-version').then(r => r.json()).then(j => j.rev)));
await page.evaluate(() => document.getElementById("move").click()); await sleep(200);
let d = await M("debugSelect", 20.474, 9.5, "two-tap countertop water dispenser");
await M("debugDraft", [d.box[0] - 0.04, d.box[1] - 0.29, d.box[2] - 0.04, d.box[3] - 0.29]);
console.log("request furnish sha:", (await M("state")).request.furnish);
console.log("unrelated revision:", execFileSync("python3", [BUMP, SB], { encoding: "utf8" }).trim());
const r1 = await accept();
console.log((r1 === "saved" ? "PASS" : "FAIL") + " 1) Accept after an unrelated change ->", r1);
await sleep(3000);
await page.evaluate(() => document.getElementById("move").click()); await sleep(200);
d = await M("debugSelect", 20.474, 9.5, "two-tap countertop water dispenser");
await M("debugDraft", [d.box[0] + 0.02, d.box[1], d.box[2] + 0.02, d.box[3]]);
// someone else moves the coffee table (a furnish change) meanwhile
const r = await M("debugSelect", 4.645, 2.529);
const res = await fetch(`${B}/api/edit-ai/transform`, { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ version: "karims-version", op: "move", dx: 0.05, dy: 0, piece: r }) }).then(r => r.json());
console.log("other tab moved the coffee table:", res.summary || res.error);
await M("debugSelect", 20.474, 9.5, "two-tap countertop water dispenser");
await M("debugDraft", [d.box[0] + 0.02, d.box[1], d.box[2] + 0.02, d.box[3]]);
const r2 = await accept();
console.log((/^refused: This version.s furniture changed/.test(r2) ? "PASS" : "FAIL") + " 2) Accept after a furniture change ->", r2);
await browser.close();
