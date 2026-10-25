# When an edit needs the 2D plan

The plan DXF (layer `2furni`) draws only what takes room you'd walk around. Edit the plan only when the change moves
or resizes one of these. Everything else is 3D-only: edit `furnish.js` and reply.

## Plan (2D) and 3D together
- Floor-standing furniture and joinery: beds, sofas, tables, chairs, wardrobes, cabinets, vanities, rugs.
- Wall-fixed pieces reaching ~30 cm or more into the room below head height (~1.5 m): wall desks, floating vanities,
  benches, consoles, wall beds, deep low cabinets.
- Walls, partitions, doors (`move_door`) and windows (`move_window`).
- Any piece that already has a `2furni` outline under it (`furniture_near` lists them) when its position or footprint
  (width along the wall, depth into the room) changes.

## 3D only (no DXF edit, no plan match needed)
- Height ("taller", "lower", "85 cm high"): the outline is the footprint.
- Colour, material, finish, doors opening.
- Lights: `pendant(...)`, `sconce(...)`, LED coves, downlights.
- AC units: `ac(...)` calls (split units), and their size / depth / height.
- Plaster curtain boxes, AC bulkheads, ceiling boxes, soffits, ducted linear grille faces: anything whose lowest part
  stays above head height. Their depth from the wall is local z in `p.box(...)`, not a plan footprint.
- Thin wall-hung things: art, mirrors, TVs, shallow shelves, paint panels (unless one already has an outline).
- Pieces with no `2furni` outline under them.

## Rules
- Never invent a 2furni outline for a 3D-only piece.
- Never call `discard` only because there's no plan outline to match a 3D-only change.
- A 3D-only piece brought down below head height (into walking room) becomes a plan piece: draw its outline.
- Unsure? `furniture_near` at the piece's (x, y): no outline listed there means 3D-only.

See `3d-only-patterns.md` for worked examples.
