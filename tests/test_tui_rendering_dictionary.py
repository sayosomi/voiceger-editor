from types import SimpleNamespace
import unittest

from voiceger_editor.tui_rendering_dictionary import build_document
from voiceger_editor.tui_rendering_editor_common import EditorDocumentBuilder
from tests.tui_rendering_test_support import render_state


class DictionaryRenderingDocumentTests(unittest.TestCase):
    def test_dictionary_menu_owner(self):
        editor = SimpleNamespace(
            kind="dictionary_menu",
            title="DICTIONARY",
            selection="japanese",
            payload={"japanese_count": 3, "english_count": 2},
            active_field=None,
            input_value="",
            input_cursor=0,
            error="",
        )
        builder = EditorDocumentBuilder(render_state(editor=editor), 80)
        self.assertTrue(build_document(builder))
        self.assertTrue(any("3 words" in line for line, _key in builder.lines))
        self.assertTrue(any("2 words" in line for line, _key in builder.lines))


if __name__ == "__main__":
    unittest.main()
