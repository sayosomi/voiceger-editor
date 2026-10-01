import curses
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui_editors import (
    AdjustmentPressedIntent,
    ApplySettingsIntent,
    ApplyCaptionIntent,
    BuildPronunciationIntent,
    BuildPronunciationResult,
    ClearAdjustmentFeedbackIntent,
    ClearCandidatesIntent,
    CloseEditorIntent,
    EnglishWordGroup,
    EnglishGroupingCache,
    PreviewIntent,
    PronunciationRow,
    QueryApplicationResult,
    ReplaceQueryIntent,
    SettingsApplicationResult,
    TuiEditorController,
    UpdateStatusIntent,
)
from voiceger_accent_adapter.tui_rendering import _active_input_prefix
from voiceger_accent_adapter.query_editing import japanese_pronunciation
from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    PronunciationPunctuation,
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

    def test_caption_editor_requires_explicit_apply_after_finishing_input(self):
        controller, _provider = self.make_controller()
        controller.open_caption(
            "hello", current_caption="old", origin=("caption", None), busy=False
        )
        editor = controller.editor
        self.assertEqual(editor.kind, "caption")
        self.assertEqual(editor.title, "EDIT CAPTION TEXT")
        self.assertEqual(editor.payload["opening_caption"], "hello")
        self.assertEqual(editor.active_field, "draft")
        self.assertEqual(editor.input_value, "hello")
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=None, current_caption="old"
            ),
            (UpdateStatusIntent(""),),
        )
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.payload["draft"], "hello")
        self.assertEqual(controller.move_selection(1), (ClearAdjustmentFeedbackIntent(),))
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=None, current_caption="old"
            ),
            (ApplyCaptionIntent("hello"),),
        )

    def test_caption_clear_reset_and_back_only_change_or_discard_draft(self):
        controller, _provider = self.make_controller()
        controller.open_caption(
            "opening", current_caption="opening", origin=("caption", None), busy=False
        )
        editor = controller.editor
        editor.input_value = "edited"
        controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption="opening"
        )
        self.assertEqual(editor.payload["draft"], "edited")

        controller.move_selection(2)
        controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption="opening"
        )
        self.assertEqual(editor.payload["draft"], "")
        self.assertIs(controller.editor, editor)

        controller.move_selection(1)
        controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption="opening"
        )
        self.assertEqual(editor.payload["draft"], "opening")
        self.assertEqual(editor.payload["opening_caption"], "opening")
        self.assertIs(controller.editor, editor)

        controller.move_selection(1)
        close = controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption="opening"
        )
        self.assertIsNone(controller.editor)
        self.assertIn(
            CloseEditorIntent(("caption", None), "Caption draft discarded."), close
        )

    def test_caption_escape_is_back_and_discards_active_draft(self):
        controller, _provider = self.make_controller()
        controller.open_caption(
            "opening", current_caption=None, origin=("caption", None), busy=False
        )
        editor = controller.editor
        editor.input_value = "unapplied"
        intents = controller.handle_key(
            "\x1b", settings=self.settings(), query=None, current_caption=None
        )
        self.assertIsNone(controller.editor)
        self.assertIn(
            CloseEditorIntent(("caption", None), "Caption draft discarded."), intents
        )
        self.assertEqual(editor.payload["draft"], "opening")

    def test_build_confirmation_has_typed_rebuild_cancel_and_atomic_completion(self):
        controller, _provider = self.make_controller()
        controller.open_build_confirmation(origin=("build_pronunciation", None))
        editor = controller.editor
        self.assertEqual(editor.title, "REBUILD PRONUNCIATION?")
        self.assertIn("manual pronunciation or utterance edits", editor.payload["warning"].lower())
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=None, current_caption="caption"
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
        controller.move_selection(1)
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

    def test_pronunciation_rows_take_punctuation_from_pure_and_mixed_query_state(self):
        controller, _provider = self.make_controller()
        pure = AudioQuery(
            accent_phrases=[
                _phrase(("ソ", "ウ"), 2),
                _phrase(("ナ", "ノ"), 1),
                _phrase(("ダ",), 1),
            ],
            kana="stale caption pronunciation。",
            pronunciationPunctuation=[
                PronunciationPunctuation(afterAccentPhrase=0, mark="！"),
                PronunciationPunctuation(afterAccentPhrase=0, mark="？"),
                PronunciationPunctuation(afterAccentPhrase=1, mark="…"),
                PronunciationPunctuation(afterAccentPhrase=1, mark="…"),
            ],
        )
        pure_rows = controller.pronunciation_rows(
            pure,
            (("ja", "caption punctuation must not be used?!", None),),
        )
        self.assertEqual(
            [row.punctuation_suffix for row in pure_rows],
            ["！？", "……", ""],
        )

        mixed = mixed_query()
        mixed.voicegerSegments[0].pronunciationPunctuation = [
            PronunciationPunctuation(afterAccentPhrase=0, mark="、"),
            PronunciationPunctuation(afterAccentPhrase=1, mark="…"),
            PronunciationPunctuation(afterAccentPhrase=1, mark="！"),
        ]
        mixed_rows = controller.pronunciation_rows(mixed, segments(mixed)[:1])
        self.assertEqual(
            [row.punctuation_suffix for row in mixed_rows],
            ["、", "…！"],
        )

        legacy = mixed_query()
        legacy.voicegerSegments[0].pronunciationPunctuation = None
        legacy_rows = controller.pronunciation_rows(legacy, segments(legacy)[:1])
        self.assertEqual(
            [row.punctuation_suffix for row in legacy_rows[:2]],
            ["", "？"],
        )

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
            ["HH", "AH2", "L", "OW1", "W", "ER1", "L", "D"],
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
        self.assertEqual(editor.title, "EDIT PRONUNCIATION")
        self.assertEqual(editor.selection, "pronunciation")
        self.assertEqual(editor.active_field, "pronunciation")
        self.assertEqual(editor.payload["source_text"], "なのだ。")
        self.assertEqual(editor.payload["canonical_pronunciation"], "ナ'/ノダ'。")
        self.assertEqual(editor.payload["opening_draft"], "ナ' ノダ'。")
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
                key, settings=self.settings(), query=query, current_caption="source"
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

    def test_japanese_direct_field_question_mark_is_input_and_applies_canonically(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        editor = controller.editor

        controller.handle_key(
            curses.KEY_BACKSPACE,
            settings=self.settings(),
            query=query,
            current_caption="source",
        )
        intents = controller.handle_key(
            "?",
            settings=self.settings(),
            query=query,
            current_caption="source",
        )

        self.assertEqual(intents, ())
        self.assertEqual(editor.input_value, "ナ' ノダ'?")
        self.assertEqual(editor.active_field, "pronunciation")

        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_caption="source",
        )
        self.assertEqual(editor.input_value, "ナ' ノダ'？")
        self.assertEqual(editor.payload["pronunciation"], "ナ' ノダ'？")
        controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(),
            query=query,
            current_caption="source",
        )
        controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(),
            query=query,
            current_caption="source",
        )
        applied = controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_caption="source",
        )

        replacement = next(
            item for item in applied if isinstance(item, ReplaceQueryIntent)
        )
        self.assertEqual(
            japanese_pronunciation(replacement.query, segment_index=0),
            "ナ'/ノダ'？",
        )
        self.assertEqual(
            replacement.query.voicegerSegments[0].text,
            "なのだ。",
        )

    def test_japanese_direct_field_canonicalizes_all_ascii_punctuation_on_finish_and_apply(self):
        cases = ((".", "。"), (",", "、"), ("?", "？"), ("!", "！"))
        previous_marks = {".": "！", ",": "。", "?": "！", "!": "？"}
        for alias, expected in cases:
            with self.subTest(alias=alias):
                query = direct_japanese_query()
                query.voicegerSegments[0].pronunciationTerminator = previous_marks[alias]
                controller, _provider = self.make_controller(
                    {"hello": (("hello", ("HH", "AH1")),)}
                )
                rows = controller.pronunciation_rows(query, segments(query))
                controller.open_pronunciation_item(
                    query, rows, 0, origin=("pronunciation", 0), busy=False
                )
                editor = controller.editor

                controller.handle_key(
                    curses.KEY_END,
                    settings=self.settings(),
                    query=query,
                    current_caption="unchanged Caption",
                )
                controller.handle_key(
                    curses.KEY_BACKSPACE,
                    settings=self.settings(),
                    query=query,
                    current_caption="unchanged Caption",
                )
                controller.handle_key(
                    alias,
                    settings=self.settings(),
                    query=query,
                    current_caption="unchanged Caption",
                )
                controller.handle_key(
                    "\n",
                    settings=self.settings(),
                    query=query,
                    current_caption="unchanged Caption",
                )

                canonical_draft = "ナ' ノダ'" + expected
                self.assertEqual(editor.input_value, canonical_draft)
                self.assertEqual(editor.payload["pronunciation"], canonical_draft)
                controller.handle_key(
                    curses.KEY_DOWN,
                    settings=self.settings(),
                    query=query,
                    current_caption="unchanged Caption",
                )
                controller.handle_key(
                    curses.KEY_DOWN,
                    settings=self.settings(),
                    query=query,
                    current_caption="unchanged Caption",
                )
                applied = controller.handle_key(
                    "\n",
                    settings=self.settings(),
                    query=query,
                    current_caption="unchanged Caption",
                )
                replacement = next(
                    item for item in applied if isinstance(item, ReplaceQueryIntent)
                )
                self.assertEqual(
                    japanese_pronunciation(replacement.query, segment_index=0),
                    "ナ'/ノダ'" + expected,
                )

    def test_unchanged_japanese_direct_field_closes_without_replacing_query(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller({"hello": (("hello", ("HH", "AH1")),)})
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        editor = controller.editor

        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )

        self.assertEqual(intents, (UpdateStatusIntent(""),))
        self.assertIs(controller.editor, editor)
        self.assertIsNone(editor.active_field)
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
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
            "/", settings=self.settings(), query=query, current_caption="source"
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
            curses.KEY_DC, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            "　", settings=self.settings(), query=query, current_caption="source"
        )

        self.assertEqual(editor.input_value, "ナ'　ノダ'。")
        self.assertEqual(editor.error, "")
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
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
                    self.settings(), query=query, current_caption="source"
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

    def test_pronunciation_menu_order_and_enter_finishes_both_input_fields(self):
        cases = (
            (
                "japanese",
                direct_japanese_query(),
                (("hello", ("HH", "AH1")),),
                0,
                ["pronunciation", "preview", "apply", "save_dictionary", "dictionary", "edit_text", "clear", "reset", "back"],
                "ナ' ノダ'！",
                "pronunciation",
            ),
            (
                "english_word",
                mixed_query(),
                {
                    "hello everyone": (
                        ("hello", ("HH", "AH1", "L", "OW2")),
                        ("everyone", ("EH1", "V", "R", "IY0")),
                    )
                },
                2,
                ["phonemes", "preview", "apply", "save_dictionary", "dictionary", "edit_text", "clear", "reset", "back"],
                "HH AE1 L OW0",
                "phonemes",
            ),
        )
        for kind, query, groups, row_index, expected_keys, draft, field in cases:
            with self.subTest(kind=kind):
                controller, _provider = self.make_controller(groups)
                rows = controller.pronunciation_rows(query, segments(query))
                controller.open_pronunciation_item(
                    query,
                    rows,
                    row_index,
                    origin=("pronunciation", row_index),
                    busy=False,
                )
                editor = controller.editor
                self.assertEqual(editor.kind, kind)
                self.assertEqual(editor.title, "EDIT PRONUNCIATION")
                self.assertEqual(controller.selection_keys(), expected_keys)
                editor.input_value = draft
                original_query = query.model_dump()

                intents = controller.handle_key(
                    "\n",
                    settings=self.settings(),
                    query=query,
                    current_caption="source",
                )

                self.assertEqual(intents, (UpdateStatusIntent(""),))
                self.assertIs(controller.editor, editor)
                self.assertIsNone(editor.active_field)
                self.assertEqual(editor.selection, field)
                self.assertEqual(query.model_dump(), original_query)

    def test_preview_intents_are_transient_and_invalid_drafts_do_not_request_synthesis(self):
        japanese = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(japanese, segments(japanese))
        controller.open_pronunciation_item(
            japanese, rows, 0, origin=("pronunciation", 0), busy=False
        )
        editor = controller.editor
        original = japanese.model_dump()
        editor.input_value = "ミ' ノダ'？"
        controller.handle_key(
            "\n", settings=self.settings(), query=japanese, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(),
            query=japanese,
            current_caption="source",
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=japanese, current_caption="source"
        )
        preview = next(intent for intent in intents if isinstance(intent, PreviewIntent))
        self.assertIs(controller.editor, editor)
        self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in intents))
        self.assertIsNone(preview.query.voicegerSegments)
        self.assertEqual(japanese_pronunciation(preview.query), "ミ'/ノダ'？")
        self.assertEqual(japanese.model_dump(), original)

        editor.input_value = "bad pronunciation"
        intents = controller.preview(japanese)
        self.assertFalse(any(isinstance(item, PreviewIntent) for item in intents))
        self.assertIn("Error: Preview failed:", editor.error)
        self.assertEqual(japanese.model_dump(), original)

    def test_english_preview_intent_uses_transient_grouping_and_rejects_invalid_draft(self):
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
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        editor = controller.editor
        original = query.model_dump()
        editor.input_value = "HH AE1 L OW0"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(),
            query=query,
            current_caption="source",
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        preview = next(intent for intent in intents if isinstance(intent, PreviewIntent))

        self.assertIs(controller.editor, editor)
        self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in intents))
        self.assertEqual(len(preview.query.voicegerSegments), 1)
        self.assertEqual(preview.query.voicegerSegments[0].text, "hello everyone")
        self.assertEqual(
            preview.query.voicegerSegments[0].phonemes,
            ["HH", "AE1", "L", "OW0", "EH1", "V", "R", "IY0"],
        )
        self.assertEqual(query.model_dump(), original)

        editor.input_value = "HH AH3"
        intents = controller.preview(query)
        self.assertFalse(any(isinstance(item, PreviewIntent) for item in intents))
        self.assertIn("Error: Preview failed:", editor.error)
        self.assertEqual(query.model_dump(), original)

    def test_clear_reset_back_preserve_the_opening_draft_for_both_kinds(self):
        cases = (
            (
                "japanese",
                direct_japanese_query(),
                (("hello", ("HH", "AH1")),),
                0,
                "ナ' ノダ'！",
                "Japanese pronunciation draft cleared.",
                "Japanese pronunciation draft reset.",
                "pronunciation",
            ),
            (
                "english_word",
                mixed_query(),
                {
                    "hello everyone": (
                        ("hello", ("HH", "AH1", "L", "OW2")),
                        ("everyone", ("EH1", "V", "R", "IY0")),
                    )
                },
                2,
                "HH AE1 L OW0",
                "English phoneme draft cleared.",
                "English phoneme draft reset.",
                "phonemes",
            ),
        )
        for kind, query, groups, row_index, changed, clear_status, reset_status, field in cases:
            with self.subTest(kind=kind):
                controller, _provider = self.make_controller(groups)
                rows = controller.pronunciation_rows(query, segments(query))
                origin = ("pronunciation", row_index)
                controller.open_pronunciation_item(
                    query, rows, row_index, origin=origin, busy=False
                )
                editor = controller.editor
                opening = editor.payload["opening_draft"]
                canonical_before = query.model_dump()
                editor.input_value = changed
                controller.handle_key(
                    "\n",
                    settings=self.settings(),
                    query=query,
                    current_caption="source",
                )

                controller.move_selection(6)
                cleared = controller.handle_key(
                    "\n",
                    settings=self.settings(),
                    query=query,
                    current_caption="source",
                )
                self.assertEqual(cleared, (UpdateStatusIntent(clear_status),))
                self.assertEqual(editor.input_value, "")
                self.assertEqual(editor.payload["opening_draft"], opening)
                self.assertIs(controller.editor, editor)
                self.assertEqual(query.model_dump(), canonical_before)

                controller.move_selection(1)
                reset = controller.handle_key(
                    "\n",
                    settings=self.settings(),
                    query=query,
                    current_caption="source",
                )
                self.assertEqual(reset, (UpdateStatusIntent(reset_status),))
                self.assertEqual(editor.input_value, opening)
                self.assertEqual(editor.payload["opening_draft"], opening)
                self.assertEqual(query.model_dump(), canonical_before)

                controller.move_selection(1)
                backed = controller.handle_key(
                    "\n",
                    settings=self.settings(),
                    query=query,
                    current_caption="source",
                )
                self.assertIsNone(controller.editor)
                discard_status = (
                    "Japanese pronunciation draft discarded."
                    if kind == "japanese"
                    else "English word draft discarded."
                )
                self.assertIn(CloseEditorIntent(origin, discard_status), backed)
                self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in backed))
                self.assertEqual(query.model_dump(), canonical_before)

    def test_preview_busy_keeps_pronunciation_editor_and_draft_locked(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {
                "hello everyone": (
                    ("hello", ("HH", "AH1", "L", "OW2")),
                    ("everyone", ("EH1", "V", "R", "IY0")),
                )
            }
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        editor = controller.editor
        before = editor.input_value
        intents = controller.handle_key(
            curses.KEY_DOWN,
            settings=self.settings(),
            query=query,
            current_caption="source",
            preview_busy=True,
        )
        self.assertEqual(
            intents,
            (UpdateStatusIntent("Wait for Preview to finish before editing pronunciation."),),
        )
        self.assertIs(controller.editor, editor)
        self.assertEqual(editor.input_value, before)
        self.assertEqual(editor.selection, "phonemes")

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
        self.assertEqual(editor.title, "EDIT PRONUNCIATION")
        self.assertNotIn("english_segment", editor.kind)
        self.assertEqual(editor.payload["label"], "hello")
        self.assertEqual(
            controller.selection_keys(),
            ["phonemes", "preview", "apply", "save_dictionary", "dictionary", "edit_text", "clear", "reset", "back"],
        )
        self.assertEqual(editor.active_field, "phonemes")
        self.assertEqual(editor.input_value, "HH AH1 L OW2")
        controller.handle_key(
            "X", settings=self.settings(), query=query, current_caption="source"
        )
        self.assertEqual(editor.input_value, "HH AH1 L OW2X")
        controller.handle_key(
            curses.KEY_BACKSPACE,
            settings=self.settings(), query=query, current_caption="source",
        )
        self.assertEqual(editor.input_value, "HH AH1 L OW2")
        editor.input_value = "HH AE1 L OW0"
        editor.input_cursor = len(editor.input_value)
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        self.assertEqual(intents, (UpdateStatusIntent(""),))
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        replacement = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(
            replacement.query.voicegerSegments[1].phonemes[:4],
            ["HH", "AE1", "L", "OW0"],
        )
        completed = controller.complete_query_application(
            replacement, QueryApplicationResult()
        )
        self.assertEqual(completed[-1], CloseEditorIntent(("pronunciation", 2), replacement.success_status))
        self.assertEqual(controller.grouping_cache[1].groups[0].phonemes, ("HH", "AE1", "L", "OW0"))
        self.assertIsNone(controller.editor)

    def test_english_direct_edit_applies_full_stress_values_to_selected_word(self):
        original = ("Z", "UW1", "N", "D", "AA1", "M", "OW1", "N")
        expected = ["Z", "UW1", "N", "D", "AA0", "M", "OW0", "N"]
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(language="en", text="Zundamon", phonemes=list(original))
            ],
        )
        controller, _provider = self.make_controller(
            {"Zundamon": (("Zundamon", original),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        editor = controller.editor
        self.assertEqual(editor.input_value, " ".join(original))
        editor.input_value = "Z UW1 N D AA0 M OW0 N"

        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )

        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        replacement = next(
            intent for intent in intents if isinstance(intent, ReplaceQueryIntent)
        )

        self.assertEqual(replacement.query.voicegerSegments[0].phonemes, expected)

    def test_english_direct_field_rejects_invalid_stress_then_retries_corrected_draft(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {
                "hello everyone": (
                    ("hello", ("HH", "AH1", "L", "OW2")),
                    ("everyone", ("EH1", "V", "R", "IY0")),
                )
            }
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        editor = controller.editor
        editor.input_value = "hh ah3 l ow2"
        editor.input_cursor = 6
        original_query = query.model_dump()

        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )

        self.assertEqual(intents, ())
        self.assertEqual(query.model_dump(), original_query)
        self.assertEqual(editor.input_value, "hh ah3 l ow2")
        self.assertTrue(editor.error.startswith("Error: English phonemes were not changed:"))
        controller.handle_key(
            curses.KEY_UP, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_UP, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        editor.input_value = "HH AH0 L OW2"
        editor.input_cursor = len(editor.input_value)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        self.assertEqual(editor.input_value, "HH AH0 L OW2")
        self.assertEqual(editor.error, "")

        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        replacement = next(
            intent for intent in intents if isinstance(intent, ReplaceQueryIntent)
        )
        self.assertEqual(
            replacement.query.voicegerSegments[1].phonemes[:4],
            ["HH", "AH0", "L", "OW2"],
        )

    def test_english_direct_field_uses_shared_cursor_and_text_edit_keys(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {
                "hello everyone": (
                    ("hello", ("HH", "AH1", "L", "OW2")),
                    ("everyone", ("EH1", "V", "R", "IY0")),
                )
            }
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        editor = controller.editor
        original = "HH AH1 L OW2"

        def press(key):
            controller.handle_key(
                key,
                settings=self.settings(),
                query=query,
                current_caption="source",
                screen_width=8,
            )

        press(curses.KEY_HOME)
        self.assertEqual(editor.input_cursor, 0)
        press(curses.KEY_DOWN)
        self.assertGreater(editor.input_cursor, 0)
        press(curses.KEY_UP)
        self.assertEqual(editor.input_cursor, 0)
        press(curses.KEY_RIGHT)
        self.assertEqual(editor.input_cursor, 1)
        press("X")
        self.assertEqual(editor.input_value, "HXH AH1 L OW2")
        press(curses.KEY_BACKSPACE)
        self.assertEqual(editor.input_value, original)
        press(curses.KEY_END)
        self.assertEqual(editor.input_cursor, len(original))
        press(curses.KEY_LEFT)
        press(curses.KEY_DC)
        self.assertEqual(editor.input_value, "HH AH1 L OW")
        press("2")
        self.assertEqual(editor.input_value, original)

    def test_english_direct_field_rejects_empty_pronunciation_without_mutation(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {
                "hello everyone": (
                    ("hello", ("HH", "AH1", "L", "OW2")),
                    ("everyone", ("EH1", "V", "R", "IY0")),
                )
            }
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        editor = controller.editor
        editor.input_value = ""
        editor.input_cursor = 0
        original_query = query.model_dump()

        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=query, current_caption="source"
            ),
            (),
        )
        self.assertEqual(query.model_dump(), original_query)
        self.assertEqual(editor.input_value, "")
        self.assertIn("must not be empty", editor.error)

    def test_unchanged_english_direct_field_closes_without_query_replacement(self):
        query = mixed_query()
        controller, _provider = self.make_controller(
            {
                "hello everyone": (
                    ("hello", ("HH", "AH1", "L", "OW2")),
                    ("everyone", ("EH1", "V", "R", "IY0")),
                )
            }
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        controller.editor.input_value = "hh ah1 l ow2"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        controller.handle_key(
            curses.KEY_DOWN, settings=self.settings(), query=query, current_caption="source"
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="source"
        )

        self.assertEqual(
            intents[-1],
            CloseEditorIntent(("pronunciation", 2), "English phonemes unchanged."),
        )
        self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in intents))
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
            type("Style", (), {"id": 3, "name": "Neutral"})(),
            type("Style", (), {"id": 1, "name": "Sweet"})(),
            type("Style", (), {"id": 22, "name": "Whispering"})(),
        )
        controller, _provider = self.make_controller(styles=styles)
        controller.open_settings(
            self.settings(), origin=("settings", None), busy=False
        )
        self.assertEqual(controller.editor.selection, "style_id")
        self.assertEqual(controller.adjust_settings(-1), (ClearAdjustmentFeedbackIntent(),))
        self.assertEqual(controller.adjust_settings(1), (AdjustmentPressedIntent("settings", "style_id", 1),))
        self.assertEqual(controller.editor.payload["draft_settings"]["style_id"], "1")
        self.assertEqual(controller.adjust_settings(1), (AdjustmentPressedIntent("settings", "style_id", 1),))
        self.assertEqual(controller.editor.payload["draft_settings"]["style_id"], "22")
        self.assertEqual(controller.adjust_settings(-1), (AdjustmentPressedIntent("settings", "style_id", -1),))
        self.assertEqual(controller.editor.payload["draft_settings"]["style_id"], "1")
        controller.editor.selection = "apply"
        intent = controller._activate_selection(self.settings(), None, None)[0]
        self.assertIsInstance(intent, ApplySettingsIntent)
        self.assertEqual(intent.settings.style_id, 1)
        self.assertEqual(intent.settings.output_dir, self.settings().output_dir)

    def test_settings_reject_unavailable_style_id_instead_of_falling_back(self):
        styles = (
            type("Style", (), {"id": 3, "name": "Neutral"})(),
            type("Style", (), {"id": 1, "name": "Sweet"})(),
        )
        controller, _provider = self.make_controller(styles=styles)
        controller.open_settings(
            Settings(style_id=2), origin=("settings", None), busy=False
        )

        self.assertEqual(
            controller.adjust_settings(1),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(
            controller.editor.payload["draft_settings"]["style_id"],
            "2",
        )
        self.assertEqual(
            controller.editor.error,
            "Error: Style ID 2 is not available.",
        )

    def test_sampling_settings_adjust_edit_reset_and_apply_as_draft(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor

        editor.selection = "top_k"
        self.assertEqual(
            controller.adjust_settings(1),
            (AdjustmentPressedIntent("settings", "top_k", 1),),
        )
        self.assertEqual(editor.payload["draft_settings"]["top_k"], "21")

        editor.selection = "top_p"
        self.assertEqual(
            controller.adjust_settings(-1),
            (AdjustmentPressedIntent("settings", "top_p", -1),),
        )
        self.assertEqual(editor.payload["draft_settings"]["top_p"], "0.95")

        editor.selection = "temperature"
        controller.adjust_settings(-1)
        self.assertEqual(editor.payload["draft_settings"]["temperature"], "0.95")
        self.assertEqual(settings.temperature, 1.0)

        for field, value, expected in (
            ("top_k", "37", "37"),
            ("top_p", "0.35", "0.35"),
            ("temperature", "0.65", "0.65"),
        ):
            with self.subTest(direct_edit=field):
                editor.selection = field
                controller.handle_key(
                    "\n", settings=settings, query=None, current_caption=None
                )
                self.assertEqual(editor.active_field, field)
                editor.input_value = value
                editor.input_cursor = len(editor.input_value)
                controller.handle_key(
                    "\n", settings=settings, query=None, current_caption=None
                )
                self.assertIsNone(editor.active_field)
                self.assertEqual(
                    editor.payload["draft_settings"][field],
                    expected,
                )

        editor.payload["draft_settings"]["take_count"] = "9"
        editor.selection = "reset_sampling"
        intents = controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )
        self.assertEqual(editor.payload["draft_settings"]["top_k"], "20")
        self.assertEqual(editor.payload["draft_settings"]["top_p"], "1.00")
        self.assertEqual(editor.payload["draft_settings"]["temperature"], "1.00")
        self.assertEqual(editor.payload["draft_settings"]["take_count"], "9")
        self.assertEqual(
            intents[-1],
            UpdateStatusIntent("Sampling reset to Voiceger defaults."),
        )

        editor.payload["draft_settings"]["top_k"] = "37"
        editor.payload["draft_settings"]["top_p"] = "0.45"
        editor.payload["draft_settings"]["temperature"] = "0.80"
        editor.selection = "apply"
        apply = controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )
        self.assertEqual(len(apply), 1)
        self.assertIsInstance(apply[0], ApplySettingsIntent)
        self.assertEqual(apply[0].settings.top_k, 37)
        self.assertEqual(apply[0].settings.top_p, 0.45)
        self.assertEqual(apply[0].settings.temperature, 0.80)

    def test_settings_selection_order_and_adjustable_enter_emit_full_targets(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        self.assertEqual(
            controller.selection_keys(),
            [
                "style_id", "speed", "take_count", "output_dir", "save_text", "save_lab",
                "top_k", "top_p", "temperature", "reset_sampling",
                "apply", "reset", "back",
            ],
        )

        drafts = (
            ("style_id", {"style_id": "2"}, Settings(style_id=2, output_dir=settings.output_dir)),
            ("speed", {"speed": "1.25"}, Settings(speed=1.25, output_dir=settings.output_dir)),
            ("save_text", {"save_text": True}, Settings(save_text=True, output_dir=settings.output_dir)),
            ("save_lab", {"save_lab": True}, Settings(save_lab=True, output_dir=settings.output_dir)),
        )
        for field, updates, expected in drafts:
            with self.subTest(field=field):
                controller.open_settings(
                    settings, origin=("settings", None), busy=False
                )
                editor = controller.editor
                editor.payload["draft_settings"].update(updates)
                editor.selection = field
                intents = controller.handle_key(
                    "\n", settings=settings, query=None, current_caption=None
                )
                self.assertEqual(intents, (ApplySettingsIntent(expected),))
                self.assertIs(controller.editor, editor)
                self.assertIsNone(editor.active_field)

    def test_settings_txt_left_and_right_each_toggle_continuously(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor
        editor.selection = "save_text"
        editor.payload["draft_settings"]["save_text"] = False

        self.assertEqual(
            controller.adjust_settings(-1),
            (AdjustmentPressedIntent("settings", "save_text", -1),),
        )
        self.assertTrue(editor.payload["draft_settings"]["save_text"])
        self.assertEqual(
            controller.adjust_settings(-1),
            (AdjustmentPressedIntent("settings", "save_text", -1),),
        )
        self.assertFalse(editor.payload["draft_settings"]["save_text"])
        self.assertEqual(
            controller.adjust_settings(1),
            (AdjustmentPressedIntent("settings", "save_text", 1),),
        )
        self.assertTrue(editor.payload["draft_settings"]["save_text"])
        self.assertEqual(
            controller.adjust_settings(1),
            (AdjustmentPressedIntent("settings", "save_text", 1),),
        )
        self.assertFalse(editor.payload["draft_settings"]["save_text"])

    def test_settings_tab_and_backtab_move_between_section_starts_and_wrap(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor

        for expected in ("take_count", "output_dir", "top_k", "apply", "style_id"):
            intents = controller.handle_key(
                "\t", settings=settings, query=None, current_caption=None
            )
            self.assertEqual(intents, (ClearAdjustmentFeedbackIntent(),))
            self.assertEqual(editor.selection, expected)

        backtab = getattr(curses, "KEY_BTAB")
        for expected in ("apply", "top_k", "output_dir", "take_count", "style_id"):
            intents = controller.handle_key(
                backtab, settings=settings, query=None, current_caption=None
            )
            self.assertEqual(intents, (ClearAdjustmentFeedbackIntent(),))
            self.assertEqual(editor.selection, expected)

    def test_sampling_shortcuts_focus_rows_and_reset_only_the_draft(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor

        for shortcut, expected in (("k", "top_k"), ("p", "top_p"), ("t", "temperature")):
            with self.subTest(shortcut=shortcut):
                intents = controller.handle_key(
                    shortcut, settings=settings, query=None, current_caption=None
                )
                self.assertEqual(intents, (ClearAdjustmentFeedbackIntent(),))
                self.assertEqual(editor.selection, expected)

        editor.payload["draft_settings"].update(
            {"top_k": "37", "top_p": "0.45", "temperature": "0.80"}
        )
        intents = controller.handle_key(
            "d", settings=settings, query=None, current_caption=None
        )
        self.assertEqual(editor.selection, "reset_sampling")
        self.assertEqual(editor.payload["draft_settings"]["top_k"], "20")
        self.assertEqual(editor.payload["draft_settings"]["top_p"], "1.00")
        self.assertEqual(editor.payload["draft_settings"]["temperature"], "1.00")
        self.assertEqual(settings.top_k, 20)
        self.assertEqual(settings.top_p, 1.0)
        self.assertEqual(settings.temperature, 1.0)
        self.assertEqual(
            intents[-1],
            UpdateStatusIntent("Sampling reset to Voiceger defaults."),
        )

    def test_settings_take_count_enter_edits_numeric_draft_before_explicit_apply(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor
        editor.selection = "take_count"

        self.assertEqual(
            controller.handle_key(
                "\n", settings=settings, query=None, current_caption=None
            ),
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(editor.active_field, "take_count")
        self.assertEqual(editor.input_value, "4")

        editor.input_value = "42"
        editor.input_cursor = 2
        self.assertEqual(
            controller.handle_key(
                "\n", settings=settings, query=None, current_caption=None
            ),
            (UpdateStatusIntent(""),),
        )
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.payload["draft_settings"]["take_count"], "42")
        self.assertIs(controller.editor, editor)

        editor.selection = "apply"
        self.assertEqual(
            controller.handle_key(
                "\n", settings=settings, query=None, current_caption=None
            ),
            (
                ApplySettingsIntent(
                    Settings(take_count=42, output_dir=settings.output_dir)
                ),
            ),
        )

    def test_settings_take_count_direct_edit_rejects_invalid_values_in_place(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor
        editor.selection = "take_count"
        controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )

        for value in ("101", "not-a-number"):
            with self.subTest(value=value):
                editor.input_value = value
                editor.input_cursor = len(value)
                self.assertEqual(
                    controller.handle_key(
                        "\n", settings=settings, query=None, current_caption=None
                    ),
                    (),
                )
                self.assertEqual(editor.active_field, "take_count")
                self.assertEqual(
                    editor.payload["draft_settings"]["take_count"],
                    "4",
                )
                self.assertIn(
                    "Take count must be an integer from 1 through 100",
                    editor.error,
                )

    def test_settings_validation_rejects_invalid_full_draft_before_emitting_apply(self):
        settings = self.settings()
        controller, _provider = self.make_controller()
        controller.open_settings(settings, origin=("settings", None), busy=False)
        editor = controller.editor
        editor.payload["draft_settings"]["take_count"] = "101"

        intents = controller.handle_key(
            "\n", settings=settings, query=None, current_caption=None
        )

        self.assertEqual(intents, ())
        self.assertIs(controller.editor, editor)
        self.assertIn("take_count must be an integer from 1 through 100", editor.error)

    def test_settings_reset_restores_opening_snapshot_and_back_or_escape_discards(self):
        opening = Settings(
            style_id=3,
            speed=1.2,
            take_count=6,
            output_dir=Path("/tmp/opening-output"),
            save_text=True,
        )
        controller, _provider = self.make_controller()
        controller.open_settings(opening, origin=("help", None), busy=False)
        editor = controller.editor
        editor.payload["draft_settings"].update(
            {
                "style_id": "7",
                "speed": "2.00",
                "take_count": "1",
                "output_dir": "/tmp/changed-output",
                "save_text": False,
            }
        )
        editor.selection = "reset"
        intents = controller.handle_key(
            "\n", settings=opening, query=None, current_caption=None
        )
        self.assertEqual(
            editor.payload["draft_settings"],
            {
                "style_id": "3",
                "speed": "1.2",
                "take_count": "6",
                "output_dir": "/tmp/opening-output",
                "save_text": True,
                "save_lab": False,
                "top_k": "20",
                "top_p": "1.00",
                "temperature": "1.00",
            },
        )
        self.assertEqual(intents[-1], UpdateStatusIntent("Settings draft reset."))
        self.assertIs(controller.editor, editor)

        editor.payload["draft_settings"]["take_count"] = "2"
        editor.selection = "back"
        back = controller.handle_key(
            "\n", settings=opening, query=None, current_caption=None
        )
        self.assertIsNone(controller.editor)
        self.assertEqual(
            back[-1], CloseEditorIntent(("help", None), "Settings draft discarded.")
        )

        controller.open_settings(opening, origin=("settings", None), busy=False)
        controller.editor.payload["draft_settings"]["style_id"] = "1"
        cancelled = controller.handle_key(
            "\x1b", settings=opening, query=None, current_caption=None
        )
        self.assertIsNone(controller.editor)
        self.assertEqual(
            cancelled[-1],
            CloseEditorIntent(("settings", None), "Settings draft discarded."),
        )

    def test_settings_field_edits_remain_on_the_same_selection_row(self):
        controller, _provider = self.make_controller()
        controller.open_settings(
            self.settings(), origin=("settings", None), busy=False,
            selected_field="output_dir",
        )
        self.assertEqual(controller.editor.selection, "output_dir")
        self.assertIsNone(controller.editor.active_field)
        controller.handle_key(
            "\n", settings=self.settings(), query=None, current_caption=None
        )
        self.assertEqual(controller.editor.active_field, "output_dir")
        controller.editor.input_value = "/tmp/new-output"
        self.assertEqual(
            controller.handle_key(
                "\n", settings=self.settings(), query=None, current_caption=None
            ),
            (UpdateStatusIntent(""),),
        )
        self.assertEqual(controller.editor.selection, "output_dir")
        self.assertIsNone(controller.editor.active_field)
        self.assertEqual(
            controller.editor.payload["draft_settings"]["output_dir"],
            "/tmp/new-output",
        )

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

    def test_japanese_edit_text_back_restores_the_pronunciation_draft_exactly(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        parent = controller.editor
        parent.input_value = "ナ' ノダ'？"
        parent.input_cursor = 4
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        parent.input_cursor = 4
        controller.move_selection(5)
        before = deepcopy(parent)

        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        section = controller.editor
        self.assertEqual(section.kind, "section_text")
        self.assertEqual(section.payload["language"], "ja")
        self.assertEqual(section.payload["opening_text"], "なのだ。")
        section.input_value = "discard this text"
        controller.handle_key(
            "\x1b", settings=self.settings(), query=query, current_caption="caption"
        )

        self.assertEqual(controller.editor, before)
        self.assertEqual(controller.editor.input_value, "ナ' ノダ'？")
        self.assertEqual(controller.editor.input_cursor, 4)
        self.assertEqual(controller.editor.payload["pronunciation"], "ナ' ノダ'？")

    def test_english_edit_text_back_restores_the_pronunciation_draft_exactly(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 2, origin=("pronunciation", 2), busy=False
        )
        parent = controller.editor
        parent.input_value = "HH AH0"
        parent.input_cursor = 5
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        parent.input_cursor = 5
        controller.move_selection(5)
        before = deepcopy(parent)

        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        section = controller.editor
        self.assertEqual(section.kind, "section_text")
        self.assertEqual(section.payload["language"], "en")
        self.assertEqual(section.payload["opening_text"], "hello")
        section.input_value = "discard this word"
        controller.handle_key(
            "\x1b", settings=self.settings(), query=query, current_caption="caption"
        )

        self.assertEqual(controller.editor, before)
        self.assertEqual(controller.editor.input_value, "HH AH0")
        self.assertEqual(controller.editor.input_cursor, 5)
        self.assertEqual(controller.editor.payload["phonemes"], "HH AH0")

    def test_section_text_reset_and_apply_emit_a_committed_query_intent(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        controller.move_selection(5)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        section = controller.editor
        original_query = query.model_dump()
        section.input_value = "draft text"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        controller.move_selection(3)
        reset = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        self.assertEqual(reset, (UpdateStatusIntent("Section text draft reset."),))
        self.assertEqual(section.input_value, "なのだ。")
        self.assertEqual(query.model_dump(), original_query)

        controller.move_selection(-3)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        section.input_value = "明日も晴れ"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        controller.move_selection(2)
        with patch(
            "voiceger_accent_adapter.query_editing.text_to_pronunciation",
            return_value=parse_pronunciation("ア'シ/タ'モ！"),
        ):
            intents = controller.handle_key(
                "\n", settings=self.settings(), query=query, current_caption="caption"
            )

        replacement = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(replacement.editor_kind, "section_text")
        self.assertEqual(replacement.query.voicegerSegments[0].text, "明日も晴れ")
        self.assertIsNone(replacement.pure_japanese_utterance_text)
        self.assertEqual(query.model_dump(), original_query)
        closed = controller.complete_query_application(
            replacement, QueryApplicationResult()
        )
        self.assertIsNone(controller.editor)
        self.assertEqual(
            closed[-1],
            CloseEditorIntent(("pronunciation", 0), replacement.success_status),
        )

    def test_pure_japanese_section_apply_carries_the_new_utterance_source(self):
        query = AudioQuery(
            accent_phrases=[_phrase(("ア", "メ"), 2)],
            kana="アメ'。",
        )
        controller, _provider = self.make_controller()
        rows = controller.pronunciation_rows(query, (("ja", "本当の発話", None),))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(5)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        section = controller.editor
        self.assertEqual(section.payload["opening_text"], "本当の発話")
        section.input_value = "更新した発話"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(2)
        with patch(
            "voiceger_accent_adapter.query_editing.text_to_pronunciation",
            return_value=parse_pronunciation("キョ'ウ！"),
        ):
            intents = controller.handle_key(
                "\n", settings=self.settings(), query=query, current_caption="Caption"
            )
        replacement = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(replacement.pure_japanese_utterance_text, "更新した発話")
        self.assertIsNone(replacement.query.voicegerSegments)
        self.assertEqual(japanese_pronunciation(replacement.query), "キョ'ウ！")

    def test_section_text_preview_is_noncommitting_and_locks_until_preview_finishes(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        controller.move_selection(5)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        section = controller.editor
        section.input_value = "preview text"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        original = query.model_dump()
        with patch(
            "voiceger_accent_adapter.query_editing.text_to_pronunciation",
            return_value=parse_pronunciation("ミ'ズ？"),
        ):
            controller.move_selection(1)
            intents = controller.handle_key(
                "\n", settings=self.settings(), query=query, current_caption="caption"
            )
        preview = next(item for item in intents if isinstance(item, PreviewIntent))
        self.assertEqual(preview.query.kana, "ミ'ズ？")
        self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in intents))
        self.assertIs(controller.editor, section)
        locked = controller.handle_key(
            "\x1b",
            settings=self.settings(),
            query=query,
            current_caption="caption",
            preview_busy=True,
        )
        self.assertEqual(
            locked,
            (UpdateStatusIntent("Wait for Preview to finish before editing section text."),),
        )
        self.assertIs(controller.editor, section)
        self.assertEqual(query.model_dump(), original)

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

    def test_add_clear_reset_and_back_keep_the_opening_language_and_empty_draft(self):
        query = mixed_query()
        controller, _provider = self.make_controller()
        controller.open_add_section(
            query,
            pure_japanese_utterance_text=None,
            origin=("add_section", None),
            busy=False,
        )
        editor = controller.editor
        self.assertEqual(controller.selection_keys(), ["language", "draft", "add", "clear", "reset", "back"])
        editor.input_value = "discarded"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(2)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertEqual(editor.payload["draft"], "")
        self.assertEqual(editor.payload["language"], "ja")
        controller.move_selection(1)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertEqual(editor.payload["draft"], "")
        self.assertEqual(editor.payload["language"], "ja")
        controller.move_selection(1)
        close = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertIsNone(controller.editor)
        self.assertIn(
            CloseEditorIntent(("add_section", None), "New section draft discarded."),
            close,
        )

    def test_delete_confirmation_cancel_restores_section_editor(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        controller.move_selection(5)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        section = controller.editor
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        controller.move_selection(4)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        confirmation = controller.editor
        self.assertEqual(confirmation.title, "DELETE SECTION?")
        self.assertEqual(
            confirmation.payload["warning"],
            "This section will be removed from the synthesized utterance.",
        )
        canceled = controller.handle_key(
            "\x1b", settings=self.settings(), query=query, current_caption="caption"
        )
        self.assertEqual(controller.editor, section)
        self.assertEqual(query.voicegerSegments[0].text, "なのだ。")
        self.assertFalse(any(isinstance(item, ReplaceQueryIntent) for item in canceled))

    def test_clear_candidates_confirmation_cancel_is_non_destructive(self):
        controller, _provider = self.make_controller()
        controller.open_clear_candidates_confirmation(origin=("clear_candidates", None))
        confirmation = controller.editor

        self.assertEqual(confirmation.title, "CLEAR CANDIDATES?")
        self.assertIn("candidate WAV files will be discarded", confirmation.payload["warning"])
        canceled = controller.handle_key(
            "b", settings=self.settings(), query=None, current_caption="Caption"
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

    def test_delete_action_is_absent_for_the_only_pure_japanese_section(self):
        query = AudioQuery(
            accent_phrases=[_phrase(("ア",), 1)],
            kana="ア'。",
        )
        controller, _provider = self.make_controller()
        rows = controller.pronunciation_rows(query, (("ja", "actual", None),))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        controller.move_selection(5)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="caption"
        )
        self.assertFalse(controller.editor.payload["can_delete"])
        self.assertNotIn("delete_section", controller.selection_keys())

    def test_add_japanese_appends_one_built_section_to_a_mixed_query(self):
        query = mixed_query()
        original = query.model_dump()
        controller, _provider = self.make_controller()
        controller.open_add_section(
            query,
            pure_japanese_utterance_text=None,
            origin=("add_section", None),
            busy=False,
        )
        editor = controller.editor
        editor.input_value = "追加の日本語"
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(1)
        with patch(
            "voiceger_accent_adapter.query_editing.text_to_pronunciation",
            return_value=parse_pronunciation("ツ'イカ！"),
        ):
            intents = controller.handle_key(
                "\n", settings=self.settings(), query=query, current_caption="Caption"
            )
        addition = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(addition.editor_kind, "add_section")
        self.assertEqual(addition.query.voicegerSegments[0].model_dump(), original["voicegerSegments"][0])
        self.assertEqual(addition.query.voicegerSegments[1].model_dump(), original["voicegerSegments"][1])
        self.assertEqual(addition.query.voicegerSegments[2].language, "ja")
        self.assertEqual(addition.query.voicegerSegments[2].text, "追加の日本語")
        self.assertEqual(addition.query.voicegerSegments[2].accentPhraseStart, 2)
        self.assertEqual(addition.query.voicegerSegments[2].accentPhraseCount, 1)
        self.assertEqual(addition.query.voicegerSegments[2].pronunciationTerminator, "！")
        self.assertEqual(query.model_dump(), original)

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
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        intent = next(item for item in deletion if isinstance(item, ReplaceQueryIntent))
        self.assertEqual(intent.deleted_segment_index, 1)
        controller.complete_query_application(intent, QueryApplicationResult())
        self.assertEqual(set(controller.grouping_cache), {1})
        self.assertEqual(controller.grouping_cache[1], world_grouping)

    def test_deleting_back_to_one_japanese_section_records_pure_source(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
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
        editor = controller.editor
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.move_selection(4)
        controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        intents = controller.handle_key(
            "\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        deletion = next(item for item in intents if isinstance(item, ReplaceQueryIntent))
        self.assertIsNone(deletion.query.voicegerSegments)
        self.assertEqual(deletion.pure_japanese_utterance_text, "なのだ。")
        self.assertEqual(
            [phrase.model_dump() for phrase in deletion.query.accent_phrases],
            [phrase.model_dump() for phrase in query.accent_phrases],
        )
        self.assertEqual(deletion.editor_kind, "delete_section")
        self.assertIsNotNone(editor)


if __name__ == "__main__":
    unittest.main()
