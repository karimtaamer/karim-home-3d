#!/usr/bin/env python3
"""Main's electrical, lighting and low-current points -> electrical-kareems-changes.json (Main only).

    python3 build_electrical.py            # writes electrical-kareems-changes.json; prints counts by type

Source: the designer's "Furniture plan" + "Upper lighting with furniture" (Lotus apartment, 1st issue 20-08-2026), applied
to Main's layout as it is (no wall, room or furniture moves). Each point is given a rough spot inside its room and the wall
it sits on; the script finds that wall face in model-kareems-changes.js (a ray from the spot), so every plate sits on a
real wall. Points with `at` instead of `wall` (ceiling spots, points inside joinery) keep their coordinates.
Heights are the plan's (cm from the slab) unless the point is adapted to Main's furniture; `status` says which:
  plan     - as on the electrical sheets (same room, same use; position fitted to Main's walls)
  adapted  - the plan's point moved or changed to fit Main (why in `note`)
  added    - not on the sheets, needed by Main (heaters, hood, fans, DB, router, doorbell ...)
  existing - already modelled in furnish-kareems-changes.js; listed so it gets a label (no new 3D part)
index.html (electrical.js) builds the 3D parts and labels from the JSON; drawing.js draws the 2D layer.
"""
import json, math, subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "electrical-kareems-changes.json"
M = json.loads(subprocess.run(["node", "-e", 'global.window={};require("./model-kareems-changes.js");'
                               'process.stdout.write(JSON.stringify(window.MODEL))'], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout)
CEIL = M["ceiling"]

EDGES = []
for w in M["walls"]:
    for ring in [w["outer"], *w.get("holes", [])]:
        for i in range(len(ring)):
            EDGES.append((ring[i - 1], ring[i]))
DIRS = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}


def face(x, y, wall, reach=2.5):
    """The wall face hit from (x, y) going towards `wall` (N/E/S/W): the point on it, 3 mm proud."""
    dx, dy = DIRS[wall]
    best = None
    for (ax, ay), (bx, by) in EDGES:
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-12:
            continue
        t = ((ax - x) * ey - (ay - y) * ex) / den
        u = ((ax - x) * dy - (ay - y) * dx) / den
        if 1e-6 < t < reach and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best):
            best = t
    if best is None:
        raise SystemExit(f"no wall {wall} of ({x}, {y}) within {reach} m")
    return round(x + dx * (best - 0.003), 4), round(y + dy * (best - 0.003), 4)


P = []        # points
LINES = []    # linear LED runs (new only)
BANKS = {}    # switch bank id -> point


def pt(kind, room, label, *, wall=None, at=None, x=None, y=None, h=None, status="plan", note="", **kw):
    """wall: the wall the plate is on (N = the room's north wall, so it faces south); x / y: where along it.
    proud: metres out from the wall face, for plates on a cladding (the kitchen's 15 mm stone splashback)."""
    if wall:
        fx, fy = face(x, y, wall)
        facing = OPP[wall]
        if (d := kw.pop("proud", 0)):
            fx, fy = round(fx - DIRS[wall][0] * d, 4), round(fy - DIRS[wall][1] * d, 4)
    else:
        fx, fy = at
        facing = kw.pop("facing", None)
    d = {"id": kw.pop("id", f"{kind}-{len(P) + 1}"), "type": kind, "room": room, "x": fx, "y": fy,
         "h": None if h is None else round(h, 3), "facing": facing, "label": label, "status": status}
    if note:
        d["note"] = note
    d.update(kw)
    P.append(d)
    if kind in ("switch", "acctl"):
        BANKS[d["id"]] = d
    return d


def spots(room, circuit, xy, label, status="plan", note=""):
    for (x, y) in xy:
        pt("spot", room, label, at=(round(x, 3), round(y, 3)), h=CEIL, circuit=circuit, status=status, note=note)


def row(a, b, n, fixed, along="x"):
    return [((a + (b - a) * (i + 0.5) / n), fixed) if along == "x" else (fixed, (a + (b - a) * (i + 0.5) / n)) for i in range(n)]


# ================================================================ Lighting (ceiling spots, 6 W)
# Spot counts by best practice (Karim 7 Nov 2026): spots ~1.3 m apart (half the ceiling height), 89 -> 70 in the flat.
# Living 11 -> 8, master bedroom 16 -> 10 (none over the pillows), guest bathroom 8 -> 6, entrance + corridor 14 -> 10,
# dining table rows 12 -> 8 (the pendants light the table). Master bathroom, kitchen, laundry and reception unchanged.
spots("Living room", "living-A", row(0.65, 4.25, 4, 3.75, "y"), "Ceiling spot — living room, half A (sofa side)", "adapted", "best-practice spot count (Karim 7 Nov 2026): about 1.3 m apart (half the 2.6 m ceiling), 89 -> 70 spots in the flat")
spots("Living room", "living-B", row(0.65, 4.25, 4, 5.35, "y"), "Ceiling spot — living room, half B (TV side)", "adapted", "best-practice spot count (Karim 7 Nov 2026): about 1.3 m apart (half the 2.6 m ceiling), 89 -> 70 spots in the flat")
spots("Master bedroom", "master-A", [(x, y) for x in (3.9, 4.85) for y in (7.45, 8.65)], "Ceiling spot — master bedroom, half A (window half)",
      "adapted", "6 bedroom spots in two halves (best-practice count, Karim 7 Nov 2026), off the pillow end of the bed (headboard west)")
spots("Master bedroom", "master-B", [(x, 6.25) for x in (3.9, 4.85)], "Ceiling spot — master bedroom, half B (door half)",
      "adapted", "6 bedroom spots in two halves (best-practice count, Karim 7 Nov 2026), off the pillow end of the bed (headboard west)")
spots("Master bedroom", "master-vanity-spots", [(3.0, 5.25), (4.05, 5.25)], "Ceiling spot — over the bedroom vanity",
      "adapted", "the two spots in front of Main's bedroom vanity, controlled by the vanity switch")
spots("Master bedroom", "master-dresser-spots", [(1.5, 5.575), (2.2, 5.575)], "Ceiling spot — dresser/wardrobe corner by the bathroom door",
      "adapted", "the two boxed spots by the wardrobe and bathroom door, controlled by the local switch at the marked wall")
spots("Master bathroom", "mbath", [(0.95, 6.65), (1.75, 6.95), (0.95, 8.15), (1.78, 8.45)], "Ceiling spot — master bathroom (basin / middle / shower / WC)",
      "adapted", "4 spots as on the plan, over Main's vanity, middle, shower and WC bay")
spots("Kitchen", "kitchen-A", [(x, 6.55) for x in (7.45, 8.35, 9.25)] + [(7.45, 7.4), (9.25, 7.4)], "Ceiling spot — kitchen, half A")
spots("Kitchen", "kitchen-B", [(8.35, 7.4)] + [(x, 8.3) for x in (7.45, 8.35, 9.25)], "Ceiling spot — kitchen, half B")
# Laundry (Dad's review (Karim 11 Nov 2026)): the 3 spots become one 90 cm recessed linear light (LINES below); the north spot sat on the cupboard edge.
spots("Guest bathroom", "gbath-spots", row(6.95, 9.1, 2, 14.2, "y") + row(6.95, 9.1, 2, 13.4, "y") + row(6.95, 9.1, 2, 12.6, "y"),
      "Ceiling spot — guest bathroom, vanity / middle / shower", "adapted", "all guest-bathroom spots share one key")
