import tempfile
import unittest
from pathlib import Path

from voiceger_accent_adapter.filename import (
    build_output_filename,
    next_output_index,
    sanitize_filename_part,
    shorten_text_for_filename,
)


class FileNameTests(unittest.TestCase):
    def test_voicevox_style_default_shape(self):
        self.assertEqual(
            build_output_filename(
                index=1,
                character_name="ずんだもん",
                style_name="style_1",
                text="今日は雨ですね。",
            ),
            "001_ずんだもん（style_1）_今日は雨ですね。.wav",
        )

    def test_text_is_truncated_like_voicevox(self):
        self.assertEqual(
            shorten_text_for_filename("12345678901"),
            "123456789…",
        )

    def test_invalid_filename_characters_are_removed(self):
        self.assertEqual(
            sanitize_filename_part('a/b:c?"d*e|f'),
            "abcdef",
        )

    def test_next_index_uses_highest_existing_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "001_a.wav").write_bytes(b"")
            (root / "003_b.wav").write_bytes(b"")
            (root / "not-indexed.wav").write_bytes(b"")
            self.assertEqual(next_output_index(root), 4)


if __name__ == "__main__":
    unittest.main()
