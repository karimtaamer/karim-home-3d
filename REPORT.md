# Electrical plan category chips (Main, 7 Nov 2026)

- Lighting and Sockets & power remain unchanged. Switches now contains switch banks and AC controls only.
- Network & TV now includes indoor and outdoor intercom points alongside data, TV, router, Wi-Fi access points, and other network points.
- New Sensors & fans chip contains every motion/presence sensor and exhaust fan. Other contains the doorbell, chime, breaker panel, and any sound control point.
- Verified all electrical kinds have exactly one category and all 201 current Main points map to the intended chip; no electrical point or wiring changed.

# Hot-water decision: instant electric heater (Main, 7 Nov 2026)

- Karim confirmed the master-bath instant heater is electric. Main keeps its existing instant-heater point inside the vanity.
- Removed the 40 L electric storage heater and its dedicated power point from the laundry upper cabinet; the openable cabinet remains as storage.
- Removed the electric towel-heater marker and fused-spur point. The visible towel rail remains unheated.
- Updated the client decision in README §5. Other plan versions keep their existing layouts.
- Checks: generated electrical data contains one electric instant-heater connection and no laundry storage-heater or electric towel-heater points; JS syntax, `git diff --check`, and all six design locks pass. The furniture checker still reports only the earlier coffee-counter size mismatch.

# Follow-up electrical corrections: terrace curtains and master bedroom (Main, 7 Nov 2026)

- Reception switch key 3 now serves both curtain-pocket LEDs along the terrace wall: the reception window and the dining slider. The dining switch retains the separate north-window curtain-pocket LED.
- Removed the artwork and picture light above Main's master bed, its electrical feed, and the picture-light key from both bedside banks. Each bedside now has two two-way pendant keys.
- Main bedroom entrance bank now has three keys: bedroom spots A, bedroom spots B, and the bedroom curtain pocket. The separate three-key vanity bank controls its two ceiling spots, mirror glow, and shelf/tray LEDs. Moved the two banks apart along the same wall so the plan shows both markers and the 3D plates sit side by side.
- Added a one-key switch on the short wall marked by the client's arrow for the two boxed spots by the bathroom-door/wardrobe corner. Those two spots have their own circuit, separate from the vanity spots.
- Verified generated electrical JSON circuit assignments and switch positions; JS syntax, Python syntax, `git diff --check`, and all six design locks passed. `check_furnish.py` passes the changed master bedroom furniture and flags only the previously recorded coffee-counter mismatch (DWG 150 × 60 cm; 3D 150 × 66 cm).

# Electrical corrections: client review batch (Main, 7 Nov 2026)

- Added the missing 220 cm terrace wall sconce to the 3D furniture, matching its existing plan point.
- Separated the reception curtain LED from its TV-wall and artwork lighting. Combined dining spots on one key, and all corridor and lobby spots on one two-way key at the front door and dining end. Moved entrance-console lighting to the front-door bank and removed the separate lobby switch.
- Moved the master bathroom bank inside onto the short wall beside its vanity socket, the guest bathroom bank inside beside its vanity socket, and the laundry bank inside. Both bathrooms have three keys: one for every spot, one for the vanity/mirror/shower-niche LEDs, and one for the exhaust fan alone.
- Replaced the kitchen sound/intercom screens with the kitchen light switches. Removed the living-room sound/intercom screens, leaving one indoor intercom beside the main door. Removed the entrance low-current panel; fibre, TV, intercom and Cat6 home-run to the shoe-cabinet hub.
- Changed plug-in appliance points to sockets (fridge, dishwasher, washer, robot dock, water filter, hood, oven, microwave). Kept dedicated high-load/fixed connections as power points. The hob and its separate extractor supply are both represented.
- Added a double socket to the marked reception wall, removed the 45 cm master-bedroom window-wall socket, and moved the breaker panel behind the entrance artwork.
- Checks: `python3 build_electrical.py`, JS syntax, and `python3 check_locks.py` passed. `check_furnish.py` still flags the pre-existing coffee-counter size mismatch (DWG 150 × 60 cm; 3D 150 × 66 cm); all other checked furniture passed.

# Electrical: network hub + ceiling Wi-Fi access points (Main, 7 Nov 2026)

- Hallway router (210 cm), its socket and its Cat6 uplink removed. New `hub` (type `router`): fibre box, router and 16-port PoE switch in the entrance shoe cabinet (x 10.8, 30 cm), with a double socket beside it.
- The low-current panel and its fibre conduit were part of this earlier proposal; the client review batch above removes the panel and brings those cables to the shoe-cabinet hub.
- New type `ap` (ceiling Wi-Fi access point, Cat6 + PoE): AP1 (5.425, 5.05) between the lobby spots, AP2 main (10.25, 4.6) above the shoe cabinet, AP3 (18.3, 5.625) between the dining and reception spot rows. Network & TV chip.
- Flip desk plate is now double data (`2D`). No kitchen or terrace data points (Karim).
- Passed: `node --check electrical.js`, `check_locks.py`, every point type maps to a kind and a chip. Not run: headless page check.

# Electrical: guest-bath switch inside + category chips (Main, 7 Nov 2026)

- Guest bathroom 3-gang switch moved inside: south wall inner face beside the door frame (vanity side), x 14.13, 120 cm.
- 2D plan: the Electrical button now opens a chip row (3D bar has no Electrical button now): Lighting · Switches & sensors · Sockets & power · Network & TV · Intercom & other.
- Passed: `node --check electrical.js`, `check_locks.py`, every point type maps to a chip.
- Not run: headless page check timed out at 60 s waiting for the page to load (SwiftShader); one attempt, not repeated.

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
