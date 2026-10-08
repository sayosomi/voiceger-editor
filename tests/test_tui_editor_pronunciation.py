from pathlib import Path
import unittest

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editor_pronunciation import TuiPronunciationEditorOwner
from voiceger_editor.tui_editors import TuiEditorController
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.voicevox_api_models import AccentPhrase, AudioQuery, Mora


def _phrase():
    return AccentPhrase(
        moras=[Mora(text="ナ", vowel="a", vowel_length=0.1, pitch=0.0)],
        accent=1,
    )


class TuiPronunciationEditorOwnerTests(unittest.TestCase):
    def test_pronunciation_policy_is_delegated_from_facade(self):
        controller = TuiEditorController(
            english_word_groups=lambda _text: (),
            available_styles=lambda: (),
            input_prefix=_active_input_prefix,
        )
        self.assertIsInstance(
            controller._pronunciation,
            TuiPronunciationEditorOwner,
        )
        query = AudioQuery(accent_phrases=[_phrase()], kana="ナ'")
        rows = controller.pronunciation_rows(
            query,
            (("ja", "な", None),),
        )
        controller.open_pronunciation_item(
            query,
            rows,
            0,
            origin=("pronunciation", 0),
            busy=False,
        )

        controller.handle_key(
            "/",
            settings=Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            query=query,
            current_caption="な",
        )

        self.assertEqual(controller.editor.kind, "japanese")
        self.assertIn("Use spaces for phrase boundaries", str(controller.editor.error))


if __name__ == "__main__":
    unittest.main()
