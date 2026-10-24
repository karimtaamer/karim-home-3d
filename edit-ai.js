// Edit AI: change the flat from the viewer, in words. A floating button (3D and 2D, not Renders) freezes the view;
// you circle what to change (or pick Whole view), say what you want and may attach reference pictures. edit_ai.py
// (api/edit-ai.py on Vercel) has an OpenAI model edit furnish.js / materials.js / the version's DXF, rebuilds the
// model and drawing from the DXF, and stores the result as live overrides of the deployed files; the page then
// reloads on the same view with them (liveFiles / liveImport below load them), while git catches up behind.

const API = "api/edit-ai";
const MAX_SIDE = 1280, REF_SIDE = 1024, MAX_REFS = 4;
const INK = "#e5322d";
const store = sessionStorage;

// --- Live overrides: the files Edit AI changed for this version, loaded instead of the deployed ones -----------------
export async function liveFiles(version) {
  const live = { map: {}, api: false, ready: false, rev: null, summary: null, undo: false, broken: [], version };
  live.url = p => live.map[p] || p;
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 5000);
    const r = await fetch(`${API}/patches?version=${encodeURIComponent(version)}`, { signal: ctl.signal, cache: "no-store" });
    clearTimeout(t);
    const ok = r.ok && r.headers.get("content-type")?.includes("json");
    if (!ok) return live;
    const p = await r.json();
    Object.assign(live, { api: true, ready: p.ready, rev: p.rev, summary: p.summary, undo: p.undo, model: p.model });
    for (const [path, f] of Object.entries(p.files || {})) {
      live.map[path] = f.url ? new URL(f.url, location.href).href
        : URL.createObjectURL(new Blob([f.content], { type: path.endsWith(".js") ? "text/javascript" : "application/json" }));
    }
  } catch { /* no Edit AI backend here (a plain static server): the deployed files, as ever */ }
  return live;
}

// A module (furnish.js, materials.js) from its live override when there is one. If the override won't load, or one of
// its functions throws, the deployed module stands in, so a bad edit never blanks the page (Edit AI offers to undo it).
export async function liveImport(live, path) {
  const base = () => import(`./${path}`);
  if (!live.map[path]) return base();
  const [mod, fallback] = await Promise.all([import(live.map[path]).catch(e => (console.error(e), null)), base()]);
  if (!mod) { live.broken.push(path); return fallback; }
  const out = {};
  for (const [k, f] of Object.entries(mod)) {
    out[k] = typeof f !== "function" || typeof fallback[k] !== "function" ? f : (...a) => {
      const parent = a[0]?.isObject3D ? a[0] : null, n = parent?.children.length;
      try { return f(...a); } catch (e) {
        console.error(`Edit AI: ${path} ${k}() threw, using the deployed one`, e);
        if (parent) parent.remove(...parent.children.slice(n));
        live.broken.push(path);
        return fallback[k](...a);
      }
    };
  }
  return out;
}

