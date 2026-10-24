// Renders: every designer render from spots.json, grouped by room, as a third view beside the 3D model
// and the drawing. Click one to see it large; arrow keys step through, Esc closes.
// With Generate Photo Spot's backend (actions.can()), the large view can also edit a render in words (a new
// version, the old kept) and delete a generated one, after a confirmation.

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
        <label>What should change?<textarea placeholder="e.g. walnut nightstands, warmer evening light"></textarea></label>
        <p class="rnote">Saved as a new version; this one stays.</p>
        <div class="rerr"></div>
        <div class="rrow"><button type="submit" class="rgo">Make new version</button><button type="button" class="rcancel">Cancel</button></div>
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
  const notes = editor.querySelector("textarea");
  let order = [], at = -1, shown = false, busy = false;

  function sheet(which) {
    editor.hidden = which !== editor;
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
    box.querySelector(".rdel-open").hidden = !s.ai;  // the designer's renders stay
    sheet(null);
    box.hidden = false;
  }
  const close = () => { if (!busy) { box.hidden = true; at = -1; } };
  box.querySelector(".rclose").onclick = close;
  box.querySelector(".rprev").onclick = () => open(at - 1);
  box.querySelector(".rnext").onclick = () => open(at + 1);
  box.addEventListener("click", e => e.target === box && close());
  addEventListener("keydown", e => {
    if (!shown || box.hidden || e.target.closest?.(".rsheet")) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") open(at - 1);
    else if (e.key === "ArrowRight") open(at + 1);
  });

  box.querySelector(".redit-open").onclick = () => { sheet(editor); notes.value = ""; notes.focus(); };
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
    const text = notes.value.trim();
    if (!text) return;
    const spot = await work(editor, "Editing", () => actions.edit(order[at], text));
    if (spot) open(order.findIndex(s => s.id === spot.id));
  };
  confirm.querySelector(".rgo").onclick = async () => {
    const i = at;
    if (await work(confirm, "Deleting", () => actions.remove(order[i]).then(() => true))) {
      if (order.length) open(Math.min(i, order.length - 1)); else close();
    }
  };
  for (const t of ["keydown", "keyup"]) editor.addEventListener(t, e => e.stopPropagation());  // typing doesn't walk

  return {
    fill(renders) {
      const groups = byRoom(renders, rooms);
      order = groups.flatMap(g => g.items);
      list.innerHTML = "";
      for (const g of groups) {
        const section = document.createElement("section");
        const title = document.createElement("h2"), count = document.createElement("span"), grid = document.createElement("div");
        title.textContent = g.caption;
        count.textContent = g.items.length;
        title.appendChild(count);
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
    },
    show() { shown = true; root.hidden = false; },
    hide() { shown = false; root.hidden = true; close(); },
  };
}
