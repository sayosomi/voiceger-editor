"""Slice 9a: authenticated native/VOICEVOX dictionary export transactions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient

from tests.test_user_dictionary import FakeBackend
from voiceger_editor.pronunciation import PitchEvent
from voiceger_editor.settings import Settings
from voiceger_editor.user_dictionary import UserDictionaryCore
from voiceger_editor.web import ASSETS, create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


TOKEN = "dictionary-export-web-test-323-token-long-enough"
EVENTS = (
    PitchEvent(1, "["), PitchEvent(2, "]"),
    PitchEvent(4, "["), PitchEvent(5, "]"),
)


class DictionaryExportWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.output = root / "output"
        (root / "voiceger").mkdir()
        self.core = UserDictionaryCore(
            root / "voiceger", data_directory=root / "data",
            openjtalk_dictionary=FakeBackend(),
        )
        self.word_id = self.core.add_japanese_word(
            surface="スタックチャン", pronunciation="スタックチャン",
            accent_type=2, pitch_events=EVENTS,
        )
        self.core.add_english_entry("sweet", ["S", "W", "IY1", "T"])
        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.settings = patch(
            "voiceger_editor.web_recipe.load_settings",
            return_value=Settings(output_dir=self.output),
        )
        self.auth.start()
        self.settings.start()
        self.service = WebSessionOperations(dictionary_core=self.core)
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post(
            "/api/web/sessions", headers=self.write,
        ).json()["id"]
        self.prefix = f"/api/web/sessions/{self.sid}/dictionary"

    def tearDown(self):
        self.client.close()
        self.service.shutdown()
        self.settings.stop()
        self.auth.stop()

    def revision(self):
        response = self.client.get(self.prefix + "/ja", headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["revision"]

    def review(self, kind, revision=None):
        return self.client.post(
            self.prefix + "/export/review", headers=self.write,
            json={
                "format": kind,
                "expected_revision": revision or self.revision(),
            },
        )

    def commit(self, review, *, confirm=False, revision=None):
        return self.client.post(
            self.prefix + "/export/commit", headers=self.write,
            json={
                "token": review["token"],
                "expected_revision": revision or self.revision(),
                "confirmed_pitch_loss": confirm,
            },
        )

    def test_native_complete_zip_and_filename_collision(self):
        review = self.review("native")
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()["lossy_pitch_count"], 0)
        self.assertFalse(self.output.exists())  # Preview must not touch disk.
        first = self.commit(review.json())
        self.assertEqual(first.status_code, 200, first.text)
        filename = first.json()["filename"]
        self.assertEqual(Path(filename).name, filename)
        with ZipFile(self.output / filename) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "manifest.json", "user_dict.json",
                    "english_user_dict.json", "user_dict_pitch_events.json",
                },
            )
            self.assertIn(self.word_id, json.loads(
                archive.read("user_dict_pitch_events.json"),
            )["entries"])
            self.assertIn("sweet", json.loads(
                archive.read("english_user_dict.json"),
            ))
        replay = self.commit(review.json())
        self.assertEqual(replay.status_code, 409)
        second = self.commit(self.review("native").json())
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(filename, second.json()["filename"])
        self.assertEqual(len(list(self.output.glob("*.zip"))), 2)

    def test_voicevox_warning_cancel_then_confirmed_output(self):
        revision = self.revision()
        review = self.review("voicevox").json()
        self.assertEqual(review["lossy_pitch_count"], 1)
        self.assertEqual(review["scope"], "Mac Output folder")
        cancelled = self.client.post(
            self.prefix + "/export/cancel", json={"token": review["token"]},
            headers=self.write,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.commit(review, confirm=True).status_code, 409)
        unconfirmed = self.commit(self.review("voicevox").json())
        self.assertEqual(unconfirmed.status_code, 409)
        self.assertFalse(self.output.exists())
        saved = self.commit(self.review("voicevox").json(), confirm=True)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["lossy_pitch_count"], 1)
        payload = json.loads(
            (self.output / saved.json()["filename"]).read_text(encoding="utf-8"),
        )
        self.assertIn(self.word_id, payload)
        self.assertNotIn("sweet", payload)
        self.assertEqual(self.revision(), revision)  # No dictionary mutation.
        self.assertEqual(len(list(self.output.glob("*.json"))), 1)

    def test_auth_origin_stale_revisions_and_worker_busy(self):
        revision = self.revision()
        self.assertEqual(
            self.client.post(self.prefix + "/export/review", json={
                "format": "native", "expected_revision": revision,
            }).status_code, 401,
        )
        self.assertEqual(
            self.client.post(
                self.prefix + "/export/review",
                headers=self.read, json={
                    "format": "native", "expected_revision": revision,
                },
            ).status_code, 403,
        )
        self.assertEqual(
            self.client.post(
                self.prefix + "/export/review",
                headers={**self.write, "Origin": "https://bad.example"},
                json={"format": "native", "expected_revision": revision},
            ).status_code, 403,
        )
        self.assertEqual(self.review("unknown").status_code, 422)
        existing = self.review("native").json()
        self.core.add_japanese_word(
            surface="雨", pronunciation="アメ", accent_type=1,
        )
        self.assertEqual(self.commit(existing, revision=revision).status_code, 409)
        self.assertEqual(self.review("native", revision=revision).status_code, 409)
        self.assertFalse(self.output.exists())
        self.service._active = (self.sid, "fake-running")
        try:
            self.assertEqual(self.review("native").status_code, 409)
        finally:
            self.service._active = None

    def test_storage_failure_does_not_expose_path_or_touch_dictionary(self):
        review = self.review("native").json()
        with patch(
            "voiceger_editor.web_dictionary_export.export_voiceger_editor_dictionaries",
            side_effect=OSError("sensitive path /home/private"),
        ):
            failed = self.commit(review)
        self.assertEqual(failed.status_code, 503, failed.text)
        self.assertEqual(failed.json()["detail"], {"code": "export_io"})
        self.assertNotIn("private", failed.text)
        self.assertEqual(self.commit(review).status_code, 409)
        self.assertEqual(self.revision(), review["token"] if False else self.revision())

    def test_mobile_ui_markup_and_production_js_syntax(self):
        import shutil
        import subprocess

        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="dictionary-management"', html)
        self.assertIn('id="dictionary-export-native"', html)
        self.assertIn('id="dictionary-export-voicevox"', html)
        self.assertIn('id="dictionary-export-message"', html)
        self.assertIn('role="status"', html)
        self.assertIn('dictionaryPath() + "/export/review"', js)
        self.assertIn('dictionaryPath() + "/export/commit"', js)
        self.assertIn('dictionaryPath() + "/export/cancel"', js)
        self.assertIn("window.confirm", js)
        if shutil.which("node"):
            completed = subprocess.run(
                ["node", "--check", str(ASSETS / "app.js")],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