// --- The button, the freeze, the highlight and the chat --------------------------------------------------------------
export function createEditAI({ THREE, camera, scene, live, showing, mode, room, furniture, materials, cutPlane, drawingFrame, freeMouse }) {
  if (!live.api) return null;  // no backend: no button
  const style = document.createElement("style");
  style.textContent = `
    #edit-ai-btn { position: fixed; right: 18px; bottom: 52px; z-index: 4; display: flex; align-items: center; gap: 7px; border: 0; border-radius: 999px;
      padding: 11px 17px; font: 600 13px Inter, sans-serif; letter-spacing: .02em; color: #fffaf3; background: linear-gradient(135deg, #2b2622, #5a4636);
      box-shadow: 0 4px 16px #0003, 0 0 0 1px #ffffff1c inset; cursor: pointer; transition: transform .15s; }
    #edit-ai-btn:hover { transform: translateY(-1px); }
    #edit-ai-btn svg { width: 16px; height: 16px; fill: none; stroke: #e7b866; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    body.renders #edit-ai-btn, body.edit-ai-open #edit-ai-btn { display: none; }
    @media (max-width: 760px) { #edit-ai-btn { bottom: 128px; right: 14px; padding: 10px 14px; } }
    #edit-ai { position: fixed; inset: 0; z-index: 7; font: 13px Inter, sans-serif; color: #2b2622; }
    #edit-ai[hidden] { display: none; }
    #edit-ai .freeze, #edit-ai .ink { position: absolute; inset: 0; width: 100%; height: 100%; }
    #edit-ai .freeze { object-fit: fill; filter: saturate(.9); }
    #edit-ai .ink { touch-action: none; cursor: crosshair; }
    #edit-ai.chatting .ink { pointer-events: none; }
    #edit-ai .tint { position: absolute; inset: 0; pointer-events: none; box-shadow: 0 0 0 4px #e7b866 inset; }
    #edit-ai .ask { position: absolute; left: 50%; top: 18px; transform: translateX(-50%); display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
      justify-content: center; max-width: calc(100vw - 24px); padding: 9px 10px 9px 16px; border-radius: 999px; background: #fffaf3f2; box-shadow: 0 4px 18px #0003; }
    #edit-ai.chatting .ask { display: none; }
    #edit-ai button { font: inherit; cursor: pointer; border: 0; border-radius: 999px; padding: 7px 13px; background: #2b262212; color: #2b2622; }
    #edit-ai button.go { background: #2b2622; color: #fffaf3; }
    #edit-ai button:disabled { opacity: .45; cursor: default; }
    #edit-ai .x { position: absolute; top: 14px; right: 14px; width: 36px; height: 36px; padding: 0; font-size: 18px; background: #fffaf3f2; box-shadow: 0 2px 10px #0003; }
    #edit-ai .chat { position: absolute; top: 0; right: 0; bottom: 0; width: 360px; display: flex; flex-direction: column; background: #f3eee5; box-shadow: -6px 0 24px #0003; }
    #edit-ai .chat[hidden] { display: none; }
    #edit-ai .chat header { display: flex; align-items: baseline; gap: 8px; padding: 18px 18px 10px; }
    #edit-ai .chat h2 { margin: 0; font: 400 26px "Cormorant Garamond", serif; }
    #edit-ai .chat .meta { flex: 1; font-size: 11px; color: #6d645b; }
    #edit-ai .chat header button { padding: 4px 10px; }
    #edit-ai .msgs { flex: 1; overflow-y: auto; padding: 4px 18px 12px; display: flex; flex-direction: column; gap: 10px; }
    #edit-ai .m { max-width: 92%; padding: 9px 12px; border-radius: 14px; line-height: 1.4; white-space: pre-wrap; }
    #edit-ai .m.bot { background: #fffaf3; align-self: flex-start; box-shadow: 0 0 0 1px #2b262214 inset; }
    #edit-ai .m.me { background: #2b2622; color: #f3eee5; align-self: flex-end; }
    #edit-ai .m.err { background: #fbe4e1; color: #8a2119; align-self: stretch; }
    #edit-ai .m.note { background: none; color: #6d645b; font-size: 11.5px; padding: 0 2px; }
    #edit-ai .m img { display: block; max-width: 100%; border-radius: 8px; margin-top: 6px; }
    #edit-ai .busy { display: flex; align-items: center; gap: 9px; color: #6d645b; font-size: 12px; }
    #edit-ai .busy::before { content: ""; width: 16px; height: 16px; border-radius: 50%; border: 2px solid #2b262226; border-top-color: #b8862f; animation: eai-spin 1s linear infinite; }
    @keyframes eai-spin { to { transform: rotate(1turn); } }
    #edit-ai .thumbs { display: flex; gap: 6px; padding: 0 18px; flex-wrap: wrap; }
    #edit-ai .thumbs:empty { display: none; }
    #edit-ai .thumbs span { position: relative; }
    #edit-ai .thumbs img { height: 52px; border-radius: 6px; display: block; }
    #edit-ai .thumbs b { position: absolute; top: -6px; right: -6px; width: 18px; height: 18px; border-radius: 50%; background: #2b2622; color: #fff;
      font-size: 11px; display: grid; place-items: center; cursor: pointer; }
    #edit-ai form { display: flex; gap: 6px; align-items: flex-end; padding: 10px 14px 16px; }
    #edit-ai textarea { flex: 1; min-height: 44px; max-height: 160px; resize: none; font: 13px Inter, sans-serif; color: #2b2622; background: #fffaf3; border: 0;
      border-radius: 14px; padding: 11px 12px; box-shadow: 0 0 0 1px #2b262226 inset; }
    #edit-ai form button { height: 40px; }
    #edit-ai .attach { width: 40px; padding: 0; font-size: 17px; }
    @media (max-width: 760px) {
      #edit-ai .chat { top: auto; left: 0; width: auto; height: 56vh; border-radius: 18px 18px 0 0; box-shadow: 0 -6px 24px #0003; }
      #edit-ai .ask { top: 62px; border-radius: 16px; }
    }
    #edit-ai-toast { position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 6; display: flex; gap: 8px; align-items: center;
      max-width: calc(100vw - 24px); padding: 9px 10px 9px 16px; border-radius: 16px; background: #2b2622f2; color: #f3eee5; font: 12.5px Inter, sans-serif;
      box-shadow: 0 6px 20px #0004; }
    #edit-ai-toast span { flex: 1; }
    #edit-ai-toast button { font: inherit; border: 0; border-radius: 999px; padding: 6px 12px; cursor: pointer; background: #f3eee5; color: #2b2622; }
    #edit-ai-toast button.ghost { background: #ffffff1f; color: #f3eee5; }
    #edit-ai-toast.bad { background: #8a2119f2; }
  `;
  document.head.appendChild(style);

  const btn = Object.assign(document.createElement("button"), { id: "edit-ai-btn", title: "Change something in this view with AI" });
  btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="2.2"/></svg>Edit AI`;
  document.body.appendChild(btn);

  const box = document.createElement("div");
  box.id = "edit-ai";
  box.hidden = true;
  box.innerHTML = `
    <img class="freeze" alt=""><canvas class="ink"></canvas><div class="tint"></div>
    <div class="ask"><span>Highlight what to change: circle or scribble on it.</span>
      <button class="whole">Whole view</button><button class="clear" hidden>Clear</button><button class="go next" disabled>Next</button></div>
    <button class="x" title="Close">×</button>
    <aside class="chat" hidden>
      <header><h2>Edit AI</h2><span class="meta"></span><button class="redo" title="Circle something else">Re-mark</button></header>
      <div class="msgs"></div>
      <div class="thumbs"></div>
      <form><button type="button" class="attach" title="Attach reference pictures">+</button>
        <textarea rows="1" placeholder="What do you want changed?"></textarea><button class="go send">Send</button></form>
      <input type="file" accept="image/*" multiple hidden>
    </aside>`;
  document.body.appendChild(box);
  // Typing here mustn't walk the camera or hit the drawing's shortcuts.
  for (const t of ["keydown", "keyup", "wheel"]) box.addEventListener(t, e => e.stopPropagation());
  const $ = s => box.querySelector(s);
  const freezeImg = $(".freeze"), ink = $(".ink"), ctx = ink.getContext("2d"), msgs = $(".msgs"), area = $("textarea"), thumbs = $(".thumbs");
  const fileInput = $("input[type=file]");
  $(".chat .meta").textContent = live.model ? `· ${live.model}` : "";

  let freeze = null;  // { url, w, h, plan: drawing frame or null }
  let strokes = [], whole = false, refs = [], busy = false;
  const histKey = `editai-history:${live.version}`;
  let history = JSON.parse(store.getItem(histKey) || "[]");

  // --- Freeze and highlight ---
  function capture() {
    const src = showing() === "drawing" ? document.querySelector("#drawing canvas") : document.querySelector("canvas#scene");
    const k = Math.min(1, MAX_SIDE / Math.max(src.width, src.height));
    const c = Object.assign(document.createElement("canvas"), { width: Math.round(src.width * k), height: Math.round(src.height * k) });
    c.getContext("2d").drawImage(src, 0, 0, c.width, c.height);
    return { canvas: c, url: c.toDataURL("image/jpeg", 0.88), w: innerWidth, h: innerHeight };
  }
  function open() {
    if (showing() === "renders") return;
    freeMouse?.();
    freeze = capture();
    freeze.frame = showing() === "drawing" ? drawingFrame?.() : null;
    freezeImg.src = freeze.url;
    strokes = []; whole = false;
    box.hidden = false;
    box.classList.remove("chatting");
    $(".chat").hidden = true;
    document.body.classList.add("edit-ai-open");
    sizeInk();
    markStep();
  }
  function close() {
    if (busy) return;
    box.hidden = true;
    document.body.classList.remove("edit-ai-open");
  }
  function sizeInk() {
    ink.width = innerWidth * devicePixelRatio; ink.height = innerHeight * devicePixelRatio;
    drawInk();
  }
  function drawInk(target = ctx, sx = devicePixelRatio, sy = devicePixelRatio) {
    target.save();
    target.setTransform(sx, 0, 0, sy, 0, 0);
    if (target === ctx) target.clearRect(0, 0, innerWidth, innerHeight);
    target.lineCap = target.lineJoin = "round";
    target.strokeStyle = INK;
    target.lineWidth = 5;
    target.shadowColor = "#0006"; target.shadowBlur = 3;
    for (const s of strokes) {
      target.beginPath();
      s.forEach(([x, y], i) => (i ? target.lineTo(x, y) : target.moveTo(x, y)));
      if (s.length === 1) target.lineTo(s[0][0] + 0.1, s[0][1]);
      target.stroke();
    }
    target.restore();
  }
  function markStep() {
    $(".next").disabled = !strokes.length;
    $(".clear").hidden = !strokes.length;
  }
  let pen = null;
  ink.addEventListener("pointerdown", e => { ink.setPointerCapture(e.pointerId); pen = [[e.clientX, e.clientY]]; strokes.push(pen); drawInk(); markStep(); });
  ink.addEventListener("pointermove", e => { if (pen) { pen.push([e.clientX, e.clientY]); drawInk(); } });
  const lift = () => (pen = null);
  ink.addEventListener("pointerup", lift);
  ink.addEventListener("pointercancel", lift);
  $(".clear").onclick = () => { strokes = []; drawInk(); markStep(); };
  $(".whole").onclick = () => { whole = true; strokes = []; drawInk(); toChat("Got it, the whole view. What do you want changed?"); };
  $(".next").onclick = () => { whole = false; toChat("Got it, I see what you marked. What do you want changed?"); };
  $(".redo").onclick = () => { if (!busy) { box.classList.remove("chatting"); $(".chat").hidden = true; markStep(); } };
  $(".x").onclick = close;
  btn.onclick = open;
  addEventListener("resize", () => !box.hidden && sizeInk());

  function toChat(greeting) {
    box.classList.add("chatting");
    $(".chat").hidden = false;
    if (!msgs.children.length) for (const h of history.slice(-6)) say(h.role === "user" ? "me" : "bot", h.text);
    if (!live.ready) say("err", "Edit AI isn't switched on yet: the server has no EDIT_AI_OPENAI_API_KEY. You can still try; it will say the same.");
    say("bot", greeting);
    setTimeout(() => area.focus(), 50);
  }
  function say(kind, text, img) {
    const m = document.createElement("div");
    m.className = `m ${kind}`;
    m.textContent = text;
    if (img) m.appendChild(Object.assign(document.createElement("img"), { src: img }));
    msgs.appendChild(m);
    msgs.scrollTop = msgs.scrollHeight;
    return m;
  }

  // --- Reference pictures (re-encoded through a canvas: smaller, and no EXIF goes out) ---
  async function addRef(file) {
    if (refs.length >= MAX_REFS || !file.type.startsWith("image/")) return;
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const k = Math.min(1, REF_SIDE / Math.max(bmp.width, bmp.height));
    const c = Object.assign(document.createElement("canvas"), { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    refs.push(c.toDataURL("image/jpeg", 0.85));
    showRefs();
  }
  function showRefs() {
    thumbs.innerHTML = "";
    refs.forEach((u, i) => {
      const s = document.createElement("span");
      s.innerHTML = `<img src="${u}" alt=""><b title="Remove">×</b>`;
      s.querySelector("b").onclick = () => { refs.splice(i, 1); showRefs(); };
      thumbs.appendChild(s);
    });
  }
  $(".attach").onclick = () => fileInput.click();
  fileInput.onchange = async () => { for (const f of fileInput.files) await addRef(f); fileInput.value = ""; };
  area.addEventListener("paste", e => { for (const it of e.clipboardData?.items || []) if (it.type.startsWith("image/")) addRef(it.getAsFile()); });
  area.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !PHONE.matches) { e.preventDefault(); send(); } });
  area.addEventListener("input", () => { area.style.height = "auto"; area.style.height = Math.min(160, area.scrollHeight) + "px"; });
  $("form").onsubmit = e => { e.preventDefault(); send(); };
  const PHONE = matchMedia("(max-width: 760px)");

  // --- What the model is told about the view ---
  const r3 = n => +n.toFixed(3);
  function camQuery() {
    const p = camera.position, d = camera.getWorldDirection(new THREE.Vector3());
    return [p.x, -p.z, p.y, p.x + d.x, -(p.z + d.z), p.y + d.y, camera.fov].map(r3);
  }
  const libName = new Map(Object.entries(materials || {}).map(([k, m]) => [m, k]));
  function hits3D(points) {
    const ray = new THREE.Raycaster(), out = [], seen = new Set();
    for (const [x, y] of points) {
      ray.setFromCamera(new THREE.Vector2((x / freeze.w) * 2 - 1, -(y / freeze.h) * 2 + 1), camera);
      const hit = ray.intersectObjects(scene.children, true).find(h => {
        if (!h.object.isMesh || (cutPlane && cutPlane.distanceToPoint(h.point) < -1e-3)) return false;
        for (let o = h.object; o; o = o.parent) if (!o.visible) return false;
        const m = [].concat(h.object.material)[0];
        return m && m.visible !== false && !(m.transparent && m.opacity < 0.05);
      });
      if (!hit) continue;
      const key = `${hit.object.uuid}`;
      if (seen.has(key)) continue;
      seen.add(key);
      let inFurniture = false;
      for (let o = hit.object; o; o = o.parent) if (o === furniture) inFurniture = true;
      const m = [].concat(hit.object.material)[0];
      out.push({ x: r3(hit.point.x), y: r3(-hit.point.z), h: r3(hit.point.y), material: libName.get(m) || m?.name || "", furniture: inFurniture });
      if (out.length >= 10) break;
    }
    return out;
  }
  function samples() {
    const pts = strokes.flat();
    if (!pts.length) return [[freeze.w / 2, freeze.h / 2]];
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const c = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
    const step = Math.max(1, Math.floor(pts.length / 14));
    return [c, ...pts.filter((_, i) => i % step === 0)];
  }
  function context() {
    const c = { showing: showing(), mode: mode(), room: room(), wholeView: whole, cam: camQuery() };
    if (c.showing === "drawing" && freeze.frame) {
      const w = freeze.frame.toWorld;
      const box2 = (a, b) => { const p = w(...a), q = w(...b); return [r3(Math.min(p[0], q[0])), r3(Math.min(p[1], q[1])), r3(Math.max(p[0], q[0])), r3(Math.max(p[1], q[1]))]; };
      c.planBox = box2([0, 0], [freeze.w, freeze.h]);
      const pts = strokes.flat();
      if (pts.length) c.highlightBox = box2([Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1]))], [Math.max(...pts.map(p => p[0])), Math.max(...pts.map(p => p[1]))]);
      delete c.cam;
    } else c.hits = hits3D(samples());
    return c;
  }
  function marked() {
    if (whole || !strokes.length) return freeze.url;
    const c = Object.assign(document.createElement("canvas"), { width: freeze.canvas.width, height: freeze.canvas.height });
    const g = c.getContext("2d");
    g.drawImage(freeze.canvas, 0, 0);
    drawInk(g, c.width / freeze.w, c.height / freeze.h);
    return c.toDataURL("image/jpeg", 0.88);
  }

  // --- Send, apply, reload on the same view ---
  async function call(action, body) {
    const r = await fetch(`${API}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({ error: `${r.status} ${r.statusText}` }));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  async function send() {
    const text = area.value.trim();
    if (busy || !text) return;
    busy = true;
    $(".send").disabled = true;
    say("me", text);
    refs.forEach(u => say("me", "", u).classList.add("ref"));
    const wait = say("note", "");
    wait.classList.add("busy");
    wait.append("Working on it: finding the piece, editing, rebuilding…");
    try {
      const res = await call("chat", { version: live.version, message: text, image: marked(), refs, context: context(), history });
      wait.remove();
      history.push({ role: "user", text }, { role: "assistant", text: res.reply });
      history = history.slice(-12);
      store.setItem(histKey, JSON.stringify(history));
      area.value = ""; refs = []; showRefs();
      say("bot", res.reply);
      const cost = res.usd != null ? ` · $${res.usd.toFixed(3)}` : "";
      if (!res.changed?.length) { say("note", `No change made${cost}`); return; }
      say("note", `Applying the change${cost}…`);
      await apply(res, cost);
    } catch (e) {
      wait.remove();
      say("err", e.message);
    } finally {
      busy = false;
      $(".send").disabled = false;
    }
  }
  async function apply(res, cost) {
    // Make sure the new code loads before showing it; a version that doesn't is undone on the spot.
    const fresh = await liveFiles(live.version);
    for (const p of ["furnish.js", "materials.js"]) {
      if (!fresh.map[p]) continue;
      try { await import(fresh.map[p]); } catch (e) {
        await call("undo", { version: live.version });
        throw new Error(`That edit broke the 3D code (${e.message}), so I undid it. Try saying it another way.`);
      }
    }
    store.setItem("editai-applied", JSON.stringify({ version: live.version, reply: res.reply, cost, sync: res.sync }));
    reloadHere();
  }
  function reloadHere() {
    const q = new URLSearchParams(location.search);
    for (const k of ["cam", "view", "room", "show"]) q.delete(k);
    if (mode() === "walk") q.set("cam", camQuery().join(","));
    else q.set("view", mode());
    if (showing() !== "model") q.set("show", showing());
    location.search = q;
  }

  // --- After the reload: what changed, with Undo; or a warning if the change didn't load ---
  function toast(text, actions, bad) {
    document.getElementById("edit-ai-toast")?.remove();
    const t = document.createElement("div");
    t.id = "edit-ai-toast";
    t.className = "ui" + (bad ? " bad" : "");
    t.appendChild(Object.assign(document.createElement("span"), { textContent: text }));
    for (const [label, fn, ghost] of actions) {
      const b = Object.assign(document.createElement("button"), { textContent: label, className: ghost ? "ghost" : "" });
      b.onclick = async () => { b.disabled = true; try { await fn(); } catch (e) { b.disabled = false; t.querySelector("span").textContent = e.message; } };
      t.appendChild(b);
    }
    document.body.appendChild(t);
    return t;
  }
  const undoAndReload = async () => {
    await call("undo", { version: live.version });
    history.push({ role: "user", text: "(undid the last change)" });
    store.setItem(histKey, JSON.stringify(history));
    store.setItem("editai-applied", JSON.stringify({ version: live.version, reply: "Undone.", undone: true }));
    reloadHere();
  };
  const applied = JSON.parse(store.getItem("editai-applied") || "null");
  store.removeItem("editai-applied");
  if (live.broken.length) {
    toast(`The last Edit AI change didn't load (${[...new Set(live.broken)].join(", ")}); showing the code before it.`,
      [["Undo it", undoAndReload], ["×", () => document.getElementById("edit-ai-toast").remove(), true]], true);
  } else if (applied?.version === live.version) {
    const t = toast(applied.undone ? "Edit AI change undone." : `${applied.reply}${applied.cost || ""}`,
      applied.undone ? [["×", () => t.remove(), true]]
        : [["Undo", undoAndReload], ["Edit more", () => (t.remove(), open())], ["×", () => t.remove(), true]]);
    if (applied.undone) setTimeout(() => t.remove(), 4000);
  }
  return { open, close };
}
