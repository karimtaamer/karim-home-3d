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


if __name__ == "__main__":
    unittest.main()
