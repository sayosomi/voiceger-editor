import curses
import unittest
from unittest.mock import call, patch

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
    def test_bracketed_paste_mode_is_enabled_and_disabled_once(self):
        reader = TuiInputReader()
        with patch("voiceger_editor.tui_input.curses.putp") as putp:
            reader.set_bracketed_paste(True)
            reader.set_bracketed_paste(True)
            reader.close()

        self.assertEqual(
            putp.call_args_list,
            [call(b"\x1b[?2004h"), call(b"\x1b[?2004l")],
        )

    def test_bracketed_paste_returns_one_multiline_payload(self):
        reader = TuiInputReader()
        screen = FakeScreen(
            list("\x1b[200~first\r\n\nsecond\x1b[201~")
        )
        with patch("voiceger_editor.tui_input.curses.putp"):
            reader.set_bracketed_paste(True)
            event = reader.read(screen)

        self.assertEqual(event, PasteText("first\n\nsecond"))
        self.assertEqual(screen.timeouts, [5, 100])

    def test_enter_remains_an_ordinary_enter_while_paste_mode_is_enabled(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\n"])
        with patch("voiceger_editor.tui_input.curses.putp"):
            reader.set_bracketed_paste(True)
            self.assertEqual(reader.read(screen), "\n")

    def test_unmatched_escape_sequence_is_not_consumed(self):
        reader = TuiInputReader()
        screen = FakeScreen(["\x1b", "[", "X"])
        with patch("voiceger_editor.tui_input.curses.putp"):
            reader.set_bracketed_paste(True)
            self.assertEqual(reader.read(screen), "\x1b")
            self.assertEqual(reader.read(screen), "[")
            self.assertEqual(reader.read(screen), "X")


if __name__ == "__main__":
    unittest.main()
