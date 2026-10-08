from pathlib import Path
from tests.tui_rendering_test_support import RenderingTestCase, render_state

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_editor.tui_rendering_editor_common import EditorDocumentBuilder
from voiceger_editor.tui_rendering_settings import build_document



class SettingsRenderingDocumentTests(RenderingTestCase):
    def test_settings_owner_builds_settings_rows(self):
        editor = SimpleNamespace(
            kind="settings",
            title="SETTINGS",
            selection="style_id",
            payload={
                "draft_settings": {
                    "style_id": 1,
                    "speed": 1.0,
                    "take_count": 4,
                    "output_dir": "/tmp/output",
                }
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
        )
        builder = EditorDocumentBuilder(render_state(editor=editor), 80)

        with patch(
            "voiceger_editor.tui_rendering_shared.available_styles",
            return_value=(),
        ):
            handled = build_document(builder)

        self.assertTrue(handled)
        self.assertTrue(any("Style" in line for line, _key in builder.lines))
        self.assertTrue(any("[A] Apply" in line for line, _key in builder.lines))

    def test_settings_use_sections_shortcuts_and_candidate_clearing_markers(self):
        editor = SimpleNamespace(
            kind="settings", title="EDIT SETTINGS", selection="speed",
            payload={"draft_settings": {
                "style_id": "3", "speed": "1.00", "take_count": "4",
                "output_dir": "/tmp/output", "save_text": True,
            }},
            active_field=None, input_value="", input_cursor=0, error="", scroll=0,
        )
        with patch(
            "voiceger_editor.tui_rendering_shared.available_styles",
            return_value=(SimpleNamespace(id=3, name="Neutral"),),
        ):
            document, _, _ = self.renderer.editor_document(render_state(editor=editor), 80)
        visible = "\n".join(line for line, _key in document)

        for heading in ("Voice", "Generation", "Output", "Sampling", "Actions"):
            self.assertIn(heading, visible)
        for marked in (
            "[S] Style *", "[V] Speed *", "[K] Top K *",
            "[P] Top P *", "[T] Temperature *",
        ):
            self.assertIn(marked, visible)
        for unmarked in ("[N] Takes", "[F] Output", "[O] File format & naming"):
            self.assertIn(unmarked, visible)
        self.assertNotIn("[X] TXT", visible)
        self.assertNotIn("[L] LAB", visible)
        self.assertIn("[D] Reset sampling to Voiceger defaults", visible)
        self.assertIn("[A] Apply and save", visible)
        self.assertIn("[R] Reset", visible)
        self.assertIn("[Esc] Back", visible)
        self.assertIn(
            "* Applying this setting clears existing candidates.",
            visible,
        )
        self.assertEqual(
            [key for _line, key in document if key is not None],
            [
                "style_id", "speed", "take_count", "output_dir", "audio_output",
                "top_k", "top_p", "temperature", "reset_sampling",
                "apply", "reset", "back",
            ],
        )
        self.assertNotIn("input:", visible)

        editor.active_field = "speed"
        editor.input_value = "1.25"
        editor.input_cursor = 4
        with patch(
            "voiceger_editor.tui_rendering_shared.available_styles",
            return_value=(SimpleNamespace(id=3, name="Neutral"),),
        ):
            active, _, _ = self.renderer.editor_document(render_state(editor=editor), 80)
        speed_lines = [line for line, key in active if key == "speed"]
        self.assertTrue(any(line.startswith("▶ Speed *") and "1.25" in line for line in speed_lines))

    def test_audio_output_settings_render_draft_preview_and_sidecars(self):
        editor = SimpleNamespace(
            kind="audio_output_settings",
            title="AUDIO OUTPUT",
            selection="output_format",
            payload={
                "draft_settings": {
                    "output_format": "wav",
                    "wav_encoding": "source",
                    "flac_encoding": "pcm16",
                    "filename_template": "{style}_{text}",
                    "save_text": True,
                    "save_lab": False,
                },
                "preview_text": "今日は雨",
                "preview_style": "Neutral",
                "filename_preview": "Neutral_今日は雨.wav",
                "filename_preview_error": "",
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _, _ = self.renderer.editor_document(
            render_state(editor=editor),
            80,
        )
        visible = "\n".join(line for line, _key in document)
        self.assertIn("AUDIO OUTPUT", visible)
        self.assertIn("Format", visible)
        self.assertIn("< WAV >", visible)
        self.assertIn("Encoding", visible)
        self.assertIn("< Source >", visible)
        self.assertIn("Filename template  {style}_{text}", visible)
        self.assertIn("Preview", visible)
        self.assertIn("Neutral_今日は雨.wav", visible)
        self.assertIn("[X] TXT", visible)
        self.assertIn("ON", visible)
        self.assertIn("[L] LAB", visible)
        self.assertIn("OFF", visible)
        self.assertIn("YYYY MM DD HH mm ss · {text} {style}", visible)
        self.assertEqual(
            [key for _line, key in document if key is not None],
            [
                "output_format", "output_encoding", "filename_template",
                "save_text", "save_lab", "back",
            ],
        )

    def test_audio_output_renders_flac_specific_encoding(self):
        editor = SimpleNamespace(
            kind="audio_output_settings",
            title="AUDIO OUTPUT",
            selection="output_encoding",
            payload={
                "draft_settings": {
                    "output_format": "flac",
                    "wav_encoding": "float32",
                    "flac_encoding": "pcm24",
                    "filename_template": "{text}",
                    "save_text": False,
                    "save_lab": False,
                },
                "filename_preview": "sample.flac",
                "filename_preview_error": "",
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _, _ = self.renderer.editor_document(
            render_state(editor=editor),
            80,
        )
        visible = "\n".join(line for line, _key in document)
        self.assertIn("< FLAC >", visible)
        self.assertIn("< PCM 24-bit >", visible)
        self.assertNotIn("Float 32-bit", visible)

    def test_audio_output_renders_mp3_bitrate_without_encoding_row(self):
        editor = SimpleNamespace(
            kind="audio_output_settings",
            title="AUDIO OUTPUT",
            selection="mp3_bitrate",
            payload={
                "draft_settings": {
                    "output_format": "mp3",
                    "wav_encoding": "source",
                    "flac_encoding": "pcm16",
                    "mp3_bitrate": "256k",
                    "filename_template": "{text}",
                    "save_text": False,
                    "save_lab": False,
                },
                "filename_preview": "sample.mp3",
                "filename_preview_error": "",
            },
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
            scroll=0,
        )

        document, _, _ = self.renderer.editor_document(
            render_state(editor=editor),
            80,
        )
        visible = "\n".join(line for line, _key in document)
        self.assertIn("< MP3 >", visible)
        self.assertIn("Bitrate", visible)
        self.assertIn("< 256 kbps >", visible)
        self.assertNotIn("Encoding", visible)
        self.assertEqual(
            [key for _line, key in document if key is not None],
            [
                "output_format", "mp3_bitrate", "filename_template",
                "save_text", "save_lab", "back",
            ],
        )

    def test_audio_output_preview_uses_live_template_draft_and_explains_invalid_input(self):
        editor = SimpleNamespace(
            kind="audio_output_settings",
            title="AUDIO OUTPUT",
            selection="filename_template",
            payload={
                "draft_settings": {
                    "output_format": "flac",
                    "wav_encoding": "source",
                    "flac_encoding": "pcm24",
                    "filename_template": "{text}",
                    "save_text": False,
                    "save_lab": False,
                },
                "preview_text": "sample",
                "preview_style": "Neutral",
                "filename_preview": "",
                "filename_preview_error": "unsupported date/time token in {take}",
            },
            active_field="filename_template",
            input_value="{take}_{text}",
            input_cursor=len("{take}_{text}"),
            error="",
            scroll=0,
        )

        document, cursor_line, _ = self.renderer.editor_document(
            render_state(editor=editor),
            80,
        )
        visible = "\n".join(line for line, _key in document)
        self.assertIn("▶ Filename template  {take}_{text}", visible)
        self.assertIn("Invalid:", visible)
        self.assertIn("unsupported date/time token", visible)
        self.assertIsNotNone(cursor_line)

    def test_settings_style_display_falls_back_to_id_when_unresolved(self):
        editor = SimpleNamespace(
            kind="settings", title="EDIT SETTINGS", selection="style_id",
            payload={"draft_settings": {
                "style_id": "19", "speed": "1.00", "take_count": "4",
                "output_dir": "/tmp/output", "save_text": False,
            }},
            active_field=None, input_value="", input_cursor=0, error="", scroll=0,
        )
        with patch(
            "voiceger_editor.tui_rendering_shared.available_styles",
            return_value=(),
        ):
            document, _, _ = self.renderer.editor_document(
                render_state(editor=editor), 80
            )
        self.assertIn("▶ [S] Style *", "\n".join(line for line, _key in document))

        with patch(
            "voiceger_editor.tui_rendering_shared.available_styles",
            side_effect=RuntimeError("styles unavailable"),
        ):
            value = self.renderer.setting_display("style_id", "19", Path("/missing"))
        self.assertEqual(value, "19")

if __name__ == "__main__":
    unittest.main()
