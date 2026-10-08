"""Conflict-policy tests kept beside the focused operation policy owner."""

import unittest

from voiceger_editor.tui_operations import TuiOperations


class TuiOperationConflictTests(unittest.TestCase):
    def setUp(self):
        self.operations = TuiOperations()

    def test_settings_conflicts_block_synthesis_but_allow_future_take_count(self):
        self.operations.busy = True
        self.operations.worker_operation = "initial"

        self.assertIsNone(
            self.operations.settings_change_conflict_status(("take_count",))
        )
        self.assertIsNone(
            self.operations.settings_change_conflict_status(("output_dir",))
        )
        conflict = self.operations.settings_change_conflict_status(("speed",))
        self.assertIsNotNone(conflict)
        self.assertIn("Synthesis settings cannot change", str(conflict))

    def test_output_setting_changes_are_blocked_while_accepting(self):
        self.operations.busy = True
        self.operations.worker_operation = "accept"

        for name in (
            "output_dir",
            "filename_template",
            "output_format",
            "wav_encoding",
            "flac_encoding",
            "mp3_bitrate",
            "save_text",
            "save_lab",
        ):
            with self.subTest(name=name):
                conflict = self.operations.settings_change_conflict_status((name,))
                self.assertIsNotNone(conflict)
                self.assertIn("Output settings cannot change", str(conflict))


if __name__ == "__main__":
    unittest.main()
