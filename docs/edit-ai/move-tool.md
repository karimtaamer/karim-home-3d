# Move / Resize tool

The **Move** button (next to Measure, in the 3D bar and the Drawing bar) lets you pick a piece and drag it
or its edge/corner handles. Each drop is one Edit AI revision, so Undo and Reset work as usual.

## API: `POST /api/edit-ai/transform` (no LLM, deterministic)

```json
{"version": "bigger-bedroom", "rev": 12, "op": "move", "dx": -0.1, "dy": 0,
 "piece": {"kind": "item", "x": 2.02, "y": 8.965, "facing": "S", "lines": [560], "box": [...], "low": 0, ...}}
```

`op: "resize"` sends `box: [x0, y0, x1, y1]` (plan metres) in place of dx/dy. Parts add `part`, `pos`, `pscale`, `hostBox`.
The answer is `{rev, summary, notes, plan, ...}`. If the page's `rev` is old, the server refuses, the same way chat does.
The route has its own rate bucket (`move:<ip>`, 120/min).

## What it writes

* **2D:** it finds the piece's 2furni outline (IoU ≥ 0.45 with the 3D box) and runs `dxf_edit` `move_piece` /
  `resize_piece`. Things drawn inside the outline move with it. If the plan has no room, the request is refused
  or the 3D move is trimmed to what the plan really did (and a note says so). Pieces whose bottom is at
  1.5 m or higher, lights, and pieces with no outline are 3D-only: no outline is ever made up for them.
* **3D (furnish.js):**
  * A move rewrites the `item(x, y, …)` numbers. Pieces built in a loop are unrolled first.
  * A resize wraps the call as `sized(item(…), across, out)` and re-anchors it so the far edge stays put.
  * A part (a `p.label` block) gets a first line like
    `p.g.position.set(…); p.g.scale.set(…);  // Move tool: …`, which a later Move replaces.
* `item()` records `userData.piece = {x, y, facing, lines}` (call-site lines come from the stack), and `label()`
  marks `userData.part`. That's how the browser points the server at the right source line.

Look-only and 2D↔3D sync rules are the same as for chat edits. This adds no new exemptions.
