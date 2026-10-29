"""Issue #308: protected pure-Japanese editing without a Voiceger runtime."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_web_takes import FakeUtterance, TOKEN
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.query_editing import japanese_pronunciation
from voiceger_editor.voicevox_api_models import VoicegerSegment
from voiceger_editor.voicevox_query import build_audio_query
from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


class JapaneseUtterance(FakeUtterance):
    def __init__(self, caption, output):
        super().__init__(caption, output)
        self._query = build_audio_query(pronunciation=parse_pronunciation("ア'メ。"))
        self.preview_notations = []

    @property
    def query(self):
        if not self.is_prepared:
            raise RuntimeError("not prepared")
        return deepcopy(self._query)

    def prepare_from_caption(self):
        self.discard_takes()
        self._spoken_text = self.caption
        self.is_prepared = True

    def replace_query(self, query):
        self.discard_takes()
        self._query = deepcopy(query)

    def preview_synthesis(self, query):
        self.preview_notations.append(japanese_pronunciation(query))
        return super().preview_synthesis(query)


class JapaneseWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output = Path(self.tmp.name) / "output"
        self.fake = None

        def factory(caption):
            self.fake = JapaneseUtterance(caption, self.output)
            return self.fake

        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.terms = patch("voiceger_editor.web_takes.require_current_acceptance")
        self.auth.start()
        self.terms.start()
        self.service = WebSessionOperations(caption_factory=factory)
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        response = self.client.post("/api/web/sessions", headers=self.write)
        self.assertEqual(response.status_code, 201)
        self.root = "/api/web/sessions/" + response.json()["id"]
        response = self.client.post(self.root + "/batch/items?expected_revision=0",
                                    headers=self.write, json={"text": "雨"})
        self.assertEqual(response.status_code, 200, response.text)
        self.item_id = response.json()["items"][0]["id"]
        self.path = self.root + "/batch/items/" + self.item_id
        self.finish(self.action("POST", "/audio/prepare", {"rebuild": False}))

    def tearDown(self):
        self.client.close()
        self.service.shutdown()
        self.terms.stop()
        self.auth.stop()
        self.tmp.cleanup()

    def batch(self):
        response = self.client.get(self.root + "/batch", headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def action(self, method, suffix, payload=None, *, revision=None, headers=None):
        if revision is None:
            revision = self.batch()["revision"]
        return self.client.request(
            method, self.path + suffix + "?expected_revision=" + str(revision),
            json=payload, headers=self.write if headers is None else headers,
        )

    def finish(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        opid = response.json()["id"]
        for _ in range(200):
            response = self.client.get(self.root + "/operations/" + opid, headers=self.read)
            self.assertEqual(response.status_code, 200)
            op = response.json()
            if op["status"] not in ("running", "cancelling"):
                return op
            time.sleep(0.005)
        self.fail("worker timed out")

    def test_real_query_snapshot_and_empty_or_mixed_unavailability(self):
        self.assertEqual(self.batch()["items"][0]["pronunciation"], "ア'メ。")
        self.fake._query.voicegerSegments = [
            VoicegerSegment(language="ja", text="雨", accentPhraseStart=0,
                            accentPhraseCount=1)
        ]
        self.assertIsNone(self.batch()["items"][0]["pronunciation"])
        self.assertEqual(self.action("PATCH", "/pronunciation", {"notation": "アメ'"}).status_code,
                         422)
        self.assertEqual(self.action(
            "POST", "/pronunciation/preview", {"notation": "アメ'"}).status_code, 422)

    def test_draft_preview_never_commits_or_clears_takes(self):
        self.finish(self.action("POST", "/takes/generate"))
        before = self.batch()
        op = self.finish(self.action("POST", "/pronunciation/preview",
                                     {"notation": "アメ'！"}))
        self.assertEqual(op["status"], "succeeded")
        self.assertEqual(self.fake.preview_notations, ["アメ'！"])
        after = self.batch()
        self.assertEqual(after, before)
        handle = op["result"]["preview_id"]
        self.assertEqual(self.client.get(self.path + "/audio/preview/" + handle).status_code,
                         401)
        self.assertTrue(self.client.get(
            self.path + "/audio/preview/" + handle, headers=self.read
        ).content.startswith(b"RIFF"))
        self.assertFalse(self.output.exists())

    def test_apply_noop_retains_accepted_candidates_and_files(self):
        self.finish(self.action("POST", "/takes/generate"))
        self.finish(self.action("POST", "/takes/1/accept"))
        files = [(p.name, p.read_bytes()) for p in self.output.iterdir()]
        before = self.batch()
        response = self.action("PATCH", "/pronunciation", {"notation": "ア'メ。"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["changed"])
        self.assertEqual(self.batch(), before)
        response = self.action("PATCH", "/pronunciation", {"notation": "ア'メ."})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["changed"])
        self.assertEqual(self.batch(), before)
        self.assertEqual([(p.name, p.read_bytes()) for p in self.output.iterdir()], files)

    def test_apply_real_change_invalidates_candidates_not_saved_outputs(self):
        self.finish(self.action("POST", "/takes/generate"))
        self.finish(self.action("POST", "/takes/1/accept"))
        # Preserve accepted WAV/TXT and a representative LAB sidecar byte-for-byte.
        lab = self.output / "accepted-voice.lab"
        lab.write_bytes(b"0 600000 a\\n600000 1200000 i\\n")
        files = [(p.name, p.read_bytes()) for p in self.output.iterdir()]
        previous = self.batch()
        change = self.action("PATCH", "/pronunciation", {"notation": "[シ]コク[メ]タン！"})
        self.assertEqual(change.status_code, 200, change.text)
        self.assertTrue(change.json()["changed"])
        item = self.batch()["items"][0]
        self.assertEqual(item["pronunciation"], "[シ]コク[メ]タン！")
        self.assertEqual(item["candidate_count"], 0)
        self.assertEqual(item["accepted_take_numbers"], [])
        self.assertEqual(item["generation_outcome"], None)
        self.assertEqual(self.batch()["revision"], previous["revision"] + 1)
        self.assertEqual([(p.name, p.read_bytes()) for p in self.output.iterdir()], files)
        self.finish(self.action("POST", "/takes/generate"))
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 4)

    def test_invalid_drafts_are_atomic(self):
        self.finish(self.action("POST", "/takes/generate"))
        original = self.batch()
        for invalid in ("", "アメ", "ア'/メ", "ア'メ ", "ア'メ/アメ'",
                        "キ'ョ", "ア'[メ]", "ア[メ'", "[シ]コク[メ'", "\nア'メ"):
            with self.subTest(invalid=invalid):
                response = self.action("PATCH", "/pronunciation", {"notation": invalid})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.batch(), original)
                response = self.action("POST", "/pronunciation/preview",
                                       {"notation": invalid})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.batch(), original)

    def test_cancelled_draft_preview_does_not_publish_audio(self):
        from threading import Event

        started, release = Event(), Event()
        original_preview = self.fake.preview_synthesis
        before = self.batch()

        def blocked(query):
            started.set()
            if not release.wait(4):
                raise RuntimeError("test preview release timed out")
            return original_preview(query)

        with patch.object(self.fake, "preview_synthesis", side_effect=blocked):
            response = self.action("POST", "/pronunciation/preview",
                                   {"notation": "アメ'！"})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(started.wait(3), "Draft Preview worker did not start")
            op_id = response.json()["id"]
            cancelled = self.client.post(
                self.root + "/operations/" + op_id + "/cancel", headers=self.write,
            )
            self.assertEqual(cancelled.status_code, 200)
            release.set()
            result = self.finish(response)

        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["result"])
        self.assertIsNone(self.service._sessions[self.root.rsplit("/", 1)[-1]].preview_audio)
        self.assertEqual(self.batch(), before)
        self.assertFalse(self.output.exists())

    def test_draft_preview_blocks_session_close_and_expiry_then_disposes(self):
        from threading import Event

        started, release = Event(), Event()
        original_preview = self.fake.preview_synthesis

        def blocked(query):
            started.set()
            if not release.wait(4):
                raise RuntimeError("test preview release timed out")
            return original_preview(query)

        sid = self.root.rsplit("/", 1)[-1]
        with patch.object(self.fake, "preview_synthesis", side_effect=blocked):
            response = self.action("POST", "/pronunciation/preview",
                                   {"notation": "アメ'！"})
            self.assertEqual(response.status_code, 202)
            self.assertTrue(started.wait(3))
            try:
                self.assertEqual(self.client.delete(
                    self.root, headers=self.write,
                ).status_code, 409)
                # Expiry never disposes the active worker's query mid-Preview.
                self.service._idle_seconds = 1
                with self.service._lock:
                    self.service._sessions[sid].touched -= 100
                self.assertEqual(self.batch()["items"][0]["pronunciation"], "ア'メ。")
            finally:
                release.set()
            result = self.finish(response)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.client.delete(self.root, headers=self.write).status_code, 204)
        self.assertEqual(self.client.get(self.root + "/batch", headers=self.read).status_code, 404)
        handle = result["result"]["preview_id"]
        self.assertEqual(self.client.get(
            self.path + "/audio/preview/" + handle, headers=self.read,
        ).status_code, 404)

    def test_revision_auth_origin_and_conflict(self):
        before = self.batch()
        self.assertEqual(self.client.patch(self.path + "/pronunciation?expected_revision=" +
                         str(before["revision"]), json={"notation": "アメ'"}).status_code, 401)
        self.assertEqual(self.action("PATCH", "/pronunciation", {"notation": "アメ'"},
                                     headers=self.read).status_code, 403)
        self.assertEqual(self.action("PATCH", "/pronunciation", {"notation": "アメ'"},
                                     revision=before["revision"] - 1).status_code, 409)
        self.assertEqual(self.batch(), before)
        # A valid caption-only mutation advances revision without touching query.
        response = self.action("PATCH", "/caption", {"caption": "字幕のみ"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.action("POST", "/pronunciation/preview",
                                     {"notation": "アメ'"}, revision=before["revision"]).status_code, 409)
        self.assertEqual(self.batch()["items"][0]["pronunciation"], "ア'メ。")

    def test_worker_busy_rejects_commit_without_changing_query(self):
        from threading import Event
        start, release = Event(), Event()
        self.fake.begin = start
        self.fake.release = release
        original = self.batch()
        response = self.action("POST", "/takes/generate")
        self.assertTrue(start.wait(3))
        try:
            self.assertEqual(self.action("PATCH", "/pronunciation",
                                         {"notation": "アメ'"}).status_code, 409)
            self.assertEqual(self.action("POST", "/pronunciation/preview",
                                         {"notation": "アメ'"}).status_code, 409)
            self.assertEqual(self.batch()["items"][0]["pronunciation"], "ア'メ。")
        finally:
            release.set()
        self.assertEqual(self.finish(response)["status"], "succeeded")
        self.assertEqual(original["items"][0]["pronunciation"], "ア'メ。")


if __name__ == "__main__":
    unittest.main()
