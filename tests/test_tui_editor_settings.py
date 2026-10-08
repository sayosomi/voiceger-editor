from pathlib import Path
import curses
import unittest

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editor_settings import TuiSettingsEditorOwner
from voiceger_editor.tui_editors import TuiEditorController
from voiceger_editor.tui_rendering import _active_input_prefix


class TuiSettingsEditorOwnerTests(unittest.TestCase):
    def make_controller(self):
        return TuiEditorController(
            english_word_groups=lambda _text: (),
            available_styles=lambda: (),
            input_prefix=_active_input_prefix,
        )

    def test_settings_owner_holds_adjustment_policy_behind_facade(self):
        controller = self.make_controller()
        self.assertIsInstance(controller._settings, TuiSettingsEditorOwner)
        controller.open_settings(
            Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            origin=("settings", None),
            busy=False,
        )
        controller.editor.selection = "top_k"
        before = controller.editor.payload["draft_settings"]["top_k"]

        controller.handle_key(
            curses.KEY_RIGHT,
            settings=Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            query=None,
            current_caption=None,
        )

        self.assertNotEqual(
            controller.editor.payload["draft_settings"]["top_k"],
            before,
        )


if __name__ == "__main__":
    unittest.main()
