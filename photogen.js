// Generate a render: in Walk, turn the view you are standing in into a photoreal render with OpenAI
// (photogen.py does the calls, so the key never reaches the page). It sends an untextured clay screenshot of
// the model (the shapes only; the finishes come from the brief and references), a plan of the room drawn from
// the DWG, the view's numbers and a list of the named pieces in frame (so none is dropped); the designer's renders go
// along as style references. Make an edit (a comment typed over the picture, with up to four inspiration pictures
// to copy a look from: inspiration.js) re-runs it on the attempt shown; approve to save it as a photo spot. Each
// attempt shows what it cost (photogen.py's estimate from OpenAI's usage, in EGP).
// The endpoints are photogen.py's: the local server, or api/photospot.py on Vercel; with neither (a plain
// static server) the button stays hidden. If PHOTOSPOT_PASSWORD is set there, the page asks for it once.
// The button first shows a preview of the shot from where you stand, with − / + to frame it: + widens it by
// stepping back along the view (never through a wall or out of the room), then by a wider lens; − undoes
// that and then narrows the lens. The spot is saved with that framing, and named after the furniture piece
// it frames (spotnames.js), or failing that, by photogen.py from the generated image.

import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { GTAOPass } from "three/addons/postprocessing/GTAOPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { framedWord, uniqueName, wordFor } from "./spotnames.js";
import { MAX_INSPO, USD_EGP, egp, focusWhenReady, inspirationPicker } from "./inspiration.js";

const W = 1536, H = 1024;  // the 3:2 frame photogen.py asks for
// The clay VIEW: matte light grey; glass a faint grey-blue at its own opacity; lamps and LED strips a soft white.
const CLAY = 0xd9d9d6, CLAY_GLASS = 0xdde6ea, CLAY_SKY = 0xf4f4f2;
const COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"];
// Framing: steps back of STEP m up to BACK m, CLEAR m short of any wall or tall piece behind; then the frame's
// vertical lens in steps of LENS degrees, from FOV_MIN to FOV_MAX (about 50 to 112 degrees across at 3:2).
const STEP = 0.4, BACK = 3, CLEAR = 0.3, LENS = 6, FOV_MIN = 34, FOV_MAX = 90;

