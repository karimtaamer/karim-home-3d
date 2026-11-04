#!/usr/bin/env python3
"""Main's electrical, lighting and low-current points -> electrical-kareems-changes.json (Main only).

    python3 build_electrical.py            # writes electrical-kareems-changes.json; prints counts by type

Source: SAMRA CONCEPTS "Furniture plan" + "Upper lighting with furniture" (Lotus apartment, 1st issue 20-08-2026), applied
to Main's layout as it is (no wall, room or furniture moves). Each point is given a rough spot inside its room and the wall
it sits on; the script finds that wall face in model-kareems-changes.js (a ray from the spot), so every plate sits on a
real wall. Points with `at` instead of `wall` (ceiling spots, points inside joinery) keep their coordinates.
Heights are the plan's (cm from the slab) unless the point is adapted to Main's furniture; `status` says which:
  plan     - as on the Samra sheets (same room, same use; position fitted to Main's walls)
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
    """wall: the wall the plate is on (N = the room's north wall, so it faces south); x / y: where along it."""
    if wall:
        fx, fy = face(x, y, wall)
        facing = OPP[wall]
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
spots("Living room", "living-A", row(0.75, 4.25, 5, 3.75, "y"), "Ceiling spot — living room, half A (sofa side)")
spots("Living room", "living-B", row(0.65, 4.25, 6, 5.35, "y"), "Ceiling spot — living room, half B (TV side)")
spots("Master bedroom", "master-A", [(x, y) for x in (2.95, 3.95, 4.85) for y in (7.85, 8.65)], "Ceiling spot — master bedroom, half A (window half)",
      "adapted", "Samra's 12 bedroom spots in two halves, laid on Main's bed (headboard west) and wardrobe (east wall)")
spots("Master bedroom", "master-B", [(x, y) for x in (2.95, 3.95, 4.85) for y in (6.25, 7.05)], "Ceiling spot — master bedroom, half B (door half)",
      "adapted", "Samra's 12 bedroom spots in two halves, laid on Main's bed (headboard west) and wardrobe (east wall)")
spots("Master bedroom", "master-entry", [(3.0, 5.25), (4.05, 5.25)], "Ceiling spot — over the dresser (bedroom entrance spots)",
      "adapted", "the plan's 2 master-lobby spots, over Main's dresser by the door")
spots("Master bedroom", "master-wardrobe", [(1.3, 5.45), (2.0, 5.35)], "Ceiling spot — wardrobe corner (the plan's dressing-room spots)",
      "adapted", "Main has no dressing room: its spots light the south wardrobe and the cupboard by the bathroom door")
spots("Master bathroom", "mbath", [(0.95, 6.65), (1.75, 6.95), (0.95, 8.15), (1.78, 8.45)], "Ceiling spot — master bathroom (basin / middle / shower / WC)",
      "adapted", "4 spots as on the plan, over Main's vanity, middle, shower and WC bay")
spots("Kitchen", "kitchen-A", [(x, 6.55) for x in (7.45, 8.35, 9.25)] + [(7.45, 7.4), (9.25, 7.4)], "Ceiling spot — kitchen, half A")
spots("Kitchen", "kitchen-B", [(8.35, 7.4)] + [(x, 8.3) for x in (7.45, 8.35, 9.25)], "Ceiling spot — kitchen, half B")
spots("Laundry", "laundry", row(7.25, 8.85, 3, 11.4, "y"), "Ceiling spot — laundry")
spots("Guest bathroom", "gbath-basin", row(6.95, 9.1, 3, 14.2, "y"), "Ceiling spot — guest bathroom, over the vanity")
spots("Guest bathroom", "gbath-mid", row(6.95, 9.1, 3, 13.4, "y"), "Ceiling spot — guest bathroom, middle")
spots("Guest bathroom", "gbath-bath", row(6.95, 9.1, 2, 12.6, "y"), "Ceiling spot — guest bathroom, over the bath / shower")
spots("Entrance", "corridor-A", [(6.75, 4.6), (8.45, 4.6), (10.15, 4.6), (11.6, 5.75), (12.9, 6.25), (14.2, 6.25)],
      "Ceiling spot — entrance corridor, circuit A (two-way)", "adapted", "the plan's corridor spots (14 on 2 two-way circuits) laid along Main's entrance and hallway")
spots("Entrance", "corridor-B", [(7.6, 4.6), (9.3, 4.6), (10.95, 4.6), (10.85, 6.1), (12.25, 6.25), (13.55, 6.25)],
      "Ceiling spot — entrance corridor, circuit B (two-way)", "adapted", "the plan's corridor spots (14 on 2 two-way circuits) laid along Main's entrance and hallway")
spots("Entrance", "lobby", [(5.05, 5.05), (5.8, 5.05)], "Ceiling spot — lobby by the bedroom and living-room doors")
spots("Reception", "reception-A", row(18.0, 21.0, 4, 3.0), "Ceiling spot — reception, half A (sofa side)")
spots("Reception", "reception-B", row(18.0, 21.0, 4, 4.6), "Ceiling spot — reception, half B (TV side)")
spots("Dining", "dining-A", row(15.9, 20.7, 6, 6.65), "Ceiling spot — dining, half A")
spots("Dining", "dining-B", row(15.9, 20.7, 6, 8.55), "Ceiling spot — dining, half B")
spots("Dining", "buffet", [(15.55, 7.6), (15.55, 8.4)], "Ceiling spot — over the buffet niche")
spots("Dining", "office", [(20.15, 9.05), (20.85, 9.05)], "Ceiling spot — over the coffee corner / flip desk",
      "adapted", "the plan's 2 office spots, over Main's coffee corner and flip desk")

# Existing decorative fittings (furnish-kareems-changes.js), listed for their labels and switch.
for x in (17.6, 18.4, 19.2):
    pt("pendant", "Dining", "Lantern pendant over the dining table", at=(x, 7.6), h=1.75, status="existing", circuit="dining-pendants")
for y in (6.231, 8.79):
    pt("pendant", "Master bedroom", "Bedside globe pendant", at=(2.48, y), h=1.15, status="existing", circuit="bedside-" + ("S" if y < 7 else "N"))
pt("walllight", "Terrace", "Terrace wall light", at=(21.51, 5.775), h=2.0, facing="E", status="existing", circuit="terrace-wall")
pt("walllight", "Terrace", "Terrace wall light", at=(21.47, 8.6), h=2.0, facing="E", status="existing", circuit="terrace-wall")
pt("walllight", "Terrace", "Terrace wall light (party-mood height)", wall="W", x=21.8, y=2.45, h=2.2, circuit="terrace-wall",
   status="plan", note="the plan's wall lights along the glass wall: Main keeps its two sconces and adds this one south of the window")
pt("walllight", "Entrance", "Wall sconce beside the front door", at=(7.63, 3.6), h=1.75, facing="N", status="existing", circuit="door-sconces")
pt("walllight", "Entrance", "Wall sconce beside the front door", at=(9.33, 3.6), h=1.75, facing="N", status="existing", circuit="door-sconces")
LINES.append({"id": "led-master-curtain", "type": "led", "room": "Master bedroom", "x0": 2.6, "y0": 8.88, "x1": 5.7, "y1": 8.88, "h": CEIL - 0.02,
              "label": "Indirect LED in the curtain box over the bedroom window", "circuit": "master-curtain", "status": "plan"})
LINES.append({"id": "led-reception-curtain", "type": "led", "room": "Reception", "x0": 21.1, "y0": 2.3, "x1": 21.1, "y1": 5.4, "h": CEIL - 0.02,
              "label": "Indirect LED in the curtain box over the reception window", "circuit": "reception-curtain", "status": "plan"})
LINES.append({"id": "led-living-curtain", "type": "led", "room": "Living room", "x0": 3.06, "y0": 0.8, "x1": 3.06, "y1": 4.2, "h": CEIL - 0.02,
              "label": "Indirect LED over the living-room window (Main's cove light)", "circuit": "living-cove", "status": "existing"})

# ================================================================ Switch banks (centre 1.20; bedside 0.85)
SW = 1.20
def bank(id, room, title, gangs, *, two_way=None, **kw):
    lab = f"{len(gangs)}-gang switch — {title}"
    return pt("switch", room, lab, id=id, h=kw.pop("h", SW), gangs=gangs, two_way=two_way, **kw)

bank("sw-front-door", "Entrance", "inside the front door",
     ["Sconces beside the front door", "Corridor spots, circuit A (two-way)", "Corridor spots, circuit B (two-way)"],
     two_way="sw-dining-end", wall="S", x=7.82, y=4.2)
bank("sw-dining-end", "Hallway", "hallway, dining end",
     ["Entrance console cove + mirror lights", "Corridor spots, circuit A (two-way)", "Corridor spots, circuit B (two-way)"],
     two_way="sw-front-door", wall="S", x=14.35, y=6.2, status="plan",
     note="the plan's second corridor bank (Diviater) at the reception/dining end; its sconce rocker becomes the console's lights")
bank("sw-lobby", "Entrance", "lobby by the bedroom and living-room doors", ["Lobby spots"], wall="N", x=6.35, y=5.0,
     status="adapted", note="the plan's master-lobby rocker, on Main's corridor wall by the bedroom door")
bank("sw-living", "Living room", "living room, by the door",
     ["Spots, half A (sofa side)", "Spots, half B (TV side)", "Window cove LED, TV-wall sconces and picture lights"],
     wall="N", x=4.95, y=4.0)
bank("sw-master-door", "Master bedroom", "bedroom door",
     ["Dresser spots (entrance)", "Bedroom spots, half A (intermediate: door + both bedsides)", "Bedroom spots, half B (intermediate: door + both bedsides)"],
     two_way="sw-bed-S,sw-bed-N", at=(4.516, 5.585), facing="W", status="existing",
     note="Main's existing 3-gang plate by the door: the plan's 'master entrance' bank. Three control points need 2-way + intermediate (or smart) switches")
bank("sw-master-dresser", "Master bedroom", "dresser, wardrobes and curtain",
     ["Curtain-box LED", "Dresser mirror, shelf column and shoe lighting", "Wardrobe and wardrobe-corner spots (the plan's dressing room)"],
     wall="E", x=4.3, y=5.35, status="adapted", note="the plan's 'dresser / wardrobes / curtain' bank plus the dressing-room 2-gang folded in (Main has no dressing room)")
for side, y, sy in (("S", 6.231, 6.43), ("N", 8.79, 8.59)):
    bank(f"sw-bed-{side}", "Master bedroom", f"bedside ({'door' if side == 'S' else 'window'} side)",
         ["Bedside pendant", "Bedroom spots, half A (intermediate)", "Bedroom spots, half B (intermediate)"],
         two_way="sw-master-door", wall="W", x=2.6, y=sy, h=0.85, status="adapted",
         note="the plan's bed-switch bank (over the console), on each side of Main's bed on the headboard wall")
bank("sw-mbath", "Master bathroom", "master bathroom, outside the door",
     ["Spots over the vanity", "Spots, middle + shower", "WC spot + exhaust fan"], wall="N", x=2.22, y=5.6, status="adapted",
     note="outside the bathroom door, on the dry side (the plan draws it on the bedroom wall too)")
bank("sw-kitchen", "Kitchen", "kitchen, by the door",
     ["Spots, half A", "Spots, half B", "Under-cabinet LED strips"], wall="S", x=9.95, y=6.2)
bank("sw-laundry", "Laundry", "laundry, outside the door", ["Laundry spots + exhaust fan"], wall="N", x=10.7, y=6.3,
     status="adapted", note="outside the door: inside, the full-height joinery runs to the door")
bank("sw-gbath", "Guest bathroom", "guest bathroom, outside the door",
     ["Spots over the vanity", "Spots, middle", "Bath / shower spots + exhaust fan"], wall="N", x=14.25, y=6.3,
     status="adapted", note="moved outside the door, out of the wet zone (the plan draws it inside)")
bank("sw-dining", "Dining", "dining, by the hallway door",
     ["Lantern pendants", "Dining spots, half A", "Dining spots, half B", "Buffet spots + niche LED"], wall="S", x=15.22, y=6.2,
     status="adapted", note="the plan puts the dining and reception banks on the wall by the hallway door; in Main the buffet mass covers that wall, so they sit on the south wall just right of the door")
bank("sw-reception", "Reception", "reception, by the hallway door",
     ["Reception spots, half A", "Reception spots, half B", "Curtain-box LED + TV-wall niche (library) lights"], wall="S", x=15.58, y=6.2,
     status="adapted", note="beside the dining bank, on the south wall right of the hallway door (the buffet mass covers the plan's wall)")
bank("sw-office", "Dining", "coffee corner, by the terrace door",
     ["Terrace floor lighting (seat-lip LED)", "Terrace wall lights", "Coffee corner / flip-desk spots"], wall="E", x=20.9, y=8.25,
     status="adapted", note="the plan's office bank (balcony floor / balcony wall / office), by Main's coffee corner and terrace slider")

# AC controllers (wall thermostats), 1.50
pt("acctl", "Living room", "AC controller — living room split", wall="N", x=4.75, y=4.0, h=1.5)
pt("acctl", "Master bedroom", "AC controller — master bedroom split", wall="E", x=4.3, y=5.47, h=1.5, status="adapted", note="by the door bank (the plan shows it by the bed wall)")
pt("acctl", "Dining", "AC controller — dining split", wall="S", x=15.22, y=6.2, h=1.5, status="adapted", note="over the dining bank (the plan's 'reception and dining ACs' box by the door)")
pt("acctl", "Reception", "AC controller — reception split", wall="S", x=15.58, y=6.2, h=1.5, status="adapted", note="over the reception bank")

# ================================================================ Power
def sock(room, label, n=2, **kw):
    return pt("socket", room, label, gang=n, **kw)

# Living room
pt("multi", "Living room", "TV plate behind the TV — data, HDMI, TV + double socket", wall="E", x=5.7, y=2.25, h=1.2,
   parts=["D", "H", "TV", "2S"], note="hidden behind the screen (1.10–1.95)")
pt("multi", "Living room", "TV-console plate — data, HDMI, TV + double socket (boxes, soundbar)", wall="E", x=5.7, y=2.25 - 0.55, h=0.6,
   parts=["D", "H", "TV", "2S"], note="inside the floating console (0.45–0.72); HDMI conduit to the 120 plate")
pt("sound", "Living room", "Sound system screen (audio control)", wall="E", x=5.8, y=4.12, h=1.5)
pt("intercom", "Living room", "Intercom screen — answer the front door", wall="E", x=5.8, y=4.3, h=1.5)
sock("Living room", "Double socket 45 cm — sofa end table (lamp, chargers)", wall="N", x=3.45, y=3.9, h=0.45)
sock("Living room", "Double socket 90 cm — reading lamp over the end table", wall="N", x=3.75, y=3.9, h=0.9)
sock("Living room", "Double socket 45 cm — sofa corner", wall="N", x=4.6, y=3.9, h=0.45, note="clear of the art on the north wall")
sock("Living room", "Double socket 45 cm — chaise end", wall="S", x=4.95, y=1.0, h=0.45)
sock("Living room", "Double socket 45 cm — beside the TV wall (plant / cleaning)", wall="S", x=5.85, y=1.0, h=0.45)
pt("power", "Living room", "AC power point — living-room split (dedicated circuit)", wall="W", x=3.3, y=0.68, h=2.3, appliance="split AC", status="added")

# Master bedroom
for side, y in (("door", 6.08), ("window", 8.94)):
    sock("Master bedroom", f"Double socket 70 cm — bedside ({side} side): lamp, phone", wall="W", x=2.6, y=y, h=0.7, status="adapted",
         note="the plan's bedside 70 points, on Main's headboard wall")
    pt("phone", "Master bedroom", f"Phone point 70 cm — bedside ({side} side)", wall="W", x=2.6, y=y + (0.1 if y < 7 else -0.1), h=0.7, status="adapted")
sock("Master bedroom", "Double socket 100 cm — dresser (hair dryer, mirror)", wall="S", x=2.75, y=5.0, h=1.0, status="adapted",
     note="the plan's 'table area' socket 100, on Main's south-wall dresser")
sock("Master bedroom", "Double socket 45 cm — by the door (vacuum)", wall="E", x=4.3, y=5.15, h=0.45)
sock("Master bedroom", "Double socket 45 cm — window wall", wall="N", x=5.9, y=8.6, h=0.45)
pt("power", "Master bedroom", "AC power point — master split (dedicated circuit)", wall="S", x=3.95, y=5.0, h=2.3, appliance="split AC", status="added")
# Master bathroom
sock("Master bathroom", "Socket 120 cm — by the vanity (shaver, hair dryer), splash-protected", n=1, wall="S", x=1.25, y=6.6, h=1.2, status="adapted")
pt("power", "Master bathroom", "Instant water heater point — inside the vanity (existing socket)", at=(0.566, 6.525), h=0.66, facing="E",
   appliance="instant water heater 7.5 kW", status="existing", note="Main already models this socket on the vanity's back panel; it needs its own 3×6 mm circuit")
pt("fan", "Master bathroom", "Exhaust fan — master bathroom (with the WC rocker)", at=(1.78, 7.95), h=CEIL, status="added")

# Kitchen
sock("Kitchen", "Double socket 130 cm — counter left of the sink", wall="N", x=6.95, y=8.5, h=1.3)
sock("Kitchen", "Double socket 130 cm — counter right of the sink", wall="N", x=9.2, y=8.5, h=1.3)
pt("power", "Kitchen", "Socket 60 cm — water filter, under the sink", wall="N", x=8.8, y=8.5, h=0.6, appliance="water filter", note="under the sink, just east of the window (the wall under the window is the opening)")
pt("power", "Kitchen", "Double socket 130 cm — for the fridge", wall="E", x=9.8, y=7.05, h=1.3, appliance="fridge", note="behind the fridge, as the plan")
pt("power", "Kitchen", "Dishwasher point — in the base under the raised dishwasher", wall="E", x=9.8, y=8.3, h=0.4, appliance="dishwasher",
   status="adapted", note="the plan has the dishwasher at the sink (60); Main's dishwasher is the raised column on the east run")
sock("Kitchen", "Double socket 130 cm — counter by the water dispenser", wall="E", x=9.8, y=8.95, h=1.3, status="adapted", note="feeds Main's countertop water dispenser")
pt("power", "Kitchen", "Cooker point 60 cm — hob", wall="W", x=6.9, y=7.376, h=0.6, appliance="cooker / hob")
pt("power", "Kitchen", "Hood point — over the hob, inside the upper", wall="W", x=6.9, y=7.376, h=2.1, appliance="cooker hood", status="added")
sock("Kitchen", "Double socket 130 cm — counter by the hob (south)", wall="W", x=6.9, y=6.6, h=1.3)
sock("Kitchen", "Double socket 130 cm — counter by the hob (north)", wall="W", x=6.9, y=8.15, h=1.3)
pt("power", "Kitchen", "Oven point — behind the pan drawer under the oven", at=(8.117, 5.672), h=0.55, facing="N", appliance="built-in oven",
   status="adapted", note="plan: 130 on the south wall; in Main's tower the oven is 66.5–122.5, so the point sits under it, reachable through the drawer")
pt("power", "Kitchen", "Microwave point — behind the microwave in the tower niche", at=(8.117, 5.672), h=1.45, facing="N", appliance="microwave",
   status="adapted", note="plan: 150; Main's microwave niche is 127–164")
pt("tv", "Kitchen", "TV point 180 cm (kitchen TV)", wall="S", x=9.35, y=6.2, h=1.8, status="adapted",
   note="the plan's south wall is Main's full-height pantry + tower: moved to the free wall east of the tower")
sock("Kitchen", "Double socket 180 cm — kitchen TV", wall="S", x=9.6, y=6.2, h=1.8, status="adapted")
pt("phone", "Kitchen", "Phone point 150 cm", wall="S", x=8.85, y=6.2, h=1.5, status="adapted", note="moved off the pantry wall, east of the tower")
pt("sound", "Kitchen", "Sound system screen (audio control)", wall="S", x=9.05, y=6.2, h=1.5, status="adapted", note="moved off the pantry wall, east of the tower")
pt("intercom", "Kitchen", "Intercom screen — answer the front door", wall="S", x=9.25, y=6.2, h=1.5, status="adapted", note="moved off the pantry wall, east of the tower")

# Laundry
pt("power", "Laundry", "Washing-machine point 60 cm — behind the oak base", wall="N", x=11.9, y=8.5, h=0.6, appliance="washing machine",
   status="adapted", note="Main's washer stands on a 0.76 base: the socket is inside the base, beside the hoses. No dryer in Main, so the plan's dryer point (120) is left out")
sock("Laundry", "Double socket 120 cm — counter (iron, steamer)", wall="N", x=11.15, y=8.5, h=1.2)
sock("Laundry", "Double socket 120 cm — passage wall", wall="E", x=11.6, y=7.6, h=1.2)
pt("power", "Laundry", "Water-heater point — 40 L heater in the upper cabinet (dedicated 3×6 mm)", wall="N", x=11.25, y=8.5, h=2.35,
   appliance="electric water heater", status="added", note="not on the plan; the heater lives in the counter's upper cabinet")
pt("fan", "Laundry", "Exhaust fan — laundry (with the laundry light)", at=(11.4, 8.85), h=CEIL, status="added")

# Guest bathroom
sock("Guest bathroom", "Socket 130 cm — by the vanity mirror (shaver, hair dryer)", n=1, wall="E", x=14.3, y=7.05, h=1.3)
sock("Guest bathroom", "Socket 130 cm — by the WC (bidet / smart seat)", n=1, wall="N", x=14.45, y=8.8, h=1.3)
pt("fan", "Guest bathroom", "Exhaust fan — guest bathroom (with the bath rocker)", at=(12.9, 8.6), h=CEIL, status="added")

# Entrance, hallway
sock("Entrance", "Double socket 45 cm — entrance corridor", wall="S", x=10.0, y=4.2, h=0.45, note="beside the console (cleaning)")
sock("Entrance", "Double socket 45 cm — lobby by the bedroom door", wall="S", x=4.9, y=5.0, h=0.45)
sock("Hallway", "Double socket 45 cm — hallway", wall="N", x=12.6, y=6.2, h=0.45)
pt("db", "Entrance", "Distribution board (DB) — 36-way, main breakers for the whole flat", wall="N", x=6.75, y=5.0, h=1.8, w=0.45, hh=0.6,
   status="added", note="not on the plan (quotation: 36-way DB). Near the front door, clear of the gallery art; bottom 1.50, top 2.10. Confirm wall depth with the electrician")
pt("lcp", "Entrance", "Low-current panel — fibre/ONT, Cat6 patch, TV splitter, intercom power", wall="N", x=7.25, y=5.0, h=1.78, w=0.35, hh=0.45,
   status="added", note="beside the DB: every data (D), TV and intercom cable runs home here")
pt("router", "Hallway", "Wi-Fi router — centre of the flat, fed by Cat6 from the low-current panel", wall="S", x=13.05, y=6.2, h=2.2,
   status="added", note="in the hallway, halfway between the bedroom and the reception, so Wi-Fi reaches both ends; a mesh point can plug into the reception/living data points")
sock("Hallway", "Socket 210 cm — router power", n=1, wall="S", x=13.3, y=6.2, h=2.1, status="added")
pt("data", "Hallway", "Data point (Cat6) — router uplink from the low-current panel", wall="S", x=12.8, y=6.2, h=2.1, status="added")
pt("chime", "Entrance", "Doorbell chime", wall="N", x=7.6, y=5.0, h=2.1, status="added")
pt("intercom_out", "Entrance", "Outdoor intercom unit — outside the front door (camera + call button)", wall="N", x=9.2, y=3.0, h=1.45,
   status="plan", note="the plan puts it outside the door at 120 on the 45° corner; Main's door has a flat wall, so beside the door at 1.45 (camera height)")
pt("doorbell", "Entrance", "Doorbell push — outside the front door", wall="N", x=7.8, y=3.0, h=1.3, status="added")

# Dining, coffee corner
sock("Dining", "Double socket 45 cm — north wall (west)", wall="N", x=15.4, y=9.0, h=0.45)
sock("Dining", "Double socket 45 cm — north wall (by the table)", wall="N", x=18.6, y=9.0, h=0.45)
sock("Dining", "Double socket 100 cm — over the buffet (lamps, warming tray)", at=(14.975, 8.05), h=0.95, facing="E", status="adapted",
     note="the plan's 130 socket on the column by the hallway door, moved onto Main's buffet panel")
pt("power", "Dining", "AC power point — dining split (dedicated circuit)", at=(14.975, 9.4), h=2.3, facing="E", appliance="split AC", status="added")
sock("Dining", "Double socket 115 cm — espresso machine", wall="N", x=20.0, y=9.0, h=1.15, status="adapted",
     note="the plan's office sockets 110: Main's marble top is at 1.00, so 1.15")
sock("Dining", "Double socket 115 cm — water dispenser", wall="N", x=20.45, y=9.0, h=1.15, status="adapted")
pt("multi", "Dining", "Desk plate 115 cm — data + double socket for the flip desk and monitor", wall="N", x=20.9, y=9.0, h=1.15, parts=["D", "2S"],
   status="adapted", note="the plan's office D 110 + socket, at Main's flip desk")

# Reception
pt("multi", "Reception", "TV plate behind the TV — data, HDMI, TV + double socket", at=(17.545, 4.29), h=1.2, facing="E", parts=["D", "H", "TV", "2S"],
   note="inside the TV opening, hidden by the 166.8 cm TV")
pt("multi", "Reception", "Niche plate 50 cm — data, HDMI, TV + double socket (soundbar, sub, box)", at=(17.27, 3.9), h=0.5, facing="E",
   parts=["D", "H", "TV", "2S"], status="adapted", note="the plan's 60 plate, at the back of Main's low lit niche (0.30–0.69); HDMI conduit to the TV plate")
pt("sound", "Reception", "Sound system screen (audio control)", wall="S", x=17.75, y=2.5, h=1.5, status="adapted",
   note="off the column (Karim's rule): on the south wall beside the TV run")
pt("intercom", "Reception", "Intercom screen — answer the front door", wall="S", x=17.95, y=2.5, h=1.5, status="adapted",
   note="off the column (Karim's rule): on the south wall beside the TV run")
sock("Reception", "Double socket 45 cm — left of the sofa", wall="S", x=18.15, y=2.5, h=0.45)
sock("Reception", "Double socket 45 cm — right of the sofa", wall="S", x=20.55, y=2.5, h=0.45)
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

# ================================================================ write
counts = Counter(p["type"] for p in P)
sockets = sum(1 for p in P if p["type"] in ("socket",))
legend = {
    "socket": "Socket (single or double)", "power": "Dedicated power point (appliance, AC, heater)", "wp": "Weatherproof outdoor socket",
    "multi": "Combined plate (data / HDMI / TV / sockets on one plate)", "data": "Data point, Cat6 RJ-45", "phone": "Phone point, RJ-12",
    "tv": "TV / antenna point", "sound": "Sound-system screen", "intercom": "Intercom screen", "intercom_out": "Outdoor intercom unit",
    "doorbell": "Doorbell push", "chime": "Doorbell chime", "switch": "Switch bank", "acctl": "AC controller", "spot": "Ceiling spot 6 W",
    "pendant": "Pendant light", "walllight": "Wall light", "fan": "Exhaust fan", "db": "Distribution board", "lcp": "Low-current panel",
    "router": "Wi-Fi router", "led": "Indirect LED strip",
}
OUT.write_text(json.dumps({
    "version": "kareems-changes",
    "source": "SAMRA CONCEPTS, Lotus apartment: Furniture plan + Upper lighting with furniture, 1st issue 20-08-2026 (Eng. Omar Samra / Eng. Mariam Ahmed)",
    "built_by": "build_electrical.py (edit there, then rerun)",
    "heights": "metres; the plan's heights are cm from the concrete slab, used as-is until the floor build-up is confirmed",
    "legend": legend, "points": P, "lines": LINES,
}, ensure_ascii=False, indent=1) + "\n")
print(f"{OUT.name}: {len(P)} points, {len(LINES)} LED lines")
for k, v in sorted(counts.items()):
    print(f"  {k:13s} {v}")
print("  by status:", dict(Counter(p['status'] for p in P)))
