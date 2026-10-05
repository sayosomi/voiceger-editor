import curses
import unittest
from types import SimpleNamespace

from voiceger_editor.openjtalk_dictionary import expand_word_type, normalize_surface
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.tui_dictionary import (
    DictionaryOperationIntent,
    TuiDictionaryController,
)
from voiceger_editor.tui_editors import (
    AdjustmentPressedIntent,
    ClearAdjustmentFeedbackIntent,
    PreviewIntent,
)
from voiceger_editor.tui_shortcuts import menu_items
from voiceger_editor.tui_status import StatusKind
from voiceger_editor.user_dictionary import JapaneseWordType


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

    def finish_operation(self, intents):
        operation = next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
        value = operation.work()
        completion = self.controller.complete_operation(operation.request, value)
        return operation, completion

    @staticmethod
    def operation(intents):
        return next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )

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
        self.core.english["hello"] = en_word(
            "hello", ["HH", "AH0", "L", "OW1"]
        )
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

    def test_empty_list_still_exposes_add_and_back(self):
        self.controller.open_menu()
        self.key("\n")

        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(self.controller.editor.payload["entries"], ())
        self.assertEqual(self.controller.editor.selection, "add")

        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "back")
        self.key(curses.KEY_UP)
        self.assertEqual(self.controller.editor.selection, "add")

        self.key("a")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.title, "ADD JAPANESE DICTIONARY WORD")
        self.assertEqual(self.controller.editor.selection, "surface")
        self.assertEqual(self.controller.editor.active_field, "surface")
        self.assertEqual(self.controller.editor.input_value, "")

    def test_direct_japanese_add_generates_from_surface_without_overwriting_manual_reading(self):
        generated = [
            parse_pronunciation("ズン'ダモン"),
            parse_pronunciation("ズンダ'モン"),
        ]
        calls = []

        def japanese_pronunciation(surface):
            calls.append(surface)
            return generated[len(calls) - 1]

        controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
            japanese_pronunciation=japanese_pronunciation,
        )
        controller.open_menu()
        controller.handle_key("j")
        controller.handle_key("a")
        self.assertEqual(controller.editor.active_field, "surface")
        controller.handle_key("ずんだもん")
        intents = controller.handle_key("\n")

        editor = controller.editor
        operation = next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
        self.assertEqual(operation.status, "Generating Japanese pronunciation…")
        self.assertEqual(operation.request.operation, "generate_japanese_pronunciation")
        self.assertEqual(operation.request.language, "ja")
        self.assertEqual(calls, [])
        value = operation.work()
        controller.complete_operation(operation.request, value)
        self.assertEqual(calls, ["ずんだもん"])
        self.assertEqual(editor.payload["pronunciation"], "ズンダモン")
        self.assertEqual(editor.payload["accent"], 2)
        self.assertEqual(editor.payload["moras"], ("ズ", "ン", "ダ", "モ", "ン"))

        editor.payload["pronunciation"] = "マニュアル"
        editor.payload["moras"] = ("マ", "ニュ", "ア", "ル")
        editor.payload["accent"] = 1
        editor.selection = "surface"
        controller.handle_key("\n")
        controller.handle_key("\n")
        self.assertEqual(calls, ["ずんだもん"])
        self.assertEqual(editor.payload["pronunciation"], "マニュアル")

        intents = controller.handle_key("g")
        operation = next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
        self.assertEqual(calls, ["ずんだもん"])
        value = operation.work()
        controller.complete_operation(operation.request, value)
        self.assertEqual(calls, ["ずんだもん", "ずんだもん"])
        self.assertEqual(editor.payload["pronunciation"], "ズンダモン")
        self.assertEqual(editor.payload["accent"], 3)
        self.assertEqual(self.core.japanese, {})

    def test_direct_english_add_generates_one_word_and_preserves_draft_on_generation_error(self):
        calls = []

        def english_word_groups(surface):
            calls.append(surface)
            if surface == "two words":
                return (
                    ("two", ("T", "UW1")),
                    ("words", ("W", "ER1", "D", "Z")),
                )
            return ((surface, ("V", "OY1", "AH0", "JH", "ER0")),)

        controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
            english_word_groups=english_word_groups,
        )
        controller.open_menu()
        controller.handle_key("e")
        controller.handle_key("a")
        self.assertEqual(controller.editor.active_field, "surface")
        controller.handle_key("Voiceger")
        intents = controller.handle_key("\n")

        editor = controller.editor
        operation = next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
        self.assertEqual(operation.status, "Generating English pronunciation…")
        self.assertEqual(operation.request.operation, "generate_english_pronunciation")
        self.assertEqual(calls, [])
        value = operation.work()
        controller.complete_operation(operation.request, value)
        self.assertEqual(calls, ["Voiceger"])
        self.assertEqual(
            editor.payload["phonemes"],
            ("V", "OY1", "AH0", "JH", "ER0"),
        )

        previous = editor.payload["phonemes"]
        editor.payload["surface"] = "two words"
        intents = controller.handle_key("g")
        operation = next(
            item for item in intents if isinstance(item, DictionaryOperationIntent)
        )
        self.assertEqual(editor.payload["phonemes"], previous)
        with self.assertRaisesRegex(ValueError, "exactly one word"):
            operation.work()
        completed = controller.complete_operation(
            operation.request,
            error=ValueError("English dictionary Surface must resolve to exactly one word"),
        )
        self.assertIn("Pronunciation was not generated: English dictionary Surface", completed[0].status)
        self.assertEqual(editor.payload["phonemes"], previous)
        self.assertEqual(self.core.english, {})

    def test_generation_save_and_delete_failures_keep_both_languages_retryable(self):
        for language in ("ja", "en"):
            with self.subTest(language=language, operation="generation"):
                core = FakeDictionaryCore()
                controller = TuiDictionaryController(
                    core,
                    input_prefix=lambda _editor: "▶ ",
                    japanese_pronunciation=lambda _surface: parse_pronunciation("カ'ナ"),
                    english_word_groups=lambda surface: ((surface, ("K", "AE1")),),
                )
                if language == "ja":
                    controller.open_quick_save_japanese(
                        surface="かな", pronunciation="カ'ナ"
                    )
                    editor = controller.editor
                    previous = (
                        editor.payload["pronunciation"],
                        editor.payload["moras"],
                        editor.payload["accent"],
                    )
                else:
                    controller.open_quick_save_english(
                        surface="hello", phonemes="HH AH0"
                    )
                    editor = controller.editor
                    previous = editor.payload["phonemes"]
                operation = self.operation(controller.handle_key("g"))
                failure = RuntimeError("analysis failed")
                completion = controller.complete_operation(
                    operation.request,
                    error=failure,
                )
                self.assertEqual(completion[0].status, "Pronunciation was not generated: analysis failed")
                self.assertIs(completion[0].status.kind, StatusKind.ERROR)
                self.assertIs(controller.editor, editor)
                if language == "ja":
                    self.assertEqual(
                        (
                            editor.payload["pronunciation"],
                            editor.payload["moras"],
                            editor.payload["accent"],
                        ),
                        previous,
                    )
                else:
                    self.assertEqual(editor.payload["phonemes"], previous)
                retry = self.operation(controller.handle_key("g"))
                self.assertEqual(editor.error, "")
                self.assertEqual(retry.status, "Generating Japanese pronunciation…" if language == "ja" else "Generating English pronunciation…")

            with self.subTest(language=language, operation="save"):
                core = FakeDictionaryCore()
                controller = TuiDictionaryController(
                    core,
                    input_prefix=lambda _editor: "▶ ",
                )
                if language == "ja":
                    controller.open_quick_save_japanese(
                        surface="かな", pronunciation="カ'ナ"
                    )
                else:
                    controller.open_quick_save_english(
                        surface="hello", phonemes="HH AH0"
                    )
                editor = controller.editor
                operation = self.operation(controller.handle_key("s"))
                completion = controller.complete_operation(
                    operation.request,
                    error=RuntimeError("save failed"),
                )
                self.assertEqual(completion[0].status, "Dictionary word was not saved: save failed")
                self.assertIs(completion[0].status.kind, StatusKind.ERROR)
                self.assertIs(controller.editor, editor)
                self.assertTrue(editor.payload["quick_save"])
                retry = self.operation(controller.handle_key("s"))
                self.assertEqual(retry.status, "Saving Japanese dictionary word…" if language == "ja" else "Saving English dictionary word…")

            with self.subTest(language=language, operation="delete"):
                core = FakeDictionaryCore()
                if language == "ja":
                    core.japanese["word-1"] = ja_word("雨", "アメ", 1)
                else:
                    core.english["hello"] = en_word("hello", ["HH", "AH0"])
                controller = TuiDictionaryController(
                    core,
                    input_prefix=lambda _editor: "▶ ",
                )
                controller.open_menu()
                controller.handle_key("j" if language == "ja" else "e")
                controller.handle_key("x")
                confirmation = controller.editor
                operation = self.operation(controller.handle_key("d"))
                completion = controller.complete_operation(
                    operation.request,
                    error=RuntimeError("delete failed"),
                )
                self.assertEqual(completion[0].status, "Dictionary word was not deleted: delete failed")
                self.assertIs(completion[0].status.kind, StatusKind.ERROR)
                self.assertIs(controller.editor, confirmation)
                self.assertEqual(controller.editor.kind, "dictionary_delete_confirmation")
                self.assertTrue(core.japanese if language == "ja" else core.english)
                retry = self.operation(controller.handle_key("d"))
                self.assertEqual(retry.status, "Deleting Japanese dictionary word…" if language == "ja" else "Deleting English dictionary word…")

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

    def test_operation_work_uses_snapshots_when_the_live_draft_changes(self):
        calls = []
        controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
            english_word_groups=lambda surface: calls.append(surface)
            or ((surface, ("R", "EH1", "K")),),
        )
        controller.open_quick_save_english(
            surface="record",
            phonemes="R EH1 K",
        )
        editor = controller.editor
        generation = self.operation(controller.handle_key("g"))
        editor.payload["surface"] = "mutated"

        generation_value = generation.work()

        self.assertEqual(calls, ["record"])
        self.assertEqual(generation_value, ("R", "EH1", "K"))

        editor.payload["surface"] = "record"
        editor.payload["phonemes"] = ("R", "EH1", "K")
        save = self.operation(controller.handle_key("s"))
        editor.payload["surface"] = "changed after snapshot"
        editor.payload["phonemes"] = ("K", "AE1", "T")

        save.work()

        self.assertIn("record", self.core.english)
        self.assertEqual(self.core.english["record"].phonemes, ["R", "EH1", "K"])
        self.assertNotIn("changed after snapshot", self.core.english)

        self.core.japanese["word-1"] = ja_word("雨", "アメ", 1)
        controller.open_menu()
        controller.handle_key("j")
        controller.handle_key("x")
        deletion = self.operation(controller.handle_key("d"))
        controller.editor.payload["identifier"] = "missing"

        deletion.work()

        self.assertNotIn("word-1", self.core.japanese)

    def test_empty_surface_validation_does_not_create_background_work(self):
        for language in ("ja", "en"):
            with self.subTest(language=language):
                controller = TuiDictionaryController(
                    FakeDictionaryCore(),
                    input_prefix=lambda _editor: "▶ ",
                )
                if language == "ja":
                    controller.open_quick_save_japanese(
                        surface="かな", pronunciation="カ'ナ"
                    )
                else:
                    controller.open_quick_save_english(
                        surface="hello", phonemes="HH AH0"
                    )
                editor = controller.editor
                editor.payload["surface"] = "  "

                self.assertEqual(controller.handle_key("g"), ())
                self.assertEqual(controller.handle_key("s"), ())
                self.assertEqual(editor.error, "Surface must not be empty.")
                self.assertFalse(
                    any(
                        isinstance(item, DictionaryOperationIntent)
                        for item in controller.handle_key("g")
                    )
                )

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
        self.assertIsNone(editor.active_field)
        self.assertEqual(editor.payload["word_uuid"], "existing")
        self.assertEqual(editor.payload["pronunciation"], "ズンダモン")
        self.assertEqual(editor.payload["accent"], 2)
        self.assertEqual(editor.payload["priority"], 7)

        intents = self.key("s")
        self.assertEqual(intents[0].status, "Saving Japanese dictionary word…")
        self.assertIs(self.controller.editor, editor)
        self.assertEqual(self.core.japanese["existing"].accent_type, 4)
        self.finish_operation(intents)

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
        word_type_intents = self.key(curses.KEY_RIGHT)
        self.assertIn(
            AdjustmentPressedIntent("dictionary", "word_type", 1),
            word_type_intents,
        )
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
        editor.payload["priority"] = 5
        priority_intents = self.key(curses.KEY_RIGHT)
        self.assertIn(
            AdjustmentPressedIntent("dictionary", "priority", 1),
            priority_intents,
        )
        self.assertEqual(editor.payload["priority"], 6)

        editor.payload["priority"] = 10
        upper_boundary = self.key(curses.KEY_RIGHT)
        self.assertEqual(
            upper_boundary,
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(editor.payload["priority"], 10)

        editor.payload["priority"] = 0
        lower_boundary = self.key(curses.KEY_LEFT)
        self.assertEqual(
            lower_boundary,
            (ClearAdjustmentFeedbackIntent(),),
        )
        self.assertEqual(editor.payload["priority"], 0)

        before = dict(self.core.japanese)
        editor.selection = "preview"
        intents = self.key("\n")
        self.assertIsInstance(intents[0], PreviewIntent)
        self.assertEqual(self.core.japanese, before)

    def test_existing_entry_navigator_moves_without_wrapping_for_both_languages(self):
        cases = (
            (
                "ja",
                {
                    "first-ja": ja_word("あめ", "アメ", 1),
                    "second-ja": ja_word("ぶどう", "ブドウ", 2),
                },
                ("あめ", "ぶどう"),
            ),
            (
                "en",
                {
                    "Apple": en_word("Apple", ["AE1", "P", "AH0", "L"]),
                    "zebra": en_word("zebra", ["Z", "IY1", "B", "R", "AH0"]),
                },
                ("Apple", "zebra"),
            ),
        )
        for language, entries, surfaces in cases:
            with self.subTest(language=language):
                core = FakeDictionaryCore()
                if language == "ja":
                    core.japanese.update(entries)
                else:
                    core.english.update(entries)
                controller = TuiDictionaryController(
                    core,
                    input_prefix=lambda _editor: "▶ ",
                )
                controller.open_menu()
                controller.handle_key("j" if language == "ja" else "e")
                controller.handle_key("\n")

                editor = controller.editor
                self.assertEqual(editor.payload["entry_index"], 0)
                self.assertEqual(editor.payload["entry_total"], 2)
                self.assertEqual(
                    editor.payload["surface"],
                    normalize_surface(surfaces[0]) if language == "ja" else surfaces[0],
                )

                shortcut_move = controller.handle_key("]")
                self.assertFalse(
                    any(
                        isinstance(item, AdjustmentPressedIntent)
                        for item in shortcut_move
                    )
                )
                editor = controller.editor
                self.assertEqual(editor.payload["entry_index"], 1)
                self.assertEqual(editor.payload["entry_total"], 2)
                self.assertEqual(editor.selection, "entry_navigator")
                self.assertEqual(
                    editor.payload["surface"],
                    normalize_surface(surfaces[1]) if language == "ja" else surfaces[1],
                )

                boundary = controller.handle_key("]")
                self.assertEqual(boundary[0].status, "Last dictionary word.")
                self.assertEqual(controller.editor.payload["entry_index"], 1)

                left_move = controller.handle_key(curses.KEY_LEFT)
                self.assertIn(
                    AdjustmentPressedIntent(
                        "dictionary",
                        "entry_navigator",
                        -1,
                    ),
                    left_move,
                )
                self.assertEqual(controller.editor.payload["entry_index"], 0)
                self.assertEqual(controller.editor.selection, "entry_navigator")

                boundary = controller.handle_key(curses.KEY_LEFT)
                self.assertFalse(
                    any(
                        isinstance(item, AdjustmentPressedIntent)
                        for item in boundary
                    )
                )
                self.assertEqual(boundary[0].status, "First dictionary word.")
                self.assertEqual(controller.editor.payload["entry_index"], 0)

                right_move = controller.handle_key(curses.KEY_RIGHT)
                self.assertIn(
                    AdjustmentPressedIntent(
                        "dictionary",
                        "entry_navigator",
                        1,
                    ),
                    right_move,
                )
                self.assertEqual(controller.editor.payload["entry_index"], 1)

                controller.handle_key("\x1b")
                self.assertIn(
                    controller.editor.kind,
                    {"dictionary_japanese_list", "dictionary_english_list"},
                )
                self.assertEqual(controller.editor.selection, ("entry", 1))

    def test_dirty_entry_navigation_uses_existing_discard_confirmation(self):
        self.core.english["Apple"] = en_word(
            "Apple", ["AE1", "P", "AH0", "L"]
        )
        self.core.english["zebra"] = en_word(
            "zebra", ["Z", "IY1", "B", "R", "AH0"]
        )
        self.controller.open_menu()
        self.key("e")
        self.key("\n")
        editor = self.controller.editor
        editor.payload["surface"] = "draft"

        self.key("]")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_discard_confirmation",
        )

        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.assertEqual(self.controller.editor.payload["surface"], "draft")
        self.assertEqual(self.controller.editor.payload["entry_index"], 0)

        self.key("]")
        self.key("d")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.assertEqual(self.controller.editor.payload["surface"], "zebra")
        self.assertEqual(self.controller.editor.payload["entry_index"], 1)
        self.assertEqual(self.controller.editor.selection, "entry_navigator")
        self.assertIn("Apple", self.core.english)
        self.assertNotIn("draft", self.core.english)

    def test_add_and_quick_save_entry_screens_do_not_have_navigator(self):
        for language in ("ja", "en"):
            with self.subTest(language=language):
                controller = TuiDictionaryController(
                    FakeDictionaryCore(),
                    input_prefix=lambda _editor: "▶ ",
                )
                controller.open_menu()
                controller.handle_key("j" if language == "ja" else "e")
                controller.handle_key("a")
                editor = controller.editor
                self.assertIsNone(editor.payload["entry_index"])
                self.assertIsNone(editor.payload["entry_total"])

        self.controller.open_quick_save_english(
            surface="record",
            phonemes="R EH1 K ER0 D",
        )
        editor = self.controller.editor
        self.assertIsNone(editor.payload["entry_index"])
        self.assertIsNone(editor.payload["entry_total"])

    def test_existing_entry_navigator_does_not_override_field_left_right(self):
        self.core.japanese["first"] = ja_word("あめ", "アメ", 1)
        self.core.japanese["second"] = ja_word("ぶどう", "ブドウ", 2)
        self.controller.open_menu()
        self.key("j")
        self.key("\n")
        editor = self.controller.editor

        editor.selection = "pronunciation"
        self.key(curses.KEY_RIGHT)

        self.assertEqual(editor.payload["entry_index"], 0)
        self.assertEqual(editor.payload["accent"], 2)

        self.controller.open_menu()
        self.core.english["record"] = en_word(
            "record", ["R", "EH1", "K", "ER0", "D"]
        )
        self.core.english["zebra"] = en_word(
            "zebra", ["Z", "IY1", "B", "R", "AH0"]
        )
        self.key("e")
        self.key("\n")
        editor = self.controller.editor
        editor.selection = "phonemes"
        self.key(curses.KEY_RIGHT)

        self.assertEqual(editor.payload["entry_index"], 0)
        self.assertEqual(
            editor.payload["phonemes"],
            ("R", "EH0", "K", "ER1", "D"),
        )

    def test_dirty_back_and_escape_require_discard_confirmation(self):
        self.controller.open_quick_save_english(
            surface="Voiceger",
            phonemes="V OY1 AH0 JH ER0",
        )
        editor = self.controller.editor
        editor.payload["surface"] = "Voiceger2"

        self.key("\x1b")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_discard_confirmation",
        )

        self.key("\x1b")
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
        before = dict(self.core.english)
        editor.selection = "preview"
        intents = self.key("\n")
        self.assertIsInstance(intents[0], PreviewIntent)
        self.assertEqual(self.core.english, before)

        editor.selection = "phonemes"
        self.key(curses.KEY_RIGHT)

        self.assertEqual(
            editor.payload["phonemes"],
            ("R", "EH0", "K", "ER1", "D"),
        )
        intents = self.key("s")
        self.finish_operation(intents)
        self.assertIsNone(self.controller.editor)
        self.assertEqual(
            self.core.english["record"].phonemes,
            ["R", "EH0", "K", "ER1", "D"],
        )

    def test_entry_action_order_and_delete_visibility_follow_persisted_identity(self):
        cases = (
            (
                "ja",
                {"stable-ja": ja_word("ずんだもん", "ズンダモン", 3)},
                [
                    "surface",
                    "generate_pronunciation",
                    "pronunciation",
                    "word_type",
                    "priority",
                    "preview",
                    "save",
                    "delete",
                    "dictionary",
                    "back",
                ],
            ),
            (
                "en",
                {"Voiceger": en_word("Voiceger", ["V", "OY1", "AH0", "JH", "ER0"])},
                [
                    "surface",
                    "generate_pronunciation",
                    "phonemes",
                    "preview",
                    "save",
                    "delete",
                    "dictionary",
                    "back",
                ],
            ),
        )
        for language, entries, expected in cases:
            with self.subTest(language=language):
                core = FakeDictionaryCore()
                if language == "ja":
                    core.japanese.update(entries)
                else:
                    core.english.update(entries)
                controller = TuiDictionaryController(
                    core,
                    input_prefix=lambda _editor: "▶ ",
                )
                controller.open_menu()
                controller.handle_key("j" if language == "ja" else "e")
                controller.handle_key("\n")
                editor = controller.editor

                self.assertTrue(editor.payload["can_delete"])
                self.assertEqual(
                    [item.key for item in menu_items(editor.kind, editor.payload)],
                    expected,
                )

                visited = [editor.selection]
                for _ in range(len(expected) - 1):
                    controller.handle_key(curses.KEY_DOWN)
                    visited.append(controller.editor.selection)
                self.assertEqual(visited, expected)

                controller.handle_key("\x1b")
                controller.handle_key("a")
                editor = controller.editor
                self.assertFalse(editor.payload["can_delete"])
                self.assertNotIn(
                    "delete",
                    [item.key for item in menu_items(editor.kind, editor.payload)],
                )

    def test_edit_delete_uses_stable_identity_cancel_preserves_draft_and_success_returns_list(self):
        self.core.japanese["stable-ja"] = ja_word("ずんだもん", "ズンダモン", 3)
        self.core.english["Voiceger"] = en_word(
            "Voiceger", ["V", "OY1", "AH0", "JH", "ER0"]
        )

        self.controller.open_menu()
        self.key("j")
        self.key("\n")
        editor = self.controller.editor
        editor.payload["surface"] = "draft-ja"

        self.key("x")
        self.assertEqual(self.controller.editor.kind, "dictionary_delete_confirmation")
        self.assertEqual(self.controller.editor.payload["identifier"], "stable-ja")
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertEqual(self.controller.editor.payload["surface"], "draft-ja")

        self.key("x")
        intents = self.key("d")
        self.finish_operation(intents)
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertNotIn("stable-ja", self.core.japanese)
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

        self.key("e")
        self.key("\n")
        editor = self.controller.editor
        self.assertEqual(editor.payload["original_surface"], "Voiceger")
        editor.payload["surface"] = "Renamed draft"

        self.key("x")
        self.assertEqual(self.controller.editor.kind, "dictionary_delete_confirmation")
        self.assertEqual(self.controller.editor.payload["identifier"], "Voiceger")
        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.assertEqual(self.controller.editor.payload["surface"], "Renamed draft")

        self.key("x")
        intents = self.key("d")
        self.finish_operation(intents)
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertNotIn("Voiceger", self.core.english)
        self.assertNotIn("Renamed draft", self.core.english)

    def test_quick_save_delete_visibility_distinguishes_existing_from_new(self):
        self.core.japanese["stable-ja"] = ja_word("ずんだもん", "ズンダモン", 3)
        self.core.english["Voiceger"] = en_word(
            "Voiceger", ["V", "OY1", "AH0", "JH", "ER0"]
        )

        self.controller.open_quick_save_japanese(
            surface="ずんだもん",
            pronunciation="ズンダ'モン",
        )
        self.assertTrue(self.controller.editor.payload["can_delete"])
        self.assertIn(
            "delete",
            [item.key for item in menu_items(
                self.controller.editor.kind,
                self.controller.editor.payload,
            )],
        )

        self.controller.open_quick_save_english(
            surface="Voiceger",
            phonemes="V OY1 AH0 JH ER0",
        )
        self.assertTrue(self.controller.editor.payload["can_delete"])

        self.controller.open_quick_save_japanese(
            surface="新語",
            pronunciation="シン'ゴ",
        )
        self.assertFalse(self.controller.editor.payload["can_delete"])
        self.assertNotIn(
            "delete",
            [item.key for item in menu_items(
                self.controller.editor.kind,
                self.controller.editor.payload,
            )],
        )

        self.controller.open_quick_save_english(
            surface="Newword",
            phonemes="N UW1 W ER0 D",
        )
        self.assertFalse(self.controller.editor.payload["can_delete"])

    def test_delete_confirmation_uses_common_modal_navigation_for_both_languages(self):
        self.core.japanese["ja"] = ja_word("ずんだもん", "ズンダモン", 3)
        self.core.english["hello"] = en_word(
            "hello", ["HH", "AH0", "L", "OW1"]
        )

        self.controller.open_menu()
        self.key("j")
        self.controller.editor.selection = ("entry", 0)
        self.key("x")

        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_delete_confirmation",
        )
        self.assertEqual(self.controller.editor.selection, "delete")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "cancel")
        self.key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "cancel")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertIn("ja", self.core.japanese)

        self.key("\x1b")
        self.key("e")
        self.controller.editor.selection = ("entry", 0)
        self.key("x")
        self.key(curses.KEY_DOWN)
        self.key(curses.KEY_UP)
        self.assertEqual(self.controller.editor.selection, "delete")
        intents = self.key("\n")
        self.assertEqual(intents[0].status, "Deleting English dictionary word…")
        self.assertEqual(self.controller.editor.kind, "dictionary_delete_confirmation")
        self.assertIn("hello", self.core.english)
        self.finish_operation(intents)

        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertEqual(self.core.english, {})

    def test_management_crud_and_delete_confirmation_for_both_languages(self):
        self.controller.open_menu()
        self.key("\n")
        self.key("a")
        editor = self.controller.editor
        editor.active_field = None
        editor.payload.update(
            surface="雨",
            pronunciation="アメ",
            moras=("ア", "メ"),
            accent=1,
        )
        intents = self.key("s")
        self.assertEqual(intents[0].status, "Saving Japanese dictionary word…")
        self.assertEqual(self.core.japanese, {})
        self.finish_operation(intents)
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(len(self.core.japanese), 1)

        self.controller.editor.selection = ("entry", 0)
        self.key("x")
        self.assertEqual(
            self.controller.editor.kind,
            "dictionary_delete_confirmation",
        )
        intents = self.key("d")
        self.assertEqual(intents[0].status, "Deleting Japanese dictionary word…")
        self.assertEqual(self.controller.editor.kind, "dictionary_delete_confirmation")
        self.assertEqual(len(self.core.japanese), 1)
        self.finish_operation(intents)
        self.assertEqual(self.core.japanese, {})

        self.key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")
        self.assertEqual(self.controller.editor.payload["japanese_count"], 0)
        self.key(curses.KEY_DOWN)
        self.key("\n")
        self.key("a")
        editor = self.controller.editor
        editor.active_field = None
        editor.payload["surface"] = "hello"
        editor.payload["phonemes"] = ("HH", "AH0", "L", "OW1")
        intents = self.key("s")
        self.assertEqual(intents[0].status, "Saving English dictionary word…")
        self.assertEqual(self.core.english, {})
        self.finish_operation(intents)
        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertIn("hello", self.core.english)

        self.controller.editor.selection = ("entry", 0)
        self.key("x")
        intents = self.key("d")
        self.assertEqual(intents[0].status, "Deleting English dictionary word…")
        self.assertEqual(self.controller.editor.kind, "dictionary_delete_confirmation")
        self.assertIn("hello", self.core.english)
        self.finish_operation(intents)
        self.assertEqual(self.core.english, {})

    def test_management_edit_existing_entries_for_both_languages(self):
        self.core.japanese["existing-ja"] = ja_word("雨", "アメ", 1)
        self.core.english["hello"] = en_word("hello", ["HH", "AH0", "L", "OW1"])

        self.controller.open_menu()
        self.key("\n")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_entry")
        self.assertIsNone(self.controller.editor.active_field)

        self.key("\n")
        self.controller.editor.input_value = "飴"
        self.controller.editor.input_cursor = 1
        self.key("\n")
        intents = self.key("s")
        self.assertEqual(intents[0].status, "Saving Japanese dictionary word…")
        self.assertEqual(self.core.japanese["existing-ja"].surface, normalize_surface("雨"))
        self.finish_operation(intents)

        self.assertEqual(self.controller.editor.kind, "dictionary_japanese_list")
        self.assertEqual(self.core.japanese["existing-ja"].surface, normalize_surface("飴"))

        self.key("\x1b")
        self.key(curses.KEY_DOWN)
        self.key("\n")
        self.key("\n")
        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.assertIsNone(self.controller.editor.active_field)

        self.key("\n")
        self.controller.editor.input_value = "hello2"
        self.controller.editor.input_cursor = len("hello2")
        self.key("\n")
        intents = self.key("s")
        self.assertEqual(intents[0].status, "Saving English dictionary word…")
        self.assertIn("hello", self.core.english)
        self.finish_operation(intents)

        self.assertEqual(self.controller.editor.kind, "dictionary_english_list")
        self.assertNotIn("hello", self.core.english)
        self.assertIn("hello2", self.core.english)

    def test_entry_surface_field_uses_shared_cursor_and_text_edit_keys(self):
        self.controller.open_quick_save_english(
            surface="hello",
            phonemes="HH AH0 L OW1",
        )
        editor = self.controller.editor
        editor.selection = "surface"

        self.key("\n")
        self.assertEqual(editor.active_field, "surface")

        self.key(curses.KEY_HOME)
        self.assertEqual(editor.input_cursor, 0)
        self.key(curses.KEY_RIGHT)
        self.key("X")
        self.assertEqual(editor.input_value, "hXello")
        self.assertEqual(editor.input_cursor, 2)

        self.key(curses.KEY_BACKSPACE)
        self.assertEqual(editor.input_value, "hello")
        self.assertEqual(editor.input_cursor, 1)

        self.key(curses.KEY_END)
        self.key(curses.KEY_LEFT)
        self.key(curses.KEY_DC)
        self.assertEqual(editor.input_value, "hell")
        self.assertEqual(editor.input_cursor, 4)

        self.key("o")
        self.assertEqual(editor.input_value, "hello")

    def test_dictionary_shortcut_from_entry_opens_top_level_menu_and_back_restores_draft(self):
        self.controller.open_quick_save_english(
            surface="hello",
            phonemes="HH AH0 L OW1",
        )
        entry = self.controller.editor
        entry.payload["surface"] = "hello-draft"

        self.key("d")

        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

        self.key("\x1b")

        self.assertEqual(self.controller.editor.kind, "dictionary_english_entry")
        self.assertEqual(self.controller.editor.payload["surface"], "hello-draft")
        self.assertTrue(self.controller.editor.payload["quick_save"])


if __name__ == "__main__":
    unittest.main()
