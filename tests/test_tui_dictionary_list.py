import curses
import unittest
from types import SimpleNamespace

from voiceger_editor.openjtalk_dictionary import expand_word_type, normalize_surface
from voiceger_editor.tui_dictionary import (
    DictionaryOperationIntent,
    TuiDictionaryController,
)
from voiceger_editor.tui_dictionary_list import DictionaryListStateOwner
from voiceger_editor.user_dictionary import JapaneseWordType


def ja_word(
    surface,
    pronunciation="ズンダモン",
    accent=3,
    *,
    priority=5,
    word_type=JapaneseWordType.PROPER_NOUN,
):
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
        identity = f"new-{self.next_id}"
        self.next_id += 1
        self.japanese[identity] = ja_word(
            values["surface"],
            values["pronunciation"],
            values["accent_type"],
            priority=values["priority"],
            word_type=values["word_type"],
        )
        return identity

    def update_japanese_word(self, identity, **values):
        self.japanese[identity] = ja_word(
            values["surface"],
            values["pronunciation"],
            values["accent_type"],
            priority=values["priority"],
            word_type=values["word_type"],
        )

    def delete_japanese_word(self, identity):
        del self.japanese[identity]

    def set_english_entry(self, surface, phonemes):
        entry = en_word(surface, phonemes)
        key = surface.strip().casefold()
        for old_surface in tuple(self.english):
            if old_surface.strip().casefold() == key:
                self.english[old_surface] = entry
                if old_surface != surface:
                    self.english = {
                        surface if name == old_surface else name: value
                        for name, value in self.english.items()
                    }
                return entry
        self.english[surface] = entry
        return entry

    def update_english_entry(self, original_surface, *, surface, phonemes):
        original_key = original_surface.strip().casefold()
        entry = en_word(surface, phonemes)
        updated = {}
        replaced = False
        for old_surface, old_entry in self.english.items():
            if old_surface.strip().casefold() == original_key:
                updated[surface] = entry
                replaced = True
            else:
                updated[old_surface] = old_entry
        if not replaced:
            raise ValueError("not found")
        self.english = updated
        return entry

    def delete_english_entry(self, surface):
        key = surface.strip().casefold()
        for old_surface in tuple(self.english):
            if old_surface.strip().casefold() == key:
                del self.english[old_surface]
                return
        raise ValueError("not found")


class DictionaryListStateOwnerTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeDictionaryCore()
        self.owner = DictionaryListStateOwner(self.core)

    @staticmethod
    def identities(view):
        return list(view.identities)

    def test_all_japanese_sort_modes_and_canonical_added_order(self):
        self.core.japanese = {
            "proper": ja_word(
                "delta",
                priority=5,
                word_type=JapaneseWordType.PROPER_NOUN,
            ),
            "verb": ja_word(
                "charlie",
                priority=1,
                word_type=JapaneseWordType.VERB,
            ),
            "common": ja_word(
                "bravo",
                priority=9,
                word_type=JapaneseWordType.COMMON_NOUN,
            ),
            "adjective": ja_word(
                "echo",
                priority=5,
                word_type=JapaneseWordType.ADJECTIVE,
            ),
            "suffix": ja_word(
                "alpha",
                priority=3,
                word_type=JapaneseWordType.SUFFIX,
            ),
        }
        canonical = list(self.core.japanese)

        expected = {
            "surface_asc": ["suffix", "common", "verb", "proper", "adjective"],
            "surface_desc": ["adjective", "proper", "verb", "common", "suffix"],
            "word_type": ["proper", "common", "verb", "adjective", "suffix"],
            "priority_asc": ["verb", "suffix", "proper", "adjective", "common"],
            "priority_desc": ["common", "proper", "adjective", "suffix", "verb"],
            "added_asc": ["proper", "verb", "common", "adjective", "suffix"],
            "added_desc": ["suffix", "adjective", "common", "verb", "proper"],
        }
        for sort_mode, identities in expected.items():
            with self.subTest(sort_mode=sort_mode):
                self.owner.set_japanese_sort(sort_mode)
                self.assertEqual(self.identities(self.owner.japanese_view()), identities)
                self.assertEqual(list(self.core.japanese), canonical)

    def test_all_english_sort_modes_and_canonical_added_order(self):
        self.core.english = {
            "zebra": en_word("zebra", ["Z", "IY1", "B", "R", "AH0"]),
            "Apple": en_word("Apple", ["AE1", "P", "AH0", "L"]),
            "record": en_word("record", ["R", "EH1", "K", "ER0", "D"]),
        }
        canonical = list(self.core.english)
        expected = {
            "surface_asc": ["Apple", "record", "zebra"],
            "surface_desc": ["zebra", "record", "Apple"],
            "added_asc": ["zebra", "Apple", "record"],
            "added_desc": ["record", "Apple", "zebra"],
        }
        for sort_mode, identities in expected.items():
            with self.subTest(sort_mode=sort_mode):
                self.owner.set_english_sort(sort_mode)
                self.assertEqual(self.identities(self.owner.english_view()), identities)
                self.assertEqual(list(self.core.english), canonical)

    def test_japanese_surface_pronunciation_word_type_and_combined_filters(self):
        self.core.japanese = {
            "ascii": ja_word(
                "abc",
                "エービーシー",
                2,
                word_type=JapaneseWordType.PROPER_NOUN,
            ),
            "rain": ja_word(
                "雨",
                "アメ",
                1,
                word_type=JapaneseWordType.COMMON_NOUN,
            ),
            "candy": ja_word(
                "飴",
                "アメ",
                1,
                word_type=JapaneseWordType.PROPER_NOUN,
            ),
        }

        self.owner.set_japanese_filter(text_query="bc", word_type_filter="ALL")
        self.assertEqual(self.identities(self.owner.japanese_view()), ["ascii"])

        self.owner.set_japanese_filter(text_query="アメ", word_type_filter="ALL")
        self.assertEqual(
            self.identities(self.owner.japanese_view()),
            ["rain", "candy"],
        )

        self.owner.set_japanese_filter(
            text_query="",
            word_type_filter="COMMON_NOUN",
        )
        self.assertEqual(self.identities(self.owner.japanese_view()), ["rain"])

        self.owner.set_japanese_filter(
            text_query="アメ",
            word_type_filter="PROPER_NOUN",
        )
        self.assertEqual(self.identities(self.owner.japanese_view()), ["candy"])

    def test_english_surface_and_arpabet_filters(self):
        self.core.english = {
            "Apple": en_word("Apple", ["AE1", "P", "AH0", "L"]),
            "record": en_word("record", ["R", "EH1", "K", "ER0", "D"]),
            "zebra": en_word("zebra", ["Z", "IY1", "B", "R", "AH0"]),
        }

        self.owner.set_english_filter(text_query="app")
        self.assertEqual(self.identities(self.owner.english_view()), ["Apple"])

        self.owner.set_english_filter(text_query="er0 d")
        self.assertEqual(self.identities(self.owner.english_view()), ["record"])

    def test_recompute_restores_visible_focus_and_falls_back_deterministically(self):
        self.core.japanese = {
            "zebra": ja_word("zebra"),
            "apple": ja_word("apple"),
            "record": ja_word("record"),
        }
        self.owner.remember_focus("ja", "zebra")

        self.owner.set_japanese_sort("surface_desc")
        view = self.owner.japanese_view()
        self.assertEqual(view.focused_identity, "zebra")
        self.assertEqual(view.focused_index, 0)

        self.owner.set_japanese_filter(
            text_query="record",
            word_type_filter="ALL",
        )
        view = self.owner.japanese_view()
        self.assertEqual(view.focused_identity, "record")
        self.assertEqual(view.focused_index, 0)

        self.owner.set_japanese_filter(
            text_query="no-match",
            word_type_filter="ALL",
        )
        view = self.owner.japanese_view()
        self.assertIsNone(view.focused_identity)
        self.assertIsNone(view.focused_index)
        self.assertEqual(view.shown_count, 0)
        self.assertEqual(view.total_count, 3)


class DictionaryListControllerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeDictionaryCore()
        self.controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
        )

    def key(self, value):
        return self.controller.handle_key(value)

    def finish_operation(self, intents):
        operation = next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
        value = operation.work()
        self.controller.complete_operation(operation.request, value)

    def test_sort_shortcut_cycles_and_preserves_stable_edit_target(self):
        self.core.japanese = {
            "zebra": ja_word("zebra"),
            "apple": ja_word("apple"),
        }
        self.controller.open_menu()
        self.key("j")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.payload["entry_ids"][1], "zebra")

        self.key("s")

        self.assertEqual(self.controller.editor.payload["sort_mode"], "surface_desc")
        self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.assertEqual(self.controller.editor.payload["entry_ids"][0], "zebra")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.payload["word_uuid"], "zebra")

    def test_japanese_filter_modal_applies_text_and_word_type_together(self):
        self.core.japanese = {
            "rain": ja_word(
                "雨",
                "アメ",
                1,
                word_type=JapaneseWordType.COMMON_NOUN,
            ),
            "candy": ja_word(
                "飴",
                "アメ",
                1,
                word_type=JapaneseWordType.PROPER_NOUN,
            ),
        }
        self.controller.open_menu()
        self.key("j")

        self.key("f")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_japanese_filter",
        )
        self.assertEqual(self.controller.editor.selection, "text_query")
        self.key("\n")
        self.key("アメ")
        self.key("\n")
        self.key(curses.KEY_DOWN)
        self.key(curses.KEY_RIGHT)
        self.assertEqual(
            self.controller.editor.payload["word_type_filter"],
            "PROPER_NOUN",
        )
        self.key("a")

        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(self.controller.editor.payload["text_filter"], "アメ")
        self.assertEqual(
            self.controller.editor.payload["word_type_filter"],
            "PROPER_NOUN",
        )
        self.assertEqual(self.controller.editor.payload["visible_count"], 1)
        self.assertEqual(self.controller.editor.payload["total_count"], 2)
        self.assertEqual(self.controller.editor.payload["entry_ids"], ("candy",))

    def test_english_filter_modal_matches_arpabet_and_clear_restores_all_entries(self):
        self.core.english = {
            "Apple": en_word("Apple", ["AE1", "P", "AH0", "L"]),
            "record": en_word("record", ["R", "EH1", "K", "ER0", "D"]),
        }
        self.controller.open_menu()
        self.key("e")
        self.key("f")
        self.key("\n")
        self.key("ER0 D")
        self.key("\n")
        self.key("a")

        self.assertEqual(self.controller.editor.payload["entry_ids"], ("record",))
        self.assertEqual(self.controller.editor.payload["visible_count"], 1)
        self.assertEqual(self.controller.editor.payload["total_count"], 2)

        self.key("f")
        self.assertEqual(
            self.controller.editor.payload["text_query"],
            "ER0 D",
        )
        self.key("c")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.controller.editor.payload["text_filter"], "")
        self.assertEqual(self.controller.editor.payload["visible_count"], 2)
        self.assertEqual(self.controller.editor.payload["total_count"], 2)

    def test_filter_shortcut_state_survives_entry_and_delete_cancel_round_trips(self):
        self.core.english = {
            "record": en_word("record", ["R", "EH1", "K", "ER0", "D"]),
            "zebra": en_word("zebra", ["Z", "IY1", "B", "R", "AH0"]),
        }
        self.controller.open_menu()
        self.key("e")
        self.key("f")
        self.key("\n")
        self.key("record")
        self.key("\n")
        self.key("a")

        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.key("\x1b")
        self.assertEqual(self.controller.editor.payload["text_filter"], "record")

        self.key("x")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_delete_confirmation",
        )
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.controller.editor.payload["text_filter"], "record")
        self.assertEqual(self.controller.editor.payload["entry_ids"], ("record",))

    def test_sort_recompute_preserves_stable_edit_target(self):
        self.core.japanese = {
            "zebra": ja_word("zebra"),
            "apple": ja_word("apple"),
        }
        self.controller.open_menu()
        self.key("j")
        self.key(curses.KEY_DOWN)
        self.assertEqual(
            self.controller.editor.payload["entry_ids"][1],
            "zebra",
        )

        self.controller.set_japanese_list_sort("surface_desc")

        self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.assertEqual(
            self.controller.editor.payload["entry_ids"][0],
            "zebra",
        )
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.payload["word_uuid"], "zebra")

    def test_sort_recompute_preserves_stable_delete_target(self):
        self.core.english = {
            "zebra": en_word("zebra", ["Z", "IY1", "B", "R", "AH0"]),
            "Apple": en_word("Apple", ["AE1", "P", "AH0", "L"]),
        }
        self.controller.open_menu()
        self.key("e")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.payload["entry_ids"][1], "zebra")

        self.controller.set_english_list_sort("surface_desc")

        self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.key("x")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_delete_confirmation",
        )
        self.assertEqual(self.controller.editor.payload["identifier"], "zebra")

    def test_filter_hidden_and_empty_results_use_list_fallback(self):
        self.core.japanese = {
            "zebra": ja_word("zebra"),
            "apple": ja_word("apple"),
        }
        self.controller.open_menu()
        self.key("j")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.payload["entry_ids"][1], "zebra")

        self.controller.set_japanese_list_filter(
            text_query="apple",
            word_type_filter="ALL",
        )
        self.assertEqual(self.controller.editor.selection, ("entry", 0))
        self.assertEqual(self.controller.editor.payload["entry_ids"], ("apple",))

        self.controller.set_japanese_list_filter(
            text_query="no-match",
            word_type_filter="ALL",
        )
        self.assertEqual(self.controller.editor.selection, "add")
        self.assertEqual(self.controller.editor.payload["entries"], ())
        self.assertIsNone(self.controller.editor.payload["entry_index"])

    def test_sort_and_filter_state_survives_entry_and_delete_round_trips(self):
        self.core.english = {
            "zebra": en_word("zebra", ["Z", "IY1", "B", "R", "AH0"]),
            "record": en_word("record", ["R", "EH1", "K", "ER0", "D"]),
        }
        self.controller.open_menu()
        self.key("e")
        self.controller.set_english_list_sort("added_desc")
        self.controller.set_english_list_filter(text_query="record")

        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.controller.editor.payload["sort_mode"], "added_desc")
        self.assertEqual(self.controller.editor.payload["text_filter"], "record")

        self.key("x")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_delete_confirmation",
        )
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.controller.editor.payload["sort_mode"], "added_desc")
        self.assertEqual(self.controller.editor.payload["text_filter"], "record")

        self.key("\n")
        editor = self.controller.editor
        editor.payload["surface"] = "recording"
        intents = self.key("s")
        self.finish_operation(intents)

        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.controller.editor.payload["sort_mode"], "added_desc")
        self.assertEqual(self.controller.editor.payload["text_filter"], "record")
        self.assertEqual(
            self.controller.editor.payload["entry_ids"],
            ("recording",),
        )
        self.assertEqual(self.controller.editor.selection, ("entry", 0))


if __name__ == "__main__":
    unittest.main()
