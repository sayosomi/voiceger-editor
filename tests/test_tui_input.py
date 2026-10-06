import curses
import unittest

from voiceger_editor.tui_input import PasteText, TuiInputReader


class FakeScreen:
    def __init__(self, keys=()):
        self.keys = list(keys)
        self.timeouts = []

    def get_wch(self):
        if not self.keys:
            raise curses.error("no more fake keys")
        return self.keys.pop(0)

    def timeout(self, milliseconds):
        self.timeouts.append(milliseconds)


class TuiInputReaderTests(unittest.TestCase):
    def test_enter_without_queued_input_remains_finish_key(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\n"])

        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            "\n",
        )
        self.assertEqual(screen.timeouts, [5, 100])

    def test_enter_with_queued_input_is_inferred_as_paste_newline(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\n", "s"])

        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            PasteText("\n"),
        )
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            "s",
        )
        self.assertEqual(screen.timeouts, [5, 100])

    def test_keypad_enter_with_queued_input_is_inferred_as_paste_newline(self):
        reader = TuiInputReader()
        screen = FakeScreen([curses.KEY_ENTER, "s"])

        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            PasteText("\n"),
        )
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            "s",
        )

    def test_consecutive_paste_newlines_preserve_blank_line(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\n", "\n", "x"])

        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            PasteText("\n"),
        )
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            PasteText("\n"),
        )
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            "x",
        )

    def test_trailing_newline_in_active_paste_burst_is_preserved(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\n", "x", "\n"])

        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            PasteText("\n"),
        )
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            "x",
        )
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            PasteText("\n"),
        )

    def test_idle_timeout_ends_paste_burst_before_manual_enter(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\n", "x"])

        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            PasteText("\n"),
        )
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            "x",
        )
        self.assertIsNone(
            reader.read(screen, infer_paste_newlines=True)
        )

        screen.keys.append("\n")
        self.assertEqual(
            reader.read(screen, infer_paste_newlines=True),
            "\n",
        )

    def test_paste_inference_is_disabled_outside_add_captions(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\n", "x"])

        self.assertEqual(
            reader.read(screen, infer_paste_newlines=False),
            "\n",
        )
        self.assertEqual(screen.keys, ["x"])
        self.assertEqual(screen.timeouts, [])

    def test_keyboard_interrupt_is_normalized_to_ctrl_c_key(self):
        class InterruptScreen(FakeScreen):
            def get_wch(self):
                raise KeyboardInterrupt

        reader = TuiInputReader()

        self.assertEqual(reader.read(InterruptScreen()), "\x03")


if __name__ == "__main__":
    unittest.main()
