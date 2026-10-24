// Photo spots: stand on a marked spot in Walk and an Enter photo spot button offers the designer's render of
// that view; nothing switches until it is pressed (or the spot is picked in the Photo spots panel).
// Spots live in spots.json (cam = x,y,h,lookX,lookY,lookH,fov in plan metres, the model camera closest
// to the render's angle; a render without one yet is only listed under Renders). The renders in renders/
// are kept out of git; on the live site vercel.json serves renders/ from Vercel Blob (publish_renders.sh).
// Spots approved in Generate Photo Spot (photogen.js, "ai": true) are added while the page is open, as are
// renders edited or deleted under Renders (an edit is a new version: "of" the first, with a "version" number).
// A plan version's file is { extends: "spots.json", replaces: [rooms], spots: [...] }: the main plan's spots
// except in the rooms the version redraws, plus its own.

import { byRoom, shortLabel } from "./renders.js";

const NEAR = 0.4;      // metres from the spot that count as "on it"
const FACING = 20;     // degrees of heading either way that count as facing the view

// A spots file as one list, a version's resolved against the file it extends.
export async function loadSpots(url) {
  const data = await (await fetch(url)).json();
  if (Array.isArray(data)) return data;
  const base = await loadSpots(new URL(data.extends, url));
  return [...base.filter(s => !data.replaces?.includes(s.room)), ...data.spots];
}

