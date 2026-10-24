# Karim's Apartment — 3D model viewer

A Three.js viewer of the flat, built from the architect's DWG floor plan: Walk (the default) and Top views,
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
| `interact.js` | Openable cabinets in Walk: the soft "tap me" cue and the door animation (§5) | Yes |
| `photogen.js` | Generate Photo Spot UI (framing preview, screenshot, comment, approve) | Yes |
| `spotnames.js` | Auto-names for new photo spots: furniture word per `furnish.js` piece, by its plan point | Yes (when a piece moves) |
| `photogen.py` | Local dev server **and** the Generate Photo Spot backend (OpenAI calls) | Yes |
| `api/photospot.py`, `photogen_blob.py` | The same backend as a Vercel function, storing files in Vercel Blob | Yes |
| `publish_renders.sh` | Uploads renders, reference copies and the material board to Blob | Yes |
| `build_geometry.py`, `build_drawing.py` | DXF → `model.js` / `drawing.json` | Yes |
| `dwgtool.py` | Inspect a DWG/DXF and render cropped, marked-up PNGs (see `DWG_EDITING.md` §1) | Yes |
| `dwg/main.dxf`, `dwg/bigger-bedroom.dxf`, `dwg/shifted-bedroom.dxf`, `dwg/naghams-changes.dxf` | The plan drawing for each version: the only build sources (§3) | Yes, see `DWG_EDITING.md` |
| `suite_merge.py` | One plan everywhere except the master suite, taken from another; `--check` compares the versions (§3) | Yes |
| `check_furnish.py` | Runs `furnish.js` in node and compares its key pieces (kitchen appliances, laundry, entrance, coffee corner, guest WC counter, v12 bed/nightstands/cupboard) with the version's DXF; flags > 2 cm (§3) | Yes |
| `*-bigger-bedroom.*`, `*-shifted-bedroom.*`, `*-naghams-changes.*`, `*-as-built.*` | The other plan versions (see §4); `dwg/as-built.dxf` is the survey of the empty flat | Same rules as the main files |
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
| (none) | Start in Walk inside the reception |
| `?view=top` | Start in the Top view (`?view=dollhouse`, from before Dollhouse was removed, starts as with no param) |
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

**One drawing per version, in `dwg/` (2026-10-23).** These DXFs are the only build sources: edit them in
place and commit them. They are identical outside the master suite and differ only inside it.
`~/.dwg-tools/bin/python suite_merge.py --check dwg/*.dxf` must print `outside the suite: identical` after any edit
(it skips `dwg/as-built.dxf`, the survey of the flat as it stands, §4).
**Exception (2026-10-24):** `dwg/naghams-changes.dxf` also differs in the kitchen: the whole south run (DWG x 196.88
west wall to 198.97) is floor-to-ceiling joinery, 60 deep: a 119.2 cm pantry from the west wall, then a 90 cm appliance
tower at the east end, in place of counter, under-counter unit and wall cabinets. So `--check` lists those 15 kitchen
entities for that file; any other difference is still an error. A room edit copied in with `suite_merge.py` must keep
that kitchen run.

**Changing the plan, step by step** (anyone with repo access):
1. Pull, then edit the version's file in `dwg/` (AutoCAD, DraftSight, LibreCAD or ezdxf). Save it back **as DXF,
   under the same name**: a DWG, or a file with another name, is not picked up by the build.
2. Master bedroom or master bathroom: edit that version's file only. Any other room: edit one file, copy the change to
   the others with `suite_merge.py` (below), then run `--check`.
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
   ~/.dwg-tools/bin/python check_furnish.py dwg/naghams-changes.dxf --version naghams-changes
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

Client edit (2026-10-24, all three files): the entrance shoe unit is an L-shaped built-in (`2furni` polyline `1243`): a
0.44 x 0.26 m piece on the column's face and a 1.09 x 0.42 m console beside it, now running to the side wall (east edge
DWG x 201.4240 to 201.7536, was 33 cm short). `furnish.js` builds it as the entrance render's console (oak frame, LED
cove, seat on a drawer, lit shoe shelf, mirror and hooks) beside a cream cabinet with oak fluting.

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

