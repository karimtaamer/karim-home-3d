# Karim's Apartment — 3D model viewer

A Three.js viewer of the flat, built from the architect's DWG floor plan: Dollhouse / Top / Walk views,
a 2D drawing view, a tape measure, the designer's renders as "photo spots", and an in-viewer
**Generate Photo Spot** button that turns a Walk view into a photoreal render with OpenAI.

- Plain static site: no bundler, no npm. Three.js 0.170 comes from jsDelivr through the import map in `index.html`.
- Live on Vercel. Every push to `main` deploys to production (`.github/workflows/deploy.yml`).
- All geometry comes from the DWG. Dimensions are never taken from the renders.

---

## 1. File map

| File | What it is | Edit by hand? |
|---|---|---|
| `index.html` | The whole viewer: scene, views, UI, plan versions (`VERSIONS`), URL params | Yes |
| `model.js` | Walls, openings, rooms, labels and tour grid, as `window.MODEL` | **No**: built by `build_geometry.py` |
| `drawing.json` | DWG linework, text and snap points for the 2D drawing view | **No**: built by `build_drawing.py` |
| `tour.json` | Room seeds, room viewpoints ("stops"), entry point, floor-finish overrides | Yes |
| `furnish.js` | Furniture, joinery and fittings, room by room | Yes |
| `materials.js` | Material library (oak, limewash, stone, …) using the textures in `textures/` | Yes |
| `spots.json` | Photo spots: designer renders plus approved AI renders, each with a camera | Yes (or via Approve) |
| `photogen-brief.json` | Finishes text and material-board swatches for Generate Photo Spot | Yes |
| `spots.js`, `renders.js` | Photo-spot UI in Walk; the Renders gallery screen | Yes |
| `drawing.js`, `measure.js` | 2D drawing view with object snaps; 3D tape measure | Yes |
| `photogen.js` | Generate Photo Spot UI (screenshot, comment, approve) | Yes |
| `photogen.py` | Local dev server **and** the Generate Photo Spot backend (OpenAI calls) | Yes |
| `api/photospot.py`, `photogen_blob.py` | The same backend as a Vercel function, storing files in Vercel Blob | Yes |
| `publish_renders.sh` | Uploads renders, reference copies and the material board to Blob | Yes |
| `build_geometry.py`, `build_drawing.py` | DXF → `model.js` / `drawing.json` | Yes |
| `dwgtool.py` | Inspect a DWG/DXF and render cropped, marked-up PNGs (see `DWG_EDITING.md` §1) | Yes |
| `dwg/main.dxf`, `dwg/bigger-bedroom.dxf`, `dwg/shifted-bedroom.dxf` | The plan drawing for each version: the only build sources (§3) | Yes, see `DWG_EDITING.md` |
| `suite_merge.py` | One plan everywhere except the master suite, taken from another; `--check` compares the versions (§3) | Yes |
| `check_furnish.py` | Runs `furnish.js` in node and compares its key pieces (kitchen appliances, laundry, entrance, coffee corner, guest WC counter, v12 bed/nightstands/cupboard) with the version's DXF; flags > 2 cm (§3) | Yes |
| `*-bigger-bedroom.*`, `*-shifted-bedroom.*` | The other plan versions (see §4) | Same rules as the main files |
| `models/*.glb` | Fixtures made from the renders with Meshy (image-to-3D) | Replace only |
| `textures/` | Poly Haven PBR scans (CC0, see `CREDITS.txt`) | Add only |
| `renders/` | Designer renders and approved AI renders (**git-ignored**, served from Blob live) | Add files |
| `notes/compare/` | Local-only render-vs-model comparison tool (git-ignored) | — |
| `explore.html` | First viewer from the initial commit. Not linked from anywhere; legacy | No |

---

## 2. Running it locally

```sh
python3 photogen.py              # http://127.0.0.1:8000, with Generate Photo Spot
python3 photogen.py --dry-run    # same, but "generates" by echoing the screenshot (no OpenAI credits)
python3 photogen.py 8765         # another port
```

