// Renders: every designer render from spots.json, grouped by room, as a third view beside the 3D model
// and the drawing. Click one to see it large; arrow keys step through, Esc closes.
// With Generate Photo Spot's backend (actions.can()), the large view can also edit a render (a new version, the
// old kept) as Make an edit does on a new photo spot: red marks circled on it, a note for each, stacked, sent at once
// (markedit.js; up to four inspiration pictures can go with them, inspiration.js), and delete a generated one,
// after a confirmation. An edit's cost (EGP) shows on the new version's caption.
// There, each room's title also has Upload photo: the client's own pictures (several at once; a phone offers the
// camera), shrunk here to UPLOAD_PX JPEG so they fit Vercel's 4.5 MB request, filed under that room ("user": true,
// deletable like a generated one). Rooms with no picture yet show then too, so one can be added.

import { MAX_INSPO, egp, inspirationPicker } from "./inspiration.js";
import { markEditor } from "./markedit.js";

// Groups in the order of the Rooms panel; anything filed under a room without a viewpoint goes last.
export function byRoom(list, rooms) {
  const groups = rooms.map(r => ({ ...r, items: list.filter(s => s.room === r.room) }));
  const other = list.filter(s => !rooms.some(r => r.room === s.room));
  if (other.length) groups.push({ room: "", caption: "Other", items: other });
  return groups.filter(g => g.items.length);
}
// Under its room's title "Reception 2" reads "View 2"; a caption that only repeats the room reads "View".
export function shortLabel(caption, room) {
  const rest = caption.startsWith(room) ? caption.slice(room.length).replace(/^[\s·:–-]+/, "") : caption;
  return !rest ? "View" : /^\d+$/.test(rest) ? `View ${rest}` : rest;
}
const versioned = (label, s) => (s.version > 1 ? `${label} · v${s.version}` : label);

