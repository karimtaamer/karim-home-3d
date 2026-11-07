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
spots("Laundry", "laundry", row(7.25, 8.85, 3, 11.4, "y"), "Ceiling spot — laundry")
spots("Guest bathroom", "gbath-spots", row(6.95, 9.1, 2, 14.2, "y") + row(6.95, 9.1, 2, 13.4, "y") + row(6.95, 9.1, 2, 12.6, "y"),
      "Ceiling spot — guest bathroom, vanity / middle / shower", "adapted", "all guest-bathroom spots share one key")
spots("Entrance", "hallway", [(6.75, 4.6), (9.55, 4.6), (11.225, 5.925), (13.225, 6.25),
                              (8.15, 4.6), (10.95, 4.6), (12.25, 6.25), (14.2, 6.25)],
      "Ceiling spot — entrance corridor (one two-way key)", "adapted", "all corridor spots on one two-way circuit from the front door and dining end")
spots("Entrance", "hallway", [(5.05, 5.05), (5.8, 5.05)], "Ceiling spot — lobby by the bedroom and living-room doors",
      "adapted", "the lobby spots join the hallway circuit")
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
]:
    LINES.append({"id": lid, "type": "led", "room": room, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "h": POCKET_TOP,
                  "label": lab, "circuit": circ, "status": "added",
                  "note": "warm 24 V strip in a 0.15 x 0.15 plasterboard pocket, the opening plus its curtain stack-back each side; the curtain tracks are in the pocket too"})

# ================================================================ Switch banks (centre 1.20; bedside 0.85)
SW = 1.20
def bank(id, room, title, gangs, *, two_way=None, **kw):
    lab = f"{len(gangs)}-gang switch — {title}"
    return pt("switch", room, lab, id=id, h=kw.pop("h", SW), gangs=gangs, two_way=two_way, **kw)

bank("sw-front-door", "Entrance", "inside the front door",
     ["Sconces beside the front door", "All hallway and lobby spots (two-way)", "Entrance console cove + mirror lights + pill sconce", "Gallery picture lights (4)"],
     two_way="sw-dining-end", wall="S", x=7.82, y=4.2)
bank("sw-dining-end", "Hallway", "hallway, dining end",
     ["All hallway and lobby spots (two-way)"],
     two_way="sw-front-door", wall="S", x=14.35, y=6.2, status="plan",
     note="one two-way key for the full hallway including the lobby")
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
bank("sw-kitchen", "Kitchen", "kitchen, by the door",
     ["Spots, half A", "Spots, half B", "Under-cabinet LED strips", "Plinth LED"], wall="S", x=9.15, y=6.2,
     status="adapted", note="light switches replace the old sound and intercom screens")
bank("sw-laundry", "Laundry", "laundry, inside on the toilet partition", ["Laundry spots + exhaust fan", "Under-cabinet LED"], wall="E", x=11.55, y=8.02,
     status="adapted", note="on the inside partition, about one metre up the wall from the doorway, at the marked arrow tip")
# Guest bathroom (Karim 7 Nov 2026): inside, on the wall beside the door frame, over the vanity end, same 120 cm
bank("sw-gbath", "Guest bathroom", "guest bathroom, inside beside the vanity socket",
     ["All vanity, middle and shower spots", "Under-vanity, shelf + mirror glow + shower-niche LED", "Exhaust fan"], wall="E", x=14.3, y=7.30,
     status="adapted", note="three keys inside, beside the vanity socket; the fan has its own key")
bank("sw-dining", "Dining", "dining, by the hallway door",
     ["Lantern pendants", "All dining spots", "Buffet niche LED + mirror glow", "North-window curtain-pocket LED"], wall="S", x=15.22, y=6.2,
     gang_circuits=["dining-pendants", "dining-spots", "dining-accent", "dining-curtain"],
     status="adapted", note="the plan puts the dining and reception banks on the wall by the hallway door; in Main the buffet mass covers that wall, so they sit on the south wall just right of the door")
