// Renders: every designer render from spots.json, grouped by room, as a third view beside the 3D model
// and the drawing. Click one to see it large; arrow keys step through, Esc closes.

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

export function createRenders(root, rooms) {
  root.innerHTML = `
    <div class="rlist"></div>
    <div class="rbox" hidden>
      <img alt="">
      <div class="rcap"></div>
      <button class="rclose" aria-label="Close">✕</button>
      <button class="rprev" aria-label="Previous">‹</button>
      <button class="rnext" aria-label="Next">›</button>
    </div>`;
  const list = root.querySelector(".rlist"), box = root.querySelector(".rbox");
  const big = box.querySelector("img"), cap = box.querySelector(".rcap");
  let order = [], at = -1, shown = false;

  function open(i) {
    at = (i + order.length) % order.length;
    big.src = order[at].src;
    cap.textContent = `${order[at].caption} · ${at + 1} of ${order.length}`;
    box.hidden = false;
  }
  const close = () => { box.hidden = true; at = -1; };
  box.querySelector(".rclose").onclick = close;
  box.querySelector(".rprev").onclick = () => open(at - 1);
  box.querySelector(".rnext").onclick = () => open(at + 1);
  box.addEventListener("click", e => e.target === box && close());
  addEventListener("keydown", e => {
    if (!shown || box.hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") open(at - 1);
    else if (e.key === "ArrowRight") open(at + 1);
  });

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
          f.querySelector("figcaption").textContent = shortLabel(s.caption, g.caption);
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
