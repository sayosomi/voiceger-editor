import unittest

from voiceger_editor.pronunciation import (
    PronunciationPunctuation,
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

    def test_supported_punctuation_round_trips_at_any_position(self):
        source = "ソ'ウ？ソ'ウナノダ！デ'モ、ホント'ウ…"
        value = parse_pronunciation(source)

        self.assertEqual(format_pronunciation(value), source)
        self.assertEqual(
            [
                item.mark
                for item in value.items
                if isinstance(item, PronunciationPunctuation)
            ],
            ["？", "！", "、", "…"],
        )
        self.assertIsNone(value.terminator)
        self.assertEqual(value.trailing_punctuation, "…")

    def test_ascii_and_comma_like_aliases_are_canonicalized(self):
        cases = (
            ("ア'メ.", "ア'メ。"),
            ("ア'メ,", "ア'メ、"),
            ("ア'メ?", "ア'メ？"),
            ("ア'メ!", "ア'メ！"),
            ("ア'メ，", "ア'メ、"),
            ("ア'メ：", "ア'メ、"),
            ("ア'メ；", "ア'メ、"),
            ("ア'メ·", "ア'メ、"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(
                    format_pronunciation(parse_pronunciation(source)),
                    expected,
                )

    def test_terminator_compatibility_view(self):
        for suffix in ("", "。", "？", "！", "、", "…"):
            with self.subTest(suffix=suffix):
                value = parse_pronunciation("ア'メ" + suffix)
                expected = suffix if suffix in {"。", "？", "！"} else None
                self.assertEqual(value.terminator, expected)

    def test_multiple_punctuation_tokens_preserve_order(self):
        value = parse_pronunciation("エ'？ソ'ウ！…ホント'ウナノダ、")
        self.assertEqual(
            format_pronunciation(value),
            "エ'？ソ'ウ！…ホント'ウナノダ、",
        )

    def test_punctuation_cannot_start_pronunciation_or_follow_slash(self):
        for source in ("？ア'メ", "ア'メ/？", "ア'メ/"):
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
