import unittest

from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.voiceger_tokens import (
    VoicegerTokenConversionError,
    pronunciation_to_voiceger_tokens,
)


PHONES = {
    "あ": ["a"],
    "め": ["m", "e"],
    "きょ": ["ky", "o"],
    "わ": ["w", "a"],
    "て": ["t", "e"],
    "ん": ["N"],
    "き": ["k", "i"],
    "で": ["d", "e"],
    "す": ["s", "u"],
    "ね": ["n", "e"],
    "が": ["g", "a"],
    "っ": ["cl"],
    "こ": ["k", "o"],
}


def fake_g2p(mora):
    return PHONES[mora]


class VoicegerTokenTests(unittest.TestCase):
    def test_rain(self):
        value = parse_pronunciation("あ'め")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            ["a", "]", "m", "e"],
        )

    def test_candy(self):
        value = parse_pronunciation("あめ'")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            ["a", "[", "m", "e"],
        )

    def test_nakadaka(self):
        value = parse_pronunciation("てん'き")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            ["t", "e", "[", "N", "]", "k", "i"],
        )

    def test_phrase_boundary_adds_no_hash_token(self):
        value = parse_pronunciation("あめ'/あ'め。")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            ["a", "[", "m", "e", "a", "]", "m", "e", "."],
        )

    def test_long_vowel_repeats_previous_vowel(self):
        value = parse_pronunciation("きょ'ーわ")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            ["ky", "o", "]", "o", "w", "a"],
        )

    def test_long_vowel_cannot_start_phrase(self):
        value = parse_pronunciation("ー'")
        with self.assertRaises(VoicegerTokenConversionError):
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p)


if __name__ == "__main__":
    unittest.main()
