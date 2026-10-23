# Editing the plan drawings (DWG / DXF)

Rules for changing the floor plan itself. Read this before any edit to a plan DXF. Builds are in README §3–4.

## 1. Files and tools

- **Edit the DXF, not the DWG.** Main builds from `~/Downloads/master-bed186-v6-shoes2-2block-laundry.dxf`, Bigger
  Master Bedroom from `~/Downloads/master-bed-v9-2block-laundry.dxf`. Back the file up first
  (`cp -n plan.dxf plan.before-<what>.dxf`).
- **Python:** `~/.dwg-tools/bin/python` with ezdxf. Open files with `ezdxf.recover.readfile` (libredwg output has
  small structural faults), and run `doc.audit()` before saving.
- **Reading a DWG:** `dwg2dxf -y -o out.dxf in.dwg` (libredwg) is fine for reading.
- **Writing a DWG for AutoCAD:** use the free [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
  through ezdxf's [odafc add-on](https://ezdxf.readthedocs.io/en/stable/addons/odafc.html)
  (`odafc.convert("plan.dxf", "plan.dwg", version="R2018")`). It isn't installed yet. Don't hand out
  `dxf2dwg` (libredwg) output as the user's DWG: it is experimental and AutoCAD may refuse or "recover" it.
- **Coordinates:** the drawing is in DWG model-space metres. Room work is easier in the model.js frame:
  `x_model = x_dwg - 190.4049651574427`, `y_model = y_dwg + 121.6132067325871` (Main and v9 share it).

## 2. How these drawings are built

| Layer | Holds | Notes |
|---|---|---|
| `1wall` | Wall faces, door frames (jamb profiles), bath end walls | Each wall is **two parallel face lines**: 0.11–0.12 m apart inside, 0.25 m on the outside walls |
| `Windows` | Window lines in the wall gap | Three or four parallel lines plus jambs |
| `3door` | Dynamic door blocks | Their bounding box spans every state: locate them by insert point, never by bbox |
| `2furni`, `2 furni` | Furniture and fittings | Closed polylines or blocks (bath `eds`, washer `etggt`, dishwasher `dfs`, …) |
| `_DIM` | Dimensions | The viewer doesn't use them |
| `ISLAK` | Room names (TEXT) | **Every TEXT becomes a room label in the 3D.** Never add TEXT for notes |

Some doors are not `3door` blocks but loose `1wall` jamb profiles, an `ARC` swing and a `_DIM` leaf polyline (the guest
toilet's door). Move all of those together.

## 3. Wall rules

1. **Always two faces.** A wall is never one line. When you move, add or shorten a wall, do it to both faces.
2. **Close every junction.** When a wall moves, the walls it meets must be trimmed or extended so their faces run
   into its faces: no gaps, no overlaps, no stubs left where it used to be.
3. **Openings stop at the frame.** At a door or window, both faces end at the frame or jamb, on both sides of the
   opening. Moving a door means moving its frame, swing and leaf, then extending (or trimming) both wall faces on
   both sides to meet the frame again.
4. **Don't rely on the 3D to hide mistakes.** `build_geometry.py` silently fills wall-thin gaps under 0.6 m, so a
   missing face looks fine in 3D but shows as a hole in the Drawing view. Check the drawing, not only the model.
5. **Copying from another drawing** (e.g. a designer's proposal): diff entity by entity in a shared frame, copy
   only the zone asked for, then run the checks in §5 on that zone. Proposals can carry their own drafting
   faults: 2-block moved the toilet door 0.34 m without extending the wall faces to it.

## 4. Furniture rules

- Draw it on `2furni` as closed `LWPOLYLINE`s (plus plain lines for details). Reuse existing blocks by moving
  their `INSERT` (edit by handle) rather than redrawing them.
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

## 6. Tools worth knowing

- [CAD-MCP](https://github.com/Codemod3/CAD-MCP): MCP server over ezdxf (read, add lines/polylines, delete by handle,
  export DWG through ODA). It has no move, offset or wall tools, so scripts in ezdxf stay the better editor here.
- [text-to-cad `dxf` skill](https://claudemarketplaces.com/skills/earthtojake/text-to-cad/dxf): generates new DXFs
  from ezdxf code. Its validation habit (entity counts per layer and type) is worth copying; it doesn't edit plans.
