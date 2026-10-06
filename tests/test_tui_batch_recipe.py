import curses
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from voiceger_editor.batch_recipe import BatchRecipeError
from voiceger_editor.caption_batch import CaptionBatch
from voiceger_editor.settings import Settings
from voiceger_editor.tui_batch import TuiBatchController
from voiceger_editor.tui_batch_recipe import TuiBatchRecipeController
from voiceger_editor.tui_editors import OpenHelpIntent, QuitIntent, UpdateStatusIntent
from voiceger_editor.tui_output_path import BeginOutputPathEditIntent


class FakeSession:
    def __init__(self, caption):
        self.caption = caption
        self.candidates = ()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class TuiBatchRecipeControllerTests(unittest.TestCase):
    def make_owner(self, text=""):
        owner = TuiBatchController(default_take_count=4)
        if text:
            owner.add_captions(text, session_factory=FakeSession)
        return owner

    def make_controller(self, owner, *, reader=None, writer=None):
        settings = Settings(output_dir=Path("/tmp/voiceger-output"))
        return TuiBatchRecipeController(
            adapter=SimpleNamespace(name="adapter"),
            runtime_settings=lambda: settings,
            current_batch=lambda: owner.batch,
            replace_batch=owner.replace_batch,
            output_dir=lambda: settings.output_dir,
            input_prefix=lambda _editor: "▶ ",
            reader=reader or Mock(),
            writer=writer or Mock(),
        )

    @staticmethod
    def set_path(controller, path):
        controller.editor.input_value = path
        controller.editor.input_cursor = len(path)
        controller.handle_key("\n")

    @staticmethod
    def status_text(intents):
        for intent in intents:
            if isinstance(intent, UpdateStatusIntent):
                return str(intent.status)
        return ""

    def test_read_defaults_to_output_directory_and_write_uses_shared_output(self):
        owner = self.make_owner()
        controller = self.make_controller(owner)
        output_dir = Path("/tmp/voiceger-output")

        controller.open_read()
        self.assertEqual(controller.editor.kind, "batch_recipe_read_path")
        self.assertEqual(
            controller.editor.input_value,
            str(output_dir) + os.sep,
        )
        self.assertEqual(controller.editor.active_field, "path")

        controller.handle_key("\x1b")
        self.assertFalse(controller.active)

        controller.open_write()
        self.assertEqual(controller.editor.kind, "batch_recipe_write_path")
        self.assertEqual(controller.editor.selection, "file_name")
        self.assertIsNone(controller.editor.active_field)
        self.assertEqual(
            controller.editor.payload["file_name"],
            "batch.voiceger.json",
        )
        self.assertEqual(
            controller.handle_key("f"),
            (BeginOutputPathEditIntent("batch_write"),),
        )

    def test_printable_shortcuts_are_path_text_while_editing(self):
        owner = self.make_owner()
        controller = self.make_controller(owner)
        controller.open_read()
        opening = controller.editor.input_value

        for key in ("f", "r", "w", "q", "?"):
            self.assertEqual(controller.handle_key(key), ())

        self.assertEqual(controller.editor.input_value, opening + "frwq?")
        self.assertEqual(controller.editor.active_field, "path")

        controller.handle_key("\n")
        self.assertIsNone(controller.editor.active_field)
        controller.handle_key("f")
        self.assertEqual(controller.editor.active_field, "path")
        controller.handle_key("\n")
        self.assertIsInstance(controller.handle_key("?")[0], OpenHelpIntent)
        self.assertIsInstance(controller.handle_key("q")[0], QuitIntent)

    def test_invalid_read_keeps_current_batch_and_does_not_expand_path_in_tui(self):
        owner = self.make_owner("current")
        current = owner.batch
        reader = Mock(side_effect=BatchRecipeError("invalid recipe"))
        controller = self.make_controller(owner, reader=reader)

        controller.open_read()
        self.set_path(controller, "~/edited.voiceger.json")
        intents = controller.handle_key("r")

        self.assertEqual(intents, ())
        self.assertIs(owner.batch, current)
        self.assertEqual(controller.editor.kind, "batch_recipe_read_path")
        self.assertIn("Batch was not read: invalid recipe", str(controller.editor.error))
        reader.assert_called_once()
        self.assertEqual(reader.call_args.args[0], "~/edited.voiceger.json")
        self.assertIn("adapter", reader.call_args.kwargs)
        self.assertIn("runtime_settings", reader.call_args.kwargs)

    def test_read_into_empty_batch_replaces_only_after_core_returns(self):
        owner = self.make_owner()
        replacement = self.make_owner("loaded first\nloaded second").batch
        reader = Mock(return_value=replacement)
        controller = self.make_controller(owner, reader=reader)

        controller.open_read()
        self.set_path(controller, "/tmp/loaded.voiceger.json")
        intents = controller.handle_key("r")

        self.assertIs(owner.batch, replacement)
        self.assertFalse(controller.active)
        self.assertEqual(owner.focus_key, ("caption", 0))
        self.assertEqual(
            self.status_text(intents),
            "Batch read: /tmp/loaded.voiceger.json",
        )

    def test_nonempty_read_requires_cancel_focused_replacement_confirmation(self):
        owner = self.make_owner("current")
        current = owner.batch
        replacement = self.make_owner("loaded").batch
        loaded_session = replacement.items[0].session
        reader = Mock(return_value=replacement)
        controller = self.make_controller(owner, reader=reader)

        controller.open_read()
        self.set_path(controller, "/tmp/loaded.voiceger.json")
        controller.handle_key("r")

        self.assertIs(owner.batch, current)
        self.assertEqual(
            controller.editor.kind,
            "batch_recipe_replace_confirmation",
        )
        self.assertEqual(controller.editor.selection, "cancel")
        self.assertEqual(loaded_session.close_calls, 0)

        controller.handle_key("\x1b")

        self.assertIs(owner.batch, current)
        self.assertEqual(loaded_session.close_calls, 1)
        self.assertEqual(controller.editor.kind, "batch_recipe_read_path")
        self.assertEqual(controller.editor.selection, "read")
        self.assertEqual(
            controller.editor.payload["path"],
            "/tmp/loaded.voiceger.json",
        )

    def test_confirmed_read_replaces_current_batch_and_closes_old_sessions(self):
        owner = self.make_owner("current first\ncurrent second")
        previous_sessions = owner.sessions
        replacement = self.make_owner("loaded").batch
        loaded_session = replacement.items[0].session
        reader = Mock(return_value=replacement)
        controller = self.make_controller(owner, reader=reader)

        controller.open_read()
        self.set_path(controller, "/tmp/loaded.voiceger.json")
        controller.handle_key("r")
        intents = controller.handle_key("r")

        self.assertIs(owner.batch, replacement)
        self.assertFalse(controller.active)
        self.assertTrue(all(session.close_calls == 1 for session in previous_sessions))
        self.assertEqual(loaded_session.close_calls, 0)
        self.assertEqual(
            self.status_text(intents),
            "Batch read: /tmp/loaded.voiceger.json",
        )

    def test_confirmation_arrow_and_enter_semantics_keep_cancel_as_default(self):
        owner = self.make_owner("current")
        replacement = self.make_owner("loaded").batch
        controller = self.make_controller(owner, reader=Mock(return_value=replacement))

        controller.open_read()
        self.set_path(controller, "/tmp/loaded.voiceger.json")
        controller.handle_key("r")

        controller.handle_key(curses.KEY_DOWN)
        self.assertEqual(controller.editor.selection, "cancel")
        controller.handle_key(curses.KEY_UP)
        self.assertEqual(controller.editor.selection, "replace")
        controller.handle_key("\n")

        self.assertIs(owner.batch, replacement)

    def test_write_delegates_to_core_under_shared_output_directory(self):
        owner = self.make_owner("current")
        target = Path("/tmp/voiceger-output") / "saved.voiceger.json"
        writer = Mock(return_value=target)
        controller = self.make_controller(owner, writer=writer)

        controller.open_write()
        controller.handle_key("\n")
        controller.editor.input_value = "saved.voiceger.json"
        controller.editor.input_cursor = len("saved.voiceger.json")
        controller.handle_key("\n")
        intents = controller.handle_key("w")

        writer.assert_called_once_with(target, owner.batch)
        self.assertFalse(controller.active)
        self.assertEqual(
            self.status_text(intents),
            f"Batch written: {target}",
        )

    def test_write_failure_keeps_editor_open_and_batch_unchanged(self):
        owner = self.make_owner("current")
        current = owner.batch
        writer = Mock(side_effect=BatchRecipeError("not prepared"))
        controller = self.make_controller(owner, writer=writer)

        controller.open_write()
        controller.editor.payload["file_name"] = "fail.voiceger.json"
        intents = controller.handle_key("w")

        self.assertEqual(intents, ())
        self.assertIs(owner.batch, current)
        self.assertEqual(controller.editor.kind, "batch_recipe_write_path")
        self.assertIn("Batch was not written: not prepared", str(controller.editor.error))

    def test_write_rejects_a_file_name_that_escapes_output_directory(self):
        owner = self.make_owner("current")
        writer = Mock()
        controller = self.make_controller(owner, writer=writer)

        controller.open_write()
        controller.editor.payload["file_name"] = "../outside.voiceger.json"
        intents = controller.handle_key("w")

        self.assertEqual(intents, ())
        writer.assert_not_called()
        self.assertIn("File name must be one file name", str(controller.editor.error))


if __name__ == "__main__":
    unittest.main()
