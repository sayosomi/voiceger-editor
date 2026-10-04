import curses
import unittest

from voiceger_editor.tui_help import HelpOutcome, TuiHelpController


class TuiHelpControllerTests(unittest.TestCase):
    def test_open_resets_scroll_and_close_preserves_owned_state(self):
        help_controller = TuiHelpController()
        help_controller.scroll = 7

        help_controller.open()

        self.assertTrue(help_controller.active)
        self.assertEqual(help_controller.scroll, 0)

        help_controller.close()

        self.assertFalse(help_controller.active)
        self.assertEqual(help_controller.scroll, 0)

    def test_up_down_scroll_clamps_to_available_range(self):
        help_controller = TuiHelpController()
        help_controller.open()

        help_controller.handle_key(
            curses.KEY_UP,
            height=12,
            max_scroll=3,
        )
        self.assertEqual(help_controller.scroll, 0)

        for _ in range(5):
            help_controller.handle_key(
                curses.KEY_DOWN,
                height=12,
                max_scroll=3,
            )

        self.assertEqual(help_controller.scroll, 3)
        self.assertTrue(help_controller.active)

    def test_page_scroll_uses_viewport_step_and_clamps(self):
        help_controller = TuiHelpController()
        help_controller.open()
        help_controller.scroll = 1

        help_controller.handle_key(
            curses.KEY_NPAGE,
            height=12,
            max_scroll=20,
        )
        self.assertEqual(help_controller.scroll, 10)

        help_controller.handle_key(
            curses.KEY_PPAGE,
            height=12,
            max_scroll=20,
        )
        self.assertEqual(help_controller.scroll, 1)

        help_controller.handle_key(
            curses.KEY_PPAGE,
            height=12,
            max_scroll=20,
        )
        self.assertEqual(help_controller.scroll, 0)

    def test_close_keys_close_without_requesting_quit(self):
        for key in ("\x1b", "?", "\n", "\r", curses.KEY_ENTER):
            with self.subTest(key=key):
                help_controller = TuiHelpController()
                help_controller.open()

                outcome = help_controller.handle_key(
                    key,
                    height=24,
                    max_scroll=5,
                )

                self.assertIs(outcome, HelpOutcome.CLOSED)
                self.assertFalse(help_controller.active)

    def test_quit_keys_close_and_return_quit_outcome(self):
        for key in ("q", "Q", "\x03"):
            with self.subTest(key=key):
                help_controller = TuiHelpController()
                help_controller.open()

                outcome = help_controller.handle_key(
                    key,
                    height=24,
                    max_scroll=5,
                )

                self.assertIs(outcome, HelpOutcome.QUIT)
                self.assertFalse(help_controller.active)

    def test_clamp_scroll_reconciles_state_after_terminal_resize(self):
        help_controller = TuiHelpController()
        help_controller.scroll = 12

        help_controller.clamp_scroll(4)
        self.assertEqual(help_controller.scroll, 4)

        help_controller.clamp_scroll(-1)
        self.assertEqual(help_controller.scroll, 0)


if __name__ == "__main__":
    unittest.main()
