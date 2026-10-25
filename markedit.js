// Marked edits on a picture: Make an edit on a Generate Photo Spot attempt (photogen.js) and Edit on the Renders
// screen (renders.js). As in Edit AI, you circle what to change in red on the picture (a looping hand shows how on
// opening), and each mark gets its own note; circling again after a note (or Add another edit) starts the next
// mark, so several mark + note pairs stack up, numbered, each with a crop of what it marks. A note can also be for
// the whole picture (light, mood). The one Regenerate sends them all: edits() -> [{ i, note, box }] (box: the mark's
// [x0, y0, x1, y1] as fractions of the picture, i its number; neither on a whole-picture note) and marked(): the
// picture with the numbered red marks drawn in (JPEG data URL), which photogen.py sends beside the clean one, so
// "the wardrobe on the right" can't be taken for the one on the left.

export const INK = "#e5322d";  // Edit AI's red
const SIDE = 1536;  // long side of the marked picture as sent (photogen.py's frame)
export const MAX_MARKS = 8;

// Edit AI's hand, its fingertip at the origin.
const HAND = `<g class="hand"><g transform="translate(-8,-4)">
  <path d="M10 2 C 10 -2, 17 -2, 17 2 L 17 30 L 18 22 C 18 18, 25 18, 25 22 L 25 32 L 26 26 C 26 22, 33 22, 33 26 L 33 36 L 34 31 C 34 27, 41 27, 41 31 L 41 52 C 41 66, 33 74, 22 74 C 12 74, 6 68, 3 58 L -4 40 C -6 35, 0 32, 4 36 L 10 46 Z"
    fill="#efbb92" stroke="#5c3a22" stroke-width="2" stroke-linejoin="round"/>
  <path d="M17 30 L17 40 M25 32 L25 41 M33 36 L33 43" stroke="#8a5d3b" stroke-width="1" stroke-linecap="round" fill="none"/></g></g>`;
// The cue: a small photo of a bedroom, the hand circling the wardrobe on its right.
const CUE = `<svg viewBox="0 0 200 134">
  <defs><linearGradient id="mk-wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e3d6c6"/><stop offset="1" stop-color="#f1e9de"/></linearGradient></defs>
  <rect x="2" y="2" width="196" height="130" rx="8" fill="url(#mk-wall)" stroke="#fffaf3" stroke-width="3"/>
  <polygon points="4,104 196,104 196,130 4,130" fill="#c08a58"/>
  <rect x="12" y="18" width="40" height="86" fill="#f4eee6" stroke="#cfc3b2"/><line x1="32" y1="18" x2="32" y2="104" stroke="#cfc3b2"/>
  <rect x="74" y="34" width="34" height="34" rx="16" fill="#cbd9de" stroke="#e8d3a8" stroke-width="2"/>
  <rect x="68" y="78" width="48" height="26" fill="#8a5d3b"/>
  <rect x="146" y="22" width="34" height="82" fill="#9b6b44"/><line x1="163" y1="22" x2="163" y2="104" stroke="#7a5233"/>
  <rect class="pick" x="146" y="22" width="34" height="82" fill="${INK}" fill-opacity="0"/>
  <path class="loop" pathLength="190" d="M162 12 C 186 12, 194 40, 192 64 C 190 96, 176 114, 160 112 C 140 110, 134 84, 136 58 C 138 30, 146 14, 168 14"/>
  ${HAND}
  <g transform="translate(184,10)"><circle r="8" fill="${INK}"/><text y="4" text-anchor="middle" font-family="Inter, sans-serif" font-size="11" font-weight="700" fill="#fff">1</text></g>
</svg><div class="cap">Circle what you want changed<br><span>then say how, one note per mark</span></div>`;