# Corridor redistributed as dad's sheet (Dad's review (Karim 11 Nov 2026)), measured off it and snapped to even spacing: one straight line on the
# lobby line (y 5.05) from the lobby to the bend, 1.44 apart; two spots flanking the front door; three in the upper corridor,
# 1.715 apart, with AP2 and the corridor sensor between the first two. Same count (10), one circuit.
spots("Entrance", "hallway", [(5.05, 5.05), (6.49, 5.05), (7.93, 5.05), (9.36, 5.05), (10.80, 5.05)],
      "Ceiling spot — entrance corridor and lobby (one line)", "adapted", "dad's redistribution: one straight line on the lobby line, evenly spaced")
spots("Entrance", "hallway", [(7.93, 4.03), (9.36, 4.03)], "Ceiling spot — inside the front door (either side of it)",
      "adapted", "dad's redistribution: two spots flanking the front door, in line with the corridor spots above")
spots("Entrance", "hallway", [(10.80, 6.25), (12.515, 6.25), (14.23, 6.25)], "Ceiling spot — upper corridor (laundry / guest bathroom)",
      "adapted", "dad's redistribution: three evenly spaced in one straight line (the spot on the diagonal is gone)")
spots("Reception", "reception-A", row(18.0, 21.0, 4, 3.0), "Ceiling spot — reception, half A (sofa side)")
spots("Reception", "reception-B", row(18.0, 21.0, 4, 4.6), "Ceiling spot — reception, half B (TV side)")
spots("Dining", "dining-spots", row(15.9, 20.7, 4, 6.65) + row(15.9, 20.7, 4, 8.55),
      "Ceiling spot — dining (one key)", "adapted", "all dining ceiling spots share one switch key")
# Buffet and coffee-corner spots removed (Karim 7 Nov 2026): the dining is two clean rows of 4; the buffet niche, its
# mirror and the coffee shelves have their own LED (accent-light power points below).

# Existing decorative fittings (furnish-kareems-changes.js), listed for their labels and switch.
for x in (16.705, 17.505, 18.305):  # centred on the DWG dining table (17.505, 7.846), as furnish-kareems-changes.js (7 Nov 2026)
    pt("pendant", "Dining", "Lantern pendant over the dining table", at=(x, 7.846), h=1.75, status="existing", circuit="dining-pendants")
for y in (6.231, 8.79):
    pt("pendant", "Master bedroom", "Bedside globe pendant", at=(2.48, y), h=1.15, status="existing", circuit="bedside-" + ("S" if y < 7 else "N"),
       note="two-way: switched from the plates over both nightstands")
pt("walllight", "Terrace", "Terrace wall light", at=(21.51, 5.775), h=2.0, facing="E", status="existing", circuit="terrace-wall")
pt("walllight", "Terrace", "Terrace wall light", at=(21.47, 8.6), h=2.0, facing="E", status="existing", circuit="terrace-wall")
pt("walllight", "Terrace", "Terrace wall light (party-mood height)", wall="W", x=21.8, y=2.45, h=2.2, circuit="terrace-wall",
   status="existing", note="the plan's wall light south of the window, now also modelled as a 3D sconce")
pt("walllight", "Entrance", "Wall sconce beside the front door", at=(7.63, 3.6), h=1.75, facing="N", status="existing", circuit="door-sconces")
pt("walllight", "Entrance", "Wall sconce beside the front door", at=(9.33, 3.6), h=1.75, facing="N", status="existing", circuit="door-sconces")
# Curtain pockets (Karim 7 Nov 2026): the plasterboard ceiling stops 0.20 short of each curtained window wall; a warm
# LED strip at the top of the 0.15 slot, on the room side, washes down the curtains (furnish-kareems-changes.js pockets).
POCKET_TOP = CEIL + 0.13
for lid, room, (x0, y0, x1, y1), lab, circ in [
    ("led-master-curtain", "Master bedroom", (3.118, 8.885, 5.078, 8.885), "LED in the curtain pocket over the bedroom window", "master-curtain"),
    ("led-reception-curtain", "Reception", (21.082, 2.772, 21.082, 5.558), "LED in the curtain pocket over the reception window", "reception-curtain"),
    ("led-slider-curtain", "Dining", (21.082, 5.84, 21.082, 8.379), "LED in the curtain pocket over the dining slider", "reception-curtain"),
    ("led-living-curtain", "Living room", (3.075, 1.54, 3.075, 3.45), "LED in the curtain pocket over the living-room window", "living-cove"),
    ("led-dining-curtain", "Dining", (16.025, 9.358, 17.884, 9.358), "LED in the curtain pocket over the dining window", "dining-curtain"),
    ("led-divider-curtain", "Reception", (17.542, 5.651, 21.062, 5.651), "LED in the reception / dining divider curtain box (reception side)", "reception-curtain"),
]:
    LINES.append({"id": lid, "type": "led", "room": room, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "h": POCKET_TOP,
                  "label": lab, "circuit": circ, "status": "added",
                  "note": "warm 24 V strip in a 0.15 x 0.15 plasterboard pocket, the opening plus its curtain stack-back each side; the curtain tracks are in the pocket too"})

LINES.append({"id": "linear-laundry", "type": "led", "room": "Laundry", "x0": 11.4, "y0": 7.25, "x1": 11.4, "y1": 8.15, "h": CEIL,
              "label": "Linear LED ceiling light 90 cm, 4000 K — laundry", "circuit": "laundry", "status": "added",
              "note": "Dad's review (Karim 11 Nov 2026): one recessed linear light along the room instead of spots, for even, shadow-free light; neutral white to see true colours"})

# ================================================================ Switch banks (centre 1.20; bedside 0.85)
SW = 1.20
def bank(id, room, title, gangs, *, two_way=None, **kw):
    lab = f"{len(gangs)}-gang switch — {title}"
    return pt("switch", room, lab, id=id, h=kw.pop("h", SW), gangs=gangs, two_way=two_way, **kw)

# Stacked plates (Dad's review (Karim 11 Nov 2026)): a standard Egyptian box takes 3 modules at most, so 4 keys become two 2-gang boxes, one above
# the other (main lights on top at 1.25, mood / accent below at 1.13; edges aligned, one plate range). `stack` names the
# group: the 2D plan draws one marker for it and the card shows the wall view.
TOP, LOW = 1.25, 1.13
# Front door flipped to hinge on the west jamb (#19): the switches move to the latch side, east of the door.
bank("sw-front-door", "Entrance", "inside the front door, top box",
     ["All hallway and lobby spots (two-way + lobby)", "Sconces beside the front door"],
     two_way="sw-dining-end,sw-lobby", wall="S", x=9.2, y=4.2, h=TOP, stack="front-door", status="adapted",
     note="the front door now hinges on the west jamb, so the switches sit on the latch side east of it; top box of two")