**Editing a room outside the suite:** edit it in one file (say `dwg/main.dxf`), copy it into the others with
`suite_merge.py` (BASE = the edited file, SUITE = OUT = the version to update; each keeps its own suite), check,
then rebuild all of them (§3 / §4):

```sh
PY=~/.dwg-tools/bin/python
$PY suite_merge.py dwg/main.dxf dwg/bigger-bedroom.dxf  dwg/bigger-bedroom.dxf
$PY suite_merge.py dwg/main.dxf dwg/shifted-bedroom.dxf dwg/shifted-bedroom.dxf
$PY suite_merge.py dwg/main.dxf dwg/naghams-changes.dxf dwg/naghams-changes.dxf
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
- `--window x,y,sill,head[,frosted]`: give the one window whose opening holds DWG point x,y its own sill and head
  (and frosted glass); its depth is read from the wall at its middle. Every other window keeps the fixed heights,
  and a model built without the flag is unchanged. `index.html` / `explore.html` read `sill`, `head`, `frosted`
  on that opening. Repeatable.
- `--debug FILE.png`: write a debug render of the plan.

What the scripts rely on in the DWG:
- **Layers:** `1wall` = walls, `Windows`, `3door`, `2furni` / `2 furni` = furniture. Room names come from the drawing's text labels (English or Arabic).
- **Heights are fixed in `build_geometry.py`:** ceiling 2.6 m, door head 2.1 m, window sill 0.9 m, slider head 2.4 m, parapet 1.1 m (one window can override its sill/head with `--window`).
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
| Nagham's Changes | `naghams-changes` | `dwg/naghams-changes.dxf` (a copy of `dwg/shifted-bedroom.dxf`, 2026-10-24) | `model-naghams-changes.js`, `drawing-naghams-changes.json`, `tour-naghams-changes.json`, `spots-naghams-changes.json` |
| Kareem's Changes | `kareems-changes` | `dwg/kareems-changes.dxf` (a copy of `dwg/naghams-changes.dxf`, 2026-10-25) | `model-kareems-changes.js`, `drawing-kareems-changes.json`, `tour-kareems-changes.json`, `spots-kareems-changes.json` |
| As-built | `as-built` | `dwg/as-built.dxf` (the surveyor's `as-built-original.dwg`, Sep 2026) | `model-as-built.js`, `drawing-as-built.json`, `tour-as-built.json`, `spots-as-built.json` (empty) |

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
    --cut 191.0809,-112.944,191.2609,-112.724   # master shower niche stack in the back-wall build-out
~/.dwg-tools/bin/python build_drawing.py $S --model model-shifted-bedroom.js --out drawing-shifted-bedroom.json
```

Nagham's Changes (2026-10-24) starts as an exact copy of Shifted Bedroom: the DXF is a byte copy, the tour, spots and
`drawing-naghams-changes.json` are copies of Shifted Bedroom's, and `furnish.js`, `spotnames.js` and `check_furnish.py`
treat it like `shifted-bedroom`. Change its suite in `dwg/naghams-changes.dxf` only, then split its `furnish.js` branch
from Shifted Bedroom's where the furniture differs.

Kareem's Changes (2026-10-25) starts as an exact copy of Nagham's Changes: the DXF, model, drawing, tour and spots
are byte copies of Nagham's (comments updated), and `furnish.js`, `spotnames.js` and `check_furnish.py` treat it like
`naghams-changes`. Change it in `dwg/kareems-changes.dxf` only, then split its `furnish.js` branch from Nagham's where
the furniture differs. Rebuild it like Nagham's below with `N=dwg/kareems-changes.dxf` and the `-kareems-changes` outputs
(same `--wall` / `--cut` / `--window` flags).

