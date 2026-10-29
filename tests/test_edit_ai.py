"""Edit AI: Undo after git sync, and every version having its own files.

    python3 -m unittest tests/test_edit_ai.py
"""
import os, shutil, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["EDIT_AI_GIT_SYNC"] = "0"
import edit_ai  # noqa: E402

V = "kareems-changes"
F = f"furnish-{V}.js"  # the version's own furniture file (26 Oct 2026)
CHAIR = "    const cw = mat.walnut, cf = mat.linenSlate;  // frame, upholstery"
BLACK = '    const cw = version === "kareems-changes" ? mat.chairBlack : mat.walnut, cf = mat.linenSlate;  // frame, upholstery'
SHARED = "    const cw = mat.chairBlack, cf = mat.linenSlate;  // frame, upholstery"


def furnish(chair):
    """The real furnish-<V>.js with the armchair's material line swapped for `chair`."""
    text = (REPO / F).read_text()
    line = next(l for l in text.splitlines() if "const cw =" in l)
    return text.replace(line, chair)


class Sandbox(unittest.TestCase):
    """A throwaway repo root with no Blob and no git sync."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="edit-ai-test-"))
        self.saved = edit_ai.ROOT, edit_ai.BLOB, edit_ai.git_sync
        edit_ai.ROOT, edit_ai.BLOB = self.root, False
        edit_ai._cache.clear()
        self.synced = []
        edit_ai.git_sync = lambda v, contents, summary: self.synced.append(contents) or "test"

    def tearDown(self):
        edit_ai.ROOT, edit_ai.BLOB, edit_ai.git_sync = self.saved
        edit_ai._cache.clear()
        shutil.rmtree(self.root, ignore_errors=True)

    def deploy(self, text):
        (self.root / F).write_text(text)

    def edit(self, text, summary):
        ws = edit_ai.Workspace(V)
        ws.plan_dirty = False
        ws.write("furnish.js", text.encode())
        try:
            return edit_ai.save(ws, summary)
        finally:
            shutil.rmtree(ws.tmp, ignore_errors=True)


class Undo(Sandbox):
    def test_undo_after_git_sync_restores_the_pre_edit_file(self):
        before, after = furnish(CHAIR), furnish(BLACK)
        self.deploy(before)
        self.edit(after, "black armchair")
        self.deploy(after)  # git_sync pushed it: deployed() IS the edit now (e9f8dba)
        res = edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1][F].decode(), before, "Undo must commit the pre-edit file, not the edit")
        self.assertEqual(res["shas"][F]["to"], edit_ai.sha(before.encode()))
        self.assertNotEqual(res["shas"][F]["to"], res["shas"][F]["from"])
        live = edit_ai.patches(V)["files"][F]  # the page loads the restored file
        self.assertEqual(live["sha"], edit_ai.sha(before.encode()))

    def test_a_lagging_deploy_of_an_undone_edit_does_not_bring_it_back(self):
        # 27 Oct 2026: edit A, undo A, edit B, undo B in under a minute; the bundle then caught up to A's commit (the
        # undo's commit not deployed yet) and the live file was merged onto it, so A came back. Our own states win.
        base, a, b = furnish(CHAIR), furnish(BLACK), furnish(CHAIR).replace("// frame, upholstery", "// frame, upholstery (b)")
        self.deploy(base)
        self.edit(a, "A")
        edit_ai.undo({"version": V})
        self.edit(b, "B")
        self.deploy(a)  # the deploy of A's commit lands now
        live = edit_ai.patches(V)["files"][F]
        self.assertEqual(live["sha"], edit_ai.sha(b.encode()), "the page must show B, not A merged back in")
        self.assertNotIn("chairBlack", edit_ai.Workspace(V).text("furnish.js"))

    def test_undo_takes_the_edit_off_git_not_a_lagging_bundle(self):
        # 27 Oct 2026: edit A (white doors), undo A, then edit B and undo B while the bundle was a build of A's commit:
        # B's undo took B off that bundle and kept A as a "later commit", so A came back. Undo works on git main.
        base, a = furnish(CHAIR), furnish(BLACK)
        b = base + "\n// B: an edit elsewhere in the file\n"  # a different line from A's (they'd merge, not conflict)
        git = {}
        saved = edit_ai.fresh, edit_ai.git_sync
        edit_ai.fresh = lambda p: git.get(p, edit_ai.deployed(p))
        edit_ai.git_sync = lambda v, contents, summary: git.update(contents) or "test"
        try:
            self.deploy(base)
            self.edit(a, "A")
            edit_ai.undo({"version": V})
            self.deploy(a)  # the build of A's commit lands; the undo's commit isn't built yet
            self.edit(b, "B")
            edit_ai.undo({"version": V})
            self.assertEqual(git[F].decode(), base, "undoing B must leave git as it was before B, without A")
        finally:
            edit_ai.fresh, edit_ai.git_sync = saved

    def test_undo_before_git_sync_goes_back_to_deployed(self):
        before = furnish(CHAIR)
        self.deploy(before)
        self.edit(furnish(BLACK), "black armchair")
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1][F].decode(), before)
        self.assertNotIn(F, edit_ai.patches(V)["files"])  # deployed already is the original

    def test_undo_keeps_later_unrelated_commits(self):
        before, after = furnish(CHAIR), furnish(BLACK)
        self.deploy(before)
        self.edit(after, "black armchair")
        later = after.replace("// --- Reception:", "// --- Reception (later commit):", 1)
        self.assertNotEqual(later, after)
        self.deploy(later)
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1][F].decode(), before.replace("// --- Reception:", "// --- Reception (later commit):", 1))

    def test_undo_of_the_second_edit_after_both_synced(self):
        a, b = furnish(CHAIR), furnish(BLACK)
        c = b.replace("mat.linenSlate;  // frame", 'version === "kareems-changes" ? mat.chairBlackFabric : mat.linenSlate;  // frame')
        self.deploy(a)
        self.edit(b, "black frame")
        self.deploy(b)
        self.edit(c, "black cushions")
        self.deploy(c)
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1][F].decode(), b)


class UndoStack(Sandbox):
    """Undo, Undo takes back the change before the last one; it used to undo the Undo (re-apply it: e2e J244 / J277)."""
    def test_second_undo_takes_back_the_change_before(self):
        a, b = furnish(CHAIR), furnish(BLACK)
        c = b.replace("mat.linenSlate;  // frame", 'version === "kareems-changes" ? mat.chairBlackFabric : mat.linenSlate;  // frame')
        self.deploy(a)
        self.edit(b, "black frame")
        self.edit(c, "black cushions")
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1][F].decode(), b)
        self.assertTrue(edit_ai.patches(V)["undo"])  # the black frame is still there to undo
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1][F].decode(), a)
        self.assertNotIn(F, edit_ai.patches(V)["files"])
        self.assertFalse(edit_ai.patches(V)["undo"])  # nothing left: no Undo offered (it used to redo)
        with self.assertRaises(ValueError):
            edit_ai.undo({"version": V})


class VersionIsolation(Sandbox):
    """Each version has its own furnish-<v>.js / materials-<v>.js: an edit in one never reaches another."""
    def test_own_file_names(self):
        self.assertEqual(edit_ai.own("karims-version", "furnish.js"), "furnish-karims-version.js")
        self.assertEqual(edit_ai.own("karims-version", "materials.js"), "materials-karims-version.js")
        self.assertEqual(edit_ai.own("karims-version", "tour-karims-version.json"), "tour-karims-version.json")

    def test_an_edit_stays_in_its_version(self):
        other = "karims-version"
        before = furnish(CHAIR)
        self.deploy(before)
        (self.root / f"furnish-{other}.js").write_text(before)
        res = self.edit(furnish(SHARED), "black armchair")  # a plain edit of the shared-looking line, no version check
        self.assertEqual(res["changed"], [F])
        self.assertIn(F, edit_ai.patches(V)["files"])
        self.assertEqual(edit_ai.patches(other)["files"], {})
        self.assertEqual((self.root / f"furnish-{other}.js").read_text(), before)

    def test_pre_split_override_already_pulled_drops_out(self):
        self.deploy(furnish(CHAIR))
        e = {"sha": "9924d0735c024e622ba3", "url": "x", "base": "y"}
        self.assertEqual(edit_ai.resolve({"version": V, "files": {"furnish.js": e}}), {})

    def test_pre_split_override_is_replayed_on_the_own_file(self):
        self.deploy(furnish(CHAIR))
        e = {"sha": "later", "url": "x", "base": "y", "ops": [{"old": "// --- Reception:", "new": "// --- Reception (live):"}]}
        st, _, content = edit_ai.resolve({"version": V, "files": {"furnish.js": e}})[F]
        self.assertEqual(st, "replayed")
        self.assertEqual(content.decode(), furnish(CHAIR).replace("// --- Reception:", "// --- Reception (live):"))


class VersionScope(unittest.TestCase):
    """version_scope / other_versions_changed: still used by Move and Resize on the leftover version checks."""
    def test_const_alias_branch_passes(self):
        # KC names Main and Karim's version since 26 Oct 2026; scope it to Main alone to test the alias itself
        f0 = furnish(CHAIR).replace('const KC = ["kareems-changes", "karims-version"].includes(version)',
                                    'const KC = version === "kareems-changes"')
        line = next(l for l in f0.splitlines() if "item(KC ? SC : 18.86" in l)
        f1 = f0.replace(line, line.replace("KC ? SC : 18.86", "KC ? SC + 0.1 : 18.86"))
        self.assertEqual(edit_ai.other_versions_changed(f0, f1, V), [])

    def test_new_block_for_this_version_passes(self):
        f0 = furnish(CHAIR)
        f1 = f0.replace("  rug(17.9, 2.906", f'  if (version === "{V}") {{\n    rug(1, 1, 2, 2);\n  }}\n  rug(17.9, 2.906', 1)
        self.assertNotEqual(f0, f1)
        self.assertEqual(edit_ai.other_versions_changed(f0, f1, V), [])


class PieceChecks(unittest.TestCase):
    """The deterministic wrong-piece / wrong-way checks (e2e r2 J244 J264 J266), on the real version files."""
    def check(self, v, message, old, new, ctx=None):
        ws = edit_ai.Workspace(v)
        ws.ctx = ctx or {}
        f0 = ws.text("furnish.js")
        self.assertEqual(f0.count(old), 1, old)
        return edit_ai.piece_checks(ws, message, f0, f0.replace(old, new), "")

    def test_toward_the_shower_the_wrong_way_is_sent_back(self):  # J264: the shower is north of the radiator
        out = self.check("naghams-changes", "Move the towel radiator 10 cm toward the shower",
                         "item(2.192, 7.6632", "item(2.192, 7.5632")
        self.assertTrue(out and out.startswith("Check the direction"), out)
        self.assertIsNone(self.check("naghams-changes", "Move the towel radiator 10 cm toward the shower",
                                     "item(2.192, 7.6632", "item(2.192, 7.7632"))

    def test_the_named_piece_wins_over_a_similar_one(self):  # J266: "flip desk" is the reception one, not the fold-down desk
        out = self.check("karims-version", "Widen flip desk 5 cm", "q.box(-0.42, 0.42, 0.75, 1.425, 0, 0.025, mat.limewash);",
                         "q.box(-0.445, 0.445, 0.75, 1.425, 0, 0.025, mat.limewash);")
        self.assertTrue(out and out.startswith("Check the piece") and "flip desk" in out, out)

    def test_a_piece_in_the_ring_named_by_one_word(self):  # J244: the buffet, not the vanity behind the same wall
        out = self.check("karims-version", "Shrink the buffet niche", "item(14.66, 7.75", "item(14.66, 8.035",
                         {"highlightBox": [14.37, 6.5, 15.81, 9.5]})
        self.assertTrue(out and "buffet" in out, out)

    def test_the_right_piece_passes(self):
        self.assertIsNone(self.check("karims-version", "Move the sofa 20 cm west", "item(21.027, version", "item(20.827, version",
                                     {"highlightBox": [19.9, 3.3, 21.2, 5.7]}))


    def test_the_landmark_isnt_the_piece(self):  # J235 / J250 r3: "closer to the table" names the table only as a landmark
        self.assertIsNone(self.check("naghams-changes", "Move the armchair next to the side table, keep the table where it is",
                                     '? 18.33 : 19.1, version', '? 18.33 : 19.4, version'))
        self.assertIsNone(self.check("naghams-changes", "Move each dining chair 5 cm closer to the dining table, keep the table",
                                     'item(x, 6.55, "N", p => chair(p));', 'item(x, 6.6, "N", p => chair(p));'))


class Round3(unittest.TestCase):
    """e2e round 3: dxf_edit op shapes, the reviewer's diff, Arabic claims."""
    def test_op_shorthand_and_zero_moves(self):  # J213 / J218 / J206
        ops, dropped = edit_ai.norm_ops([{"delete": ["1A"]}, {"type": "move_piece", "handle": "2B", "dx": 0.1, "dy": 0},
                                         {"handle": "3C", "dx": 0, "dy": -0.1}, {"handle": "4D", "grow": {"E": 0.1}},
                                         {"op": "move", "handles": ["A49"], "dx": 0, "dy": 0}, {"delete": []}])
        self.assertEqual([o["op"] for o in ops], ["delete", "move_piece", "move_piece", "resize_piece"])
        self.assertEqual(ops[0]["handles"], ["1A"])
        self.assertEqual(len(dropped), 2)

    def test_review_diff_drops_failed_and_discarded_ops(self):  # J207 / J215 / J222
        ws = SimpleNamespace(cfg={"dxf": "d", "model": "m", "drawing": "w", "tour": "t"}, changed=set(), orig={},
                             pieces={"2C7C": [1, 1, 2, 2]}, pieces_now={"2C7C": [0.8, 1, 1.8, 2]})
        trace = [{"tool": "dxf_edit", "args": "wrong way", "out": "{}"}, {"tool": "discard", "args": "", "out": ""},
                 {"tool": "dxf_edit", "args": "failed door", "out": "nothing changed: no arc"},
                 {"tool": "dxf_edit", "args": "the move", "out": "{}"}]
        d = edit_ai.edit_diff(ws, trace)
        self.assertIn("the move", d)
        self.assertNotIn("wrong way", d)
        self.assertNotIn("failed door", d)
        self.assertIn("2C7C: x 1..2, y 1..2 -> x 0.8..1.8", d)

    def test_arabic_claim(self):  # J223
        self.assertTrue(edit_ai.AR_CLAIM.search("رجّعت عمق خزانة المراية لـ٣٠ سم"))
        self.assertFalse(edit_ai.AR_CLAIM.search("ماغيّرتش حاجة"))


class DrawingSame(unittest.TestCase):
    def test_same_strokes_in_another_order(self):  # J229: a DXF rewritten with no net op isn't a change
        a = '{"strokes": {"#f00": [[0, 0, 1, 1], [2, 2, 3, 3]]}, "texts": []}'
        b = '{"strokes": {"#f00": [[2, 2, 3, 3.0001], [0, 0, 1, 1]]}, "texts": []}'
        self.assertTrue(edit_ai.drawing_same(a, b))
        self.assertFalse(edit_ai.drawing_same(a, '{"strokes": {"#f00": [[0, 0, 1, 1]]}, "texts": []}'))


if __name__ == "__main__":
    unittest.main()
