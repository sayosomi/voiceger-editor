from types import SimpleNamespace
import unittest

from voiceger_editor.tui_rendering_editor_common import EditorDocumentBuilder
from voiceger_editor.tui_rendering_editor_general import build_document
from tests.tui_rendering_test_support import render_state


class GeneralEditorRenderingDocumentTests(unittest.TestCase):
    def test_caption_owner_builds_draft_and_actions(self):
        editor = SimpleNamespace(
            kind="caption",
            title="EDIT CAPTION",
            selection="draft",
            payload={"draft": "hello"},
            active_field=None,
            input_value="hello",
            input_cursor=5,
            error="",
        )
        builder = EditorDocumentBuilder(render_state(editor=editor), 80)

        self.assertTrue(build_document(builder))
        self.assertIn(("▶ hello", "draft"), builder.lines)
        self.assertTrue(any("[A] Apply" in line for line, _key in builder.lines))


if __name__ == "__main__":
    unittest.main()