Kareem's en-suite (2026-10-25): the bathroom door (frame, leaf, swing, wall ends) sits 0.16 further east, hinge DWG x
192.4871, leaving a 5 cm wall nib to the partition (was 21) and the open leaf 11 cm off it; `doorsAsDrawn` follows. The
vanity runs the whole west wall, south wall face to the shower partition (1.185, DWG y -115.4781 to -114.2931), 0.60
deep (`2furni` outline `1336`), with the basin block re-centred on it (y -114.8856). Over it, in place of the backlit
mirror, a mirrored medicine cabinet (dashed `2furni` outline, 0.80 x 0.30 on the 2 cm battens): two leaves hinged at
the outer edges, 25 cm clear inside, three glass shelves, bottom 1.32 / top 2.07, an LED halo on the battens and a
strip under it. `furnish.js` (`vanity(…, d, above)` and `medCabinet`), `spotnames.js` and `check_furnish.py` (master
vanity, medicine cabinet) follow it.

Its en-suite (2026-10-24) is rearranged to Nagham's sketch: the bathroom/bedroom partition (the headboard wall, still
0.11) sits 14 cm further east (bathroom-side face DWG x 192.5965), and the bed and bedside tables moved with it (bed
foot 1.40 from the wardrobe front). Shower in the north-west corner, 0.84 wide inside x 1.29 deep, in front of a
0.21 solid build-out on the north wall (DWG y -112.8031, `1wall`) that buries the column (its old faces kept dashed)
and carries the concealed mixer, rain arm and hand shower (outlet at the west end, in front of the column). A
`--wall` face (hidden, DWG x 190.9609) closes the west wall up to the facade behind it. A 0.20 solid partition
(stone-lined in the build) between the shower and the basin, with one wide niche in its shower face: cut 0.70 wide x
0.15 deep rough (dashed, centred on the shower, 0.07 solid each side, 0.05 left behind it on the vanity side),
finished 0.67 x 0.135 in porcelain, three 4 cm porcelain slab shelves with 25.5 cm clear (floors 0.895 / 1.19 /
1.485, top 1.74) and warm LEDs in `furnish.js`, carved by `--cut`. Fold-up teak seat on the west wall (dashed, open
outline): 0.45 along the wall from 0.05 off the partition, 0.35 deep, top 0.45, 0.49 clear to the glass line. A 2 cm
clear glass panel (with its channel), 0.69 long from the build-out face to 0.90 from the north wall, on its own
`Glass` layer (colour 4, not `Windows`, so the build doesn't read it as a window), leaving a 0.60 walk-in gap. WC
bay to its east on the north wall, 0.776 wide: a concealed-cistern build-out 0.30 deep across the bay (`2furni`; 1.12
high in 3D, porcelain-clad with a top ledge and a flush plate) and a wall-hung pan 0.54 long, centred, front 0.84
from the north wall. The en-suite window is WC-only: 0.60 x 0.60, DWG x 191.9087-192.5087 (0.088 of wall to the
glass and to the partition, centred on the WC), sill 1.50, head 2.10, frosted, the shower side solid; `--window`
gives it those heights in 3D, and `furnish.js` clads its wall face in porcelain from the 1.12 cistern ledge to the
sill. Vanity 1.153 long (to the partition), 0.51 deep, DWG y -115.4463 to -114.2931; bowl, tap spout and backlit
mirror centred on it at y -114.8697. Towel radiator on the east wall at DWG y -113.725 to -114.175 (0.29 south of
the pan front), with three champagne-bronze towel hooks at 1.30 (y -114.33 / -114.48 / -114.63) on the 0.61 of
plain wall between it and the open door leaf. Bathroom door and the room's other walls are
unchanged from Shifted Bedroom. `furnish.js` (the `NC` branch in the shared block) and `spotnames.js` follow it.

```sh
N=dwg/naghams-changes.dxf
# --wall: west wall face hidden behind the shower build-out; --cut: shower niche in the shower/basin partition;
# --window: the WC window's 1.50 sill, 2.10 head and frosted glass
~/.dwg-tools/bin/python build_geometry.py $N --out model-naghams-changes.js --tour tour-naghams-changes.json \
    --wall 190.9609,-112.8031,190.9609,-112.3428 --cut 191.0309,-114.2431,191.7309,-114.0731 \
    --window 192.2087,-112.47,1.5,2.1,frosted
~/.dwg-tools/bin/python build_drawing.py $N --model model-naghams-changes.js --out drawing-naghams-changes.json
```

As-built is the flat as it stands today, empty: the surveyor's "AS BUILT PLAN" (2026-10-24). It is a record, not a
design, so the master-suite rule below doesn't apply to it and `suite_merge.py --check` skips `dwg/as-built*.dxf`.
`furnish()` returns before building anything for it (no furniture, joinery or fittings), and `spots-as-built.json`
is an empty list (no photo spots, no Renders tab). `dwg/as-built.dxf` came from the DWG through ODA File Converter
(DXF 2018), cut down to the as-built plan (the DWG also holds an old furnished plan, the title block and a logo;
the survey's `_DIM` dimensions are kept and show in the Drawing tab) and moved by (-0.054080, -87.082745) m onto
the design frame, so its walls line up with Main's and the model origin is the same. Layer names were already the
build's (`1wall`, `Windows`, `3door`). It has no room names, so `tour-as-built.json` seeds every room.

```sh
A=dwg/as-built.dxf
~/.dwg-tools/bin/python build_geometry.py $A --out model-as-built.js --tour tour-as-built.json
~/.dwg-tools/bin/python build_drawing.py $A --model model-as-built.js --out drawing-as-built.json
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

**Quick changes.** If the ask is a small furniture or fitting tweak (swap a mirror for a cabinet, move one piece a few centimetres, change a material), edit `furnish.js` for that piece and — when it is drawn on the plan — the matching `2furni` outline in that version's DXF only. Then run `check_furnish.py` for the version(s) you touched. Rebuild model/drawing only when the DXF walls or openings changed. Leave the full rebuild + multi-version screenshot pass for real layout work (walls, doors, room moves).

**Furniture: `furnish.js`**
- Each piece is built in its own frame: x across, y up, z out from the wall.
- `item(x, y, facing, build)` puts its back-centre on a plan point, facing `N` / `E` / `S` / `W` into the room.
- Positions come from the DWG furniture layer where the piece is drawn there. Otherwise use standard sizes fitted to the room as the renders show it.
- Load a GLB fixture with `p.model("models/x.glb", material | null, dx, dy, dz, { size | height | width })`:
  - pass a library material for single-material pieces;
  - pass `null` to keep a mixed-material model's own textures.

**Openable cabinets: `interact.js`**
- In Walk, standing within 1.8 m (in plan) of a cabinet and looking at it shows a soft glowing circle on it. Tap / click it, or press E, to open or close it. With the mouse captured, a click opens it too.
- Make a piece openable by building it in its own Group, with each door or drawer front in its own child Group (pivot on the hinge). Then mark the Group with data:
  ```js
  g.userData.openable = { id: "pantry", label: "Pantry", anchor: new THREE.Vector3(0, 1.2, 0.65),  // cue spot, in g's frame
    leaves: [{ obj: leftDoor, axis: "y", open: -100 * Math.PI / 180 }, { obj: drawer, slide: new THREE.Vector3(0, 0, 0.4) }],
    reach: 1.8, duration: 0.6 };
  ```
  - A hinged leaf turns `open` radians about `axis`. Check the sign: the free edge must swing out (+z), not into the wall.
  - A sliding leaf moves by `slide`, in its parent's frame.
  - Leaves start from their built (closed) pose.
- `medCabinet` in `furnish.js` is the worked example (Kareem's Changes master en-suite).

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

- **Framing first (2026-10-24).** The button opens a preview of the shot from where you stand. **+** steps back
  along the view in 0.4 m steps (up to 3 m, stopping 0.3 m short of the first wall, tall piece or the room's edge;
  never out through a doorway), then widens the lens 6° at a time to 112° across; **−** undoes that, then narrows
  the lens. **Generate** sends that framing, and the spot is saved with it (camera position and `fov`).
- **Auto-name.** The spot is named after the furniture piece it aims at, e.g. "Master bedroom dresser" ("… dresser 2"
  if the room has one). `spotnames.js` maps each `furnish.js` piece's plan point to a word; rays across the frame
  vote, the centre counting most. **If a piece moves in `furnish.js`, update its point in `spotnames.js`** (the
  browser check in the photospot-v2 run tests every point). No named piece in frame: after the first attempt
  `photogen.py` names it from the image with `gpt-4.1-nano` (`OPENAI_NAME_MODEL`), well under $0.001. The name
  stays editable before saving.
- **What gets sent.** `photogen.js` sends three things to `photogen.py`:
  - an untextured **clay** screenshot of the model from the framed camera (shown as the "Clay view (sent)" thumbnail):
    every material swapped for a matte light grey for that one render (glass a faint see-through grey-blue, lamps and
    LED strips white, no bloom, soft GTAO), then put back. The AI only paints the real finishes onto those shapes;
    the textured "Model view" is the preview only;
  - a plan crop of the room drawn from the DWG;
  - the camera numbers.
- **The OpenAI call.** `photogen.py` calls OpenAI image edit (`gpt-image-2`, 1536×1024). Along with the screenshot it sends:
  - the **material board**: the `swatches` in `photogen-brief.json`, each a crop of a render (`box` = left, top, right, bottom as fractions), laid out as one labelled image;
  - a few designer renders of the room as style references (another room in shot adds one only if both rooms are
    wet or both dry, so a bedroom edge seen from the en-suite sends no bedroom), and the earlier renders that show
    its furniture (see below);
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
  - For the room the shot is filed under (and its `STAND_IN`, e.g. the entrance for the hallway) only, `photogen.py` sends the renders that show its pieces, labelled `FURNITURE - ... shows <where>`, plus that plan version's approved AI spots of that room (on Vercel fetched from Blob as they are). Never other rooms in shot: their pieces came into the photo (a bed through the en-suite door).
  - A render already sent as a style reference serves both roles. At most `MAX_FURNITURE` (6) extra images, and never more than 16 in all (OpenAI's limit).
  - The geometry lock stays: the VIEW decides what stands where; only the pieces' designs come from the references.
  - **To add a piece:** add a `furniture` entry naming a render already in a `spots*.json` file. Nothing to publish: the whole 1024 px renders are already in Blob.
- `photogen-brief.json` is re-read on every run, so edits to finishes and swatches apply immediately. After changing swatches, run `sh publish_renders.sh` so the live site gets the new board.
- Test UI changes with `--dry-run` (or `PHOTOGEN_MOCK=1`). Real runs cost OpenAI credits.

**Editing and deleting renders** (Renders screen, large view; only where Generate Photo Spot's backend runs)
- **Edit:** write what should change. `photogen.py` sends the render as image 1, plus the material board and the
  furniture renders, to the same image edit (about $0.30 at high quality, 1536×1024). The result is a **new version**:
  a spot with the same room, caption and camera, `"of"` its first version, `"version": n` and the `"edit"` text. The
  old one stays. Walk shows the latest version of each; Renders shows them all ("dresser · v2").
- **Delete** (after a confirmation): generated renders only; the designer's renders stay. Locally it removes the
  image and the `spots*.json` entry. On Vercel it deletes the Blob image and spot, and leaves a marker
  `renders/ai-deleted/<spots file>/<id>.json`, which also hides a generated spot kept in git (remove that from git by
  hand) and stops its id being reused.
- Both need `PHOTOSPOT_PASSWORD` if it is set, like generating.

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
  - `EDIT_AI_OPENAI_API_KEY` (Edit AI, § 8)
  - `BLOB_READ_WRITE_TOKEN`
  - optional `PHOTOSPOT_PASSWORD`: if set, the page asks for it once before generate, approve, edit or delete.
    Currently unset, so anyone with the link can delete generated renders: set it.
  - optional `OPENAI_NAME_MODEL` (default `gpt-4.1-nano`): names a spot from its image when no furniture is in frame.
- **Local secrets:** `.env` holds `OPENAI_API_KEY`. `.env.local` holds `BLOB_READ_WRITE_TOKEN` (from `vercel env pull`). Git and Vercel ignore both.
- **Ignored files:**
  - `.gitignore`: `renders/`, `dist/`, `notes/compare/`, `.env*`, `.vercel`, `.sc/`, `.gstack/`.
  - `.vercelignore` also drops the build scripts, `notes/`, `.github/` and `publish_renders.sh` from the deploy.

## 8. Edit AI

The floating **Edit AI** button (3D and 2D only, hidden in Renders) lets anyone with the link change the flat in words:
tap it, the view freezes, circle what to change (or pick **Whole view**), then say what you want and optionally attach reference images.

- **Files:** `edit-ai.js` (button, freeze + highlight, chat, live loading), `edit_ai.py` (the agent and its tools, `/api/edit-ai/*`),
  `edit_ai_dxf.py` (DXF query/edit CLI), `api/edit-ai.py` (Vercel entry). `index.html` only calls `liveFiles` / `liveImport` / `createEditAI`.
- **Model:** `gpt-5.2` with vision (override with `EDIT_AI_MODEL`). It greps and reads the repo, edits `furnish.js`,
  `materials.js` and the version's tour, and (where `dwg/` and the build scripts exist, i.e. locally) moves walls in the plan DXF and
  rebuilds the model and drawing. It never edits the As-built plan unless you are on the As-built page. No image generation.
- **Hot path:** every change is saved as a revision in Blob (`edit-ai-live/<version>/rev-*.json`, files content-addressed in
  `edit-ai-live/files/`; served same-origin through the `/edit-ai-live/*` rewrite). The page loads `GET /api/edit-ai/patches?version=`
  first and uses those files instead of the deployed ones, then reloads in place with the same camera. Undo writes a new revision.
  Once git catches up the override is "synced"; if the deployed file moved on, the edit's search/replace ops are replayed on it,
  and if that fails the override is dropped (conflict) so the site never shows a stale file.
- **Git:** after the live save a background job commits the change to `main` (local: `git commit` + push as karimtaamer;
  Vercel: GitHub API, only if `EDIT_AI_GITHUB_TOKEN` is set, else the change lives in Blob only).
- **Safety:** per-IP rate limit (`EDIT_AI_RATE`, default 20 requests/hour), images capped (~2 MB screenshot, 4 refs re-encoded
  in the browser to 1024 px, which strips EXIF), JS is syntax-checked (locally) and test-imported in the browser; a broken edit is undone.
- **Env vars:** `EDIT_AI_OPENAI_API_KEY` (required, separate from photogen's `OPENAI_API_KEY`), optional `EDIT_AI_MODEL`, `EDIT_AI_RATE`,
  `EDIT_AI_GIT_SYNC=0` (off), `EDIT_AI_GITHUB_TOKEN` / `EDIT_AI_GITHUB_REPO` / `EDIT_AI_GITHUB_BRANCH`, `EDIT_AI_DWG_PYTHON`
  (python with ezdxf for DXF edits). Without the key the button still shows and explains that Edit AI isn't switched on.
- **Run locally:** `python3 edit_ai.py [port]` serves the site with both APIs (reads `.env`).
- **Limits:** the rate limit is per server instance; on Vercel only furniture/finishes/tour edits (no DXF, since `.vercelignore`
  drops `dwg/` and the build scripts); concurrent edits are last-write-wins; the 2D zoom isn't kept across the reload.
