import curses
import unittest

from voiceger_editor.tui_numbered_list import NumberedListJump


class NumberedListJumpTests(unittest.TestCase):
    def test_one_through_nine_activate_existing_visible_numbers_immediately(self):
        jump = NumberedListJump()

        first = jump.handle_key("1", item_count=9)
        ninth = jump.handle_key("9", item_count=9)

        self.assertTrue(first.handled)
        self.assertEqual(first.target_number, 1)
        self.assertEqual(ninth.target_number, 9)
        self.assertFalse(jump.active)

    def test_unavailable_direct_digit_is_a_handled_no_op(self):
        jump = NumberedListJump()

        outcome = jump.handle_key("9", item_count=3)

        self.assertTrue(outcome.handled)
        self.assertIsNone(outcome.target_number)
        self.assertFalse(jump.active)

    def test_zero_requires_ten_items_and_enters_explicit_number_mode(self):
        jump = NumberedListJump()

        self.assertFalse(jump.handle_key("0", item_count=9).handled)
        self.assertTrue(jump.handle_key("0", item_count=10).handled)
        self.assertTrue(jump.active)
        self.assertEqual(jump.value, "")

    def test_explicit_mode_collects_digits_and_opens_valid_multi_digit_target(self):
        jump = NumberedListJump()
        jump.handle_key("0", item_count=12)
        jump.handle_key("1", item_count=12)
        jump.handle_key("1", item_count=12)

        outcome = jump.handle_key("\n", item_count=12)

        self.assertEqual(outcome.target_number, 11)
        self.assertFalse(jump.active)
        self.assertEqual(jump.value, "")

    def test_invalid_enter_stays_active_and_reports_warning(self):
        jump = NumberedListJump()
        jump.handle_key("0", item_count=12)
        jump.handle_key("1", item_count=12)
        jump.handle_key("3", item_count=12)

        outcome = jump.handle_key(curses.KEY_ENTER, item_count=12)

        self.assertTrue(jump.active)
        self.assertEqual(jump.value, "13")
        self.assertEqual(outcome.warning, "Enter a number from 1 to 12.")

    def test_escape_cancels_and_other_actions_are_swallowed_while_active(self):
        jump = NumberedListJump()
        jump.handle_key("0", item_count=12)

        swallowed = jump.handle_key("a", item_count=12)
        cancelled = jump.handle_key("\x1b", item_count=12)

        self.assertTrue(swallowed.handled)
        self.assertIsNone(swallowed.target_number)
        self.assertTrue(cancelled.handled)
        self.assertFalse(jump.active)

    def test_backspace_allows_correction_without_timeout_logic(self):
        jump = NumberedListJump()
        jump.handle_key("0", item_count=12)
        jump.handle_key("1", item_count=12)
        jump.handle_key("3", item_count=12)
        jump.handle_key(curses.KEY_BACKSPACE, item_count=12)
        jump.handle_key("2", item_count=12)

        outcome = jump.handle_key("\n", item_count=12)

        self.assertEqual(outcome.target_number, 12)


if __name__ == "__main__":
    unittest.main()