- Any static server also works (`python3 -m http.server`). The Generate Photo Spot button then hides itself.
- Real generation needs `OPENAI_API_KEY` in `.env` (git-ignored). Optional: `OPENAI_IMAGE_MODEL` (default `gpt-image-2`).
- The material board needs Pillow (`pip install pillow`). Without it, generation runs with no board.

**URL parameters** (combine with `&`):

| Param | Effect |
|---|---|
| `?v=bigger-bedroom` | Load a plan version (default: main) |
| `?view=top` / `?view=dollhouse` | Start in that view |
| `?room=master` | Start in Walk at the first room whose caption starts with this |
| `?cam=x,y,h,lookX,lookY,lookH[,fov]` | Stand at an exact camera (plan metres), e.g. to match a render |
| `?clean` | Hide all UI (for screenshots) |
| `?show=drawing` / `?show=renders` | Open the drawing or Renders screen |

---

## 3. Building the model from the DWG

The build scripts need the Python venv at `~/.dwg-tools` (ezdxf, shapely, numpy). `dwg2dxf` comes from
libredwg (`brew install libredwg`).

```sh
P=dwg/main.dxf
~/.dwg-tools/bin/python build_geometry.py $P                  # → model.js (+ reads tour.json)
~/.dwg-tools/bin/python build_drawing.py  $P                  # → drawing.json (needs model.js first)
~/.dwg-tools/bin/python build_geometry.py $P --debug debug.png  # plan image for checking walls
```

**One drawing per version, in `dwg/` (2026-10-23).** These three DXFs are the only build sources: edit them in
place and commit them. They are identical outside the master suite and differ only inside it.
`~/.dwg-tools/bin/python suite_merge.py --check dwg/*.dxf` must print `outside the suite: identical` after any edit.

**Changing the plan, step by step** (anyone with repo access):
1. Pull, then edit the version's file in `dwg/` (AutoCAD, DraftSight, LibreCAD or ezdxf). Save it back **as DXF,
   under the same name**: a DWG, or a file with another name, is not picked up by the build.
2. Master bedroom or master bathroom: edit that version's file only. Any other room: edit one file, copy the change to
   the other two with `suite_merge.py` (below), then run `--check`.
3. Rebuild that version's `model*.js` and `drawing*.json` (commands below and in §4). The viewer reads these, not
   the DXF, so a drawing edit doesn't show until it's rebuilt. Rebuilding needs the `~/.dwg-tools` venv and libredwg
   (above). Without them, push the DXF and ask someone who has them to rebuild.
4. Run `check_furnish.py` after any drawing or `furnish.js` edit, for every version the edit touches (it needs
   node). It exits non-zero when a key piece of furniture is more than 2 cm off the DXF: move the piece in
   `furnish.js` (or fix the drawing), don't loosen the check.
   ```sh
   ~/.dwg-tools/bin/python check_furnish.py dwg/main.dxf --version main
   ~/.dwg-tools/bin/python check_furnish.py dwg/bigger-bedroom.dxf --version bigger-bedroom
   ~/.dwg-tools/bin/python check_furnish.py dwg/shifted-bedroom.dxf --version shifted-bedroom
   ```
5. Commit the DXF and the rebuilt files together, and push.

A new DWG from the designer arrives in `~/Downloads`: convert it, compare it with the matching `dwg/` file and copy
its changes into `dwg/` (see `DWG_EDITING.md` §1). Nothing builds from `~/Downloads`.

