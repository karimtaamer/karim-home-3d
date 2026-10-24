# Editing the plan drawings (DWG / DXF)

Rules for changing the floor plan itself. Read this before any edit to a plan DXF. Builds are in README §3–4.

## 1. Files and tools

- **Edit the DXF in `dwg/`, not a DWG.** One file per version: `dwg/main.dxf`, `dwg/bigger-bedroom.dxf`,
  `dwg/shifted-bedroom.dxf`, `dwg/naghams-changes.dxf`. Outside the master suite all of them are identical (v12): change a shared room in one,
  copy it to the others with `suite_merge.py`, and run `suite_merge.py --check dwg/*.dxf` (README §3). A suite
  change goes in that version's file only. Git is the backup: don't leave `.before-*` copies in `dwg/`.
- **A new DWG from the designer:** convert it (below), diff it against the matching `dwg/` file, and bring the
  changes into `dwg/`. Don't build from `~/Downloads`.
- **Python:** `~/.dwg-tools/bin/python` with ezdxf. Open files with `ezdxf.recover.readfile` (libredwg output has
  small structural faults), and run `doc.audit()` before saving.
- **Reading a DWG:** `dwg2dxf -y -o out.dxf in.dwg` (libredwg) is fine for reading.
- **Writing a DWG for AutoCAD:** use the free [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
  through ezdxf's [odafc add-on](https://ezdxf.readthedocs.io/en/stable/addons/odafc.html)
  (`odafc.convert("plan.dxf", "plan.dwg", version="R2018")`). It isn't installed yet. Don't hand out
  `dxf2dwg` (libredwg) output as the user's DWG: it is experimental and AutoCAD may refuse or "recover" it.
- **Inspecting and rendering:** `~/.dwg-tools/bin/python dwgtool.py info|text|dims|render FILE` (see its docstring).
  `render --bbox x1,y1,x2,y2` crops in DWG metres; `--grid` shows coordinates; `--layers 1wall,Windows` shows walls
  alone; `--box`, `--circle`, `--note` and `--mark-label` add red mark-ups. Open every PNG and look at it before using it.
- **ODA traps** (once it's installed): it converts folders, not files; it exits 0 even when it fails (check the output
  file exists); it hangs on an empty input folder (`ls` the folder first). After writing a DWG, convert it back to DXF
  and compare entity counts per layer with the DXF you wrote: they must match.
- **Coordinates:** the drawing is in DWG model-space metres. Room work is easier in the model.js frame:
  `x_model = x_dwg - 190.4049651574427`, `y_model = y_dwg + 121.6132067325871` (Main and v9 share it).

## 2. How these drawings are built

| Layer | Holds | Notes |
|---|---|---|
| `1wall` | Wall faces, door frames (jamb profiles), door swing ARCs, bath end walls, fixed kitchen/laundry appliance blocks | Each wall is **two parallel face lines**: 0.11–0.12 m apart inside, 0.25 m on the outside walls. Appliance blocks: dishwasher `dfs`, fridge `wgsfd`, sink `wrewwer`, hob `yrtds`, washer `etggt` |
| `Windows` | Window lines in the wall gap | Three or four parallel lines plus jambs |
| `3door` | Dynamic door blocks (`*U15` ×2, `*U17`) | Each INSERT expands to every state (~440 entities, hundreds of metres off the plan): locate them by insert point, never by bbox. Crop renders to the plan window |
| `2furni`, `2 furni` | Furniture and fittings | Closed polylines. A few blocks sit on `0` (bath `eds`): leave them there |
| `_DIM` | Dimensions | The viewer doesn't use them |
| `ISLAK` | Room names (TEXT) | **Every TEXT becomes a room label in the 3D.** Never add TEXT for notes |

Walls are **not hatched**; the only HATCHes are `WOOD2` door frames. Don't add wall hatch.
New entities copy the layer, colour (ByLayer), linetype and type (LINE vs LWPOLYLINE) of a nearby entity of the same kind.

Some doors are not `3door` blocks but loose `1wall` jamb profiles, an `ARC` swing and a `_DIM` leaf polyline (the guest
toilet's door). Move all of those together.

**Moving one door:** never move or explode a `3door` INSERT that is shared (`*U15` is inserted twice). Count its
references with `msp.query('INSERT[name=="*U15"]')`. If it is shared, copy the block, edit the copy and repoint only
this INSERT. Move the swing `ARC` and jamb pieces by the same offset. The arc radius must equal the leaf width, and the
leaf must open against a wall or into clear space.

## 3. Wall rules

1. **Always two faces.** A wall is never one line. When you move, add or shorten a wall, do it to both faces.
2. **Close every junction.** When a wall moves, the walls it meets must be trimmed or extended so their faces run
   into its faces: no gaps, no overlaps, no stubs left where it used to be.
   - **T-junction:** the through wall's face is broken between the partition's two faces, and the partition's faces end
     exactly on it. The through wall's far face stays continuous.
   - **L-corner:** outer faces meet at one point, inner faces at another (no fillet).
   - **Exact endpoints:** compute them and snap to existing endpoints within 1e-4 m. Never eyeball them.
3. **Openings stop at the frame.** At a door or window, both faces end at the frame or jamb, on both sides of the
   opening. Moving a door means moving its frame, swing and leaf, then extending (or trimming) both wall faces on
   both sides to meet the frame again.
4. **Don't rely on the 3D to hide mistakes.** `build_geometry.py` silently fills wall-thin gaps under 0.6 m, so a
   missing face looks fine in 3D but shows as a hole in the Drawing view. Check the drawing, not only the model.
5. **Copying from another drawing** (e.g. a designer's proposal): diff entity by entity in a shared frame, copy
   only the zone asked for, then run the checks in §5 on that zone. Proposals can carry their own drafting
   faults: 2-block moved the toilet door 0.34 m without extending the wall faces to it.

6. **Real walls, windows and columns beat sketches.** If a sketch puts a wall inside a real window or column, keep
   the real one, overlay the sketch on the walls, list each conflict and ask the user. Never move a window silently:
   it needs the engineer's OK.

## 4. Furniture rules

- Draw it on `2furni` as closed `LWPOLYLINE`s (plus plain lines for details). Reuse existing blocks by moving
  their `INSERT` (edit by handle) rather than redrawing them.
- **Blocks hide surprises.** The bath block `eds` carries its own screen line, and rotating `dfs` once left two stray
  dashes poking into the fridge. Render the zone after moving or rotating any block.
- Wall-hung items (mirror, floating shelf) are thin rectangles against the wall face: 2–3 cm for a mirror, 15–25 cm for
  a shelf. A counter-top item (water dispenser) is drawn inside the counter outline.
- **Clearance targets** (face to face): corridors ≥ 90 cm (entrances ideally ≥ 120), in front of kitchen runs
  100–120 cm, in front of a WC or basin 60–70 cm, in front of an appliance door about 60 cm. Door swings must not hit
  furniture. A washer and dryer side by side need ≥ 120 cm plus gaps; otherwise stack them.
- Keep the furniture in `furnish.js` and the drawing in step: same positions, same sizes.

## 5. Checks before rebuilding

1. **Dimensions:** measure every changed room and clearance wall-face to wall-face and compare with the target the
   user gave (e.g. sink zone 0.65 m). Report them as a table.
2. **Wall faces:** every `1wall` face line has a partner 0.08–0.30 m away along its length, except at corners and
   frames. Scan the zone's face lines for gaps that aren't openings.
3. **Nothing else changed:** entity diff of before vs after; only the intended zone may differ.
4. **Look at it:** render a crop of the zone (ezdxf `addons.drawing` + matplotlib), then the viewer's Drawing tab
   and 3D after the rebuild.
5. **ezdxf `doc.audit()`** shows no errors.
6. **Hygiene by script** in the zone: no zero-length lines and no colinear overlapping `1wall` lines. Overlaps already
   in the source are left alone but reported.
7. **Entity counts per layer**, before vs after. Explain every difference (e.g. `1wall` +1, `2furni` +9).

## 6. Reporting to the user

- Give clear dimensions in **cm**. Answer a drawing question with a cropped, marked-up PNG from `dwgtool.py render`.
  A quick dimension question gets the numbers only, no image.
- Mark-ups (red boxes, notes, dimension arrows) go **in the PNG only**, never in the DXF.
- One clean plan: no "new / removed / moved / before / after" labels in the drawing or the images.
- **Master bedroom changes:** always send two images: (a) the whole room with clearances marked (bed to walls and
  wardrobes, walkways, door swings) and (b) a zoom on the entrance passage (its width, the pinch point, door sizes).
- List every assumption, deviation from the user's sketch and open engineer sign-off. Never present those as settled.

## 7. Tools worth knowing

- [CAD-MCP](https://github.com/Codemod3/CAD-MCP): MCP server over ezdxf (read, add lines/polylines, delete by handle,
  export DWG through ODA). It has no move, offset or wall tools, so scripts in ezdxf stay the better editor here.
- [text-to-cad `dxf` skill](https://claudemarketplaces.com/skills/earthtojake/text-to-cad/dxf): generates new DXFs
  from ezdxf code. Its validation habit (entity counts per layer and type) is worth copying; it doesn't edit plans.
