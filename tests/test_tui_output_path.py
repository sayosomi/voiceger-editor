import curses
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.tui_app_test_support import TuiAppTestCase, mixed_query

from voiceger_editor.tui_output_path import TuiOutputPathController


class TuiOutputPathControllerTests(unittest.TestCase):
    def make_controller(self, *, save_result=True):
        state = {
            "path": Path("/saved/output"),
            "status": None,
            "saved": [],
        }

        def save(value):
            state["saved"].append(value)
            if save_result:
                state["path"] = Path(value).expanduser()
            return save_result

        controller = TuiOutputPathController(
            get_output_dir=lambda: state["path"],
            save_output_dir=save,
            set_status=lambda value: state.__setitem__("status", value),
        )
        return controller, state

    def test_begin_uses_current_shared_output_and_enter_saves(self):
        controller, state = self.make_controller()

        self.assertTrue(controller.begin("dictionary_export"))
        self.assertEqual(controller.state.value, "/saved/output")
        self.assertEqual(controller.state.cursor, len("/saved/output"))

        controller.handle_key(curses.KEY_HOME)
        controller.handle_key("x")
        self.assertTrue(controller.active)
        controller.handle_key("\n")

        self.assertFalse(controller.active)
        self.assertEqual(state["saved"], ["x/saved/output"])

    def test_escape_cancels_without_saving(self):
        controller, state = self.make_controller()
        controller.begin("batch_list")

        controller.handle_key("\x1b")

        self.assertFalse(controller.active)
        self.assertEqual(state["saved"], [])

    def test_failed_save_keeps_editor_active_for_retry(self):
        controller, state = self.make_controller(save_result=False)
        controller.begin("batch_write")

        controller.handle_key("\n")

        self.assertTrue(controller.active)
        self.assertEqual(state["saved"], ["/saved/output"])

    def test_begin_is_not_globally_blocked_by_background_work(self):
        controller, _state = self.make_controller()

        self.assertTrue(controller.begin("batch_list"))

        self.assertTrue(controller.active)


class BatchOutputIntegrationTests(TuiAppTestCase):
    def test_batch_output_edit_is_shared_and_cancel_does_not_change_settings(self):
        app = self.make_app(query=mixed_query())
        app._handle_key("\x1b")
        previous = app.settings.output_dir

        app._handle_key("f")
        self.assertTrue(app._output_path_controller.active)
        app._output_path_controller.state.value = "/tmp/unsaved-batch-output"
        app._handle_key("\x1b")
        self.assertEqual(app.settings.output_dir, previous)

        app._handle_key("f")
        app._output_path_controller.state.value = "/tmp/saved-batch-output"
        with patch("voiceger_editor.tui.save_settings") as save:
            app._handle_key("\n")
        save.assert_called_once()
        self.assertEqual(app.settings.output_dir, Path("/tmp/saved-batch-output"))
        self.assertFalse(app._output_path_controller.active)



if __name__ == "__main__":
    unittest.main()
