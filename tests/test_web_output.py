"""Web Slice 10b Output setting regression tests."""

from pathlib import Path
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

from fastapi.testclient import TestClient

from voiceger_editor.settings import Settings
from voiceger_editor.styles import VoicegerStyle
from voiceger_editor.web import ASSETS, create_web_app
from voiceger_editor.web_sessions import WebSessionOperations

TOKEN = "output-web-test-token-long-enough"
STYLES = (VoicegerStyle(3, "Neutral", "neutral.wav"),)


class FakeSpeech:
    def __init__(self, caption, settings):
        self.caption = caption
        self.settings = settings
        self.candidates = []
        self.is_prepared = False
        self.synthesis_source_text = None

    @property
    def style(self):
        return SimpleNamespace(name="Neutral")

    @property
    def active_candidate_count(self):
        return len(self.candidates)

    def replace_caption(self, caption):
        self.caption = caption

    def replace_settings(self, settings, *, preserve_takes=False):
        self.settings = settings
        if not preserve_takes:
            self.candidates.clear()

    def discard_takes(self):
        self.candidates.clear()


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.initial = Settings(output_dir=Path(self.tmp.name) / "old")
        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.auth.start()
        self.formats = patch("voiceger_editor.web_output.available_output_formats",
                             return_value=("wav", "flac", "mp3"))
        self.formats.start()
        self.writer = patch("voiceger_editor.web_output.save_settings")
        self.save = self.writer.start()
        self.service = WebSessionOperations(
            caption_factory=lambda caption: FakeSpeech(caption, self.initial)
        )
        self.service._batch_settings = self.initial
        self.service._styles = lambda: STYLES
        self.client = TestClient(create_web_app(service=self.service))
        self.read = {"Authorization": "Bearer " + TOKEN}
        self.write = {**self.read, "X-Voiceger-Web-Request": "1"}
        self.sid = self.client.post("/api/web/sessions",
                                    headers=self.write).json()["id"]
        self.base = "/api/web/sessions/" + self.sid

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.writer.stop()
        self.formats.stop()
        self.auth.stop()
        self.tmp.cleanup()

    def get_output(self):
        response = self.client.get(self.base + "/settings/output",
                                   headers=self.read)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def batch(self):
        return self.client.get(self.base + "/batch",
                               headers=self.read).json()

    def patch_output(self, **changes):
        data = self.get_output()
        return self.client.patch(
            self.base + "/settings/output?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=" +
            str(data["settings_revision"]),
            headers=self.write, json={**data["values"], **changes},
        )

    def add(self):
        result = self.client.post(
            self.base + "/batch/items?expected_revision=" +
            str(self.batch()["revision"]),
            json={"text": "こんにちは"}, headers=self.write,
        )
        self.assertEqual(result.status_code, 200, result.text)
        return self.service._sessions[self.sid].batch.items[0]

    def test_preview_and_invalid_values(self):
        response = self.client.get(
            self.base + "/settings/output/preview",
            params={"template": "{style}_{caption}", "output_format": "flac"},
            headers=self.read,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filename"], "Neutral_サンプル.flac")
        self.assertEqual(self.patch_output(output_dir="relative").status_code, 422)
        self.assertEqual(self.patch_output(filename_template="{bad}").status_code, 422)
        self.assertEqual(self.patch_output(wav_encoding="invalid").status_code, 422)
        with patch("voiceger_editor.web_output.available_output_formats",
                   return_value=("wav", "flac")):
            self.assertEqual(self.patch_output(output_format="mp3").status_code, 422)
        self.assertEqual(self.client.get(self.base + "/settings/output").status_code, 401)

    def test_retarget_preserves_takes_and_clears_old_reviews(self):
        item = self.add()
        item.session.candidates.append(SimpleNamespace(
            number=1, frame_count=16000, sampling_rate=16000, style_name="Neutral"
        ))
        item.mark_accepted(1)
        item.set_generation_outcome("completed")
        state = self.service._sessions[self.sid]
        old_review = Mock()
        state.pending_recipe = old_review
        state.pending_dictionary_export = object()
        state.pending_dictionary_import = object()
        old_root = self.service._recipe_root()
        destination = Path(self.tmp.name) / "new-output"
        result = self.patch_output(output_dir=str(destination),
                                   output_format="flac", flac_encoding="pcm24",
                                   save_text=True, save_lab=True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotEqual(old_root, self.service._recipe_root())
        old_review.dispose.assert_called_once()
        self.assertIsNone(state.pending_recipe)
        self.assertIsNone(state.pending_dictionary_export)
        self.assertIsNone(state.pending_dictionary_import)
        self.assertEqual(item.session.settings.output_dir, destination)
        self.assertEqual(item.session.settings.output_format, "flac")
        self.assertEqual(len(item.session.candidates), 1)
        self.assertEqual(item.accepted_take_numbers, frozenset({1}))
        self.assertEqual(item.generation_outcome, "completed")
        self.save.assert_called_once()

    def test_failed_save_and_reset(self):
        item = self.add()
        previous = self.get_output()
        previous_batch = self.batch()
        self.save.side_effect = PermissionError("sensitive Mac path")
        result = self.patch_output(save_text=True)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("sensitive Mac path", result.text)
        self.assertEqual(self.get_output(), previous)
        self.assertEqual(self.batch(), previous_batch)
        self.save.side_effect = None
        changed = self.patch_output(save_text=True, output_format="flac")
        self.assertEqual(changed.status_code, 200)
        now = self.get_output()
        response = self.client.post(
            self.base + "/settings/reset?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=" +
            str(now["settings_revision"]),
            headers=self.write,
        )
        self.assertEqual(response.status_code, 200, response.text)
        output = response.json()["output"]["values"]
        self.assertEqual(output["output_dir"], str(self.initial.output_dir))
        self.assertEqual(output["filename_template"], self.initial.filename_template)
        self.assertEqual(output["output_format"], "wav")
        self.assertFalse(output["save_text"])

    def test_static_mobile_screen_contract(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        self.assertLess(html.index('id="default-takes"'),
                        html.index('id="output-settings-form"'))
        self.assertLess(html.index('id="output-settings-form"'),
                        html.index("Webサーバー"))
        for key in ("output-dir", "output-template", "output-format",
                    "output-encoding", "output-text", "output-lab",
                    "output-filename-preview", "output-settings-status"):
            self.assertIn('id="' + key + '"', html)
        self.assertIn("function autoSaveOutput()", js)
        self.assertIn("function outputDirty()", js)
        self.assertNotIn('id="save-output-settings"', html)


if __name__ == "__main__":
    unittest.main()
