import unittest
from threading import Event

from voiceger_editor.tui_interrupts import TuiInterruptController
from voiceger_editor.tui_operations import TuiOperations, UpdateStatusEffect


class TuiInterruptControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = TuiInterruptController()
        self.operations = TuiOperations()

    def test_ctrl_c_requests_generation_cancellation_without_quit(self):
        cancellation_event = Event()
        self.operations.busy = True
        self.operations.worker_operation = "initial"
        self.operations._cancellation_event = cancellation_event

        result = self.controller.handle_key("\x03", self.operations)

        self.assertTrue(result.handled)
        self.assertEqual(result.effects, (UpdateStatusEffect("Cancelling…"),))
        self.assertTrue(cancellation_event.is_set())

    def test_completed_generation_guard_makes_repeated_ctrl_c_harmless(self):
        self.operations._ctrl_c_cancellation_guard = True

        first = self.controller.handle_key("\x03", self.operations)
        second = self.controller.handle_key("\x03", self.operations)

        self.assertTrue(first.handled)
        self.assertTrue(second.handled)
        self.assertTrue(self.operations.cancellation_guard_armed)
        self.assertEqual(
            first.effects,
            (UpdateStatusEffect("Generation already finished; nothing to cancel."),),
        )

    def test_non_ctrl_c_clears_completed_guard_then_idle_ctrl_c_falls_through(self):
        self.operations._ctrl_c_cancellation_guard = True

        ordinary = self.controller.handle_key("j", self.operations)
        ctrl_c = self.controller.handle_key("\x03", self.operations)

        self.assertFalse(ordinary.handled)
        self.assertFalse(self.operations.cancellation_guard_armed)
        self.assertFalse(ctrl_c.handled)
        self.assertEqual(ctrl_c.effects, ())

    def test_non_ctrl_c_does_not_clear_guard_while_generation_is_active(self):
        self.operations.busy = True
        self.operations.worker_operation = "regenerate_all"
        self.operations._ctrl_c_cancellation_guard = True

        result = self.controller.handle_key("?", self.operations)

        self.assertFalse(result.handled)
        self.assertTrue(self.operations.cancellation_guard_armed)


if __name__ == "__main__":
    unittest.main()
