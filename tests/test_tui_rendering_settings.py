from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_editor.tui_rendering_editor_common import EditorDocumentBuilder
from voiceger_editor.tui_rendering_settings import build_document

from tests.tui_rendering_test_support import render_state


class SettingsRenderingDocumentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
