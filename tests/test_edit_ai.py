"""Edit AI: Undo after git sync, and one version's change staying in that version.

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
CHAIR = "    const cw = mat.walnut, cf = mat.linenSlate;  // frame, upholstery"
BLACK = '    const cw = version === "kareems-changes" ? mat.chairBlack : mat.walnut, cf = mat.linenSlate;  // frame, upholstery'
SHARED = "    const cw = mat.chairBlack, cf = mat.linenSlate;  // frame, upholstery"


def furnish(chair):
    """The real furnish.js with the armchair's material line swapped for `chair`."""
    text = (REPO / "furnish.js").read_text()
    line = next(l for l in text.splitlines() if "const cw =" in l)
    return text.replace(line, chair)


class Undo(unittest.TestCase):
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
        (self.root / "furnish.js").write_text(text)

    def edit(self, text, summary):
        ws = edit_ai.Workspace(V)
        ws.plan_dirty = False
        ws.write("furnish.js", text.encode())
        try:
            return edit_ai.save(ws, summary)
        finally:
            shutil.rmtree(ws.tmp, ignore_errors=True)

    def test_undo_after_git_sync_restores_the_pre_edit_file(self):
        before, after = furnish(CHAIR), furnish(BLACK)
        self.deploy(before)
        self.edit(after, "black armchair")
        self.deploy(after)  # git_sync pushed it: deployed() IS the edit now (e9f8dba)
        res = edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1]["furnish.js"].decode(), before, "Undo must commit the pre-edit file, not the edit")
        self.assertEqual(res["shas"]["furnish.js"]["to"], edit_ai.sha(before.encode()))
        self.assertNotEqual(res["shas"]["furnish.js"]["to"], res["shas"]["furnish.js"]["from"])
        live = edit_ai.patches(V)["files"]["furnish.js"]  # the page loads the restored file
        self.assertEqual(live["sha"], edit_ai.sha(before.encode()))

    def test_undo_before_git_sync_goes_back_to_deployed(self):
        before = furnish(CHAIR)
        self.deploy(before)
        self.edit(furnish(BLACK), "black armchair")
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1]["furnish.js"].decode(), before)
        self.assertNotIn("furnish.js", edit_ai.patches(V)["files"])  # deployed already is the original

    def test_undo_keeps_later_unrelated_commits(self):
        before, after = furnish(CHAIR), furnish(BLACK)
        self.deploy(before)
        self.edit(after, "black armchair")
        later = after.replace("// --- Reception:", "// --- Reception (later commit):", 1)
        self.assertNotEqual(later, after)
        self.deploy(later)
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1]["furnish.js"].decode(), before.replace("// --- Reception:", "// --- Reception (later commit):", 1))

    def test_undo_of_the_second_edit_after_both_synced(self):
        a, b = furnish(CHAIR), furnish(BLACK)
        c = b.replace("mat.linenSlate;  // frame", 'version === "kareems-changes" ? mat.chairBlackFabric : mat.linenSlate;  // frame')
        self.deploy(a)
        self.edit(b, "black frame")
        self.deploy(b)
        self.edit(c, "black cushions")
        self.deploy(c)
        edit_ai.undo({"version": V})
        self.assertEqual(self.synced[-1]["furnish.js"].decode(), b)


class VersionIsolation(unittest.TestCase):
    def ws(self, f1, mats0=None, mats1=None):
        files = {"furnish.js": f1.encode()}
        orig = {"furnish.js": furnish(CHAIR).encode()}
        if mats0 is not None:
            files["materials.js"], orig["materials.js"] = mats1.encode(), mats0.encode()
        return SimpleNamespace(v=V, orig=orig, changed=set(files), text=lambda p: files[p].decode())

    def test_ternary_for_this_version_passes(self):
        self.assertIsNone(edit_ai.version_leak(self.ws(furnish(BLACK)), "make the armchair black"))

    def test_shared_line_change_is_refused(self):
        msg = edit_ai.version_leak(self.ws(furnish(SHARED)), "make the armchair black")
        self.assertIn("Check the version", msg)
        self.assertIn(f'version === "{V}" ?', msg)

    def test_all_versions_when_asked(self):
        self.assertIsNone(edit_ai.version_leak(self.ws(furnish(SHARED)), "make the armchair black in all versions"))

    def test_other_versions_branch_only(self):
        f = furnish(BLACK.replace('version === "kareems-changes"', 'version !== "kareems-changes"'))
        self.assertIn("Check the version", edit_ai.version_leak(self.ws(f), "make the armchair black"))

    def test_const_alias_branch_passes(self):
        f0 = furnish(CHAIR)
        line = next(l for l in f0.splitlines() if "item(KC ? SC : 18.86" in l)
        f1 = f0.replace(line, line.replace("KC ? SC : 18.86", "KC ? SC + 0.1 : 18.86"))
        self.assertEqual(edit_ai.other_versions_changed(f0, f1, V), [])

    def test_new_block_for_this_version_passes(self):
        f0 = furnish(CHAIR)
        f1 = f0.replace("  rug(17.9, 2.906", f'  if (version === "{V}") {{\n    rug(1, 1, 2, 2);\n  }}\n  rug(17.9, 2.906', 1)
        self.assertNotEqual(f0, f1)
        self.assertEqual(edit_ai.other_versions_changed(f0, f1, V), [])

    def test_changing_an_existing_material_is_refused(self):
        m0 = (REPO / "materials.js").read_text()
        m1 = m0.replace("chairBlack: std({ color: 0x161514", "chairBlack: std({ color: 0x000000", 1)
        self.assertNotEqual(m0, m1)
        msg = edit_ai.version_leak(self.ws(furnish(CHAIR), m0, m1), "make it darker")
        self.assertIn("chairBlack", msg)


if __name__ == "__main__":
    unittest.main()
