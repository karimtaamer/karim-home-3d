# Edit AI: the 50 hardest asks (26 Oct 2026)

The asks most likely to go wrong, picked from the 355 in `capability-audit.md` and written as a homeowner would type
them about this flat (Main: rooms LIVING ROOM, RECEPTION, DINING, KITCHEN, ENTRANCE, HALLWAY, MASTER BEDROOM, TOILET 1 =
master bath, TOILET 2 = guest WC, LAUNDRY, TERRACE). Ranked hardest first. Hard = many tools in one job, plan geometry
that must stay closed, 2D and 3D kept in step, judgement (structure, clearances, locks), ambiguity, or the time limit.
Use them as the live test set: run each on Main, Undo after, and score it against "Passes when".

**Status:** ✅ the tools can do it · ⚠️ the tools can, but it is big / easy to get half right · ❌ a known gap.

| # | Ask | Takes | Why it's hard | Passes when | |
|---|---|---|---|---|---|
| 1 | Swap the laundry and the guest WC | rename_room ×2, WC / basin / washer / dryer moved in furnish + plan outlines, wet finishes, doors checked | Two rooms' contents in one job; outlines and 3D must move together; easily runs out of time | Names swapped, every fixture in its new room on both views, doors still clear | ⚠️ |
| 2 | Split the reception to make a guest bedroom with its own shower room | 2 partitions, 2 doors, 2 room names (one wet), shower / WC / basin, bed, wardrobe | Biggest layout job: new rooms, wet kind from the name, clearances, staged saves | Two named rooms, closed walls, doors that open into clear floor, fixtures sized for real | ⚠️ |
| 3 | Copy Karim's version's kitchen into Main | Read the other version's furnish branches and plan; rebuild them for Main only | Cross-version: furnish branches on version, the plan is a different file, specs live per version | Main's kitchen matches Karim's; Karim's version unchanged | ⚠️ |
| 4 | Put these bathroom finishes in all versions | set_room per version | Room specs live in each version's own tour; one message only writes the version you are on | Both versions show the finishes | ❌ |
| 5 | Remove the wall between the kitchen and the entrance and add an island facing the entrance | remove_wall, island in furnish + outline, kitchen run ends | Open plan: the wall's junctions, the run's ends, island clearance (≥ 1 m), structural warning | Wall gone and closed up on both sides, island with 1 m+ all round, engineer note | ✅ |
| 6 | Take 40 cm from the living room into the master bedroom, keep the bed centred and the wardrobe on its wall | move_wall, bed / wardrobe / living pieces re-placed, outlines | Moving a wall that furniture on both sides depends on; the TV wall nearby is locked | Wall moved 40 cm, bed centred, nothing in the wall, locks hold | ✅ |
| 7 | Enclose half of the terrace as a glass sunroom with a tiled floor | add_wall (glass, full height) ×2–3, room label, kind dry, floor, ceiling | Parapet vs full walls, outdoor → indoor kind, glass walls meeting the parapet | Named sunroom, glass walls closed to the building, tiled floor, ceiling | ✅ |
| 8 | Make the guest WC a full bathroom by taking 60 cm from the hallway | move_wall, door moved, shower added, finishes | The hallway must stay ≥ 90 cm; the door and its swing move with the wall | Bigger WC with a shower, hallway still ≥ 90 cm, door clear | ✅ |
| 9 | Make the whole flat Scandinavian: pale oak floors, white walls, linen sofas, oak furniture | set_room ×9, materials, many furnish pieces | Dozens of edits: needs planning and save_progress, or it times out | Every room done or saved in parts, with what's left said | ⚠️ |
| 10 | Paint every room a different colour from this photo's palette | Vision on the reference, set_room ×9 | Reading colours from a photo, mapping them to rooms sensibly | Nine rooms painted, colours visibly from the photo | ✅ |
| 11 | Turn the terrace slider into a window with a 60 cm wall under it, and give the terrace a new glass door from the dining room | set_openings kind / sill, add_opening glass_slider | Two openings, one on another wall; terrace access must survive | Window with sill 0.6 where the slider was; new door from the dining room | ✅ |
| 12 | French doors from the dining room to the terrace, opening out, with brass handles | convert_opening double_door, opens outward, set_openings style glazed + handle | Double-leaf detection, outward swing over the terrace, glazed leaves | Two glazed leaves opening onto the terrace, brass levers | ✅ |
| 13 | A walk-in wardrobe in the master bedroom with a partition and a sliding door | add_wall, add_opening sliding_door, room label, wardrobe joinery both sides | Partition placement vs bed clearance; the new room's name | Closed partition, sliding door, wardrobes inside, bed still 60 cm clear | ✅ |
| 14 | A study in the reception corner behind a glass wall with a pocket door, desk, shelves and a lamp | add_wall glass, pocket_door, label STUDY, furnish, lamp() | Glass wall + door in it + furniture + a real light | Glass-walled study with a pocket door and a lit desk | ✅ |
| 15 | Make the entrance wall a gentle curve and put a bench along it | remove_wall, add_wall through, bench following the curve | Curved wall junctions; furniture along a curve from boxes | Smooth curved wall joined at both ends; bench follows it | ✅ |
| 16 | Recess the TV into a niche in the living-room wall | add_niche, TV moved | The TV wall is a design lock: it must refuse unless the ask names it, and the wall may be too thin | Refused politely, or (when named) a niche no deeper than the wall allows | ✅ |
| 17 | Remove the column in the reception | remove (solid), structural warning | Locked (reception column face 17.542) and structural | Refused unless the column is named; never silently | ✅ |
| 18 | Thicker wall between the master bedroom and the living room for soundproofing | set_wall_thickness keep N/S | Which face stays; the TV wall lock on the living side | Wall thicker on the bedroom side, locks hold | ✅ |
| 19 | All interior doors white, panelled, 2.2 m tall, with black handles | set_openings ×8 + home door height | Eight doors in one job; the front door shown shut | Every interior door changed, front door untouched | ✅ |
| 20 | A double-height living room | home ceiling up, every other room's ceilingHeight back down, tall windows | No mezzanine: needs the raise-all-then-lower-others recipe | Living room 4.5 m, every other room still 2.6 m, no gaps | ✅ |
| 21 | Lower the hallway ceiling to 2.3 m with a cove light | set_room ceilingHeight, furnish cove + lamp | Doors stay 2.1; the cove sits under the new ceiling | Hallway ceiling 2.3 with a lit cove, doors unchanged | ✅ |
| 22 | A sunken living room 30 cm down with two steps from the entrance | set_room floorLevel −0.3, steps in furnish at the opening | Steps at the right opening; furniture follows the level | Living floor 30 cm down, steps at the entrance opening, furniture on the floor | ✅ |
| 23 | Raise only the area under the bed 20 cm as a platform | Furnish platform (not the whole room) | Judgement: floorLevel is for the whole room | A platform under the bed, rest of the floor flat | ✅ |
| 24 | A shower niche at 1.1 m in the master bath with an LED strip and two shelves | add_niche on the shower wall, furnish shelves + strip | The right wall face inside the shower; 11 cm walls allow ~9 cm | Niche at 1.1 m, shelves and strip inside it | ✅ |
| 25 | Swap the bed and the wardrobe walls in the master bedroom | Two big pieces + outlines, window and door clearances | Wardrobe can't block the window; bed needs 60 cm sides | Both swapped, nothing blocks the window or the door | ✅ |
| 26 | Move the master bedroom door 50 cm and make it a pocket door so the wardrobe fits | convert_opening pocket_door, move, wardrobe resized | Three linked changes; wardrobe outline vs the new door | Pocket door 50 cm along, wardrobe longer, outlines match | ✅ |
| 27 | A window over the kitchen sink, 1.1 m up, centred on the sink, white frame | add_opening on the outer wall, set_openings sill / head / frame | Centre on a block (the sink); the uppers must clear it | Window centred on the sink, sill 1.1, white frame, uppers cut round it | ✅ |
| 28 | A bay window with a seat in the living room | Walls stepping out + 3 windows + seat | No bay op; exterior wall geometry by hand | A real bay, closed walls, seat inside | ⚠️ |
| 29 | A corner window in the master bedroom | Two windows meeting at the corner | The corner post stays (no corner-glass kind) | Two windows meeting at the corner (with a post) | ⚠️ |
| 30 | Close the hallway-dining doorway and open an arched one 1.5 m further along | remove_opening, add_opening opening, set_openings arch | Two openings + arch; the wall must take it | Old doorway walled up, arched opening 1.5 m on | ✅ |
| 31 | Turn the laundry into a pantry | Washer / dryer out, shelving, rename PANTRY, kind dry (wood floor) | Rename + kind + furniture in one go | Named pantry, wood floor, shelves, no appliances | ✅ |
| 32 | How many litres of paint for the living room and bedroom walls, two coats? | measure, arithmetic | Net wall area (openings off), coverage, coats: no edit | A number with its working; nothing changed | ✅ |
| 33 | How many 60×120 tiles for the kitchen and both bathrooms, with 10% waste? | measure, arithmetic (floor + wall tiles to height) | Which surfaces are tiled; wet-room wall tiles | A tile count with its working; nothing changed | ✅ |
| 34 | Put this photo of my grandparents in the frame above the sofa | save_picture, the right art piece re-skinned | Finding "the frame above the sofa"; photo upload | That frame shows the photo | ✅ |
| 35 | Replace the living-room sofa with a real mid-century sofa, same size, facing the TV | find_model, p.model sized + turned, outline | Model orientation and size; the outline stays matched | A modelled sofa, right size, facing the TV | ✅ |
| 36 | A chandelier over the dining table that really lights the table | find_model, lamp() beam onto the table | Model + real light; light count cap | Chandelier centred over the table, table lit | ✅ |
| 37 | Warm dim light in the bedroom, bright neutral light in the kitchen | set_room light ×2 | Two rooms, opposite settings | Both rooms lit as asked | ✅ |
| 38 | A skylight over the kitchen island | set_room skylights | It's a flat in a building: should say a skylight needs a roof above | Says so, or adds it only if confirmed top floor | ✅ |
| 39 | A 1.1 m glass balustrade round the terrace | mark_wall glass + height on each parapet run | Several parapet runs, each found and marked | Every parapet run glass at 1.1 m | ✅ |
| 40 | A half-height wall with an oak top between the dining area and the reception | add_wall height 1.1 + oak cap in furnish | Open-plan boundary placement; cap matches the wall | A low wall with an oak top, rooms still named | ✅ |
| 41 | Widen the front door to 1 m, walnut, with a brass lever | move_door / convert width, set_openings leaf / handle | The front door is a block and shown shut | 1 m walnut front door with a brass lever | ✅ |
| 42 | The guest WC door hits the toilet: make it open outward | convert_opening opens | Clearance judgement; outward over the hallway | Door swings into the hallway, clear of the WC | ✅ |
| 43 | Double doors between the reception and the dining area | They're open plan: a wall first, then double_door | Judgement: there is no wall to put doors in | Asks, or builds the wall and the doors | ✅ |
| 44 | Move the AC above the window and box the pipe run to the outside wall | 3D-only AC + bulkhead path | Pipe route along walls; nothing on the plan | AC over the window, bulkhead to the outer wall | ✅ |
| 45 | Change the U kitchen to a galley with a 1.2 m aisle | run() rework, appliances, outlines | Reworking the run builder within the step budget | Two parallel runs, 1.2 m apart, appliances placed | ⚠️ |
| 46 | Mirror the master bathroom left to right | Every fixture + outlines + door | Many pieces mirrored about the room's axis | Mirror image on both views, door still works | ⚠️ |
| 47 | Make it look like this (a Pinterest photo of a whole living room) | Vision, finishes, models, many pieces | Interpreting a whole look; big job | Recognisably the photo's look, saved in parts | ⚠️ |
| 48 | اقفل باب المطبخ واعمل باب جديد من ناحية المدخل | remove_opening + add_opening on another wall, in Arabic | Arabic ask; which kitchen door, which wall faces the entrance | Old door walled, new one onto the entrance; reply in Arabic | ✅ |
| 49 | Mark the underfloor heating and the fire-rated doors, and tell me the tiled floor area | set_home notes ×n, measure | Notes on the right places + a number | Notes pinned, an area with its working | ✅ |
| 50 | Move the terrace door 1 m south and make the terrace parapet 1.4 m for privacy | move (a slider is a window on the plan), home parapet | Slider = window lines; parapet height is home-wide | Slider 1 m south, every parapet 1.4 m | ✅ |

## Known gaps these surface

- **#4:** room finishes, opening looks, notes and other tour specs only reach the version you're on. "In all versions"
  works for furnish.js (shared) but not for these. Fix: let set_room / set_openings / set_home take `versions: "all"`
  and write every version's tour in the same revision set.
- **#20:** a room's ceiling can only go below the home's. Taller rooms use the raise-all-then-lower-others recipe
  (enforced, with that hint, since 26 Oct).
- **#28, #29:** no bay or corner-glass op.
- **#1, #2, #3, #9, #45–47:** possible, but big. They need planning and save_progress, and are the first to try live.