bank("sw-reception", "Reception", "reception, by the hallway door",
     ["Reception spots, half A", "Reception spots, half B", "Both terrace-wall curtain boxes (reception window + dining slider)", "TV-wall niche (library) lights + picture lights over the sofa art"], wall="S", x=15.58, y=6.2,
     gang_circuits=["reception-A", "reception-B", "reception-curtain", "reception-accent"],
     status="adapted", note="beside the dining bank, on the south wall right of the hallway door (the buffet mass covers the plan's wall)")
bank("sw-office", "Dining", "coffee corner, by the terrace door",
     ["Terrace floor lighting (seat-lip LED) + BBQ counter LED", "Terrace wall lights", "Coffee corner shelf LED"], wall="E", x=20.9, y=8.25,
     status="adapted", note="the plan's office bank (balcony floor / balcony wall / office), by Main's coffee corner and terrace slider")

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
pt("power", "Kitchen", "Cooker point 60 cm — hob", wall="W", x=6.9, y=7.376, h=0.6, appliance="cooker / hob")
sock("Kitchen", "Extractor hood socket — over the hob, inside the upper", n=1, wall="W", x=6.9, y=7.376, h=2.1, appliance="cooker hood", status="added",
     note="separate supply for the extractor above the hob")
sock("Kitchen", "Double socket 130 cm — counter by the hob (south)", wall="W", x=6.9, y=6.6, h=1.3, proud=0.015)
sock("Kitchen", "Double socket 130 cm — counter by the hob (north)", wall="W", x=6.9, y=8.15, h=1.3, proud=0.015)
sock("Kitchen", "Oven socket — behind the pan drawer under the oven", n=1, at=(8.117, 5.672), h=0.55, facing="N", appliance="built-in oven",
     status="adapted", note="plan: 130 on the south wall; in Main's tower the oven is 66.5–122.5, so the socket sits under it, reachable through the drawer; electrician to size it for the selected oven")
sock("Kitchen", "Microwave socket — behind the microwave in the tower niche", n=1, at=(8.117, 5.672), h=1.45, facing="N", appliance="microwave",
   status="adapted", note="plan: 150; Main's microwave niche is 127–164")
pt("tv", "Kitchen", "TV point 180 cm (kitchen TV)", wall="S", x=9.35, y=6.2, h=1.8, status="adapted",
   note="the plan's south wall is Main's full-height pantry + tower: moved to the free wall east of the tower")
sock("Kitchen", "Double socket 180 cm — kitchen TV", wall="S", x=9.6, y=6.2, h=1.8, status="adapted")
pt("phone", "Kitchen", "Phone point 150 cm", wall="S", x=8.85, y=6.2, h=1.5, status="adapted", note="moved off the pantry wall, east of the tower")

# Laundry
sock("Laundry", "Washing-machine socket 60 cm — behind the oak base", n=1, wall="N", x=11.9, y=8.5, h=0.6, appliance="washing machine",
   status="adapted", note="Main's washer stands on a 0.76 base: the socket is inside the base, beside the hoses. No dryer in Main, so the plan's dryer point (120) is left out")
sock("Laundry", "Double socket 120 cm — counter (iron, steamer)", wall="N", x=11.15, y=8.5, h=1.2)
sock("Laundry", "Double socket 120 cm — passage wall", wall="E", x=11.6, y=7.6, h=1.2)
# No storage water heater in the laundry upper cabinet; it is storage now.
sock("Laundry", "Socket 60 cm — robot vacuum dock, inside the joinery's bottom bay", n=1, wall="W", x=10.6, y=7.21, h=0.6,
   appliance="robot vacuum dock (Roborock-style, 34 x 49 x 52 cm)", status="added",
   note="on the back wall of the south bay of the tall joinery, over the dock's top (52 cm) and under the 71 cm clear needed to lift its tanks out: it plugs in behind, no cable across the floor")
pt("fan", "Laundry", "Exhaust fan — laundry (with the laundry light)", at=(11.4, 8.85), h=CEIL, status="added")

# Guest bathroom
sock("Guest bathroom", "Socket 130 cm — by the vanity mirror (shaver, hair dryer)", n=1, wall="E", x=14.3, y=7.05, h=1.3)
sock("Guest bathroom", "Socket 130 cm — by the WC (bidet / smart seat)", n=1, wall="N", x=14.45, y=8.8, h=1.3)
pt("fan", "Guest bathroom", "Exhaust fan — guest bathroom (own switch key)", at=(12.9, 8.6), h=CEIL, status="added", circuit="gbath-fan")

