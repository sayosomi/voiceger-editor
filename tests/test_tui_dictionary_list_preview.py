"""Focused Dictionary list Preview and debounced accent-save regression tests."""

import curses

from voiceger_editor.tui_dictionary_operations import DictionaryOperationIntent
from voiceger_editor.tui_editors import PreviewIntent
from voiceger_editor.tui_status import StatusKind
from tests.tui_dictionary_test_support import (
    DictionaryControllerTestCase,
    en_word,
    ja_word,
)


class DictionaryListPreviewAndAccentTests(DictionaryControllerTestCase):
    def _japanese(self):
        self.core.japanese["first"] = ja_word("あめ", "アメ", 1)
        self.core.japanese["second"] = ja_word("ぶどう", "ブドウ", 2)
        self.controller.open_menu()
        self.key("j")
        self.assertEqual(self.controller.editor.selection, ("entry", 0))

    def _commit(self):
        (operation,) = self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        )
        self.assertIsInstance(operation, DictionaryOperationIntent)
        self.assertEqual(operation.request.operation, "save_japanese_list_accents")
        operation.work()
        return self.controller.complete_operation(operation.request)

    def test_japanese_boundaries_and_visible_pending_preview(self):
        self._japanese()
        self.assertEqual(self.key(curses.KEY_LEFT), ())
        self.assertEqual(self.controller.editor.payload["entries"][0][1].accent_type, 1)

        self.key(curses.KEY_RIGHT)
        self.assertEqual(self.controller.editor.payload["entries"][0][1].accent_type, 2)
        self.assertEqual(self.core.japanese["first"].accent_type, 1)

        for key in (" ", "p"):
            preview = self.key(key)
            self.assertEqual(len(preview), 1)
            self.assertIsInstance(preview[0], PreviewIntent)
            self.assertEqual(preview[0].query.accent_phrases[0].accent, 2)
            self.assertEqual(self.controller.editor.selection, ("entry", 0))

        self.assertTrue(self.controller.has_unsaved_list_accents)
        self._commit()
        self.assertFalse(self.controller.has_unsaved_list_accents)
        self.assertEqual(self.core.japanese["first"].accent_type, 2)
        self.assertEqual(self.controller.editor.selection, ("entry", 0))

    def test_rapid_updates_and_inflight_newer_change_are_serialized(self):
        self._japanese()
        self.key(curses.KEY_RIGHT)
        self.key(curses.KEY_DOWN)
        self.key(curses.KEY_RIGHT)
        self.key(curses.KEY_LEFT)
        self.assertEqual(self.controller.editor.payload["entries"][1][1].accent_type, 2)

        (first,) = self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        )
        self.assertEqual(self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        ), ())
        self.key(curses.KEY_UP)
        self.controller.handle_key(curses.KEY_LEFT, dictionary_operation_busy=True)

        # Newer edit is visible while an older fixed snapshot is being saved.
        self.assertEqual(self.controller.editor.payload["entries"][0][1].accent_type, 1)
        first.work()
        self.controller.complete_operation(first.request)
        self.assertTrue(self.controller.has_unsaved_list_accents)
        self.assertEqual(self.controller.editor.payload["entries"][0][1].accent_type, 1)
        self._commit()
        self.assertEqual(self.core.japanese["first"].accent_type, 1)
        self.assertEqual(self.core.japanese["second"].accent_type, 2)
        self.assertFalse(self.controller.has_unsaved_list_accents)

    def test_save_then_leave_or_open_editor_without_dropping_pending_edits(self):
        self._japanese()
        self.key(curses.KEY_RIGHT)
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self._commit()
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")
        self.assertEqual(self.core.japanese["first"].accent_type, 2)

        self.key("j")
        self.key(curses.KEY_LEFT)
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self._commit()
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.payload["accent"], 1)

    def test_failed_commit_restores_core_and_reports_error(self):
        self._japanese()
        self.key(curses.KEY_RIGHT)
        (op,) = self.controller.pending_accent_commit(
            operation_busy=False, now=float("inf")
        )
        self.key("\x1b")
        result = self.controller.complete_operation(
            op.request, error=RuntimeError("compile failed")
        )
        self.assertEqual(result[0].status.kind, StatusKind.ERROR)
        self.assertIn("not saved", str(result[0].status))
        self.assertEqual(self.core.japanese["first"].accent_type, 1)
        self.assertEqual(self.controller.editor.payload["entries"][0][1].accent_type, 1)
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertFalse(self.controller.has_unsaved_list_accents)

    def test_sort_and_focus_after_pending_changes(self):
        self._japanese()
        self.key(curses.KEY_RIGHT)
        self.key("s")
        self.assertEqual(self.controller.editor.selection, "sort")
        self.assertEqual(self.controller.editor.payload["entries"][1][1].accent_type, 2)
        self.key(curses.KEY_UP)
        self.assertEqual(self.controller.editor.selection, ("entry", 1))
        self._commit()
        self.assertEqual(self.controller.editor.selection, ("entry", 1))

    def test_preview_only_works_for_focused_word_rows(self):
        self._japanese()
        self.key(curses.KEY_DOWN)
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "sort")
        self.assertEqual(self.key(" "), ())
        self.assertEqual(self.key("p"), ())
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "filter")
        self.assertEqual(self.key(" "), ())
        self.assertEqual(self.key("p"), ())

        self.controller.open_menu()
        self.key("e")
        self.assertEqual(self.key(" "), ())
        self.assertEqual(self.key("p"), ())

    def test_english_preview_is_read_only_and_left_right_does_not_adjust(self):
        self.core.english["hello"] = en_word(
            "hello", ["HH", "AH0", "L", "OW1"]
        )
        self.controller.open_menu()
        self.key("e")
        before = self.core.list_english_entries()
        for key in (" ", "p"):
            result = self.key(key)
            self.assertIsInstance(result[0], PreviewIntent)
            segments = result[0].query.voicegerSegments
            self.assertEqual(segments[0].text, "hello")
            self.assertEqual(list(segments[0].phonemes), ["HH", "AH0", "L", "OW1"])
            self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.key(curses.KEY_RIGHT)
        self.assertEqual(self.core.list_english_entries(), before)

    def test_preview_action_enter_targets_remembered_word_and_empty_is_safe(self):
        self._japanese()
        for _ in range(3):
            self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "preview")
        result = self.key("\n")
        self.assertIsInstance(result[0], PreviewIntent)
        self.assertEqual(self.controller.editor.selection, "preview")

        self.core.japanese.clear()
        self.controller.open_menu()
        self.key("j")
        self.assertEqual(self.key(" "), ())
        self.assertEqual(self.key("p"), ())
        self.controller.editor.selection = "preview"
        self.assertEqual(self.key("\n"), ())