**Everything outside the master suite follows the designer's `master-v12.dwg` (all versions).** Each version's DXF is
v12 (with the drafting fixes in §4) with the master suite zone swapped for the version's own: DWG x 190.6 to 196.78, y -117.25 to -112.15, plus the wall faces that run out
of it (`CE0`, the north inner face, and `99`, the corridor's north face). v12 outside the suite, compared with the
older Main DXF (`master-bed186-v6-shoes2-2block-laundry.dxf`, in `~/Downloads` only):
- laundry / guest WC partition 0.166 m east of the 2-block one (laundry 1.88 x 2.30 m, guest WC 2.34 x 2.30 m),
  guest bath 0.90 m deep, guest WC door 0.175 m and WC 0.151 m west, washer and counter moved with the partition,
  laundry window 0.176 m west;
- kitchen: fridge block 0.286 m south, dishwasher in the east run beside it (no room for the old oven tower: the
  3D fridge fills the whole 0.99 m block, see the 2026-10-24 note);
- entrance: one 1.20 x 0.42 m shoe unit (no bench niche) and a 1.20 x 0.40 m bench facing the front door;
- the coffee corner is as before.

Client edit since (2026-10-23, all three files): the guest WC vanity counter `A4A` is 0.60 m deep (front edge moved from
x 204.63 to 204.472, 2.6 cm clear of the door frame) instead of v12's 0.455 m.

**`furnish.js` synced with the DXFs (2026-10-24)**, checked with `check_furnish.py` (all three versions pass). No
drawing change, so no rebuild (`build_geometry.py` on `dwg/shifted-bedroom.dxf` gives the same model geometry).
- Kitchen (all versions): one 0.991 m fridge filling block `wgsfd` (was a 0.65 m fridge plus a 0.32 m tall larder);
  hob and hood 0.924 m wide centred on block `yrtds` (were 0.76 / 0.90 m, 10 cm north); sink 0.877 m wide centred
  on block `wrewwer` (was 0.70 m, 9 cm west). `run()` takes `sinkW` / `hobW`.
- Laundry (all versions): joinery `B02` 2.069 x 0.617 m, y 6.887 to 8.956 (was 2.20 m, to 9.13); counter x 10.937
  to 11.535; stacked washer/dryer x 11.535 to 12.135 (was 5 cm east).
- Entrance bench cushion back on the wall (0.40 m deep, was 0.38).
- Shifted Bedroom suite: bed 2.10 wide x 1.99 long with the headboard inside the DWG outline (was 1.90 x 2.15
  plus a 2.76 m headboard); nightstands 0.47 x 0.52 deep (were 0.48 x 0.42); bathroom-door cupboard 0.87 m (was
  0.81). `bed()` and `nightstand()` take sizes; Main and v9 keep the old ones (only the bed's
  foot rest is 1 cm narrower, to stay inside the bed's width).

**Editing a room outside the suite:** edit it in one file (say `dwg/main.dxf`), copy it into the other two with
`suite_merge.py` (BASE = the edited file, SUITE = OUT = the version to update; each keeps its own suite), check,
then rebuild all three (§3 / §4):

```sh
PY=~/.dwg-tools/bin/python
$PY suite_merge.py dwg/main.dxf dwg/bigger-bedroom.dxf  dwg/bigger-bedroom.dxf
$PY suite_merge.py dwg/main.dxf dwg/shifted-bedroom.dxf dwg/shifted-bedroom.dxf
$PY suite_merge.py --check dwg/*.dxf
```

A merge can reorder the lines in the built model file without changing the geometry. **Editing the suite:** edit
that version's file only.

`build_geometry.py` flags:
- `--out FILE`: model file to write (default `model.js`).
- `--tour FILE`: tour file to read (default `tour.json`).
- `--wall x0,y0,x1,y1`: add a wall face line the DWG left out, in DWG coordinates. Repeatable.
- `--cut x0,y0,x1,y1`: carve a rectangle out of the walls, full height (a niche the DWG draws dashed; the build
  would otherwise fill it as a gap). `furnish.js` fills it above and below. DWG coordinates, repeatable. Run the
  rectangle 2 cm past the wall face into the room: an edge exactly on the face leaves a sliver that closes it.
- `--debug FILE.png`: write a debug render of the plan.

What the scripts rely on in the DWG:
- **Layers:** `1wall` = walls, `Windows`, `3door`, `2furni` / `2 furni` = furniture. Room names come from the drawing's text labels (English or Arabic).
- **Heights are fixed in `build_geometry.py`:** ceiling 2.6 m, door head 2.1 m, window sill 0.9 m, slider head 2.4 m, parapet 1.1 m.
- **Wet rooms** (kitchen, bath, WC, laundry) get tile floors; **outdoor rooms** (terrace, balcony) get decking. Matching is by room name.

**Piers drawn with several back lines** (2026-10-23 fix in `build_geometry.py`): a pier face paired with two
back lines gives two strips with the same span. The corner-square step used to treat them as two pieces meeting
end to end and add a block off each end, widening the entrance pier (to 8.9-10.7) and the dining pier by the
coffee corner (to 18.9-20.1). It now skips same-span pairs, so piers are as wide as the DWG draws them. It also
skips a sliver under 5 cm lying inside a wall at least 0.5 m long: v12's guest WC door jamb tucks 2 cm under the
bath end wall, which used to push 37 cm of wall into the doorway.

> **Don't regenerate `model.js` / `drawing.json` unless the drawing changed.** Diff the output (`git diff --stat`)
> after any rebuild.

**Coordinate frames** (easy to mix up):
- **`tour.json`** uses DWG model-space metres, e.g. `[198.9, -117.75]`.
- **Everything else** uses plan metres in `model.js`'s frame: `furnish.js`, `spots.json` cams, `?cam=`, `drawing.json`. Here x = east, y = north, origin at the plan's corner, e.g. `[5.2, 6.3]`.
- **3D world** is `(x, height, -y)`.

---

## 4. Plan versions

| Version | `?v=` | DWG | Files |
|---|---|---|---|
| Main | *(none)* / `main` | `dwg/main.dxf` (suite from the designer's `master-bed186-v6-shoes2.dwg`, rest from `master-v12.dwg`) | `model.js`, `drawing.json`, `tour.json`, `spots.json` |
| Bigger Master Bedroom | `bigger-bedroom` | `dwg/bigger-bedroom.dxf` (suite from `master-bed-v9.dwg`, rest from `master-v12.dwg`) | `model-bigger-bedroom.js`, `drawing-bigger-bedroom.json`, `tour-bigger-bedroom.json`, `spots-bigger-bedroom.json` |
| Shifted Bedroom | `shifted-bedroom` | `dwg/shifted-bedroom.dxf` (all from `master-v12.dwg`) | `model-shifted-bedroom.js`, `drawing-shifted-bedroom.json`, `tour-shifted-bedroom.json`, `spots-shifted-bedroom.json` |

Bigger Master Bedroom (v9) folds the passage into the master toilet, which **needs façade approval**. Never present it
as settled.

Build the Bigger Master Bedroom version. v9 is missing the bathroom/kitchen wall face line, so `--wall` adds it:

```sh
V=dwg/bigger-bedroom.dxf
~/.dwg-tools/bin/python build_geometry.py $V --out model-bigger-bedroom.js \
    --tour tour-bigger-bedroom.json --wall 196.65,-112.594,196.65,-115.017
~/.dwg-tools/bin/python build_drawing.py $V --model model-bigger-bedroom.js --out drawing-bigger-bedroom.json
```

Shifted Bedroom (v12) moves the master bathroom to the west end, centres the bed on its partition, puts the
wardrobe on the kitchen wall and a desk on the south wall. It also moves the north-façade windows (bedroom 2.18 m,
master bathroom 0.90 m), which **needs façade approval**. Two drafting fixes went into
the v12 drawing (and so into every version): v12's "MM" note (MTEXT on `2furni`) was dropped,
since it would become a room label, and line `801` (corridor wall face under the guest bath) was snapped 2 cm onto
the bath end wall.

```sh
S=dwg/shifted-bedroom.dxf
~/.dwg-tools/bin/python build_geometry.py $S --out model-shifted-bedroom.js --tour tour-shifted-bedroom.json \
    --cut 191.0809,-113.0631,191.2609,-112.7431   # master shower niche stack in the back-wall build-out
~/.dwg-tools/bin/python build_drawing.py $S --model model-shifted-bedroom.js --out drawing-shifted-bedroom.json
```

**Rule: a version may differ from Main only in the master suite.** Any other DWG difference is a mistake to
flag, not to build. When a new DWG changes rooms outside the suite, ask whether it should become the shared base
for every version (as v12 did).

To add a version:
1. Diff its DWG against the main one and confirm only the intended rooms changed.
2. Write `tour-<id>.json` and `spots-<id>.json` that **extend** the main files. Copy `*-bigger-bedroom.json` as a template.
   - Tour: `{ "extends": "tour.json", "seeds": [...], "stops": [...], "doorsAsDrawn": [...] }`. Seeds and stops replace the main ones with the same name or room. `doorsAsDrawn` lists door hinges that open the way the DWG swings them.
   - Spots: `{ "extends": "spots.json", "replaces": [rooms], "spots": [...] }`. Drops the main spots in those rooms and adds its own.
3. Run both build scripts with `--out` / `--tour` / `--model` as above.
4. Add an entry to `VERSIONS` in `index.html`.
5. If furniture differs, branch on `version === "<id>"` in `furnish.js` (see the `bigger-bedroom` and `shifted-bedroom` blocks).

---

## 5. Editing the model by hand

**Furniture: `furnish.js`**
- Each piece is built in its own frame: x across, y up, z out from the wall.
- `item(x, y, facing, build)` puts its back-centre on a plan point, facing `N` / `E` / `S` / `W` into the room.
- Positions come from the DWG furniture layer where the piece is drawn there. Otherwise use standard sizes fitted to the room as the renders show it.
- Load a GLB fixture with `p.model("models/x.glb", material | null, dx, dy, dz, { size | height | width })`:
  - pass a library material for single-material pieces;
  - pass `null` to keep a mixed-material model's own textures.

**Materials: `materials.js`**
- `makeMaterials()` builds the library.
- `size` is the real-world width one texture tile covers. UVs are in metres.
- New texture: drop Poly Haven `_diff` / `_nor` / `_rough` JPGs into `textures/` and add a line to `CREDITS.txt`.

**Floors and rooms: `tour.json`**
- `finishes`: override a room's floor, e.g. `{"KITCHEN": "wood"}`. Values: `wood`, `tile`, `decking`.
- `seeds`: name parts of an open floor shared by several rooms. `"replace": true` moves a drawing label's seed.
- `stops`: the room buttons' camera viewpoints, as `eye` and `look` points.
- After changing seeds or stops, re-run `build_geometry.py` (§3). They are baked into `model.js`.

**Client decisions that override the designer's renders** (don't "fix" these to match a render):
- The kitchen door stays on the east wall, as in the DWG.
- The terrace counter has **no sink** (render 34 still shows one).
- The terrace has **no pergola** (the terrace renders still show one).
- The 2.5 × 4.2 m X-box left of the living room is a void, not part of the flat.
- The shoe cabinet is the unit beside the front door. Nothing goes in the master-suite corridor.
- No scroll-driven tour. Keep the button UI with smooth animated transitions.

---

## 6. Graphics: renders and photo spots

Realism comes from **photo spots**: stand on a marked spot in Walk, press **Enter photo spot**, and a photo of
that view replaces the model.

**Designer renders**
1. Put the image in `renders/` (git-ignored).
2. Add an entry to `spots.json`: `{"id", "room", "caption", "cam": [x, y, h, lookX, lookY, lookH, fov], "photo": "renders/…"}`.
   - Find the cam by opening `?cam=…&clean` and adjusting until the model matches the render.
   - Without `cam`, the render only appears in the Renders gallery.
3. Publish it to the live site:
   ```sh
   sh publish_renders.sh
   ```
   - This uploads each render, a 1024 px reference copy and the material board to the Blob store.
   - Files already online at the same size are skipped.
   - It needs the Vercel CLI, logged in and linked. It pulls `BLOB_READ_WRITE_TOKEN` into `.env.local` if missing.

**Generate Photo Spot** (Walk view button)

- **What gets sent.** `photogen.js` sends three things to `photogen.py`:
  - a screenshot of the model from where you stand;
  - a plan crop of the room drawn from the DWG;
  - the camera numbers.
- **The OpenAI call.** `photogen.py` calls OpenAI image edit (`gpt-image-2`, 1536×1024). Along with the screenshot it sends:
  - the **material board**: the `swatches` in `photogen-brief.json`, each a crop of a render (`box` = left, top, right, bottom as fractions), laid out as one labelled image;
  - a few designer renders of the room as style references, and the earlier renders that show its furniture (see below);
  - the finishes text: `all`, plus `rooms[<ROOM>]` for each room in shot.
- **Revise or approve.**
  - Comment to re-run on the attempt shown.
  - **Approve** copies the image into `renders/` and appends an `"ai": true` spot to the spots file of the plan version on screen.
  - Drafts are kept in `renders/drafts/`.
- **Golden rule:** a generated spot **re-surfaces** the model screenshot and never redesigns it.
  - The screenshot stays image 1, so the angle and every object stay put.
  - Finishes come only from the board and the finish text; furniture designs only from the FURNITURE references below. Don't add layout instructions.
  - Asking it to "draw the designer's version" made it copy a render's layout, with bad results.
- **Furniture references (2026-10-24).** Generations used to invent furniture (e.g. a sofa that isn't Karim's). Now the real pieces come from earlier renders:
  - `furniture` in `photogen-brief.json` lists each piece: `item`, `room` (where it stands), `render` (a file in `renders/` that shows it), `where` (a short description) and optional `rooms` (other rooms it is seen from).
  - For the room and each room in shot, `photogen.py` sends the renders that show their pieces, labelled `FURNITURE - ... shows <where>`, plus that plan version's approved AI spots of those rooms (on Vercel fetched from Blob as they are).
  - A render already sent as a style reference serves both roles. At most `MAX_FURNITURE` (6) extra images, and never more than 16 in all (OpenAI's limit).
  - The geometry lock stays: the VIEW decides what stands where; only the pieces' designs come from the references.
  - **To add a piece:** add a `furniture` entry naming a render already in a `spots*.json` file. Nothing to publish: the whole 1024 px renders are already in Blob.
- `photogen-brief.json` is re-read on every run, so edits to finishes and swatches apply immediately. After changing swatches, run `sh publish_renders.sh` so the live site gets the new board.
- Test UI changes with `--dry-run`. Real runs cost OpenAI credits.

**3D fixtures with Meshy**
- `models/*.glb` were made with Meshy image-to-3D from render crops.
- Use Meshy only when asked. It costs about 20 credits per object on the Pro plan; confirm the cost first.

**Render vs model comparison** (`notes/compare/`, local only)
- `compare.py [id …]` screenshots the model at each view in `views.json` using `?clean&cam=…` and pastes it beside the render as `pair-<id>.jpg`.
- It has hard-coded `/private/tmp/...` paths for the raw renders and the screenshot script. Update them before reuse.

---

## 7. Deploying and secrets

- **Deploy:** push to `main`. GitHub Actions runs `vercel deploy --prod` with the `VERCEL_TOKEN` repo secret.
- **`vercel.json`:**
  - `/renders/*` → the public Blob store `karim-home-3d-photospots`. The live site never serves `renders/` from git.
  - `/api/photospot/<action>` → `api/photospot.py`. Max duration 300 s; `models/`, `textures/`, `notes/`, `dist/` and `renders/` are excluded from the function bundle.
- **Live approved spots** are saved to Blob as `renders/ai-spots/<spots file>/<id>.json`. The page merges them into the spots file it loads.
  - To make one permanent in git, copy its entry into `spots*.json` and its image into `renders/`.
- **Vercel env vars:**
  - `OPENAI_API_KEY`
  - `BLOB_READ_WRITE_TOKEN`
  - optional `PHOTOSPOT_PASSWORD`: if set, the page asks for it once before generate or approve. Currently unset.
- **Local secrets:** `.env` holds `OPENAI_API_KEY`. `.env.local` holds `BLOB_READ_WRITE_TOKEN` (from `vercel env pull`). Git and Vercel ignore both.
- **Ignored files:**
  - `.gitignore`: `renders/`, `dist/`, `notes/compare/`, `.env*`, `.vercel`, `.sc/`, `.gstack/`.
  - `.vercelignore` also drops the build scripts, `notes/`, `.github/` and `publish_renders.sh` from the deploy.
