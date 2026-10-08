import curses
from copy import deepcopy
from pathlib import Path
import unittest

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import (
    ClearAdjustmentFeedbackIntent,
    CloseEditorIntent,
    PreviewIntent,
    QueryApplicationResult,
    ReplaceQueryIntent,
    TuiEditorController,
    UpdateStatusIntent,
)
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.tui_status import StatusKind
from voiceger_editor.query_editing import japanese_pronunciation
from voiceger_editor.voicevox_api_models import AudioQuery, PronunciationPunctuation, VoicegerSegment
from voiceger_editor.tui_editor_pronunciation import TuiPronunciationEditorOwner
from tests.tui_editor_test_support import (
    EditorControllerTestCase,
    _phrase,
    mixed_query,
    direct_japanese_query,
    segments,
)


class TuiPronunciationEditorOwnerTests(EditorControllerTestCase):
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
        query = AudioQuery(accent_phrases=[_phrase(("ナ",), 1)], kana="ナ'")
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
        self.assertIn("Preview failed:", editor.error)
        self.assertIs(editor.error.kind, StatusKind.ERROR)
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
        self.assertIn("Preview failed:", editor.error)
        self.assertIs(editor.error.kind, StatusKind.ERROR)
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
        self.assertTrue(
            editor.error.startswith("English phonemes were not changed:")
        )
        self.assertIs(editor.error.kind, StatusKind.ERROR)
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


if __name__ == "__main__":
    unittest.main()
