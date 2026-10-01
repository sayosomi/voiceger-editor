import unittest
from datetime import datetime

from voiceger_editor.filename import (
    build_output_filename,
    sanitize_filename_part,
)


class FileNameTests(unittest.TestCase):
    def test_filename_uses_local_minute_timestamp_and_full_source(self):
        self.assertEqual(
            build_output_filename(
                text="今日はhelloと言うよ。",
                timestamp=datetime(2026, 9, 28, 1, 45, 32),
            ),
            "202609280145_今日はhelloと言うよ。.wav",
        )

    def test_filename_ignores_seconds(self):
        source = "同じ分です。"
        first = build_output_filename(
            text=source,
            timestamp=datetime(2026, 10, 1, 20, 45, 0),
        )
        second = build_output_filename(
            text=source,
            timestamp=datetime(2026, 10, 1, 20, 45, 59),
        )
        self.assertEqual(first, "202610012045_同じ分です。.wav")
        self.assertEqual(second, first)

    def test_filename_does_not_truncate_source_longer_than_old_limit(self):
        source = "12345678901とても長い発話です。"
        result = build_output_filename(
            text=source,
            timestamp=datetime(2026, 9, 27, 17, 55, 6),
        )
        self.assertEqual(
            result,
            f"202609271755_{source}.wav",
        )
        self.assertNotIn("…", result)

    def test_source_filename_characters_are_sanitized(self):
        self.assertEqual(
            build_output_filename(
                text='a/b:c?"d*e|f123456',
                timestamp=datetime(2026, 9, 27, 17, 55, 6),
            ),
            "202609271755_abcdef123456.wav",
        )

    def test_invalid_filename_characters_are_removed(self):
        self.assertEqual(
            sanitize_filename_part('a/b:c?"d*e|f'),
            "abcdef",
        )


if __name__ == "__main__":
    unittest.main()
