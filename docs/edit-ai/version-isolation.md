# Every version has its own everything

Karim, 26 Oct 2026: *"Each version should be totally separate: everything. Any change in 2D, 3D, furnishing, or
anything I do in a plan should only apply to that plan. Even renders."*

Every plan version has its own copy of every file it is built from or shows. Nothing is shared or inherited:

| What | File per version |
|---|---|
| Plan (2D) | `dwg/<v>.dxf` |
| Walls, openings (3D) | `model-<v>.js`, `drawing-<v>.json` (built from the DXF) |
| Furniture, joinery, fittings | `furnish-<v>.js` |
| Materials, colours | `materials-<v>.js` |
| Tour, room / opening specs | `tour-<v>.json` (standalone; no `extends`) |
| Photo spots, renders | `spots-<v>.json` (standalone; no `extends`), plus that file's Blob spots |

Versions: `kareems-changes` (Main), `karims-version` (Karim's version, `?v=kareems-changes` on the page),
`naghams-changes`, `as-built`.

## Edit AI

* The model, its tools and the checks call the files `furnish.js` / `materials.js`; `own(v, path)` in `edit_ai.py`
  turns that into the version's file wherever a file is read, stored in the live store or committed. `edit-ai.js`
  does the same in the page (`liveImport(live, "furnish.js")`, `live.url("furnish.js")`).
* An edit simply changes the version's own file. There is no "in all versions": a change you want in several
  versions is made in each of them.
* Each `furnish-<v>.js` started as an exact copy of the old shared `furnish.js`, so some `version === "..."` checks
  remain. Only the branches that run for that version matter; `version_scope()` still marks the others for the model
  (grep / furniture_near) and `review()` still catches an edit that only touches a branch that never runs.
* Live overrides from before the split were stored as `furnish.js` / `materials.js`. `resolve()` drops the ones
  already pulled into git (`PULLED`), replays any later one onto the version's own file (`legacy()`), and
  `edit_ai_pull.py` merges such a leftover into `furnish-<v>.js`. Undo of a pre-split change is refused.

## Undo

Undo restores the file the edit started from (`pre_url` / `base_url` in the revision), taken back off the deployed
file, never plain `deployed()`: after git sync the deployed file *is* the edit (26 Oct, `0dfc896`: an empty Undo of
the black armchair). The page checks the served files after an Undo and reports an error if they are still the edit's.
