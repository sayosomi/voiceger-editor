import curses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_editor.dictionary_export import DictionaryExportResult
from voiceger_editor.settings import Settings
from voiceger_editor.tui_dictionary import (
    DictionaryOperationIntent,
    OpenDictionarySettingsIntent,
    TuiDictionaryController,
)
from voiceger_editor.tui_rendering import TuiRenderer, TuiRenderState
from voiceger_editor.tui_shortcuts import menu_items
from voiceger_editor.tui_status import EMPTY_STATUS, StatusKind


class FakeDictionaryCore:
    def list_japanese_entries(self):
        return {}

    def list_english_entries(self):
        return {}


class TuiDictionaryExportTests(unittest.TestCase):
    def setUp(self):
        self.core = FakeDictionaryCore()
        self.current_output_dir = Path("/first-output")
        self.controller = TuiDictionaryController(
            self.core,
            input_prefix=lambda _editor: "▶ ",
            output_dir=lambda: self.current_output_dir,
        )

    @staticmethod
    def operation(intents):
        return next(
            intent
            for intent in intents
            if isinstance(intent, DictionaryOperationIntent)
        )

    def open_export(self):
        self.controller.open_menu()
        intents = self.controller.handle_key("x")
        self.assertTrue(intents)
        self.assertEqual(self.controller.editor.kind, "dictionary_export")

    def test_top_level_export_and_export_screen_use_declared_vertical_navigation(self):
        self.assertEqual(
            [item.key for item in menu_items("dictionary_menu")],
            ["japanese", "english", "import", "export", "back"],
        )
        self.open_export()
        self.assertEqual(
            [item.key for item in menu_items("dictionary_export")],
            ["output", "voiceger", "voicevox", "back"],
        )
        self.assertEqual(self.controller.editor.selection, "voiceger")

        self.controller.handle_key(curses.KEY_UP)
        self.assertEqual(self.controller.editor.selection, "output")
        self.controller.handle_key(curses.KEY_UP)
        self.assertEqual(self.controller.editor.selection, "output")
        self.controller.handle_key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "voiceger")
        self.controller.handle_key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "voicevox")
        self.controller.handle_key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "back")
        self.controller.handle_key(curses.KEY_DOWN)
        self.assertEqual(self.controller.editor.selection, "back")
        self.controller.handle_key("\x1b")
        self.assertEqual(self.controller.editor.kind, "dictionary_menu")

    def test_output_shortcut_suspends_export_for_direct_settings_edit(self):
        self.open_export()

        intents = self.controller.handle_key("o")

        self.assertEqual(
            intents,
            (OpenDictionarySettingsIntent("output_dir", edit=True),),
        )
        self.assertTrue(self.controller.active)
        self.assertEqual(self.controller.editor.selection, "output")
        self.assertTrue(self.controller.suspend_editor())
        self.assertFalse(self.controller.active)
        self.assertTrue(self.controller.restore_suspended_editor())
        self.assertEqual(self.controller.editor.kind, "dictionary_export")
        self.assertEqual(self.controller.editor.selection, "output")

    def test_voiceger_export_uses_current_output_dir_and_reports_actual_names(self):
        self.open_export()
        self.current_output_dir = Path("/new-output")
        result = DictionaryExportResult(
            paths=(
                Path("/new-output/202610060102_user_dict-2.json"),
                Path("/new-output/202610060102_english_user_dict-2.json"),
            )
        )
        with patch(
            "voiceger_editor.tui_dictionary.export_voiceger_editor_dictionaries",
            return_value=result,
        ) as export:
            operation = self.operation(self.controller.handle_key("e"))
            self.assertEqual(
                operation.status,
                "Exporting Voiceger Editor dictionaries…",
            )
            value = operation.work()

        export.assert_called_once_with(self.core, Path("/new-output"))
        completion = self.controller.complete_operation(operation.request, value)
        self.assertEqual(self.controller.editor.kind, "dictionary_export")
        self.assertIn("202610060102_user_dict-2.json", completion[0].status)
        self.assertIn(
            "202610060102_english_user_dict-2.json",
            completion[0].status,
        )

    def test_voicevox_export_and_failure_keep_export_screen_open(self):
        self.open_export()
        self.controller.handle_key(curses.KEY_DOWN)
        result = DictionaryExportResult(
            paths=(Path("/first-output/202610060102_voicevox_user_dict.json"),)
        )
        with patch(
            "voiceger_editor.tui_dictionary.export_voicevox_dictionary",
            return_value=result,
        ) as export:
            operation = self.operation(self.controller.handle_key("\n"))
            self.assertEqual(
                operation.status,
                "Exporting VOICEVOX dictionary…",
            )
            value = operation.work()

        export.assert_called_once_with(self.core, Path("/first-output"))
        self.controller.complete_operation(operation.request, value)
        self.assertEqual(self.controller.editor.kind, "dictionary_export")

        failed = self.operation(self.controller.handle_key("v"))
        completion = self.controller.complete_operation(
            failed.request,
            error=OSError("disk full"),
        )
        self.assertEqual(self.controller.editor.kind, "dictionary_export")
        self.assertEqual(
            completion[0].status,
            "Dictionary export was not completed: disk full",
        )
        self.assertIs(completion[0].status.kind, StatusKind.ERROR)

    def test_renderer_labels_voicevox_as_japanese_dictionary_only(self):
        self.open_export()
        editor = SimpleNamespace(
            kind="dictionary_export",
            title="EXPORT DICTIONARY",
            selection="voiceger",
            payload={},
            active_field=None,
            input_value="",
            input_cursor=0,
            error=EMPTY_STATUS,
        )
        settings = Settings(output_dir=Path("/shown-output"))
        state = TuiRenderState(
            voiceger_root=Path("/nonexistent/voiceger"),
            settings=settings,
            session=None,
            focus_key=("dictionary", None),
            status=EMPTY_STATUS,
            segments=(),
            pronunciation_rows=(),
            busy=False,
            worker_operation=None,
            worker_target=None,
            operation_completed=0,
            operation_total=0,
            pressed_adjustment=None,
            editor=editor,
        )
        document, _cursor_line, _cursor_column = TuiRenderer().editor_document(
            state,
            120,
        )
        rendered = "\n".join(text for text, _key in document)
        self.assertIn("[O] Output: /shown-output", rendered)
        self.assertIn("[E] Voiceger Editor", rendered)
        self.assertIn("Japanese + English", rendered)
        self.assertIn("[V] VOICEVOX", rendered)
        self.assertIn("Japanese dictionary only", rendered)
        self.assertNotIn("English dictionary is not included", rendered)
        self.assertEqual(
            [key for _text, key in document if key is not None],
            ["output", "voiceger", "voicevox", "back"],
        )


if __name__ == "__main__":
    unittest.main()
