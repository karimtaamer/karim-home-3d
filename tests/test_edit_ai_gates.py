"""Edit AI quality gates: Luna's prompt check before an edit, Sol's review after it (one fix round on a low score),
and the cost of the whole run. No model is called: the editor is scripted and OpenAI is a fake.

    python3 -m unittest tests/test_edit_ai_gates.py
"""
import json, os, shutil, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["EDIT_AI_GIT_SYNC"] = "0"
import edit_ai  # noqa: E402

V = "kareems-changes"
F = f"furnish-{V}.js"  # the version's own furniture file (26 Oct 2026)
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
USAGE = {"prompt_tokens": 1000, "completion_tokens": 100}


class Gates(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="edit-ai-gates-"))
        (self.root / F).write_text("const sofa = 1;\n")
        names = ("ROOT", "BLOB", "git_sync", "post", "openai", "tool", "review", "lock_breaks")
        self.saved = {n: getattr(edit_ai, n) for n in names}
        self.key = os.environ.get("EDIT_AI_OPENAI_API_KEY")
        os.environ["EDIT_AI_OPENAI_API_KEY"] = "sk-test-" + "x" * 30
        edit_ai.ROOT, edit_ai.BLOB = self.root, False
        edit_ai._cache.clear()
        edit_ai.git_sync = lambda v, contents, summary: "test"
        edit_ai.review = lambda ws, message, reply: None  # the rule checks have their own tests
        edit_ai.lock_breaks = lambda ws, message, record=False: None
        self.sent, self.scores, self.turns = [], [], []
        edit_ai.post = self.fake_post
        edit_ai.openai = self.fake_editor
        edit_ai.tool = lambda ws, name, args: ws.write("furnish.js", args["text"].encode()) or "ok"

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(edit_ai, n, v)
        if self.key is None:
            os.environ.pop("EDIT_AI_OPENAI_API_KEY", None)
        else:
            os.environ["EDIT_AI_OPENAI_API_KEY"] = self.key
        edit_ai._cache.clear()
        shutil.rmtree(self.root, ignore_errors=True)

    def fake_post(self, url, body, headers=None, who="OpenAI"):
        """OpenAI: chat/completions for Luna, /v1/responses for Sol; answers from self.scores in turn."""
        self.sent.append((url, body))
        answer = json.dumps(self.scores.pop(0))
        if url == edit_ai.RESPONSES_URL:
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": answer}]}],
                    "usage": {"input_tokens": 1000, "output_tokens": 100}}
        return {"choices": [{"message": {"role": "assistant", "content": answer}}], "usage": USAGE}

    def fake_editor(self, messages, first=False, model=None):
        """Edits furnish.js on its first turn of each round, then replies."""
        self.turns.append(messages[-1]["content"] if isinstance(messages[-1]["content"], str) else "(request)")
        if messages[-1]["role"] == "tool":
            return {"choices": [{"message": {"role": "assistant", "content": "Made the sofa 2."}}], "usage": USAGE}
        text = "const sofa = 3;\n" if "reviewer" in self.turns[-1] else "const sofa = 2;\n"
        call = {"id": f"c{len(self.turns)}", "type": "function", "function": {"name": "edit", "arguments": json.dumps({"text": text})}}
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}], "usage": USAGE}

    def chat(self, **extra):
        phases = []
        res = edit_ai.chat({"version": V, "message": "make the sofa 2", "image": PNG, "context": {}, "model": "gpt-6-luna", **extra},
                           phases.append)
        return res, phases

    # --- the prompt check ---
    def test_precheck_grades_and_prices(self):
        self.scores = [{"score": 2, "tip": "Say where to move it."}]
        out = edit_ai.precheck({"message": "move this", "context": {"hits": [{"furniture": True, "material": "walnut"}]}})
        self.assertEqual((out["score"], out["tip"], out["model"]), (2, "Say where to move it.", "gpt-6-luna"))
        self.assertAlmostEqual(out["usd"], (1000 * 0.1 + 100 * 0.5) / 1e6)
        url, body = self.sent[0]
        self.assertEqual(url, edit_ai.OPENAI_URL)
        self.assertIn("1 circle on a furniture piece (walnut)", body["messages"][1]["content"])
        self.assertEqual(body["max_completion_tokens"], 80)

    def test_precheck_never_blocks(self):
        self.scores = ["not json"]
        self.assertEqual(edit_ai.precheck({"message": "move this"}), {"skipped": True})
        os.environ["EDIT_AI_GATES"] = "0"
        try:
            self.assertEqual(edit_ai.precheck({"message": "move this"}), {"skipped": True})
        finally:
            os.environ.pop("EDIT_AI_GATES")

    # --- the review ---
    def test_good_review_saves_without_a_fix(self):
        self.scores = [{"score": 9, "problems": [], "summary": "Sofa is 2."}]
        res, phases = self.chat()
        self.assertEqual(res["review"]["score"], 9)
        self.assertFalse(res["review"]["improved"])
        self.assertEqual(res["changed"], ["furnish.js"])  # chat() reports the generic names
        self.assertEqual(phases, ["Checking the edit", "Saving your edit"])
        self.assertIsNone(res["costs"]["fix"])
        self.assertAlmostEqual(res["costs"]["total"], res["costs"]["edit"] + res["costs"]["review"])
        url, body = self.sent[0]
        self.assertEqual(url, edit_ai.RESPONSES_URL)  # Sol is on /v1/responses
        self.assertIn("-const sofa = 1;", json.dumps(body["input"]))

    def test_low_review_runs_one_fix_round(self):
        self.scores = [{"score": 4, "problems": ["Make it 3, not 2."], "summary": "Wrong size."},
                       {"score": 9, "problems": [], "summary": "Right now."}]
        res, phases = self.chat()
        self.assertEqual((res["review"]["score"], res["review"]["final"], res["review"]["improved"]), (4, 9, True))
        self.assertIn("We found improvements, please wait a moment", phases)
        self.assertTrue(any("Make it 3, not 2." in t for t in self.turns), "the editor gets Sol's notes")
        live = edit_ai.patches(V)["files"][F]
        self.assertIn("sofa = 3", live.get("content") or (self.root / live["url"].lstrip("/")).read_text())
        c = res["costs"]
        self.assertGreater(c["fix"], 0)
        self.assertAlmostEqual(c["total"], c["edit"] + c["fix"] + c["review"], places=4)
        self.assertEqual(len(self.sent), 2, "one review, one re-score: no second fix round")

    def test_a_fix_round_that_gives_up_keeps_the_first_edit(self):
        # 27 Oct 2026: mosaic asked, terrazzo given (review 6); the fix round discarded and the user got nothing.
        self.scores = [{"score": 5, "problems": ["Use mosaic, not terrazzo."], "summary": "Close."}]
        editor = self.fake_editor

        def gives_up(messages, first=False, model=None):
            if "reviewer" in str(messages[-1].get("content")):
                call = {"id": "dz", "type": "function", "function": {"name": "discard", "arguments": "{}"}}
                return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 1}}
            if messages[-1].get("tool_call_id") == "dz":
                return {"choices": [{"message": {"role": "assistant", "content": "Couldn't do mosaic."}}], "usage": {"prompt_tokens": 10, "completion_tokens": 1}}
            return editor(messages, first, model)
        edit_ai.openai = gives_up
        write = edit_ai.tool
        edit_ai.tool = lambda ws, name, args: (ws.discard() or "discarded") if name == "discard" else write(ws, name, args)
        res, _ = self.chat()
        self.assertEqual(res["changed"], ["furnish.js"], "the first edit is kept")
        self.assertIn("Made the sofa 2.", res["reply"])

    def test_no_review_when_gates_are_off(self):
        os.environ["EDIT_AI_GATES"] = "0"
        try:
            res, phases = self.chat()
        finally:
            os.environ.pop("EDIT_AI_GATES")
        self.assertIsNone(res["review"])
        self.assertEqual(self.sent, [])
        self.assertEqual(res["costs"]["total"], res["costs"]["edit"])

    def test_review_failure_lets_the_edit_through(self):
        self.scores = ["{broken"]
        res, _ = self.chat()
        self.assertIsNone(res["review"])
        self.assertEqual(res["changed"], ["furnish.js"])  # chat() reports the generic names

    # --- "No, try again" on the done toast ---
    def test_retry_runs_on_the_strong_model(self):
        self.scores = [{"score": 9, "problems": [], "summary": "Right."}]
        models, first_ask = [], []
        editor = self.fake_editor

        def spy(messages, first=False, model=None):
            models.append(model)
            first_ask.append(messages[-1]["content"][0]["text"] if isinstance(messages[-1]["content"], list) else None)
            return editor(messages, first, model)
        edit_ai.openai = spy
        res, _ = self.chat(retry=True)
        self.assertEqual((res["route"], res["model"]), ("retry", edit_ai.live_model(edit_ai.COMPLEX_MODEL)))
        self.assertEqual(set(models), {edit_ai.live_model(edit_ai.COMPLEX_MODEL)}, "the retry never runs on the pick it was sent with")
        self.assertIn("Second try", first_ask[0])
        self.assertIn("make the sofa 2", first_ask[0])
        self.assertEqual(res["retryModel"], edit_ai.live_model(edit_ai.COMPLEX_MODEL))


class Stream(unittest.TestCase):
    def test_phases_then_result_as_ndjson(self):
        import threading, urllib.request
        from http.server import ThreadingHTTPServer
        saved = edit_ai.chat

        def fake_chat(req, emit=None):
            emit("Checking the edit")
            emit("We found improvements, please wait a moment")
            return {"reply": "Done.", "changed": ["furnish.js"], "costs": {"total": 0.01}}
        edit_ai.chat = fake_chat
        srv = ThreadingHTTPServer(("127.0.0.1", 0), edit_ai.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/api/edit-ai/chat", method="POST",
                                         data=json.dumps({"stream": True}).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                self.assertIn("ndjson", r.headers["Content-Type"])
                lines = [json.loads(l) for l in r.read().decode().splitlines() if l.strip()]
        finally:
            srv.shutdown()
            edit_ai.chat = saved
        self.assertEqual([l.get("phase") for l in lines[:2]], ["Checking the edit", "We found improvements, please wait a moment"])
        self.assertEqual(lines[-1]["done"]["costs"]["total"], 0.01)


if __name__ == "__main__":
    unittest.main()
