import unittest
from unittest.mock import Mock

from voiceger_editor.tui_editor_english import TuiEnglishEditorOwner
from voiceger_editor.tui_editors import TuiEditorController
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.voicevox_api_models import AudioQuery, VoicegerSegment


class TuiEnglishEditorOwnerTests(unittest.TestCase):
    def make_controller(self, provider):
        return TuiEditorController(
            english_word_groups=provider,
            available_styles=lambda: (),
            input_prefix=_active_input_prefix,
        )

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

    def test_source_change_rebuilds_grouping_from_matching_canonical_words(self):
        provider = Mock(return_value=(("Hi", ("HH", "AY1")),))
        controller = self.make_controller(provider)
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(
                    language="en",
                    text="Hi",
                    phonemes=["HH", "AY1"],
                )
            ],
        )

        self.assertEqual(controller.english_grouping(query, 0).source_text, "Hi")
        query.voicegerSegments[0].text = "Hello"
        provider.return_value = (("Hello", ("HH", "AY1")),)

        grouping = controller.english_grouping(query, 0)

        self.assertEqual(grouping.source_text, "Hello")
        self.assertEqual(provider.call_count, 2)

    def test_reconcile_drops_cache_when_canonical_flat_phonemes_change(self):
        provider = Mock(return_value=(("Hi", ("HH", "AY1")),))
        controller = self.make_controller(provider)
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(
                    language="en",
                    text="Hi",
                    phonemes=["HH", "AY1"],
                )
            ],
        )
        controller.english_grouping(query, 0)
        updated = query.model_copy(deep=True)
        updated.voicegerSegments[0].phonemes = ["HH", "AA1"]

        controller.reconcile_groupings(updated)

        self.assertNotIn(0, controller.grouping_cache)


if __name__ == "__main__":
    unittest.main()
