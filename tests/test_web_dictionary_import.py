"""Slice 9b: Output-only reviewed Web dictionary merge acceptance."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_user_dictionary import FakeBackend
from voiceger_editor.dictionary_export import (
    export_voiceger_editor_dictionaries, export_voicevox_dictionary,
)
from voiceger_editor.settings import Settings
from voiceger_editor.user_dictionary import UserDictionaryCore
from voiceger_editor.web import ASSETS, create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


TOKEN = "web-dictionary-import-test-token-strong-enough"


class WebImportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.output = self.root / "output"
        self.output.mkdir()
        (self.root / "voiceger").mkdir()
        self.core = UserDictionaryCore(
            self.root / "voiceger", data_directory=self.root / "local",
            openjtalk_dictionary=FakeBackend(),
        )
        self.current_word = self.core.add_japanese_word(
            surface="雨", pronunciation="アメ", accent_type=1,
        )
        self.core.add_english_entry("sweet", ["S", "W", "IY1", "T"])
        self.incoming = UserDictionaryCore(
            self.root / "voiceger", data_directory=self.root / "incoming",
            openjtalk_dictionary=FakeBackend(),
        )
        self.incoming.add_japanese_word(surface="雨", pronunciation="アメ", accent_type=0)
        self.incoming.add_japanese_word(surface="太陽", pronunciation="タイヨー", accent_type=1)
        self.incoming.add_english_entry("sweet", ["S", "W", "EH1", "T"])
        self.incoming.add_english_entry("zunda", ["Z", "UW1", "N", "D", "AH0"])
        self.zip_name = export_voiceger_editor_dictionaries(
            self.incoming, self.output
        ).paths[0].name
        self.json_name = export_voicevox_dictionary(
            self.incoming, self.output
        ).paths[0].name
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
        self.url = f"/api/web/sessions/{self.sid}/dictionary/import"
        self.dictionary = f"/api/web/sessions/{self.sid}/dictionary"

    def tearDown(self):
        self.client.close()
        self.service.shutdown()
        self.settings.stop()
        self.auth.stop()

    def revision(self):
        response = self.client.get(self.dictionary + "/ja", headers=self.read)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["revision"]

    def post(self, suffix, data, headers=None):
        return self.client.post(
            self.url + suffix, json=data, headers=self.write if headers is None else headers,
        )

    def review(self, filename):
        response = self.post("/review", {
            "filename": filename, "expected_revision": self.revision(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_zip_selection_and_non_destructive_merge(self):
        names = self.client.get(self.url + "/files", headers=self.read)
        self.assertEqual(names.status_code, 200)
        self.assertIn(self.zip_name, names.json()["files"])
        review = self.review(self.zip_name)
        self.assertEqual(review["format"], "backup")
        self.assertEqual(review["new"], 2)
        self.assertEqual(review["conflicts"], 2)
        self.assertEqual(review["selected"], 2)
        self.assertEqual(review["replacements"], 0)
        token = review["token"]
        self.assertEqual(
            self.post("/commit", {"token": token, "confirmed": False}).status_code,
            409,
        )
        # A rejected commit consumes the review; open a new one.
        review = self.review(self.zip_name)
        token = review["token"]
        conflict = next(x for x in review["items"] if x["relation"] == "conflict" and x["language"] == "ja")
        chosen = self.post("/selection", {
            "token": token, "language": "ja", "identity": conflict["identity"],
            "selected": True,
        })
        self.assertEqual(chosen.status_code, 200, chosen.text)
        self.assertEqual(chosen.json()["replacements"], 1)
        committed = self.post("/commit", {"token": token, "confirmed": True})
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(committed.json()["imported"], 2)
        self.assertEqual(committed.json()["replaced"], 1)
        self.assertEqual(self.post("/commit", {"token": token, "confirmed": True}).status_code, 409)
        self.assertEqual(self.core.list_japanese_entries()[self.current_word].accent_type, 0)
        self.assertIn("sweet", self.core.list_english_entries())
        self.assertEqual(self.core.list_english_entries()["sweet"].phonemes,
                         ["S", "W", "IY1", "T"])
        self.assertEqual(len(self.core.list_japanese_entries()), 2)

    def test_json_cancel_clear_and_source_change(self):
        review = self.review(self.json_name)
        self.assertEqual(review["format"], "japanese")
        cleared = self.post("/clear", {"token": review["token"]})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["selected"], 0)
        self.assertEqual(self.post("/cancel", {"token": review["token"]}).status_code, 200)
        self.assertEqual(self.post("/commit", {
            "token": review["token"], "confirmed": True,
        }).status_code, 409)
        review = self.review(self.json_name)
        file = self.output / self.json_name
        file.write_bytes(file.read_bytes() + b" ")
        changed = self.post("/commit", {"token": review["token"], "confirmed": True})
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertEqual(len(self.core.list_japanese_entries()), 1)

    def test_source_restrictions_auth_and_conflicts(self):
        (self.output / "shortcut.json").symlink_to(self.output / self.json_name)
        listing = self.client.get(self.url + "/files", headers=self.read).json()
        self.assertNotIn("shortcut.json", listing["files"])
        self.assertEqual(self.post("/review", {
            "filename": "../secret.json", "expected_revision": self.revision(),
        }).status_code, 422)
        self.assertEqual(self.post("/review", {
            "filename": "shortcut.json", "expected_revision": self.revision(),
        }).status_code, 422)
        revision = self.revision()
        self.assertEqual(self.client.post(self.url + "/review", json={
            "filename": self.zip_name, "expected_revision": revision,
        }).status_code, 401)
        self.assertEqual(self.post("/review", {
            "filename": self.zip_name, "expected_revision": revision,
        }, headers=self.read).status_code, 403)
        self.assertEqual(self.post("/review", {
            "filename": self.zip_name, "expected_revision": revision,
        }, headers={**self.write, "Origin": "https://evil.example"}).status_code, 403)
        review = self.review(self.zip_name)
        self.core.add_japanese_word(surface="水", pronunciation="ミズ", accent_type=1)
        self.assertEqual(self.post("/selection", {
            "token": review["token"], "language": "ja",
            "identity": review["items"][0]["identity"], "selected": True,
        }).status_code, 409)
        self.assertEqual(self.post("/commit", {
            "token": review["token"], "confirmed": True,
        }).status_code, 409)

    def test_browser_markup_and_js_syntax(self):
        import shutil
        import subprocess
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="dictionary-import-file"', html)
        self.assertIn('id="view-dictionary-import-review"', html)
        self.assertIn('id="dictionary-import-entries"', html)
        self.assertIn('importPath() + "/commit"', js)
        self.assertIn('dictionaryPushHistory("dictionary-import-review")', js)
        if shutil.which("node"):
            checked = subprocess.run(["node", "--check", str(ASSETS / "app.js")],
                                     capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            review_ui = subprocess.run(
                ["node", str(ASSETS.parent.parent / "tests" / "fixtures" /
                 "web_dictionary_import_review.js"), str(ASSETS / "app.js")],
                capture_output=True, text=True,
            )
            self.assertEqual(review_ui.returncode, 0, review_ui.stderr)
            self.assertIn("DICT_IMPORT_REVIEW_PASS", review_ui.stdout)
