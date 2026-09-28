import curses
from pathlib import Path
import unittest

from voiceger_accent_adapter.english_stress import (
    english_phonemes_to_editor_state,
)
from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui_editors import (
    AdjustmentPressedIntent,
    ApplySettingsIntent,
    ClearAdjustmentFeedbackIntent,
    CloseEditorIntent,
    EnglishWordGroup,
    EnglishGroupingCache,
    PronunciationRow,
    QueryApplicationResult,
    ReplaceQueryIntent,
    ReplaceSourceTextIntent,
    SettingsApplicationResult,
    TuiEditorController,
    UpdateStatusIntent,
)
from voiceger_accent_adapter.tui_rendering import _active_input_prefix
from voiceger_accent_adapter.query_editing import japanese_pronunciation
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


def _phrase(morae, accent):
    return AccentPhrase(
        moras=[
            Mora(text=mora, vowel="a", vowel_length=0.1, pitch=0.0)
            for mora in morae
        ],
        accent=accent,
    )


def mixed_query():
    return AudioQuery(
        accent_phrases=[
            _phrase(("ア", "シ", "タ", "ワ"), 4),
            _phrase(("キョ", "ウ"), 1),
        ],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="明日は今日",
                accentPhraseStart=0,
                accentPhraseCount=2,
                pronunciationTerminator="？",
            ),
            VoicegerSegment(
                language="en",
                text="hello everyone",
                phonemes=["HH", "AH1", "L", "OW2", "EH1", "V", "R", "IY0"],
            ),
        ],
    )


def direct_japanese_query():
    return AudioQuery(
        accent_phrases=[_phrase(("ナ",), 1), _phrase(("ノ", "ダ"), 2)],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="なのだ。",
                accentPhraseStart=0,
                accentPhraseCount=2,
                pronunciationTerminator="。",
            ),
            VoicegerSegment(
                language="en",
                text="hello",
                phonemes=["HH", "AH1"],
            ),
        ],
    )


def segments(query):
    return [
        (item.language, item.text, index)
        for index, item in enumerate(query.voicegerSegments or [])
    ]


class GroupProvider:
    def __init__(self, groups):
        self.groups = groups
        self.calls = []

    def __call__(self, source):
        self.calls.append(source)
        return self.groups[source]


