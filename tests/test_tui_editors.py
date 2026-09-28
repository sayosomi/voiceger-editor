import curses
from pathlib import Path
from types import SimpleNamespace
import unittest

from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui_editors import (
    AdjustmentPressedIntent,
    ApplySettingsIntent,
    CloseEditorIntent,
    EnglishWordGroup,
    QueryApplicationResult,
    ReplaceQueryIntent,
    ReplaceSourceTextIntent,
    SettingsApplicationResult,
    SettingsChanges,
    SourceTextApplicationResult,
    TuiEditorController,
    UpdateStatusIntent,
)
from voiceger_accent_adapter.tui_rendering import _active_input_prefix
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


def japanese_and_english_query(
    english_phonemes=("HH", "AY1"),
    *,
    english_text="Hi!",
):
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text="ア", vowel="a", vowel_length=0.1, pitch=0.0)],
                accent=1,
            )
        ],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="雨",
                accentPhraseStart=0,
                accentPhraseCount=1,
            ),
            VoicegerSegment(
                language="en",
                text=english_text,
                phonemes=list(english_phonemes),
            ),
        ],
    )


def english_query(phonemes=("HH", "AY1"), *, text="Hi!"):
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(
                language="en",
                text=text,
                phonemes=list(phonemes),
            )
        ],
    )


def segment_tuples(query):
    return [
        (segment.language, segment.text, index)
        for index, segment in enumerate(query.voicegerSegments or [])
    ]


class GroupProvider:
    def __init__(self, groups=None):
        self.groups = groups or {}
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return self.groups.get(text, ())


