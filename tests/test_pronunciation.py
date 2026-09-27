import unittest

from voiceger_accent_adapter.pronunciation import (
    PronunciationSyntaxError,
    format_pronunciation,
    parse_pronunciation,
)


class PronunciationParserTests(unittest.TestCase):
    def test_rain_atamadaka(self):
        value = parse_pronunciation("あ'め")
        self.assertEqual(value.phrases[0].morae, ("あ", "め"))
        self.assertEqual(value.phrases[0].nucleus, 1)
        self.assertEqual(format_pronunciation(value), "あ'め")

    def test_candy_heiban(self):
        value = parse_pronunciation("あめ")
        self.assertEqual(value.phrases[0].morae, ("あ", "め"))
        self.assertIsNone(value.phrases[0].nucleus)
        self.assertEqual(format_pronunciation(value), "あめ")

    def test_phrase_boundaries(self):
        value = parse_pronunciation("あしたの/て'んきわ/はれ。")
        self.assertEqual(len(value.phrases), 3)
        self.assertIsNone(value.phrases[0].nucleus)
        self.assertEqual(value.phrases[1].nucleus, 1)
        self.assertIsNone(value.phrases[2].nucleus)
        self.assertEqual(value.terminator, "。")
        self.assertEqual(
            format_pronunciation(value),
            "あしたの/て'んきわ/はれ。",
        )

    def test_compound_mora_marker_must_follow_complete_mora(self):
        good = parse_pronunciation("きゃ'く")
        self.assertEqual(good.phrases[0].morae, ("きゃ", "く"))
        self.assertEqual(good.phrases[0].nucleus, 1)

        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("き'ゃく")

    def test_sokuon_n_and_long_vowel_are_morae(self):
        value = parse_pronunciation("がっこ'ー")
        self.assertEqual(value.phrases[0].morae, ("が", "っ", "こ", "ー"))
        self.assertEqual(value.phrases[0].nucleus, 3)

        value = parse_pronunciation("ほん")
        self.assertEqual(value.phrases[0].morae, ("ほ", "ん"))

    def test_rejects_multiple_accent_markers(self):
        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("あ'め'")

    def test_rejects_empty_phrase(self):
        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("あめ//です")

    def test_rejects_non_kana_reading(self):
        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("雨")


if __name__ == "__main__":
    unittest.main()
