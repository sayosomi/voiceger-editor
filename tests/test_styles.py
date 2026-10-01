import tempfile
import unittest
from pathlib import Path

from voiceger_editor.styles import (
    KNOWN_STYLES,
    PRESET_PROMPT_TEXT,
    available_styles,
    get_style,
)


class StyleTests(unittest.TestCase):
    def test_known_reference_files_become_styles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refs = root / "reference"
            refs.mkdir()
            (refs / "01_ref_emoNormal026.wav").write_bytes(b"")
            (refs / "05_ref_emoSasa026.wav").write_bytes(b"")

            styles = available_styles(root)

            self.assertEqual(
                [(style.id, style.name) for style in styles],
                [(3, "Neutral"), (22, "Whispering")],
            )
            self.assertEqual(styles[0].prompt_text, PRESET_PROMPT_TEXT)

    def test_known_styles_use_voicevox_zundamon_ids(self):
        self.assertEqual(
            [(style.id, style.name) for style in KNOWN_STYLES],
            [
                (3, "Neutral"),
                (1, "Sweet"),
                (7, "Snippy"),
                (5, "Sexy"),
                (22, "Whispering"),
                (38, "Murmuring"),
                (75, "Exhausted"),
                (76, "Sobbing"),
            ],
        )

    def test_get_style_resolves_voicevox_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refs = root / "reference"
            refs.mkdir()
            (refs / "08_ref_emoSobbing026.wav").write_bytes(b"")

            style = get_style(root, 76)
            self.assertEqual(style.name, "Sobbing")
            self.assertEqual(style.filename, "08_ref_emoSobbing026.wav")

    def test_missing_style_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reference").mkdir()

            with self.assertRaises(ValueError):
                get_style(root, 3)


if __name__ == "__main__":
    unittest.main()
