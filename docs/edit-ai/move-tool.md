# Move and Resize

The **Move and Resize** button (next to Measure, in the 3D bar and the Drawing bar) lets you pick a piece and drag it
or its edge/corner handles.

## Accept before save

* Dragging and pulling handles only **previews**: the piece moves / stretches in place, a dashed outline shows where it
  was, and the label and the bar at the bottom give its size (W × D cm, and what it was) and how far it moved. Several
  drags add up in one draft.
* **Accept** (or Enter) saves the draft as one `transform` write, one Edit AI revision; the page reloads and the toast's
  **Undo** takes it back (Edit AI's undo path).
* **Cancel**, Esc, or a tap away from the draft throws it away and puts the piece back. Nothing reaches the server.
* The same in Walk, Top and the 2D drawing.

## Up and down (Z)

* **Walk:** a dashed stalk rises from the middle of the picked piece to its top: the **square** there makes it taller
  or shorter (its bottom stays), the **dot** above it raises or lowers it. Top and the drawing look straight down, so
  they have no height handles.
* **Keys, every view:** PageUp / PageDown raise or lower it 1 cm (Shift: 10 cm); with Alt they make it taller / shorter.
* The label says `10 cm up` or `85 cm tall (was 75)`, measured from where it started (`move-origins-<v>.json` keeps
  its first `z` too). A height change can share a draft with a plan move or resize.
* The plan has no heights: a height-only change leaves the DXF alone and says so.

## Picking: whole piece first, double-tap to drill in (Figma-style)

* 3D: a tap picks the whole piece (`item()`). A double-tap on it goes one level in, to the named part under the
  pointer (`p.label(...)`, e.g. the coffee bar's espresso machine, a TV-wall niche, the buffet's niche or sideboard).
  The chips under it are the trail (`Whole TV library › south tall niche`) and the parts one level in (`+ TV niche`);
  Esc climbs one level out.
* 2D: a tap picks the smallest outline under the point (as before); the chips climb out.

## API: `POST /api/edit-ai/transform` (no LLM, deterministic)

```json
{"version": "kareems-changes", "rev": "…", "op": "move", "dx": -0.1, "dy": 0,
 "piece": {"kind": "item", "x": 2.02, "y": 8.965, "facing": "S", "anchor": [2.02, 8.965], "lines": [560], "box": [...], "low": 0, ...}}
```

`op: "resize"` sends `box: [x0, y0, x1, y1]` (plan metres) in place of dx/dy, and `z: [low, high]` (m) for a new
height. A move sends `dz` (m) to raise or lower it. The piece adds `sy` / `py` (its height scale and base),
`others` (the plan boxes of the floor pieces round it) and `twin` (which of several pieces placed at the same x, y,
facing it is). Parts add `part`, `pos`, `pscale`, `posY`, `pscaleY`, `hostBox`, `frame` (a part inside a part) and
`param` (a part drawn from numbers). If the page's `rev` is old, the server refuses, the same way chat does. The route
has its own rate bucket (`move:<ip>`, 120 an hour).

## What it writes

* **2D:** it finds the piece's 2furni outline (IoU ≥ 0.45 with the 3D box) and runs `dxf_edit` `move_piece` /
  `resize_piece` with `allow_overlap`: the plan goes where the user dragged it, even into a neighbour (the notes say
  what it now runs into), so a bed flush between its nightstands still moves. A piece drawn as one block moves the
  block and a resize stretches it (`scale`). A piece drawn as several lines with no outline of its own (the corner
  sofa: seat, backs and end table) takes every 2furni line inside its plan box, less those inside a smaller
  neighbour's box (a rug's box holds the coffee table), and moves (`move`), turns (`rotate`) or stretches (`scale`)
  them with it. A floor piece drawn only inside one outline round several pieces (the dining set block) changes in
  3D only, and only while it stays inside that outline. Pieces at 1.5 m or higher, lights, niches and pieces with no
  lines under them are 3D-only.
* **3D (furnish.js), for this version only** (docs/edit-ai/version-isolation.md):
  * A literal `item(x, y, …)` on a line only this version runs is rewritten; on a shared line each number becomes
    `version === "<v>" ? new : old`.
  * A resize wraps the call as `sized(item(…), across, out)` (gated the same way) and re-anchors it so the far edge
    stays; a height change adds `up` (height scale, from its base) and `lift` (m): `sized(item(…), across, out, up, lift)`.
  * A piece placed by a loop or shared code (curtains, terrace plants, prints) gets a line in the `MOVED` table near
    `item()`: `if (version === "<v>") MOVED["x,y,facing"] = [x, y, across, out(, up, lift)];`. `item()` applies it.
    Pieces placed at the same x, y, facing (the dining table, its rug and the pendant over it) are told apart by the
    order they are placed: `MOVED["18.4,7.6,S#2"]` is the second (Karim's version's `item()` counts them).
  * A part (a `p.label` block) gets a first line `p.g.position.set(…), p.g.scale.set(…)` (its height too; guarded by
    version on a shared block).
  * A part with `param` (the niches) changes the numbers it is cut from (`tall`, `low`, `niche`): across, and up /
    down where its param names them (`z: [2, 3]`, the TV niche). The tall niches' heights are a settled design (the
    buffet niche matches them), written into the code, so they can't be raised or made taller here.
  * Before saving, `other_versions_changed()` must find every other version unchanged, else nothing is saved.
  * A change that breaks a design lock is saved (the user pressed Accept), the lock is marked suspended and the toast says
    so; Undo puts both back.
* `item()` records `userData.piece = {x, y, facing, lines}` and `label()` marks `userData.part` (+ `param`): that is how
  the browser points the server at the right source line.

## Tests

* `python3 tests/test_move_tool.py`: gating, MOVED table, heights, twin keys, niche numbers, leak guard (no server).
* `node tests/move_sweep.mjs http://127.0.0.1:<port> out.json [start] [end]`: Karim's version, every piece and part
  moved along X, Y, Z and resized along X, Y, Z through move.js (draft, Accept, reload), each checked in 3D after the
  reload and on the plan (DXF outline / lines / block, drawing rebuilt; untouched for heights and 3D-only pieces),
  then undone. Same sandbox rule. Resumable: it skips what `out.json` already has. Run several sandboxes for speed.
* `node tests/move_z_e2e.mjs http://127.0.0.1:<port>`: heights with real input: the Walk handles, PageUp / PageDown
  (Shift, Alt) in Walk, Top and the drawing, Accept, Undo.
* Sandbox: copy the working tree without `.git`, `.env`, `renders/` and `edit-ai-live/`, then
  `env -u BLOB_READ_WRITE_TOKEN -u VERCEL EDIT_AI_GIT_SYNC=0 python3 edit_ai.py <port>` in it. Setting
  `EDIT_AI_DWG_PYTHON` to a wrapper that prints a line to stderr after the real DWG python mimics Vercel (stderr after
  the JSON: the cause of "Extra data: line 2 column 1" before 26 Oct 2026).
* `node tests/move_e2e.mjs http://127.0.0.1:<port>`: browser e2e against a **sandbox** copy served by `edit_ai.py` with
  no Blob token and `EDIT_AI_GIT_SYNC=0`; every accepted change is undone. Never point it at the live site.
* `python3 tests/move_same_scene.py before.json after.json`: furnish.js instrumentation changes nothing on screen.
