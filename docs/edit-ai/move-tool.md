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

`op: "resize"` sends `box: [x0, y0, x1, y1]` (plan metres) in place of dx/dy. Parts add `part`, `pos`, `pscale`,
`hostBox`, `frame` (a part inside a part) and `param` (a part drawn from numbers). If the page's `rev` is old, the
server refuses, the same way chat does. The route has its own rate bucket (`move:<ip>`, 120/min).

## What it writes

* **2D:** it finds the piece's 2furni outline (IoU ≥ 0.45 with the 3D box) and runs `dxf_edit` `move_piece` /
  `resize_piece`; the 3D follows what the plan really did. A floor piece drawn only inside one outline round several
  pieces (the dining set block) changes in 3D only, and only while it stays inside that outline. Pieces at 1.5 m or
  higher, lights, niches and pieces with no outline are 3D-only.
* **3D (furnish.js), for this version only** (docs/edit-ai/version-isolation.md):
  * A literal `item(x, y, …)` on a line only this version runs is rewritten; on a shared line each number becomes
    `version === "<v>" ? new : old`.
  * A resize wraps the call as `sized(item(…), across, out)` (gated the same way) and re-anchors it so the far edge stays.
  * A piece placed by a loop or shared code (curtains, terrace plants, prints) gets a line in the `MOVED` table near
    `item()`: `if (version === "<v>") MOVED["x,y,facing"] = [x, y, across, out];`. `item()` applies it.
  * A part (a `p.label` block) gets a first line `p.g.position.set(…), p.g.scale.set(…)` (guarded by version on a shared block).
  * A part with `param` (the niches) changes the numbers it is cut from (`tall`, `low`, `niche`), across only.
  * Before saving, `other_versions_changed()` must find every other version unchanged, else nothing is saved.
  * A change that breaks a design lock is saved (the user pressed Accept), the lock is marked suspended and the toast says
    so; Undo puts both back.
* `item()` records `userData.piece = {x, y, facing, lines}` and `label()` marks `userData.part` (+ `param`): that is how
  the browser points the server at the right source line.

## Tests

* `python3 tests/test_move_tool.py`: gating, MOVED table, niche numbers, leak guard (no server).
* `node tests/move_e2e.mjs http://127.0.0.1:<port>`: browser e2e against a **sandbox** copy served by `edit_ai.py` with
  no Blob token and `EDIT_AI_GIT_SYNC=0`; every accepted change is undone. Never point it at the live site.
* `python3 tests/move_same_scene.py before.json after.json`: furnish.js instrumentation changes nothing on screen.
