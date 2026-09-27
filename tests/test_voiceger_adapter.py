import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from voiceger_accent_adapter.pronunciation import AccentPhrase, Pronunciation
from voiceger_accent_adapter.voiceger_adapter import (
    _filename_text,
    _next_output_path,
    resolve_pronunciation,
)


class ResolvePronunciationTests(unittest.TestCase):
    def test_manual_pronunciation_is_canonicalized(self):
        text, parsed, resolved = resolve_pronunciation(
            "今日は雨ですね。",
            "キョ'ーワ/アメデスネ'。",
        )
        self.assertEqual(text, "今日は雨ですね。")
        self.assertEqual(resolved, "キョ'ーワ/アメデスネ'。")
        self.assertEqual(parsed.phrases[1].accent, 5)

    def test_missing_manual_terminator_uses_text_terminator(self):
        text, _, resolved = resolve_pronunciation(
            "雨？",
            "ア'メ",
        )
        self.assertEqual(text, "雨？")
        self.assertEqual(resolved, "ア'メ？")

    def test_text_without_terminator_gets_period(self):
        fake = Pronunciation(
            phrases=(AccentPhrase(("ア", "メ"), 1),),
            terminator="。",
        )
        with patch(
            "voiceger_accent_adapter.voiceger_adapter.text_to_pronunciation",
            return_value=fake,
        ):
            text, _, resolved = resolve_pronunciation("雨")

        self.assertEqual(text, "雨。")
        self.assertEqual(resolved, "ア'メ。")

    def test_rejects_newlines(self):
        with self.assertRaises(ValueError):
            resolve_pronunciation("一行目\n二行目")


class OutputFilenameTests(unittest.TestCase):
    def test_readable_dated_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _next_output_path(
                Path(tmp),
                "今日は雨ですね。",
                now=datetime(2026, 9, 27, 12, 0, 0),
            )
            self.assertEqual(path.name, "20260927_今日は雨ですね。.wav")

    def test_duplicate_adds_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "20260927_今日は雨ですね。.wav"
            existing.touch()

            path = _next_output_path(
                root,
                "今日は雨ですね。",
                now=datetime(2026, 9, 27, 12, 0, 0),
            )
            self.assertEqual(path.name, "20260927_今日は雨ですね。_2.wav")

    def test_unsafe_filename_characters_are_replaced(self):
        self.assertEqual(
            _filename_text('A/B:C*D?E"F<G>H|I'),
            "A_B_C_D_E_F_G_H_I",
        )


if __name__ == "__main__":
    unittest.main()
