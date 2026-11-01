"""Web Slice 10b Output setting regression tests."""

from pathlib import Path
import os
import shutil
import subprocess
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

    def stage_output_settings(self, settings):
        if any(getattr(settings, key) != getattr(self.settings, key)
               for key in ("style_id", "speed", "top_k", "top_p",
                           "temperature", "take_count")):
            raise ValueError("Output preflight changed synthesis values")
        return lambda: setattr(self, "settings", settings)

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
        self.reset_writer = patch("voiceger_editor.web_settings.save_settings")
        self.reset_save = self.reset_writer.start()
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
        self.reset_writer.stop()
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
        self.assertEqual(self.patch_output(filename_template="///").status_code, 422)
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

    def test_output_noop_does_not_persist_or_advance_revisions(self):
        before = self.get_output()
        batch = self.batch()
        response = self.patch_output()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.get_output(), before)
        self.assertEqual(self.batch(), batch)
        self.save.assert_not_called()

    def test_output_security_and_stale_revisions(self):
        before = self.get_output()
        path = (self.base + "/settings/output?expected_revision=" +
                str(self.batch()["revision"]) + "&expected_settings_revision=" +
                str(before["settings_revision"]))
        values = {**before["values"], "save_text": True}
        for headers in (
            {}, self.read,
            {**self.write, "Origin": "https://outside.example"},
        ):
            response = self.client.patch(path, headers=headers, json=values)
            self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.get_output(), before)
        valid = self.client.patch(path, headers=self.write, json=values)
        self.assertEqual(valid.status_code, 200, valid.text)
        stale = self.client.patch(path, headers=self.write, json=values)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.get_output()["settings_revision"],
                         before["settings_revision"] + 1)
        self.assertEqual(self.save.call_count, 1)

    def test_reject_non_directory_ancestors_and_symlinks(self):
        directory = Path(self.tmp.name)
        regular_file = directory / "file-parent"
        regular_file.write_text("not a folder", encoding="utf-8")
        self.assertEqual(self.patch_output(
            output_dir=str(regular_file / "nested")).status_code, 422)
        self.assertEqual(self.patch_output(
            output_dir=str(regular_file)).status_code, 422)
        link = directory / "link"
        link.symlink_to(directory, target_is_directory=True)
        self.assertEqual(self.patch_output(output_dir=str(link)).status_code, 422)
        self.assertEqual(self.patch_output(
            output_dir=str(link / "nested")).status_code, 422)
        good = directory / "not-created" / "nested"
        self.assertEqual(self.patch_output(
            output_dir=str(good)).status_code, 200)
        self.assertFalse(good.exists())

    def test_preflight_failure_keeps_disk_settings_and_other_sessions(self):
        first = self.add()
        other_sid = self.client.post(
            "/api/web/sessions", headers=self.write,
        ).json()["id"]
        other_base = "/api/web/sessions/" + other_sid
        second = self.client.post(
            other_base + "/batch/items?expected_revision=0",
            json={"text": "さようなら"}, headers=self.write,
        )
        self.assertEqual(second.status_code, 200, second.text)
        second_item = self.service._sessions[other_sid].batch.items[0]
        before_first = self.batch()
        before_other = self.client.get(
            other_base + "/batch", headers=self.read,
        ).json()
        before_output = self.get_output()
        second_item.session.stage_output_settings = Mock(
            side_effect=ValueError("reference WAV was removed"),
        )
        response = self.patch_output(save_lab=True)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("reference WAV", response.text)
        self.save.assert_not_called()
        self.assertEqual(first.session.settings, self.initial)
        self.assertEqual(second_item.session.settings, self.initial)
        self.assertEqual(self.batch(), before_first)
        self.assertEqual(self.client.get(
            other_base + "/batch", headers=self.read,
        ).json(), before_other)
        self.assertEqual(self.get_output(), before_output)

    def test_real_partial_file_write_failure_rolls_back_output(self):
        from voiceger_editor.settings import save_settings as real_save_settings

        config = Path(self.tmp.name) / "settings" / "config.json"
        real_save_settings(self.initial, config_path=config)
        original_bytes = config.read_bytes()
        item = self.add()
        item.session.candidates.append(SimpleNamespace(
            number=1, frame_count=42, sampling_rate=16000,
            style_name="Neutral",
        ))
        item.mark_accepted(1)
        before_output = self.get_output()
        before_batch = self.batch()
        self.save.side_effect = lambda value: real_save_settings(
            value, config_path=config,
        )
        with patch("voiceger_editor.settings.os.fsync",
                   side_effect=OSError("simulated partial write")):
            response = self.patch_output(save_text=True)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertNotIn("simulated partial write", response.text)
        self.assertEqual(config.read_bytes(), original_bytes)
        self.assertEqual(list(config.parent.glob("*.tmp")), [])
        self.assertEqual(self.get_output(), before_output)
        self.assertEqual(self.batch(), before_batch)
        self.assertEqual(item.accepted_take_numbers, frozenset({1}))
        self.assertEqual(len(item.session.candidates), 1)

    def test_output_changes_propagate_to_multiple_live_sessions(self):
        first = self.add()
        other_sid = self.client.post(
            "/api/web/sessions", headers=self.write,
        ).json()["id"]
        other_base = "/api/web/sessions/" + other_sid
        response = self.client.post(
            other_base + "/batch/items?expected_revision=0",
            json={"text": "またね"}, headers=self.write,
        )
        self.assertEqual(response.status_code, 200, response.text)
        second = self.service._sessions[other_sid].batch.items[0]
        previous_other = self.client.get(
            other_base + "/batch", headers=self.read,
        ).json()["revision"]
        result = self.patch_output(
            output_format="flac", flac_encoding="pcm24",
            save_text=True, save_lab=True,
        )
        self.assertEqual(result.status_code, 200, result.text)
        for item in (first, second):
            self.assertEqual(item.session.settings.output_format, "flac")
            self.assertEqual(item.session.settings.flac_encoding, "pcm24")
            self.assertTrue(item.session.settings.save_text)
            self.assertTrue(item.session.settings.save_lab)
        after_other = self.client.get(
            other_base + "/batch", headers=self.read,
        ).json()["revision"]
        self.assertEqual(after_other, previous_other + 1)

    def test_real_browser_beforeunload_output_draft_guard(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required for browser unload regression")
        source = r"""
const fs=require("fs"),assert=require("assert").strict;
const js=fs.readFileSync(process.argv[1],"utf8");
const first=js.indexOf('  window.addEventListener("beforeunload",');
const last=js.indexOf("\\n  });",first);
assert(first>=0 && last>first,"production unload handler not found");
const handler=js.slice(first,last+"\n  });".length);
function fire(view,outputDirtyValue) {
  let callback=null;
  const win={addEventListener(name,fn){if(name==="beforeunload")callback=fn;}};
  new Function("window","currentView","commonDirty","defaultTakesDirty",
    "outputDirty","pronunciationDirty","sectionDirty",
    "dictionaryPronunciationDirty","dictionaryEntryDirty",handler)(
    win,view,()=>false,()=>false,()=>outputDirtyValue,
    ()=>false,()=>false,()=>false,()=>false);
  assert.equal(typeof callback,"function");
  let prevented=0;
  const e={returnValue:null,preventDefault(){prevented++;}};
  callback(e);
  return {prevented,returnValue:e.returnValue};
}
assert.deepEqual(fire("session",true),{prevented:1,returnValue:""});
assert.deepEqual(fire("session",false),{prevented:0,returnValue:null});
assert.deepEqual(fire("list",true),{prevented:0,returnValue:null});
console.log("OUTPUT_BEFOREUNLOAD_GUARD_PASS");
"""
        result = subprocess.run(
            [node, "-e", source, str(ASSETS / "app.js")],
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(result.returncode, 0,
                         result.stdout + "\n" + result.stderr)
        self.assertIn("OUTPUT_BEFOREUNLOAD_GUARD_PASS", result.stdout)

    def test_android_launcher_targets_actual_issue_branch(self):
        launcher = (ASSETS.parents[1] / "scripts" /
                    "run_web_e2e_329.py").read_text(encoding="utf-8")
        self.assertIn(
            'BRANCH = "sayosomi/issue-329-web-output"', launcher,
        )
        self.assertIn('SCRATCH = REPOSITORY / "scratch" / "issue329-e2e"',
                      launcher)

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
