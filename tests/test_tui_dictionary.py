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


from threading import Event
from types import SimpleNamespace
from voiceger_editor.openjtalk_dictionary import expand_word_type
from voiceger_editor.pronunciation import parse_pronunciation
from voiceger_editor.tui_editors import OpenDictionaryIntent
from voiceger_editor.tui_status import EMPTY_STATUS, StatusKind, error_status
from voiceger_editor.user_dictionary import JapaneseWordType
from tests.tui_app_test_support import TuiAppTestCase, FakeScreen, mixed_query

class TuiDictionaryIntegrationTests(TuiAppTestCase):
    def test_dictionary_explicit_generation_renders_status_before_analysis_for_both_languages(self):
        cases = (
            (
                "ja",
                "Generating Japanese pronunciation…",
                "ズン'ダモン",
                "ズンダモン",
            ),
            (
                "en",
                "Generating English pronunciation…",
                ("V", "OY1", "AH0", "JH", "ER0"),
                ("V", "OY1", "AH0", "JH", "ER0"),
            ),
        )
        for language, status, generated, expected in cases:
            with self.subTest(language=language):
                started = Event()
                release = Event()
                calls = []

                def analyze(surface):
                    calls.append(surface)
                    started.set()
                    if not release.wait(timeout=1):
                        raise RuntimeError("test release timeout")
                    if language == "ja":
                        return parse_pronunciation(generated)
                    return ((surface, generated),)

                app = self.make_app(batch_item=False)
                if language == "ja":
                    app._dictionary_controller._japanese_pronunciation = analyze
                    app._dictionary_controller.open_quick_save_japanese(
                        surface="ずんだもん",
                        pronunciation="ズン'ダモン",
                    )
                    editor = app._dictionary_controller.editor
                    previous = editor.payload["pronunciation"]
                else:
                    app._dictionary_controller._english_word_groups = analyze
                    app._dictionary_controller.open_quick_save_english(
                        surface="Voiceger",
                        phonemes="HH AH0",
                    )
                    editor = app._dictionary_controller.editor
                    previous = editor.payload["phonemes"]
                editor.error = error_status("stale local validation")
                editor.selection = "generate_pronunciation"
                app._screen = FakeScreen()

                app._handle_key("\n")

                self.assertEqual(app._status, status)
                self.assertEqual(editor.error, EMPTY_STATUS)
                self.assertEqual(calls, [])
                self.assertTrue(app._operations.busy)
                self.assertEqual(app._operations.worker_operation, "dictionary")
                app._render()
                self.assertIn(f"Status: {status}", self.rendered(app._screen))
                old_selection = editor.selection
                app._handle_key(curses.KEY_DOWN)
                self.assertIs(app._dictionary_controller.editor, editor)
                self.assertEqual(editor.selection, old_selection)
                self.assertEqual(app._status, status)

                app._operations.start_pending_worker()
                self.assertTrue(started.wait(timeout=1))
                if language == "ja":
                    self.assertEqual(editor.payload["pronunciation"], previous)
                else:
                    self.assertEqual(editor.payload["phonemes"], previous)
                release.set()
                app._operations.join_worker()
                app._consume_events()

                self.assertEqual(app._status, "Pronunciation generated from Surface.")
                self.assertFalse(app._operations.busy)
                self.assertIsNone(app._operations.worker_operation)
                if language == "ja":
                    self.assertEqual(editor.payload["pronunciation"], expected)
                else:
                    self.assertEqual(editor.payload["phonemes"], expected)

    def test_finishing_new_dictionary_surface_uses_deferred_generation(self):
        cases = (
            ("ja", "Generating Japanese pronunciation…", "ア'メ"),
            ("en", "Generating English pronunciation…", ("V", "OY1")),
        )
        for language, status, generated in cases:
            with self.subTest(language=language):
                started = Event()
                release = Event()
                calls = []

                def analyze(surface):
                    calls.append(surface)
                    started.set()
                    if not release.wait(timeout=1):
                        raise RuntimeError("test release timeout")
                    if language == "ja":
                        return parse_pronunciation(generated)
                    return ((surface, generated),)

                app = self.make_app(batch_item=False)
                if language == "ja":
                    app._dictionary_controller._japanese_pronunciation = analyze
                else:
                    app._dictionary_controller._english_word_groups = analyze
                app._dispatch_editor_intents((OpenDictionaryIntent(),))
                app._handle_key("j" if language == "ja" else "e")
                app._handle_key("a")
                app._handle_key("雨" if language == "ja" else "Voiceger")

                app._handle_key("\n")

                editor = app._dictionary_controller.editor
                self.assertEqual(app._status, status)
                self.assertEqual(calls, [])
                self.assertIsNotNone(app._operations._pending_worker)
                app._operations.start_pending_worker()
                self.assertTrue(started.wait(timeout=1))
                release.set()
                app._operations.join_worker()
                app._consume_events()
                self.assertEqual(app._status, "Pronunciation generated from Surface.")
                if language == "ja":
                    self.assertEqual(editor.payload["pronunciation"], "アメ")
                else:
                    self.assertEqual(editor.payload["phonemes"], generated)

    def test_dictionary_updates_keep_quick_save_draft_open_until_public_update_succeeds(self):
        japanese_word = SimpleNamespace(
            surface=normalize_surface("雨"),
            pronunciation="アメ",
            accent_type=1,
            priority=5,
            context_id=expand_word_type(JapaneseWordType.PROPER_NOUN.value)["context_id"],
        )
        english_word = SimpleNamespace(
            surface="record",
            phonemes=["R", "EH1", "K", "ER0", "D"],
        )
        cases = (
            (
                "ja",
                "Saving Japanese dictionary word…",
                "Japanese dictionary word saved.",
                "update_japanese_word",
                {"word-1": japanese_word},
                lambda controller: controller.open_quick_save_japanese(
                    surface="雨", pronunciation="ア'メ"
                ),
            ),
            (
                "en",
                "Saving English dictionary word…",
                "English dictionary word saved.",
                "update_english_entry",
                {"record": english_word},
                lambda controller: controller.open_quick_save_english(
                    surface="record", phonemes="R EH1 K ER0 D"
                ),
            ),
        )
        for language, status, success, method_name, entries, open_entry in cases:
            with self.subTest(language=language):
                started = Event()
                release = Event()
                app = self.make_app(batch_item=False)
                core = app.adapter.user_dictionary
                getattr(core, "list_japanese_entries" if language == "ja" else "list_english_entries").return_value = entries
                method = getattr(core, method_name)

                def persist(*_args, **_kwargs):
                    started.set()
                    if not release.wait(timeout=1):
                        raise RuntimeError("test release timeout")

                method.side_effect = persist
                open_entry(app._dictionary_controller)
                editor = app._dictionary_controller.editor

                app._handle_key("s")

                self.assertEqual(app._status, status)
                self.assertIs(app._dictionary_controller.editor, editor)
                method.assert_not_called()
                app._operations.start_pending_worker()
                self.assertTrue(started.wait(timeout=1))
                self.assertIs(app._dictionary_controller.editor, editor)
                release.set()
                app._operations.join_worker()
                app._consume_events()

                method.assert_called_once()
                self.assertIsNone(app._dictionary_controller.editor)
                self.assertEqual(app._status, success)
                self.assertNotIn("Saving", app._status)

    def test_dictionary_deletions_keep_confirmation_and_list_until_success(self):
        for language in ("ja", "en"):
            with self.subTest(language=language):
                started = Event()
                release = Event()
                app = self.make_app(batch_item=False)
                core = app.adapter.user_dictionary
                japanese_entries = {
                    "word-1": SimpleNamespace(
                        surface=normalize_surface("雨"),
                        pronunciation="アメ",
                        accent_type=1,
                        priority=5,
                        context_id=expand_word_type(JapaneseWordType.PROPER_NOUN.value)["context_id"],
                    )
                }
                english_entries = {
                    "hello": SimpleNamespace(
                        surface="hello",
                        phonemes=["HH", "AH0", "L", "OW1"],
                    )
                }
                core.list_japanese_entries.return_value = japanese_entries.copy()
                core.list_english_entries.return_value = english_entries.copy()
                method = getattr(
                    core,
                    "delete_japanese_word" if language == "ja" else "delete_english_entry",
                )

                def delete(identifier):
                    started.set()
                    if not release.wait(timeout=1):
                        raise RuntimeError("test release timeout")
                    if language == "ja":
                        japanese_entries.pop(identifier)
                        core.list_japanese_entries.return_value = japanese_entries.copy()
                    else:
                        english_entries.pop(identifier)
                        core.list_english_entries.return_value = english_entries.copy()

                method.side_effect = delete
                app._dispatch_editor_intents((OpenDictionaryIntent(),))
                app._handle_key("j" if language == "ja" else "e")
                app._handle_key("x")
                confirmation = app._dictionary_controller.editor
                self.assertEqual(confirmation.kind, "dictionary_delete_confirmation")

                app._handle_key("d")

                status = (
                    "Deleting Japanese dictionary word…"
                    if language == "ja"
                    else "Deleting English dictionary word…"
                )
                success = (
                    "Japanese dictionary word deleted."
                    if language == "ja"
                    else "English dictionary word deleted."
                )
                self.assertEqual(app._status, status)
                self.assertIs(app._dictionary_controller.editor, confirmation)
                method.assert_not_called()
                app._operations.start_pending_worker()
                self.assertTrue(started.wait(timeout=1))
                self.assertIs(app._dictionary_controller.editor, confirmation)
                release.set()
                app._operations.join_worker()
                app._consume_events()

                method.assert_called_once()
                self.assertNotEqual(app._dictionary_controller.editor, confirmation)
                list_kind = (
                    "dictionary_japanese_list"
                    if language == "ja"
                    else "dictionary_english_list"
                )
                self.assertEqual(app._dictionary_controller.editor.kind, list_kind)
                self.assertEqual(app._dictionary_controller.editor.payload["entries"], ())
                self.assertEqual(app._status, success)

    def test_dictionary_failures_replace_busy_status_and_keep_both_languages_retryable(self):
        def fail(*_args, **_kwargs):
            raise RuntimeError("operation failed")

        for language in ("ja", "en"):
            with self.subTest(language=language, operation="generation"):
                app = self.make_app(batch_item=False)
                if language == "ja":
                    app._dictionary_controller._japanese_pronunciation = fail
                    app._dictionary_controller.open_quick_save_japanese(
                        surface="雨", pronunciation="ア'メ"
                    )
                    expected_busy = "Generating Japanese pronunciation…"
                    previous = app._dictionary_controller.editor.payload["pronunciation"]
                else:
                    app._dictionary_controller._english_word_groups = fail
                    app._dictionary_controller.open_quick_save_english(
                        surface="hello", phonemes="HH AH0"
                    )
                    expected_busy = "Generating English pronunciation…"
                    previous = app._dictionary_controller.editor.payload["phonemes"]
                editor = app._dictionary_controller.editor
                app._handle_key("g")
                self.assertEqual(app._status, expected_busy)
                self.complete_dictionary_operation(app)
                self.assertEqual(
                    app._status,
                    "Pronunciation was not generated: operation failed",
                )
                self.assertIs(app._status.kind, StatusKind.ERROR)
                self.assertFalse(app._operations.busy)
                self.assertIsNone(app._operations.worker_operation)
                self.assertIs(app._dictionary_controller.editor, editor)
                if language == "ja":
                    self.assertEqual(editor.payload["pronunciation"], previous)
                else:
                    self.assertEqual(editor.payload["phonemes"], previous)

            with self.subTest(language=language, operation="save"):
                app = self.make_app(batch_item=False)
                core = app.adapter.user_dictionary
                if language == "ja":
                    app._dictionary_controller.open_quick_save_japanese(
                        surface="雨", pronunciation="ア'メ"
                    )
                    method = core.add_japanese_word
                    expected_busy = "Saving Japanese dictionary word…"
                else:
                    app._dictionary_controller.open_quick_save_english(
                        surface="hello", phonemes="HH AH0"
                    )
                    method = core.set_english_entry
                    expected_busy = "Saving English dictionary word…"
                method.side_effect = fail
                editor = app._dictionary_controller.editor
                app._handle_key("s")
                self.assertEqual(app._status, expected_busy)
                self.complete_dictionary_operation(app)
                self.assertEqual(
                    app._status,
                    "Dictionary word was not saved: operation failed",
                )
                self.assertIs(app._status.kind, StatusKind.ERROR)
                self.assertIs(app._dictionary_controller.editor, editor)
                method.assert_called_once()

            with self.subTest(language=language, operation="delete"):
                app = self.make_app(batch_item=False)
                core = app.adapter.user_dictionary
                if language == "ja":
                    core.list_japanese_entries.return_value = {
                        "word-1": SimpleNamespace(
                            surface=normalize_surface("雨"),
                            pronunciation="アメ",
                            accent_type=1,
                            priority=5,
                            context_id=expand_word_type(JapaneseWordType.PROPER_NOUN.value)["context_id"],
                        )
                    }
                    method = core.delete_japanese_word
                    expected_busy = "Deleting Japanese dictionary word…"
                else:
                    core.list_english_entries.return_value = {
                        "hello": SimpleNamespace(
                            surface="hello",
                            phonemes=["HH", "AH0"],
                        )
                    }
                    method = core.delete_english_entry
                    expected_busy = "Deleting English dictionary word…"
                method.side_effect = fail
                app._dispatch_editor_intents((OpenDictionaryIntent(),))
                app._handle_key("j" if language == "ja" else "e")
                app._handle_key("x")
                confirmation = app._dictionary_controller.editor
                app._handle_key("d")
                self.assertEqual(app._status, expected_busy)
                self.complete_dictionary_operation(app)
                self.assertEqual(
                    app._status,
                    "Dictionary word was not deleted: operation failed",
                )
                self.assertIs(app._status.kind, StatusKind.ERROR)
                self.assertIs(app._dictionary_controller.editor, confirmation)
                self.assertEqual(confirmation.kind, "dictionary_delete_confirmation")
                method.assert_called_once()
