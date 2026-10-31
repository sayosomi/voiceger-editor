"""Slice 10a: common and item-local Web settings regression coverage."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from voiceger_editor.settings import Settings
from voiceger_editor.styles import VoicegerStyle
from voiceger_editor.web import ASSETS, create_web_app
from voiceger_editor.web_sessions import WebSessionOperations


TOKEN = "web-settings-test-token-long-enough-for-authentication"
STYLES = (
    VoicegerStyle(3, "Neutral", "neutral.wav"),
    VoicegerStyle(1, "Sweet", "sweet.wav"),
)


class FakeSpeech:
    """A minimal UtteranceSession for Web state and retention checks."""

    def __init__(self, caption: str, settings: Settings):
        self.caption = caption
        self.settings = settings
        self.is_prepared = False
        self.candidates = []
        self.synthesis_source_text = None

    @property
    def style(self):
        return SimpleNamespace(name={3: "Neutral", 1: "Sweet"}[self.settings.style_id])

    @property
    def active_candidate_count(self):
        return len(self.candidates)

    def replace_caption(self, caption):
        self.caption = caption

    def replace_settings(self, settings, *, preserve_takes=False):
        old = self.settings
        changed = any(
            getattr(old, key) != getattr(settings, key)
            for key in ("style_id", "speed", "top_k", "top_p", "temperature")
        )
        if changed and not preserve_takes:
            self.discard_takes()
        self.settings = settings

    def discard_takes(self):
        self.candidates.clear()


class WebSynthesisSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Settings(output_dir=Path(self.temp.name))
        self.auth = patch.dict(os.environ, {"VOICEGER_WEB_TOKEN": TOKEN})
        self.auth.start()
        self.saved = patch("voiceger_editor.web_settings.save_settings")
        self.save_mock = self.saved.start()
        self.service = WebSessionOperations(
            caption_factory=lambda caption: FakeSpeech(caption, self.config)
        )
        self.service._batch_settings = self.config
        self.service._styles = lambda: STYLES
        self.client = TestClient(create_web_app(service=self.service))
        self.read_headers = {"Authorization": "Bearer " + TOKEN}
        self.write_headers = {
            **self.read_headers, "X-Voiceger-Web-Request": "1"
        }
        self.sid = self.client.post(
            "/api/web/sessions", headers=self.write_headers
        ).json()["id"]

    def tearDown(self):
        self.service.shutdown()
        self.client.close()
        self.saved.stop()
        self.auth.stop()
        self.temp.cleanup()

    @property
    def base(self):
        return "/api/web/sessions/" + self.sid

    def add(self, caption="こんにちは"):
        rev = self.batch()["revision"]
        response = self.client.post(
            self.base + "/batch/items?expected_revision=" + str(rev),
            headers=self.write_headers, json={"text": caption},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return self.service._sessions[self.sid].batch.items[-1]

    def batch(self):
        response = self.client.get(self.base + "/batch", headers=self.read_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def settings(self):
        response = self.client.get(self.base + "/settings", headers=self.read_headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def item_voice(self, item, *, style_id=1, speed=1.25, revision=None):
        if revision is None:
            revision = self.batch()["revision"]
        return self.client.patch(
            self.base + "/batch/items/" + item.item_id +
            "/voice?expected_revision=" + str(revision),
            headers=self.write_headers,
            json={"style_id": style_id, "speed": speed},
        )

    def common(self, *, style_id=3, speed=1.0, top_k=20,
               top_p=1.0, temperature=1.0,
               revision=None, settings_revision=None):
        data = self.settings()
        rev = data["revision"] if revision is None else revision
        shared_rev = (
            data["settings_revision"]
            if settings_revision is None else settings_revision
        )
        return self.client.patch(
            self.base + "/settings?expected_revision=" + str(rev) +
            "&expected_settings_revision=" + str(shared_rev),
            headers=self.write_headers,
            json={
                "style_id": style_id, "speed": speed, "top_k": top_k,
                "top_p": top_p, "temperature": temperature,
            },
        )

    def test_approved_two_column_ui_contract(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        self.assertIn('class="item-voice-grid"', html)
        self.assertIn('id="item-style"', html)
        self.assertIn('id="item-speed"', html)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertIn('id="edit-take-count"', html)
        self.assertNotIn("このCaptionの生成条件", html)
        self.assertIn('id="common-settings-form"', html)

    def test_authenticated_values_and_style_catalog(self):
        data = self.settings()
        self.assertEqual(data["values"]["style_id"], 3)
        self.assertEqual([x["name"] for x in data["styles"]], ["Neutral", "Sweet"])
        self.assertNotIn("output_dir", str(data))
        self.assertEqual(
            self.client.get(self.base + "/settings").status_code, 401
        )

    def test_item_voice_keeps_accepted_takes_and_siblings(self):
        item = self.add()
        sibling = self.add("ふたつめ")
        item.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000, sampling_rate=16000,
                            style_name="Neutral")
        )
        item.mark_accepted(1)
        previous_revision = self.batch()["revision"]
        response = self.item_voice(item)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["revision"], previous_revision + 1)
        self.assertEqual(len(item.session.candidates), 1)
        self.assertEqual(item.accepted_take_numbers, frozenset({1}))
        self.assertEqual(sibling.session.settings.style_id, 3)
        self.assertEqual(item.session.settings.speed, 1.25)
        second = self.item_voice(item)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["revision"], previous_revision + 1)

    def test_item_voice_validation_and_revision_conflict(self):
        item = self.add()
        revision = self.batch()["revision"]
        self.assertEqual(
            self.item_voice(item, speed=-1, revision=revision).status_code, 422
        )
        self.assertEqual(
            self.item_voice(item, style_id=999, revision=revision).status_code, 422
        )
        self.assertEqual(
            self.item_voice(item, revision=revision - 1).status_code, 409
        )
        self.assertEqual(item.session.settings, self.config)

    def test_common_sampling_clears_candidates_and_keeps_local_style(self):
        item = self.add()
        other = self.add("ふたつめ")
        self.assertEqual(self.item_voice(item).status_code, 200)
        for entry in (item, other):
            entry.session.candidates.append(
                SimpleNamespace(number=1, frame_count=16000,
                                sampling_rate=16000, style_name="Neutral")
            )
            entry.mark_accepted(1)
        result = self.common(top_k=30)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(item.session.settings.style_id, 1)
        self.assertEqual(item.session.settings.speed, 1.25)
        self.assertEqual(other.session.settings.style_id, 3)
        self.assertEqual(item.session.settings.top_k, 30)
        for entry in (item, other):
            self.assertEqual(entry.session.candidates, [])
            self.assertEqual(entry.accepted_take_numbers, frozenset())
        self.assertEqual(self.save_mock.call_count, 1)
        self.assertEqual(self.common(style_id=1, top_k=30).status_code, 200)
        self.assertEqual(other.session.settings.style_id, 1)

    def test_failed_save_and_busy_worker_do_not_mutate(self):
        item = self.add()
        item.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000,
                            sampling_rate=16000, style_name="Neutral")
        )
        self.save_mock.side_effect = PermissionError("private Mac path")
        response = self.common(top_k=30)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("private Mac path", response.text)
        self.assertEqual(self.service._batch_settings.top_k, 20)
        self.assertEqual(len(item.session.candidates), 1)
        self.save_mock.side_effect = None
        self.service._active = (self.sid, "operation")
        try:
            self.assertEqual(self.common(top_k=30).status_code, 409)
            self.assertEqual(self.item_voice(item).status_code, 409)
        finally:
            self.service._active = None

    def test_independent_settings_revision_and_csrf(self):
        old = self.settings()
        self.assertEqual(self.common(top_k=25).status_code, 200)
        stale = self.common(
            top_k=30, revision=self.batch()["revision"],
            settings_revision=old["settings_revision"],
        )
        self.assertEqual(stale.status_code, 409)
        unauthorized = self.client.patch(
            self.base + "/settings?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=1",
            headers=self.read_headers,
            json={"style_id": 3, "speed": 1, "top_k": 20,
                  "top_p": 1, "temperature": 1},
        )
        self.assertEqual(unauthorized.status_code, 403)


if __name__ == "__main__":
    unittest.main()
