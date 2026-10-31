"""Slice 10a: common and item-local Web settings regression coverage."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
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
               top_p=1.0, temperature=1.0, confirmed=False,
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
                "confirm_take_invalidation": confirmed,
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
        self.assertIn('id="common-settings-form" class="setting-section" novalidate', html)
        self.assertIn('id="item-speed" type="number" inputmode="decimal" min="0" step="0.01"', html)
        self.assertIn('id="common-speed" type="number" inputmode="decimal" min="0" step="0.01"', html)
        self.assertIn('class="sampling-settings-group"', html)
        self.assertIn('class="sampling-settings-heading"', html)
        self.assertIn('id="reset-sampling">リセット</button>', html)
        self.assertIn('id="common-settings-status"', html)
        self.assertIn('id="default-takes-status"', html)
        self.assertNotIn('id="reset-common-draft"', html)
        self.assertNotIn('<button type="submit">保存</button>\n        </form>\n        <div class="setting-section">\n          <h3>セッション', html)
        self.assertIn('border-top: 1px solid #cbdcd2', css)
        self.assertLess(html.index('id="common-speed"'),
                        html.index('class="sampling-settings-heading"'))
        self.assertLess(html.index('class="sampling-settings-heading"'),
                        html.index('id="common-top-k"'))

    def test_actual_browser_settings_draft_guards(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for browser guard verification")
        source = r"""
const fs=require("fs"),assert=require("assert").strict;
const js=fs.readFileSync(process.argv[1],"utf8");
const begin=js.indexOf("  function itemVoiceDirty(item) {");
const end=js.indexOf("  function guardDraft() {",begin);
assert(begin>=0 && end>begin,"settings guard source not found");
const nodes={
  "item-style":{value:"3"},
  "item-speed":{value:"1.00"},
  "common-style":{value:"3"},
  "common-speed":{value:"1.00"},
  "common-top-k":{value:"20"},
  "common-top-p":{value:"1.00"},
  "common-temperature":{value:"1.00"},
};
const data={values:{style_id:3,speed:1,top_k:20,top_p:1,temperature:1}};
const make=data=>new Function("$","commonSettingsData",
  js.slice(begin,end)+"return {itemVoiceDirty,commonDirty};"
)(id=>nodes[id],data);
const guards=make(data),item={style_id:3,speed:1};
assert.equal(guards.itemVoiceDirty(item),false);
assert.equal(guards.commonDirty(),false);
nodes["item-speed"].value="1.25";
assert.equal(guards.itemVoiceDirty(item),true);
nodes["item-speed"].value="1.00";
nodes["item-style"].value="1";
assert.equal(guards.itemVoiceDirty(item),true);
nodes["item-style"].value="3";
nodes["common-temperature"].value="0.85";
assert.equal(guards.commonDirty(),true);
nodes["common-temperature"].value="";
assert.equal(guards.commonDirty(),true);
nodes["common-temperature"].value="1.00";
assert.equal(make(null).commonDirty(),false);
assert.equal(make(null).itemVoiceDirty(item),false);
const speedStart=js.indexOf("  function validSpeed(raw) {");
const speedEnd=js.indexOf("  async function saveItemVoice() {",speedStart);
assert(speedStart>=0 && speedEnd>speedStart,"speed validation source not found");
const precision=new Function(js.slice(speedStart,speedEnd)+
  "return {validSpeed,validSampling};")();
assert.equal(precision.validSpeed("1.234567"),1.234567);
assert.equal(precision.validSampling({
  style_id:3,speed:1.234567,top_k:20,top_p:1,temperature:1
}).speed,1.234567);
console.log("WEB_SETTINGS_BROWSER_GUARDS_PASS");
"""
        result = subprocess.run(
            [node, "-e", source, str(ASSETS / "app.js")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("WEB_SETTINGS_BROWSER_GUARDS_PASS", result.stdout)

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

    def test_common_noop_preserves_high_precision_values(self):
        precise = Settings(
            output_dir=Path(self.temp.name),
            speed=1.2345, top_p=0.125, temperature=0.98765,
        )
        self.service._batch_settings = precise
        previous = self.settings()
        result = self.common(
            speed=1.2345, top_p=0.125, temperature=0.98765,
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["settings_revision"],
                         previous["settings_revision"])
        self.save_mock.assert_not_called()
        self.assertEqual(self.service._batch_settings, precise)

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
        refused = self.common(top_k=30)
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(
            refused.json()["detail"]["code"], "take_invalidation_confirmation_required"
        )
        self.assertEqual(len(item.session.candidates), 1)
        self.save_mock.assert_not_called()
        result = self.common(top_k=30, confirmed=True)
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

    def test_confirmation_covers_other_web_sessions(self):
        other_sid = self.client.post(
            "/api/web/sessions", headers=self.write_headers
        ).json()["id"]
        self.service.add_captions(other_sid, 0, "別セッション")
        other = self.service._sessions[other_sid].batch.items[0]
        other.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000,
                            sampling_rate=16000, style_name="Neutral")
        )
        revision = self.settings()["settings_revision"]
        response = self.common(top_p=0.8)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(other.session.candidates), 1)
        self.assertEqual(self.settings()["settings_revision"], revision)
        self.save_mock.assert_not_called()
        confirmed = self.common(top_p=0.8, confirmed=True)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(other.session.candidates, [])

    def test_nonboolean_confirmation_is_rejected(self):
        response = self.client.patch(
            self.base + "/settings?expected_revision=" +
            str(self.batch()["revision"]) + "&expected_settings_revision=0",
            headers=self.write_headers,
            json={"style_id": 3, "speed": 1, "top_k": 20,
                  "top_p": 1, "temperature": 1,
                  "confirm_take_invalidation": "yes"},
        )
        self.assertEqual(response.status_code, 422)
        self.save_mock.assert_not_called()

    def test_failed_save_and_busy_worker_do_not_mutate(self):
        item = self.add()
        item.session.candidates.append(
            SimpleNamespace(number=1, frame_count=16000,
                            sampling_rate=16000, style_name="Neutral")
        )
        self.save_mock.side_effect = PermissionError("private Mac path")
        response = self.common(top_k=30, confirmed=True)
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
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(stale.json()["detail"]["code"], "settings_revision_conflict")
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
