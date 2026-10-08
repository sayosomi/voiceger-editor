import unittest

from voiceger_editor.settings import Settings
from voiceger_editor.tui_cli import build_argument_parser, settings_for_invocation


class TuiCliTests(unittest.TestCase):
    def test_command_line_options_still_override_persisted_defaults(self):
        args = build_argument_parser().parse_args(
            [
                "example",
                "--take-count",
                "8",
                "--style",
                "22",
                "--speed",
                "1.25",
                "--save-text",
                "--save-lab",
            ]
        )
        base = Settings()

        effective = settings_for_invocation(args, base)

        self.assertEqual(effective.take_count, 8)
        self.assertEqual(effective.style_id, 22)
        self.assertEqual(effective.speed, 1.25)
        self.assertTrue(effective.save_text)
        self.assertTrue(effective.save_lab)
        self.assertEqual(base, Settings())

    def test_terms_management_actions_are_mutually_exclusive(self):
        parser = build_argument_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["--accept-terms", "--show-terms-status"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["--accept-terms", "--open-terms"])


if __name__ == "__main__":
    unittest.main()
