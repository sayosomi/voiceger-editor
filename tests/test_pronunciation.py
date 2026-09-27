import unittest

from voiceger_accent_adapter.pronunciation import (
    PronunciationSyntaxError,
    format_pronunciation,
    parse_pronunciation,
)


class PronunciationParserTests(unittest.TestCase):
    def test_rain_accent_1(self):
        value = parse_pronunciation("あ'め")
        self.assertEqual(value.phrases[0].morae, ("あ", "め"))
        self.assertEqual(value.phrases[0].accent, 1)
        self.assertEqual(format_pronunciation(value), "あ'め")

    def test_candy_accent_2(self):
        value = parse_pronunciation("あめ'")
        self.assertEqual(value.phrases[0].morae, ("あ", "め"))
        self.assertEqual(value.phrases[0].accent, 2)
        self.assertEqual(format_pronunciation(value), "あめ'")

    def test_accepts_katakana_too(self):
        value = parse_pronunciation("アメ'")
        self.assertEqual(value.phrases[0].morae, ("ア", "メ"))
        self.assertEqual(value.phrases[0].accent, 2)

    def test_phrase_boundaries(self):
        value = parse_pronunciation("あしたの'/て'んきわ/はれ'。")
        self.assertEqual(len(value.phrases), 3)
        self.assertEqual(value.phrases[0].accent, 4)
        self.assertEqual(value.phrases[1].accent, 1)
        self.assertEqual(value.phrases[2].accent, 2)
        self.assertEqual(value.terminator, "。")
        self.assertEqual(
            format_pronunciation(value),
            "あしたの'/て'んきわ/はれ'。",
        )

    def test_terminators_round_trip(self):
        for suffix in ("", "。", "？", "！"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    format_pronunciation(parse_pronunciation("ア'メ" + suffix)),
                    "ア'メ" + suffix,
                )

    def test_sentence_terminators_are_only_supported_at_the_end(self):
        for source in ("ア。'メ", "ア'メ/？", "ア'！メ"):
            with self.subTest(source=source):
                with self.assertRaises(PronunciationSyntaxError):
                    parse_pronunciation(source)

    def test_compound_mora_marker_must_follow_complete_mora(self):
        good = parse_pronunciation("きゃ'く")
        self.assertEqual(good.phrases[0].morae, ("きゃ", "く"))
        self.assertEqual(good.phrases[0].accent, 1)

        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("き'ゃく")

    def test_sokuon_n_and_long_vowel_are_morae(self):
        value = parse_pronunciation("がっこ'ー")
        self.assertEqual(value.phrases[0].morae, ("が", "っ", "こ", "ー"))
        self.assertEqual(value.phrases[0].accent, 3)

        value = parse_pronunciation("ほん'")
        self.assertEqual(value.phrases[0].morae, ("ほ", "ん"))
        self.assertEqual(value.phrases[0].accent, 2)

    def test_rejects_missing_accent_marker(self):
        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("あめ")

        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("あ'/め")

    def test_rejects_multiple_accent_markers(self):
        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("あ'め'")

    def test_rejects_empty_phrase(self):
        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("あめ'//です'")

    def test_rejects_non_kana_reading(self):
        with self.assertRaises(PronunciationSyntaxError):
            parse_pronunciation("雨'")


if __name__ == "__main__":
    unittest.main()
