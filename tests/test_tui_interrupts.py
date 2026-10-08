import unittest
from unittest.mock import Mock

from voiceger_editor.tui_interrupts import TuiInterruptController
from voiceger_editor.tui_operations import UpdateStatusEffect


class TuiInterruptControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = TuiInterruptController()
        self.operations = Mock()
        self.operations.can_cancel_batch = False
        self.operations.cancellation_guard_armed = False
        self.operations.request_batch_cancellation.return_value = (
            UpdateStatusEffect("Cancelling…"),
        )

    def test_ctrl_c_requests_active_batch_cancellation_without_quitting(self):
        self.operations.can_cancel_batch = True

        result = self.controller.handle_key("\x03", self.operations)

        self.assertTrue(result.handled)
        self.assertFalse(result.quit_requested)
        self.assertEqual(result.effects, (UpdateStatusEffect("Cancelling…"),))
        self.operations.request_batch_cancellation.assert_called_once_with()

    def test_ctrl_c_completion_guard_reports_finished_generation(self):
        self.operations.cancellation_guard_armed = True

        result = self.controller.handle_key("\x03", self.operations)

        self.assertTrue(result.handled)
        self.assertFalse(result.quit_requested)
        self.assertEqual(
            result.effects,
            (UpdateStatusEffect("Generation already finished; nothing to cancel."),),
        )
        self.operations.request_batch_cancellation.assert_not_called()

    def test_idle_ctrl_c_requests_quit(self):
        result = self.controller.handle_key("\x03", self.operations)

        self.assertTrue(result.handled)
        self.assertTrue(result.quit_requested)
        self.assertEqual(result.effects, ())

    def test_non_ctrl_c_clears_completion_guard_and_returns_unhandled(self):
        self.operations.cancellation_guard_armed = True

        result = self.controller.handle_key("x", self.operations)

        self.assertFalse(result.handled)
        self.assertFalse(result.quit_requested)
        self.operations.clear_completed_cancellation_guard.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
