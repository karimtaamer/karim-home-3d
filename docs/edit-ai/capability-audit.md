# Edit AI capability audit: 355 homeowner requests (26 Oct 2026)

## Status after the fixes (26 Oct 2026, evening)

Every fix in the catalogue below is built except the viewer-only items (U) and stairs / lifts (L, a one-storey flat).
By the same static review the 355 requests now stand at **340 ✅ · 9 ⚠️ · 6 ❌** (was 227 / 49 / 79):

- ⚠️ still: 12 swap bathroom and laundry and 16 a new en-suite (possible with the wall ops in saved stages, but big
  jobs for a model to get right first time); 73 corner window (two windows, the corner post stays); 74 bay window (walls
  + windows by hand, no bay op); 175 / 255 a specific product (library models are generic); 316 / 319 plumbing and gas
  (a note on the plan, no services layer); 57 showing a door open (the viewer's).
- ❌ still: 29 plan without furniture, 342 export, 343 before / after (viewer features, not edits); 137 facade (the
  outside isn't modelled); 282 stairs and 355 a lift (one storey).

Tested through the same tool calls the model makes, rebuilt for real: `tests/test_edit_ai_openings.py`,
`tests/test_edit_ai_home.py` (room finishes, renames, partitions with a new room, low / glass walls, move / thicken /
remove a wall, niches, door looks, double doors, notes, measure, pictures, saving in parts). A headless load of a
sandbox with all of it applied threw no errors (the screenshot caught the loading screen, so the look itself wasn't
checked). No request was run against a model.

The original audit follows; its verdicts are as they were before the fixes.


What a family building or fitting out a home would ask Edit AI, checked against what the code lets it do. Static
review of `edit_ai.py` (its tools and instructions), `edit_ai_dxf.py` (plan ops), `furnish.js` / `materials.js` (what
the 3D can build), `build_geometry.py` and `index.html` (what the viewer draws and Edit AI can't edit). Assumes today's
openings / heights work is pushed (rows marked **new** depend on it). No request was run against a model: 355 live
runs would spend credits and commit 355 edits.

**Verdicts:** ✅ works today · ⚠️ partly: approximate, manual and error-prone, or a hack the instructions don't
teach · ❌ can't. **Fix** points at the catalogue at the end.

What Edit AI can write: `furnish.js` (any 3D piece from boxes / cylinders / the few GLB models, with full access to the
scene), `materials.js` (new colours; only the textures already in `textures/`), the version's tour JSON (floor finish
per room from wood / tile / decking, tour stops, door-swing display, **new** opening specs and home heights), and the
plan DXF through `dxf_edit` (move / copy / delete lines, furniture outlines, windows, doors, **new** add / convert /
remove openings). It can't write `index.html` (walls, floors, ceilings, skirting, door leaves, window frames, room
lights), `build_flags.json` (niches / cuts), texture or model files, or add TEXT (room names).

## A. Walls and layout

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 1 | Remove the wall between the kitchen and living room | ⚠️ | Only by deleting both face lines by hand; the walls it met are left with gaps, rooms don't re-merge reliably | W |
| 2 | Move this wall 30 cm east | ⚠️ | Moves both faces by hand; junctions not trimmed / extended | W |
| 3 | Add a partition to split this bedroom in two | ⚠️ | Two add_line faces, no junction help; the new room gets no name | W, R |
| 4 | Make this wall thicker for soundproofing | ⚠️ | set_points on one face; neighbours not trimmed | W |
| 5 | Make this wall thinner | ⚠️ | Same | W |
| 6 | Half-height wall between kitchen and dining | ⚠️ | A furnish box in 3D only; not a wall on the plan | W |
| 7 | Curved wall in the living room | ❌ | The build reads straight wall lines only | W |
| 8 | Glass partition between the study and living room | ⚠️ | **new** full-height window over a wall run works for one span; no glass-wall kind | W |
| 9 | Add a column here | ⚠️ | A closed polyline on 1wall builds as solid, but no op or guidance | W |
| 10 | Remove this column | ⚠️ | Delete works; no structural warning | W |
| 11 | Take 50 cm from the corridor into the master bedroom | ⚠️ | A wall move | W |
| 12 | Swap the bathroom and the laundry | ❌ | Walls, fixtures, plumbing and room names in one job: past the step budget and the tools | W, R, B |
| 13 | Close off the kitchen with a wall and a door | ⚠️ | Partition by hand + **new** add_opening door | W |
| 14 | Enclose the balcony into an indoor room | ⚠️ | Walls / windows by hand; it stays "outdoor" (kind comes from its name) | W, R |
| 15 | Add a walk-in closet off the bedroom | ⚠️ | Partition by hand + doorway | W |
| 16 | Create an en-suite in the second bedroom | ❌ | Partition + door + wet room (needs a name) + fixtures: too big, no room-kind control | W, R, B |
| 17 | Extend the kitchen into the dining area | ⚠️ | A wall move | W |
| 18 | Recess a niche in the living-room wall for the TV | ❌ | Wall recesses are build flags (`--cut`) Edit AI can't write | N |
| 19 | Recessed shelves in the wall | ❌ | Same | N |
| 20 | Arched opening between hall and living room | ❌ | Openings are rectangular boxes in the viewer | O |
| 21 | Make the corridor wider | ⚠️ | A wall move | W |
| 22 | Square off this angled wall | ⚠️ | Manual line edits | W |
| 23 | Dropped ceiling box over the kitchen | ✅ | furnish ceiling box (3D-only pattern) | |
| 24 | Feature wall with wood slats | ✅ | Panel with oakSlats / oakBattens | |
| 25 | Stone-clad feature wall | ⚠️ | Panel works; one stone texture only | T |
| 26 | Add a fireplace / chimney breast | ✅ | Boxes, with a plan outline | |
| 27 | Open shelving room divider | ✅ | Furniture | |
| 28 | Move the whole kitchen to the other wall | ⚠️ | run() builder + outlines + appliances: often past the step budget | B |
| 29 | Show me the plan without furniture | ❌ | A viewer toggle, not an edit | U |
| 30 | Rename this room "Study" | ❌ | Room names are DWG TEXT; Edit AI may not add or change TEXT | R |

## B. Doors

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 31 | Move this door 40 cm along the wall | ✅ | move_door (block doors: **new** convert first) | |
| 32 | Make this door 90 cm wide | ✅ | move_door width / convert width | |
| 33 | Make the door open the other way | ✅ | **new** convert_opening opens | |
| 34 | Swap the hinge side | ✅ | **new** convert_opening hinge | |
| 35 | Change it to a sliding door | ✅ | **new** sliding_door | |
| 36 | Pocket door that slides into the wall | ⚠️ | Shown as a sliding leaf in the gap; no pocket in the wall | O |
| 37 | Barn door sliding on the wall face | ⚠️ | furnish panel + rail; the plan shows a bare gap | O |
| 38 | Double doors into the living room | ❌ | One leaf, 0.5–1.3 m | O |
| 39 | French doors to the terrace | ❌ | No double glazed leaves | O |
| 40 | Bi-fold doors | ❌ | No such kind | O |
| 41 | Add a new door here | ✅ | **new** add_opening door | |
| 42 | Remove this door and close the wall | ✅ | **new** remove_opening | |
| 43 | Replace the door with an open archway | ⚠️ | **new** bare doorway works; the arch doesn't | O |
| 44 | Make the doors 2.4 m tall | ✅ | **new** set_openings head / home door height | |
| 45 | Paint this door white | ❌ | Door leaves are oak in the viewer (index.html) | O |
| 46 | Glass door for the study | ❌ | Leaves are always solid | O |
| 47 | Brass door handles | ❌ | Doors have no handles at all | O |
| 48 | Walnut front door | ❌ | Leaf material fixed | O |
| 49 | Add architraves round the door | ⚠️ | furnish boxes round the opening, by hand | O |
| 50 | Frosted-glass sliding door for the bathroom | ⚠️ | **new** sliding glass panel; frosted only on windows | O |
| 51 | Cat flap in the kitchen door | ✅ | Small box (approximate) | |
| 52 | Threshold strip under the door | ✅ | Thin box | |
| 53 | Turn this door into a window | ✅ | **new** convert_opening | |
| 54 | Make the doorway a 2 m open passage | ✅ | **new** convert to "opening", width 2 | |
| 55 | Hidden flush door painted like the wall | ❌ | Leaf material / style fixed | O |
| 56 | Door with a glass fanlight above | ❌ | Wall above the head is solid | O |
| 57 | Show this door open | ⚠️ | Swing side **new**; open / shut state is the viewer's | U |
| 58 | Swing the door into the corridor, not the room | ✅ | **new** opens | |
| 59 | Second door to the kitchen | ✅ | **new** add_opening | |
| 60 | Mark this door as fire-rated / acoustic | ❌ | No notes or specs on elements | Q |

## C. Windows and glazing

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 61 | Make this window bigger | ✅ | move_window width / **new** head, sill | |
| 62 | Centre the window over the bed | ✅ | move_window centre_on | |
| 63 | Add a window on this wall | ✅ | **new** add_opening window | |
| 64 | Remove this window | ✅ | **new** remove_opening | |
| 65 | Start the window 60 cm above the floor (wall under it) | ✅ | **new** set_openings sill (the terrace case) | |
| 66 | Window up to the ceiling | ✅ | **new** head | |
| 67 | Floor-to-ceiling window | ✅ | **new** sill 0, head = ceiling | |
| 68 | Frosted glass in the bathroom window | ✅ | **new** frosted | |
| 69 | White window frames | ❌ | Frames are black steel in the viewer | O |
| 70 | More panes / mullions | ❌ | Pane count fixed (1 window, 2 slider) | O |
| 71 | Turn the terrace slider into a normal window | ✅ | **new** kind window | |
| 72 | Turn this window into a sliding door to the terrace | ✅ | **new** glass_slider | |
| 73 | Corner window | ⚠️ | Two windows; the corner post stays | W |
| 74 | Bay window | ❌ | Needs the wall to step out | W |
| 75 | Skylight | ❌ | No roof; one flat ceiling plane per room | C |
| 76 | Window seat | ✅ | furnish | |
| 77 | Curtains | ✅ | curtain / sheer | |
| 78 | Roller blinds | ✅ | Boxes | |
| 79 | Shutters | ✅ | Boxes (approximate) | |
| 80 | Security bars | ✅ | Boxes | |
| 81 | Tinted or reflective glass | ❌ | Glass is clear or frosted | O |
| 82 | Deep window ledge | ✅ | Box | |
| 83 | High clerestory window | ✅ | **new** sill / head | |
| 84 | Round or arched window | ❌ | Rectangular only | O |
| 85 | Internal window between two rooms | ✅ | **new** add_opening window | |

## D. Heights and ceilings

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 86 | Raise the ceiling to 2.8 m | ✅ | **new** home ceiling | |
| 87 | Lower the ceiling in the corridor only | ❌ | One ceiling height for the flat | C |
| 88 | Cove lighting round the living-room ceiling | ✅ | furnish (coveWall exists) | |
| 89 | Coffered ceiling | ✅ | Boxes (approximate) | |
| 90 | Dark ceiling colour | ❌ | Ceiling material is the viewer's | F |
| 91 | Wooden slats on the ceiling | ✅ | furnish ceilingBits | |
| 92 | Exposed beams | ✅ | Boxes | |
| 93 | Double-height living room | ❌ | Single storey, one ceiling | C |
| 94 | All doors 2.1 m | ✅ | **new** home door | |
| 95 | Kitchen uppers to the ceiling | ✅ | furnish | |
| 96 | Taller skirting (12 cm) | ❌ | Skirting is 8 cm oak in the viewer | F |
| 97 | No skirting | ❌ | Same | F |
| 98 | Picture rail / dado rail | ✅ | Thin boxes | |
| 99 | Higher terrace parapet | ✅ | **new** home parapet | |
| 100 | Raise one window's head only | ✅ | **new** head | |
| 101 | All windows with a 1 m sill | ✅ | **new** home sill | |
| 102 | Raised sleeping platform | ⚠️ | A box; the floor itself doesn't step | L |
| 103 | Sunken living room | ❌ | One floor level | L |
| 104 | Ceiling fan | ✅ | Boxes / cylinders | |
| 105 | Lower false ceiling in the bathroom for services | ❌ | One ceiling height | C |

## E. Floors

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 106 | Wood floor in the bedrooms | ✅ | Tour finishes: wood | |
| 107 | Tiles in the kitchen | ✅ | Tour finishes: tile | |
| 108 | Marble floor in the living room | ❌ | Floors pick from wood / tile / decking only (index.html FINISH) | F |
| 109 | Herringbone parquet | ❌ | No such floor or texture | F, T |
| 110 | Terrazzo | ❌ | Same | F, T |
| 111 | Carpet in the bedroom | ❌ | Same | F, T |
| 112 | Darker wood floor | ❌ | Floor materials fixed (a tinted oak would do) | F |
| 113 | Large grey porcelain tiles | ❌ | Same | F, T |
| 114 | One floor throughout | ✅ | Finishes for every room (of the three) | |
| 115 | Rug under the bed | ✅ | rug() | |
| 116 | Change the rug colour | ✅ | | |
| 117 | Decking on the terrace | ✅ | Default | |
| 118 | Outdoor tiles on the terrace | ✅ | Finishes: tile | |
| 119 | Patterned cement tiles in the bathroom | ❌ | No texture | F, T |
| 120 | Floor border / inlay | ⚠️ | Thin box on the floor | F |
| 121 | Threshold strip between floors | ✅ | Box | |
| 122 | Note underfloor heating here | ❌ | No notes | Q |
| 123 | Polished concrete / epoxy | ❌ | No such floor | F, T |
| 124 | 60×120 tile layout | ❌ | Floor textures fixed | F, T |
| 125 | Step down to the terrace | ❌ | One floor level | L |

## F. Wall finishes and paint

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 126 | Paint the living-room walls sage green | ⚠️ | Only by panels on each wall face; all walls share one material | F |
| 127 | One dark-blue accent wall | ✅ | Paint panel on that face | |
| 128 | Wallpaper in the bedroom | ❌ | No pattern texture | F, T |
| 129 | Bathroom tiles to half height | ❌ | Wet rooms are stone to the ceiling, by name | F |
| 130 | White bathroom wall tiles | ❌ | stoneWall is shared; changing it changes every version (refused) | F |
| 131 | Marble kitchen splashback | ✅ | splash param / box | |
| 132 | Wood panelling behind the bed | ✅ | oakSlats panel | |
| 133 | Exposed brick wall | ❌ | No texture | F, T |
| 134 | Concrete wall finish | ❌ | No texture | F, T |
| 135 | Mirror wall in the gym | ✅ | mirror panel | |
| 136 | All walls off-white | ❌ | limewash shared by every version | F |
| 137 | Facade colour | ❌ | The outside isn't modelled | L |
| 138 | Stone walls in the laundry | ❌ | Stone follows the room name | F, R |
| 139 | Paint the bathroom instead of stone | ❌ | Same | F |
| 140 | LED strip set into the wall | ✅ | ledStrip | |
| 141 | TV on a wall panel | ✅ | | |
| 142 | Acoustic panels | ✅ | Boxes | |
| 143 | Ceiling the same colour as the walls | ❌ | Ceiling material fixed | F |
| 144 | Wainscoting | ✅ | Boxes | |
| 145 | Tiled wall with a niche | ❌ | Recess | N |

## G. Kitchen

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 146 | Sage-green cabinets | ✅ | New material + version ternary | |
| 147 | White marble worktop | ✅ | marbleTop | |
| 148 | Add an island | ✅ | Sol route; plan outline | |
| 149 | Breakfast bar with stools | ✅ | | |
| 150 | Move the fridge to the other side | ✅ | run() params | |
| 151 | Dishwasher next to the sink | ✅ | Front panel box | |
| 152 | Hob on the island | ✅ | | |
| 153 | Change to an L-shaped kitchen | ⚠️ | Big rework; step budget | B |
| 154 | No uppers, open shelves | ✅ | | |
| 155 | Uppers to the ceiling | ✅ | | |
| 156 | Pantry cupboard | ✅ | | |
| 157 | Black bar handles | ✅ | Boxes | |
| 158 | Handleless push-to-open | ✅ | | |
| 159 | Wine fridge | ✅ | | |
| 160 | Double sink | ✅ | sinkW + plan block | |
| 161 | Coffee station | ✅ | | |
| 162 | Cabinet doors that open | ✅ | openable | |
| 163 | Under-cabinet lighting | ⚠️ | ledStrip glows but lights nothing | E |
| 164 | Different range hood | ✅ | | |
| 165 | Oven tower | ✅ | Exists | |
| 166 | Worktop at 95 cm | ✅ | | |
| 167 | Pull-out bin | ✅ | openable drawer | |
| 168 | Microwave in the uppers | ✅ | | |
| 169 | Glass-front uppers | ✅ | displayGlass | |
| 170 | Patterned tile splashback | ❌ | No texture | T |
| 171 | Boiling-water tap | ✅ | Approximate | |
| 172 | Corner carousel | ✅ | Approximate | |
| 173 | Breakfast table | ✅ | | |
| 174 | Open the kitchen to the living room | ⚠️ | Wall removal | W |
| 175 | A Bosch oven like this photo | ⚠️ | Boxes from the reference; no product models | M |

## H. Bathrooms

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 176 | Move the toilet to the other wall | ✅ | wc() + plan block | |
| 177 | Wall-hung toilet | ✅ | | |
| 178 | Add a bidet | ✅ | | |
| 179 | Walk-in shower instead of the bath | ✅ | Glass + tray boxes | |
| 180 | Freestanding oval bath | ⚠️ | Box / cylinder approximation | M |
| 181 | Double vanity | ✅ | vanity() | |
| 182 | Floating vanity | ✅ | | |
| 183 | Lit mirror | ✅ | mirror + glow | |
| 184 | Mirror cabinet | ✅ | medCabinet | |
| 185 | Heated towel rail | ✅ | GLB | |
| 186 | Shower niche | ❌ | Recess | N |
| 187 | Rain shower head | ✅ | | |
| 188 | Glass shower screen | ✅ | | |
| 189 | Different tile colour | ❌ | stoneWall shared | F |
| 190 | Black taps | ✅ | | |
| 191 | Skylight in the bathroom | ❌ | No roof | C |
| 192 | Window in the bathroom | ✅ | **new** | |
| 193 | Frosted bathroom window | ✅ | **new** | |
| 194 | Make the bathroom bigger | ⚠️ | Wall move | W |
| 195 | Washer and dryer in the bathroom | ✅ | | |
| 196 | Stack the washer and dryer | ✅ | | |
| 197 | Grab bars | ✅ | | |
| 198 | Bench in the shower | ✅ | teak seat GLB | |
| 199 | Vessel basin | ✅ | Approximate | |
| 200 | Low privacy wall for the WC | ⚠️ | 3D box only | W |
| 201 | Turn the guest WC into a full bathroom | ⚠️ | Needs a bigger room | W, B |
| 202 | Extractor fan | ✅ | grille | |
| 203 | Sliding bathroom door | ✅ | **new** | |
| 204 | Towel hooks | ✅ | | |
| 205 | Floor tiles different from the wall tiles | ❌ | Both are the stone material | F |

## I. Bedrooms

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 206 | Bed on the other wall | ✅ | | |
| 207 | King-size bed | ✅ | | |
| 208 | Upholstered headboard | ✅ | | |
| 209 | Nightstands | ✅ | | |
| 210 | Floating nightstands | ✅ | | |
| 211 | Wardrobe along this wall | ✅ | | |
| 212 | Sliding wardrobe doors | ✅ | | |
| 213 | Mirrored wardrobe doors | ✅ | | |
| 214 | Walk-in wardrobe shelving | ✅ | | |
| 215 | Desk | ✅ | | |
| 216 | Fold-down desk | ✅ | | |
| 217 | Dressing table | ✅ | | |
| 218 | TV facing the bed | ✅ | | |
| 219 | Reading lights over the bed | ✅ | sconce (fitting) | |
| 220 | Blackout curtains | ✅ | | |
| 221 | Bunk bed | ✅ | Approximate | |
| 222 | Cot | ✅ | Approximate | |
| 223 | Window seat | ✅ | | |
| 224 | Bench at the foot of the bed | ✅ | | |
| 225 | Ceiling fan | ✅ | | |
| 226 | Different bedding colours | ✅ | | |
| 227 | Reading-corner armchair | ✅ | chair() | |
| 228 | Storage bed | ✅ | | |
| 229 | Make it a home office (and call it that) | ⚠️ | Furniture yes; the name no | R |
| 230 | Wall shelves | ✅ | | |

## J. Living and dining

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 231 | Turn the sofa to face the window | ✅ | | |
| 232 | Different sofa fabric | ✅ | | |
| 233 | Two sofas instead of the L | ✅ | | |
| 234 | Add an armchair | ✅ | | |
| 235 | Bigger coffee table | ✅ | | |
| 236 | Round dining table | ✅ | | |
| 237 | Dining for eight | ✅ | | |
| 238 | Bench seating at the table | ✅ | | |
| 239 | Move the TV wall | ✅ | Locked: refused unless named, then allowed | |
| 240 | Fireplace under the TV | ✅ | Approximate | |
| 241 | Built-in bookshelves | ✅ | | |
| 242 | Home bar | ✅ | | |
| 243 | Piano | ✅ | Approximate | |
| 244 | Floor lamp that lights the corner | ⚠️ | The lamp, not its light | E |
| 245 | Pendant over the dining table | ✅ | Fitting (glow) | |
| 246 | Plants | ✅ | | |
| 247 | Wall art | ✅ | | |
| 248 | Gallery wall | ✅ | | |
| 249 | Media console | ✅ | | |
| 250 | Different dining chairs | ✅ | | |
| 251 | Sideboard | ✅ | Buffet niche locked | |
| 252 | Room divider | ✅ | | |
| 253 | Bigger living room | ⚠️ | Wall move | W |
| 254 | Projector screen | ✅ | | |
| 255 | This exact IKEA KIVIK sofa | ⚠️ | Boxes from the photo | M |

## K. Lighting and electrical

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 256 | Downlights in the living room | ✅ | downlight glow | |
| 257 | Make the room brighter | ❌ | Room lights are the viewer's | E |
| 258 | Warmer light | ❌ | Same | E |
| 259 | Spotlight on the painting | ⚠️ | Fitting yes, beam no | E |
| 260 | LED strip under the bed | ✅ | Glow | |
| 261 | Chandelier | ✅ | Approximate | |
| 262 | Sconces either side of the mirror | ✅ | | |
| 263 | Lamps that really light the corner | ⚠️ | A THREE light could be added in furnish, but nothing teaches or caps it | E |
| 264 | Dimmer / lighting scenes | ❌ | Viewer | E |
| 265 | Evening view with the lights on | ❌ | Viewer | E |
| 266 | Sockets beside the bed | ✅ | Small boxes | |
| 267 | Light switch by the door | ✅ | | |
| 268 | USB sockets at the desk | ✅ | | |
| 269 | Floor socket under the sofa | ✅ | | |
| 270 | Terrace wall lights | ✅ | | |
| 271 | Lower the pendant | ✅ | | |
| 272 | Track lighting | ✅ | | |
| 273 | Thermostat on the wall | ✅ | | |
| 274 | Show me where the sockets are | ❌ | No electrical layer; no answer-only mode | Q |
| 275 | Pendants over the island | ✅ | | |
| 276 | Bathroom mirror light | ✅ | | |
| 277 | Night light in the corridor | ✅ | Fitting | |
| 278 | Ceiling fan with a light | ✅ | | |
| 279 | Brass light fittings | ✅ | | |
| 280 | Remove this light | ✅ | | |

## L. Storage and joinery

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 281 | Shoe cabinet at the entrance | ✅ | | |
| 282 | Storage under the stairs | ❌ | No stairs | L |
| 283 | Laundry cupboard | ✅ | | |
| 284 | Storage bench | ✅ | | |
| 285 | Floor-to-ceiling bookcase | ✅ | | |
| 286 | Coat hooks | ✅ | | |
| 287 | Broom cupboard | ✅ | | |
| 288 | Storage over the doors | ✅ | | |
| 289 | Shelves in a wall niche | ⚠️ | Shelves yes, the niche no | N |
| 290 | Wardrobe drawers and rails | ✅ | | |
| 291 | All joinery in walnut | ⚠️ | Many pieces: step budget | B |
| 292 | Utility sink in the laundry | ✅ | | |
| 293 | Pull-out ironing board | ✅ | | |
| 294 | Bike rack on the wall | ✅ | | |
| 295 | Pet feeding drawer | ✅ | | |

## M. Terrace and outdoors

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 296 | Outdoor dining table | ✅ | | |
| 297 | Sun loungers | ✅ | | |
| 298 | Planters along the parapet | ✅ | | |
| 299 | Pergola | ✅ | Boxes; README §5 says no pergola, Edit AI should say so | |
| 300 | Outdoor kitchen / BBQ | ✅ | No terrace sink (README §5) | |
| 301 | Glass balustrade instead of the parapet | ❌ | Parapets are walls; no glass kind | W, O |
| 302 | Higher parapet for privacy | ✅ | **new** home parapet | |
| 303 | Privacy screen | ✅ | screen material | |
| 304 | Awning | ✅ | | |
| 305 | Outdoor lights | ✅ | Fittings | |
| 306 | Tiles on the terrace | ✅ | Finishes | |
| 307 | Artificial grass | ❌ | No such floor | F, T |
| 308 | Water feature | ✅ | Approximate | |
| 309 | Outdoor shower | ✅ | Approximate | |
| 310 | Hot tub | ✅ | Approximate | |

## N. Air conditioning and services

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 311 | Split AC on this wall | ✅ | ac() | |
| 312 | Move the AC | ✅ | | |
| 313 | Ducted AC with linear grilles | ✅ | | |
| 314 | AC bulkhead | ✅ | | |
| 315 | Water heater in the laundry | ✅ | | |
| 316 | Show the plumbing and drains | ❌ | No services layer | Q |
| 317 | Ceiling access panel | ✅ | | |
| 318 | Electrical panel box | ✅ | | |
| 319 | Gas line to the hob | ❌ | No services layer | Q |
| 320 | Bathroom ventilation | ✅ | | |

## O. Decor

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 321 | Curtain colour | ✅ | | |
| 322 | Cushions | ✅ | | |
| 323 | Throw blanket | ✅ | | |
| 324 | Books and vases on the shelves | ✅ | | |
| 325 | Hallway mirror | ✅ | | |
| 326 | Wall clock | ✅ | | |
| 327 | Put my own photo in this frame | ❌ | Art is one fixed texture; no uploads | T |
| 328 | Photo frames | ✅ | Generic | |
| 329 | Bigger plant | ✅ | | |
| 330 | Coloured glass vase | ✅ | | |

## P. The plan, rooms and the whole home

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 331 | Rename this room | ❌ | TEXT | R |
| 332 | Name the new room | ❌ | No TEXT may be added | R |
| 333 | Make this room a bathroom (wet floor and walls) | ❌ | Kind follows the name | R, F |
| 334 | Show room sizes | ⚠️ | It can reply with sizes (plan_rooms), but the prompt check grades a question as a bad edit | Q |
| 335 | How many m² is the flat? | ⚠️ | Same | Q |
| 336 | How much paint / tile do I need? | ❌ | No wall-area or quantity tool | Q |
| 337 | Do this in all versions | ✅ | | |
| 338 | Copy Karim's kitchen into Main | ⚠️ | Big; step budget | B |
| 339 | Undo the last change | ✅ | Undo button | |
| 340 | Add a tour stop in the kitchen | ✅ | Tour stops | |
| 341 | Start the walk-through from the terrace | ❌ | Start is computed from the entrance door | U |
| 342 | Export the plan to PDF / DWG | ❌ | Not an edit | U |
| 343 | Show before and after side by side | ❌ | Viewer | U |
| 344 | Make me a photo of this room | ❌ | That's Generate Photo Spot | U |
| 345 | Make the whole flat Scandinavian | ⚠️ | Dozens of pieces: step budget | B |

## Q. Accessibility and family

| # | Request | | Why | Fix |
|---|---|---|---|---|
| 346 | 90 cm doors for a wheelchair | ✅ | move_door / convert width | |
| 347 | Step-free shower | ✅ | | |
| 348 | Lower worktop section | ✅ | | |
| 349 | Handrail along the corridor | ✅ | | |
| 350 | Baby gate | ✅ | | |
| 351 | Changing table | ✅ | | |
| 352 | Dog crate built into the joinery | ✅ | | |
| 353 | Lever handles on every door | ❌ | No handles | O |
| 354 | More turning space in the bathroom | ⚠️ | Wall move | W |
| 355 | Home lift | ❌ | Single storey | L |

## Totals

355 requests: **227 ✅ (64%) · 49 ⚠️ (14%) · 79 ❌ (22%)**.

Requests each fix unlocks (⚠️ + ❌ rows naming it; a row can name two): W walls 28 · F room finishes 27 · O opening
looks 21 · T textures 14 · R room names 10 · B big jobs 8 · Q questions 8 · E lighting 8 · U viewer 6 · L levels 6 ·
N niches 5 · C ceilings 5 · M models 3.

## Fix catalogue

| Fix | What | How | Effort |
|---|---|---|---|
| **W** | Wall ops | `dxf_edit` add_wall (two faces from a centre line + thickness, snapped to the walls it meets, T-junctions cut), move_wall (both faces, junctions trimmed / extended), remove_wall (faces gone, the walls it met closed), set_thickness, curved walls as short segments, a low-wall kind (tour spec with height, like openings) and a glass-wall kind. Rooms re-derive from walls already. | 6–8 h |
| **F** | Room finishes | Tour `"rooms": {NAME: {floor, walls, ceiling, skirting, tileHeight}}` with any material name; index.html reads it (floor from any material, a full-height paint lining from the room skins, ceiling material, skirting height / off, stone to a height); a `set_room` tool. | 3–4 h |
| **T** | Texture library | Add CC0 textures (herringbone and dark oak, terrazzo, large porcelain, cement tile, carpet, brick, concrete, grass, wallpaper weaves) and their materials; let a reference photo become an art / photo texture. | 2–3 h + ~15 MB |
| **O** | Opening looks | Opening specs gain frame and leaf material, glass (clear / frosted / tinted), panes, leaves (double / French), style (flush, panelled, glazed, bi-fold, pocket, barn), handle and arch; index.html draws them; draw_opening adds double / bi-fold kinds. | 4–5 h |
| **R** | Room names and kinds | `dxf_edit` rename_room (change a TEXT's words) and add_room_label (TEXT on ISLAK, only through this op); a room-kind override in the tour (wet / dry / outdoor). | 1.5 h |
| **N** | Niches and recesses | Tour `"cuts"` (like the `--cut` flag, per version) with a recess depth and height range; a niche tool; furnish fills above / below. | 2–3 h |
| **E** | Real lighting | A furnish `lamp()` helper adding a capped number of THREE point / spot lights tied to fittings; room light brightness / warmth in the tour; instructions. | 2 h |
| **C** | Ceilings per room | Per-room ceiling height (and skylights as a hole in that room's ceiling with a glazed lantern) from the tour `rooms` spec. | 2 h on top of F |
| **B** | Big jobs | Plan first, then edit in stages (each staged edit saved), a larger step budget on Sol (60), and the Vercel 300 s limit in mind (stage per call). | 3 h |
| **Q** | Questions and notes | Answer-only mode (the prompt check passes questions; plan_rooms + a wall-length / area tool for paint and tile quantities); notes on elements (fire-rated, underfloor heating). | 2 h |
| **M** | Product models | A curated GLB library Edit AI can place (sofas, armchairs, baths, appliances), and optionally Meshy text-to-3D behind a cost confirmation. | 4–6 h + credits |
| **L** | Floor levels | Steps, platforms, sunken areas: per-region floor height. Stairs and lifts are out of scope for a one-storey flat. | 4 h (levels only) |
| **U** | Viewer, not Edit AI | Furniture toggle, door open state, walk start, export, before / after, photos: belong to the viewer / Photo Spot. | n/a |
