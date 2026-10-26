"""Edit AI home tools: room finishes (set_room), walls (add / remove / move / thickness, low and glass), room names,
niches, door looks and double doors, notes, measuring, pictures and saving a big job in parts, through the same tool
calls the model makes, rebuilt for real. No model is called. Needs the DWG Python (ezdxf + shapely), else skipped.

    python3 -m unittest tests/test_edit_ai_home.py
"""
import json, os, shutil, sys, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["EDIT_AI_GIT_SYNC"] = "0"
import edit_ai  # noqa: E402

V = "kareems-changes"
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def model(ws):
    s = ws.text(ws.cfg["model"])
    return json.loads(s[s.index("{"):s.rindex("}") + 1])


@unittest.skipUnless(edit_ai.plan_edits(), "no DWG Python (ezdxf + shapely) here")
class Home(unittest.TestCase):
    def setUp(self):
        self.saved = edit_ai.BLOB, edit_ai.ROOT
        edit_ai.BLOB = False
        self.ws = edit_ai.Workspace(V)
        ws = self.ws
        ws.plan_dirty, ws.dxf_furni, ws.pieces, ws.clashes, ws.new_outlines, ws.moves = False, False, {}, {}, [], []
        ws.pieces_now, ws.win_moved, ws.allow_as_built, ws.refs, ws.message = {}, [], False, [PNG], "test"
        edit_ai.rebuild(ws)

    def tearDown(self):
        edit_ai.BLOB, edit_ai.ROOT = self.saved
        shutil.rmtree(self.ws.tmp, ignore_errors=True)

    def tool(self, name, args):
        out = edit_ai.tool(self.ws, name, args)
        self.assertNotIn("nothing changed:", out, out)
        return out

    def finish(self):
        edit_ai.rebuild(self.ws)
        self.ws.plan_dirty = False
        return model(self.ws)

    def tour(self):
        return json.loads(self.ws.text(self.ws.cfg["tour"]))

    def test_room_finishes(self):
        self.tool("set_room", {"room": "LIVING ROOM", "floor": "herringbone", "walls": "#a3b18a", "skirting": 0.12,
                               "ceiling": "#2b2b2b", "ceilingHeight": 2.4, "light": {"brightness": 1.5, "warmth": "neutral"},
                               "skylights": [{"at": [4.5, 2.5], "w": 0.8, "d": 0.8}]})
        self.tool("set_room", {"room": "TOILET 1", "tileHeight": 1.2, "walls": "#ffffff", "tiles": "porcelain"})
        self.tool("set_room", {"room": "MASTER BEDROOM", "floor": "wood", "floorLevel": 0.2})
        m = self.finish()
        self.assertEqual(m["rooms"]["LIVING ROOM"]["floor"], "herringbone")
        self.assertEqual(m["rooms"]["TOILET 1"]["tileHeight"], 1.2)
        self.assertEqual(self.tour()["finishes"]["MASTER BEDROOM"], "wood", "the plain finishes stay in finishes")
        with self.assertRaises(ValueError):
            self.tool("set_room", {"room": "LIVING ROOM", "floor": "unobtainium"})
        with self.assertRaises(ValueError):
            self.tool("set_room", {"room": "NOWHERE", "floor": "wood"})

    def test_rename_moves_the_specs_with_the_room(self):
        self.tool("set_room", {"room": "LAUNDRY", "walls": "#ffffff"})
        self.tool("dxf_edit", {"ops": [{"op": "rename_room", "name": "LAUNDRY", "to": "UTILITY"}]})
        m = self.finish()
        self.assertIn("UTILITY", {f["room"] for f in m["floor"]})
        self.assertIn("UTILITY", self.tour()["rooms"])
        self.assertNotIn("LAUNDRY", self.tour()["rooms"])

    def test_partition_with_a_new_room_and_a_low_wall(self):
        before = model(self.ws)
        self.tool("dxf_edit", {"ops": [{"op": "add_wall", "a": [2.9, 2.5], "b": [6.2, 2.5]},
                                       {"op": "add_room_label", "at": [4.0, 1.4], "name": "STUDY"}]})
        m = self.finish()
        self.assertIn("STUDY", {f["room"] for f in m["floor"]})
        self.assertLess(sum(f["room"] == "LIVING ROOM" for f in m["floor"]) and
                        sum(abs(edit_ai._ring_area(f["outer"])) for f in m["floor"] if f["room"] == "LIVING ROOM"),
                        sum(abs(edit_ai._ring_area(f["outer"])) for f in before["floor"] if f["room"] == "LIVING ROOM"))
        self.tool("dxf_edit", {"ops": [{"op": "mark_wall", "at": [4.5, 2.5], "height": 1.1, "glass": True}]})
        m = self.finish()
        self.assertTrue(any(w.get("glass") and abs(w["height"] - 1.1) < 1e-6 for w in m["walls"]))

    def test_remove_move_and_thicken_a_wall(self):
        self.tool("dxf_edit", {"ops": [{"op": "move_wall", "at": [10.27, 8.0], "dx": 0.1, "dy": 0}]})
        self.finish()
        self.tool("dxf_edit", {"ops": [{"op": "set_wall_thickness", "at": [10.37, 8.0], "thickness": 0.2}]})
        self.finish()
        out = self.tool("dxf_edit", {"ops": [{"op": "remove_wall", "at": [10.37, 8.0]}]})
        self.assertIn("removed", out)
        self.finish()

    def test_niche_and_door_looks(self):
        self.tool("dxf_edit", {"ops": [{"op": "add_niche", "at": [2.92, 2.0], "width": 0.6, "depth": 0.08, "bottom": 0.9, "top": 1.5}]})
        m = self.finish()
        self.assertEqual(len(m["niches"]), 1)
        self.assertEqual((m["niches"][0]["bottom"], m["niches"][0]["top"]), (0.9, 1.5))
        door = next(o for o in m["openings"] if o["kind"] == "door")
        xs, ys = [q[0] for q in door["outer"]], [q[1] for q in door["outer"]]
        c = [sum(xs) / 4, sum(ys) / 4]
        self.tool("set_openings", {"openings": [{"at": c, "leaf": "#ffffff", "style": "panelled", "handle": "brass", "fanlight": 0.3}]})
        m = self.finish()
        o = next(o for o in m["openings"] if o["kind"] == "door" and o.get("style") == "panelled")
        self.assertEqual((o["leaf"], o["handle"], o["fanlight"]), ("#ffffff", "brass", 0.3))

    def test_double_doors_swing_both_leaves(self):
        out = self.tool("dxf_edit", {"ops": [{"op": "convert_opening", "at": [8.1, 9.18], "to": "double_door", "width": 1.1, "opens": "S"}]})
        m = self.finish()
        sw = [s for s in m["swings"] if 7.4 < s["hinge"][0] < 8.8 and 8.9 < s["hinge"][1] < 9.3]
        self.assertEqual(len(sw), 2, out)

    def test_notes_start_measure_and_picture(self):
        self.tool("set_home", {"notes": [{"at": [8.1, 9.0], "text": "underfloor heating"}], "start": [22.0, 5.0]})
        m = self.finish()
        self.assertEqual(m["notes"][0]["text"], "underfloor heating")
        q = json.loads(self.tool("measure", {"room": "KITCHEN"}))
        self.assertGreater(q["rooms"][0]["floor_m2"], 5)
        self.assertGreater(q["rooms"][0]["wall_m2_net"], 10)
        out = self.tool("save_picture", {"ref": 1, "name": "family"})
        self.assertIn("mat.picFamily", out)
        self.assertIn("picFamily: std({ map: picture(\"uploads/picFamily-", self.ws.text("materials.js"))
        self.assertTrue(any(p.startswith("uploads/") for p in self.ws.changed))

    def test_save_progress_keeps_a_part(self):
        root, blob = edit_ai.ROOT, edit_ai.BLOB
        tmp = self.ws.tmp / "root"
        tmp.mkdir()
        edit_ai.ROOT = tmp  # revisions go to a scratch store
        saved_fns = {n: getattr(edit_ai, n) for n in ("git_sync", "review", "lock_breaks", "version_leak")}
        edit_ai.git_sync = lambda v, c, s: "test"
        edit_ai.review = lambda ws, m, r: None  # the gates have their own tests; here: the part is saved
        edit_ai.lock_breaks = lambda ws, m, record=False: None
        edit_ai.version_leak = lambda ws, m: None
        try:
            for f in ("furnish.js", "materials.js"):
                (tmp / f).write_bytes((REPO / f).read_bytes())
            self.ws.write("furnish.js", self.ws.read("furnish.js") + b"\n// part one\n")
            self.ws.plan_dirty = False
            out = edit_ai.save_progress(self.ws, "add a comment", "part one")
            self.assertIn("saved (revision", out)
            self.assertFalse(self.ws.changed)
        finally:
            edit_ai.ROOT, edit_ai.BLOB = root, blob
            for n, f in saved_fns.items():
                setattr(edit_ai, n, f)


if __name__ == "__main__":
    unittest.main()
