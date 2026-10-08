import unittest

from voiceger_editor.tui_editor_english import TuiEnglishEditorOwner
from voiceger_editor.tui_editors import TuiEditorController
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.voicevox_api_models import AudioQuery, VoicegerSegment


class TuiEnglishEditorOwnerTests(unittest.TestCase):
    def test_grouping_cache_has_one_focused_owner(self):
        controller = TuiEditorController(
            english_word_groups=lambda _text: (("hello", ("HH", "AH1")),),
            available_styles=lambda: (),
            input_prefix=_active_input_prefix,
        )
        self.assertIsInstance(controller._english, TuiEnglishEditorOwner)
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(
                    language="en",
                    text="hello",
                    phonemes=["HH", "AH1"],
                )
            ],
        )

        grouping = controller.english_grouping(query, 0)

        self.assertIs(
            controller.grouping_cache,
            controller._english.grouping_cache,
        )
        self.assertIs(controller.grouping_cache[0], grouping)
        controller.clear_groupings()
        self.assertEqual(controller.grouping_cache, {})


if __name__ == "__main__":
    unittest.main()
