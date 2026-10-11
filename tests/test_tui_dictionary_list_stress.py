"""English Dictionary list primary-stress editing, debounce and routing tests."""

import curses

from voiceger_editor.tui_dictionary_operations import DictionaryOperationIntent
from voiceger_editor.tui_editors import PreviewIntent
from voiceger_editor.tui_status import StatusKind
from tests.tui_dictionary_test_support import (
    DictionaryControllerTestCase,
    en_word,
)


class EnglishDictionaryListStressTests(DictionaryControllerTestCase):
    def _english(self):
        self.core.english["Zebra"] = en_word(
            "Zebra", ["Z", "IY1", "B", "R", "AH0"]
        )
        self.core.english["Alpha"] = en_word(
            "Alpha", ["AE1", "L", "F", "AH2"]
        )
        self.controller.open_menu()
        self.key("e")
        self.assertEqual(self.controller.editor.selection, ("entry", 0))

    def _commit(self):
        (op,) = self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        )
        self.assertIsInstance(op, DictionaryOperationIntent)
        self.assertEqual(op.request.operation, "save_english_list_stresses")
        op.work()
        return self.controller.complete_operation(op.request)

    def test_move_is_bounded_and_preview_uses_pending_visible_tokens(self):
        self._english()
        self.assertEqual(self.controller.editor.payload["entries"][0].surface, "Alpha")
        self.key(curses.KEY_LEFT)
        self.key(curses.KEY_RIGHT)
        word = self.controller.editor.payload["entries"][0]
        self.assertEqual(word.phonemes, ["AE2", "L", "F", "AH1"])
        self.assertEqual(self.core.english["Alpha"].phonemes, ["AE1", "L", "F", "AH2"])
        for key in (" ", "p", "P"):
            (intent,) = self.key(key)
            self.assertIsInstance(intent, PreviewIntent)
            self.assertEqual(
                intent.query.voicegerSegments[0].phonemes,
                ["AE2", "L", "F", "AH1"],
            )
        self.key(curses.KEY_RIGHT)
        self.assertEqual(self.controller.editor.payload["entries"][0].phonemes, word.phonemes)
        self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.assertTrue(self.controller.has_unsaved_list_accents)
        self._commit()
        self.assertFalse(self.controller.has_unsaved_list_accents)
        self.assertEqual(self.core.english["Alpha"].phonemes, ["AE2", "L", "F", "AH1"])

    def test_absent_multiple_and_single_vowel_primary_are_not_adjustable(self):
        for phonemes in (
            ["HH", "AH0", "L", "OW0"],
            ["HH", "AH1", "L", "OW1"],
            ["HH", "AH1", "L"],
            ["HH", "IH"],
        ):
            with self.subTest(phonemes=phonemes):
                self.core.english = {"Test": en_word("Test", phonemes)}
                self.controller.open_menu()
                self.key("e")
                self.key(curses.KEY_LEFT)
                self.key(curses.KEY_RIGHT)
                self.assertEqual(
                    self.controller.editor.payload["entries"][0].phonemes, phonemes
                )
                self.assertFalse(self.controller.has_unsaved_list_accents)

    def test_legacy_unmarked_vowel_moves_with_existing_stress_rules(self):
        self.core.english["Legacy"] = en_word("Legacy", ["ER", "AH1"])
        self.controller.open_menu()
        self.key("e")
        self.key(curses.KEY_LEFT)
        self.assertEqual(
            self.controller.editor.payload["entries"][0].phonemes, ["ER1", "AH0"]
        )
        self._commit()
        self.assertEqual(self.core.english["Legacy"].phonemes, ["ER1", "AH0"])

    def test_switch_sort_and_concurrent_older_save_do_not_lose_newer_edits(self):
        self._english()
        self.key(curses.KEY_RIGHT)
        (first,) = self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        )
        self.assertEqual(self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        ), ())
        self.key(curses.KEY_LEFT)
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, ("entry", 1))
        self.key(curses.KEY_RIGHT)
        self.key("s")
        self.assertEqual(self.controller.editor.selection, "sort")
        first.work()
        self.controller.complete_operation(first.request)
        self.assertTrue(self.controller.has_unsaved_list_accents)
        self._commit()
        self.assertFalse(self.controller.has_unsaved_list_accents)
        self.assertEqual(self.core.english["Alpha"].phonemes, ["AE1", "L", "F", "AH2"])
        self.assertEqual(self.core.english["Zebra"].phonemes, ["Z", "IY0", "B", "R", "AH1"])

    def test_navigation_and_detail_editor_wait_for_persistence(self):
        self._english()
        self.key(curses.KEY_RIGHT)
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self._commit()
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")
        self.key("e")
        self.key(curses.KEY_LEFT)
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self._commit()
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.assertEqual(
            tuple(self.controller.editor.payload["phonemes"]),
            ("AE1", "L", "F", "AH2"),
        )

    def test_commit_failure_rolls_back_and_reports_error(self):
        self._english()
        self.key(curses.KEY_RIGHT)
        (op,) = self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        )
        self.key("\x1b")
        result = self.controller.complete_operation(
            op.request, error=OSError("disk full")
        )
        self.assertEqual(result[0].status.kind, StatusKind.ERROR)
        self.assertIn("not saved", str(result[0].status))
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.core.english["Alpha"].phonemes, ["AE1", "L", "F", "AH2"])
        self.assertEqual(
            self.controller.editor.payload["entries"][0].phonemes,
            ["AE1", "L", "F", "AH2"],
        )
        self.assertFalse(self.controller.has_unsaved_list_accents)

    def test_nonword_rows_do_not_adjust_or_preview(self):
        self._english()
        self.key(curses.KEY_DOWN)
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "sort")
        before = self.core.list_english_entries()
        self.assertEqual(self.key(" "), ())
        self.assertEqual(self.key("p"), ())
        self.key(curses.KEY_RIGHT)
        self.assertEqual(self.core.list_english_entries(), before)
        self.assertFalse(self.controller.has_unsaved_list_accents)
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "filter")
        self.key(curses.KEY_LEFT)
        self.assertFalse(self.controller.has_unsaved_list_accents)