class TuiEditorControllerTests(unittest.TestCase):
    def make_controller(self, groups=None, styles=()):
        provider = GroupProvider(groups or {})
        controller = TuiEditorController(
            english_word_groups=provider,
            available_styles=lambda: styles,
            input_prefix=_active_input_prefix,
        )
        return controller, provider

    @staticmethod
    def settings():
        return Settings(output_dir=Path("/tmp/voiceger-editor-tests"))

    def test_text_editor_opens_on_input_and_returns_a_source_intent(self):
        controller, _provider = self.make_controller()
        controller.open_text(
            "hello", current_source="old", origin=("text", None), busy=False
        )
        editor = controller.editor
        self.assertEqual(editor.active_field, "draft")
        self.assertEqual(editor.input_value, "hello")
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=None, current_source="old"
            ),
            (ReplaceSourceTextIntent("hello"),),
        )

    def test_pronunciation_rows_are_one_per_phrase_and_english_word(self):
        groups = {
            "hello everyone": (
                ("hello", ("HH", "AH1", "L", "OW2")),
                ("everyone", ("EH1", "V", "R", "IY0")),
            )
        }
        controller, provider = self.make_controller(groups)
        rows = controller.pronunciation_rows(mixed_query(), segments(mixed_query()))

        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [(row.language, row.phrase_index, row.word) for row in rows],
            [("ja", 0, None), ("ja", 1, None), ("en", None, "hello"), ("en", None, "everyone")],
        )
        self.assertEqual([row.first_in_segment for row in rows], [True, False, True, False])
        self.assertEqual(rows[0].moras, ("ア", "シ", "タ", "ワ"))
        self.assertEqual(rows[1].moras, ("キョ", "ウ"))
        self.assertEqual(rows[2].phonemes, ("HH", "AH1", "L", "OW2"))
        self.assertEqual(provider.calls, ["hello everyone"])

    def test_english_grouping_must_flatten_to_the_canonical_segment(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {"hello everyone": (("hello", ("HH", "AH1")),)}
        )

        rows = controller.pronunciation_rows(query, segments(query))

        self.assertEqual(len(rows), 2)
        self.assertIn("exactly match", controller.grouping_error)

    def test_main_japanese_accent_moves_one_mora_and_boundary_is_a_noop(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {"hello everyone": (("hello", ("HH", "AH1", "L", "OW2", "EH1", "V", "R", "IY0")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))

        blocked = controller.adjust_pronunciation(query, rows[0], 1)
        self.assertEqual(blocked, (ClearAdjustmentFeedbackIntent(),))

        moved = controller.adjust_pronunciation(query, rows[1], 1)
        intent = next(item for item in moved if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(intent.query.accent_phrases[1].accent, 2)

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
            ["HH", "AH0", "L", "OW1", "W", "ER1", "L", "D"],
        )
        self.assertEqual(
            intent.accepted_grouping.groups[1].phonemes,
            ("W", "ER1", "L", "D"),
        )
        self.assertEqual(query.voicegerSegments[0].phonemes[1], "AH1")

    def test_japanese_child_opens_whole_segment_as_active_direct_notation(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller({"hello": (("hello", ("HH", "AH1")),)})
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query,
            rows,
            1,
            origin=("pronunciation", 1),
            busy=False,
        )
        editor = controller.editor
        self.assertEqual(editor.kind, "japanese")
        self.assertEqual(editor.title, "EDIT JAPANESE PRONUNCIATION")
        self.assertEqual(editor.selection, "pronunciation")
        self.assertEqual(editor.active_field, "pronunciation")
        self.assertEqual(editor.payload["source_text"], "なのだ。")
        self.assertEqual(editor.payload["canonical_pronunciation"], "ナ'/ノダ'。")
        self.assertEqual(editor.input_value, "ナ' ノダ'。")
        self.assertEqual(editor.input_original, "ナ' ノダ'。")
        self.assertNotIn("/", editor.input_value)
        self.assertNotIn("editing_morae", editor.payload)
        self.assertNotIn("editing_accent", editor.payload)
        self.assertNotIn("mora_cursor", editor.payload)

    def test_japanese_direct_field_uses_character_cursor_and_text_edits(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller({"hello": (("hello", ("HH", "AH1")),)})
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )

        def press(key):
            controller.handle_key(
                key, settings=self.settings(), query=query, current_source="source"
            )

        editor = controller.editor
        press(curses.KEY_HOME)
        self.assertEqual(editor.input_cursor, 0)
        press(curses.KEY_RIGHT)
        press("X")
        self.assertEqual(editor.input_value, "ナX' ノダ'。")
        self.assertEqual(editor.input_cursor, 2)
        press(curses.KEY_BACKSPACE)
        self.assertEqual(editor.input_value, "ナ' ノダ'。")
        press(curses.KEY_HOME)
        press(curses.KEY_RIGHT)
        press(curses.KEY_DC)
        self.assertEqual(editor.input_value, "ナ ノダ'。")
        self.assertEqual(editor.input_cursor, 1)
        press(curses.KEY_END)
        self.assertEqual(editor.input_cursor, len(editor.input_value))
        press(curses.KEY_LEFT)
        self.assertEqual(editor.input_cursor, len(editor.input_value) - 1)
        self.assertNotIn("editing_morae", editor.payload)
        self.assertNotIn("mora_cursor", editor.payload)

    def test_unchanged_japanese_direct_field_closes_without_replacing_query(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller({"hello": (("hello", ("HH", "AH1")),)})
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )

        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_source="source"
        )

        close_intent = next(
            intent for intent in intents if isinstance(intent, CloseEditorIntent)
        )
        self.assertEqual(close_intent.status, "Japanese pronunciation unchanged.")
        self.assertIsNone(controller.editor)

    def test_japanese_direct_field_rejects_slash_and_explains_space_boundaries(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller({"hello": (("hello", ("HH", "AH1")),)})
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        editor = controller.editor
        original = editor.input_value

        controller.handle_key(
            "/", settings=self.settings(), query=query, current_source="source"
        )

        self.assertEqual(editor.input_value, original)
        self.assertIn("Use spaces for phrase boundaries", editor.error)
        self.assertIn("not used in this editor", editor.error)
        self.assertNotIn("ASCII", editor.error)
        self.assertIn("phrase boundaries", editor.error)
        self.assertNotIn("/", editor.input_value)

    def test_full_width_space_is_ordinary_input_and_boundary_only_change_is_unchanged(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        editor = controller.editor
        editor.input_cursor = 2
        controller.handle_key(
            curses.KEY_DC, settings=self.settings(), query=query, current_source="source"
        )
        controller.handle_key(
            "　", settings=self.settings(), query=query, current_source="source"
        )

        self.assertEqual(editor.input_value, "ナ'　ノダ'。")
        self.assertEqual(editor.error, "")
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_source="source"
        )
        self.assertEqual(
            intents,
            (
                ClearAdjustmentFeedbackIntent(),
                CloseEditorIntent(
                    ("pronunciation", 0), "Japanese pronunciation unchanged."
                ),
            ),
        )

    def test_ascii_full_width_and_mixed_spaces_share_canonical_phrase_boundaries(self):
        expected = "ナ'/ノダ'/カ'！"
        notations = ("ナ' ノダ' カ'！", "ナ'　ノダ'　カ'！", "ナ'　ノダ' カ'！")
        for notation in notations:
            with self.subTest(notation=notation):
                query = direct_japanese_query()
                query.accent_phrases.append(_phrase(("カ",), 1))
                query.voicegerSegments[0].accentPhraseCount = 3
                controller, _provider = self.make_controller(
                    {"hello": (("hello", ("HH", "AH1")),)}
                )
                rows = controller.pronunciation_rows(query, segments(query))
                controller.open_pronunciation_item(
                    query, rows, 0, origin=("pronunciation", 0), busy=False
                )
                controller.editor.input_value = notation

                intents = controller.apply(
                    self.settings(), query=query, current_source="source"
                )

                replacement = next(
                    intent for intent in intents if isinstance(intent, ReplaceQueryIntent)
                )
                self.assertEqual(
                    japanese_pronunciation(replacement.query, segment_index=0),
                    expected,
                )
                self.assertEqual(
                    replacement.query.voicegerSegments[0].accentPhraseCount, 3
                )
                self.assertEqual(
                    replacement.query.voicegerSegments[0].pronunciationTerminator,
                    "！",
                )

    def test_english_word_opens_directly_and_phoneme_edit_commits_to_query(self):
        query = mixed_query()
        groups = {
            "hello everyone": (
                ("hello", ("HH", "AH1", "L", "OW2")),
                ("everyone", ("EH1", "V", "R", "IY0")),
            )
        }
        controller, _provider = self.make_controller(groups)
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query,
            rows,
            2,
            origin=("pronunciation", 2),
            busy=False,
        )
        editor = controller.editor
        self.assertEqual(editor.kind, "english_word")
        self.assertEqual(editor.title, "EDIT WORD PRONUNCIATION")
        self.assertNotIn("english_segment", editor.kind)
        self.assertEqual(editor.payload["label"], "hello")
        self.assertEqual(controller.selection_keys(), ["phonemes"])

        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_source="source"
        )
        editor.input_value = "HH AE L OW"
        editor.input_cursor = len(editor.input_value)
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_source="source"
        )
        replacement = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(
            replacement.query.voicegerSegments[1].phonemes[:4],
            ["HH", "AE1", "L", "OW2"],
        )
        completed = controller.complete_query_application(
            replacement, QueryApplicationResult()
        )
        self.assertEqual(completed[-1], CloseEditorIntent(("pronunciation", 2), replacement.success_status))
        self.assertEqual(controller.grouping_cache[1].groups[0].phonemes, ("HH", "AE1", "L", "OW2"))
        self.assertIsNone(controller.editor)

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

    def test_settings_keep_draft_apply_semantics_and_emit_movement_feedback(self):
        styles = (
            type("Style", (), {"id": 1, "name": "Neutral"})(),
            type("Style", (), {"id": 2, "name": "Sweet"})(),
        )
        controller, _provider = self.make_controller(styles=styles)
        controller.open_settings(
            self.settings(), origin=("settings", None), busy=False
        )
        self.assertEqual(controller.editor.selection, "style_id")
        self.assertEqual(controller.adjust_settings(-1), (ClearAdjustmentFeedbackIntent(),))
        self.assertEqual(controller.adjust_settings(1), (AdjustmentPressedIntent("settings", "style_id", 1),))
        self.assertEqual(controller.editor.payload["draft_settings"]["style_id"], "2")
        controller.editor.selection = "apply"
        intent = controller._activate_selection(self.settings(), None, None)[0]
        self.assertIsInstance(intent, ApplySettingsIntent)
        self.assertEqual(intent.changes.style_id, 2)

    def test_settings_field_edits_remain_on_the_same_selection_row(self):
        controller, _provider = self.make_controller()
        controller.open_settings(
            self.settings(), origin=("settings", None), busy=False,
            selected_field="output_dir", edit=True,
        )
        self.assertEqual(controller.editor.selection, "output_dir")
        self.assertEqual(controller.editor.active_field, "output_dir")
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=None, current_source=None
            ),
            (UpdateStatusIntent(""),),
        )
        self.assertEqual(controller.editor.selection, "output_dir")
        self.assertIsNone(controller.editor.active_field)

    def test_cancel_and_success_close_restore_the_exact_origin(self):
        controller, _provider = self.make_controller()
        controller.open_text(
            "draft", current_source="old", origin=("pronunciation", 3), busy=False
        )
        close = controller.cancel()[1]
        self.assertEqual(close, CloseEditorIntent(("pronunciation", 3), "Text draft discarded."))

        controller.open_settings(self.settings(), origin=("settings", None), busy=False)
        result = controller.complete_settings_application(SettingsApplicationResult())
        self.assertEqual(result[-1].origin, ("settings", None))


if __name__ == "__main__":
    unittest.main()
