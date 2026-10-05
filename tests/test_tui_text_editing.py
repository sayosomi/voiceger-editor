import curses
import unittest

from voiceger_editor.tui_text_editing import apply_text_edit_key


class TuiTextEditingTests(unittest.TestCase):
    def test_horizontal_home_and_end_movement_preserve_text(self):
        result = apply_text_edit_key("abcd", 2, curses.KEY_LEFT)
        self.assertEqual((result.value, result.cursor), ("abcd", 1))
        self.assertTrue(result.handled)
        self.assertFalse(result.text_changed)

        result = apply_text_edit_key("abcd", result.cursor, curses.KEY_RIGHT)
        self.assertEqual(result.cursor, 2)

        self.assertEqual(
            apply_text_edit_key("abcd", 2, curses.KEY_HOME).cursor,
            0,
        )
        self.assertEqual(
            apply_text_edit_key("abcd", 2, "\x01").cursor,
            0,
        )
        self.assertEqual(
            apply_text_edit_key("abcd", 2, curses.KEY_END).cursor,
            4,
        )
        self.assertEqual(
            apply_text_edit_key("abcd", 2, "\x05").cursor,
            4,
        )

        self.assertEqual(
            apply_text_edit_key("abcd", 0, curses.KEY_LEFT).cursor,
            0,
        )
        self.assertEqual(
            apply_text_edit_key("abcd", 4, curses.KEY_RIGHT).cursor,
            4,
        )

    def test_wrapped_vertical_movement_preserves_visual_column(self):
        down = apply_text_edit_key(
            "abcdef",
            1,
            curses.KEY_DOWN,
            input_width=3,
        )
        self.assertEqual(down.cursor, 4)

        up = apply_text_edit_key(
            down.value,
            down.cursor,
            curses.KEY_UP,
            input_width=3,
        )
        self.assertEqual(up.cursor, 1)

    def test_backspace_and_delete_report_edit_attempts_at_boundaries(self):
        backspace = apply_text_edit_key("abcd", 2, curses.KEY_BACKSPACE)
        self.assertEqual(
            (backspace.value, backspace.cursor),
            ("acd", 1),
        )
        self.assertTrue(backspace.text_changed)
        self.assertTrue(backspace.edit_attempted)

        delete = apply_text_edit_key("abcd", 2, curses.KEY_DC)
        self.assertEqual(
            (delete.value, delete.cursor),
            ("abd", 2),
        )
        self.assertTrue(delete.text_changed)
        self.assertTrue(delete.edit_attempted)

        blocked_backspace = apply_text_edit_key(
            "abcd",
            0,
            curses.KEY_BACKSPACE,
        )
        self.assertEqual(blocked_backspace.value, "abcd")
        self.assertFalse(blocked_backspace.text_changed)
        self.assertTrue(blocked_backspace.edit_attempted)

        blocked_delete = apply_text_edit_key(
            "abcd",
            4,
            curses.KEY_DC,
        )
        self.assertEqual(blocked_delete.value, "abcd")
        self.assertFalse(blocked_delete.text_changed)
        self.assertTrue(blocked_delete.edit_attempted)

    def test_printable_insertion_and_unhandled_control_keys(self):
        inserted = apply_text_edit_key("ab", 1, "XY")
        self.assertEqual(
            (inserted.value, inserted.cursor),
            ("aXYb", 3),
        )
        self.assertTrue(inserted.text_changed)
        self.assertTrue(inserted.edit_attempted)

        full_width_space = apply_text_edit_key("ab", 1, "　")
        self.assertEqual(full_width_space.value, "a　b")

        unhandled = apply_text_edit_key("ab", 1, "\x0e")
        self.assertFalse(unhandled.handled)
        self.assertEqual(
            (unhandled.value, unhandled.cursor),
            ("ab", 1),
        )


if __name__ == "__main__":
    unittest.main()
