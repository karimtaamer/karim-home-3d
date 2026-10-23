// Generate Photo Spot: in Walk, turn the view you are standing in into a photoreal render with OpenAI
// (photogen.py does the calls, so the key never reaches the page). It sends a screenshot of the model,
// a plan of the room drawn from the DWG and the view's numbers; the designer's renders go along as
// style references. Comment to re-run it on the attempt shown; approve to save it as a photo spot.
// The endpoints are photogen.py's: the local server, or api/photospot.py on Vercel; with neither (a plain
// static server) the button stays hidden. If PHOTOSPOT_PASSWORD is set there, the page asks for it once.

const W = 1536, H = 1024;  // the 3:2 frame photogen.py asks for
const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];

export function createPhotoGen({ THREE, camera, scene, composer, renderer, M, spotsFile, roomAt, captionOf, isWalking, freeMouse, spotCount, onSaved }) {
  const button = document.getElementById("photogen");
  let ready = "";
  fetch("api/photospot").then(r => (r.ok ? r.json() : null)).then(s => {
    if (!s?.ok) return;
    ready = `Turn this view into a photo spot (${s.model})`;
    button.hidden = false;
    api.sync();
  }, () => {});

  const style = document.createElement("style");
  style.textContent = `
    #photogen-box { position: fixed; inset: 0; z-index: 6; display: grid; grid-template-columns: 1fr 320px; background: #1c1814f2; color: #f3eee5; }
    #photogen-box[hidden] { display: none; }
    #photogen-box .stage { position: relative; display: grid; place-items: center; padding: 22px; min-height: 0; }
    #photogen-box .stage > img { max-width: 100%; max-height: calc(100vh - 150px); object-fit: contain; border-radius: 6px; }
    #photogen-box .wait { position: absolute; inset: 0; display: grid; place-content: center; gap: 12px; text-align: center; background: #1c1814b3;
      font-size: 13px; letter-spacing: .06em; }
    #photogen-box .wait[hidden] { display: none; }
    #photogen-box .spin { width: 34px; height: 34px; margin: 0 auto; border-radius: 50%; border: 3px solid #f3eee533; border-top-color: #d9a54a;
      animation: pg-spin 1s linear infinite; }
    @keyframes pg-spin { to { transform: rotate(1turn); } }
    #photogen-box .thumbs { position: absolute; left: 22px; right: 22px; bottom: 18px; display: flex; gap: 8px; overflow-x: auto; }
    #photogen-box .thumbs figure { margin: 0; cursor: pointer; opacity: .6; transition: opacity .2s; }
    #photogen-box .thumbs figure.on, #photogen-box .thumbs figure:hover { opacity: 1; }
    #photogen-box .thumbs img { display: block; height: 58px; border-radius: 4px; box-shadow: 0 0 0 2px transparent; }
    #photogen-box .thumbs figure.on img { box-shadow: 0 0 0 2px #d9a54a; }
    #photogen-box .thumbs figcaption { font-size: 10px; letter-spacing: .08em; margin-top: 3px; }
    #photogen-box aside { display: flex; flex-direction: column; gap: 14px; padding: 26px 22px; background: #f3eee5; color: #2b2622; overflow-y: auto; }
    #photogen-box h2 { margin: 0; font: 400 30px "Cormorant Garamond", serif; }
    #photogen-box .meta { margin: -8px 0 0; font-size: 11.5px; letter-spacing: .04em; color: #6d645b; }
    #photogen-box label { display: flex; flex-direction: column; gap: 6px; font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase; color: #6d645b; }
    #photogen-box input, #photogen-box textarea { font: 13px Inter, sans-serif; color: #2b2622; background: #fffaf3; border: 0; border-radius: 10px;
      padding: 9px 11px; box-shadow: 0 0 0 1px #2b262226 inset; resize: vertical; }
    #photogen-box textarea { min-height: 110px; }
    #photogen-box ol { margin: 0; padding-left: 18px; font-size: 12px; color: #4a423b; }
    #photogen-box ol:empty { display: none; }
    #photogen-box .err { font-size: 12px; color: #b3412e; }
    #photogen-box .err:empty { display: none; }
    #photogen-box .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; }
    #photogen-box .actions button { border: 0; border-radius: 999px; padding: 9px 15px; cursor: pointer; font: 500 12px Inter, sans-serif;
      letter-spacing: .04em; background: #fffaf3; color: #2b2622; box-shadow: 0 0 0 1px #2b262226 inset; }
    #photogen-box .actions .approve { background: #2b2622; color: #f3eee5; }
    #photogen-box .actions button:disabled { opacity: .4; cursor: default; }
    @media (max-width: 760px) {
      #photogen-box { grid-template-columns: 1fr; grid-template-rows: auto 1fr; overflow-y: auto; }
      #photogen-box .stage { padding: 12px 12px 92px; }
      #photogen-box .stage > img { max-height: 46vh; }
      #photogen-box .thumbs { left: 12px; right: 12px; }
    }`;
  document.head.appendChild(style);
  const box = document.createElement("div");
  box.id = "photogen-box";
  box.hidden = true;
  box.innerHTML = `
    <div class="stage"><img alt=""><div class="wait" hidden><div class="spin"></div><div class="status"></div></div><div class="thumbs"></div></div>
    <aside>
      <h2>New photo spot</h2>
      <p class="meta"></p>
      <label>Name<input class="name"></label>
      <label>Comments<textarea placeholder="What should change? e.g. warmer evening light, sofa in oatmeal bouclé, no rug"></textarea></label>
      <ol></ol>
      <div class="err"></div>
      <div class="actions">
        <button class="approve">Approve &amp; save</button>
        <button class="revise">Revise</button>
        <button class="cancel">Discard</button>
      </div>
    </aside>`;
  document.body.appendChild(box);
  const $ = s => box.querySelector(s);
  const stage = $(".stage > img"), wait = $(".wait"), status = $(".status"), thumbs = $(".thumbs");
  const name = $(".name"), notes = $("textarea"), list = $("ol"), err = $(".err");
  // Typing here must not walk, measure or step through renders (they all listen on window).
  for (const t of ["keydown", "keyup"]) box.addEventListener(t, e => e.stopPropagation());

  // One sitting: the view it started from, and every attempt so far (each one's comments led to the next).
  let job = null;

  function frame() {
    // The model as you see it, without the photo-spot rings, cropped to 3:2 from the middle. It goes as the
    // picture to edit, so its angle and every object in it stay put; only the finishes change.
    const rings = scene.getObjectByName("photo-spot-markers");
    const was = rings?.visible;
    if (rings) rings.visible = false;
    composer.render();
    const src = renderer.domElement, c = document.createElement("canvas");
    c.width = W; c.height = H;
    const k = Math.min(src.width / W, src.height / H), sw = W * k, sh = H * k;
    c.getContext("2d").drawImage(src, (src.width - sw) / 2, (src.height - sh) / 2, sw, sh, 0, 0, W, H);
    if (rings) rings.visible = was;
    return c.toDataURL("image/jpeg", 0.92);  // a PNG this size can pass Vercel's 4.5 MB request limit
  }

  function view() {
    const dir = camera.getWorldDirection(new THREE.Vector3());
    const x = camera.position.x, y = -camera.position.z, h = camera.position.y;
    // The lens of the 3:2 crop: the screen's height is kept unless the screen is narrower than 3:2.
    const tv = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2), a = innerWidth / innerHeight;
    const th = a >= W / H ? tv * (W / H) : tv * a, tv2 = th / (W / H);
    const deg = r => THREE.MathUtils.radToDeg(r);
    const heading = (deg(Math.atan2(dir.x, -dir.z)) + 360) % 360, pitch = deg(Math.asin(dir.y));
    return {
      x, y, h, heading,
      cam: [x, y, h, x + dir.x * 3, y - dir.z * 3, h + dir.y * 3, deg(2 * Math.atan(tv2))],
      info: {
        height: h, facing: COMPASS[Math.round(heading / 45) % 8], hfov: deg(2 * Math.atan(th)), vfov: deg(2 * Math.atan(tv2)),
        tilt: Math.abs(pitch) < 3 ? "level" : `${Math.abs(pitch).toFixed(0)} degrees ${pitch > 0 ? "up" : "down"}`,
      },
    };
  }

  // Other rooms in shot (through doors and openings): rays fanned across the lens at waist height,
  // each sampled for rooms up to the first solid thing it meets.
  const ray = new THREE.Raycaster();
  function seen(v, own) {
    const names = new Set(), solid = [];
    scene.traverse(o => o.isMesh && o.visible && !o.material.transparent && solid.push(o));
    const half = THREE.MathUtils.degToRad(v.info.hfov / 2), hd = THREE.MathUtils.degToRad(v.heading);
    for (let k = 0; k <= 16; k++) {
      const a = hd - half + (2 * half * k) / 16, dir = new THREE.Vector3(Math.sin(a), 0, -Math.cos(a));
      ray.set(new THREE.Vector3(v.x, 1.0, -v.y), dir);
      ray.far = 12;
      const far = ray.intersectObjects(solid, false)[0]?.distance ?? 12;
      for (let d = 0.3; d < far; d += 0.15) {
        const r = roomAt(v.x + Math.sin(a) * d, v.y + Math.cos(a) * d);
        if (r && r.name !== own) names.add(r.name);
      }
    }
    return [...names];
  }

  function plan(room, v) {
    // The DWG round the room, north up: walls, glazing, doors, furniture, and the camera with its view.
    const pts = room.rings.flat().concat([[v.x, v.y]]);
    const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]), pad = 1.2;
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    const S = 1024, s = (S - 40) / Math.max(x1 - x0, y1 - y0);
    const ox = (S - (x1 - x0) * s) / 2, oy = (S - (y1 - y0) * s) / 2;
    const P = ([x, y]) => [ox + (x - x0) * s, S - oy - (y - y0) * s];
    const c = document.createElement("canvas");
    c.width = c.height = S;
    const g = c.getContext("2d");
    const path = rings => { g.beginPath(); for (const r of rings) r.forEach((p, i) => g[i ? "lineTo" : "moveTo"](...P(p))); };
    g.fillStyle = "#ffffff"; g.fillRect(0, 0, S, S);
    g.fillStyle = "#efe6d8";
    for (const f of M.floor.filter(f => f.room === room.name)) { path([f.outer]); g.fill(); }
    g.fillStyle = "#111";
    for (const w of M.walls) { path([w.outer, ...(w.holes || [])]); g.fill("evenodd"); }
    for (const o of M.openings) {
      g.fillStyle = o.kind === "door" ? "#a0704a" : "#4f8fd6";
      path([o.outer]); g.fill();
    }
    g.strokeStyle = "#8a8580"; g.lineWidth = 2;
    for (const f of M.furniture || []) { path([f]); g.closePath(); g.stroke(); }
    g.fillStyle = "#2b2622"; g.font = "600 18px Inter, sans-serif"; g.textAlign = "center";
    for (const l of M.labels || []) g.fillText(l.text, ...P([l.x, l.y]));
    // The view cone, 3 m long.
    const [cx, cy] = P([v.x, v.y]), half = THREE.MathUtils.degToRad(v.info.hfov / 2), hd = THREE.MathUtils.degToRad(v.heading);
    const end = a => P([v.x + Math.sin(a) * 3, v.y + Math.cos(a) * 3]);
    g.fillStyle = "#e0302a33"; g.strokeStyle = "#e0302a"; g.lineWidth = 3;
    g.beginPath(); g.moveTo(cx, cy); g.lineTo(...end(hd - half)); g.lineTo(...end(hd + half)); g.closePath(); g.fill(); g.stroke();
    g.fillStyle = "#e0302a"; g.beginPath(); g.arc(cx, cy, 9, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#2b2622"; g.textAlign = "left"; g.fillText("N ↑", 16, 30);
    return c.toDataURL("image/png");
  }

  function show(i) {
    job.at = i;
    stage.src = i < 0 ? job.view : job.attempts[i].src;
    thumbs.querySelectorAll("figure").forEach((f, k) => f.classList.toggle("on", k - 1 === i));
    sync();
  }
  function drawThumbs() {
    thumbs.innerHTML = "";
    [{ src: job.view, label: "Model view" }, ...job.attempts.map((a, i) => ({ src: a.src, label: `Attempt ${i + 1}` }))].forEach((t, k) => {
      const f = document.createElement("figure");
      f.innerHTML = `<img alt=""><figcaption></figcaption>`;
      f.querySelector("img").src = t.src;
      f.querySelector("figcaption").textContent = t.label;
      f.onclick = () => !job.busy && show(k - 1);
      thumbs.appendChild(f);
    });
  }
  function sync() {
    const on = !!job && !job.busy && job.at >= 0;
    $(".approve").disabled = !on || !name.value.trim();
    $(".revise").disabled = !on || !notes.value.trim();
    list.innerHTML = "";
    for (const c of job?.attempts[job.at]?.comments || []) {  // what led to the attempt shown
      const li = document.createElement("li");
      li.textContent = c;
      list.appendChild(li);
    }
  }
  name.oninput = notes.oninput = sync;

  async function call(path, body, retry = true) {
    const r = await fetch(`api/photospot/${path}`, {
      method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", "X-Photospot-Password": localStorage.photospotPassword || "" },
    });
    if (r.status === 401 && retry) {  // no password yet, or a wrong one: ask, remember it, try again
      const pw = prompt("Password for Generate Photo Spot");
      if (pw === null) throw new Error("A password is needed to generate here.");
      localStorage.photospotPassword = pw;
      return call(path, body, false);
    }
    const out = await r.json().catch(() => ({ error: `${r.status} ${r.statusText}` }));
    if (!r.ok) throw new Error(out.error || r.statusText);
    return out;
  }

  async function run(comment) {
    // A fresh attempt from the view, or (with a comment) a revision of the attempt shown.
    const base = comment ? job.attempts[job.at] : null;
    const comments = [...(base?.comments || []), ...(comment ? [comment] : [])];
    job.busy = true; err.textContent = ""; wait.hidden = false; sync();
    const t0 = performance.now();
    const tick = setInterval(() => (status.textContent = `${comment ? "Revising" : "Generating"} · ${Math.round((performance.now() - t0) / 1000)} s · usually 1–2 min`), 500);
    try {
      const out = await call("generate", { spots: spotsFile, view: job.view, plan: job.plan, ctx: job.ctx, cam: job.cam, comments, previous: base?.draft });
      job.attempts.push({ ...out, comments });
      notes.value = "";
      drawThumbs();
      show(job.attempts.length - 1);
    } catch (e) {
      err.textContent = e.message;
    } finally {
      clearInterval(tick);
      job.busy = false; wait.hidden = true; status.textContent = ""; sync();
    }
  }

  button.onclick = () => {
    if (!isWalking()) return;
    freeMouse();
    const v = view(), r = roomAt(v.x, v.y);
    if (!r) { alert("Stand inside a room to make a photo spot."); return; }
    const caption = captionOf(r.name);
    const [x0, x1] = [Math.min(...r.rings.flat().map(p => p[0])), Math.max(...r.rings.flat().map(p => p[0]))];
    const [y0, y1] = [Math.min(...r.rings.flat().map(p => p[1])), Math.max(...r.rings.flat().map(p => p[1]))];
    job = {
      view: frame(), cam: v.cam, room: r.name, attempts: [], at: -1, busy: false,
      ctx: {
        room: { name: r.name, caption, area: r.area, width: x1 - x0, depth: y1 - y0, finish: r.finish },
        seen: seen(v, r.name).map(n => ({ name: n, caption: captionOf(n) })),
        view: v.info, heights: { ceiling: M.ceiling, doorHead: M.doorHead, sill: M.sill, winHead: M.winHead, sliderHead: M.sliderHead },
      },
    };
    job.plan = plan(r, v);
    name.value = `${caption} ${spotCount(r.name) + 1}`;
    notes.value = "";
    $(".meta").textContent = `${caption} · facing ${v.info.facing} · ${v.info.hfov.toFixed(0)}° lens`;
    drawThumbs();
    show(-1);
    box.hidden = false;
    run();
  };
  $(".revise").onclick = () => run(notes.value.trim());
  $(".cancel").onclick = () => { box.hidden = true; job = null; };
  $(".approve").onclick = async () => {
    const a = job.attempts[job.at];
    job.busy = true; sync();
    try {
      const spot = await call("approve", { spots: spotsFile, draft: a.draft, room: job.room, caption: name.value.trim(), cam: job.cam });
      box.hidden = true; job = null;
      onSaved(spot);
    } catch (e) {
      err.textContent = e.message;
      job.busy = false; sync();
    }
  };

  const api = {
    // Usable in Walk only: that is where a photo spot is stood in.
    sync() {
      button.disabled = !isWalking();
      button.title = button.disabled ? "Switch to Walk and stand where the photo should be taken" : ready;
    },
  };
  return api;
}