let styled = false;
function style() {
  if (styled) return;
  styled = true;
  const s = document.createElement("style");
  s.textContent = `
    .mk-ink { position: absolute; z-index: 2; cursor: crosshair; touch-action: none; border-radius: 6px; box-shadow: 0 0 0 2px ${INK}55; }
    .mk-ink[hidden], .mk-cue[hidden] { display: none; }
    .mk-cue { position: absolute; z-index: 3; width: 190px; transform: translate(-50%, -50%); pointer-events: none; filter: drop-shadow(0 10px 24px #0007);
      animation: mk-in .4s ease-out; }
    .mk-cue svg { display: block; width: 100%; height: auto; overflow: visible; }
    .mk-cue .cap { margin-top: 8px; text-align: center; font: 600 12px Inter, sans-serif; letter-spacing: .04em; color: #fffaf3; text-shadow: 0 1px 4px #000c; line-height: 1.35; }
    .mk-cue .cap span { font-weight: 500; font-size: 10.5px; opacity: .9; }
    .mk-cue .loop { fill: none; stroke: ${INK}; stroke-width: 3.2; stroke-linecap: round; stroke-dasharray: 190; stroke-dashoffset: 190; animation: mk-draw 3.2s ease-in-out infinite; }
    .mk-cue .pick { animation: mk-pick 3.2s ease-in-out infinite; }
    .mk-cue .hand { animation: mk-hand 3.2s ease-in-out infinite; filter: drop-shadow(0 3px 4px #0006); }
    @keyframes mk-in { from { opacity: 0; } }
    @keyframes mk-draw { 0%, 12% { stroke-dashoffset: 190; opacity: 1; } 62% { stroke-dashoffset: 0; opacity: 1; } 88% { stroke-dashoffset: 0; opacity: 1; } 100% { stroke-dashoffset: 0; opacity: 0; } }
    @keyframes mk-pick { 0%, 55% { fill-opacity: 0; } 66%, 88% { fill-opacity: .28; } 100% { fill-opacity: 0; } }
    @keyframes mk-hand {
      0% { transform: translate(150px, 170px) rotate(-8deg); opacity: 0; }
      10% { transform: translate(164px, 12px) rotate(-8deg); opacity: 1; }
      12% { transform: translate(164px, 12px) scale(.94); }
      24% { transform: translate(192px, 58px) scale(.94); }
      36% { transform: translate(166px, 112px) scale(.94); }
      48% { transform: translate(136px, 64px) scale(.94); }
      62% { transform: translate(166px, 14px) scale(.94); }
      72% { transform: translate(176px, 120px) scale(1); opacity: 1; }
      90%, 100% { transform: translate(186px, 170px); opacity: 0; } }
    @media (prefers-reduced-motion: reduce) { .mk-cue :is(.hand, .loop, .pick) { animation: none; stroke-dashoffset: 0; } }
    .mk-panel { display: flex; flex-direction: column; gap: 8px; }
    .mk-hint { margin: 0; font-size: 12.5px; line-height: 1.4; color: #2b2622; }
    .mk-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; max-height: 42vh; overflow-y: auto; }
    .mk-list:empty { display: none; }
    .mk-list li { display: flex; align-items: flex-start; gap: 8px; }
    .mk-n { flex: none; display: grid; place-items: center; min-width: 24px; height: 24px; padding: 0 6px; box-sizing: border-box; border-radius: 999px;
      background: ${INK}; color: #fff; font: 700 12px Inter, sans-serif; }
    .mk-list li.whole .mk-n { background: #2b2622; font-size: 10px; letter-spacing: .04em; }
    .mk-crop { flex: none; width: 66px; height: 44px; border-radius: 5px; box-shadow: 0 0 0 2px ${INK}; background: #e6dccf; }
    .mk-list li.whole .mk-crop { display: none; }
    .mk-list textarea { flex: 1; min-width: 0; min-height: 44px; font: 13px Inter, sans-serif; color: #2b2622; background: #fffaf3; border: 0; border-radius: 10px;
      padding: 8px 10px; box-shadow: 0 0 0 1px #2b262226 inset; resize: vertical; }
    .mk-list li.empty textarea { box-shadow: 0 0 0 2px ${INK} inset; }
    .mk-list b { flex: none; width: 22px; height: 22px; border-radius: 50%; background: #2b2622; color: #f3eee5; font: 600 13px/22px Inter, sans-serif;
      text-align: center; cursor: pointer; }
    .mk-row { display: flex; flex-wrap: wrap; gap: 6px; }
    .mk-panel .mk-row button { position: static; width: auto; height: auto; min-height: 34px; border: 0; border-radius: 999px; padding: 0 13px; cursor: pointer;
      font: 500 12px Inter, sans-serif; letter-spacing: .03em; background: #fffaf3; color: #2b2622; box-shadow: 0 0 0 1px #2b262226 inset; }
    .mk-panel .mk-row button:disabled { opacity: .4; cursor: default; }
    @media (max-width: 760px) { .mk-list textarea { font-size: 16px; } .mk-cue { width: 160px; } }  /* under 16px iOS zooms the page on focus */`;
  document.head.appendChild(s);
}

const r3 = n => +n.toFixed(3);