const UPLOAD_PX = 2400, UPLOAD_CHARS = 4_200_000;  // longest side; data URL length that stays under the 4.5 MB body
// A picture the browser can open (JPEG, PNG, WebP; HEIC where the browser reads it) as a JPEG data URL.
export async function shrink(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode().catch(() => { throw new Error(`This browser can't open ${file.name}; send it as JPEG or PNG.`); });
    const k = Math.min(1, UPLOAD_PX / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(img.naturalWidth * k));
    c.height = Math.max(1, Math.round(img.naturalHeight * k));
    const g = c.getContext("2d");
    g.fillStyle = "#fff";  // a transparent PNG gets white, not black
    g.fillRect(0, 0, c.width, c.height);
    g.drawImage(img, 0, 0, c.width, c.height);
    for (const q of [0.85, 0.72, 0.6]) {
      const out = c.toDataURL("image/jpeg", q);
      if (out.length <= UPLOAD_CHARS) return out;
    }
    throw new Error(`${file.name} is too large even shrunk.`);
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function createRenders(root, rooms, actions = { can: () => false }) {
  root.innerHTML = `
    <div class="rlist"></div>
    <div class="rbox" hidden>
      <img alt="">
      <div class="rcap"></div>
      <div class="racts">
        <button class="redit-open">Edit</button>
        <button class="rdel-open">Delete</button>
      </div>
      <form class="rsheet redit" hidden>
        <label>Make an edit</label>
        <div class="rmarks"></div>
        <div class="rinspo"></div>
        <p class="rnote">Add up to ${MAX_INSPO} inspiration pictures (+ Picture, paste or drop) and say in a note what to take from them. Saved as a new version; this one stays.</p>
        <div class="rerr"></div>
        <div class="rrow"><button type="submit" class="rgo">Make new version</button><button type="button" class="rattach">+ Picture</button><button type="button" class="rcancel">Cancel</button></div>
      </form>
      <div class="rsheet rdel" hidden>
        <p class="rq"></p>
        <div class="rerr"></div>
        <div class="rrow"><button class="rgo rdanger">Delete</button><button class="rcancel">Keep it</button></div>
      </div>
      <button class="rclose" aria-label="Close">✕</button>
      <button class="rprev" aria-label="Previous">‹</button>
      <button class="rnext" aria-label="Next">›</button>
    </div>`;
  const list = root.querySelector(".rlist"), box = root.querySelector(".rbox");
  const big = box.querySelector("img"), cap = box.querySelector(".rcap");
  const acts = box.querySelector(".racts"), editor = box.querySelector(".redit"), confirm = box.querySelector(".rdel");
  const send = editor.querySelector(".rgo");
  const marks = markEditor({ stage: box, img: big, panel: editor.querySelector(".rmarks"), go: "Make new version",
    onChange: () => { if (!busy) { send.disabled = !!marks.problem(); send.title = marks.problem(); } } });
  const inspo = inspirationPicker({ form: editor, button: editor.querySelector(".rattach"), area: editor, thumbs: editor.querySelector(".rinspo"),
    onError: m => (editor.querySelector(".rerr").textContent = m) });
  let order = [], at = -1, shown = false, busy = false;

  function sheet(which) {
    editor.hidden = which !== editor;
    box.classList.toggle("marking", which === editor);  // the picture is drawn on: no stepping to another
    which === editor ? marks.open() : marks.close();
    confirm.hidden = which !== confirm;
    acts.hidden = !!which || !actions.can();
    for (const e of box.querySelectorAll(".rerr")) e.textContent = "";
  }
  function open(i) {
    if (busy) return;
    at = (i + order.length) % order.length;
    const s = order[at];
    big.src = s.src;
    cap.textContent = `${versioned(s.caption, s)} · ${at + 1} of ${order.length}`;
    box.querySelector(".rdel-open").hidden = !(s.ai || s.user);  // the designer's renders stay
    sheet(null);
    box.hidden = false;
  }
  const close = () => { if (!busy) { box.hidden = true; at = -1; } };
  box.querySelector(".rclose").onclick = close;
  box.querySelector(".rprev").onclick = () => open(at - 1);
  box.querySelector(".rnext").onclick = () => open(at + 1);
  box.addEventListener("click", e => e.target === box && close());
  addEventListener("keydown", e => {
    if (!shown || box.hidden || e.target.closest?.(".rsheet") || !editor.hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") open(at - 1);
    else if (e.key === "ArrowRight") open(at + 1);
  });

  box.querySelector(".redit-open").onclick = () => { inspo.clear(); sheet(editor); };
  box.querySelector(".rdel-open").onclick = () => {
    const s = order[at];
    confirm.querySelector(".rq").textContent = `Delete “${versioned(s.caption, s)}”? It goes for good, on every device.`;
    sheet(confirm);
  };
  for (const b of box.querySelectorAll(".rcancel")) b.onclick = () => !busy && sheet(null);
  // Edits take a minute or two; the sheet stays up with a timer, and nothing else in the box can be pressed.
  async function work(form, label, job) {
    const go = form.querySelector(".rgo"), err = form.querySelector(".rerr"), was = go.textContent, t0 = performance.now();
    busy = true; err.textContent = "";
    form.querySelectorAll("button, textarea").forEach(b => (b.disabled = true));
    const tick = setInterval(() => (go.textContent = `${label} · ${Math.round((performance.now() - t0) / 1000)} s`), 500);
    try {
      return await job();
    } catch (e) {
      err.textContent = e.message;
    } finally {
      clearInterval(tick);
      busy = false; go.textContent = was;
      form.querySelectorAll("button, textarea").forEach(b => (b.disabled = false));
    }
  }
  editor.onsubmit = async e => {
    e.preventDefault();
    if (busy || marks.problem()) return;
    const edit = { edits: marks.edits(), marked: marks.marked(), refs: inspo.list() };
    const out = await work(editor, "Editing", () => actions.edit(order[at], edit));
    if (!out?.spot) return;
    inspo.clear();
    open(order.findIndex(s => s.id === out.spot.id));
    cap.textContent += ` · ${out.usd != null ? egp(out.usd) : "Cost not reported"}`;  // what that edit cost
  };
  confirm.querySelector(".rgo").onclick = async () => {
    const i = at;
    if (await work(confirm, "Deleting", () => actions.remove(order[i]).then(() => true))) {
      if (order.length) open(Math.min(i, order.length - 1)); else close();
    }
  };
  for (const t of ["keydown", "keyup"]) editor.addEventListener(t, e => e.stopPropagation());  // typing doesn't walk

  // Upload photo: a pill at the end of each room's title, in the bar's chrome.
  const css = document.createElement("style");
  css.textContent = `
    #renders h2 .rup { margin-left: auto; align-self: center; border: 0; border-radius: 999px; padding: 8px 14px; cursor: pointer;
      font: 500 12px Inter, sans-serif; letter-spacing: .04em; color: #2b2622; background: #fffaf3e6;
      box-shadow: 0 1px 4px #0001, 0 0 0 1px #2b262214 inset; transition: background .2s, transform .15s; }
    #renders h2 .rup:not(:disabled):hover { transform: translateY(-1px); background: #fff; }
    #renders h2 .rup:disabled { opacity: .55; cursor: default; }
    #renders h2 .rup[hidden] { display: none; }
    #renders h2 .rup-err { order: 3; flex-basis: 100%; font: 400 12px Inter, sans-serif; font-style: normal; color: #b3412e; }
    #renders h2 .rup-err:empty { display: none; }
    #renders h2:has(.rup-err:not(:empty)) { flex-wrap: wrap; }
    #renders section.rempty[hidden] { display: none; }`;
  document.head.appendChild(css);
  // Upload photo: one hidden file input for every room; the room pressed is remembered until the files come back.
  const picker = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", multiple: true, hidden: true });
  root.appendChild(picker);
  let upRoom = null, upBusy = false, upText = "", upErr = {};
  const upButton = room => [...list.querySelectorAll(".rup")].find(b => b.dataset.room === room);
  function upShow(room, text) {
    upText = text;
    const b = upButton(room);
    if (b) { b.textContent = text || "Upload photo"; b.disabled = !!text; }
  }
  // Only where the backend runs: its status answers a moment after the page loads, so look again for a while.
  let tries = 0;
  function syncUp() {
    const on = actions.can() && !!actions.upload;
    for (const b of list.querySelectorAll(".rup")) b.hidden = !on;
    for (const s of list.querySelectorAll("section.rempty")) s.hidden = !on;
    if (!on && tries++ < 20) setTimeout(syncUp, 1000);
  }
  picker.onchange = async () => {
    const files = [...picker.files], room = upRoom;
    picker.value = "";
    if (!files.length || !room || upBusy) return;
    const caption = prompt(`Caption for ${files.length > 1 ? `these ${files.length} photos` : "this photo"} (optional)`, "");
    if (caption === null) return;
    upBusy = true;
    delete upErr[room];
    const errs = [];
    for (const [i, f] of files.entries()) {
      upShow(room, files.length > 1 ? `Uploading ${i + 1} of ${files.length}…` : "Uploading…");
      try {
        await actions.upload(room, { image: await shrink(f), caption: caption.trim() });
      } catch (e) {
        errs.push(`${f.name}: ${e.message}`);
        if (/password/i.test(e.message)) break;
      }
    }
    if (errs.length) upErr[room] = errs.join(" · ");
    upBusy = false;
    upShow(room, "");
    const err = list.querySelector(`.rup-err[data-room="${CSS.escape(room)}"]`);
    if (err) err.textContent = upErr[room] || "";
  };

  return {
    fill(renders) {
      const filled = byRoom(renders, rooms);
      order = filled.flatMap(g => g.items);
      // Rooms with nothing yet stay in place, hidden unless photos can be uploaded.
      const groups = [...rooms.map(r => filled.find(g => g.room === r.room) || { ...r, items: [], empty: true }), ...filled.filter(g => !g.room)];
      list.innerHTML = "";
      for (const g of groups) {
        const section = document.createElement("section");
        const title = document.createElement("h2"), count = document.createElement("span"), grid = document.createElement("div");
        title.textContent = g.caption;
        count.textContent = g.items.length;
        title.appendChild(count);
        if (g.room) {
          const up = Object.assign(document.createElement("button"), { type: "button", className: "rup", hidden: true });
          const err = Object.assign(document.createElement("em"), { className: "rup-err", textContent: upErr[g.room] || "" });
          up.dataset.room = err.dataset.room = g.room;
          up.textContent = upBusy && upRoom === g.room && upText ? upText : "Upload photo";
          up.disabled = upBusy;
          up.onclick = () => { if (upBusy) return; upRoom = g.room; picker.click(); };
          title.append(up, err);
        }
        if (g.empty) { section.className = "rempty"; section.hidden = true; }
        grid.className = "rgrid";
        for (const s of g.items) {
          const f = document.createElement("figure");
          f.innerHTML = `<img loading="lazy" alt=""><figcaption></figcaption>`;
          f.querySelector("img").src = s.src;
          f.querySelector("figcaption").textContent = versioned(shortLabel(s.caption, g.caption), s);
          f.onclick = () => open(order.indexOf(s));
          grid.appendChild(f);
        }
        section.append(title, grid);
        list.appendChild(section);
      }
      tries = 0;
      syncUp();
    },
    show() { shown = true; root.hidden = false; tries = 0; syncUp(); },
    hide() { shown = false; root.hidden = true; close(); },
  };
}
