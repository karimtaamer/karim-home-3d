#!/usr/bin/env python3
"""Final Electrical's electrical layer -> electrical-final-electrical.json (that version only).

    python3 build_electrical_final_electrical.py    # writes the JSON; deterministic, re-running gives the same bytes

Source: the site engineer's layer as the Light and Power Plan has it (electrical-light-power-plan.json, read, never
written) PLUS the changes Karim asked him for in the final comments PDF (electrical-diff.pdf, 23 Nov 2026), nothing
else. EDITS below holds one block per PDF item (item: 1..19, and "Q1" / "Q2" for the open questions, whose requested
answer is applied and marked assumption: true). Where an item asks for one of Main's points, it is copied from
electrical-kareems-changes.json (read, never written). Everything the PDF does not mention stays exactly as the engineer
drew it: same id, xy, h, gangs, labels, status "engineer".

Provenance on the points the edits touch:
  - copied from Main: status "requested", item, from_main (Main's id; kept as the id unless it collides with an engineer
    id, then prefixed "fe-");
  - the engineer's, changed: his id, status "requested", item, changed (what changed vs the engineer);
  - new, with no Main twin: a clear id of its own, status "requested", item.
Removed points are dropped; changed ones stay where they were in his list; added ones follow, in item order.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LPP = json.loads((ROOT / "electrical-light-power-plan.json").read_text())
MAIN = {p["id"]: p for p in json.loads((ROOT / "electrical-kareems-changes.json").read_text())["points"]}
OUT = ROOT / "electrical-final-electrical.json"

TWO_WAY_1 = "All corridor / lobby spots — one circuit, two-way from 3 places"
CURTAIN = "Curtain-box LED + curtain-motor outlet (M 268) — "
CURTAIN_NOTE = "Karim's comments: the curtain box's LED outlet and the curtain-motor outlet, at 268, at Main's motor point"

# op: "add" (main: copy Main's point; or point: a new one), "remove" (id), "modify" (id, set, changed).
# set: fields put on the point (Main's or the engineer's). gangs_from: copy that Main point's gangs.
# drop: Main's fields left off the copy.
EDITS = [
    # 1. Reception & dining curtains: an LED + motor outlet in each curtain box, at Main's curtain-motor points.
    *[{"item": 1, "op": "add", "main": m, "set": {"type": "curtainled", "h": 2.68, "label": CURTAIN + where, "note": CURTAIN_NOTE}}
      for m, where in [("power-215", "reception window"), ("power-216", "dining slider"),
                       ("power-217", "dining window"), ("power-218", "reception / dining divider")]],
    # 2. Reception / dining switches by the hallway door: his two 3-gang plates go, Main's 2 x 2 grid comes in at 120 / 110.
    {"item": 2, "op": "remove", "id": "switch-16"},
    {"item": 2, "op": "remove", "id": "switch-17"},
    {"item": 2, "op": "add", "main": "sw-dining", "set": {"h": 1.2, "label": "2-gang switch — dining, by the hallway door, top box, 120 cm"}},
    {"item": 2, "op": "add", "main": "sw-dining-2", "set": {"h": 1.1, "label": "2-gang switch — dining, by the hallway door, lower box, 110 cm"}},
    {"item": 2, "op": "add", "main": "sw-reception", "set": {"h": 1.2, "label": "2-gang switch — reception, by the hallway door, top box, 120 cm"}},
    {"item": 2, "op": "add", "main": "sw-reception-2", "set": {"h": 1.1, "label": "2-gang switch — reception, by the hallway door, lower box, 110 cm"}},
    # 3. Reception: a double socket at 45 by the east sofa.
    {"item": 3, "op": "add", "main": "socket-166"},
    # 4. Dining, terrace door: his 3-gang keeps its place, its rockers named (gang 3 is the planter, not spots over the
    #    seat); his 1-gang becomes the coffee-corner switch, at Main's position. shutter-3 stays.
    {"item": 4, "op": "modify", "id": "switch-18", "changed": "gangs named for the terrace (was 3 unnamed dining gangs)",
     "set": {"gangs": ["Terrace floor LED + seat-lip LED + BBQ counter LED", "Terrace wall lights", "Planter lighting"]}},
    {"item": 4, "op": "modify", "id": "switch-19", "main_xy": "sw-coffee",
     "changed": "moved to the coffee corner (Main sw-coffee), 110 -> 120; now the coffee-corner shelf LED",
     "set": {"h": 1.2, "label": "1-gang light switch — coffee corner, east end, 120 cm", "gangs": ["Coffee corner shelf LED"]}},
    # 5. Terrace: every socket weatherproof IP55 (his positions, heights and gang counts).
    *[{"item": 5, "op": "modify", "id": f"socket-{n}", "wp": True, "changed": "made weatherproof IP55 (was an indoor universal socket)"}
      for n in range(49, 56)],
    # 6. Living: LED + motor outlet in the curtain box; the LED on a third rocker of his living-room switch.
    {"item": 6, "op": "add", "main": "power-213", "set": {"type": "curtainled", "h": 2.68, "label": CURTAIN + "living-room window", "note": CURTAIN_NOTE}},
    {"item": 6, "op": "modify", "id": "switch-2", "add_gang": "Curtain-pocket LED", "changed": "2-gang -> 3-gang: gang 3 the curtain-pocket LED",
     "set": {"label": "3-gang light switch — living room, by the door, 120 cm"}},
    # 7. Entrance gallery: his four wall-light outlets go; one picture light at 210, centred on the west wall.
    *[{"item": 7, "op": "remove", "id": f"walllight-{n}"} for n in (7, 8, 9, 10)],
    {"item": 7, "op": "add", "main": "ledfeed-195"},
    # 8. Entrance console: a double socket at 60 on the bay's back wall above the seat, at Karim's red circle in
    #    att-console-3d.png. The bay (furnish: x 10.2585 to 11.3486, back wall y 3.6001) is seen looking south, so its
    #    east post is on the picture's left: the circle, left of the mirror (x 10.36 to 10.82) under the hooks, is 0.30 in
    #    from the east post's inner face (11.3036). 3 mm proud of the wall, like his wall points.
    {"item": 8, "op": "add", "point": {
        "id": "socket-console-60", "type": "socket", "room": "Entrance", "x": 11.0036, "y": 3.6031, "h": 0.6, "facing": "N",
        "label": "Double socket 60 cm — entrance console, back wall above the seat (east side)", "gang": 2,
        "note": "Karim's 3D picture (red circle): left of the mirror under the hooks, 0.30 in from the console's east post"}},
    # 9. Corridor: his three two-way switches share one circuit for all the spots; the middle one is the intermediate.
    {"item": 9, "op": "modify", "id": "switch-11", "gang1": TWO_WAY_1, "changed": "gang 1 named: all corridor / lobby spots, two-way from 3 places"},
    {"item": 9, "op": "modify", "id": "switch-14", "gang1": TWO_WAY_1, "changed": "gang 1 named: all corridor / lobby spots, two-way from 3 places"},
    {"item": 9, "op": "modify", "id": "switch-15", "gang1": TWO_WAY_1 + " (intermediate)",
     "changed": "gang 1 named, and made the intermediate of the 3-place circuit",
     "set": {"label": "Intermediate 3-gang light switch (gang 1 intermediate) — corridor, outside the master bedroom door, 120 cm",
             "intermediate": True}},
    # 10. Lobby by the master-bedroom door: a double socket at 30 right under his switch-15, and Main's 45 on the living-door wall.
    {"item": 10, "op": "add", "main": "socket-lobby-30", "xy_from": "switch-15", "set": {"h": 0.3}},
    {"item": 10, "op": "add", "main": "socket-144"},
    # 11. Master bedsides: his two 2-gangs two-way with each other, rockers as Main's.
    {"item": 11, "op": "modify", "id": "switch-3", "gangs_from": "sw-bed-N", "changed": "made two-way with switch-4; gangs named as Main's",
     "set": {"two_way": "switch-4"}},
    {"item": 11, "op": "modify", "id": "switch-4", "gangs_from": "sw-bed-S", "changed": "made two-way with switch-3; gangs named as Main's",
     "set": {"two_way": "switch-3"}},
    # 12. Master bedroom: his door switch keeps its place with Main's door rockers; the stacked 110 moves beside the vanity at 120.
    {"item": 12, "op": "modify", "id": "switch-5", "gangs_from": "sw-master-door", "changed": "gangs named as Main's sw-master-door"},
    {"item": 12, "op": "modify", "id": "switch-6", "main_xy": "sw-master-dresser", "gangs_from": "sw-master-dresser",
     "changed": "moved beside the vanity (Main sw-master-dresser), 110 -> 120; vanity rockers",
     "set": {"h": 1.2, "label": "3-gang light switch — master bedroom, beside the vanity, 120 cm"}},
    # 13. Master bedroom: a double socket at 52 in the vanity's knee space.
    {"item": 13, "op": "add", "main": "socket-dresser-52"},
    # 14. Dressing: Main's 2-gang at 125 outside the bathroom door.
    {"item": 14, "op": "add", "main": "sw-master-dresser-spots"},
    # 15. Master bathroom: his 3-gang goes; Main's two boxes come in at 120 / 110. His 110 socket, on the same spot, moves
    #     along the wall to Main's socket-109 position so it doesn't clash with the 110 box. Fan / heater untouched.
    {"item": 15, "op": "remove", "id": "switch-7"},
    {"item": 15, "op": "add", "main": "sw-mbath", "set": {"h": 1.2, "label": "2-gang switch — master bathroom, inside beside the vanity socket, top box, 120 cm"}},
    {"item": 15, "op": "add", "main": "sw-mbath-2", "set": {"h": 1.1, "label": "2-gang switch — master bathroom, inside beside the vanity socket, lower box, 110 cm"}},
    {"item": 15, "op": "modify", "id": "socket-11", "along_from": "socket-109",
     "changed": "moved ~20 cm so it does not clash with the new 110 switch box"},
    # 16. Master bathroom: a socket inside the medicine cabinet at 139.
    {"item": 16, "op": "add", "main": "socket-110"},
    # 17. Kitchen: the plinth LED driver at 15, on a fourth rocker of his kitchen switch.
    {"item": 17, "op": "add", "main": "ledfeed-127"},
    {"item": 17, "op": "modify", "id": "switch-9", "add_gang": "Plinth LED (lower cabinets)", "changed": "3-gang -> 4-gang: gang 4 the plinth LED",
     "set": {"label": "4-gang light switch — kitchen, by the door, 110 cm"}},
    # 18. Guest bathroom: a ceiling motion sensor where Main has its presence sensor.
    {"item": 18, "op": "add", "main": "sensor-176", "drop": ["tech"], "set": {"h": 2.6, "label": "Motion sensor (MS) — guest bathroom ceiling"}},
    # 19. Guest bathroom: a socket at 130 right of the 120 / 110 box toward the vanity.
    {"item": 19, "op": "add", "main": "socket-141"},
    # Q1. AC power outlets (open question; the requested answer): Main's four split-AC points.
    *[{"item": "Q1", "op": "add", "main": m, "assumption": True} for m in ("power-103", "power-108", "power-168", "power-154")],
    # Q2. TV / HDMI heights (open question; the requested answer): living = a box at 120 and one at 60, each TV + HDMI;
    #     reception = TV + HDMI at 50.
    {"item": "Q2", "op": "add", "like": "tv-1", "assumption": True, "point": {
        "id": "tv-living-60", "h": 0.6, "label": "TV (dish) outlet — living room, TV wall, 60 cm"}},
    {"item": "Q2", "op": "add", "like": "hdmi-1", "assumption": True, "point": {
        "id": "hdmi-living-60", "h": 0.6, "label": "HDMI outlet — living room, TV wall, 60 cm"}},
    {"item": "Q2", "op": "modify", "id": "tv-3", "assumption": True, "changed": "120 -> 50",
     "set": {"h": 0.5, "label": "TV (dish) outlet — reception TV wall, 50 cm"}},
    {"item": "Q2", "op": "modify", "id": "hdmi-3", "assumption": True, "changed": "120 -> 50",
     "set": {"h": 0.5, "label": "HDMI outlet — reception TV wall, 50 cm"}},
]


def build():
    """(the layer, one log row per edit)."""
    pts = [dict(p) for p in LPP["points"]]
    by = {p["id"]: p for p in pts}
    eng_ids = set(by)
    removed, added, log = set(), [], []
    for e in EDITS:
        op, item = e["op"], e["item"]
        if op == "remove":
            assert e["id"] in by and e["id"] not in removed, e
            removed.add(e["id"])
            p = by[e["id"]]
        elif op == "modify":
            p = by[e["id"]]
            if p["status"] == "engineer":
                p["status"] = "requested"
            p["item"] = item
            if "main_xy" in e:
                m = MAIN[e["main_xy"]]
                p.update(x=m["x"], y=m["y"], facing=m["facing"])
            if "along_from" in e:  # along his wall (facing N/S: x; E/W: y), staying on it
                m = MAIN[e["along_from"]]
                p["x" if p["facing"] in "NS" else "y"] = m["x" if p["facing"] in "NS" else "y"]
            if "gangs_from" in e:
                p["gangs"] = list(MAIN[e["gangs_from"]]["gangs"])
            if "gang1" in e:
                p["gangs"] = [e["gang1"], *p["gangs"][1:]]
            if "add_gang" in e:
                p["gangs"] = [*p["gangs"], e["add_gang"]]
            if e.get("wp"):
                p["type"] = "wp"
                p["label"] = "Weatherproof socket (IP55) — " + p["label"].split(" — ", 1)[1]
            p.update(e.get("set", {}))
            if e.get("assumption"):
                p["assumption"] = True
            p["changed"] = e["changed"]
        else:
            if "main" in e:
                m = MAIN[e["main"]]
                pid = m["id"] if m["id"] not in eng_ids else "fe-" + m["id"]
                p = {}
                for k, v in m.items():
                    if k == "status":
                        p.update(status="requested", item=item, from_main=m["id"])
                    elif k != "gang_circuits" and k not in e.get("drop", ()):  # Main's circuit keys: his points have none
                        p[k] = list(v) if isinstance(v, list) else v
                p["id"] = pid
                if "xy_from" in e:
                    s = by[e["xy_from"]]
                    p.update(x=s["x"], y=s["y"], facing=s["facing"])
                p.update(e.get("set", {}))
            elif "like" in e:  # a twin of one of his points, at its x, y
                p = {k: v for k, v in by[e["like"]].items() if k not in ("src", "pdf", "dim", "note")}
                p.update(e["point"], status="requested", item=item)
            else:
                p = {**e["point"], "status": "requested", "item": item}
            if e.get("assumption"):
                p["assumption"] = True
            assert p["id"] not in by, p["id"]
            by[p["id"]] = p
            added.append(p)
        log.append({"item": item, "action": op, "id": p["id"], "type": p["type"], "room": p["room"], "x": p["x"], "y": p["y"],
                    "h": p["h"], "from_main": p.get("from_main", ""),
                    "note": "removed (as the PDF asks)" if op == "remove" else p.get("changed") or p["label"]})
    out = [p for p in pts if p["id"] not in removed] + added
    ids = [p["id"] for p in out]
    assert len(ids) == len(set(ids))
    legend = dict(LPP["legend"])
    legend.setdefault("power", "Dedicated power point (AC unit)")
    layer = {
        "version": "final-electrical",
        "source": "The site engineer's drawings (as the Light and Power Plan has them) plus Karim's final comments to him "
                  "(electrical-diff.pdf, 23 Nov 2026); requested points copied from Main where Main has them",
        "built_by": "build_electrical_final_electrical.py (edit its EDITS table, then rerun)",
        "heights": LPP["heights"],
        "lighting": LPP["lighting"],
        "legend": legend, "points": out, "lines": [],
    }
    return layer, log


if __name__ == "__main__":
    layer, log = build()
    OUT.write_text(json.dumps(layer, ensure_ascii=False, indent=1) + "\n")
    P = layer["points"]
    print(f"{OUT.name}: {len(P)} points ({len(LPP['points'])} engineer's; {len(log)} edits)")
    for k, v in sorted(Counter(p["type"] for p in P).items()):
        print(f"  {k:11s} {v}")
