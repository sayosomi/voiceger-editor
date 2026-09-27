import unittest
from unittest.mock import patch

from voiceger_accent_adapter.pronunciation import AccentPhrase, Pronunciation
from voiceger_accent_adapter.voiceger_adapter import resolve_pronunciation


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


if __name__ == "__main__":
    unittest.main()
