"""Focused regression tests for Dictionary Import interaction ownership."""

import curses
from unittest.mock import patch

from voiceger_editor.dictionary_import import (
    DictionaryImportRelation,
    EnglishDictionaryImportReview,
    JapaneseDictionaryImportReview,
)
from voiceger_editor.tui_dictionary import DictionaryOperationIntent
from voiceger_editor.tui_status import StatusKind
from voiceger_editor.user_dictionary import (
    EnglishUserDictionaryEntry,
    JapaneseWordType,
)
from tests.tui_dictionary_test_support import (
    DictionaryControllerTestCase,
    en_word,
    import_ja_word,
)


class TuiDictionaryImportTests(DictionaryControllerTestCase):
    def _open_import_review(self, review):
        owner = self.controller._import_owner
        owner._import_review = review
        owner._import_source_path = "/tmp/dictionary.json"
        self.controller._stack.clear()
        self.controller._stack.append(self.controller._menu_state())
        self.controller.editor = owner._import_review_state()

    def test_import_review_uses_one_vertical_list_toggle_clear_and_back(self):
        review = EnglishDictionaryImportReview(
            {
                "Existing": EnglishUserDictionaryEntry(
                    surface="Existing",
                    phonemes=["IH0", "G", "Z", "IH1", "S", "T", "IH0", "NG"],
                ),
                "Same": EnglishUserDictionaryEntry(
                    surface="Same",
                    phonemes=["S", "EY1", "M"],
                ),
            },
            [
                EnglishUserDictionaryEntry(
                    surface="Existing",
                    phonemes=["EH1", "G", "Z", "IH0", "S", "T", "IH0", "NG"],
                ),
                EnglishUserDictionaryEntry(
                    surface="New",
                    phonemes=["N", "UW1"],
                ),
                EnglishUserDictionaryEntry(
                    surface="Same",
                    phonemes=["S", "EY1", "M"],
                ),
            ],
        )
        self.controller.open_menu()
        self.key("i")
        editor = self.controller.editor
        editor.payload["path"] = "/tmp/dictionary.json"
        editor.active_field = None

        with patch(
            "voiceger_editor.tui_dictionary_import.prepare_dictionary_import",
            return_value=review,
        ):
            intents = self.key("i")
            _operation, completion = self.finish_operation(intents)
        self.assertTrue(completion)
        self.assertEqual(self.controller.editor.kind, "dictionary_import_review")
        self.assertEqual(self.controller.editor.payload["total_count"], 3)
        self.assertEqual(self.controller.editor.payload["exact_duplicate_count"], 1)
        self.assertEqual(len(self.controller.editor.payload["items"]), 2)
        self.assertFalse(self.controller.editor.payload["items"][0].selected)
        self.assertTrue(self.controller.editor.payload["items"][1].selected)

        self.assertEqual(self.controller.editor.selection, ("import_entry", 0))
        self.key(" ")
        self.assertTrue(self.controller.editor.payload["items"][0].selected)
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, ("import_entry", 1))
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "import_selected")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "clear_selection")
        self.key("\n")
        self.assertTrue(
            all(not item.selected for item in self.controller.editor.payload["items"])
        )
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "back")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

    def test_import_japanese_detail_only_adjusts_word_type_and_reclassifies(self):
        existing = import_ja_word(
            "雨",
            "アメ",
            1,
            word_type=JapaneseWordType.PROPER_NOUN,
        )
        incoming = import_ja_word(
            "雨",
            "アメ",
            1,
            word_type=JapaneseWordType.COMMON_NOUN,
            priority=6,
        )
        review = JapaneseDictionaryImportReview(
            {"existing": existing},
            [("11111111-1111-4111-8111-111111111111", incoming)],
        )
        self.controller._import_owner._import_review = review
        self.controller._import_owner._import_source_path = "/tmp/japanese.json"
        self.controller.editor = self.controller._import_owner._import_review_state()
        self.assertEqual(
            self.controller.editor.payload["word_type_labels"],
            ("普通名詞",),
        )

        self.key("\n")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_import_japanese_detail",
        )
        self.assertEqual(self.controller.editor.selection, "word_type")
        self.assertEqual(self.controller.editor.payload["word_type_label"], "普通名詞")
        before = self.controller.editor.payload["item"]
        self.assertIs(before.relation, DictionaryImportRelation.NEW)

        self.key(curses.KEY_LEFT)
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_import_japanese_detail",
        )
        after = self.controller.editor.payload["item"]
        self.assertIs(after.relation, DictionaryImportRelation.CONFLICT)
        self.assertIsNotNone(after.existing)
        self.assertEqual(
            self.controller.editor.payload["word_type"],
            JapaneseWordType.PROPER_NOUN,
        )
        self.assertEqual(self.controller.editor.payload["word_type_label"], "固有名詞")
        self.assertEqual(
            self.controller.editor.payload["existing_word_type_label"],
            "固有名詞",
        )
        self.assertFalse(after.selected)

        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_import_review")
        self.assertEqual(
            self.controller.editor.payload["word_type_labels"],
            ("固有名詞",),
        )

    def test_import_commit_refreshes_menu_and_reports_counts(self):
        review = EnglishDictionaryImportReview(
            {},
            [
                EnglishUserDictionaryEntry(
                    surface="Voiceger",
                    phonemes=["V", "OY1", "AH0", "JH", "ER0"],
                )
            ],
        )
        self.controller.open_menu()
        self._open_import_review(review)

        self.controller.editor.selection = "import_selected"
        intents = self.key("\n")
        operation, completion = self.finish_operation(intents)

        self.assertEqual(operation.request.operation, "commit_dictionary_import")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")
        self.assertEqual(self.controller.editor.payload["english_count"], 1)
        self.assertIn("Voiceger", self.core.english)
        self.assertIn("1 imported", str(completion[0].status))
        self.assertIn("0 replaced", str(completion[0].status))
        self.assertIn("0 skipped", str(completion[0].status))

    def test_import_commit_failure_keeps_review_available_and_reports_error(self):
        review = EnglishDictionaryImportReview(
            {},
            [
                EnglishUserDictionaryEntry(
                    surface="Voiceger",
                    phonemes=["V", "OY1", "AH0", "JH", "ER0"],
                )
            ],
        )
        self.controller.open_menu()
        self._open_import_review(review)
        editor = self.controller.editor
        editor.selection = "import_selected"
        operation = self.operation(self.key("\n"))

        with patch.object(review, "commit", side_effect=RuntimeError("commit failed")):
            try:
                operation.work()
            except Exception as exc:
                completion = self.controller.complete_operation(
                    operation.request,
                    error=exc,
                )
            else:
                self.fail("Import commit unexpectedly succeeded")

        self.assertIs(self.controller.editor, editor)
        self.assertEqual(editor.kind, "dictionary_import_review")
        self.assertEqual(editor.error.kind, StatusKind.ERROR)
        self.assertEqual(
            completion[0].status,
            "Dictionary import was not completed: commit failed",
        )

    def test_invalid_import_load_keeps_dictionary_and_path_screen(self):
        self.core.english["Keep"] = en_word("Keep", ["K", "IY1", "P"])
        before = dict(self.core.english)
        self.controller.open_menu()
        self.key("i")
        self.controller.editor.payload["path"] = "/missing.json"
        self.controller.editor.active_field = None

        with patch(
            "voiceger_editor.tui_dictionary_import.prepare_dictionary_import",
            side_effect=ValueError("bad dictionary"),
        ):
            intents = self.key("i")
            operation = self.operation(intents)
            try:
                operation.work()
            except Exception as exc:
                completion = self.controller.complete_operation(
                    operation.request,
                    error=exc,
                )
            else:
                self.fail("invalid import unexpectedly loaded")

        self.assertEqual(self.core.english, before)
        self.assertEqual(self.controller.editor.kind, "dictionary_import_path")
        self.assertIn("bad dictionary", str(completion[0].status))
