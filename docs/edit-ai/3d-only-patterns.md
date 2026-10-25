# 3D-only patterns (worked examples)

## Plaster curtain box / AC bulkhead on the living-room east wall
`furnish.js`, Living, the `else` branch after `const NCAC = ...` (versions without wall-mounted splits):

```js
item(21.222, (1.94 + 9.5) / 2, "W", p => p.box(-3.78, 3.78, 2.1, M.ceiling, 0, 0.3, mat.limewash));
for (const [y0, y1] of [[3.165, 5.165], [6.34, 8.08]]) item(21.222, (y0 + y1) / 2, "W", p => {
  p.box(..., 2.3, 2.36, 0.3, 0.302, mat.grille);           // grille face sits on the box front (z = depth)
  for (let k = 1; k < 3; k++) p.box(..., 0.302, 0.304, mat.applianceWhite);
});
```

- "Make this section 1 m deep from the wall": the box's z1 `0.3` -> `1.0`, and move each grille face with it
  (`0.3, 0.302` -> `1.0, 1.002`, `0.302, 0.304` -> `1.002, 1.004`). No DXF edit: it hangs from 2.1 m up.
- "Lower the bulkhead to 2.4 m": y0 `2.1` -> `2.4` (the grille heights inside it stay within the box).
- Only one window's run: split the box into pieces along local x (wall runs plan y, facing "W": local x = 5.72 - y).

## Wall-mounted split AC (`ac(x, y, facing, top, w, h, d, vane)`)
- Naghams / Kareem's versions: `ac(20.6, 2.0705, "N", 2.4, 0.85, 0.29, 0.22, true)`. Deeper = the 7th argument,
  higher = the 4th. 3D-only.

## Ceiling curtain track (NCAC branch)
- `item(21.222, ..., "W", p => p.box(..., M.ceiling - 0.03, M.ceiling, 0.02, 0.18, ...))`: depth / length changes are 3D-only.

## Lights
- `pendant(x, y, h)`: h = height of the lamp's bottom. Raise 20 cm = h + 0.2. 3D-only.
- Sconces, LED strips (`mat.ledStrip`), coves: 3D-only.

## Not 3D-only (for contrast)
- `item(4.13, 7.62, "W", bed())`: stands on a 2furni outline. Moving or resizing it needs `move_piece` / `resize_piece`.
- A wall desk 60 cm deep at 0.75 m: below head height and reaches into the room, so it needs an outline.