export async function photoSpots({ file, THREE, gsap, camera, scene, toWorld, goRoom, FOV, EYE, UP, rooms, isWalking, isBusy }) {
  if (new URLSearchParams(location.search).has("clean")) return { renders: [], add: null, remove: null };  // screenshots of the bare model stay bare
  const base = new URL(".", import.meta.url);
  const place = s => ({
    ...s,
    ...(s.cam && {
      pos: toWorld(s.cam, s.cam[2]),
      target: toWorld(s.cam.slice(3), s.cam[5]),
      heading: Math.atan2(s.cam[3] - s.cam[0], s.cam[4] - s.cam[1]),
    }),
    src: new URL(s.photo, base).href,
  });
  // Plus the spots approved on the live site, which photogen.py keeps in Vercel Blob (none locally or offline),
  // less those deleted there ({id, deleted}: a spot in git that the live site can't remove from the file).
  const approved = await fetch(new URL(`api/photospot/spots?file=${encodeURIComponent(file)}`, base))
    .then(r => (r.ok ? r.json() : []), () => []).catch(() => []);
  const gone = new Set(approved.filter(s => s.deleted).map(s => s.id));
  const all = [...await loadSpots(new URL(file, base)), ...approved].filter(s => !gone.has(s.id)).map(place);
  // One at a time (the local Python server drops bursts); only a definite 404 hides a spot.
  const renders = [];
  for (const s of all) if (await fetch(s.src, { method: "HEAD" }).then(r => r.status !== 404, () => true)) renders.push(s);
  // An edited render is a new version ("of" its first, numbered "version"): Walk stands in the latest of each.
  const first = s => s.of || s.id;
  const latest = () => renders.filter(s => s.cam && !renders.some(o => o !== s && first(o) === first(s) && (o.version || 1) > (s.version || 1)));
  const spots = latest();

  // The render sits behind the UI, whole and centred on a dark backdrop: renders are shot from spots the
  // real rooms don't allow, so they can't line up with the model the way a photo of the model would.
  const style = document.createElement("style");
  style.textContent = `
    #photo { position: fixed; inset: 0; z-index: 1; pointer-events: none; opacity: 0; background: #1c1814; }
    #photo img { width: 100%; height: 100%; object-fit: contain; }
    #photo .tag { position: absolute; right: 14px; bottom: 14px; font-size: 11px; color: #fff; background: #1c181499;
      padding: 6px 10px; border-radius: 999px; letter-spacing: .04em; }
    :is(#photo .exit, #spot-enter) { position: absolute; left: 50%; bottom: 28px; transform: translateX(-50%); pointer-events: auto; cursor: pointer;
      border: 0; border-radius: 999px; padding: 16px 30px; font: inherit; font-size: 16px; font-weight: 600; letter-spacing: .02em; white-space: nowrap;
      background: #fffaf3; color: #2b2622; box-shadow: 0 4px 18px #0006; }
    :is(#photo .exit, #spot-enter):hover { background: #fff; }
    #spot-enter { position: fixed; z-index: 2; }
    #spot-enter .key { font-weight: 400; opacity: .55; margin-left: 6px; }
    @media (max-width: 760px) { :is(#photo .exit, #spot-enter) { bottom: 132px; } #spot-enter .key { display: none; } }`;
  document.head.appendChild(style);
  const overlay = document.createElement("div");
  overlay.id = "photo";
  overlay.innerHTML = `<img alt=""><div class="tag"></div><button class="exit" hidden>✕ Exit photo spot</button>`;
  document.body.appendChild(overlay);
  const img = overlay.querySelector("img"), tag = overlay.querySelector(".tag"), exit = overlay.querySelector(".exit");
  // Standing on a spot only offers it; Enter works too, as a captured mouse can't reach the button.
  const enter = document.createElement("button");
  enter.id = "spot-enter";
  enter.hidden = true;
  enter.innerHTML = `Enter photo spot<span class="key">⏎</span>`;
  document.body.appendChild(enter);
  enter.onclick = () => offer && settle(offer);
  // Moving leaves the photo too, but a spot against a wall or a mouse not yet captured can leave nowhere to move.
  exit.onclick = () => shown && leave();
  addEventListener("keydown", e => {
    if (e.code === "Escape" && shown) leave();
    if (e.code === "Enter" && offer && !shown && !settling) settle(offer);
  });

  // Floor markers: a ring to stand in and a dot on the side you should face.
  const markers = new THREE.Group();
  markers.name = "photo-spot-markers";  // hidden in Generate Photo Spot's screenshot
  const gold = new THREE.MeshBasicMaterial({ color: 0xd9a54a, transparent: true, opacity: 0.85, depthWrite: false });
  function mark(s) {
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.16, 0.2, 40), gold);
    const dot = new THREE.Mesh(new THREE.CircleGeometry(0.05, 20), gold);
    ring.rotation.x = dot.rotation.x = -Math.PI / 2;
    ring.position.set(s.pos.x, 0.02, s.pos.z);
    dot.position.set(s.pos.x + Math.sin(s.heading) * 0.3, 0.02, s.pos.z - Math.cos(s.heading) * 0.3);
    markers.add(ring, dot);
  }
  spots.forEach(mark);
  scene.add(markers);

  // Buttons in the Photo spots panel: glide to a spot like a room button does; the render follows once you are there.
  const bar = document.getElementById("bar"), panel = document.getElementById("spots");
  function fillPanel() {
    panel.innerHTML = "";
    for (const g of byRoom(spots, rooms)) {  // a titled line per room, in the Rooms panel's order
      const line = document.createElement("div"), title = document.createElement("span");
      line.className = "group";
      title.className = "title";
      title.textContent = g.caption;
      line.appendChild(title);
      for (const s of g.items) {
        const b = document.createElement("button");
        b.textContent = shortLabel(s.caption, g.caption);
        b.title = s.caption;
        b.onclick = () => {
          delete bar.dataset.open;
          picked = s;
          goRoom({ room: s.room, caption: s.caption, eye: toWorld(s.cam, EYE), look: toWorld(s.cam.slice(3), EYE - 0.15) });
        };
        line.appendChild(b);
      }
      panel.appendChild(line);
    }
    bar.querySelector("[data-menu=spots]").hidden = !spots.length;
  }
  fillPanel();

  let shown = null, settling = false, offer = null, picked = null;
  const last = { pos: camera.position.clone(), dir: new THREE.Vector3() };
  const dir = new THREE.Vector3();
  const heading = () => { camera.getWorldDirection(dir); return Math.atan2(dir.x, -dir.z); };
  const angleTo = h => Math.abs(THREE.MathUtils.radToDeg(Math.atan2(Math.sin(heading() - h), Math.cos(heading() - h))));
  const planDist = s => Math.hypot(camera.position.x - s.pos.x, camera.position.z - s.pos.z);

  function settle(s) {
    // Step into the render's camera (height, aim, lens), then fade the render in.
    settling = true;
    offerHere(null);
    gsap.killTweensOf([camera, camera.position, overlay]);  // re-entering before leave() has finished
    img.src = s.src;
    tag.textContent = `${s.ai ? "Generated from the model" : "Designer render · not drawn to the DWG"} · move to go back`;
    const from = { pos: camera.position.clone(), aim: camera.position.clone().add(camera.getWorldDirection(new THREE.Vector3())), fov: camera.fov };
    const st = { t: 0 };
    gsap.to(st, {
      t: 1, duration: 0.7, ease: "power2.inOut",
      onUpdate: () => {
        camera.position.lerpVectors(from.pos, s.pos, st.t);
        camera.up.copy(UP);
        camera.lookAt(from.aim.clone().lerp(s.target, st.t));
        camera.fov = THREE.MathUtils.lerp(from.fov, s.cam[6], st.t);
        camera.updateProjectionMatrix();
      },
      onComplete: () => {
        settling = false; shown = s; markers.visible = false; exit.hidden = false;
        last.pos.copy(camera.position); camera.getWorldDirection(last.dir);
        gsap.to(overlay, { opacity: 1, duration: 0.8, ease: "power1.out" });
      },
    });
  }
  function leave() {
    shown = null; exit.hidden = true;
    gsap.to(overlay, { opacity: 0, duration: 0.3 });
    gsap.to(camera.position, { y: EYE, duration: 0.5 });
    gsap.to(camera, { fov: FOV.walk, duration: 0.5, onUpdate: () => camera.updateProjectionMatrix() });
  }

  function offerHere(s) {
    offer = s;
    enter.hidden = !s;
    if (s) enter.title = s.caption;
  }

  (function tick() {
    requestAnimationFrame(tick);
    markers.visible = isWalking() && !shown;
    if (settling) return;
    if (!isWalking() || isBusy()) { if (shown) leave(); return offerHere(null); }
    camera.getWorldDirection(dir);
    const moved = camera.position.distanceTo(last.pos) > 0.005 || dir.angleTo(last.dir) > 0.003;
    last.pos.copy(camera.position); last.dir.copy(dir);
    if (shown) { if (moved) leave(); return; }
    // A spot picked in the panel opens once the glide there ends; one you walk onto is only offered.
    const p = picked;
    picked = null;
    if (p && planDist(p) < NEAR) return settle(p);
    offerHere(spots.find(s => planDist(s) < NEAR && angleTo(s.heading) < FACING) || null);
  })();
  // A spot approved, edited into a new version or deleted just now: on the floor, in the panel and under Renders straight away.
  function refresh() {
    spots.splice(0, spots.length, ...latest());
    markers.clear();
    spots.forEach(mark);
    fillPanel();
    return renders;
  }
  function add(raw) {
    renders.push(place(raw));
    return refresh();
  }
  function remove(id) {
    const i = renders.findIndex(s => s.id === id);
    if (i >= 0) renders.splice(i, 1);
    if (shown?.id === id) leave();
    return refresh();
  }
  return { renders, add, remove };
}
