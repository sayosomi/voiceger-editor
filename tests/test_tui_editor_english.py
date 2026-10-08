import unittest
from unittest.mock import Mock

from voiceger_editor.tui_editors import QueryApplicationResult, ReplaceQueryIntent, TuiEditorController
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.voicevox_api_models import AudioQuery, VoicegerSegment
from voiceger_editor.tui_editor_english import TuiEnglishEditorOwner
from tests.tui_editor_test_support import EditorControllerTestCase, mixed_query, segments


class TuiEnglishEditorOwnerTests(EditorControllerTestCase):
    def make_owner_controller(self, provider):
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
        controller = self.make_owner_controller(provider)
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
        controller = self.make_owner_controller(provider)
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

    def test_english_grouping_must_flatten_to_the_canonical_segment(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {"hello everyone": (("hello", ("HH", "AH1")),)}
        )

        rows = controller.pronunciation_rows(query, segments(query))

        self.assertEqual(len(rows), 2)
        self.assertIn("exactly match", controller.grouping_error)

    def test_main_english_stress_moves_only_selected_word_and_keeps_other_markers(self):
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(
                    language="en",
                    text="hello world",
                    phonemes=["HH", "AH1", "L", "OW2", "W", "ER1", "L", "D"],
                )
            ],
        )
        controller, _provider = self.make_controller(
            {
                "hello world": (
                    ("hello", ("HH", "AH1", "L", "OW2")),
                    ("world", ("W", "ER1", "L", "D")),
                )
            }
        )
        rows = controller.pronunciation_rows(query, (("en", "hello world", 0),))

        intents = controller.adjust_pronunciation(query, rows[0], 1)
        intent = next(item for item in intents if isinstance(item, ReplaceQueryIntent))

        self.assertEqual(
            intent.query.voicegerSegments[0].phonemes,
            ["HH", "AH2", "L", "OW1", "W", "ER1", "L", "D"],
        )
        self.assertEqual(
            intent.accepted_grouping.groups[1].phonemes,
            ("W", "ER1", "L", "D"),
        )
        self.assertEqual(query.voicegerSegments[0].phonemes[1], "AH1")

    def test_english_main_adjustment_preserves_cache_only_after_application(self):
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(
                    language="en",
                    text="hello world",
                    phonemes=["HH", "AH1", "L", "OW0", "W", "ER1", "L", "D"],
                )
            ],
        )
        groups = {
            "hello world": (
                ("hello", ("HH", "AH1", "L", "OW0")),
                ("world", ("W", "ER1", "L", "D")),
            )
        }
        controller, _provider = self.make_controller(groups)
        rows = controller.pronunciation_rows(query, (("en", "hello world", 0),))
        intent = next(
            item
            for item in controller.adjust_pronunciation(query, rows[0], 1)
            if isinstance(item, ReplaceQueryIntent)
        )
        self.assertEqual(controller.grouping_cache[0].groups[0].phonemes, groups["hello world"][0][1])
        controller.complete_query_application(intent, QueryApplicationResult())
        self.assertEqual(
            controller.grouping_cache[0].groups[0].phonemes,
            ("HH", "AH0", "L", "OW1"),
        )
        self.assertEqual(controller.grouping_cache[0].groups[1].phonemes, ("W", "ER1", "L", "D"))


if __name__ == "__main__":
    unittest.main()