bank("sw-front-door-2", "Entrance", "inside the front door, lower box",
     ["Entrance console cove + mirror lights + pill sconce", "Gallery picture lights (4)"],
     wall="S", x=9.2, y=4.2, h=LOW, stack="front-door", status="adapted", note="lower box of two, under the main-light box")
bank("sw-dining-end", "Hallway", "hallway, dining end",
     ["All hallway and lobby spots (two-way)"],
     two_way="sw-front-door,sw-lobby", wall="S", x=14.35, y=6.2, status="plan",
     note="one two-way key for the full hallway including the lobby")
bank("sw-lobby", "Entrance", "lobby by the master-bedroom door (intermediate)",
     ["All hallway and lobby spots (intermediate: on / off from here too)"],
     two_way="sw-front-door,sw-dining-end", wall="N", x=5.85, y=5.2, status="added",
     note="Dad's review (Karim 11 Nov 2026): an intermediate switch so the corridor light can be switched when leaving the master bedroom or the living room; the corridor is then switched from three places")
bank("sw-living", "Living room", "living room, by the door",
     ["Spots, half A (sofa side)", "Spots, half B (TV side)", "Curtain-pocket LED, TV-wall sconces, TV console glow and picture lights"],
     wall="N", x=4.95, y=4.0)
# The bedroom and vanity plates sit side by side along the door wall: the vanity plate is nearer the vanity, and the
# main bedroom plate is nearer the entrance. They have distinct plan positions so both switch symbols remain visible.
bank("sw-master-door", "Master bedroom", "main bedroom lights by the door",
     ["Bedroom spots, half A", "Bedroom spots, half B", "Bedroom curtain-pocket LED"],
     wall="E", x=4.3, y=5.65, h=1.2, status="adapted", gang_circuits=["master-A", "master-B", "master-curtain"],
     note="three keys near the bedroom entrance; the separate vanity plate is farther along the wall toward the vanity")
bank("sw-master-dresser", "Master bedroom", "bedroom vanity, beside the main switch",
     ["Two spots over the vanity", "Vanity mirror glow", "Vanity LEDs: shelf column and jewellery tray"],
     wall="E", x=4.3, y=5.37, h=1.2, status="adapted",
     gang_circuits=["master-vanity-spots", "master-vanity-mirror", "master-vanity-led"],
     note="three vanity keys on the same wall, nearer the vanity; separated from the bedroom plate in both plan and 3D")
bank("sw-master-dresser-spots", "Master bedroom", "dresser spots by the bathroom-door wall",
     ["The two dresser/wardrobe corner spots marked on the plan"],
     wall="N", x=2.246, y=5.8, h=1.2, status="added", gang_circuits=["master-dresser-spots"],
     note="one key centred on the short return wall at the arrow, for the two boxed spots only")
# Bedsides: each of the two keys controls one pendant from either bedside.
for side, y in (("S", 6.231), ("N", 8.79)):
    bank(f"sw-bed-{side}", "Master bedroom", f"bedside ({'door' if side == 'S' else 'window'} side), over the nightstand",
         ["Bedside pendant, door side (two-way with the other bedside)", "Bedside pendant, window side (two-way with the other bedside)"],
         two_way=f"sw-bed-{'N' if side == 'S' else 'S'}", wall="W", x=2.6, y=y, h=0.85, status="adapted",
         gang_circuits=["bedside-S", "bedside-N"],
         note="both bedsides switch both pendants; the sockets are in the nightstand top, under a flap")
bank("sw-mbath", "Master bathroom", "inside beside the vanity socket",
     ["All spots (vanity, middle, shower and WC)", "Under-vanity LED, cabinet glow + shower-niche LED", "Exhaust fan"],
     wall="S", x=1.20, y=6.6, status="adapted",
     note="three keys on the short wall beside the 135 cm vanity socket; the exhaust fan has its own key")
# Karim's review (Karim 12 Nov 2026): the two boxes move beside the fridge, onto the south face of the fridge run's tall
# end panel (y 6.878, x 9.466-10.196), 0.12 in from the door wall: on your right as you open the door and step in.
# The door hinges on the south jamb and its leaf opens onto the south wall, so it never covers them.
KSW = (10.08, 6.875)
bank("sw-kitchen", "Kitchen", "kitchen, beside the fridge as you come in, top box",
     ["Spots, half A", "Spots, half B", "Ceiling exhaust fan"], at=KSW, facing="S", h=TOP, stack="kitchen",
     status="adapted", note="Karim's review (Karim 12 Nov 2026): moved from the south wall (x 9.15) to beside the fridge, on your right as you open the door; same 125 / 113 heights; on the tall end panel, so the back box needs a stud lining or a box set in the panel (the fridge's 5 cm vent gap is behind it)")
bank("sw-kitchen-2", "Kitchen", "kitchen, beside the fridge as you come in, lower box",
     ["Under-cabinet LED strips (upper cabinets)", "Plinth LED (lower cabinets)"], at=KSW, facing="S", h=LOW, stack="kitchen",
     status="adapted", note="Karim's review (Karim 12 Nov 2026): lower box: the cabinet LEDs, under the top box beside the fridge")
bank("sw-laundry", "Laundry", "laundry, inside on the toilet partition", ["Laundry linear light + exhaust fan", "Under-cabinet LED"], wall="E", x=11.55, y=8.02,
     status="adapted", note="on the inside partition, about one metre up the wall from the doorway, at the marked arrow tip")
# Guest bathroom (Karim 7 Nov 2026): inside, on the wall beside the door frame, over the vanity end, same 120 cm
bank("sw-gbath", "Guest bathroom", "guest bathroom, inside by the door (latch side)",
     ["All vanity, middle and shower spots", "Under-vanity, shelf + mirror glow + shower-niche LED", "Exhaust fan"], wall="S", x=14.15, y=7.3,
     status="adapted", note="Dad's review (Karim 11 Nov 2026): on the short wall between the door frame and the vanity corner, off the mirror wall and its cladding; the fan has its own key")
# By the hallway door: 8 keys in a 2 x 2 grid of 2-gang boxes (Dad's review (Karim 11 Nov 2026)): dining column left, reception right.
bank("sw-dining", "Dining", "dining, by the hallway door, top box",
     ["Lantern pendants", "All dining spots"], wall="S", x=15.22, y=6.2, h=TOP, stack="hall-dining",
     gang_circuits=["dining-pendants", "dining-spots"],
     status="adapted", note="the dining column of the 2 x 2 grid by the hallway door, main lights on top (the buffet mass covers the plan's wall)")
bank("sw-dining-2", "Dining", "dining, by the hallway door, lower box",
     ["Buffet niche LED + mirror glow", "North-window curtain-pocket LED"], wall="S", x=15.22, y=6.2, h=LOW, stack="hall-dining",
     gang_circuits=["dining-accent", "dining-curtain"], status="adapted", note="the dining column's lower box: accent lights")
bank("sw-reception", "Reception", "reception, by the hallway door, top box",
     ["Reception spots, half A", "Reception spots, half B"], wall="S", x=15.58, y=6.2, h=TOP, stack="hall-reception",
     gang_circuits=["reception-A", "reception-B"],
     status="adapted", note="the reception column of the 2 x 2 grid by the hallway door, main lights on top")
