import curses
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from voiceger_editor.settings import Settings
from voiceger_editor.tui_editors import (
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
    CloseEditorIntent,
    PreviewIntent,
    QueryApplicationResult,
    ReplaceQueryIntent,
    TuiEditorController,
    UpdateStatusIntent,
)
from voiceger_editor.tui_input import PasteText
from voiceger_editor.tui_rendering import _active_input_prefix
from voiceger_editor.query_editing import japanese_pronunciation
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.voicevox_api_models import AudioQuery
from voiceger_editor.tui_editor_common import ApplyCaptionIntent
from voiceger_editor.tui_editor_text import TuiTextEditorOwner
from tests.tui_editor_test_support import (
    EditorControllerTestCase,
    _phrase,
    mixed_query,
    direct_japanese_query,
    segments,
)


class TuiTextEditorOwnerTests(EditorControllerTestCase):
    def test_caption_draft_and_apply_are_owned_behind_facade(self):
        controller = TuiEditorController(
            english_word_groups=lambda _text: (),
            available_styles=lambda: (),
            input_prefix=_active_input_prefix,
        )
        self.assertIsInstance(controller._text, TuiTextEditorOwner)
        controller.open_caption(
            "opening",
            current_caption="opening",
            origin=("caption", None),
            busy=False,
        )
        controller.editor.input_value = "changed"
        controller.handle_key(
            "\n",
            settings=Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            query=None,
            current_caption="opening",
        )
        controller.move_selection(1)

        intents = controller.handle_key(
            "\n",
            settings=Settings(output_dir=Path("/tmp/voiceger-editor-tests")),
            query=None,
            current_caption="opening",
        )

        self.assertTrue(any(isinstance(item, ApplyCaptionIntent) for item in intents))

    def test_caption_editor_requires_explicit_apply_after_finishing_input(self):
        controller, _provider = self.make_controller()
        controller.open_caption(
            "hello", current_caption="old", origin=("caption", None), busy=False
        )
        editor = controller.editor
        self.assertEqual(editor.kind, "caption")
        self.assertEqual(editor.title, "EDIT CAPTION TEXT")
        self.assertEqual(editor.payload["opening_caption"], "hello")
        self.assertFalse(editor.payload["multiline"])
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

    def test_add_captions_editor_remains_available_while_synthesis_is_busy(self):
        controller, _provider = self.make_controller()

        intents = controller.open_caption(
            "",
            current_caption=None,
            origin=("add_captions", None),
            busy=True,
            multiline=True,
        )

        self.assertEqual(controller.editor.title, "ADD CAPTIONS")
        self.assertEqual(controller.editor.active_field, "draft")
        self.assertEqual(intents[0], UpdateStatusIntent(""))

    def test_existing_caption_editor_stays_blocked_while_synthesis_is_busy(self):
        controller, _provider = self.make_controller()

        intents = controller.open_caption(
            "existing",
            current_caption="existing",
            origin=("caption", None),
            busy=True,
        )

        self.assertIsNone(controller.editor)
        self.assertEqual(
            intents,
            (UpdateStatusIntent("Wait for synthesis to finish before editing Caption."),),
        )

    def test_add_captions_editor_accepts_paste_and_ctrl_n_newlines(self):
        controller, _provider = self.make_controller()
        controller.open_caption(
            "",
            current_caption=None,
            origin=("add_captions", None),
            busy=False,
            multiline=True,
        )
        editor = controller.editor
        self.assertEqual(editor.title, "ADD CAPTIONS")
        self.assertTrue(editor.payload["multiline"])

        controller.handle_key(
            PasteText("first\n\nsecond"),
            settings=self.settings(),
            query=None,
            current_caption=None,
        )
        controller.handle_key(
            "\x0e",
            settings=self.settings(),
            query=None,
            current_caption=None,
        )
        controller.handle_key(
            "third",
            settings=self.settings(),
            query=None,
            current_caption=None,
        )

        self.assertEqual(editor.input_value, "first\n\nsecond\nthird")
        self.assertEqual(editor.active_field, "draft")
        self.assertEqual(
            controller.handle_key(
                "\n",
                settings=self.settings(),
                query=None,
                current_caption=None,
            ),
            (UpdateStatusIntent(""),),
        )
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.payload["draft"], "first\n\nsecond\nthird")
        self.assertEqual(editor.selection, "draft")
        self.assertEqual(controller.move_selection(1), (ClearAdjustmentFeedbackIntent(),))
        self.assertEqual(
            controller.handle_key(
                "\n",
                settings=self.settings(),
                query=None,
                current_caption=None,
            ),
            (ApplyCaptionIntent("first\n\nsecond\nthird"),),
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
            "voiceger_editor.query_editing.text_to_pronunciation",
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
            "voiceger_editor.query_editing.text_to_pronunciation",
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
            "voiceger_editor.query_editing.text_to_pronunciation",
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

    def test_add_section_language_arrow_feedback_only_on_change(self):
        query = mixed_query()
        controller, _provider = self.make_controller()
        controller.open_add_section(
            query,
            pure_japanese_utterance_text=None,
            origin=("add_section", None),
            busy=False,
        )
        editor = controller.editor
        controller.handle_key(
            "\n",
            settings=self.settings(),
            query=query,
            current_caption="Caption",
        )
        controller.move_selection(-1)
        self.assertEqual(editor.selection, "language")
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.payload["language"], "ja")

        moved_right = controller.handle_key(
            curses.KEY_RIGHT,
            settings=self.settings(),
            query=query,
            current_caption="Caption",
        )
        self.assertEqual(editor.payload["language"], "en")
        self.assertEqual(
            moved_right,
            (
                AdjustmentPressedIntent("editor", "language", 1),
                UpdateStatusIntent(""),
            ),
        )

        blocked_right = controller.handle_key(
            curses.KEY_RIGHT,
            settings=self.settings(),
            query=query,
            current_caption="Caption",
        )
        self.assertEqual(editor.payload["language"], "en")
        self.assertEqual(
            blocked_right,
            (ClearAdjustmentFeedbackIntent(),),
        )

        moved_left = controller.handle_key(
            curses.KEY_LEFT,
            settings=self.settings(),
            query=query,
            current_caption="Caption",
        )
        self.assertEqual(editor.payload["language"], "ja")
        self.assertEqual(
            moved_left,
            (
                AdjustmentPressedIntent("editor", "language", -1),
                UpdateStatusIntent(""),
            ),
        )

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
        self.assertEqual(confirmation.selection, "cancel")
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
            "voiceger_editor.query_editing.text_to_pronunciation",
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
            "d", settings=self.settings(), query=query, current_caption="Caption"
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


    def test_direct_japanese_delete_from_second_phrase_removes_entire_section(self):
        query = direct_japanese_query()
        original = query.model_dump()
        controller, _provider = self.make_controller()
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 1, origin=("pronunciation", 1), busy=False
        )
        controller.handle_key(
            "\\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertIn("delete_section", controller.selection_keys())
        controller.handle_key(
            "x", settings=self.settings(), query=query, current_caption="Caption"
        )
        confirmation = controller.editor
        self.assertEqual(confirmation.title, "DELETE SECTION?")
        self.assertEqual(confirmation.selection, "cancel")
        self.assertEqual(confirmation.payload["target_text"], "なのだ。")
        self.assertEqual(confirmation.payload["target_language"], "ja")
        intents = controller.handle_key(
            "d", settings=self.settings(), query=query, current_caption="Caption"
        )
        deletion = next(x for x in intents if isinstance(x, ReplaceQueryIntent))
        self.assertEqual(deletion.deleted_segment_index, 0)
        self.assertEqual(len(deletion.query.voicegerSegments), 1)
        self.assertEqual(deletion.query.voicegerSegments[0].language, "en")
        self.assertEqual(deletion.query.accent_phrases, [])
        self.assertEqual(query.model_dump(), original)

    def test_direct_english_delete_from_second_word_removes_entire_section(self):
        query = mixed_query()
        original = query.model_dump()
        groups = {
            "hello everyone": (
                ("hello", ("HH", "AH1", "L", "OW2")),
                ("everyone", ("EH1", "V", "R", "IY0")),
            )
        }
        controller, _provider = self.make_controller(groups)
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 3, origin=("pronunciation", 3), busy=False
        )
        controller.handle_key(
            "\\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.handle_key(
            "x", settings=self.settings(), query=query, current_caption="Caption"
        )
        confirmation = controller.editor
        self.assertEqual(confirmation.payload["target_text"], "hello everyone")
        self.assertEqual(confirmation.payload["target_language"], "en")
        intents = controller.handle_key(
            "d", settings=self.settings(), query=query, current_caption="Caption"
        )
        deletion = next(x for x in intents if isinstance(x, ReplaceQueryIntent))
        self.assertEqual(deletion.deleted_segment_index, 1)
        self.assertIsNone(deletion.query.voicegerSegments)
        self.assertEqual(deletion.pure_japanese_utterance_text, "明日は今日")
        self.assertEqual(query.model_dump(), original)

    def test_direct_delete_cancel_preserves_japanese_and_english_drafts(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller(
            {"hello": (("hello", ("HH", "AH1")),)}
        )
        for index, text in ((0, "ナ' ノダ'？"), (2, "HH AH0")):
            with self.subTest(index=index):
                rows = controller.pronunciation_rows(query, segments(query))
                controller.open_pronunciation_item(
                    query, rows, index, origin=("pronunciation", index), busy=False
                )
                controller.editor.input_value = text
                controller.handle_key(
                    "\\n", settings=self.settings(), query=query, current_caption="Caption"
                )
                parent = deepcopy(controller.editor)
                controller.handle_key(
                    "x", settings=self.settings(), query=query, current_caption="Caption"
                )
                result = controller.handle_key(
                    "\\x1b", settings=self.settings(), query=query, current_caption="Caption"
                )
                self.assertEqual(controller.editor, parent)
                self.assertEqual(controller.editor.input_value, text)
                self.assertFalse(any(isinstance(x, ReplaceQueryIntent) for x in result))

    def test_section_text_delete_uses_x_and_preserves_unsaved_draft_on_cancel(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller()
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        controller.handle_key(
            "\\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.handle_key(
            "e", settings=self.settings(), query=query, current_caption="Caption"
        )
        controller.editor.input_value = "changed draft"
        controller.handle_key(
            "\\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        saved_editor = deepcopy(controller.editor)
        self.assertNotIn("d", [
            item.shortcut for item in __import__(
                "voiceger_editor.tui_shortcuts", fromlist=["menu_items"]
            ).menu_items("section_text", {"can_delete": True})
        ])
        controller.handle_key(
            "x", settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertEqual(controller.editor.payload["target_text"], "なのだ。")
        controller.handle_key(
            "\\x1b", settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertEqual(controller.editor, saved_editor)
        self.assertEqual(controller.editor.payload["draft"], "changed draft")

    def test_stale_section_is_rejected_before_and_after_confirmation(self):
        query = direct_japanese_query()
        controller, _provider = self.make_controller()
        rows = controller.pronunciation_rows(query, segments(query))
        controller.open_pronunciation_item(
            query, rows, 0, origin=("pronunciation", 0), busy=False
        )
        controller.handle_key(
            "\\n", settings=self.settings(), query=query, current_caption="Caption"
        )
        changed = query.model_copy(deep=True)
        changed.voicegerSegments[0].text = "changed elsewhere"
        result = controller.handle_key(
            "x", settings=self.settings(), query=changed, current_caption="Caption"
        )
        self.assertEqual(result, ())
        self.assertEqual(controller.editor.kind, "japanese")
        self.assertIn("Selected section changed", str(controller.editor.error))
        controller.handle_key(
            "x", settings=self.settings(), query=query, current_caption="Caption"
        )
        self.assertEqual(controller.editor.kind, "delete_confirmation")
        result = controller.handle_key(
            "d", settings=self.settings(), query=changed, current_caption="Caption"
        )
        self.assertFalse(any(isinstance(x, ReplaceQueryIntent) for x in result))
        self.assertEqual(controller.editor.kind, "japanese")
        self.assertIn("selected section changed", str(controller.editor.error))

if __name__ == "__main__":
    unittest.main()