export function createPhotoGen({ THREE, camera, scene, composer, renderer, M, spotsFile, version, furniture, solids, roomAt, captionOf, isWalking, freeMouse, spotNames, onSaved }) {
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
    /* Make an edit: a comment box over the picture, opened from the button, never left standing empty. */
    #photogen-box .edit { position: absolute; left: 22px; right: 22px; bottom: 96px; display: flex; flex-direction: column; gap: 8px; max-width: 560px;
      margin: 0 auto; padding: 12px; border-radius: 14px; background: #f3eee5f2; color: #2b2622; box-shadow: 0 8px 28px #0006; }
    #photogen-box .edit[hidden] { display: none; }
    #photogen-box .edit span { font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase; color: #6d645b; }
    #photogen-box .edit textarea { min-height: 72px; }
    #photogen-box .edit .actions { margin-top: 0; justify-content: flex-end; }
    #photogen-box .edit .actions .attach { margin-right: auto; }
    #photogen-box .edit .hint { font-size: 11.5px; color: #6d645b; }
    #photogen-box .cost { margin: 0; font-size: 12.5px; color: #2b2622; }
    #photogen-box .cost:empty { display: none; }
    #photogen-box ol { margin: 0; padding-left: 18px; font-size: 12px; color: #4a423b; }
    #photogen-box ol:empty { display: none; }
    #photogen-box .err { font-size: 12px; color: #b3412e; }
    #photogen-box .err:empty { display: none; }
    #photogen-box .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; }
    #photogen-box .actions button { border: 0; border-radius: 999px; padding: 9px 15px; cursor: pointer; font: 500 12px Inter, sans-serif;
      letter-spacing: .04em; background: #fffaf3; color: #2b2622; box-shadow: 0 0 0 1px #2b262226 inset; }
    #photogen-box .actions .approve { background: #2b2622; color: #f3eee5; }
    #photogen-box .actions button:disabled { opacity: .4; cursor: default; }
    #photogen-box[data-mode=frame] :is(.gen, .thumbs, .edit), #photogen-box:not([data-mode=frame]) .frame { display: none; }
    #photogen-box .zoom { display: flex; align-items: center; gap: 10px; }
    #photogen-box .zoom button { width: 56px; height: 56px; border: 0; border-radius: 999px; font: 300 30px Inter, sans-serif; line-height: 1; cursor: pointer;
      background: #fffaf3; color: #2b2622; box-shadow: 0 0 0 1px #2b262226 inset; touch-action: manipulation; }
    #photogen-box .zoom button:disabled { opacity: .35; cursor: default; }
    #photogen-box .zoom .lens { flex: 1; font-size: 12px; letter-spacing: .04em; color: #4a423b; text-align: center; }
    #photogen-box .frame.actions button { min-height: 44px; padding: 0 20px; font-size: 13px; }
    @media (max-width: 760px) {
      #photogen-box { grid-template-columns: 1fr; grid-template-rows: auto 1fr; overflow-y: auto; }
      #photogen-box[data-mode=frame] .stage { padding-bottom: 12px; }
      #photogen-box .stage { padding: 12px 12px 92px; }
      #photogen-box .stage > img { max-height: 46vh; }
      #photogen-box .thumbs { left: 12px; right: 12px; }
      #photogen-box .edit { left: 12px; right: 12px; bottom: 92px; }
      #photogen-box .edit textarea { font-size: 16px; }  /* under 16px iOS zooms the page on focus */
    }`;
  document.head.appendChild(style);
  const box = document.createElement("div");
  box.id = "photogen-box";
  box.hidden = true;
  box.innerHTML = `
    <div class="stage"><img alt=""><div class="wait" hidden><div class="spin"></div><div class="status"></div></div><div class="thumbs"></div>
      <form class="edit" hidden><span>Make an edit</span>
        <textarea placeholder="What should change? e.g. warmer evening light, sofa in oatmeal bouclé, no rug"></textarea>
        <div class="inspo"></div>
        <p class="hint">Add up to ${MAX_INSPO} inspiration pictures (+, paste or drop) and say what to take from them. The camera and layout stay.</p>
        <div class="actions"><button type="button" class="attach">+ Picture</button><button type="button" class="edit-cancel">Cancel</button><button class="approve regen">Regenerate</button></div>
      </form></div>
    <aside>
      <h2 class="frame">Frame the shot</h2>
      <p class="frame meta">Your view as the photo will frame it. Press + to take in more of the room.</p>
      <div class="frame zoom"><button class="out-less" aria-label="Zoom in">−</button><span class="lens"></span><button class="out-more" aria-label="Zoom out">+</button></div>
      <div class="frame actions"><button class="approve go">Generate</button><button class="cancel">Cancel</button></div>
      <h2 class="gen">New photo spot</h2>
      <p class="gen meta"></p>
      <label class="gen">Name<input class="name"></label>
      <ol class="gen"></ol>
      <p class="gen cost"></p>
      <div class="err"></div>
      <div class="gen actions">
        <button class="approve save">Approve &amp; save</button>
        <button class="revise">Make an edit</button>
        <button class="cancel">Discard</button>
      </div>
    </aside>`;
  document.body.appendChild(box);
  const $ = s => box.querySelector(s);
  const stage = $(".stage > img"), wait = $(".wait"), status = $(".status"), thumbs = $(".thumbs");
  const name = $(".name"), editor = $(".edit"), notes = $(".edit textarea"), list = $("ol"), err = $(".err"), costLine = $(".cost");
  const inspo = inspirationPicker({ form: editor, button: $(".edit .attach"), area: notes, thumbs: $(".edit .inspo"), onError: m => (err.textContent = m) });
  // Typing here must not walk, measure or step through renders (they all listen on window).
  for (const t of ["keydown", "keyup"]) box.addEventListener(t, e => e.stopPropagation());

  // One sitting: the view it started from, and every attempt so far (each one's comments led to the next).
  let job = null;
  // The framing being chosen: where you stand (pos), the most you can step back (room), how far back and the lens.
  let shot = null;

  function frame(p, clay = false) {
    // The model from pose p (or as you see it), without the photo-spot rings, drawn straight into a 3:2 frame at
    // full size. The clay one goes as the picture to edit, so its angle and every object in it stay put and the
    // model's placeholder finishes don't: only the real ones are painted on. The textured one is the preview.
    const rings = scene.getObjectByName("photo-spot-markers");
    const was = rings?.visible;
    if (rings) rings.visible = false;
    const keep = { pos: camera.position.clone(), fov: camera.fov, aspect: camera.aspect };
    const size = renderer.getSize(new THREE.Vector2()), pr = renderer.getPixelRatio();
    if (p) camera.position.copy(p.pos);
    camera.fov = p ? p.vfov : keep.fov;
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(1); renderer.setSize(W, H, false);
    composer.setPixelRatio(1); composer.setSize(W, H);
    clay ? clayRender() : composer.render();
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    c.getContext("2d").drawImage(renderer.domElement, 0, 0, W, H);
    renderer.setPixelRatio(pr); renderer.setSize(size.x, size.y, false);
    composer.setPixelRatio(pr); composer.setSize(size.x, size.y);
    camera.position.copy(keep.pos); camera.fov = keep.fov; camera.aspect = keep.aspect;
    camera.updateProjectionMatrix();
    if (rings) rings.visible = was;
    return c.toDataURL("image/jpeg", 0.92);  // a PNG this size can pass Vercel's 4.5 MB request limit
  }

  // One render with every mesh in matte clay, then everything put back. A material's clay twin keeps what decides
  // whether and where it shows (opacity and transparency, so faded and hidden pieces stay so; side; the cut
  // plane's clipping) and drops its colour, maps, metal and gloss. Glass keeps its low opacity so windows read
  // as openings; a strong glow (lamp shades, LED strips) turns a soft white so light sources still read; mirrors
  // are clay. The lights turn white and the sky a flat light grey, so nothing tints the clay; the screen's bloom
  // is left out and a soft ambient occlusion (GTAO) shades the corners instead.
  function clayRender() {
    const twins = new Map(), meshes = [], lights = [], bg = scene.background;
    const twin = m => {
      if (!twins.has(m)) {
        const glow = m.emissive && Math.max(m.emissive.r, m.emissive.g, m.emissive.b) * (m.emissiveIntensity ?? 1) >= 0.8;
        twins.set(m, new THREE.MeshStandardMaterial({
          color: m.transparent && m.opacity < 0.3 ? CLAY_GLASS : CLAY, roughness: 1, metalness: 0,
          emissive: glow ? 0xffffff : CLAY, emissiveIntensity: glow ? 1.2 : 0.03,  // a little lift in the shade
          transparent: m.transparent, opacity: m.opacity, depthWrite: m.depthWrite, visible: m.visible,
          side: m.side, clippingPlanes: m.clippingPlanes, clipShadows: m.clipShadows,
        }));
      }
      return twins.get(m);
    };
    let ao = null;
    try {
      scene.traverse(o => {
        if (o.isMesh) {
          meshes.push([o, o.material]);
          o.material = Array.isArray(o.material) ? o.material.map(twin) : twin(o.material);
        } else if (o.isLight) {
          lights.push([o, o.color.clone(), o.groundColor?.clone()]);
          o.color.set(0xffffff);
          o.groundColor?.set(0xffffff);
        }
      });
      scene.background = new THREE.Color(CLAY_SKY);
      ao = new EffectComposer(renderer);
      ao.addPass(new RenderPass(scene, camera));
      ao.addPass(new GTAOPass(scene, camera, W, H));
      ao.addPass(new OutputPass());
      ao.render();
    } finally {
      for (const [o, m] of meshes) o.material = m;
      for (const [o, c, g] of lights) { o.color.copy(c); if (g) o.groundColor.copy(g); }
      scene.background = bg;
      if (ao) { for (const p of ao.passes) p.dispose?.(); ao.dispose(); }
      for (const m of twins.values()) m.dispose();
    }
  }

  // The lens of the screen's middle 3:2: its height is kept unless the screen is narrower than 3:2.
  function screenFov() {
    const tv = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2), a = innerWidth / innerHeight;
    const th = a >= W / H ? tv * (W / H) : tv * a;
    return THREE.MathUtils.radToDeg(2 * Math.atan(th / (W / H)));
  }

  function view(p) {
    const dir = camera.getWorldDirection(new THREE.Vector3());
    const x = p.pos.x, y = -p.pos.z, h = p.pos.y;
    const tv = Math.tan(THREE.MathUtils.degToRad(p.vfov) / 2), th = tv * (W / H);
    const deg = r => THREE.MathUtils.radToDeg(r);
    const heading = (deg(Math.atan2(dir.x, -dir.z)) + 360) % 360, pitch = deg(Math.asin(dir.y));
    return {
      x, y, h, heading,
      cam: [x, y, h, x + dir.x * 3, y - dir.z * 3, h + dir.y * 3, p.vfov],
      info: {
        height: h, facing: COMPASS[Math.round(heading / 45) % 8], hfov: deg(2 * Math.atan(th)), vfov: p.vfov,
        tilt: Math.abs(pitch) < 3 ? "level" : `${Math.abs(pitch).toFixed(0)} degrees ${pitch > 0 ? "up" : "down"}`,
      },
    };
  }

  // How far back along the view you can step: to CLEAR short of the first wall (or tall piece, at eye height)
  // behind, and only while still in the room you stand in (a doorway behind doesn't lead out of it).
  const back = new THREE.Raycaster();
  function room(pos) {
    const dir = camera.getWorldDirection(new THREE.Vector3()).setY(0).normalize().negate();
    const tall = [];
    furniture.traverse(o => o.isMesh && o.visible && tall.push(o));
    let far = BACK + CLEAR;
    for (const [h, list] of [[1.2, solids], [pos.y, solids], [pos.y, tall]]) {
      back.set(new THREE.Vector3(pos.x, h, pos.z), dir);
      back.far = far;
      far = Math.min(far, back.intersectObjects(list, false)[0]?.distance ?? far);
    }
    // The room's edge counts as a wall too (glazing doesn't stop the rays).
    const own = roomAt(pos.x, -pos.z)?.name;
    let edge = 0;
    while (edge < far && roomAt(pos.x + dir.x * (edge + 0.05), -(pos.z + dir.z * (edge + 0.05)))?.name === own) edge += 0.05;
    return { dir, max: Math.max(0, Math.min(BACK, Math.min(far, edge) - CLEAR)) };
  }
  const pose = () => ({ pos: shot.pos.clone().addScaledVector(shot.room.dir, shot.back), vfov: shot.vfov });
  function reframe() {
    stage.src = frame(pose());
    const hfov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(shot.vfov) / 2) * (W / H)));
    $(".lens").textContent = `${hfov.toFixed(0)}° lens${shot.back > 0.01 ? ` · ${shot.back.toFixed(1)} m back` : ""}`;
    $(".out-more").disabled = shot.back >= shot.room.max - 0.01 && shot.vfov >= FOV_MAX;
    $(".out-less").disabled = shot.back <= 0.01 && shot.vfov <= shot.min;
  }
  // + steps back while there's room, then widens the lens; − narrows back to where you started, then steps in, then zooms.
  function zoomOut() {
    if (shot.back < shot.room.max - 0.01) shot.back = Math.min(shot.room.max, shot.back + STEP);
    else shot.vfov = Math.min(FOV_MAX, shot.vfov + LENS);
    reframe();
  }
  function zoomIn() {
    if (shot.vfov > shot.start + 0.01) shot.vfov = Math.max(shot.start, shot.vfov - LENS);
    else if (shot.back > 0.01) shot.back = Math.max(0, shot.back - STEP);
    else shot.vfov = Math.max(shot.min, shot.vfov - LENS);
    reframe();
  }
  $(".out-more").onclick = zoomOut;
  $(".out-less").onclick = zoomIn;
  $(".stage").addEventListener("wheel", e => {
    if (box.dataset.mode !== "frame") return;
    e.preventDefault();
    (e.deltaY > 0 ? zoomOut : zoomIn)();
  }, { passive: false });

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

  // The room the shot is of, which need not be the one you stand in (from the dining, looking into the
  // reception, it is the reception): a grid of rays through the framed lens, each landing on the first opaque
  // thing it meets (floor, wall, furniture, ceiling); the room it lands in (stepped back a little off the face,
  // as a wall belongs to the side it is seen from) scores the ray's weight: how far it went (the floor at your
  // feet fills the frame's foot but is little of what is shown), falling off from the frame's middle.
  // The room with the most wins; nothing found, or a tie with where you stand, keeps that.
  function viewedRoom(p, own) {
    const eye = camera.clone();
    eye.position.copy(p.pos); eye.fov = p.vfov; eye.aspect = W / H;
    eye.updateProjectionMatrix(); eye.updateMatrixWorld();
    const solid = [];
    scene.traverse(o => o.isMesh && o.visible && !o.material.transparent && solid.push(o));
    const score = new Map();
    for (let i = 0; i <= 16; i++) for (let j = 0; j <= 10; j++) {
      const u = -1 + i / 8, w = -1 + j / 5;
      ray.setFromCamera(new THREE.Vector2(u, w), eye);
      ray.far = 12;
      const hit = ray.intersectObjects(solid, false)[0];
      if (!hit) continue;
      let r = null;
      for (let d = hit.distance - 0.05; !r && d > hit.distance - 0.5 && d > 0; d -= 0.1) {
        const q = ray.ray.at(d, new THREE.Vector3());
        r = roomAt(q.x, -q.z);
      }
      if (r) score.set(r.name, { r, s: (score.get(r.name)?.s || 0) + hit.distance * Math.exp(-(u * u + w * w) / 0.72) });
    }
    let best = { r: own, s: score.get(own.name)?.s || 0 };
    for (const x of score.values()) if (x.s > best.s) best = x;
    return best.r;
  }

  // What the VIEW shows, by name, so the image model knows what each grey shape is and keeps it (a grey block on a
  // counter is a water dispenser, not a spare spot for a prop): rays on a grid across the framed lens, each to the
  // first wall or piece it meets (glass is looked through). A hit is named by the nearest label up its parents
  // (furnish.js label() / named(): "water dispenser", "potted plant"), else by its piece's spotnames.js word; a named
  // part of a piece with its own word says what it sits on. -> ["two-tap countertop water dispenser (on the coffee
  // bar; left, middle height)", ...], the most seen first.
  function inventory(p) {
    const eye = camera.clone();
    eye.position.copy(p.pos); eye.fov = p.vfov; eye.aspect = W / H;
    eye.updateProjectionMatrix(); eye.updateMatrixWorld();
    const view = new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(eye.projectionMatrix, eye.matrixWorldInverse));
    const meshes = [];
    furniture.traverseVisible(o => o.isMesh && view.intersectsObject(o) && meshes.push(o));
    const walls = new Set(solids), targets = [...solids.filter(o => view.intersectsObject(o)), ...meshes];
    const found = new Map();  // labelled object -> { what, on, n, u, w }
    for (let i = 0; i < 40; i++) for (let j = 0; j < 27; j++) {
      const u = -1 + (2 * i + 1) / 40, w = -1 + (2 * j + 1) / 27;
      ray.setFromCamera(new THREE.Vector2(u, w), eye);
      ray.far = 15;
      for (const hit of ray.intersectObjects(targets, false)) {
        if (walls.has(hit.object)) break;
        const m = hit.object.material;
        if ([m].flat().every(x => x.transparent && x.opacity < 0.3)) continue;  // glass: look through it
        let o = hit.object, own = null;
        while (o.parent && o.parent !== furniture) { if (!own && o.userData.label) own = o; o = o.parent; }
        if (o.parent !== furniture) break;
        if (!own && o.userData.label) own = o;
        const word = wordFor(o, version), what = own ? own.userData.label : word;
        if (what) {
          const on = own && own !== o && word !== what ? word : null;
          const k = own || o, f = found.get(k) || { what, on, n: 0, u: 0, w: 0 };
          f.n++; f.u += u; f.w += w;
          found.set(k, f);
        }
        break;
      }
    }
    const where = f => {
      const u = f.u / f.n, w = f.w / f.n;
      return `${u < -0.33 ? "left" : u > 0.33 ? "right" : "centre"}, ${w < -0.33 ? "low" : w > 0.33 ? "high" : "middle height"}`;
    };
    // Several of a kind (chairs round a table) make one line with each one's place.
    const lines = new Map();
    for (const f of [...found.values()].sort((a, b) => b.n - a.n)) {
      const key = `${f.what}|${f.on}`, l = lines.get(key) || { ...f, at: [] };
      l.at.push(where(f));
      lines.set(key, l);
    }
    return [...lines.values()].slice(0, 24).map(l =>
      `${l.at.length > 1 ? `${l.at.length} x ` : ""}${l.what} (${l.on ? `on the ${l.on}; ` : ""}${[...new Set(l.at)].join("; ")})`);
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

  // What thumbnail k shows: -1 the model view, -2 the clay view (the one sent), then the attempts from 0.
  const atOf = k => (k < 2 ? -1 - k : k - 2);
  function show(i) {
    job.at = i;
    stage.src = i === -2 ? job.clay : i < 0 ? job.view : job.attempts[i].src;
    thumbs.querySelectorAll("figure").forEach((f, k) => f.classList.toggle("on", atOf(k) === i));
    sync();
  }
  function drawThumbs() {
    thumbs.innerHTML = "";
    [{ src: job.view, label: "Model view" }, { src: job.clay, label: "Clay view (sent)" },
      ...job.attempts.map((a, i) => ({ src: a.src, label: `Attempt ${i + 1}` }))].forEach((t, k) => {
      const f = document.createElement("figure");
      f.innerHTML = `<img alt=""><figcaption></figcaption>`;
      f.querySelector("img").src = t.src;
      f.querySelector("figcaption").textContent = t.label;
      f.onclick = () => !job.busy && show(atOf(k));
      thumbs.appendChild(f);
    });
  }
  function sync() {
    const on = !!job && !job.busy && job.at >= 0;
    $(".save").disabled = !on || !name.value.trim();
    $(".revise").disabled = !on;
    $(".regen").disabled = !on || !notes.value.trim();
    list.innerHTML = "";
    const a = job?.attempts[job.at];
    for (const c of a?.comments || []) {  // what led to the attempt shown
      const li = document.createElement("li");
      li.textContent = c;
      list.appendChild(li);
    }
    // What the attempt shown cost, and the sitting so far.
    const paid = (job?.attempts || []).filter(x => x.usd != null), total = paid.reduce((t, x) => t + x.usd, 0);
    costLine.textContent = !a ? "" : [
      `Attempt ${job.at + 1}`,
      a.inspo ? `${a.inspo} inspiration picture${a.inspo > 1 ? "s" : ""}` : "",
      a.usd != null ? egp(a.usd) : "Cost not reported",
      job.attempts.length > 1 && paid.length ? `all attempts EGP ${(total * USD_EGP).toFixed(2)}` : "",
    ].filter(Boolean).join(" · ");
  }
  notes.oninput = sync;
  name.oninput = () => { if (job) job.named = true; sync(); };  // a name typed in is never replaced

  async function call(path, body, retry = true) {
    const r = await fetch(`api/photospot/${path}`, {
      method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", "X-Photospot-Password": localStorage.photospotPassword || "" },
    });
    if (r.status === 401 && retry) {  // no password yet, or a wrong one: ask, remember it, try again
      const pw = prompt("Password for Generate a render");
      if (pw === null) throw new Error("A password is needed to generate here.");
      localStorage.photospotPassword = pw;
      return call(path, body, false);
    }
    const out = await r.json().catch(() => ({ error: `${r.status} ${r.statusText}` }));
    if (!r.ok) throw new Error(out.error || r.statusText);
    return out;
  }

  async function run(comment, refs = []) {
    // A fresh attempt from the view, or (with a comment, and any inspiration pictures) a revision of the attempt shown.
    const base = comment ? job.attempts[job.at] : null;
    const comments = [...(base?.comments || []), ...(comment ? [comment] : [])];
    job.busy = true; err.textContent = ""; wait.hidden = false; sync();
    const t0 = performance.now();
    const tick = setInterval(() => (status.textContent = `${comment ? "Revising" : "Generating"} · ${Math.round((performance.now() - t0) / 1000)} s · usually 1–2 min`), 500);
    try {
      const out = await call("generate", { spots: spotsFile, view: job.clay, plan: job.plan, ctx: job.ctx, cam: job.cam, comments, previous: base?.draft, refs });
      job.attempts.push({ ...out, comments, inspo: refs.length });
      notes.value = ""; inspo.clear();
      drawThumbs();
      show(job.attempts.length - 1);
      // No named piece in frame: name it from the picture (a cheap vision call), once, unless a name was typed.
      if (!job.word && !job.named) {
        const sitting = job, { word } = await call("name", { draft: out.draft }).catch(() => ({}));
        sitting.word = word;
        if (word && job === sitting && !job.named) name.value = uniqueName(job.caption, word, spotNames(job.room));
      }
    } catch (e) {
      err.textContent = e.message;
    } finally {
      clearInterval(tick);
      if (job) job.busy = false;  // unless discarded meanwhile
      wait.hidden = true; status.textContent = ""; sync();
    }
  }

  // First the preview, framed with − / +; Generate starts the sitting from the framing chosen.
  button.onclick = () => {
    if (!isWalking()) return;
    freeMouse();
    const pos = camera.position.clone();
    if (!roomAt(pos.x, -pos.z)) { alert("Stand inside a room to make a photo spot."); return; }
    const start = screenFov();
    shot = { pos, room: room(pos), back: 0, vfov: start, start, min: Math.min(FOV_MIN, start) };
    job = null;
    err.textContent = "";
    box.dataset.mode = "frame";
    box.hidden = false;
    reframe();
  };
  $(".go").onclick = () => {
    // Filed under the room the shot is of; where you stand only goes into the meta line and the rooms in shot.
    const p = pose(), v = view(p), here = roomAt(v.x, v.y), r = viewedRoom(p, here);
    const caption = captionOf(r.name);
    const [x0, x1] = [Math.min(...r.rings.flat().map(p => p[0])), Math.max(...r.rings.flat().map(p => p[0]))];
    const [y0, y1] = [Math.min(...r.rings.flat().map(p => p[1])), Math.max(...r.rings.flat().map(p => p[1]))];
    // The piece in frame names the spot, seen from the framed camera.
    const eye = camera.clone();
    eye.position.copy(p.pos);
    const word = framedWord({ THREE, camera: eye, root: furniture, solids, version, hfov: v.info.hfov, vfov: v.info.vfov });
    job = {
      view: frame(p), clay: frame(p, true), cam: v.cam, room: r.name, caption, word, named: false, attempts: [], at: -1, busy: false,
      ctx: {
        room: { name: r.name, caption, area: r.area, width: x1 - x0, depth: y1 - y0, finish: r.finish },
        seen: [...new Set([here.name, ...seen(v, r.name)])].filter(n => n !== r.name).map(n => ({ name: n, caption: captionOf(n) })),
        view: v.info, heights: { ceiling: M.ceiling, doorHead: M.doorHead, sill: M.sill, winHead: M.winHead, sliderHead: M.sliderHead },
        inventory: inventory(p),
      },
    };
    job.plan = plan(r, v);
    // Until the piece is known (from the picture, after the first attempt), a numbered name stands in.
    name.value = uniqueName(caption, word || "view", spotNames(r.name));
    notes.value = ""; inspo.clear();
    editor.hidden = true;
    $(".gen.meta").textContent = `${caption}${here.name !== r.name ? ` (from ${captionOf(here.name)})` : ""} · facing ${v.info.facing} · ${v.info.hfov.toFixed(0)}° lens`;
    box.dataset.mode = "generate";
    drawThumbs();
    show(-2);
    run();
  };
  // Make an edit opens the comment box over the picture; its comment re-runs the attempt shown.
  $(".revise").onclick = () => { editor.hidden = false; sync(); focusWhenReady(notes, () => !box.hidden && !editor.hidden); };
  $(".edit-cancel").onclick = () => { editor.hidden = true; };
  editor.onsubmit = e => {
    e.preventDefault();
    const comment = notes.value.trim();
    if (!comment || $(".regen").disabled) return;
    editor.hidden = true;
    run(comment, inspo.list());
  };
  box.querySelectorAll(".cancel").forEach(b => (b.onclick = () => { box.hidden = true; editor.hidden = true; inspo.clear(); job = null; shot = null; }));
  $(".save").onclick = async () => {
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
    call,  // the Renders screen's edit and delete go through the same password
    ready: () => !!ready,
    // Usable in Walk only: that is where a photo spot is stood in.
    sync() {
      button.disabled = !isWalking();
      button.title = button.disabled ? "Switch to Walk and stand where the photo should be taken" : ready;
    },
  };
  return api;
}
