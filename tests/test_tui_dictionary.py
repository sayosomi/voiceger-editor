import curses
import unittest
from types import SimpleNamespace

from voiceger_accent_adapter.openjtalk_dictionary import expand_word_type, normalize_surface
from voiceger_accent_adapter.tui_dictionary import TuiDictionaryController
from voiceger_accent_adapter.tui_editors import PreviewIntent
from voiceger_accent_adapter.user_dictionary import JapaneseWordType


def ja_word(surface, pronunciation="ズンダモン", accent=3, *, priority=5, word_type=JapaneseWordType.PROPER_NOUN):
    expanded = expand_word_type(word_type.value)
    return SimpleNamespace(
        surface=normalize_surface(surface),
        pronunciation=pronunciation,
        accent_type=accent,
        priority=priority,
        context_id=expanded["context_id"],
    )


def en_word(surface, phonemes):
    return SimpleNamespace(surface=surface, phonemes=list(phonemes))


class FakeDictionaryCore:
    def __init__(self):
        self.japanese = {}
        self.english = {}
        self.next_id = 1

    def list_japanese_entries(self):
        return dict(self.japanese)

    def list_english_entries(self):
        return dict(self.english)

    def add_japanese_word(self, **values):
        word_uuid = f"word-{self.next_id}"
        self.next_id += 1
        self.japanese[word_uuid] = ja_word(
            values["surface"],
            values["pronunciation"],
            values["accent_type"],
            priority=values["priority"],
            word_type=values["word_type"],
        )
        return word_uuid

    def update_japanese_word(self, word_uuid, **values):
        self.japanese[word_uuid] = ja_word(
            values["surface"],
            values["pronunciation"],
            values["accent_type"],
            priority=values["priority"],
            word_type=values["word_type"],
        )

    def delete_japanese_word(self, word_uuid):
        del self.japanese[word_uuid]

    def set_english_entry(self, surface, phonemes):
        key = surface.strip().casefold()
        self.english = {
            old_surface: entry
            for old_surface, entry in self.english.items()
            if old_surface.strip().casefold() != key
        }
        entry = en_word(surface, phonemes)
        self.english[surface] = entry
        return entry

    def update_english_entry(self, original_surface, *, surface, phonemes):
        original_key = original_surface.strip().casefold()
        if not any(
            old_surface.strip().casefold() == original_key
            for old_surface in self.english
        ):
            raise ValueError("not found")
        for old_surface in tuple(self.english):
            if old_surface.strip().casefold() == original_key:
                del self.english[old_surface]
        entry = en_word(surface, phonemes)
        self.english[surface] = entry
        return entry

    def delete_english_entry(self, surface):
        key = surface.strip().casefold()
        for old_surface in tuple(self.english):
            if old_surface.strip().casefold() == key:
                del self.english[old_surface]
                return
        raise ValueError("not found")


class TuiDictionaryControllerTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeDictionaryCore()
        self.controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
        )

    def key(self, value):
        return self.controller.handle_key(value)

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

        self.key("b")
        self.key(curses.KEY_DOWN)
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(
            [entry.surface for entry in self.controller.editor.payload["entries"]],
            ["Apple", "zebra"],
        )

    def test_empty_list_still_exposes_add_and_back(self):
        self.controller.open_menu()
        self.key("\n")

        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(self.controller.editor.payload["entries"], ())
        self.assertEqual(self.controller.editor.selection, "add")

        self.key("a")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.title, "ADD JAPANESE DICTIONARY WORD")

    def test_japanese_quick_save_prefills_current_edit_and_updates_existing(self):
        self.core.japanese["existing"] = ja_word(
            "ずんだもん", "ズンダモン", 4, priority=7
        )

        self.controller.open_quick_save_japanese(
            surface="ずんだもん",
            pronunciation="ズン'ダモン",
        )

        editor = self.controller.editor
        self.assertEqual(editor.kind, "dictionary_japanese_entry")
        self.assertEqual(editor.payload["word_uuid"], "existing")
        self.assertEqual(editor.payload["pronunciation"], "ズンダモン")
        self.assertEqual(editor.payload["accent"], 2)
        self.assertEqual(editor.payload["priority"], 7)

        self.key("s")

        self.assertIsNone(self.controller.editor)
        saved = self.core.japanese["existing"]
        self.assertEqual(saved.pronunciation, "ズンダモン")
        self.assertEqual(saved.accent_type, 2)
        self.assertEqual(saved.priority, 7)

    def test_duplicate_japanese_surface_requires_selection_before_editing(self):
        self.core.japanese["first"] = ja_word("ABC", "エービーシー", 2)
        self.core.japanese["second"] = ja_word("ＡＢＣ", "アブク", 1)

        self.controller.open_quick_save_japanese(
            surface="ABC",
            pronunciation="エー'ビーシー",
        )

        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_japanese_duplicates",
        )
        self.assertEqual(len(self.core.japanese), 2)

        self.key(curses.KEY_DOWN)
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.payload["word_uuid"], "second")

    def test_japanese_adjustments_preview_and_save_are_independent(self):
        self.controller.open_quick_save_japanese(
            surface="ずんだもん",
            pronunciation="ズン'ダモン",
        )
        editor = self.controller.editor

        editor.selection = "pronunciation"
        self.key(curses.KEY_RIGHT)
        self.assertEqual(editor.payload["accent"], 3)
        self.key(curses.KEY_LEFT)
        self.assertEqual(editor.payload["accent"], 2)

        editor.selection = "word_type"
        self.key(curses.KEY_RIGHT)
        self.assertEqual(editor.payload["word_type"], JapaneseWordType.COMMON_NOUN)
        editor.payload["word_type"] = JapaneseWordType.SUFFIX
        self.key(curses.KEY_RIGHT)
        self.assertEqual(editor.payload["word_type"], JapaneseWordType.PROPER_NOUN)
        self.key(curses.KEY_LEFT)
        self.assertEqual(editor.payload["word_type"], JapaneseWordType.SUFFIX)

        editor.selection = "pronunciation"
        editor.payload["accent"] = 1
        self.key(curses.KEY_LEFT)
        self.assertEqual(editor.payload["accent"], 1)

        editor.selection = "priority"
        editor.payload["priority"] = 10
        self.key(curses.KEY_RIGHT)
        self.assertEqual(editor.payload["priority"], 10)
        editor.payload["priority"] = 0
        self.key(curses.KEY_LEFT)
        self.assertEqual(editor.payload["priority"], 0)

        before = dict(self.core.japanese)
        editor.selection = "preview"
        intents = self.key("\n")
        self.assertIsInstance(intents[0], PreviewIntent)
        self.assertEqual(self.core.japanese, before)

    def test_dirty_back_and_escape_require_discard_confirmation(self):
        self.controller.open_quick_save_english(
            surface="Voiceger",
            phonemes="V OY1 AH0 JH ER0",
        )
        editor = self.controller.editor
        editor.payload["surface"] = "Voiceger2"

        self.key("b")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_discard_confirmation",
        )

        self.key("b")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.key("\x1b")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_discard_confirmation",
        )
        self.key("d")
        self.assertIsNone(self.controller.editor)

    def test_english_quick_save_moves_primary_stress_and_persists(self):
        self.controller.open_quick_save_english(
            surface="record",
            phonemes="R EH1 K ER0 D",
        )
        editor = self.controller.editor
        editor.selection = "phonemes"

        self.key(curses.KEY_RIGHT)

        self.assertEqual(
            editor.payload["phonemes"],
            ("R", "EH0", "K", "ER1", "D"),
        )
        self.key("s")
        self.assertIsNone(self.controller.editor)
        self.assertEqual(
            self.core.english["record"].phonemes,
            ["R", "EH0", "K", "ER1", "D"],
        )

    def test_management_crud_and_delete_confirmation_for_both_languages(self):
        self.controller.open_menu()
        self.key("\n")
        self.key("a")
        editor = self.controller.editor
        editor.payload.update(
            surface="雨",
            pronunciation="アメ",
            moras=("ア", "メ"),
            accent=1,
        )
        self.key("s")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(len(self.core.japanese), 1)

        self.controller.editor.selection = ("entry", 0)
        self.key("x")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_delete_confirmation",
        )
        self.key("d")
        self.assertEqual(self.core.japanese, {})

        self.key("b")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")
        self.assertEqual(self.controller.editor.payload["japanese_count"], 0)
        self.key(curses.KEY_DOWN)
        self.key("\n")
        self.key("a")
        editor = self.controller.editor
        editor.payload["surface"] = "hello"
        editor.payload["phonemes"] = ("HH", "AH0", "L", "OW1")
        self.key("s")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertIn("hello", self.core.english)

        self.controller.editor.selection = ("entry", 0)
        self.key("x")
        self.key("d")
        self.assertEqual(self.core.english, {})

    def test_management_edit_existing_entries_for_both_languages(self):
        self.core.japanese["existing-ja"] = ja_word("雨", "アメ", 1)
        self.core.english["hello"] = en_word("hello", ["HH", "AH0", "L", "OW1"])

        self.controller.open_menu()
        self.key("\n")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")

        self.key("\n")
        self.controller.editor.input_value = "飴"
        self.controller.editor.input_cursor = 1
        self.key("\n")
        self.key("s")

        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(self.core.japanese["existing-ja"].surface, normalize_surface("飴"))

        self.key("b")
        self.key(curses.KEY_DOWN)
        self.key("\n")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")

        self.key("\n")
        self.controller.editor.input_value = "hello2"
        self.controller.editor.input_cursor = len("hello2")
        self.key("\n")
        self.key("s")

        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertNotIn("hello", self.core.english)
        self.assertIn("hello2", self.core.english)

    def test_dictionary_shortcut_from_entry_opens_top_level_menu_and_back_restores_draft(self):
        self.controller.open_quick_save_english(
            surface="hello",
            phonemes="HH AH0 L OW1",
        )
        entry = self.controller.editor
        entry.payload["surface"] = "hello-draft"

        self.key("d")

        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

        self.key("b")

        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.assertEqual(self.controller.editor.payload["surface"], "hello-draft")
        self.assertTrue(self.controller.editor.payload["quick_save"])


if __name__ == "__main__":
    unittest.main()
