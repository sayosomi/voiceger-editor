import curses
from pathlib import Path
import unittest

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
        controller.begin("batch_item")

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

        self.assertTrue(controller.begin("batch_item"))

        self.assertTrue(controller.active)


if __name__ == "__main__":
    unittest.main()