class TuiEditorControllerTests(unittest.TestCase):
    def make_controller(self, groups=None, styles=()):
        provider = GroupProvider(groups)
        controller = TuiEditorController(
            english_word_groups=provider,
            available_styles=lambda: styles,
            input_prefix=_active_input_prefix,
        )
        return controller, provider

    @staticmethod
    def settings():
        return Settings(output_dir=Path("/tmp/voiceger-editor-tests"))

    def test_open_text_starts_with_draft_field_active(self):
        controller, _provider = self.make_controller()
        intents = controller.open_text(
            "hello",
            current_source="old",
            origin=("text", None),
            busy=False,
        )
        self.assertEqual(controller.editor.kind, "text")
        self.assertEqual(controller.editor.active_field, "draft")
        self.assertEqual(controller.editor.input_value, "hello")
        self.assertEqual(controller.editor.input_cursor, 5)
        self.assertTrue(any(isinstance(intent, UpdateStatusIntent) for intent in intents))

    def test_text_editing_supports_cursor_insert_delete_and_backspace(self):
        controller, _provider = self.make_controller()
        controller.open_text(
            "abcd",
            current_source="abcd",
            origin=("text", None),
            busy=False,
        )
        editor = controller.editor
        controller.handle_key(
            curses.KEY_LEFT,
            settings=self.settings(),
            query=None,
            current_source="abcd",
        )
        controller.handle_key(
            "X",
            settings=self.settings(),
            query=None,
            current_source="abcd",
        )
        self.assertEqual(editor.input_value, "abcXd")
        controller.handle_key(
            curses.KEY_HOME,
            settings=self.settings(),
            query=None,
            current_source="abcd",
        )
        controller.handle_key(
            curses.KEY_DC,
            settings=self.settings(),
            query=None,
            current_source="abcd",
        )
        self.assertEqual(editor.input_value, "bcXd")
        controller.handle_key(
            curses.KEY_END,
            settings=self.settings(),
            query=None,
            current_source="abcd",
        )
        controller.handle_key(
            curses.KEY_BACKSPACE,
            settings=self.settings(),
            query=None,
            current_source="abcd",
        )
        self.assertEqual(editor.input_value, "bcX")

    def test_text_cursor_moves_vertically_across_wrapped_lines(self):
        controller, _provider = self.make_controller()
        controller.open_text(
            "abcdefghijklmnopqrstuvw",
            current_source=None,
            origin=("text", None),
            busy=False,
        )
        editor = controller.editor
        editor.input_cursor = 5
        controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(),
            query=None,
            current_source=None,
            screen_width=12,
        )
        self.assertEqual(editor.input_cursor, 7)
        controller.handle_key(
            curses.KEY_UP,
            settings=self.settings(),
            query=None,
            current_source=None,
            screen_width=12,
        )
        self.assertEqual(editor.input_cursor, 5)

    def test_active_text_field_keeps_shortcut_characters_as_text(self):
        controller, _provider = self.make_controller()
        controller.open_text(
            "draft",
            current_source="draft",
            origin=("text", None),
            busy=False,
        )
        editor = controller.editor
        for key in ("q", "?", "s", "x"):
            intents = controller.handle_key(
                key,
                settings=self.settings(),
                query=None,
                current_source="draft",
            )
            self.assertEqual(intents, ())
        self.assertEqual(editor.input_value, "draftq?sx")
        self.assertIs(controller.editor, editor)

    def test_text_cancel_closes_with_origin_and_apply_returns_source_intent(self):
        controller, _provider = self.make_controller()
        controller.open_text(
            "discard",
            current_source="old",
            origin=("text", None),
            busy=False,
        )
        canceled = controller.cancel()
        self.assertIsNone(controller.editor)
        self.assertIn(CloseEditorIntent(("text", None), "Text draft discarded."), canceled)

        controller.open_text(
            "new",
            current_source="old",
            origin=("text", None),
            busy=False,
        )
        intents = controller.apply(self.settings(), None, "old")
        self.assertEqual(intents, (ReplaceSourceTextIntent("new"),))
        self.assertIsNotNone(controller.editor)

    def test_unchanged_source_closes_and_success_or_failure_results_keep_exact_status(self):
        controller, _provider = self.make_controller()
        controller.open_text(
            "same",
            current_source="same",
            origin=("text", None),
            busy=False,
        )
        unchanged = controller.apply(self.settings(), None, "same")
        self.assertIn(
            CloseEditorIntent(("text", None), "Source text unchanged."),
            unchanged,
        )
        # Reopen to exercise application result handling.
        controller.open_text(
            "new",
            current_source="old",
            origin=("text", None),
            busy=False,
        )
        failed = controller.complete_source_text_application(
            SourceTextApplicationResult(error="source replacement failed")
        )
        self.assertEqual(controller.editor.error, "Error: Source text was not changed: source replacement failed")
        self.assertEqual(failed, ())
        success = controller.complete_source_text_application(
            SourceTextApplicationResult(needs_rebuild=True)
        )
        self.assertIn(
            CloseEditorIntent(
                ("text", None),
                "Source text updated; rebuild pronunciation before generating.",
            ),
            success,
        )

    def test_japanese_editor_open_cancel_and_valid_apply_intent(self):
        controller, _provider = self.make_controller()
        query = japanese_and_english_query()
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        self.assertEqual(controller.editor.kind, "japanese")
        self.assertEqual(controller.editor.active_field, "draft")
        canceled = controller.cancel()
        self.assertIn(
            CloseEditorIntent(
                ("segment", 0),
                "Japanese pronunciation draft discarded.",
            ),
            canceled,
        )

        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        controller.editor.payload["draft"] = "アメ'？"
        intents = controller.apply(self.settings(), query, "雨 Hi!")
        self.assertIsInstance(intents[0], ReplaceQueryIntent)
        self.assertEqual(intents[0].editor_kind, "japanese")
        completed = controller.complete_query_application(
            intents[0],
            QueryApplicationResult(),
        )
        self.assertIn(
            CloseEditorIntent(
                ("segment", 0),
                "Japanese pronunciation updated; old takes cleared.",
            ),
            completed,
        )

    def test_japanese_invalid_notation_keeps_editor_open_with_original_error(self):
        controller, _provider = self.make_controller()
        query = japanese_and_english_query()
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        editor = controller.editor
        editor.payload["draft"] = "not a pronunciation"
        intents = controller.apply(self.settings(), query, "雨 Hi!")
        self.assertEqual(intents, ())
        self.assertIs(controller.editor, editor)
        self.assertTrue(editor.error.startswith("Error: Pronunciation was not changed:"))

    def test_japanese_application_failure_preserves_existing_error_format(self):
        controller, _provider = self.make_controller()
        query = japanese_and_english_query()
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        intent = controller.apply(self.settings(), query, "雨 Hi!")[0]
        controller.complete_query_application(
            intent,
            QueryApplicationResult(error="session replacement failed"),
        )
        self.assertEqual(
            controller.editor.error,
            "Error: Pronunciation was not changed: session replacement failed",
        )

    def test_english_grouping_cache_reuses_and_invalidates_only_on_mismatch(self):
        groups = {"Hi!": (("Hi", ("HH", "AY1")), ("!", ("!",)))}
        controller, provider = self.make_controller(groups)
        query = english_query(("HH", "AY1", "!"))
        first = controller.english_grouping(query, 0)
        second = controller.english_grouping(query, 0)
        self.assertIs(first, second)
        self.assertEqual(provider.calls, ["Hi!"])
        query.voicegerSegments[0].phonemes = ["HH", "IH1", "!"]
        with self.assertRaisesRegex(ValueError, "do not exactly match"):
            controller.english_grouping(query, 0)
        self.assertNotIn(0, controller.grouping_cache)
        groups["Hi!"] = (("Hi", ("HH", "IH1")), ("!", ("!",)))
        replacement = controller.english_grouping(query, 0)
        self.assertEqual(replacement.flattened, ("HH", "IH1", "!"))
        self.assertEqual(provider.calls, ["Hi!", "Hi!", "Hi!"])

    def test_english_grouping_requires_exact_canonical_phoneme_match(self):
        controller, _provider = self.make_controller(
            {"Hi!": (("Hi", ("HH", "AY0")), ("!", ("!",)))}
        )
        with self.assertRaisesRegex(ValueError, "Voiceger word groups do not exactly match"):
            controller.english_grouping(english_query(("HH", "AY1", "!")), 0)

    def test_english_segment_opens_word_editor_and_done_commits_group_draft(self):
        controller, _provider = self.make_controller(
            {"Hi!": (("Hi", ("HH", "AY1")), ("!", ("!",)))}
        )
        query = english_query(("HH", "AY1", "!"))
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        parent = controller.editor
        self.assertEqual(parent.kind, "english_segment")
        self.assertEqual(parent.selection, ("word", 0))
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        word = controller.editor
        self.assertEqual(word.kind, "english_word")
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        word.input_value = "HH AA K"
        intents = controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        self.assertEqual(intents, (UpdateStatusIntent(
            "Phonemes updated in the word draft; Done returns it to the segment."
        ),))
        word.selection = "done"
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        self.assertIs(controller.editor, parent)
        self.assertEqual(parent.payload["groups"][0].phonemes, ("HH", "AA1", "K"))

    def test_english_word_cancel_discards_uncommitted_word_changes(self):
        controller, _provider = self.make_controller(
            {"Hi!": (("Hi", ("HH", "AY1")), ("!", ("!",)))}
        )
        query = english_query(("HH", "AY1", "!"))
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        parent = controller.editor
        original = parent.payload["groups"]
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        word = controller.editor
        controller.handle_key(
            "\x1b",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        self.assertIs(controller.editor, parent)
        self.assertEqual(parent.payload["groups"], original)

    def test_invalid_phoneme_replacement_keeps_word_editor_open(self):
        controller, _provider = self.make_controller(
            {"Hi!": (("Hi", ("HH", "AY1")), ("!", ("!",)))}
        )
        query = english_query(("HH", "AY1", "!"))
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        editor = controller.editor
        editor.input_value = "HH NOTAPHONEME"
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        self.assertIs(controller.editor, editor)
        self.assertTrue(editor.error.startswith("Error: unsupported English phoneme:"))

    def test_primary_stress_movement_preserves_secondary_stress(self):
        controller, _provider = self.make_controller(
            {"Hi!": (("Hi", ("AA1", "K", "IH2", "K", "EH0")), ("!", ("!",)))}
        )
        query = english_query(("AA1", "K", "IH2", "K", "EH0", "!"))
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        editor = controller.editor
        editor.selection = ("primary", 0)
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        controller.handle_key(
            curses.KEY_RIGHT,
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        controller.handle_key(
            curses.KEY_RIGHT,
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        self.assertEqual(
            editor.payload["draft_state"].primary_stress_vowel_positions,
            (2,),
        )
        self.assertEqual(
            editor.payload["draft_state"].secondary_stress_vowel_positions,
            (1,),
        )

    def test_primary_stress_collision_keeps_move_active_and_reports_error(self):
        controller, _provider = self.make_controller(
            {"Hi!": (("Hi", ("AA1", "IH1")), ("!", ("!",)))}
        )
        query = english_query(("AA1", "IH1", "!"))
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        editor = controller.editor
        editor.selection = ("primary", 0)
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        controller.handle_key(
            curses.KEY_RIGHT,
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_source="Hi!",
        )
        self.assertEqual(
            editor.error,
            "Error: That vowel already has primary stress. Choose another vowel.",
        )
        self.assertTrue(editor.payload["moving_primary"])

    def test_english_apply_intent_accepts_grouping_only_after_success(self):
        controller, _provider = self.make_controller(
            {"Hi!": (("Hi", ("HH", "AY1")), ("!", ("!",)))}
        )
        query = english_query(("HH", "AY1", "!"))
        controller.open_segment(
            query,
            segment_tuples(query),
            0,
            origin=("segment", 0),
            busy=False,
        )
        controller.editor.payload["groups"] = (
            EnglishWordGroup("Hi", ("HH", "AA1"), True),
            EnglishWordGroup("!", ("!",), False),
        )
        intent = controller.apply(self.settings(), query, "Hi!")[0]
        self.assertIsInstance(intent, ReplaceQueryIntent)
        self.assertEqual(
            controller.grouping_cache[0].flattened,
            ("HH", "AY1", "!"),
        )
        failed = controller.complete_query_application(
            intent,
            QueryApplicationResult(error="query replacement failed"),
        )
        self.assertEqual(failed, ())
        self.assertIsNotNone(controller.editor)
        self.assertEqual(
            controller.grouping_cache[0].flattened,
            ("HH", "AY1", "!"),
        )
        completed = controller.complete_query_application(
            intent,
            QueryApplicationResult(),
        )
        self.assertIn(
            CloseEditorIntent(
                ("segment", 0),
                "English pronunciation updated; old takes cleared.",
            ),
            completed,
        )
        self.assertEqual(
            controller.grouping_cache[0].flattened,
            ("HH", "AA1", "!"),
        )

    def test_settings_selection_editing_and_left_right_feedback(self):
        styles = (
            SimpleNamespace(id=1),
            SimpleNamespace(id=4),
            SimpleNamespace(id=7),
        )
        controller, _provider = self.make_controller(styles=styles)
        controller.open_settings(
            self.settings(),
            origin=("settings_summary", None),
            busy=False,
        )
        editor = controller.editor
        controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(),
            query=None,
            current_source=None,
        )
        self.assertEqual(editor.selection, "speed")
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=None,
            current_source=None,
        )
        self.assertEqual(editor.active_field, "speed")
        controller.handle_key(
            curses.KEY_END,
            settings=self.settings(),
            query=None,
            current_source=None,
        )
        controller.handle_key(
            "5",
            settings=self.settings(),
            query=None,
            current_source=None,
        )
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=None,
            current_source=None,
        )
        self.assertEqual(editor.payload["draft_settings"]["speed"], "1.05")
        self.assertEqual(editor.active_field, None)

        for selected, key, expected in (
            ("style_id", curses.KEY_RIGHT, "4"),
            ("speed", curses.KEY_RIGHT, "1.06"),
            ("take_count", curses.KEY_RIGHT, "5"),
            ("save_text", curses.KEY_RIGHT, True),
        ):
            editor.selection = selected
            intents = controller.handle_key(
                key,
                settings=self.settings(),
                query=None,
                current_source=None,
            )
            self.assertEqual(editor.payload["draft_settings"][selected], expected)
            self.assertIn(
                AdjustmentPressedIntent("settings", selected, 1),
                intents,
            )

    def test_settings_left_right_adjustment_reports_existing_validation_errors(self):
        controller, _provider = self.make_controller(
            styles=(SimpleNamespace(id=1),)
        )
        controller.open_settings(
            self.settings(),
            origin=("settings_summary", None),
            busy=False,
        )
        editor = controller.editor
        editor.selection = "speed"
        editor.payload["draft_settings"]["speed"] = "nan"
        intents = controller.handle_key(
            curses.KEY_RIGHT,
            settings=self.settings(),
            query=None,
            current_source=None,
        )
        self.assertIn("Error: Speed must be a positive finite number.", editor.error)
        self.assertEqual(intents, (AdjustmentPressedIntent("settings", "speed", 1),))

    def test_settings_apply_validation_errors_keep_draft_open(self):
        for field, invalid in (
            ("style_id", "0"),
            ("speed", "nan"),
            ("take_count", "0"),
            ("output_dir", "\x00"),
        ):
            with self.subTest(field=field):
                controller, _provider = self.make_controller()
                controller.open_settings(
                    self.settings(),
                    origin=("settings_summary", None),
                    busy=False,
                )
                editor = controller.editor
                editor.payload["draft_settings"][field] = invalid
                self.assertEqual(
                    controller.apply(self.settings(), None, None),
                    (),
                )
                self.assertIs(controller.editor, editor)
                self.assertTrue(editor.error.startswith("Error: Settings were not changed:"))

    def test_settings_unchanged_closes_and_changed_values_return_typed_intent(self):
        controller, _provider = self.make_controller()
        settings = self.settings()
        controller.open_settings(
            settings,
            origin=("settings_summary", None),
            busy=False,
        )
        unchanged = controller.apply(settings, None, None)
        self.assertIn(CloseEditorIntent(
            ("settings_summary", None),
            "Settings unchanged.",
        ), unchanged)

        controller.open_settings(
            settings,
            origin=("settings_summary", None),
            busy=False,
        )
        controller.editor.payload["draft_settings"]["speed"] = "1.25"
        changed = controller.apply(settings, None, None)
        self.assertEqual(
            changed,
            (ApplySettingsIntent(SettingsChanges(speed=1.25)),),
        )

    def test_settings_application_error_keeps_editor_and_success_closes(self):
        controller, _provider = self.make_controller()
        controller.open_settings(
            self.settings(),
            origin=("settings_summary", None),
            busy=False,
        )
        controller.editor.payload["draft_settings"]["take_count"] = "5"
        intent = controller.apply(self.settings(), None, None)[0]
        self.assertIsInstance(intent, ApplySettingsIntent)
        controller.complete_settings_application(
            SettingsApplicationResult(error_status="Error: Settings were not changed: bad")
        )
        self.assertEqual(
            controller.editor.error,
            "Error: Settings were not changed: bad",
        )
        closed = controller.complete_settings_application(SettingsApplicationResult())
        self.assertIn(
            CloseEditorIntent(
                ("settings_summary", None),
                "Settings saved. Existing temporary takes were cleared.",
            ),
            closed,
        )


if __name__ == "__main__":
    unittest.main()
