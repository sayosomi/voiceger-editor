"""Top-level Dictionary coordination and routing regression tests."""

import curses
import os

from voiceger_editor.openjtalk_dictionary import normalize_surface
from tests.tui_dictionary_test_support import (
    DictionaryControllerTestCase,
    en_word,
    ja_word,
)


class TuiDictionaryControllerTests(DictionaryControllerTestCase):
    def test_menu_counts_and_lists_are_surface_sorted(self):
        self.core.japanese["b"] = ja_word("ぶどう")
        self.core.japanese["a"] = ja_word("あめ", "アメ", 1)
        self.core.english["zebra"] = en_word("zebra", ["Z", "IY1", "B", "R", "AH0"])
        self.core.english["Apple"] = en_word("Apple", ["AE1", "P", "AH0", "L"])

        self.controller.open_menu()
        self.assertEqual(self.controller.editor.payload["japanese_count"], 2)
        self.assertEqual(self.controller.editor.payload["english_count"], 2)

        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(
            [word.surface for _uuid, word in self.controller.editor.payload["entries"]],
            [normalize_surface("あめ"), normalize_surface("ぶどう")],
        )

        self.key("\x1b")
        self.key(curses.KEY_DOWN)
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(
            [entry.surface for entry in self.controller.editor.payload["entries"]],
            ["Apple", "zebra"],
        )

    def test_menu_language_shortcuts_open_each_dictionary(self):
        self.controller.open_menu()

        self.key("e")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")

        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

        self.key("j")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")

    def test_import_is_reachable_from_top_level_menu_and_opens_path_input(self):
        self.controller.open_menu()

        self.key(curses.KEY_DOWN)
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "import")

        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_import_path")
        self.assertEqual(self.controller.editor.selection, "path")
        self.assertEqual(self.controller.editor.active_field, "path")
        self.assertEqual(self.controller.editor.input_value, "." + os.sep)

        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

        self.key("i")
        self.assertEqual(self.controller.editor.kind, "dictionary_import_path")
        self.assertEqual(self.controller.editor.active_field, "path")
        self.key("\n")
        self.assertIsNone(self.controller.editor.active_field)
        self.key("f")
        self.assertEqual(self.controller.editor.active_field, "path")

    def test_dictionary_lists_use_one_vertical_navigation_list(self):
        self.core.japanese["first"] = ja_word("あめ", "アメ", 1)
        self.core.japanese["second"] = ja_word("ぶどう")
        self.controller.open_menu()
        self.key("j")

        self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, ("entry", 1))
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "sort")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "filter")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "add")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "delete")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "back")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "back")
        self.key(curses.KEY_UP)
        self.assertEqual(self.controller.editor.selection, "delete")

        self.key("\n")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_delete_confirmation",
        )
        self.assertEqual(
            self.controller.editor.payload["surface"],
            normalize_surface("ぶどう"),
        )

        self.key("\x1b")
        self.key("\x1b")
        self.core.english["hello"] = en_word("hello", ["HH", "AH0", "L", "OW1"])
        self.key("e")

        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "sort")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "filter")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "add")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "delete")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "back")

    def test_completion_does_not_apply_result_to_a_different_dictionary_editor(self):
        self.controller.open_quick_save_english(
            surface="hello",
            phonemes="HH AH0",
        )
        operation = self.operation(self.controller.handle_key("g"))
        other_editor = self.controller._menu_state()
        self.controller.editor = other_editor

        completion = self.controller.complete_operation(
            operation.request,
            ("HH", "AH1"),
        )

        self.assertEqual(len(completion), 1)
        self.assertEqual(completion[0].status, "")
        self.assertIs(self.controller.editor, other_editor)
        self.assertNotIn("phonemes", other_editor.payload)