// stage: the positioned box img sits in (the ink and the cue go over the picture there); panel: where the hint, the
// list of edits and its buttons go; go: what the send button says, for the hint; onChange() after every change.
// -> { open(), close(), clear(), edits(), marked(), problem() }
export function markEditor({ stage, img, panel, go = "Regenerate", onChange = () => {} }) {
  style();
  const ink = Object.assign(document.createElement("canvas"), { className: "mk-ink", hidden: true });
  const cue = Object.assign(document.createElement("div"), { className: "mk-cue", hidden: true, innerHTML: CUE });
  cue.setAttribute("aria-hidden", "true");
  stage.append(ink, cue);
  panel.classList.add("mk-panel");
  panel.innerHTML = `<p class="mk-hint"></p><ol class="mk-list"></ol>
    <div class="mk-row"><button type="button" class="mk-more">+ Add another edit</button><button type="button" class="mk-whole">Note for the whole picture</button></div>`;
  const hint = panel.querySelector(".mk-hint"), list = panel.querySelector(".mk-list");
  const more = panel.querySelector(".mk-more"), wholeBtn = panel.querySelector(".mk-whole");
  // Each edit: { strokes: [[[x, y] as fractions of the picture, ..]], note, whole }. fresh: the next stroke starts a new mark.
  let items = [], pen = null, fresh = true, rect = null;

  const marks = () => items.filter(x => !x.whole);
  const number = it => marks().indexOf(it) + 1;
  const label = it => (it.whole ? "The whole-picture note" : `Mark ${number(it)}`);
  function box(it) {
    const pts = it.strokes.flat(), xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const b = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    for (const k of [0, 1]) if (b[k + 2] - b[k] < 0.02) { const c = (b[k] + b[k + 2]) / 2; b[k] = Math.max(0, c - 0.01); b[k + 2] = Math.min(1, c + 0.01); }  // a tap
    return b;
  }

  // The marks on g over a w x h picture; s: picture units per CSS px (line width and number badges).
  function draw(g, w, h, s = 1) {
    g.save();
    g.lineCap = g.lineJoin = "round";
    g.strokeStyle = INK; g.lineWidth = 4.5 * s;
    g.shadowColor = "#0006"; g.shadowBlur = 3 * s;
    for (const it of marks()) for (const st of it.strokes) {
      g.beginPath();
      st.forEach(([x, y], i) => (i ? g.lineTo(x * w, y * h) : g.moveTo(x * w, y * h)));
      if (st.length === 1) g.lineTo(st[0][0] * w + 0.1, st[0][1] * h);
      g.stroke();
    }
    // Each mark's number on a red disc at its top-left corner, kept inside the picture.
    const r = 11 * s;
    g.font = `700 ${13 * s}px Inter, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
    for (const it of marks()) {
      const b = box(it), x = Math.min(w - r, Math.max(r, b[0] * w - r * 0.4)), y = Math.min(h - r, Math.max(r, b[1] * h - r * 0.4));
      g.fillStyle = INK; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
      g.shadowBlur = 0; g.fillStyle = "#fff"; g.fillText(String(number(it)), x, y + 0.5 * s);
      g.shadowBlur = 3 * s;
    }
    g.restore();
  }
  function paint() {
    if (!rect) return;
    const g = ink.getContext("2d");
    g.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    g.clearRect(0, 0, rect.w, rect.h);
    draw(g, rect.w, rect.h);
  }
  // The ink lies exactly over the picture as shown (object-fit: contain may leave bars round it).
  function place() {
    if (ink.hidden || !img.naturalWidth) return;
    const r = img.getBoundingClientRect(), s = stage.getBoundingClientRect();
    const k = Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight), w = img.naturalWidth * k, h = img.naturalHeight * k;
    rect = { x: r.left - s.left + stage.scrollLeft + (r.width - w) / 2, y: r.top - s.top + stage.scrollTop + (r.height - h) / 2, w, h };
    Object.assign(ink.style, { left: `${rect.x}px`, top: `${rect.y}px`, width: `${w}px`, height: `${h}px` });
    ink.width = Math.round(w * devicePixelRatio); ink.height = Math.round(h * devicePixelRatio);
    Object.assign(cue.style, { left: `${rect.x + w / 2}px`, top: `${rect.y + h / 2}px` });
    paint();
  }
  new ResizeObserver(place).observe(stage);
  img.addEventListener("load", place);

  const at = e => { const b = ink.getBoundingClientRect(); return [r3(Math.min(1, Math.max(0, (e.clientX - b.left) / b.width))), r3(Math.min(1, Math.max(0, (e.clientY - b.top) / b.height)))]; };
  ink.addEventListener("pointerdown", e => {
    if (e.button > 0) return;
    e.preventDefault();
    cue.hidden = true;
    let it = items.at(-1);
    // Strokes join the mark still waiting for its note (a circle drawn in two goes); after a note, a new mark.
    if (fresh || !it || it.whole || it.note.trim()) {
      if (marks().length >= MAX_MARKS) { hint.textContent = `Up to ${MAX_MARKS} marks per edit: regenerate, then mark the rest on the new picture.`; return; }
      it = { strokes: [], note: "", whole: false };
      items.push(it);
      fresh = false;
    }
    ink.setPointerCapture(e.pointerId);
    pen = [at(e)];
    it.strokes.push(pen);
    paint();
  });
  ink.addEventListener("pointermove", e => { if (pen) { pen.push(at(e)); paint(); } });
  const lift = () => {
    if (!pen) return;
    pen = null;
    drawList();
    // The note box for that mark, ready to type in.
    requestAnimationFrame(() => list.lastElementChild?.querySelector("textarea")?.focus({ preventScroll: true }));
  };
  ink.addEventListener("pointerup", lift);
  ink.addEventListener("pointercancel", lift);

  function drawList() {
    list.innerHTML = "";
    for (const it of items) {
      const li = document.createElement("li");
      li.className = it.whole ? "whole" : "";
      li.innerHTML = `<span class="mk-n"></span><canvas class="mk-crop" width="132" height="88"></canvas><textarea rows="2"></textarea><b title="Remove this edit">×</b>`;
      li.querySelector(".mk-n").textContent = it.whole ? "ALL" : number(it);
      const area = li.querySelector("textarea");
      area.value = it.note;
      area.placeholder = it.whole ? "The whole picture: e.g. warmer evening light" : `Mark ${number(it)}: what should change here? e.g. make it white`;
      area.oninput = () => { it.note = area.value; li.classList.toggle("empty", !it.note.trim()); refresh(); };
      li.classList.toggle("empty", !it.note.trim());
      li.querySelector("b").onclick = () => { items.splice(items.indexOf(it), 1); fresh = true; drawList(); paint(); };
      if (!it.whole && img.naturalWidth) {  // a crop of what the mark covers, a margin round it
        const [x0, y0, x1, y1] = box(it), mx = (x1 - x0) * 0.25 + 0.02, my = (y1 - y0) * 0.25 + 0.02;
        const a = Math.max(0, x0 - mx), b = Math.max(0, y0 - my), c = Math.min(1, x1 + mx), d = Math.min(1, y1 + my);
        const cv = li.querySelector("canvas"), g = cv.getContext("2d"), W = img.naturalWidth, H = img.naturalHeight;
        const k = Math.max(cv.width / ((c - a) * W), cv.height / ((d - b) * H));  // cover the thumb
        const sw = cv.width / k, sh = cv.height / k, sx = Math.max(0, Math.min(W - sw, ((a + c) / 2) * W - sw / 2)), sy = Math.max(0, Math.min(H - sh, ((b + d) / 2) * H - sh / 2));
        g.drawImage(img, sx, sy, sw, sh, 0, 0, cv.width, cv.height);
      }
      list.appendChild(li);
    }
    refresh();
  }

  function problem() {
    if (!items.length) return "Circle what to change on the picture first (or add a note for the whole picture).";
    const it = items.find(x => !x.note.trim());
    return it ? `${label(it)} needs a note.` : "";
  }
  function refresh() {
    const last = items.at(-1), n = items.length;
    hint.textContent = !n ? "Circle or scribble in red on what you want changed. Each mark gets its own note."
      : fresh ? "Circle the next thing to change on the picture."
      : !last.note.trim() ? (last.whole ? "Say what should change across the whole picture." : `Mark ${number(last)}: say what should change there.`)
      : `${n === 1 ? "One edit" : `${n} edits`} ready. Circle something else to add another, or press ${go} to make ${n === 1 ? "it" : "them all at once"}.`;
    more.disabled = !n || !last.note.trim() || marks().length >= MAX_MARKS;
    wholeBtn.disabled = items.some(x => x.whole);
    onChange();
  }
  more.onclick = () => { fresh = true; cue.hidden = false; refresh(); };
  wholeBtn.onclick = () => {
    items.push({ strokes: [], note: "", whole: true });
    drawList();
    list.lastElementChild.querySelector("textarea").focus({ preventScroll: true });
  };

  function clear() { items = []; pen = null; fresh = true; drawList(); paint(); }
  return {
    open() { clear(); ink.hidden = false; cue.hidden = false; place(); },
    close() { ink.hidden = cue.hidden = true; pen = null; },
    clear,
    problem,
    edits: () => items.filter(x => x.note.trim()).map(x => (x.whole ? { note: x.note.trim() } : { i: number(x), note: x.note.trim(), box: box(x).map(r3) })),
    // The picture with the numbered marks, at most SIDE px long; null with no marks (or a picture that can't be read back).
    marked() {
      if (!marks().length || !img.naturalWidth) return null;
      const k = Math.min(1, SIDE / Math.max(img.naturalWidth, img.naturalHeight));
      const c = Object.assign(document.createElement("canvas"), { width: Math.round(img.naturalWidth * k), height: Math.round(img.naturalHeight * k) });
      const g = c.getContext("2d");
      g.drawImage(img, 0, 0, c.width, c.height);
      draw(g, c.width, c.height, c.width / (rect?.w || c.width / 2));
      try { return c.toDataURL("image/jpeg", 0.88); } catch { return null; }
    },
  };
}
