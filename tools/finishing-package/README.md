# Finishing package generator (Main)

Builds the print-ready finishing package for Eng. Asmaa from Main (`kareems-changes`): one multi-page PDF
(A3 plans 1:100 / 1:50, A4 details 1:25-1:50, title block, scale bar, one highlight colour) plus a DXF and an
AutoCAD 2018 DWG of the plan with the package layers (E-LIGHT, E-SWITCH, E-POWER, E-LOWCURRENT, P-WET, C-CEILING).

```sh
~/.dwg-tools/bin/python tools/finishing-package/build_package.py --out /tmp/package   # from the repo root
```

What comes from where
- Walls, rooms, areas, openings, door swings: `model-kareems-changes.js`; linework: `drawing-kareems-changes.json`.
- Electrical (every sheet E201-E209): `electrical-kareems-changes.json`.
- Joinery / appliance boxes in the elevations, split ACs: `furnish-kareems-changes.js` run in node (same stand-in as `check_furnish.py`).
- Curtain pockets: the `pockets` array in `furnish-kareems-changes.js`. TV wall depths: `design-locks.json`.
- Not in Main (edit `package_data.yaml`): Arabic/English room names, furniture labels, plumbing wet points,
  switch keys without circuit ids, finishes/spec table, title-block text and revision.

Implementation notes (A4 PDF, plain language with Arabic site terms, printed with headless Chrome):

```sh
~/.dwg-tools/bin/python tools/finishing-package/impl_notes.py --out /tmp/package
```

Files
- `build_package.py`: cover, layout, furniture sheets, entry point. `sheets_elec.py`: E201-E209. `sheets_more.py`: plumbing,
  reception TV wall, kitchen / laundry elevations, specs, DXF/DWG export, page order (`build_all`).
- `sheets_r1.py` (R1): bathrooms D602 / D603 drawn with real fixtures, buffet wall D503, terrace doors D504-D505, terrace
  L-seat and BBQ D506-D508, living TV wall D502, gypsum ceilings C401-C404. `elevkit.py`: the elevation drawing kit
  (tiles, slats, sanitaryware, doors, windows, dimension chains, callout column).
- Lotus technical package (Samra Concepts, 20-08-2026) values used on the sheets are constants in `sheets_r1.py`
  (`CEIL`, `SOFFIT`); Main governs where they differ.

New revision: change `rev`, `date` and `changes` in `package_data.yaml`, rerun both scripts. Nothing here is loaded by the site.