bank("sw-reception-2", "Reception", "reception, by the hallway door, lower box",
     ["Curtain-box LEDs (reception window, dining slider, divider)", "TV-wall niche (library) lights + picture lights over the sofa art"],
     wall="S", x=15.58, y=6.2, h=LOW, stack="hall-reception",
     gang_circuits=["reception-curtain", "reception-accent"], status="adapted", note="the reception column's lower box: accent lights")
# Karim's review (Karim 12 Nov 2026): the terrace plate was hidden by the slider curtain's stack (the curtain pocket runs to
# y 8.379), so it slides 0.35 north to y 8.60, just past the curtain, on the same wall line; the coffee-corner switch
# leaves that wall for the coffee corner's back wall, centred on the corner (x 20.474) between the shelves and the top.
bank("sw-office", "Dining", "by the terrace door, just past the curtain (terrace lights)",
     ["Terrace floor lighting (seat-lip LED) + BBQ counter LED", "Terrace wall lights", "Spotlights above the L-seat"], wall="E", x=20.9, y=8.60,
     status="adapted",
     note="Karim's review (Karim 12 Nov 2026): moved 0.35 m north (was y 8.25, behind the curtain's stack) to just past the curtain, so it shows; same 120 cm. Key 3 now switches the light outlet for the spotlights above the L-seat (no socket)")
bank("sw-coffee", "Dining", "coffee corner, centred over the counter", ["Coffee corner shelf LED"], wall="N", x=20.474, y=9.0,
     status="added", note="Karim's review (Karim 12 Nov 2026): on the coffee corner's back wall, centred on it, where you stand to use it; 120 = 20 cm over the marble, under the shelves (1.63)")

# AC controllers (wall thermostats), 1.50
pt("acctl", "Living room", "AC controller — living room split", wall="N", x=4.75, y=4.0, h=1.5)
# (Karim 4 Nov 2026: no wall thermostats in the bedroom or by the dining door; those splits run on their remotes)

# ================================================================ Power
def sock(room, label, n=2, **kw):
    return pt("socket", room, label, gang=n, **kw)

# Living room
pt("multi", "Living room", "TV plate behind the TV — data, HDMI, TV + double socket", wall="E", x=5.7, y=2.25, h=1.2,
   parts=["D", "H", "TV", "2S"], note="hidden behind the screen (1.10–1.95)")
pt("multi", "Living room", "TV-console plate — data, HDMI, TV + double socket (boxes, soundbar)", wall="E", x=5.7, y=2.25 - 0.55, h=0.6,
   parts=["D", "H", "TV", "2S"], note="inside the floating console (0.45–0.72); HDMI conduit to the 120 plate")
sock("Living room", "Double socket 45 cm — sofa end table (lamp, chargers)", wall="N", x=3.45, y=3.9, h=0.45)
sock("Living room", "Double socket 90 cm — reading lamp over the end table", wall="N", x=3.75, y=3.9, h=0.9)
sock("Living room", "Double socket 45 cm — sofa corner", wall="N", x=4.6, y=3.9, h=0.45, note="clear of the art on the north wall")
sock("Living room", "Double socket 45 cm — chaise end", wall="S", x=4.95, y=1.0, h=0.45)
sock("Living room", "Double socket 45 cm — beside the TV wall (plant / cleaning)", wall="S", x=5.85, y=1.0, h=0.45)
pt("power", "Living room", "AC power point — living-room split (dedicated circuit)", wall="W", x=3.3, y=0.68, h=2.3, appliance="split AC", status="added")

# Master bedroom
# Flush wood flaps (Karim 4 Nov 2026): socket + 2 USB-C sunk in the top, under a lift-up flap (shown open), in place of wall sockets
FLAP = ["S", "C", "C"]
for side, y in (("door", 6.231), ("window", 8.79)):
    pt("flap", "Master bedroom", f"Flap in the nightstand top ({side} side) — socket + 2 USB-C (lamp, phones)", at=(2.41, y), h=0.55, facing="E",
       parts=FLAP, finish="walnut", status="adapted", note="the plan's bedside 70 points, moved into the nightstand: a flush walnut flap at the back of the top, the cable down inside to a box on the headboard wall behind it")
pt("flap", "Master bedroom", "Flap in the dresser top, under the mirror — socket + 2 USB-C (hair dryer, phone)", at=(3.37, 4.65), h=0.75, facing="N",
   parts=FLAP, finish="oak", status="adapted", note="the plan's 'table area' socket, moved off the wall into the dresser top: a flush oak flap at the back, under the mirror")
sock("Master bedroom", "Double socket 45 cm — by the door (vacuum)", wall="E", x=4.3, y=5.15, h=0.45)
pt("power", "Master bedroom", "AC power point — master split (dedicated circuit)", wall="S", x=3.95, y=5.0, h=2.3, appliance="split AC", status="added")
# Master bathroom
sock("Master bathroom", "Socket 135 cm — tiled wall left of the mirror, over the counter (shaver, hair dryer), splash-protected", n=1,
     wall="S", x=1.0, y=6.6, h=1.35, proud=0.012, status="adapted")  # on the 1 cm tile lining
sock("Master bathroom", "Socket inside the medicine cabinet, bottom right (toothbrush, shaver)", n=1, at=(0.591, 6.985), h=1.39, facing="E",
     status="added", note="on the cabinet's back panel, behind the mirrored leaves")
# The towel rail remains a passive towel holder: no electric towel heater or dedicated connection.
pt("power", "Master bathroom", "Electric instant water heater — inside the vanity (existing connection)", at=(0.566, 6.525), h=0.66, facing="E",
   appliance="electric instant water heater", status="existing",
   note="the selected water-heating approach for Main; the 3D model depicts a 7.5 kW unit, while the final unit and its electrical supply must be specified together")
pt("fan", "Master bathroom", "Exhaust fan — master bathroom (own switch key)", at=(1.78, 7.95), h=CEIL, status="added", circuit="mbath-fan")

# Kitchen
sock("Kitchen", "Double socket 130 cm — counter left of the sink", wall="N", x=6.95, y=8.5, h=1.3, proud=0.015)
sock("Kitchen", "Double socket 130 cm — counter right of the sink", wall="N", x=9.2, y=8.5, h=1.3, proud=0.015)
sock("Kitchen", "Socket 60 cm — water filter, under the sink", n=1, wall="N", x=8.8, y=8.5, h=0.6, appliance="water filter", note="under the sink, just east of the window (the wall under the window is the opening)")
sock("Kitchen", "Double socket 130 cm — for the fridge", wall="E", x=9.8, y=7.05, h=1.3, appliance="fridge", note="behind the fridge, as the plan")
sock("Kitchen", "Dishwasher socket — in the base under the raised dishwasher", n=1, wall="E", x=9.8, y=8.3, h=0.4, appliance="dishwasher",
   status="adapted", note="the plan has the dishwasher at the sink (60); Main's dishwasher is the raised column on the east run")
sock("Kitchen", "Double socket 130 cm — counter by the water dispenser", wall="E", x=9.8, y=8.95, h=1.3, proud=0.015, status="adapted", note="feeds Main's countertop water dispenser")
pt("water", "Kitchen", "Water outlet — filtered line for the plumbed countertop dispenser", wall="E", x=9.8, y=8.75, h=1.05, status="added",
   note="Dad's review (Karim 11 Nov 2026): a 1/4 inch filtered line from the filter under the sink (about 2 m under the counter) to a shut-off valve behind the dispenser")