# Entrance, hallway
sock("Entrance", "Double socket 45 cm — entrance corridor", wall="S", x=10.0, y=4.2, h=0.45, note="beside the console (cleaning)")
sock("Entrance", "Double socket 45 cm — lobby by the bedroom door", wall="S", x=4.9, y=5.0, h=0.45)
sock("Hallway", "Double socket 45 cm — hallway", wall="N", x=12.6, y=6.2, h=0.45)
pt("db", "Entrance", "Distribution board (DB) — 36-way, behind the entrance artwork", wall="S", x=7.0, y=4.2, h=1.8, w=0.45, hh=0.6,
   status="adapted", note="on the opposite side of the hall from its former position, concealed behind the entrance artwork; keep the artwork removable and confirm the panel remains accessible")
pt("intercom", "Entrance", "Intercom screen — answer the front door", wall="S", x=9.20, y=4.2, h=1.45, status="adapted",
   note="the only indoor intercom, beside the front door")
# Network (Karim 7 Nov 2026): the hub in the shoe cabinet, Cat6 from it to three ceiling access points (PoE) and the TV / desk plates.
pt("router", "Entrance", "Network hub — fibre box (ONT), router and 16-port PoE switch, inside the shoe cabinet", wall="S", x=10.8, y=4.2, h=0.3,
   status="added", id="hub", note="a vented compartment in the shoe cabinet (joiner to confirm which); fibre, TV, intercom and every Cat6 cable run here without a separate low-current panel")
sock("Entrance", "Double socket inside the shoe cabinet — network hub power", wall="S", x=11.1, y=4.2, h=0.3, status="added")
pt("ap", "Entrance", "Wi-Fi access point AP2 (main) — entrance ceiling, above the shoe cabinet", at=(10.25, 4.6), h=CEIL, status="added", id="ap-2",
   note="covers the entrance, hallway, kitchen, laundry and guest bathroom; on the corridor spot line, between two spots; Cat6 + PoE from the hub")
pt("chime", "Entrance", "Doorbell chime", wall="N", x=7.6, y=5.0, h=2.1, status="added")
pt("intercom_out", "Entrance", "Outdoor intercom unit — outside the front door (camera + call button)", wall="N", x=9.2, y=3.0, h=1.45,
   status="plan", note="the plan puts it outside the door at 120 on the 45° corner; Main's door has a flat wall, so beside the door at 1.45 (camera height)")
pt("doorbell", "Entrance", "Doorbell push — outside the front door", wall="N", x=7.8, y=3.0, h=1.3, status="added")

# Dining, coffee corner
sock("Dining", "Double socket 45 cm — north wall (west)", wall="N", x=15.4, y=9.0, h=0.45)
sock("Dining", "Double socket 45 cm — north wall (by the table)", wall="N", x=18.6, y=9.0, h=0.45)
pt("power", "Dining", "AC power point — dining split (dedicated circuit)", at=(14.975, 9.4), h=2.3, facing="E", appliance="split AC", status="added")
sock("Dining", "Double socket 115 cm — espresso machine", wall="N", x=20.0, y=9.0, h=1.15, status="adapted",
     note="the plan's office sockets 110: Main's marble top is at 1.00, so 1.15")
sock("Dining", "Double socket 115 cm — water dispenser", wall="N", x=20.45, y=9.0, h=1.15, status="adapted")
pt("multi", "Dining", "Desk plate 115 cm — double data + double socket for the flip desk and monitor", wall="N", x=20.9, y=9.0, h=1.15, parts=["2D", "2S"],
   status="adapted", note="the plan's office D 110 + socket, at Main's flip desk; two Cat6 (computer, printer) to the hub (Karim 7 Nov 2026)")

# Reception
pt("multi", "Reception", "TV plate behind the TV — data, HDMI, TV + double socket", at=(17.545, 4.29), h=1.2, facing="E", parts=["D", "H", "TV", "2S"],
   note="inside the TV opening, hidden by the 166.8 cm TV")
