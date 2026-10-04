"""Tests for shared semantic TUI Status values."""

from copy import deepcopy
import unittest

from voiceger_editor.tui_status import (
    StatusKind,
    error_status,
    format_status,
    info_status,
    warning_status,
)


class TuiStatusTests(unittest.TestCase):
    def test_status_kind_is_semantic_and_formatter_owns_prefixes(self):
        cases = (
            (info_status("ready"), StatusKind.INFO, "Status: ready"),
            (warning_status("check this"), StatusKind.WARNING, "Warning: check this"),
            (error_status("failed"), StatusKind.ERROR, "Error: failed"),
        )

        for status, kind, formatted in cases:
            with self.subTest(kind=kind):
                self.assertIs(status.kind, kind)
                self.assertEqual(format_status(status), formatted)

    def test_message_prefix_text_does_not_determine_severity(self):
        status = info_status("Error: this is message text")

        self.assertIs(status.kind, StatusKind.INFO)
        self.assertEqual(
            format_status(status),
            "Status: Error: this is message text",
        )

    def test_status_is_deepcopy_safe_for_editor_state_snapshots(self):
        status = error_status("invalid draft")

        copied = deepcopy(status)

        self.assertIs(copied, status)
        self.assertIs(copied.kind, StatusKind.ERROR)

    def test_empty_status_formats_to_empty_text(self):
        self.assertEqual(format_status(info_status("")), "")


if __name__ == "__main__":
    unittest.main()
