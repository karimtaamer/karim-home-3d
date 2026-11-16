"""site_measurements.py: last-write-wins merge, validation, the Blob revisions (a fake in-memory store) and the HTTP
handler on disk. Run: python3 tests/test_site_measurements.py (stdlib only, no network)."""
import json, sys, tempfile, threading, unittest, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import photogen_blob  # noqa: E402
import site_measurements as sm  # noqa: E402

V = "new-asbuilt"


class FakeBlob:
    """photogen_blob's put / get / names / delete over a dict, with a token so site_measurements uses it."""

    def __init__(self):
        self.files = {}
        self.saved = {k: getattr(photogen_blob, k) for k in ("token", "put", "get", "names", "delete")}

    def __enter__(self):
        photogen_blob.token = lambda: "vercel_blob_rw_store_secret"
        photogen_blob.put = lambda path, data, mime, overwrite=False: self.files.__setitem__(path, data) or path
        photogen_blob.get = lambda path: self.files[path]
        photogen_blob.names = lambda prefix: [p for p in self.files if p.startswith(prefix)]
        photogen_blob.delete = lambda paths: [self.files.pop(p, None) for p in paths]
        return self

    def __exit__(self, *a):
        for k, f in self.saved.items():
            setattr(photogen_blob, k, f)


def e(value, updated, note=""):
    return {"value": value, "note": note, "updated": updated}


class Merge(unittest.TestCase):
    def test_newer_wins_per_piece(self):
        a = {"w1": e(100, 10), "w2": e(200, 30)}
        b = {"w1": e(101, 20), "w2": e(199, 25), "w3": e(50, 5)}
        m = sm.merge(a, b)
        self.assertEqual(m["w1"]["value"], 101)  # b newer
        self.assertEqual(m["w2"]["value"], 200)  # a newer
        self.assertEqual(m["w3"]["value"], 50)  # only in b

    def test_clear_is_kept_as_null(self):
        m = sm.merge({"w1": e(100, 10)}, sm.clean({"w1": e(None, 11)}))
        self.assertIsNone(m["w1"]["value"])

    def test_clean_rejects_bad_input(self):
        for bad in ({"w": e("12", 1)}, {"w": e(12, 0)}, {"w": e(-1, 1)}, {"w": e(True, 1)}, {"": e(1, 1)}, ["x"]):
            with self.assertRaises(ValueError):
                sm.clean(bad)
        c = sm.clean({"w": {**e(312.5, 1, "x" * 900), "room": "LIVING ROOM", "kind": "wall", "drawn": 310.2, "evil": 1}})
        self.assertEqual(len(c["w"]["note"]), 500)
        self.assertNotIn("evil", c["w"])
        self.assertEqual(c["w"]["room"], "LIVING ROOM")

    def test_unknown_version(self):
        with self.assertRaises(ValueError):
            sm.version("kareems-changes")


class BlobStore(unittest.TestCase):
    def test_save_load_and_lww_across_devices(self):
        with FakeBlob() as fb:
            sm.save(V, {"w1": e(100, 10), "w2": e(200, 10)})  # phone
            doc = sm.save(V, {"w1": e(90, 5), "w3": e(300, 12)})  # laptop, with an older edit of w1
            self.assertEqual(doc["entries"]["w1"]["value"], 100)
            self.assertEqual(set(sm.load(V)["entries"]), {"w1", "w2", "w3"})
            self.assertTrue(all(p.startswith("site-measurements/new-asbuilt/") for p in fb.files))

    def test_two_saves_at_once_both_survive(self):
        with FakeBlob() as fb:
            sm.save(V, {"w1": e(100, 10)})
            base = sm.load(V)
            # Two requests read the same state, then each writes its own revision.
            for k, ms in (("a", 111), ("b", 112)):
                doc = {"version": V, "entries": sm.merge(base["entries"], {k: e(1, ms)}), "saved": ms}
                fb.files[f"site-measurements/{V}/{9999999999990 + ms:013d}-{k}.json"] = json.dumps(doc).encode()
            self.assertEqual(set(sm.load(V)["entries"]), {"w1", "a", "b"})

    def test_old_revisions_pruned(self):
        with FakeBlob() as fb:
            for i in range(sm.KEEP + 7):
                sm.save(V, {f"w{i}": e(100 + i, 1000 + i)})
            self.assertEqual(len(fb.files), sm.KEEP)
            self.assertEqual(len(sm.load(V)["entries"]), sm.KEEP + 7)  # every revision carries the whole doc


class Http(unittest.TestCase):
    def test_get_post_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            root, sm.ROOT = sm.ROOT, Path(d)
            token, photogen_blob.token = photogen_blob.token, lambda: None
            srv = ThreadingHTTPServer(("127.0.0.1", 0), sm.Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            url = f"http://127.0.0.1:{srv.server_address[1]}/api/measurements?version={V}"
            try:
                self.assertEqual(json.load(urllib.request.urlopen(url, timeout=10))["entries"], {})
                req = urllib.request.Request(url, json.dumps({"entries": {"w1": e(312, 5, "tape")}}).encode(),
                                             {"Content-Type": "application/json"})
                self.assertEqual(json.load(urllib.request.urlopen(req, timeout=10))["entries"]["w1"]["note"], "tape")
                self.assertEqual(json.load(urllib.request.urlopen(url, timeout=10))["entries"]["w1"]["value"], 312)
                with self.assertRaises(urllib.error.HTTPError) as c:
                    urllib.request.urlopen(url.replace(V, "kareems-changes"), timeout=10)
                self.assertEqual(c.exception.code, 400)
                self.assertTrue(list(Path(d, "site-measurements", V).glob("*.json")))
            finally:
                srv.shutdown()
                sm.ROOT, photogen_blob.token = root, token


if __name__ == "__main__":
    unittest.main()
