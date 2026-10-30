"""Issue #316 selected mobile Batch generation regression tests."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_web_takes import FakeUtterance, TOKEN
from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


class WebBatchGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "accepted"
        self.fakes = []
        def factory(caption):
            fake = FakeUtterance(caption, self.output)
            self.fakes.append(fake)
            return fake
        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.terms = patch("voiceger_editor.web_takes.require_current_acceptance")
        self.auth.start()
        self.terms.start()
        self.service = WebSessionOperations(caption_factory=factory)
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.root = "/api/web/sessions/" + self.sid

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.terms.stop()
        self.auth.stop()
        self.temp.cleanup()

    def batch(self):
        result = self.client.get(self.root + "/batch", headers=self.read)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def mutate(self, method, path, payload=None, revision=None, headers=None):
        if revision is None:
            revision = self.batch()["revision"]
        return self.client.request(
            method, self.root + "/batch" + path +
            "?expected_revision=" + str(revision),
            headers=self.write if headers is None else headers, json=payload,
        )

    def start(self):
        return self.mutate("POST", "/generate")

    def finish(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        op = response.json()
        if op["status"] == "no-op":
            return op
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            op = self.client.get(self.root + "/operations/" + op["id"],
                                 headers=self.read).json()
            if op["status"] not in ("running", "cancelling"):
                return op
            time.sleep(.01)
        self.fail("Timed out")

    def add(self, text):
        r = self.mutate("POST", "/items", {"text": text})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["items"]

    def test_empty_and_inclusion_order_and_effective_take_counts(self):
        self.assertEqual(self.finish(self.start())["reason"], "empty_selection")
        rows = self.add("first\nsecond\nthird")
        self.assertEqual(self.mutate("PATCH", "/items/" + rows[1]["id"] + "/included",
                                     {"included": False}).status_code, 200)
        self.assertEqual(self.mutate("PATCH", "/items/" + rows[2]["id"] + "/take-count",
                                     {"count": 2}).status_code, 200)
        self.assertEqual(self.mutate("PATCH", "/items/" + rows[2]["id"] + "/position",
                                     {"index": 0}).status_code, 200)
        result = self.finish(self.start())
        self.assertEqual((result["status"], result["total"], result["completed"]),
                         ("succeeded", 6, 6))
        self.assertEqual([f.syntheses for f in self.fakes], [4, 0, 2])
        self.assertTrue(self.fakes[0].is_prepared)
        self.assertFalse(self.fakes[1].is_prepared)
        data = self.batch()
        self.assertEqual([r["generation_outcome"] for r in data["items"]],
                         ["completed", "completed", None])
        self.assertIsNone(data["active_operation"])
        self.assertEqual(self.finish(self.start())["total"], 6)

    def test_multiple_accepted_preserved_on_regeneration_and_no_op(self):
        rows = self.add("one")
        self.assertEqual(self.finish(self.start())["status"], "succeeded")
        item_path = self.root + "/batch/items/" + rows[0]["id"]
        for number in (1, 2):
            rev = self.batch()["revision"]
            response = self.client.post(
                item_path + "/takes/" + str(number) + "/accept?expected_revision=" +
                str(rev), headers=self.write,
            )
            self.assertEqual(self.finish(response)["status"], "succeeded")
        accepted_files = {p.name: p.read_bytes() for p in self.output.iterdir()}
        count = self.fakes[0].syntheses
        self.assertEqual(self.finish(self.start())["status"], "succeeded")
        self.assertEqual(self.fakes[0].syntheses, count + 2)
        self.assertEqual(self.batch()["items"][0]["accepted_take_numbers"], [1, 2])
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.output.iterdir()},
            accepted_files,
        )
        for number in (3, 4):
            rev = self.batch()["revision"]
            response = self.client.post(
                item_path + "/takes/" + str(number) + "/accept?expected_revision=" +
                str(rev), headers=self.write,
            )
            self.assertEqual(self.finish(response)["status"], "succeeded")
        self.assertEqual(self.finish(self.start())["reason"], "all_accepted")
        self.assertEqual(self.fakes[0].syntheses, count + 2)
        rejected = self.mutate("PATCH", "/items/" + rows[0]["id"] +
                               "/take-count", {"count": 2})
        # Shrink across accepted Take 3/4 is blocked at planning time.
        self.assertEqual(rejected.status_code, 200)
        guarded = self.start()
        self.assertEqual(guarded.status_code, 409)
        self.assertEqual(guarded.json()["detail"]["code"], "accepted_take_protected")

    def test_stale_revision_auth_and_single_worker_cancel(self):
        rows = self.add("slow\nnext")
        old_rev = self.batch()["revision"] - 1
        self.assertEqual(self.mutate("POST", "/generate", revision=old_rev).status_code, 409)
        self.assertEqual(self.client.post(
            self.root + "/batch/generate?expected_revision=" +
            str(self.batch()["revision"])).status_code, 401)
        self.assertEqual(self.mutate(
            "POST", "/generate", headers=self.read).status_code, 403)
        begin, release = threading.Event(), threading.Event()
        self.fakes[0].begin, self.fakes[0].release = begin, release
        response = self.start()
        self.assertTrue(begin.wait(3))
        op = response.json()
        active = self.batch()["active_operation"]
        self.assertEqual(active["id"], op["id"])
        self.assertEqual(active["kind"], "batch-generate")
        self.assertEqual(active["detail"]["caption_total"], 2)
        self.assertEqual(self.start().status_code, 409)
        self.assertEqual(self.mutate("POST", "/items", {"text": "no"}).status_code, 409)
        cancelled = self.client.post(
            self.root + "/operations/" + op["id"] + "/cancel", headers=self.write,
        )
        self.assertEqual(cancelled.status_code, 200)
        release.set()
        final = self.finish(response)
        self.assertEqual(final["status"], "cancelled")
        self.assertGreaterEqual(final["completed"], 1)
        self.assertEqual(self.fakes[1].syntheses, 0)
        self.assertIsNone(self.batch()["active_operation"])

    def test_failure_preserves_first_item_and_reports_failing_item(self):
        rows = self.add("works\nfails")
        def boom():
            raise RuntimeError("Private Mac path / secret")
        self.fakes[1]._synthesize = boom
        result = self.finish(self.start())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["completed"], 4)
        self.assertNotIn("Private", result["error"])
        states = self.batch()["items"]
        self.assertEqual(states[0]["candidate_count"], 4)
        self.assertEqual(states[0]["generation_outcome"], "completed")
        self.assertEqual(states[1]["generation_outcome"], "failed")

    def test_dom_and_mobile_action_layout(self):
        from voiceger_editor.web import ASSETS
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="generate-batch"', html)
        self.assertIn(">一括生成</button>", html)
        self.assertIn('id="batch-progress-panel"', html)
        self.assertIn('id="cancel-batch"', html)
        self.assertIn("function followBatchOperation", js)
        self.assertIn("function resumeBatchOperation", js)
        self.assertIn(".batch-actions", css)


if __name__ == "__main__":
    unittest.main()