pt("multi", "Reception", "Niche plate 50 cm — data, HDMI, TV + double socket (soundbar, sub, box)", at=(17.27, 3.9), h=0.5, facing="E",
   parts=["D", "H", "TV", "2S"], status="adapted", note="the plan's 60 plate, at the back of Main's low lit niche (0.30–0.69); HDMI conduit to the TV plate")
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

# ================================================================ Motion / presence sensors (Karim 7 Nov 2026)
# Ceiling sensors that switch the lights, each centred between ceiling spots so it lines up with them. mmWave (Tuya
# Zigbee 24 GHz, mains L+N) keeps the light on while someone is still; PIR where people only walk through.
# Nothing outdoors (terrace: later, a door contact on the inside of the terrace door); nothing in the reception.
def sensor(room, label, xy, tech, status="added", note=""):
    pt("sensor", room, label, at=xy, h=CEIL, status=status, tech=tech, note=note)

sensor("Master bathroom", "Presence sensor (mmWave) — master bathroom", (1.35, 6.80), "mmWave",
       note="centred between the basin and middle spots, outside the shower and 1.2 m from the exhaust fan; sees the WC bay")
sensor("Guest bathroom", "Presence sensor (mmWave) — guest bathroom", (13.80, 8.025), "mmWave",
       note="centred between four spots (middle and vanity columns), 1.1 m from the exhaust fan")
sensor("Laundry", "Motion sensor (PIR) — laundry", (11.40, 7.783), "PIR",
       note="on the spot line, centred between the door-side and middle spots, 1.1 m from the exhaust fan")
sensor("Kitchen", "Presence sensor (mmWave) — kitchen", (8.80, 6.975), "mmWave",
       note="centred between four spots on the east (door) side, away from the hob")
sensor("Entrance", "Motion sensor (PIR) — entrance corridor", (8.85, 4.60), "PIR",
       note="on the corridor spot line, centred between two spots, about over the front door")
sensor("Entrance", "Presence sensor (mmWave) — corridor by the laundry and guest bathroom", (12.7375, 6.25), "mmWave",
       note="on the corridor spot line, centred between two spots between the laundry and guest bathroom doors")
sensor("Master bedroom", "Presence sensor (mmWave) — master bedroom, OPTIONAL, switch-off only", (4.375, 6.85), "mmWave", "optional",
       note="optional: never switches the light on, only off once the room is empty; centred between four spots")
sensor("Living room", "Presence sensor (mmWave) — living room, OPTIONAL, switch-off only", (4.55, 2.45), "mmWave", "optional",
       note="optional: never switches the light on, only off once the room is empty; between the two spot rows")

# ================================================================ Wi-Fi access points (Karim 7 Nov 2026)
# Ceiling access points, one network name, each on its own Cat6 from the hub (PoE: no socket). AP2 is with the hub above.
pt("ap", "Entrance", "Wi-Fi access point AP1 — ceiling between the bedroom and living-room doors", at=(5.425, 5.05), h=CEIL, status="added", id="ap-1",
   note="covers the master bedroom, master bathroom and living room; between the two lobby spots; Cat6 + PoE from the hub")
pt("ap", "Reception", "Wi-Fi access point AP3 — reception ceiling, between the dining and seating areas", at=(18.3, 5.625), h=CEIL, status="added", id="ap-3",
   note="covers the reception, dining and terrace (through the glass); halfway between the dining and reception spot rows; Cat6 + PoE from the hub")

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
feed("Guest bathroom", "Under-vanity, shelf + mirror glow — driver under the vanity", (14.38, 8.04), 0.30, "W", "24 V strip")
feed("Guest bathroom", "Shower-niche LED (2 niches) — driver in the ceiling void outside the shower", (13.25, 6.96), 2.45, "N", "24 V IP67 strip in the niches; box high on the south wall, outside the shower")
feed("Kitchen", "Plinth LED — driver in the sink base", (8.10, 8.75), 0.15, "S")
feed("Laundry", "Under-cabinet LED — driver in the upper cabinet", (11.16, 8.96), 1.70, "S")
feed("Terrace", "Seat-lip LED — IP65 driver in the seat storage", (24.27, 3.02), 0.20, "W")
feed("Terrace", "BBQ counter LED — IP65", (23.11, 9.23), 0.80, "S")

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
