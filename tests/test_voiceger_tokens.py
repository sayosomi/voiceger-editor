import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.runtime_locks import OPENJTALK_LOCK
from voiceger_accent_adapter.voiceger_tokens import (
    VoicegerTokenConversionError,
    _default_mora_g2p,
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
    def test_default_mora_g2p_holds_openjtalk_lock(self):
        def g2p(mora, *, kana, join):
            self.assertTrue(OPENJTALK_LOCK._is_owned())
            self.assertEqual((mora, kana, join), ("あ", False, False))
            return ["a"]

        with patch.dict(sys.modules, {"pyopenjtalk": SimpleNamespace(g2p=g2p)}):
            self.assertEqual(tuple(_default_mora_g2p("あ")), ("a",))

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

    def test_phrase_boundary_emits_openjtalk_hash(self):
        value = parse_pronunciation("あめ'/あ'め。")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            ["a", "[", "m", "e", "#", "a", "]", "m", "e", "."],
        )

    def test_sentence_terminators_map_to_distinct_voiceger_tokens(self):
        cases = (
            ("", ["a", "]", "m", "e"]),
            ("。", ["a", "]", "m", "e", "."]),
            ("？", ["a", "]", "m", "e", "?"]),
            ("！", ["a", "]", "m", "e", "!"]),
        )
        for suffix, expected in cases:
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    pronunciation_to_voiceger_tokens(
                        parse_pronunciation("あ'め" + suffix),
                        mora_g2p=fake_g2p,
                    ),
                    expected,
                )

    def test_ordered_punctuation_maps_to_distinct_voiceger_tokens(self):
        value = parse_pronunciation("あ'め、あめ'…あ'め？")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            [
                "a", "]", "m", "e", ",",
                "a", "[", "m", "e", "…",
                "a", "]", "m", "e", "?",
            ],
        )

    def test_punctuation_breaks_phrase_boundary_without_hash(self):
        value = parse_pronunciation("あ'め!あめ'.")
        self.assertEqual(
            pronunciation_to_voiceger_tokens(value, mora_g2p=fake_g2p),
            [
                "a", "]", "m", "e", "!",
                "a", "[", "m", "e", ".",
            ],
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
