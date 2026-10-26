"""Edit AI openings: heights and kind per opening (set_openings), and doors / windows added, converted and walled up
on the plan (dxf_edit add / convert / remove_opening), through the same tool calls the model makes, rebuilt for real.
No model is called. Needs the DWG Python (ezdxf + shapely; ~/.dwg-tools/bin/python here), else skipped.

    python3 -m unittest tests/test_edit_ai_openings.py
"""
import json, os, shutil, sys, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["EDIT_AI_GIT_SYNC"] = "0"
import edit_ai  # noqa: E402

V = "kareems-changes"


def model(ws):
    s = ws.text(ws.cfg["model"])
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


def inside(ring, x, y):
    c = False
    for i in range(len(ring)):
        (x1, y1), (x2, y2) = ring[i], ring[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def opening_at(m, x, y):
    return next((o for o in m["openings"] if inside(o["outer"], x, y)), None)


def centre(o):
    xs, ys = [q[0] for q in o["outer"]], [q[1] for q in o["outer"]]
    return sum(xs) / len(xs), sum(ys) / len(ys)


@unittest.skipUnless(edit_ai.plan_edits(), "no DWG Python (ezdxf + shapely) here")
class Openings(unittest.TestCase):
    def setUp(self):
        self.saved = edit_ai.BLOB
        edit_ai.BLOB = False
        self.ws = edit_ai.Workspace(V)
        ws = self.ws
        ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = False, False, {}, {}, [], []
        ws.pieces_now, ws.win_moved, ws.allow_as_built = {}, [], False
        edit_ai.rebuild(ws)  # the version as the DXF builds it today, the baseline for each test

    def tearDown(self):
        edit_ai.BLOB = self.saved
        shutil.rmtree(self.ws.tmp, ignore_errors=True)

    def finish(self):
        edit_ai.rebuild(self.ws)
        self.ws.plan_dirty = False
        return model(self.ws)

    def test_terrace_slider_kept_a_window_with_wall_under_it(self):
        m0 = model(self.ws)
        slider = next(o for o in m0["openings"] if o["kind"] == "slider")
        x, y = centre(slider)
        out = edit_ai.tool(self.ws, "set_openings", {"openings": [{"at": [x, y], "kind": "window", "sill": 0.6}]})
        self.assertIn("'sill': 0.6", out)
        o = opening_at(self.finish(), x, y)
        self.assertEqual((o["kind"], o["sill"], o["head"]), ("window", 0.6, m0["sliderHead"]), "the top stays where it was")
        self.assertEqual(sum(1 for q in model(self.ws)["openings"] if q["kind"] == "slider"),
                         sum(1 for q in m0["openings"] if q["kind"] == "slider") - 1, "only that one changes")

    def test_window_to_door_and_back(self):
        m0 = model(self.ws)
        win = next(o for o in m0["openings"] if o["kind"] == "window" and "sill" not in o)
        x, y = centre(win)
        along_x = max(q[0] for q in win["outer"]) - min(q[0] for q in win["outer"]) > 0.5
        inward = ("S" if y > 5 else "N") if along_x else ("E" if x < 12 else "W")  # into the flat
        out = edit_ai.tool(self.ws, "dxf_edit", {"ops": [{"op": "convert_opening", "at": [x, y], "to": "door", "width": 0.9,
                                                          "hinge": "start", "opens": inward}]})
        self.assertNotIn("nothing changed", out)
        m1 = self.finish()
        self.assertEqual(opening_at(m1, x, y)["kind"], "door")
        self.assertTrue(any(abs(s["hinge"][0] - x) < 0.8 and abs(s["hinge"][1] - y) < 0.8 for s in m1["swings"]), "it swings")
        self.assertIn("doorsAsDrawn", json.loads(self.ws.text(self.ws.cfg["tour"])))
        self.assertIsNone(edit_ai.lost_openings(self.ws), "a conversion isn't a lost opening")
        edit_ai.tool(self.ws, "dxf_edit", {"ops": [{"op": "convert_opening", "at": [x, y], "to": "window", "width": 1.0}]})
        self.assertEqual(opening_at(self.finish(), x, y)["kind"], "window")

    def test_door_to_wooden_sliding_door(self):
        m0 = model(self.ws)
        door = next(o for o in m0["openings"] if o["kind"] == "door"
                    and 0.8 <= max(max(q[0] for q in o["outer"]) - min(q[0] for q in o["outer"]),
                                   max(q[1] for q in o["outer"]) - min(q[1] for q in o["outer"])) <= 1.3)
        x, y = centre(door)
        out = edit_ai.tool(self.ws, "dxf_edit", {"ops": [{"op": "convert_opening", "at": [x, y], "to": "sliding_door"}]})
        self.assertNotIn("nothing changed", out)
        o = opening_at(self.finish(), x, y)
        self.assertEqual((o["kind"], o.get("panel"), o.get("head")), ("slider", "wood", 2.1))

    def test_home_heights(self):
        edit_ai.tool(self.ws, "set_openings", {"home": {"ceiling": 2.8, "door": 2.3}})
        m = self.finish()
        self.assertEqual((m["ceiling"], m["doorHead"]), (2.8, 2.3))
        self.assertTrue(all(w["height"] in (2.8, 1.1) for w in m["walls"]))
        with self.assertRaises(ValueError):
            edit_ai.tool(self.ws, "set_openings", {"home": {"ceiling": 9}})

    def test_remove_opening_is_a_lost_opening_unless_asked(self):
        m0 = model(self.ws)
        win = next(o for o in m0["openings"] if o["kind"] == "window" and "sill" not in o)
        x, y = centre(win)
        edit_ai.tool(self.ws, "dxf_edit", {"ops": [{"op": "remove_opening", "at": [x, y]}]})
        self.assertIsNone(opening_at(self.finish(), x, y))
        self.assertIn("lost", edit_ai.lost_openings(self.ws) or "")


if __name__ == "__main__":
    unittest.main()
