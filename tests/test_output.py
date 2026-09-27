import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from voiceger_accent_adapter.filename import build_output_filename
from voiceger_accent_adapter.output import save_output


class OutputSaveTests(unittest.TestCase):
    timestamp = datetime(2026, 9, 27, 17, 55, 6)

    @staticmethod
    def fake_soundfile_module():
        module = ModuleType("soundfile")

        def write(path, audio, sampling_rate):
            Path(path).write_bytes(b"new wav")

        module.write = write
        return module

    def save(self, root, source_text, *, save_text=False):
        with patch.dict(
            "sys.modules",
            {"soundfile": self.fake_soundfile_module()},
        ):
            return save_output(
                audio=[0.0],
                sampling_rate=32000,
                source_text=source_text,
                output_dir=root,
                save_text=save_text,
                timestamp=self.timestamp,
            )

    def test_wav_collision_adds_deterministic_suffix_without_overwriting(self):
        source_text = "今日は雨ですね。"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / build_output_filename(
                text=source_text,
                timestamp=self.timestamp,
            )
            existing.write_bytes(b"keep existing")

            saved = self.save(root, source_text)

            self.assertEqual(saved.wav_path.stem, existing.stem + "-2")
            self.assertEqual(existing.read_bytes(), b"keep existing")
            self.assertEqual(saved.wav_path.read_bytes(), b"new wav")
            self.assertIsNone(saved.text_path)

    def test_paired_output_skips_basename_if_either_target_exists(self):
        source_text = "雨です。\r\n 次です。"
        initial_wav = build_output_filename(
            text=source_text,
            timestamp=self.timestamp,
        )
        initial_stem = Path(initial_wav).stem

        for extension in (".wav", ".txt"):
            with self.subTest(existing_extension=extension):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    existing = root / f"{initial_stem}{extension}"
                    existing.write_bytes(b"keep existing")

                    saved = self.save(root, source_text, save_text=True)

                    self.assertEqual(saved.wav_path.stem, initial_stem + "-2")
                    self.assertEqual(saved.text_path.stem, saved.wav_path.stem)
                    self.assertEqual(saved.text_path.suffix, ".txt")
                    self.assertEqual(existing.read_bytes(), b"keep existing")
                    self.assertEqual(
                        saved.text_path.read_bytes(),
                        source_text.encode("utf-8"),
                    )
                    self.assertEqual(saved.wav_path.read_bytes(), b"new wav")


if __name__ == "__main__":
    unittest.main()
