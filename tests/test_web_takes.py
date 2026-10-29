"""Issue #304: protected Web Take workflows without real Voiceger models."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from voiceger_editor.takes import TakeBatch
from voiceger_editor.web import create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


TOKEN = "test-web-audio-token-with-thirty-two-chars"


class FakeUtterance:
    def __init__(self, caption: str, output: Path):
        self.caption = caption
        self.is_prepared = False
        self._batch = None
        self._output = output
        self.syntheses = 0
        self.previews = 0
        self.begin = None
        self.release = None

    @property
    def synthesis_source_text(self):
        return "読み上げ:" + self.caption

    @property
    def candidates(self):
        return self._batch.candidates if self._batch else ()

    @property
    def active_candidate_count(self):
        return len(self.candidates)

    @property
    def has_active_batch(self):
        return self._batch is not None

    @property
    def query(self):
        if not self.is_prepared:
            raise RuntimeError("not prepared")
        return {"test": "query"}

    def replace_caption(self, caption):
        self.caption = caption

    def prepare_from_caption(self):
        self.discard_takes()
        self.is_prepared = True

    def preview_synthesis(self, query):
        self.previews += 1
        return {"audio": np.zeros(320, dtype=np.float32), "sampling_rate": 16000}

    def _synthesize(self):
        self.syntheses += 1
        if self.begin is not None:
            self.begin.set()
        if self.release is not None:
            self.release.wait(5)
        return {"audio": np.zeros(320, dtype=np.float32), "sampling_rate": 16000}

    def generate_takes(self, *, take_count):
        self._batch = TakeBatch(
            take_count=take_count, synthesize_one=self._synthesize,
            source_text=self.caption, style_name="Fake",
        )
        return self._batch.generate_all()

    def regenerate_take(self, number, *, protected_numbers=frozenset()):
        return self._batch.regenerate(number, protected_numbers=protected_numbers)

    def regenerate_all_takes(self, *, take_count, protected_numbers=frozenset()):
        return self._batch.regenerate_all(take_count, protected_numbers=protected_numbers)

    def accept_take(self, number):
        return self._batch.accept(
            number, caption=self.caption, output_dir=self._output,
            save_text=True,
        )

    def discard_takes(self):
        if self._batch is not None:
            self._batch.close()
        self._batch = None


class WebAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "accepted"
        self.fakes = []
        def factory(caption):
            fake = FakeUtterance(caption, self.output)
            self.fakes.append(fake)
            return fake

        self.auth_patch = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.terms_patch = patch(
            "voiceger_editor.web_takes.require_current_acceptance",
        )
        self.auth_patch.start()
        self.terms_patch.start()
        self.service = WebSessionOperations(caption_factory=factory)
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.root = f"/api/web/sessions/{self.sid}"
        self.add("こんにちはなのだ")
        self.item_id = self.batch()["items"][0]["id"]

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.terms_patch.stop()
        self.auth_patch.stop()
        self.temp.cleanup()

    def batch(self):
        response = self.client.get(self.root + "/batch", headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def add(self, caption):
        response = self.client.post(
            self.root + "/batch/items?expected_revision=" +
            str(self.batch()["revision"]),
            headers=self.write, json={"text": caption},
        )
        self.assertEqual(response.status_code, 200, response.text)

    @property
    def item_path(self):
        return self.root + "/batch/items/" + self.item_id

    def action(self, method, suffix, body=None, revision=None, headers=None):
        if revision is None:
            revision = self.batch()["revision"]
        return self.client.request(
            method, self.item_path + suffix + "?expected_revision=" + str(revision),
            headers=self.write if headers is None else headers, json=body,
        )

    def finish(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        value = response.json()
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            result = self.client.get(
                self.root + "/operations/" + value["id"], headers=self.read,
            )
            self.assertEqual(result.status_code, 200)
            body = result.json()
            if body["status"] not in ("running", "cancelling"):
                return body
            time.sleep(0.005)
        self.fail("Audio worker timed out")

    def prepare(self):
        result = self.finish(self.action(
            "POST", "/audio/prepare", {"rebuild": False},
        ))
        self.assertEqual(result["status"], "succeeded")

    def generate(self):
        self.prepare()
        result = self.finish(self.action("POST", "/takes/generate"))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["completed"], 4)

    def test_initial_generation_audio_auth_and_browser_preview(self):
        self.prepare()
        preview = self.finish(self.action("POST", "/audio/preview"))
        self.assertEqual(preview["status"], "succeeded")
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 0)
        handle = preview["result"]["preview_id"]
        url = self.item_path + "/audio/preview/" + handle
        self.assertEqual(self.client.get(url).status_code, 401)
        wav = self.client.get(url, headers=self.read)
        self.assertEqual(wav.status_code, 200)
        self.assertTrue(wav.content.startswith(b"RIFF"))
        self.assertEqual(wav.headers["content-type"], "audio/wav")
        self.assertFalse(self.output.exists())

        op = self.finish(self.action("POST", "/takes/generate"))
        self.assertEqual((op["completed"], op["total"]), (4, 4))
        item = self.batch()["items"][0]
        self.assertEqual([t["number"] for t in item["takes"]], [1, 2, 3, 4])
        self.assertEqual(item["spoken_text"], "読み上げ:こんにちはなのだ")
        take_url = self.item_path + "/takes/1/audio"
        self.assertEqual(self.client.get(take_url).status_code, 401)
        self.assertTrue(self.client.get(take_url, headers=self.read).content.startswith(b"RIFF"))
        self.assertEqual(self.client.get(self.item_path + "/takes/42/audio",
                                         headers=self.read).status_code, 404)
        self.assertEqual(self.client.get(
            self.item_path + "/audio/preview/wrong", headers=self.read,
        ).status_code, 404)

    def test_multiple_acceptance_and_caption_edit_preserves_output(self):
        self.generate()
        first = self.finish(self.action("POST", "/takes/1/accept"))
        second = self.finish(self.action("POST", "/takes/2/accept"))
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(second["status"], "succeeded")
        saved = sorted(self.output.iterdir())
        self.assertEqual(len(saved), 4)
        self.assertEqual(self.action("POST", "/takes/1/accept").status_code, 409)
        self.assertEqual(self.batch()["items"][0]["accepted_take_numbers"], [1, 2])
        changed = self.action("PATCH", "/caption", {"caption": "字幕だけ変更"})
        self.assertEqual(changed.status_code, 200)
        item = self.batch()["items"][0]
        self.assertEqual(item["accepted_take_numbers"], [1, 2])
        self.assertEqual(item["candidate_count"], 4)
        self.assertEqual(item["spoken_text"], "読み上げ:こんにちはなのだ")

        result = self.finish(self.action("POST", "/takes/regenerate"))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["completed"], 2)
        self.assertEqual(self.batch()["items"][0]["accepted_take_numbers"], [1, 2])
        self.assertEqual(sorted(self.output.iterdir()), saved)
        self.assertEqual(self.action("POST", "/takes/1/regenerate").status_code, 409)

    def test_rebuild_and_clear_do_not_delete_accepted_files(self):
        self.generate()
        self.finish(self.action("POST", "/takes/1/accept"))
        paths = list(self.output.iterdir())
        self.assertEqual(self.action("POST", "/audio/prepare",
                                     {"rebuild": False}).status_code, 409)
        cleared = self.action("DELETE", "/takes")
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["items"][0]["candidate_count"], 0)
        self.assertEqual(cleared.json()["items"][0]["accepted_take_numbers"], [])
        self.assertTrue(all(p.exists() for p in paths))
        self.finish(self.action("POST", "/takes/generate"))
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 4)
        self.assertEqual(self.finish(self.action(
            "POST", "/audio/prepare", {"rebuild": True},
        ))["status"], "succeeded")
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 0)
        self.assertTrue(all(p.exists() for p in paths))

    def test_shrink_crossing_accepted_take_is_rejected(self):
        self.generate()
        self.finish(self.action("POST", "/takes/4/accept"))
        count = self.action("PATCH", "/take-count", {"count": 2})
        self.assertEqual(count.status_code, 200)
        self.assertEqual(self.action("POST", "/takes/regenerate").status_code, 409)
        self.assertEqual(self.batch()["items"][0]["accepted_take_numbers"], [4])
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 4)

    def test_stale_revision_origin_and_cross_session(self):
        self.prepare()
        before = self.batch()
        self.assertEqual(self.action("POST", "/takes/generate", revision=0).status_code, 409)
        self.assertEqual(self.action("POST", "/takes/generate",
            headers=self.read).status_code, 403)
        evil = {**self.write, "Origin": "https://untrusted.example"}
        self.assertEqual(self.action("POST", "/takes/generate",
            headers=evil).status_code, 403)
        self.assertEqual(self.action("POST", "/takes/900/accept").status_code, 422)
        self.assertEqual(self.action("POST", "/audio/prepare",
            {"rebuild": False}).status_code, 409)
        self.assertEqual(self.batch(), before)
        other = self.client.post("/api/web/sessions", headers=self.write).json()["id"]
        self.assertEqual(self.client.get(
            f"/api/web/sessions/{other}/batch/items/{self.item_id}/takes/1/audio",
            headers=self.read,
        ).status_code, 404)

    def test_worker_conflict_cancel_retains_completed_candidates(self):
        self.prepare()
        started, release = threading.Event(), threading.Event()
        self.fakes[0].begin = started
        self.fakes[0].release = release
        response = self.action("POST", "/takes/generate")
        self.assertEqual(response.status_code, 202)
        try:
            self.assertTrue(started.wait(2))
            self.assertEqual(self.action("POST", "/takes/generate").status_code, 409)
            self.assertEqual(self.action("DELETE", "/takes").status_code, 409)
            cancel = self.client.post(
                self.root + "/operations/" + response.json()["id"] + "/cancel",
                headers=self.write,
            )
            self.assertEqual(cancel.status_code, 200)
            self.assertIn(cancel.json()["status"], ("cancelling", "cancelled"))
        finally:
            release.set()
        terminal = self.finish_terminal(response.json()["id"])
        self.assertEqual(terminal["status"], "cancelled")
        self.assertEqual(terminal["completed"], 1)
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 1)
        self.fakes[0].begin = None
        self.fakes[0].release = None
        self.assertEqual(self.finish(self.action(
            "POST", "/takes/regenerate",
        ))["status"], "succeeded")

    def finish_terminal(self, identifier):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            result = self.client.get(
                self.root + "/operations/" + identifier, headers=self.read,
            ).json()
            if result["status"] not in ("running", "cancelling"):
                return result
            time.sleep(0.005)
        self.fail("Worker did not terminate")

    def test_save_failure_does_not_mark_acceptance(self):
        self.generate()
        with patch.object(self.fakes[0], "accept_take", side_effect=OSError("/private/path")):
            done = self.finish(self.action("POST", "/takes/1/accept"))
        self.assertEqual(done["status"], "failed")
        self.assertNotIn("/private/path", str(done))
        self.assertEqual(self.batch()["items"][0]["accepted_take_numbers"], [])

    def test_session_close_disposes_candidates_not_accepted_output(self):
        self.generate()
        self.finish(self.action("POST", "/takes/1/accept"))
        paths = list(self.output.iterdir())
        candidate = self.fakes[0].candidates[0].wav_path
        self.assertTrue(candidate.exists())
        closed = self.client.delete(self.root, headers=self.write)
        self.assertEqual(closed.status_code, 204)
        self.assertFalse(candidate.exists())
        self.assertTrue(all(path.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()
