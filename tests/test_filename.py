import unittest
from datetime import datetime

from voiceger_accent_adapter.filename import (
    build_output_filename,
    sanitize_filename_part,
    shorten_text_for_filename,
)


class FileNameTests(unittest.TestCase):
    def test_timestamped_wav_filename_uses_supplied_local_time(self):
        self.assertEqual(
            build_output_filename(
                text="今日は雨ですね。",
                timestamp=datetime(2026, 9, 27, 17, 55, 6),
            ),
            "20260927_175506_今日は雨ですね。.wav",
        )

    def test_text_is_truncated_like_voicevox(self):
        self.assertEqual(
            shorten_text_for_filename("12345678901"),
            "123456789…",
        )

    def test_sanitization_and_truncation_are_applied_to_filename_text(self):
        self.assertEqual(
            build_output_filename(
                text='a/b:c?"d*e|f123456',
                timestamp=datetime(2026, 9, 27, 17, 55, 6),
            ),
            "20260927_175506_abcdef123….wav",
        )

    def test_invalid_filename_characters_are_removed(self):
        self.assertEqual(
            sanitize_filename_part('a/b:c?"d*e|f'),
            "abcdef",
        )


if __name__ == "__main__":
    unittest.main()
