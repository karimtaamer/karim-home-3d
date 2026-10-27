# Report: Move and Resize, every piece in every axis, Karim's version (27 Oct 2026)

Local sandboxes only (copies of the tree, no Blob token, `EDIT_AI_GIT_SYNC=0`, a DWG python that adds a line to stderr
like Vercel). Nothing reached the live site.

- **Sweep, all 152 pieces and parts × move X / Y / Z and resize X / Y / Z (912 changes):** 898 pass. Each change saved,
  its 3D checked after the save (box and height), its 2D checked (outline / lines / block moved or stretched by the same
  metres, drawing rebuilt; plan untouched for heights and 3D-only pieces), then undone with every file back as it was.
  - 220 of them went through the real page (`tests/move_sweep.mjs`: draft, Accept, reload, Undo); the rest through the
    API with the 3D worked out by running `furnish-karims-version.js` with three.js in node (same boxes as the page for
    147 / 152; the 5 with GLB fixtures were checked in the page instead: 30 / 30).
  - The 14 that don't pass are refusals by design: the four niches can't be pulled out of their wall or pushed deeper,
    and the three tall niches' heights are the locked "buffet niche = TV tall niche" design.
- **Heights with real input (`tests/move_z_e2e.mjs`):** 30 / 30. Walk height handles, PageUp / PageDown (Shift, Alt)
  in Walk, Top and the drawing, Accept, Undo.
- **`tests/test_move_tool.py`:** 12 / 12. `check_locks.py`: all 6 locks hold.
- **`check_furnish.py` (Karim's version):** 2 flags, both from earlier live edits, not from this work: the medicine
  cabinet (plan 20 cm deep since Edit AI `fcf7333`, 3D 30) and the coffee counter (its plan outline is 150 × 113 cm, not
  the 150 × 60 the check looks for).

Fixed on the way: "Extra data: line 2 column 1" (stderr after the plan query's JSON on Vercel); Python 3.11 couldn't load
`move_tool.py`; pieces drawn as several lines (corner sofa) or inside a block (terrace chairs) now move / stretch on the
plan; block resize stretches the block (and a turned block lands right); pieces flush against a neighbour move;
two items on one line; plants keep their leaves; twins at one x, y; empty "saved" revisions now refuse; the version
leak guard's false refusals; the bath's scale set after `sized()`.

# Report: edit reload without the splash (27 Oct 2026)

- Changed: `index.html` (handoff CSS, inline pick-up script, `reloadHere()` snapshot, top-view pose restore, `reveal()`),
  `edit-ai.js` (reloads through the page's `reloadHere` with the circled spot), `drawing.js` (`view` get/set for the 2D pan / zoom).
- Passed: `node --check` on `edit-ai.js`, `drawing.js`, the page's module script and its inline script.
- Not run: the headless check (`/tmp/handoff-test/t.mjs`). Headless Chrome with SwiftShader closed the tab while the 3D page was
  still loading, before the new code ran. Per CLAUDE.md, one attempt only. Check it by hand in a real browser.
