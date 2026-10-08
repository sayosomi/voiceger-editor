from pathlib import Path
import unittest

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editor_common import ApplyCaptionIntent
from voiceger_editor.tui_editor_text import TuiTextEditorOwner
from voiceger_editor.tui_editors import TuiEditorController
from voiceger_editor.tui_rendering import _active_input_prefix


class TuiTextEditorOwnerTests(unittest.TestCase):
    def test_caption_draft_and_apply_are_owned_behind_facade(self):
        controller = TuiEditorController(
            english_word_groups=lambda _text: (),
            available_styles=lambda: (),
            input_prefix=_active_input_prefix,
        )
        self.assertIsInstance(controller._text, TuiTextEditorOwner)
        controller.open_caption(
            "opening",
            current_caption="opening",
            origin=("caption", None),
            busy=False,
        )
        controller.editor.input_value = "changed"
        controller.handle_key(
            "\n",
            settings=Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            query=None,
            current_caption="opening",
        )
        controller.move_selection(1)

        intents = controller.handle_key(
            "\n",
            settings=Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            query=None,
            current_caption="opening",
        )

        self.assertTrue(any(isinstance(item, ApplyCaptionIntent) for item in intents))


if __name__ == "__main__":
    unittest.main()