sock("Kitchen", "Spare socket 130 cm — behind the dishwasher column (future freezer column)", n=1, wall="E", x=9.8, y=8.15, h=1.3, status="added",
     note="Dad's review (Karim 11 Nov 2026): spare, in case the raised dishwasher column is swapped for a tall freezer later; on its own breaker, separate from the fridge")
pt("power", "Kitchen", "Cooker point 60 cm — hob", wall="W", x=6.9, y=7.376, h=0.6, appliance="cooker / hob")
sock("Kitchen", "Extractor hood socket — inside the lift-up cabinet over the hood", n=1, wall="W", x=6.9, y=7.376, h=1.7, appliance="cooker hood", status="added",
     note="Dad's review (Karim 11 Nov 2026): 170, just above the canopy inside the lift-up cabinet (1.65–2.25), beside the duct, easy to reach")
sock("Kitchen", "Double socket 130 cm — counter by the hob (south)", wall="W", x=6.9, y=6.6, h=1.3, proud=0.015)
sock("Kitchen", "Double socket 130 cm — counter by the hob (north)", wall="W", x=6.9, y=8.15, h=1.3, proud=0.015)
sock("Kitchen", "Oven socket — behind the pan drawer under the oven", n=1, at=(8.117, 5.672), h=0.55, facing="N", appliance="built-in oven",
     status="adapted", note="plan: 130 on the south wall; in Main's tower the oven is 66.5–122.5, so the socket sits under it, reachable through the drawer; electrician to size it for the selected oven")
sock("Kitchen", "Microwave socket — behind the microwave in the tower niche", n=1, at=(8.117, 5.672), h=1.5, facing="N", appliance="microwave",
   status="adapted", note="plan and dad: 150, at the back of Main's microwave niche (127–164)")
pt("ledfeed", "Kitchen", "Plinth LED (lower cabinets) — driver behind the tower plinth, entrance end", at=(8.117, 5.672), h=0.15, facing="N", status="added",
   note="Dad's review (Karim 11 Nov 2026): moved out of the sink base (wet) to the entrance end, by the switches; reached by taking off the plinth panel")
pt("ledfeed", "Kitchen", "Under-cabinet LED (upper cabinets) — driver in the tower cupboard above the microwave", at=(8.117, 5.672), h=1.70, facing="N", status="added",
   note="Dad's review (Karim 11 Nov 2026): the upper-cabinet strips had a key but no power point; 170, above the plinth feed, inside the tower cupboard; low-voltage cable along the uppers")
pt("tv", "Kitchen", "TV point 180 cm (kitchen TV)", wall="S", x=8.75, y=6.2, h=1.8, status="adapted",
   note="Dad's review (Karim 11 Nov 2026): moved west, clear of the door: the open door leaf lies along this wall from x 9.3 to 10.2")
sock("Kitchen", "Double socket 180 cm — kitchen TV (recessed)", wall="S", x=8.95, y=6.2, h=1.8, status="adapted", note="recessed box so the TV hangs flat; clear of the door")
sock("Kitchen", "Socket 45 cm — possible floor-standing water cooler", n=1, wall="S", x=8.55, y=6.2, h=0.45, status="added",
     note="Dad's review (Karim 11 Nov 2026): for a water cooler that may stand here, at the entrance end")
pt("water", "Kitchen", "Water outlet 45 cm — possible floor-standing water cooler", wall="S", x=8.42, y=6.2, h=0.45, status="added",
   note="Dad's review (Karim 11 Nov 2026): filtered water with a shut-off valve, beside the cooler socket")
pt("phone", "Kitchen", "Phone point 150 cm", wall="S", x=8.75, y=6.2, h=1.5, status="adapted", note="moved off the pantry wall, east of the tower; under the TV point")
pt("fan", "Kitchen", "Ceiling exhaust fan — kitchen (own switch key)", at=(8.35, 7.85), h=CEIL, status="added", circuit="kitchen-fan",
   note="Dad's review (Karim 11 Nov 2026): general extract for heat, steam and smells beyond the hood; ducted out to the north wall by the window")

# Laundry
sock("Laundry", "Washer-dryer socket — inside the oak base", n=1, wall="N", x=11.9, y=8.5, h=0.25, appliance="washer-dryer (one machine)",
   status="adapted", note="Main's LG washer-dryer stands on a 0.35 base (Karim 9 Nov, one drawer): the socket is inside the base, beside the hoses. It washes and dries, so no separate stacked dryer or dryer point")
sock("Laundry", "Double socket 120 cm — counter (iron, steamer)", wall="N", x=11.15, y=8.5, h=1.2)
sock("Laundry", "Double socket 120 cm — passage wall", wall="E", x=11.6, y=7.6, h=1.2)
pt("power", "Laundry", "Instant water heater — Ariston Aures Slim Multi 9.5 kW — dedicated 50 A breaker, 10 mm² cable, 30 mA RCD",
   at=(11.156, 9.06), h=1.9, facing="S", appliance="electric instant water heater", status="existing",
   note="not on the Samra sheets (added for Main): the unit is modelled in the laundry upper cabinet, flat on its back panel, so this point only labels it")
sock("Laundry", "Socket 60 cm — robot vacuum dock, inside the joinery's bottom bay", n=1, wall="W", x=10.6, y=7.21, h=0.6,
   appliance="robot vacuum dock (Roborock-style, 34 x 49 x 52 cm)", status="added",
   note="on the back wall of the south bay of the tall joinery, over the dock's top (52 cm) and under the 71 cm clear needed to lift its tanks out: it plugs in behind, no cable across the floor")
pt("fan", "Laundry", "Exhaust fan — laundry (with the laundry light)", at=(11.4, 8.3), h=CEIL, status="added",
   note="Dad's review (Karim 11 Nov 2026): moved off the cupboard zone into the open ceiling in front of it, on the light's line")

# Guest bathroom
sock("Guest bathroom", "Socket 130 cm — by the door, near the vanity (shaver, hair dryer), splash-protected", n=1, wall="S", x=14.45, y=7.3, h=1.3,
     status="adapted", note="Dad's review (Karim 11 Nov 2026): off the mirror wall, on the short wall by the door; IP44 on an RCD")
# (the plan's 130 socket 'by the WC (bidet / smart seat)' is deleted: no smart seat, and it sat over the column by the basin)
pt("fan", "Guest bathroom", "Exhaust fan — guest bathroom (own switch key)", at=(12.9, 8.6), h=CEIL, status="added", circuit="gbath-fan")

# Entrance, hallway
sock("Entrance", "Double socket 45 cm — entrance corridor", wall="S", x=10.0, y=4.2, h=0.45, note="beside the console (cleaning)")
sock("Entrance", "Double socket 45 cm — lobby by the bedroom door", wall="S", x=4.9, y=5.0, h=0.45)
sock("Hallway", "Double socket 45 cm — hallway", wall="N", x=12.6, y=6.2, h=0.45)
pt("db", "Entrance", "Distribution board (DB) — 36-way, behind the entrance artwork", wall="S", x=7.0, y=4.2, h=1.8, w=0.45, hh=0.6,
   status="adapted", note="on the opposite side of the hall from its former position, concealed behind the entrance artwork; keep the artwork removable and confirm the panel remains accessible")
