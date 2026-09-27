import unittest
from datetime import datetime

from voiceger_accent_adapter.filename import (
    build_output_filename,
    sanitize_filename_part,
)


class FileNameTests(unittest.TestCase):
    def test_filename_uses_local_timestamp_style_and_full_source(self):
        self.assertEqual(
            build_output_filename(
                style_name="Neutral",
                text="今日はhelloと言うよ。",
                timestamp=datetime(2026, 9, 28, 1, 45, 32),
            ),
            "20260928014532_Neutral_今日はhelloと言うよ。.wav",
        )

    def test_filename_does_not_truncate_source_longer_than_old_limit(self):
        source = "12345678901とても長い発話です。"
        result = build_output_filename(
            style_name="Murmuring",
            text=source,
            timestamp=datetime(2026, 9, 27, 17, 55, 6),
        )
        self.assertEqual(
            result,
            f"20260927175506_Murmuring_{source}.wav",
        )
        self.assertNotIn("…", result)

    def test_style_and_source_filename_characters_are_sanitized(self):
        self.assertEqual(
            build_output_filename(
                style_name='Ne/utr:al?',
                text='a/b:c?"d*e|f123456',
                timestamp=datetime(2026, 9, 27, 17, 55, 6),
            ),
            "20260927175506_Neutral_abcdef123456.wav",
        )

    def test_invalid_filename_characters_are_removed(self):
        self.assertEqual(
            sanitize_filename_part('a/b:c?"d*e|f'),
            "abcdef",
        )


if __name__ == "__main__":
    unittest.main()
