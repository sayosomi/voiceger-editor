"""Issue #304: protected Web Take workflows without real Voiceger models."""

from __future__ import annotations

import os
import shutil
import subprocess
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
        self._spoken_text = None
        self._output = output
        self.syntheses = 0
        self.previews = 0
        self.begin = None
        self.release = None

    @property
    def synthesis_source_text(self):
        return self._spoken_text

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
        self._spoken_text = "読み上げ:" + self.caption
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
            blocked = self.action("POST", "/takes/generate")
            self.assertEqual(blocked.status_code, 409)
            self.assertEqual(blocked.json()["detail"], {"code": "worker_busy"})
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
        self.assertIsNone(terminal["error"])
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

    def test_terms_rejection_is_typed_and_preserves_state(self):
        from voiceger_editor.terms_acceptance import VoicegerTermsAcceptanceError

        before = self.batch()
        for reason in ("not accepted", "previous notice version"):
            with self.subTest(reason=reason):
                with patch(
                    "voiceger_editor.web_takes.require_current_acceptance",
                    side_effect=VoicegerTermsAcceptanceError(reason),
                ):
                    rejected = self.action(
                        "POST", "/audio/prepare", {"rebuild": False},
                    )
                self.assertEqual(rejected.status_code, 409)
                self.assertEqual(rejected.json()["detail"]["code"], "terms_required")
                self.assertEqual(self.batch(), before)
                self.assertEqual(self.service._active, None)
        self.prepare()
        before = self.batch()
        with patch(
            "voiceger_editor.web_takes.require_current_acceptance",
            side_effect=VoicegerTermsAcceptanceError("stale"),
        ):
            for route in ("/audio/preview", "/takes/generate"):
                with self.subTest(route=route):
                    response = self.action("POST", route)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.json()["detail"]["code"], "terms_required")
        self.assertEqual(self.batch(), before)
        self.assertEqual(self.fakes[0].syntheses, 0)
        self.assertEqual(self.fakes[0].previews, 0)

    def test_conflicts_have_safe_actionable_codes(self):
        self.prepare()
        stale = self.action("POST", "/takes/generate", revision=0)
        self.assertEqual(stale.json()["detail"], {"code": "revision_conflict"})
        self.generate_after_preparation()
        self.finish(self.action("POST", "/takes/4/accept"))
        rejected = self.action("POST", "/takes/4/regenerate")
        self.assertEqual(rejected.json()["detail"], {"code": "accepted_take_protected"})
        rejected = self.action("POST", "/takes/4/accept")
        self.assertEqual(rejected.json()["detail"], {"code": "already_accepted"})
        self.assertEqual(self.action("PATCH", "/take-count", {"count": 2}).status_code, 200)
        rejected = self.action("POST", "/takes/regenerate")
        self.assertEqual(rejected.json()["detail"], {"code": "accepted_take_protected"})

    def generate_after_preparation(self):
        completed = self.finish(self.action("POST", "/takes/generate"))
        self.assertEqual(completed["status"], "succeeded")

    def test_single_regeneration_failure_retains_original_candidate(self):
        self.generate()
        fake = self.fakes[0]
        original = next(c for c in fake.candidates if c.number == 2)
        original_bytes = original.wav_path.read_bytes()
        with patch.object(fake._batch, "synthesize_one",
                          side_effect=OSError("/Users/private/model")):
            outcome = self.finish(self.action("POST", "/takes/2/regenerate"))
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(outcome["completed"], 0)
        self.assertNotIn("/Users/private", str(outcome))
        candidate = next(c for c in fake.candidates if c.number == 2)
        self.assertEqual(candidate.wav_path, original.wav_path)
        self.assertEqual(candidate.wav_path.read_bytes(), original_bytes)
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 4)

    def test_bulk_shrink_failure_preserves_old_and_accepted_candidates(self):
        self.generate()
        self.finish(self.action("POST", "/takes/1/accept"))
        fake = self.fakes[0]
        initial = {c.number: c.wav_path for c in fake.candidates}
        saved = tuple(self.output.iterdir())
        self.assertEqual(self.action("PATCH", "/take-count", {"count": 3}).status_code, 200)
        attempts = [0]

        def synthesize():
            attempts[0] += 1
            if attempts[0] == 2:
                raise OSError("/Users/private/bulk-failure")
            return {"audio": np.zeros(320, dtype=np.float32), "sampling_rate": 16000}

        with patch.object(fake._batch, "synthesize_one", side_effect=synthesize):
            done = self.finish(self.action("POST", "/takes/regenerate"))
        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["completed"], 1)
        paths = {c.number: c.wav_path for c in fake.candidates}
        self.assertEqual(set(paths), {1, 2, 3, 4})
        self.assertEqual(paths[1], initial[1])
        self.assertNotEqual(paths[2], initial[2])
        self.assertEqual(paths[3], initial[3])
        self.assertEqual(paths[4], initial[4])
        self.assertTrue(all(path.exists() for path in paths.values()))
        self.assertEqual(self.batch()["items"][0]["accepted_take_numbers"], [1])
        self.assertTrue(all(path.exists() for path in saved))


    def test_cancel_after_last_take_before_terminal_publish_is_consistent(self):
        """Control the exact race after run() returns, before terminal commit."""
        self.prepare()
        generated, resume_terminal = threading.Event(), threading.Event()
        original_runner = self.service._run_take_work

        def pause_after_run(session_id, operation, run, on_terminal=None):
            def run_then_pause(op):
                result = run(op)
                generated.set()
                if not resume_terminal.wait(5):
                    raise RuntimeError("Timed out waiting to publish terminal state")
                return result

            return original_runner(
                session_id, operation, run_then_pause, on_terminal,
            )

        with patch.object(self.service, "_run_take_work", side_effect=pause_after_run):
            response = self.action("POST", "/takes/generate")
            self.assertEqual(response.status_code, 202, response.text)
            operation_id = response.json()["id"]
            try:
                self.assertTrue(generated.wait(2), "Last Take did not complete")
                before = self.batch()["items"][0]
                self.assertEqual(before["candidate_count"], 4)
                # The worker is between generation and terminal publication.
                self.assertIsNone(before["generation_outcome"])
                candidate_paths = tuple(c.wav_path for c in self.fakes[0].candidates)
                self.assertTrue(all(p.exists() for p in candidate_paths))
                cancelled = self.client.post(
                    self.root + "/operations/" + operation_id + "/cancel",
                    headers=self.write,
                )
                self.assertEqual(cancelled.status_code, 200)
                self.assertEqual(cancelled.json()["status"], "cancelling")
            finally:
                resume_terminal.set()
            terminal = self.finish_terminal(operation_id)

        self.assertEqual(terminal["status"], "cancelled")
        self.assertEqual((terminal["completed"], terminal["total"]), (4, 4))
        self.assertIsNone(terminal["error"])
        self.assertEqual(self.batch()["items"][0]["generation_outcome"], "cancelled")
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 4)
        self.assertTrue(all(p.exists() for p in candidate_paths))
        self.assertIsNone(self.service._active)

    def test_cancel_after_terminal_generation_does_not_relabel_success(self):
        self.prepare()
        response = self.action("POST", "/takes/generate")
        completed = self.finish(response)
        self.assertEqual(completed["status"], "succeeded")
        operation_id = response.json()["id"]
        late_cancel = self.client.post(
            self.root + "/operations/" + operation_id + "/cancel",
            headers=self.write,
        )
        self.assertEqual(late_cancel.status_code, 200)
        self.assertEqual(late_cancel.json()["status"], "succeeded")
        self.assertEqual(self.batch()["items"][0]["generation_outcome"], "completed")
        self.assertEqual(self.batch()["items"][0]["candidate_count"], 4)

    def test_cancel_during_synthesis_exception_is_failure_not_cancellation(self):
        self.prepare()
        started, release = threading.Event(), threading.Event()
        fake = self.fakes[0]

        def fail_after_cancellation():
            started.set()
            release.wait(5)
            raise OSError("/private/engine-error")

        with patch.object(fake, "_synthesize", side_effect=fail_after_cancellation):
            response = self.action("POST", "/takes/generate")
            self.assertEqual(response.status_code, 202)
            try:
                self.assertTrue(started.wait(2))
                cancel = self.client.post(
                    self.root + "/operations/" + response.json()["id"] + "/cancel",
                    headers=self.write,
                )
                self.assertEqual(cancel.status_code, 200)
                self.assertEqual(cancel.json()["status"], "cancelling")
            finally:
                release.set()
            done = self.finish_terminal(response.json()["id"])
        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["error"], "Audio operation failed on the Mac")
        self.assertNotIn("/private/engine-error", str(done))
        item = self.batch()["items"][0]
        self.assertEqual(item["generation_outcome"], "failed")
        self.assertEqual(item["candidate_count"], 0)
        self.assertIsNone(self.service._active)

    def test_shutdown_active_take_worker_waits_then_cleans_transients(self):
        self.generate()
        self.finish(self.action("POST", "/takes/1/accept"))
        fake = self.fakes[0]
        preserved = tuple(self.output.iterdir())
        old_candidates = tuple(c.wav_path for c in fake.candidates)
        started, release = threading.Event(), threading.Event()

        def slow_synthesis():
            started.set()
            release.wait(5)
            return {"audio": np.zeros(320, dtype=np.float32), "sampling_rate": 16000}

        with patch.object(fake._batch, "synthesize_one", side_effect=slow_synthesis):
            response = self.action("POST", "/takes/2/regenerate")
            self.assertEqual(response.status_code, 202)
            try:
                self.assertTrue(started.wait(2))
                self.service.shutdown()
                self.assertTrue(all(path.exists() for path in old_candidates))
                with self.service._lock:
                    self.assertIn(self.sid, self.service._sessions)
                    self.assertIsNotNone(self.service._active)
            finally:
                release.set()
            deadline = time.monotonic() + 7
            while time.monotonic() < deadline:
                with self.service._lock:
                    if self.service._active is None and not self.service._sessions:
                        break
                time.sleep(0.005)
            else:
                self.fail("Take shutdown cleanup did not finish")
        self.assertTrue(all(not path.exists() for path in old_candidates))
        self.assertTrue(all(path.exists() for path in preserved))


    def test_idle_expiry_cleans_actual_take_candidates_not_saved_outputs(self):
        self.generate()
        self.finish(self.action("POST", "/takes/1/accept"))
        candidate_paths = [c.wav_path for c in self.fakes[0].candidates]
        saved = tuple(self.output.iterdir())
        clock = [100.0]
        with self.service._lock:
            self.service._clock = lambda: clock[0]
            self.service._idle_seconds = 3
            self.service._sessions[self.sid].touched = clock[0]
        clock[0] += 4
        gone = self.client.get(self.root, headers=self.read)
        self.assertEqual(gone.status_code, 404)
        self.assertTrue(all(not p.exists() for p in candidate_paths))
        self.assertTrue(all(p.exists() for p in saved))


    def test_mobile_conflict_messages_execute_without_disclosing_details(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed; source contract remains covered")
        path = (
            Path(__file__).resolve().parents[1]
            / "voiceger_editor" / "web_assets" / "app.js"
        )
        script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("  async function request(");
const end = source.indexOf("  function batchPath()", start);
if (start < 0 || end < start) throw new Error("request() not found");
const makeRequest = new Function("fetch", "token", source.slice(start, end) + "; return request;");
const scenarios = [
  ["terms_required", "利用規約"],
  ["revision_conflict", "別の画面"],
  ["worker_busy", "別の処理"],
  ["accepted_take_protected", "採用済みTake"],
  ["already_accepted", "採用済み"],
  ["unknown_code", "現在実行できません"]
];
(async function () {
  for (const [code, expected] of scenarios) {
    const fn = makeRequest(
      async () => ({ok: false, status: 409,
        json: async () => ({detail: {code, secret: "/private/never-disclose"}})}),
      "test-token"
    );
    let error = null;
    try { await fn("POST", "/test"); } catch (caught) { error = caught; }
    if (!error || error.conflictCode !== code ||
        !error.message.includes(expected) ||
        error.message.includes("/private/")) {
      throw new Error("Incorrect browser error mapping: " + code);
    }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        completed = subprocess.run(
            [node, "-e", script, str(path)], capture_output=True,
            text=True, timeout=10, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_mobile_conflict_messages_are_allowlisted(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "voiceger_editor" / "web_assets" / "app.js"
        ).read_text(encoding="utf-8")
        for label in (
            "revision_conflict:", "terms_required:", "worker_busy:",
            "accepted_take_protected:", "already_accepted:",
        ):
            with self.subTest(label=label):
                self.assertIn(label, source)
        self.assertIn("problem.detail.code", source)
        self.assertIn('error.conflictCode === "revision_conflict"', source)
        self.assertNotIn('response.status === 409 ? "別の画面で変更されています', source)


    def test_mobile_compact_take_ui_and_auto_prepare_contract(self):
        html = self.client.get("/").text
        js = self.client.get("/assets/app.js").text
        css = self.client.get("/assets/app.css").text
        for element in (
            'id="caption-display"', 'id="open-caption-edit"',
            'id="edit-caption-form"', 'id="cancel-caption-edit"',
            'id="edit-take-count"', 'id="item-takes-form"',
            'id="prepare-retry"', 'id="open-take-menu"',
            'id="regenerate-unaccepted"', 'id="clear-takes"',
            'id="reprepare-audio"', 'id="take-list"',
        ):
            with self.subTest(element=element):
                self.assertIn(element, html)
        self.assertIn('function maybePrepareOnOpen(item)', js)
        self.assertIn('startAudio(item.id, "/audio/prepare", { rebuild: false }, true)', js)
        self.assertIn('if (!item || item.is_prepared || autoPrepareFailures.has(item.id)) return;', js)
        self.assertIn('autoPrepareFailures.add(itemId)', js)
        self.assertIn('autoPrepareFailures.delete(itemId)', js)
        self.assertNotIn('"発音準備済み"', js)
        self.assertNotIn('id="prepare-audio"', html)
        self.assertIn('className = "take-play"', js)
        self.assertIn('className = "take-accepted"', js)
        self.assertIn('className = "take-regenerate"', js)
        self.assertIn('.take-regenerate', css)

    def test_mobile_take_playback_controls_and_caption_shortcut_contract(self):
        html = self.client.get("/").text
        js = self.client.get("/assets/app.js").text
        css = self.client.get("/assets/app.css").text
        self.assertIn('id="new-captions"', html)
        self.assertIn('function shouldSubmitCaptions(event)', js)
        self.assertIn('$("new-captions").addEventListener("keydown"', js)
        self.assertIn('$("add-form").requestSubmit()', js)
        self.assertIn('event.isComposing', js)
        self.assertIn('event.keyCode !== 229', js)
        self.assertIn('function updatePlaybackUI()', js)
        self.assertIn('"timeupdate", updatePlaybackUI', js)
        self.assertIn('"ended", function ()', js)
        self.assertIn('togglePlayback("take"', js)
        self.assertIn('togglePlayback("preview"', js)
        self.assertIn('row.classList.toggle("is-playing"', js)
        self.assertIn('row.classList.toggle("is-paused"', js)
        self.assertIn('className = "take-progress"', js)
        self.assertIn('document.createElementNS(namespace, "svg")', js)
        self.assertIn('function makeRefreshIcon()', js)
        self.assertIn('regenerate.append(makeRefreshIcon())', js)
        self.assertIn('regenerate.setAttribute("aria-label", "Take " + take.number + "を再生成")', js)
        self.assertNotIn('className = "take-more"', js)
        self.assertIn('.take-card.is-playing', css)
        self.assertIn('.take-card.is-paused', css)

    def test_mobile_cmd_enter_respects_ime_and_key_repeat(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed; source contract remains covered")
        path = (
            Path(__file__).resolve().parents[1]
            / "voiceger_editor" / "web_assets" / "app.js"
        )
        script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("  function shouldSubmitCaptions(event)");
const end = source.indexOf('  $("new-captions").addEventListener("keydown"', start);
if (start < 0 || end < start) throw new Error("shortcut helper not found");
const fn = new Function(source.slice(start, end) + ";return shouldSubmitCaptions;")();
const make = (override) => Object.assign({
  key: "Enter", metaKey: true, isComposing: false, keyCode: 13, repeat: false
}, override);
for (const input of [
  make({key:"a"}), make({metaKey:false}), make({isComposing:true}),
  make({keyCode:229}), make({repeat:true}),
]) if (fn(input)) throw new Error("shortcut fired incorrectly");
if (!fn(make())) throw new Error("Cmd+Enter did not submit");
"""
        completed = subprocess.run(
            [node, "-e", script, str(path)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_browser_playback_states_and_stale_requests(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed; interactive browser tests require Node")
        path = (
            Path(__file__).resolve().parents[1]
            / "voiceger_editor" / "web_assets" / "app.js"
        )
        script = r"""const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const begin = source.indexOf("  function clearPlayer() {");
const end = source.indexOf("  function displayAudioProgress(op) {", begin);
if (begin < 0 || end < begin) throw new Error("Playback code not found");
const playbackSource = source.slice(begin, end);
function assert(condition, message) { if (!condition) throw new Error(message); }
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, no) => { resolve = ok; reject = no; });
  return {promise, resolve, reject};
}
function setup() {
  const events = {};
  const calls = {pause:0, play:0, feedback:[], revoked:[], created:0};
  const player = {
    paused:true, ended:false, duration:10, currentTime:0, hidden:true, src:"",
    playResult:null,
    addEventListener(name, callback) {
      (events[name] || (events[name] = [])).push(callback);
    },
    emit(name) { for (const callback of (events[name] || [])) callback(); },
    pause() { calls.pause++; this.paused = true; this.emit("pause"); },
    removeAttribute(key) { if (key === "src") this.src = ""; },
    load() { this.ended = false; this.currentTime = 0; },
    play() {
      calls.play++;
      if (this.playResult) return this.playResult();
      this.paused = false;
      this.emit("play");
      this.emit("playing");
      return Promise.resolve();
    }
  };
  const row = {
    dataset: {takeNumber:"1"}, labels:{}, children:{},
    classList: {
      values:new Set(),
      toggle(name, active) {
        if (active) this.values.add(name);
        else this.values.delete(name);
      },
      contains(name) { return this.values.has(name); }
    },
    querySelector(selector) { return this.children[selector]; }
  };
  const icon = {textContent:""};
  const button = {labels:{}, querySelector() { return icon; },
    setAttribute(key,value) { this.labels[key] = value; }};
  const indicator = {hidden:true, textContent:""};
  const progress = {hidden:true, firstElementChild:{style:{width:""}}};
  row.children = {
    ".take-play":button, ".take-play-state":indicator, ".take-progress":progress
  };
  const preview = {textContent:"",labels:{},setAttribute(k,v){this.labels[k]=v;}};
  const nodes = {
    "phone-player":player, "preview-audio":preview,
    "take-list":{querySelectorAll() {return [row];}}
  };
  let fetchResponse = async () => ({
    ok:true, blob:async()=>({type:"audio/wav",size:32})
  });
  const objectUrl = {
    createObjectURL() {return "blob:mock-" + ++calls.created;},
    revokeObjectURL(url) {calls.revoked.push(url);}
  };
  const factory = new Function("$", "fetch", "URL", "setBusy", "feedback",
    "token", "selectedId", "currentView", playbackSource +
    ";return {clearPlayer,updatePlaybackUI,togglePlayback,playAudio," +
    "getState:()=>playback,getUrl:()=>playingUrl,getRequest:()=>playbackRequestId};");
  // Playback source relies on these variables as it does in the app closure.
  const create = new Function("$","fetch","URL","feedback","setBusy",
    "let playback = null; let playbackRequestId = 0; let playingUrl = '';" +
    "let busy = false; const token='token'; const selectedId='item';" +
    "const currentView='item';" + playbackSource +
    ";return {clearPlayer,updatePlaybackUI,togglePlayback,playAudio," +
    "getState:()=>playback,getUrl:()=>playingUrl};");
  const app = create(key=>nodes[key], (...args)=>fetchResponse(...args),
    objectUrl,msg=>calls.feedback.push(msg),_=>{});
  return {app,player,row,indicator,button,preview,progress,calls,
    setFetch(callback){fetchResponse=callback;}};
}
(async()=>{
  const env = setup(), {app,player,row,indicator,button,progress,calls}=env;
  await app.playAudio("/one","item","take",1);
  assert(app.getState().phase === "playing", "Take 1 did not play");
  assert(row.classList.contains("is-playing"), "Take 1 missing playing highlight");
  const originalUrl = app.getUrl();
  // F-05: old audio must stop before the new network fetch completes.
  const outstanding = deferred();
  env.setFetch(()=>outstanding.promise);
  const pending = app.playAudio("/two","item","take",2);
  assert(player.paused, "old Take continues while replacement fetch pending");
  assert(calls.revoked.includes(originalUrl), "old blob URL not released");
  assert(!row.classList.contains("is-playing"), "old Take is still highlighted");
  outstanding.resolve({ok:false,status:503});
  await pending;
  assert(app.getState() === null, "failed switch retained stale Take state");
  assert(app.getUrl() === "", "failed switch retained blob URL");
  assert(calls.feedback.some(s=>s.includes("取得できません")), "failure not reported");
  // F-06: rejected play() is never represented as normal pause.
  env.setFetch(async()=>({ok:true,blob:async()=>({type:"audio/wav",size:12})}));
  player.playResult=()=>Promise.reject(new Error("autoplay blocked"));
  await app.playAudio("/one","item","take",1);
  assert(app.getState().phase==="failed", "play rejection not marked failed");
  assert(indicator.textContent==="再生失敗", "play rejection shown as pause");
  assert(!row.classList.contains("is-paused"), "play rejection has paused styling");
  assert(player.hidden===false, "native media controls not shown after rejection");
  assert(button.labels["aria-label"].includes("再取得"), "retry action inaccessible");
  // A subsequent tap must be able to retry by fetching afresh.
  player.playResult=null;
  await app.playAudio("/one","item","take",1);
  assert(app.getState().phase==="playing", "retry did not resume playback");
  player.currentTime=4;player.emit("timeupdate");
  assert(progress.firstElementChild.style.width==="40%", "progress is incorrect");
  assert(app.togglePlayback("take","item",1), "pause tap not recognized");
  assert(app.getState().phase==="paused", "pause event not reflected");
  assert(indicator.textContent==="一時停止", "pause status missing");
  assert(app.togglePlayback("take","item",1), "resume tap not recognized");
  await Promise.resolve();
  assert(app.getState().phase==="playing", "resume failed");
  player.paused=true;player.ended=true;player.emit("ended");
  assert(app.getState()===null, "ended retains active state");
  // Media errors are distinct from pause even after playback started.
  player.paused=false;player.ended=false;
  await app.playAudio("/one","item","take",1);
  player.emit("error");
  assert(app.getState().phase==="failed", "media error was not represented");
  assert(indicator.textContent==="再生失敗", "media error not shown");
  // Late fetch completions must not revive a disposed player.
  const late=deferred();
  env.setFetch(()=>late.promise);
  const pendingLate=app.playAudio("/one","item","take",1);
  app.clearPlayer();
  const createdBefore=calls.created;
  late.resolve({ok:true,blob:async()=>({type:"audio/wav",size:16})});
  await pendingLate;
  assert(app.getState()===null, "late fetch revived disposed player");
  assert(calls.created===createdBefore, "late fetch created blob URL");
  // A late rejection from an abandoned play promise must not reinstate failure.
  const rejected=deferred();
  env.setFetch(async()=>({ok:true,blob:async()=>({type:"audio/wav",size:20})}));
  player.playResult=()=>rejected.promise;
  const pendingPlay=app.playAudio("/one","item","take",1);
  await Promise.resolve();await Promise.resolve();await Promise.resolve();
  app.clearPlayer();
  const feedbackBefore=calls.feedback.length;
  rejected.reject(new Error("stale"));
  await pendingPlay;
  assert(app.getState()===null, "stale play rejection revived state");
  assert(calls.feedback.length===feedbackBefore, "stale play rejection reported as current");
  console.log("BROWSER_PLAYBACK_STATE_TESTS_PASS");
})().catch(error=>{console.error(error);process.exitCode=1;});"""
        completed = subprocess.run(
            [node, "-e", script, str(path)], capture_output=True,
            text=True, timeout=15, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("BROWSER_PLAYBACK_STATE_TESTS_PASS", completed.stdout)

    def test_mobile_first_open_auto_prepare_is_idempotent_and_failure_gated(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed; source contract remains covered")
        path = (
            Path(__file__).resolve().parents[1]
            / "voiceger_editor" / "web_assets" / "app.js"
        )
        script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("  function maybePrepareOnOpen(");
const end = source.indexOf("  function renderItem(", start);
if (start < 0 || end < start) throw new Error("auto prepare helper missing");
const failures = new Set();
const calls = [];
const auto = new Function("autoPrepareFailures", "startAudio",
  source.slice(start, end) + "; return maybePrepareOnOpen;")(
    failures, (...args) => calls.push(args));
auto({id:"one", is_prepared:true});
if (calls.length !== 0) throw new Error("prepared item rebuilt");
auto({id:"one", is_prepared:false});
if (calls.length !== 1 || calls[0][1] !== "/audio/prepare" ||
    calls[0][2].rebuild !== false || calls[0][3] !== true) {
  throw new Error("first open did not prepare");
}
failures.add("one");
auto({id:"one", is_prepared:false});
if (calls.length !== 1) throw new Error("failure auto-retried");
auto({id:"two", is_prepared:false});
if (calls.length !== 2) throw new Error("new item not prepared");
"""
        completed = subprocess.run(
            [node, "-e", script, str(path)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

if __name__ == "__main__":
    unittest.main()
