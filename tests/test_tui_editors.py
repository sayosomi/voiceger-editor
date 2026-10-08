import curses
import unittest

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import (
    AdjustmentPressedIntent,
    BuildPronunciationIntent,
    BuildPronunciationResult,
    ClearAdjustmentFeedbackIntent,
    ClearCandidatesIntent,
    CloseEditorIntent,
    EnglishWordGroup,
    EnglishGroupingCache,
    QueryApplicationResult,
    ReplaceQueryIntent,
    SettingsApplicationResult,
    adjustment_feedback_intents,
)
from voiceger_editor.voicevox_api_models import AudioQuery, VoicegerSegment
from tests.tui_editor_test_support import (
    EditorControllerTestCase,
    _phrase,
    mixed_query,
    segments,
)


class TuiEditorControllerTests(EditorControllerTestCase):
    def test_adjustment_feedback_helper_normalizes_shared_intents(self):
        self.assertEqual(
            adjustment_feedback_intents(changed=False),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(
            adjustment_feedback_intents(
                changed=True,
                area="dictionary",
                control="priority",
                direction=-3,
            ),
            (
                AdjustmentPressedIntent("dictionary", "priority", -1),
            ),
        )
        self.assertEqual(
            adjustment_feedback_intents(
                changed=True,
                area="settings",
                control="top_k",
                direction=7,
            ),
            (
                AdjustmentPressedIntent("settings", "top_k", 1),
            ),
        )
        with self.assertRaises(ValueError):
            adjustment_feedback_intents(changed=True)

    def test_editor_selection_movement_clamps_at_both_ends(self):
        controller, _provider = self.make_controller()
        controller.open_caption(
            "hello", current_caption="old", origin=("caption", None), busy=False
        )
        editor = controller.editor
        keys = controller.selection_keys()

        editor.selection = keys[0]
        self.assertEqual(controller.move_selection(-1), ())
        self.assertEqual(editor.selection, keys[0])

        editor.selection = keys[-1]
        self.assertEqual(controller.move_selection(1), ())
        self.assertEqual(editor.selection, keys[-1])

    def test_build_confirmation_has_typed_rebuild_cancel_and_atomic_completion(self):
        controller, _provider = self.make_controller()
        controller.open_build_confirmation(origin=("build_pronunciation", None))
        editor = controller.editor
        self.assertEqual(editor.title, "REBUILD PRONUNCIATION?")
        self.assertEqual(editor.selection, "cancel")
        self.assertIn("manual pronunciation or utterance edits", editor.payload["warning"].lower())
        self.assertEqual(
            controller.handle_key(
                "r", settings=self.settings(), query=None, current_caption="caption"
            ),
            (BuildPronunciationIntent(),),
        )
        self.assertEqual(
            controller.complete_build_confirmation(
                BuildPronunciationResult(error="analysis failed")
            ),
            (),
        )
        self.assertIs(controller.editor, editor)
        self.assertIn("analysis failed", editor.error)
        self.assertEqual(
            controller.complete_build_confirmation(BuildPronunciationResult()),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertIsNone(controller.editor)

    def test_build_confirmation_cancel_and_escape_close_without_build_intent(self):
        controller, _provider = self.make_controller()
        controller.open_build_confirmation(origin=("build_pronunciation", None))
        self.assertEqual(controller.editor.selection, "cancel")
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption="caption"
        )
        self.assertEqual(
            intents,
            (
                ClearAdjustmentFeedbackIntent(),
                CloseEditorIntent(
                    ("build_pronunciation", None), "Pronunciation rebuild cancelled."
                ),
            ),
        )
        self.assertIsNone(controller.editor)

        controller, _provider = self.make_controller()
        controller.open_build_confirmation(origin=("build_pronunciation", None))
        self.assertEqual(
            controller.handle_key(
                "\x1b",
                settings=self.settings(),
                query=None,
                current_caption="caption",
            ),
            (
                ClearAdjustmentFeedbackIntent(),
                CloseEditorIntent(
                    ("build_pronunciation", None),
                    "Pronunciation rebuild cancelled.",
                ),
            ),
        )
        self.assertIsNone(controller.editor)

    def test_cancel_and_success_close_restore_the_exact_origin(self):
        controller, _provider = self.make_controller()
        controller.open_caption(
            "draft", current_caption="old", origin=("pronunciation", 3), busy=False
        )
        close = controller.cancel()[1]
        self.assertEqual(close, CloseEditorIntent(("pronunciation", 3), "Caption draft discarded."))

        controller.open_settings(self.settings(), origin=("settings", None), busy=False)
        result = controller.complete_settings_application(SettingsApplicationResult())
        self.assertEqual(result[-1].origin, ("settings", None))
        self.assertEqual(result[-1].status, "Settings saved.")

    def test_english_section_apply_retains_unchanged_words_and_accepts_new_grouping(self):
        query = mixed_query()
        manual_hello = ("HH", "AH0", "L", "OW1")
        query.voicegerSegments[1].phonemes[:4] = manual_hello
        groups = {
            "hello everyone": (
                ("hello", ("HH", "AH1", "L", "OW2")),
                ("everyone", ("EH1", "V", "R", "IY0")),
            ),
            "very hello everyone": (
                ("very", ("V", "EH1", "R", "IY0")),
                ("hello", ("HH", "AH1", "L", "OW0")),
                ("everyone", ("EH1", "V", "R", "IY0")),
            ),
        }
        controller, _provider = self.make_controller(groups)
        controller.grouping_cache[1] = EnglishGroupingCache(
            "hello everyone",
            (
                EnglishWordGroup("hello", manual_hello, True),
                EnglishWordGroup("everyone", ("EH1", "V", "R", "IY0"), True),
            ),
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(5)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        section = controller.editor
        section.input_value = "very hello everyone"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(2)
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        replacement = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(replacement.query.voicegerSegments[1].text, "very hello everyone")
        self.assertEqual(replacement.query.voicegerSegments[1].phonemes[4:8], list(manual_hello))
        self.assertEqual(replacement.grouping_index, 1)
        controller.complete_query_application(replacement, QueryApplicationResult())
        self.assertEqual(controller.grouping_cache[1].source_text, "very hello everyone")
        self.assertEqual(controller.grouping_cache[1].groups[1].phonemes, manual_hello)

    def test_clear_candidates_confirmation_cancel_is_non_destructive(self):
        controller, _provider = self.make_controller()
        controller.open_clear_candidates_confirmation(origin=("clear_candidates", None))
        confirmation = controller.editor

        self.assertEqual(confirmation.title, "CLEAR CANDIDATES?")
        self.assertEqual(confirmation.selection, "cancel")
        self.assertIn("candidate WAV files will be discarded", confirmation.payload["warning"])
        canceled = controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption="Caption"
        )

        self.assertIsNone(controller.editor)
        self.assertFalse(any(isinstance(item, ClearCandidatesIntent) for item in canceled))
        self.assertIn(
            CloseEditorIntent(("clear_candidates", None), "Candidate clearing cancelled."),
            canceled,
        )

    def test_clear_candidates_confirmation_emits_application_intent_then_closes(self):
        controller, _provider = self.make_controller()
        controller.open_clear_candidates_confirmation(origin=("clear_candidates", None))

        confirmed = controller.handle_key(
            "c", settings=self.settings(), query=None, current_caption="Caption"
        )

        self.assertIsNone(controller.editor)
        self.assertIsInstance(confirmed[0], ClearCandidatesIntent)
        self.assertEqual(
            confirmed[-1],
            CloseEditorIntent(("clear_candidates", None), "Candidates cleared."),
        )

    def test_add_english_appends_and_installs_the_new_grouping_cache(self):
        query = mixed_query()
        groups = {
            "hello everyone": (
                ("hello", ("HH", "AH1", "L", "OW2")),
                ("everyone", ("EH1", "V", "R", "IY0")),
            ),
            "bright world": (
                ("bright", ("B", "R", "AY1", "T")),
                ("world", ("W", "ER0", "L", "D")),
            ),
        }
        controller, _provider = self.make_controller(groups)
        existing_grouping = controller.english_grouping(query, 1)
        controller.open_add_section(
            query,
            pure_japanese_utterance_text=None,
            origin=("add_section", None),
            busy=False,
        )
        editor = controller.editor
        editor.payload["language"] = "en"
        editor.input_value = "bright world"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(1)
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        addition = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(len(addition.query.voicegerSegments), 3)
        self.assertEqual(addition.query.voicegerSegments[2].text, "bright world")
        self.assertEqual(addition.grouping_index, 2)
        controller.complete_query_application(addition, QueryApplicationResult())
        self.assertIs(controller.grouping_cache[1], existing_grouping)
        self.assertEqual(controller.grouping_cache[2].source_text, "bright world")
        self.assertEqual(
            controller.grouping_cache[2].flattened,
            tuple(addition.query.voicegerSegments[2].phonemes),
        )

    def test_add_english_from_pure_japanese_preserves_manual_phrases_and_resets(self):
        query = AudioQuery(
            accent_phrases=[_phrase(("ア", "メ"), 1), _phrase(("キョ", "ウ"), 1)],
            kana="ア'メ/キョ'ウ？",
            speedScale=1.2,
        )
        original_phrases = [phrase.model_dump() for phrase in query.accent_phrases]
        groups = {"hello": (("hello", ("HH", "AH1", "L", "OW0")),)}
        controller, _provider = self.make_controller(groups)
        controller.open_add_section(
            query,
            pure_japanese_utterance_text="実際の日本語？",
            origin=("add_section", None),
            busy=False,
        )
        editor = controller.editor
        editor.input_value = "discarded"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(-1)
        controller.handle_key(
            curses.KEY_RIGHT,
            settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertEqual(editor.payload["language"], "en")
        controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        editor.input_value = "hello"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(1)
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        addition = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(len(addition.query.voicegerSegments), 2)
        self.assertEqual(addition.query.voicegerSegments[0].text, "実際の日本語？")
        self.assertEqual(addition.query.voicegerSegments[0].pronunciationTerminator, "？")
        self.assertEqual([p.model_dump() for p in addition.query.accent_phrases], original_phrases)
        self.assertEqual(addition.query.speedScale, 1.2)
        controller.complete_query_application(addition, QueryApplicationResult())
        self.assertEqual(controller.grouping_cache[1].source_text, "hello")

    def test_delete_remaps_later_english_grouping_caches(self):
        query = AudioQuery(
            accent_phrases=[_phrase(("ア",), 1)],
            voicegerSegments=[
                VoicegerSegment(language="ja", text="雨", accentPhraseStart=0, accentPhraseCount=1),
                VoicegerSegment(language="en", text="hello", phonemes=["HH", "AH1"]),
                VoicegerSegment(language="en", text="world", phonemes=["W", "ER0"]),
            ],
        )
        groups = {
            "hello": (("hello", ("HH", "AH1")),),
            "world": (("world", ("W", "ER0")),),
        }
        controller, _provider = self.make_controller(groups)
        rows = controller.pronunciation_rows(query, segments(query))
        controller.english_grouping(query, 1)
        controller.english_grouping(query, 2)
        world_grouping = controller.grouping_cache[2]
        controller.open_pronunciation_item(
            query, rows, 1, origin=("pronunciation", 1), busy=False
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(5)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(4)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        deletion = controller.handle_key(
            "d", settings=self.settings(), query=query, current_caption="Caption"
        )
        intent = next(item for item in deletion if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(intent.deleted_segment_index, 1)
        controller.complete_query_application(intent, QueryApplicationResult())
        self.assertEqual(set(controller.grouping_cache), {1})
        self.assertEqual(controller.grouping_cache[1], world_grouping)


if __name__ == "__main__":
    unittest.main()
