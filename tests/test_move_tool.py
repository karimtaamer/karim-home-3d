"""Move and Resize's furnish.js edits stay in their version: python3 tests/test_move_tool.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edit_ai as E  # noqa: E402
import move_tool as MT  # noqa: E402

V = "kareems-changes"
SRC = (Path(__file__).resolve().parent.parent / f"furnish-{V}.js").read_text()  # the version's own file (26 Oct 2026)


def call_at(text, needle, kind="item"):
    n = text[:text.index(needle)].count("\n") + 1
    return n, next(c for c in MT.calls_on_line(text, n) if c["kind"] == kind)


class Gating(unittest.TestCase):
    def leak(self, new):
        return E.other_versions_changed(SRC, new, V)

    def test_shared_literal_is_gated(self):
        n, c = call_at(SRC, 'item(4.645, 2.529, "S"')
        self.assertTrue(MT.scopes(SRC, V)(n))
        t = MT.set_xy(SRC, c, 4.745, 2.529, V, True)
        self.assertIn('item(version === "kareems-changes" ? 4.745 : 4.645, version === "kareems-changes" ? 2.529 : 2.529', t)
        self.assertEqual(self.leak(t), [])
        # a second move edits the gate, not a new one
        c2 = MT.calls_on_line(t, n)[0]
        self.assertEqual(MT.arg_num(c2["args"][0], V), 4.745)
        t2 = MT.set_xy(t, c2, 4.8, 2.529, V, True)
        self.assertEqual(t2.count('version === "kareems-changes" ? 4.8 : 4.645'), 1)

    def test_expression_and_spread(self):
        n, c = call_at(SRC, 'item(LKC ? 6.1396 : 6.16, 2.25, "W", p => {')
        t = MT.set_xy(SRC, c, 6.1396, 2.35, V, True)
        self.assertEqual(self.leak(t), [])
        n, c = call_at(SRC, "item(...(KC ? [SC + SO, 2.45]")
        t = MT.set_xy(SRC, c, 20.9, 2.45, V, True)
        self.assertIn('...(version === "kareems-changes" ? [20.9, 2.45] : KC ? [SC + SO, 2.45] : [20.341, 2.687])', t)
        self.assertEqual(self.leak(t), [])

    def test_sized_is_gated(self):
        n, c = call_at(SRC, 'item(4.645, 2.529, "S"')
        t = MT.set_size(SRC, c, 1.1, 1, V, True)
        self.assertIn('sized(item(4.645', t)
        self.assertEqual(self.leak(t), [])
        c2 = next(x for x in MT.calls_on_line(t, n) if x["kind"] == "item")
        back = MT.set_size(t, c2, 1, 1, V, True)
        self.assertEqual(back, SRC)

    def test_moved_table(self):
        piece = {"x": 2.94, "y": 2.0, "facing": "E"}
        t = MT.set_table(SRC, piece, 2.94, 2.1, 1, 1, V, "curtain")
        self.assertIn('if (version === "kareems-changes") MOVED["2.94,2,E"] = [2.94, 2.1, 1, 1];', t)
        self.assertEqual(self.leak(t), [])
        t2 = MT.set_table(t, piece, 2.94, 2.0, 1, 1, V, "curtain")  # back where the code puts it: the line goes
        self.assertEqual(t2, SRC)

    def test_niche_numbers(self):
        n, c = call_at(SRC, 'item(17.25, 3.67, "E"')
        t, old = MT.set_param(SRC, c, {"src": "tall", "at": [0], "x": [0, 1]}, -1.53, -1.15, V)
        self.assertEqual(old, (-1.53, -1.19))
        # KC also runs for Karim's version (its own plan since 26 Oct 2026), so a Main move gates its own value
        self.assertIn('const tall = version === "kareems-changes" ? [[-1.53, -1.15], [-1.12, -0.78]] : KC ? [[-1.53, -1.19], [-1.12, -0.78]] :', t)
        self.assertEqual(self.leak(t), [])
        n, c = call_at(SRC, 'item(14.79, 8.0, "E"')
        t, old = MT.set_param(SRC, c, {"src": "niche", "x": [0, 1]}, -1.0, -0.6, V)
        self.assertIn('const niche = version === "kareems-changes" ? [-1, -0.6, 0.42, 2.2, 0.13] : BK ?', t)
        self.assertEqual(self.leak(t), [])

    def test_part_line_gated(self):
        n, c = call_at(SRC, 'item(20.474, 9.5, "S"')
        shared = MT.scopes(SRC, V)(n)
        t = MT.set_part(SRC, c, "espresso machine", [0.05, 0], [1.2, 1], V, shared)
        self.assertEqual(self.leak(t), [])
        c2 = next(x for x in MT.calls_on_line(t, n) if x["kind"] == "item")
        t2 = MT.set_part(t, c2, "espresso machine", [0.1, 0], [1, 1], V, shared)
        self.assertEqual(t2.count("// Move and Resize: where this part sits"), 1)

    def test_turn_is_gated(self):
        self.assertEqual([MT.turned("S", 90), MT.turned("S", -90), MT.turned("W", 180), MT.turned("S", 45)], ["E", "W", "E", 0.7854])
        n = SRC[:SRC.index("// DWG armchair")].count("\n") + 1  # its x, y may carry other versions' gates
        c = next(x for x in MT.calls_on_line(SRC, n) if x["kind"] == "item")
        t = MT.set_facing(SRC, c, "E", V, MT.scopes(SRC, V)(n))
        self.assertIn(', version === "kareems-changes" ? "E" : "S", p => {  // DWG armchair', t)
        self.assertEqual(self.leak(t), [])
        c2 = next(x for x in MT.calls_on_line(t, n) if x["kind"] == "item")
        self.assertEqual(MT.facing_of(c2["args"][2], V), "E")
        self.assertEqual(MT.facing_of(c2["args"][2], "karims-version"), "S")
        self.assertEqual(MT.set_facing(t, c2, "S", V, True), SRC)  # turned back: the gate goes
        # a gated facing still finds its call
        n, c = call_at(SRC, 'item(KC ? SC : 18.86, 2.103, "N"')
        t = MT.set_facing(SRC, c, "E", V, MT.scopes(SRC, V)(n))
        self.assertEqual(MT.find_call(t, {"x": 19.342, "y": 2.103, "facing": "E", "lines": [n]}, V)["how"], "expr")

    def test_removed_line(self):
        piece = {"x": 18.4, "y": 6.55, "facing": "N"}
        t = MT.set_removed(SRC, piece, V, "chair")
        self.assertIn('if (version === "kareems-changes") REMOVED.add("18.4,6.55,N");  // Move and Resize: deleted chair', t)
        self.assertEqual(self.leak(t), [])
        self.assertEqual(MT.set_removed(t, piece, V, "chair"), t)  # deleting it again doesn't add a second line
        self.assertEqual(MT.set_removed(t, piece, V, "chair", gone=False), SRC)  # brought back: the line goes
        t2 = MT.set_removed(SRC, {**piece, "twins": 3, "twin": 2}, V, "pendant")  # one of several at the same spot
        self.assertIn('REMOVED.add("18.4,6.55,N#2");', t2)

    def test_fold_chained_ternary_and_unsized(self):
        self.assertEqual(E.for_version('x=version==="a"?1:K?2:3;', "b"), E.for_version("x=K?2:3;", "b"))
        self.assertEqual(E.for_version('f(sized(g(1),version==="a"?2:1,1));', "b"), "f(g(1));")



KV = "karims-version"
KSRC = (Path(__file__).resolve().parent.parent / f"furnish-{KV}.js").read_text()


class Heights(unittest.TestCase):
    """Z (Move and Resize up / down, taller / shorter) in Karim's version's file."""

    def test_sized_lift_and_height_fold_for_other_versions(self):
        n, c = call_at(KSRC, 'item(4.645, 2.529, "S"')
        t = MT.set_size(KSRC, c, 1, 1, KV, True, 1.2, 0.1)
        self.assertIn('sized(item(4.645', t)
        self.assertIn('1, 1, version === "karims-version" ? 1.2 : 1, version === "karims-version" ? 0.1 : 0)', t)
        self.assertEqual(E.other_versions_changed(KSRC, t, KV), [])
        c2 = next(x for x in MT.calls_on_line(t, n) if x["kind"] == "item")
        self.assertEqual(MT.sized_args(t, c2)[2:], ['version === "karims-version" ? 1.2 : 1', 'version === "karims-version" ? 0.1 : 0'])
        back = MT.set_size(t, c2, 1, 1, KV, True, 1, 0)  # back to as it was: no wrapper left
        self.assertEqual(back, KSRC)

    def test_table_up_lift_and_twin_key(self):
        piece = {"x": 18.4, "y": 7.6, "facing": "S", "twins": 3, "twin": 2}
        t = MT.set_table(KSRC, piece, 18.4, 7.6, 1, 1, KV, "pendant light", 1, 0.2)
        self.assertIn('MOVED["18.4,7.6,S#2"] = [18.4, 7.6, 1, 1, 1, 0.2];', t)
        self.assertEqual(MT.table_entry(t, piece, KV), [18.4, 7.6, 1, 1, 1, 0.2])
        self.assertEqual(MT.set_table(t, piece, 18.4, 7.6, 1, 1, KV, "pendant light"), KSRC)

    def test_two_pieces_on_one_line_refind_the_right_one(self):
        # item(16.95, 7.6, "E", ...); item(19.85, 7.6, "W", ...): after moving the second, re-finding it by where its
        # call starts keeps the second (the first of its kind on the line is the other chair)
        n, _ = call_at(KSRC, 'item(19.85, 7.6, "W"')
        c = next(x for x in MT.calls_on_line(KSRC, n) if x["args"][0].strip() == "19.85")
        t = MT.set_xy(KSRC, c, 19.85, 7.625, KV, True)
        c2 = next(x for x in MT.calls_on_line(t, n) if x["name"] == c["name"])
        self.assertEqual(MT.arg_num(c2["args"][1], KV), 7.625)
        t2 = MT.set_size(t, c2, 1.09, 1, KV, True)
        self.assertIn('sized(item(version === "karims-version" ? 19.85 : 19.85', t2)
        self.assertIn('item(16.95, 7.6, "E"', t2)


NV = "naghams-changes"
NSRC = (Path(__file__).resolve().parent.parent / f"furnish-{NV}.js").read_text()


class NaghamsRunsAsMain(unittest.TestCase):
    """Nagham's file runs Main's branches (`if (version === "naghams-changes") version = "kareems-changes";`): Move's
    lines must be gated on what the code sees, or they never run (e2e 28 Oct 2026: J027 / J127 / J258 / J285)."""
    def test_alias_read(self):
        self.assertEqual(E.runs_as(NSRC, NV), "kareems-changes")
        self.assertEqual(E.runs_as(KSRC, KV), KV)

    def test_main_branch_runs_here(self):  # the dining fold-down desk: was refused as "another plan version" (J149)
        n = NSRC[:NSRC.index('item(18.55, 9.502, "S"')].count("\n") + 1
        self.assertIsNot(E.version_scope(NSRC, NV)[n - 1], False)

    def test_moved_line_runs(self):
        cv = E.runs_as(NSRC, NV)
        piece = {"x": 24.5, "y": 5.75, "facing": "S"}
        t = MT.set_table(NSRC, piece, 24.3, 5.75, 1, 1, cv, "potted plant")
        self.assertIn('if (version === "kareems-changes") MOVED["24.5,5.75,S"] = [24.3, 5.75, 1, 1];', t)
        self.assertNotEqual(E.for_version(t, NV), E.for_version(NSRC, NV))  # it changes what Nagham's runs
        self.assertEqual(MT.set_table(t, piece, 24.5, 5.75, 1, 1, cv, "potted plant"), NSRC)

    def test_removed_line_runs(self):
        cv = E.runs_as(NSRC, NV)
        t = MT.set_removed(NSRC, {"x": 24.5, "y": 5.75, "facing": "S"}, cv, "potted plant")
        self.assertNotEqual(E.for_version(t, NV), E.for_version(NSRC, NV))

    def test_niche_gate_edited_again(self):  # a second Move on a niche it gated: edits its own array (J314)
        n, c = call_at(KSRC, 'item(14.79, 8.0, "E"')
        t, _ = MT.set_param(KSRC, c, {"src": "niche", "x": [0, 1]}, -1.0, -0.6, KV)
        self.assertIn('const niche = version === "karims-version" ? [-1, -0.6, 0.42, 2.2, 0.13] :', t)
        c2 = next(x for x in MT.calls_on_line(t, n) if x["kind"] == "item")
        t2, old = MT.set_param(t, c2, {"src": "niche", "x": [0, 1]}, -1.05, -0.6, KV)
        self.assertEqual(old, (-1.0, -0.6))
        self.assertIn('const niche = version === "karims-version" ? [-1.05, -0.6, 0.42, 2.2, 0.13] :', t2)
        self.assertEqual(t2.count('version === "karims-version" ? [-1.05'), 1)


class Round3(unittest.TestCase):
    """e2e round 3: loop pieces turn through MOVED, walls stop a piece that was clear, 3D clash notes."""
    def test_loop_piece_turns_through_its_moved_entry(self):  # J101: Nagham's dining chair, placed by a loop
        src = (Path(__file__).resolve().parent.parent / "furnish-naghams-changes.js").read_text()
        self.assertIn("moved[6]", src)
        piece = {"x": 17.6, "y": 6.55, "facing": "N"}
        t = MT.set_table(src, piece, 17.6, 6.55, 1, 1, "naghams-changes", "chair", turn=2.3562)
        self.assertIn('MOVED["17.6,6.55,N"] = [17.6, 6.55, 1, 1, 1, 0, 2.3562];', t)
        self.assertEqual(MT.table_entry(t, piece, "naghams-changes")[6], 2.3562)
        back = MT.set_table(t, piece, 17.6, 6.55, 1, 1, "naghams-changes", "chair", turn=-3.14159265)  # facing N again
        self.assertEqual(back, src)

    def test_into_a_wall_only_from_clear(self):  # J196: a pantry flush on its wall, nudged 1 cm into it
        wall = [((6.475, 5.0), (6.475, 8.0))]
        self.assertTrue(MT.into_wall(wall, [6.4747, 6.0, 7.6666, 6.6], [6.4647, 6.0, 7.6566, 6.6]))
        self.assertFalse(MT.into_wall(wall, [6.4747, 6.0, 7.6666, 6.6], [6.4847, 6.0, 7.6766, 6.6]))  # away from it
        self.assertFalse(MT.into_wall(wall, [6.3, 6.0, 7.5, 6.6], [6.2, 6.0, 7.4, 6.6]))  # already in it: slides (J317)

    def test_3d_clash_note(self):  # J302: a table made 40 cm longer over its end chair
        chair = [19.359, 7.32, 19.86, 7.88, 0, 0.9]
        piece = {"low": 0, "high": 0.75, "others": [chair, [16.5, 6.8, 20.5, 8.4, 0, 0.01]]}
        self.assertTrue(MT.clash_3d(piece, [17.2, 7.1, 19.6, 8.1], [17.2, 7.1, 20.0, 8.1]))
        self.assertEqual(MT.clash_3d(piece, [17.2, 7.1, 19.6, 8.1], [17.1, 7.1, 19.5, 8.1]), [])  # away from it
        self.assertEqual(MT.clash_3d({**piece, "others": [chair[:4]]}, [17.2, 7.1, 19.6, 8.1], [17.2, 7.1, 20.0, 8.1]), [])

    def test_shrink_clash_is_not_new(self):  # J121 / J137: an overlap it already had isn't "now runs into"
        self.assertEqual(MT.clash_notes({"clashes": [{"with": "wall 1A", "was": True}]}), [])
        self.assertEqual(MT.clash_notes({"clashes": [{"with": "wall 1A"}]}), ["it now runs into a wall"])


if __name__ == "__main__":
    unittest.main()