pt("intercom", "Entrance", "Building intercom handset — answers the street gate", wall="S", x=7.75, y=4.2, h=1.45, status="adapted",
   note="Dad's review (Karim 11 Nov 2026): the building's own intercom (one system for the whole building); there is no indoor screen for the flat's door. West of the door, since the door now hinges there and the switches moved east")
# Network (Karim 7 Nov 2026): the hub in the shoe cabinet, Cat6 from it to three ceiling access points (PoE) and the TV / desk plates.
pt("router", "Entrance", "Network hub — fibre box (ONT), router and 16-port PoE switch, in the space above the shoe cabinet", wall="S", x=10.8, y=4.2, h=2.35,
   status="added", id="hub", note="Dad's review (Karim 11 Nov 2026): kept at the entrance, in the void between the shoe cabinet top and the ceiling, behind a vented openable front; fibre, TV and every Cat6 cable run here")
sock("Entrance", "Double socket above the shoe cabinet — network hub power", wall="S", x=11.1, y=4.2, h=2.35, status="added")
pt("ap", "Entrance", "Wi-Fi access point AP2 (main) — upper corridor ceiling, by the kitchen and laundry", at=(11.46, 6.25), h=CEIL, status="added", id="ap-2",
   note="Dad's review (Karim 11 Nov 2026): moved from above the shoe cabinet into the middle of the upper corridor (central to the kitchen, laundry, guest bathroom and dining); between the first two corridor spots, beside the corridor sensor; Cat6 + PoE from the hub")
# (no indoor doorbell chime: the smart doorbell rings the phones and its own plug-in chime)
pt("intercom_out", "Entrance", "Smart video doorbell — outside the front door (camera + button, on your phones)", wall="N", x=9.2, y=3.0, h=1.35,
   status="adapted", note="Dad's review (Karim 11 Nov 2026): one smart doorbell outside, no indoor screen; a wired low-voltage feed so it is not battery-only; on the latch side of the flipped door")

# Dining, coffee corner
sock("Dining", "Double socket 45 cm — north wall (west)", wall="N", x=15.4, y=9.0, h=0.45)
sock("Dining", "Double socket 45 cm — north wall (by the table)", wall="N", x=18.6, y=9.0, h=0.45)
pt("power", "Dining", "AC power point — dining split (dedicated circuit)", at=(14.975, 9.4), h=2.3, facing="E", appliance="split AC", status="added")
sock("Dining", "Double socket 115 cm — water dispenser", wall="N", x=20.0, y=9.0, h=1.15, status="adapted",
     note="the plan's office sockets 110: Main's marble top is at 1.00, so 1.15; behind the dispenser (west end)")
sock("Dining", "Double socket 115 cm — espresso machine", wall="N", x=20.75, y=9.0, h=1.15, status="adapted",
     note="Karim's review (Karim 12 Nov 2026): moved 0.30 m east (was x 20.45, mid-corner) behind the espresso machine, to make room for the centred coffee-corner switch")
pt("multi", "Dining", "Desk plate 45 cm — double data + double socket for the flip desk and monitor", wall="N", x=20.9, y=9.0, h=0.45, parts=["2D", "2S"],
   status="adapted", note="Dad's review (Karim 11 Nov 2026): at 45 inside the flip desk's bay, so the computer cables stay hidden under the top; slack for the 0.80 roll-out; two Cat6 to the hub")
pt("water", "Dining", "Water outlet — line for the plumbed countertop dispenser (coffee corner)", wall="N", x=20.3, y=9.0, h=1.08, status="added",
   note="Dad's review (Karim 11 Nov 2026): a cold-water line with a shut-off valve behind the dispenser; the plumber takes the shortest route (dad suggests from the kitchen-sink filter)")

# Reception
pt("multi", "Reception", "TV plate behind the TV — data, HDMI, TV + double socket (recessed)", at=(17.545, 4.875), h=1.2, facing="E", parts=["D", "H", "TV", "2S"],
   status="adapted", note="Dad's review (Karim 11 Nov 2026): on the TV's power side, not the middle: the Hisense 75Q7N has its power and ports on the right seen from the front (the north end), about 25 cm in from the edge; still hidden by the 166.8 cm TV")
pt("multi", "Reception", "Niche plate 50 cm — data, HDMI, TV + double socket (soundbar, sub, box)", at=(17.27, 4.875), h=0.5, facing="E",
   parts=["D", "H", "TV", "2S"], status="adapted", note="Dad's review (Karim 11 Nov 2026): lined up under the TV plate, at the back of Main's low lit niche (0.30–0.69); HDMI conduit straight down")
sock("Reception", "Double socket 45 cm — left of the sofa", wall="S", x=18.15, y=2.5, h=0.45)
sock("Reception", "Double socket 45 cm — right of the sofa", wall="S", x=20.55, y=2.5, h=0.45)
sock("Reception", "Double socket 45 cm — marked wall by the reception entrance", wall="S", x=16.05, y=6.2, h=0.45,
     status="added", note="two plug-in outlets on the short wall circled by the reception entrance")
pt("phone", "Reception", "Phone point 45 cm — south-east corner", wall="E", x=20.9, y=2.4, h=0.45)
sock("Reception", "Double socket 45 cm — south-east corner", wall="E", x=20.9, y=2.75, h=0.45)
sock("Reception", "Double socket 45 cm — by the east sofa", wall="E", x=20.9, y=5.35, h=0.45)
sock("Reception", "Double socket 100 cm — TV-wall end (lamp on the run)", wall="S", x=17.6, y=2.5, h=1.0)
pt("power", "Reception", "AC power point — reception split (dedicated circuit)", wall="S", x=20.0, y=2.5, h=2.35, appliance="split AC", status="added")

# Terrace (weatherproof)
pt("wp", "Terrace", "Weatherproof socket — BBQ counter", at=(23.55, 9.248), h=1.12, facing="S", status="adapted",
   note="the plan's WP 130 at the sink corner: Main's BBQ counter has no sink, so it powers the BBQ / grill")
pt("wp", "Terrace", "Weatherproof socket 45 cm — on the pier between the window and the slider (outdoor TV)", wall="W", x=21.8, y=5.55, h=0.45)
pt("tv", "Terrace", "TV point 45 cm — outdoor TV", wall="W", x=21.8, y=5.9, h=0.45)
pt("wp", "Terrace", "Weatherproof socket 45 cm — south pier by the L seat", wall="W", x=21.8, y=2.15, h=0.45)
pt("lightout", "Terrace", "Light outlet (no socket) — spotlights above the L-seat, at the planter corner", wall="W", x=21.8, y=1.93, h=0.3, status="added",
   circuit="terrace-seat-spots", note="Karim's review (Karim 12 Nov 2026): no longer a socket: a switched lighting outlet (IP66 box, cable gland) hard-wired to the spotlights above the L-seat (the spike lights in the planter strip behind it); terrace plate key 3; on a 30 mA RCD")
