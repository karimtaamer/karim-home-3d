"""Move and Resize's furnish.js edits stay in their version: python3 tests/test_move_tool.py"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import edit_ai as E  # noqa: E402
import move_tool as MT  # noqa: E402

V = "kareems-changes"
SRC = (Path(__file__).resolve().parent.parent / "furnish.js").read_text()


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

    def test_fold_chained_ternary_and_unsized(self):
        self.assertEqual(E.for_version('x=version==="a"?1:K?2:3;', "b"), E.for_version("x=K?2:3;", "b"))
        self.assertEqual(E.for_version('f(sized(g(1),version==="a"?2:1,1));', "b"), "f(g(1));")


if __name__ == "__main__":
    unittest.main()
