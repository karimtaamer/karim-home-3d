// Inspiration pictures for a photo edit (Generate Photo Spot's Make an edit, and the Renders screen's Edit): up to
// MAX_INSPO pictures from + (file picker), paste into the comment, or a drop on the form, shown as small thumbs with
// a × to remove. Each is re-encoded through a canvas (long side INSPO_SIDE, JPEG; no EXIF goes out), like Edit AI's
// references, and goes to photogen.py as a data URL. Also the USD → EGP cost line every image call shows.

export const MAX_INSPO = 4, INSPO_SIDE = 1024;
// USD→EGP: CBE rate ~24 Oct 2026 (Edit AI uses the same)
export const USD_EGP = 55.25;
export function egp(usd) { const v = usd * USD_EGP; return `Cost: EGP ${v.toFixed(v < 0.1 ? 3 : 2)}`; }

// Focus a comment box once it is laid out and the mouse is free (Edit AI's fix): focusing while pointer lock is
// still letting go (it ends asynchronously) or before the box shows leaves the caret elsewhere, and the first
// paste went nowhere. shown() says the box is still up when the frame comes.
export function focusWhenReady(area, shown = () => true) {
  const go = () => requestAnimationFrame(() => { if (shown()) area.focus({ preventScroll: true }); });
  if (document.pointerLockElement) document.addEventListener("pointerlockchange", go, { once: true });
  else go();
}

let styled = false;
function style() {
  if (styled) return;
  styled = true;
  const s = document.createElement("style");
  s.textContent = `
    .inspo-thumbs { display: flex; flex-wrap: wrap; gap: 8px; }
    .inspo-thumbs:empty { display: none; }
    .inspo-thumbs span { position: relative; display: block; }
    .inspo-thumbs img { display: block; height: 52px; max-width: 90px; object-fit: cover; border-radius: 6px; box-shadow: 0 0 0 1px #2b262226; }
    .inspo-thumbs b { position: absolute; top: -6px; right: -6px; width: 20px; height: 20px; border-radius: 50%; background: #2b2622; color: #f3eee5;
      font: 600 13px/20px Inter, sans-serif; text-align: center; cursor: pointer; }
    .inspo-drop { outline: 2px dashed #d9a54a; outline-offset: 2px; }`;
  document.head.appendChild(s);
}

async function encode(file) {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  const k = Math.min(1, INSPO_SIDE / Math.max(bmp.width, bmp.height));
  const c = Object.assign(document.createElement("canvas"), { width: Math.round(bmp.width * k), height: Math.round(bmp.height * k) });
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

// form: where pictures can be dropped; button: opens the picker; area: the comment (pasted pictures); thumbs: where
// they show; onChange(list) after each add or remove; onError(message). -> { list(), clear(), set(list) }
export function inspirationPicker({ form, button, area, thumbs, onChange = () => {}, onError = () => {} }) {
  style();
  thumbs.classList.add("inspo-thumbs");
  const input = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", multiple: true, hidden: true });
  form.appendChild(input);
  let refs = [];
  const full = () => refs.length >= MAX_INSPO;
  function draw() {
    thumbs.innerHTML = "";
    refs.forEach((u, i) => {
      const s = document.createElement("span");
      s.innerHTML = `<img alt=""><b title="Remove">×</b>`;
      s.querySelector("img").src = u;
      s.querySelector("b").onclick = () => { refs.splice(i, 1); draw(); };
      thumbs.appendChild(s);
    });
    button.disabled = full();
    button.title = full() ? `Up to ${MAX_INSPO} pictures` : "Add an inspiration picture";
    onChange(refs);
  }
  async function add(files) {
    for (const f of files) {
      if (full()) { onError(`Up to ${MAX_INSPO} pictures per edit.`); break; }
      if (!f.type.startsWith("image/")) continue;
      try { refs.push(await encode(f)); } catch (e) { onError(`Couldn't read that picture (${e.message}).`); }
      draw();
    }
  }
  button.onclick = () => input.click();
  input.onchange = async () => { await add([...input.files]); input.value = ""; };
  // As in Edit AI: text is put in by hand, so it lands on the first paste whatever else is listening (a native paste
  // into a box focused mid-layout went nowhere and had to be pasted twice); a picture alone becomes an inspiration
  // picture (a copy from Word / Notes carries an image of the text too: that one is skipped).
  area.addEventListener("paste", e => {
    const data = e.clipboardData;
    if (!data) return;
    const text = data.getData("text/plain");
    if (text) {
      e.preventDefault();
      area.focus();
      area.setRangeText(text, area.selectionStart, area.selectionEnd, "end");
      area.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    const files = [...data.items].filter(it => it.kind === "file" && it.type.startsWith("image/")).map(it => it.getAsFile()).filter(Boolean);
    if (files.length) { e.preventDefault(); add(files); }
  });
  form.addEventListener("dragover", e => {
    if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
    e.preventDefault();
    form.classList.add("inspo-drop");
  });
  form.addEventListener("dragleave", e => { if (!form.contains(e.relatedTarget)) form.classList.remove("inspo-drop"); });
  form.addEventListener("drop", e => {
    form.classList.remove("inspo-drop");
    if (!e.dataTransfer?.files?.length) return;
    e.preventDefault();
    add([...e.dataTransfer.files]);
  });
  draw();
  return { list: () => [...refs], clear() { refs = []; draw(); }, set(list) { refs = [...list].slice(0, MAX_INSPO); draw(); } };
}