pt("wp", "Terrace", "Weatherproof socket 45 cm — east parapet, general use", wall="E", x=24.3, y=5.7, h=0.45, status="added",
   note="Dad's review (Karim 11 Nov 2026): the far side of the terrace (heater, fan, string lights, cleaning); always on, IP66 on a 30 mA RCD; conduit in the parapet or under the deck")

# ================================================================ Motion / presence sensors (Karim 7 Nov 2026)
# Ceiling sensors that switch the lights, each centred between ceiling spots so it lines up with them. mmWave (Tuya
# Zigbee 24 GHz, mains L+N) keeps the light on while someone is still; PIR where people only walk through.
# Nothing outdoors (terrace: later, a door contact on the inside of the terrace door); nothing in the reception.
def sensor(room, label, xy, tech, status="added", note=""):
    pt("sensor", room, label, at=xy, h=CEIL, status=status, tech=tech, note=note)

sensor("Master bathroom", "Presence sensor (mmWave) — master bathroom", (1.35, 6.80), "mmWave",
       note="centred between the basin and middle spots, outside the shower and 1.2 m from the exhaust fan; sees the WC bay")
sensor("Guest bathroom", "Presence sensor (mmWave) — guest bathroom", (13.40, 8.025), "mmWave",
       note="Dad's review (Karim 11 Nov 2026): in line with the spots, on the middle column between its two spots; 0.75 m from the exhaust fan")
sensor("Laundry", "Motion sensor (PIR) — laundry, at the door end", (11.40, 7.05), "PIR",
       note="Dad's review (Karim 11 Nov 2026): at the door end of the linear light's line, so it catches you as you step in")
sensor("Kitchen", "Presence sensor (mmWave) — kitchen", (8.35, 6.975), "mmWave",
       note="Dad's review (Karim 11 Nov 2026): on the middle spot column, between its two southern spots; 0.88 m from the ceiling fan (PIR if the fan ever false-triggers it)")
sensor("Entrance", "Motion sensor (PIR) — entrance corridor", (7.21, 5.05), "PIR",
       note="Dad's review (Karim 11 Nov 2026): on the corridor line, between two spots, toward the lobby")
sensor("Entrance", "Presence sensor (mmWave) — upper corridor by the laundry and guest bathroom", (11.86, 6.25), "mmWave",
       note="Dad's review (Karim 11 Nov 2026): beside AP2, between the first two upper-corridor spots")
sensor("Dining", "Presence + light-level sensor — dining / reception, switch-off only", (16.50, 6.18), "mmWave", "added",
       note="Dad's review (Karim 11 Nov 2026): never switches the lights on; switches them off once the dining and reception are empty, and ignores daylight; in line with the dining spots, halfway to the wall")
sensor("Master bedroom", "Presence sensor (mmWave) — master bedroom, OPTIONAL, switch-off only", (4.375, 6.85), "mmWave", "optional",
       note="optional: never switches the light on, only off once the room is empty; centred between four spots")
sensor("Living room", "Presence sensor (mmWave) — living room, OPTIONAL, switch-off only", (4.55, 2.45), "mmWave", "optional",
       note="optional: never switches the light on, only off once the room is empty; between the two spot rows")

# ================================================================ Wi-Fi access points (Karim 7 Nov 2026)
# Ceiling access points, one network name, each on its own Cat6 from the hub (PoE: no socket). AP2 is with the hub above.
pt("ap", "Entrance", "Wi-Fi access point AP1 — ceiling between the bedroom and living-room doors", at=(5.425, 5.05), h=CEIL, status="added", id="ap-1",
   note="covers the master bedroom, master bathroom and living room; between the two lobby spots; Cat6 + PoE from the hub")
pt("ap", "Reception", "Wi-Fi access point AP3 — dining-side ceiling, just north of the divider curtain box", at=(18.3, 6.15), h=CEIL, status="added", id="ap-3",
   note="covers the reception, dining and terrace (through the glass); Karim 11 Nov 2026: moved 0.525 north (was y 5.625, on the curtain line) to 0.44 m north of the divider curtain pocket and 0.50 m short of the dining spot row; Cat6 + PoE from the hub")

# ================================================================ Accent-light power points (Karim 7 Nov 2026)
# Every light the 3D model and the renders show that had no feed: picture lights, lit niches and shelves, mirror glows,
# under-vanity / plinth / under-cabinet LED, terrace LED. One point per fitting or per LED driver (drivers sit in the
# joinery or a dry void; 24 V strips in wet rooms, IP65 outdoors). h = the box's centre, metres from the slab.
def feed(room, label, xy, h, facing=None, note="", circuit=None):
    pt("ledfeed", room, label, at=xy, h=h, facing=facing, status="added", note=note, **({"circuit": circuit} if circuit else {}))

feed("Reception", "Picture light over the sofa art (left) — wall box", (18.673, 2.073), 2.05, "N")
feed("Reception", "Picture light over the sofa art (right) — wall box", (20.003, 2.073), 2.05, "N")
feed("Reception", "LED driver in the TV box — 2 tall niches + low TV niche", (17.30, 3.30), 1.40, "E", "reached through the TV opening")
feed("Dining", "LED driver in the buffet — tall niche", (15.15, 7.18), 0.40, "E")
feed("Dining", "Buffet pebble-mirror glow — box behind the mirror", (14.99, 8.79), 1.60, "E")
feed("Dining", "Coffee corner — LED under the 2 shelves (driver in the drawer bay)", (20.47, 9.36), 0.90, "S")
feed("Dining", "Curtain-pocket LED, north window — driver above the plasterboard ceiling", (16.95, 9.40), 2.70, "S")
feed("Entrance", "Entrance console — cove, shoe shelf, header downlight, mirror (driver in the console)", (10.60, 3.75), 0.30, "N")
feed("Entrance", "Entrance pebble-mirror glow + pill sconce — box behind the mirror", (8.60, 5.50), 1.40, "S")
for i, (x, y, h, f) in enumerate([(7.0, 3.631, 2.075, "N"), (6.541, 3.85, 2.09, "E"), (6.541, 4.30, 1.73, "E"), (6.541, 3.95, 1.45, "E")], 1):
    feed("Entrance", f"Gallery picture light {i} of 4 — wall box", (x, y), h, f)
feed("Living room", "Picture light over the window-wall art — wall box", (3.62, 0.579), 2.345, "N")
feed("Living room", "Picture light over the door-wall art — wall box", (4.35, 4.412), 2.08, "S")
feed("Living room", "TV-wall linear sconce, south — wall box", (6.11, 1.10), 1.52, "W")
feed("Living room", "TV-wall linear sconce, north — wall box", (6.11, 3.40), 1.52, "W")
feed("Living room", "TV console under-glow — driver in the console", (5.93, 2.25), 0.44, "W")
feed("Master bedroom", "Bedroom vanity mirror glow — separately switched driver behind the mirror", (3.35, 4.59), 1.35, "N", circuit="master-vanity-mirror")
feed("Master bedroom", "Bedroom vanity LED — shelf column and jewellery tray driver", (2.82, 4.59), 0.65, "N", circuit="master-vanity-led")
feed("Master bathroom", "Under-vanity LED + medicine-cabinet glow — driver under the vanity", (0.84, 6.68), 0.28, "E", "24 V strip")
feed("Master bathroom", "Shower-niche LED — driver in the cabinet over the WC (dry)", (0.60, 7.75), 2.00, "E", "24 V IP67 strip in the niche")
pt("ledfeed", "Guest bathroom", "Under-vanity, shelf + mirror glow — wall box behind the vanity", wall="E", x=14.3, y=8.04, h=0.30, status="added",
   note="Dad's review (Karim 11 Nov 2026): on the east wall behind the vanity, reached through the cabinet; 24 V strip")
