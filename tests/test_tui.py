import curses
import json
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from voiceger_accent_adapter.settings import Settings
from voiceger_accent_adapter.tui import (
    TuiApp,
    _take_key_action,
    build_argument_parser,
    format_english_phonemes,
    settings_for_invocation,
)


class FakeScreen:
    def __init__(self, keys=()):
        self.keys = list(keys)
        self.rows = 24
        self.columns = 100

    def getmaxyx(self):
        return self.rows, self.columns

    def addnstr(self, *args):
        return None

    def move(self, *args):
        return None

    def refresh(self):
        return None

    def erase(self):
        return None

    def get_wch(self):
        if not self.keys:
            raise curses.error("no more fake keys")
        return self.keys.pop(0)


class TuiTests(unittest.TestCase):
    def test_english_display_hides_stress_digits_and_marks_primary_anchor(self):
        rendered = format_english_phonemes(
            ["V", "OY1", "AH0", "JH", "ER2"],
            selected_primary=0,
        )

        self.assertEqual(rendered, "V ▶[OY] AH JH ER")
        self.assertNotIn("0", rendered)
        self.assertNotIn("1", rendered)
        self.assertNotIn("2", rendered)

    def test_english_display_marks_other_primary_stress_without_stress_digits(self):
        rendered = format_english_phonemes(
            ["AA1", "K", "IY1", "ER2"],
            selected_primary=0,
        )

        self.assertEqual(rendered, "▶[AA] K [IY] ER")

    def test_take_review_key_map_uses_arrows_and_not_j_or_k(self):
        numbers = [1, 2, 4]
        self.assertEqual(
            _take_key_action(
                curses.KEY_DOWN,
                candidate_numbers=numbers,
                current_number=2,
            ),
            ("select", 4),
        )
        self.assertEqual(
            _take_key_action(
                curses.KEY_UP,
                candidate_numbers=numbers,
                current_number=4,
            ),
            ("select", 2),
        )
        self.assertEqual(
            _take_key_action("4", candidate_numbers=numbers, current_number=1),
            ("select", 4),
        )
        self.assertEqual(
            _take_key_action("r", candidate_numbers=numbers, current_number=2),
            ("regenerate", 2),
        )
        self.assertEqual(
            _take_key_action("R", candidate_numbers=numbers, current_number=2),
            ("regenerate_all", None),
        )
        self.assertIsNone(
            _take_key_action("j", candidate_numbers=numbers, current_number=2)
        )
        self.assertIsNone(
            _take_key_action("k", candidate_numbers=numbers, current_number=2)
        )

    def test_take_review_maps_space_and_enter(self):
        self.assertEqual(
            _take_key_action(" ", candidate_numbers=[3], current_number=3),
            ("replay", 3),
        )
        self.assertEqual(
            _take_key_action("\n", candidate_numbers=[3], current_number=3),
            ("accept", 3),
        )

    def test_command_line_options_override_persisted_defaults(self):
        args = build_argument_parser().parse_args(
            [
                "example",
                "--take-count", "8",
                "--style", "2",
                "--speed", "1.25",
                "--output-dir", "/tmp/voice-output",
                "--save-text",
            ]
        )
        base = Settings(take_count=4, style_id=1, speed=1.0, save_text=False)

        effective = settings_for_invocation(args, base)

        self.assertEqual(effective.take_count, 8)
        self.assertEqual(effective.style_id, 2)
        self.assertEqual(effective.speed, 1.25)
        self.assertEqual(effective.output_dir, Path("/tmp/voice-output"))
        self.assertTrue(effective.save_text)
        self.assertEqual(base, Settings())

    def test_interactive_change_does_not_persist_other_cli_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "settings.json"
            base = Settings(take_count=4, style_id=1)
            app = TuiApp(
                adapter=Mock(),
                settings=Settings(take_count=8, style_id=1),
                persisted_settings=base,
                config_path=config_path,
            )

            app._change_settings(save_text=True)

            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["take_count"], 4)
            self.assertTrue(persisted["save_text"])
            self.assertEqual(app.settings.take_count, 8)

    def test_text_editor_keeps_basic_cursor_and_backspace_controls(self):
        adapter = Mock()
        adapter.voiceger_root = Path("/nonexistent/voiceger")
        app = TuiApp(adapter=adapter, settings=Settings(), source_text="unused")
        app._screen = FakeScreen(
            [
                curses.KEY_LEFT,
                "X",
                curses.KEY_BACKSPACE,
                curses.KEY_END,
                "!",
                "\n",
            ]
        )

        value = app._read_line("Text", "ab")

        self.assertEqual(value, "ab!")


if __name__ == "__main__":
    unittest.main()
