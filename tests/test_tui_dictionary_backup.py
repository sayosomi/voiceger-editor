"""TUI flows for review, destructive restore and pre-VOICEVOX warning."""

import curses
from pathlib import Path
from unittest.mock import patch

from voiceger_editor.dictionary_backup import ParsedDictionaryBackup, DictionaryBackupReview
from voiceger_editor.dictionary_import import DictionaryImportCommitResult
from voiceger_editor.tui_dictionary import DictionaryOperationIntent
from voiceger_editor.tui_status import StatusKind
from voiceger_editor.user_dictionary import EnglishUserDictionaryEntry
from tests.tui_dictionary_test_support import DictionaryControllerTestCase, import_ja_word


class TuiDictionaryBackupTests(DictionaryControllerTestCase):
    def _review(self, restore):
        parsed = ParsedDictionaryBackup(
            source_path=Path("/tmp/dictionaries.zip"),
            japanese_entries=((
                "11111111-1111-4111-8111-111111111111",
                import_ja_word("雨", "アメ", 1),
            ),),
            english_entries=(
                EnglishUserDictionaryEntry(surface="Alpha", phonemes=["AE1", "L", "F", "AH0"]),
            ),
            pitch_events=(),
        )
        return DictionaryBackupReview(parsed, self.core, restore=restore)

    def _open_review(self, restore):
        self.controller.open_menu()
        self.key("r" if restore else "i")
        path_editor = self.controller.editor
        self.assertEqual(path_editor.kind, "dictionary_import_path")
        self.assertTrue(bool(path_editor.payload["restore"]) is restore)
        path_editor.active_field = None
        path_editor.payload["path"] = "/tmp/dictionaries.zip"
        review = self._review(restore)
        if restore:
            target = "voiceger_editor.tui_dictionary_import.prepare_dictionary_backup"
        else:
            target = "voiceger_editor.tui_dictionary_import.prepare_dictionary_import"
        with patch(target, return_value=review):
            self.finish_operation(self.key("i"))
        return review

    def test_zip_merge_shows_both_languages_and_can_toggle_each(self):
        review = self._open_review(False)
        editor = self.controller.editor
        self.assertEqual(editor.kind, "dictionary_import_review")
        self.assertEqual(editor.payload["language_counts"], (1, 1))
        self.assertEqual(editor.payload["review_count"], 2)
        self.assertEqual([item.incoming.surface for item in editor.payload["items"]],
                         ["雨", "Alpha"])
        self.assertTrue(all(item.selected for item in editor.payload["items"]))
        self.key(" ")
        self.assertFalse(self.controller.editor.payload["items"][0].selected)
        self.key(curses.KEY_DOWN)
        self.key(" ")
        self.assertFalse(self.controller.editor.payload["items"][1].selected)
        self.assertFalse(any(item.selected for item in review.items))

    def test_restore_defaults_cancel_shows_deletions_and_requires_second_confirm(self):
        review = self._open_review(True)
        self.assertEqual(self.controller.editor.kind, "dictionary_restore_review")
        self.assertEqual(self.controller.editor.selection, "cancel")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

        review = self._open_review(True)
        self.key("r")
        self.assertEqual(self.controller.editor.kind, "dictionary_restore_confirmation")
        self.assertEqual(self.controller.editor.selection, "cancel")
        self.assertIn("Delete 0 local Japanese", self.controller.editor.payload["warning"])
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_restore_review")
        self.key("r")
        with patch.object(
            review, "commit",
            return_value=DictionaryImportCommitResult(imported=2, replaced=0, skipped=0),
        ) as commit:
            operation, completion = self.finish_operation(self.key("r"))
        commit.assert_called_once_with(self.core, confirmed=True)
        self.assertEqual(operation.request.operation, "commit_dictionary_import")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")
        self.assertIn("Dictionary backup restored", str(completion[0].status))

    def test_voicevox_warns_before_any_write_and_cancel_keeps_export_screen(self):
        self.core.pitch_events["multi"] = ("additional",)
        self.controller.open_menu()
        self.key("x")
        self.assertEqual(self.controller.editor.kind, "dictionary_export")
        with patch(
            "voiceger_editor.tui_dictionary_export.export_voicevox_dictionary"
        ) as exporter:
            self.key("v")
            self.assertEqual(self.controller.editor.kind,
                             "dictionary_voicevox_loss_confirmation")
            self.assertEqual(self.controller.editor.selection, "cancel")
            self.key("\n")
            self.assertEqual(self.controller.editor.kind, "dictionary_export")
            exporter.assert_not_called()
            self.key("v")
            self.assertEqual(self.controller.editor.kind,
                             "dictionary_voicevox_loss_confirmation")
            intents = self.key("e")
            operation = next(i for i in intents if isinstance(i, DictionaryOperationIntent))
            self.assertEqual(operation.request.operation, "export_voicevox")
            self.assertEqual(self.controller.editor.kind, "dictionary_export")


if __name__ == "__main__":
    import unittest
    unittest.main()