feed("Guest bathroom", "Shower-niche LED (2 niches) — wall box high on the south wall", (13.25, 6.907), 2.45, "N",
     "Dad's review (Karim 11 Nov 2026): on the south wall face over the door head, above the wet zones; 24 V IP67 strip in the niches")
feed("Laundry", "Under-cabinet LED — driver in the upper cabinet", (11.16, 8.96), 1.70, "S")
# Terrace LED feeds on the house wall (Dad's review (Karim 11 Nov 2026)): not out in the furniture; the low-voltage cable runs from here to the seat / counter.
pt("ledfeed", "Terrace", "Seat-lip LED — IP65 box on the house wall", wall="W", x=21.8, y=2.65, h=0.3, status="added",
   note="Dad's review (Karim 11 Nov 2026): moved from inside the seat storage to the house wall; cable under the deck to the seat")
pt("ledfeed", "Terrace", "BBQ counter LED — IP65 box on the house wall", wall="W", x=21.8, y=8.95, h=0.3, status="added",
   note="Dad's review (Karim 11 Nov 2026): moved from inside the BBQ counter to the house wall; cable under the deck to the counter")

# ================================================================ Curtain motor power (Dad's review (Karim 11 Nov 2026))
# An always-on point in every curtain box at the motor end of the track, for motorised curtains or outside shutters later.
# No wall switches: the motors run on their remote, app or voice.
for room, lab, xy in [
    ("Living room", "living-room window box, north end", (3.02, 3.40)),
    ("Master bedroom", "bedroom window box, east end", (5.03, 8.94)),
    ("Reception", "east-wall box, reception window (south end)", (21.137, 2.82)),
    ("Dining", "east-wall box, dining slider (north end)", (21.137, 8.33)),
    ("Dining", "dining window box, east end", (17.83, 9.413)),
    ("Reception", "divider curtain box, column end", (17.60, 5.651)),
]:
    pt("power", room, f"Curtain motor power — {lab}", at=xy, h=CEIL + 0.08, appliance="curtain motor (future)", status="added",
       note="Dad's review (Karim 11 Nov 2026): always-on point in the curtain box at the motor end; remote / app / smart control, no wall switch")

# ================================================================ Late additions (ids fixed, so the numbered ids above stay put)
# Karim's review (Karim 12 Nov 2026): two more double sockets at 30 cm, at his red marks: one in the lobby just east of
# the master-bedroom door (under the corridor switch), one in the entrance just west of the front door (under the intercom).
sock("Entrance", "Double socket 30 cm — lobby, just past the master-bedroom door", wall="N", x=5.85, y=5.2, h=0.30, status="added", id="socket-lobby-30",
     note="Karim's review (Karim 12 Nov 2026): at the red mark on the corridor wall east of the bedroom door, under the corridor switch")
sock("Entrance", "Double socket 30 cm — entrance, beside the front door", wall="S", x=7.75, y=4.2, h=0.30, status="added", id="socket-front-door-30",
     note="Karim's review (Karim 12 Nov 2026): at the red mark on the entrance wall just west of the front door, under the intercom handset")

# ================================================================ write
counts = Counter(p["type"] for p in P)
sockets = sum(1 for p in P if p["type"] in ("socket",))
legend = {
    "socket": "Socket (single or double)", "power": "Dedicated power point (appliance, AC, heater)", "wp": "Weatherproof outdoor socket",
    "multi": "Combined plate (data / HDMI / TV / sockets on one plate)", "data": "Data point, Cat6 RJ-45", "phone": "Phone point, RJ-12",
    "tv": "TV / antenna point", "sound": "Sound-system screen", "intercom": "Intercom screen", "intercom_out": "Outdoor intercom unit",
    "doorbell": "Doorbell push", "chime": "Doorbell chime", "switch": "Switch bank", "acctl": "AC controller", "spot": "Ceiling spot 6 W",
    "pendant": "Pendant light", "walllight": "Wall light", "fan": "Exhaust fan", "db": "Distribution board", "lcp": "Low-current panel",
    "router": "Network hub (fibre box, router, PoE switch)", "led": "Indirect LED strip", "sensor": "Ceiling motion / presence sensor (mmWave or PIR)", "ledfeed": "Accent-light power point (LED driver / picture-light box)",
    "ap": "Ceiling Wi-Fi access point (Cat6 + PoE from the hub)",
    "water": "Water outlet (filtered line + shut-off valve) for a plumbed appliance",
    "lightout": "Lighting outlet (switched light feed, no socket)",
}
OUT.write_text(json.dumps({
    "version": "kareems-changes",
    "source": "Designer's electrical plan, Lotus apartment: Furniture plan + Upper lighting with furniture, 1st issue 20-08-2026",
    "built_by": "build_electrical.py (edit there, then rerun)",
    "heights": "metres; the plan's heights are cm from the concrete slab, used as-is until the floor build-up is confirmed",
    "legend": legend, "points": P, "lines": LINES,
}, ensure_ascii=False, indent=1) + "\n")
print(f"{OUT.name}: {len(P)} points, {len(LINES)} LED lines")
for k, v in sorted(counts.items()):
    print(f"  {k:13s} {v}")
print("  by status:", dict(Counter(p['status'] for p in P)))

# ================================================================ stack check (dad's review, Karim 11 Nov 2026)
# The 2D plan looks down, so points at the same spot on a wall hide each other. drawing.js draws each group within
# STACK_R as one marker with a count and the heights; this lists the groups, and stops the build if two points in a group
# are at (almost) the same height too, which is a real clash, not a stack.
STACK_R, CLASH_H = 0.12, 0.06
CEILING_TYPES = {"spot", "fan", "sensor", "ap"}
wallish = [q for q in P if q["type"] not in CEILING_TYPES and q["h"] is not None]
seen, stacks, clashes = set(), [], []
for i, a in enumerate(wallish):
    if i in seen:
        continue
    grp = [a]
    for j in range(i + 1, len(wallish)):
        b = wallish[j]
        if j not in seen and any(math.hypot(b["x"] - g["x"], b["y"] - g["y"]) < STACK_R for g in grp):
            grp.append(b); seen.add(j)
    if len(grp) > 1:
        stacks.append(grp)
        hs = sorted(g["h"] for g in grp)
        clashes += [grp for k in range(len(hs) - 1) if hs[k + 1] - hs[k] < CLASH_H][:1]
print(f"  stacks (same plan spot, drawn as one marker): {len(stacks)}")
for g in stacks:
    print("   ", " / ".join(f"{q['id']}@{round(q['h'] * 100)}" for q in sorted(g, key=lambda q: -q["h"])))
if clashes:
    raise SystemExit("CLASH: points at the same spot and height: " + "; ".join(", ".join(q["id"] for q in g) for g in clashes))
