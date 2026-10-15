import unittest
from unittest.mock import patch

from voiceger_editor.mixed_language import (
    DetectedSegment,
    build_mixed_audio_query,
    build_mixed_synthesis_plan,
    detect_language_segments,
    voiceger_text_language,
)
from voiceger_editor.pronunciation import (
    AccentPhrase,
    Pronunciation,
    format_pronunciation,
    parse_pronunciation,
)
from voiceger_editor.voicevox_api_models import (
    AccentPhrase as ApiAccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


class MixedLanguageTests(unittest.TestCase):
    def test_pronunciation_terminator_validation_and_serialization(self):
        for value in (None, "", "。", "？", "！"):
            with self.subTest(value=value):
                segment = VoicegerSegment(
                    language="ja",
                    text="雨。",
                    pronunciationTerminator=value,
                )
                serialized = segment.model_dump()
                if value is None:
                    self.assertNotIn("pronunciationTerminator", serialized)
                else:
                    self.assertEqual(serialized["pronunciationTerminator"], value)

        for value in ("?", "!", ".", "invalid"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    VoicegerSegment(
                        language="ja",
                        text="雨。",
                        pronunciationTerminator=value,
                    )

    def test_deterministic_segmentation_reconstructs_human_matrix(self):
        cases = (
            ("３，２，１", (("ja", "３，２，１"),)),
            ("３，２，１！", (("ja", "３，２，１！"),)),
            ("３，２，１？", (("ja", "３，２，１？"),)),
            ("３，２，１、", (("ja", "３，２，１、"),)),
            ("３，２，１。", (("ja", "３，２，１。"),)),
            ("３、２、１！", (("ja", "３、２、１！"),)),
            ("３，２，１なのだ！", (("ja", "３，２，１なのだ！"),)),
            ("３，２，１！なのだ", (("ja", "３，２，１！なのだ"),)),
            ("三、二、一！", (("ja", "三、二、一！"),)),
            ("さん、にー、いち！", (("ja", "さん、にー、いち！"),)),
            ("１！", (("ja", "１！"),)),
            ("１２３！", (("ja", "１２３！"),)),
            ("3,2,1!", (("ja", "3,2,1!"),)),
            ("今日はOpenAIを使うのだ！", (
                ("ja", "今日は"), ("en", "OpenAI"), ("ja", "を使うのだ！"),
            )),
            ("Hello, world!", (("en", "Hello, world!"),)),
            ("Version 2なのだ", (("en", "Version 2"), ("ja", "なのだ"))),
            ("Caption 01", (("en", "Caption 01"),)),
            ("（Hello）なのだ！", (("en", "（Hello）"), ("ja", "なのだ！"))),
            ("あ  hello,  1なのだ", (
                ("ja", "あ  "), ("en", "hello,  1"), ("ja", "なのだ"),
            )),
        )
        for caption, expected in cases:
            with self.subTest(caption=caption):
                segments = detect_language_segments(caption)
                actual = tuple((item.language, item.text) for item in segments)
                self.assertEqual(actual, expected)
                self.assertEqual("".join(item.text for item in segments), caption)
                self.assertTrue(all(item.language in {"ja", "en"} for item in segments))

    def test_unsupported_scripts_and_punctuation_only_are_rejected(self):
        for caption in ("안녕", "Привет", "hello한글", "！？。", "   "):
            with self.subTest(caption=caption):
                with self.assertRaises(ValueError):
                    detect_language_segments(caption)

    def test_source_loss_or_unsupported_injected_sections_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "complete Caption"):
            build_mixed_audio_query(
                "今日はhello",
                segments=[DetectedSegment("ja", "今日は"), DetectedSegment("en", "hell")],
            )
        with self.assertRaisesRegex(ValueError, "ja/en"):
            build_mixed_audio_query(
                "三、二、一！",
                segments=[DetectedSegment("zh", "三、二、一！")],
            )

    def test_japanese_numeric_query_keeps_all_countdown_phrases(self):
        japanese = Pronunciation(
            phrases=(
                AccentPhrase(("サ", "ン"), 1),
                AccentPhrase(("ニ", "ー"), 1),
                AccentPhrase(("イ", "チ"), 1),
            ),
            terminator="！",
        )
        for caption in ("３，２，１！", "３、２、１！", "三、二、一！"):
            with self.subTest(caption=caption), patch(
                "voiceger_editor.mixed_language.text_to_pronunciation",
                return_value=japanese,
            ) as convert:
                query = build_mixed_audio_query(caption)
                convert.assert_called_once_with(caption)
                self.assertIsNone(query.voicegerSegments)
                self.assertEqual(len(query.accent_phrases), 3)

    def test_auto_mixed_query_keeps_exact_section_identity(self):
        japanese = Pronunciation(
            phrases=(AccentPhrase(("ナ", "ノ", "ダ"), 2),),
            terminator="！",
        )
        with patch(
            "voiceger_editor.mixed_language.text_to_pronunciation",
            return_value=japanese,
        ):
            query = build_mixed_audio_query(
                "Version 2なのだ！",
                english_g2p=lambda _: ["V", "ER1", "ZH", "AH0", "N"],
            )
        self.assertEqual(
            [(item.language, item.text) for item in query.voicegerSegments],
            [("en", "Version 2"), ("ja", "なのだ！")],
        )
        self.assertEqual(query.voicegerSegments[1].accentPhraseCount, 1)
        self.assertEqual(query.voicegerSegments[0].phonemes[1], "ER1")
        plan = build_mixed_synthesis_plan(query)
        self.assertEqual(plan.text, "Version 2なのだ！")
        self.assertEqual(plan.text_language, "Japanese-English Mixed")

    def test_english_only_query_and_plan_use_native_english_mode(self):
        phonemes = ["K", "AE1", "P", "SH", "AH0", "N"]
        query = build_mixed_audio_query(
            "Caption 01",
            segments=[DetectedSegment("en", "Caption 01")],
            english_g2p=lambda _text: phonemes,
        )

        self.assertEqual(query.accent_phrases, [])
        self.assertEqual(len(query.voicegerSegments), 1)
        self.assertEqual(query.voicegerSegments[0].language, "en")
        self.assertEqual(query.voicegerSegments[0].text, "Caption 01")
        self.assertEqual(query.voicegerSegments[0].phonemes, phonemes)
        self.assertEqual(
            voiceger_text_language(query.voicegerSegments),
            "English",
        )

        plan = build_mixed_synthesis_plan(query)
        self.assertEqual(plan.text, "Caption 01")
        self.assertEqual(plan.text_language, "English")
        self.assertEqual(plan.japanese_overrides, ())
        self.assertEqual(
            plan.english_overrides,
            (("Caption 01", phonemes),),
        )

    def test_english_only_query_preserves_source_when_detector_rewrites_spacing(self):
        seen = []

        def english_g2p(value):
            seen.append(value)
            return ["K", "AE1", "P", "SH", "AH0", "N"]

        query = build_mixed_audio_query(
            "Caption 01",
            segments=[
                DetectedSegment("en", "Caption  "),
                DetectedSegment("en", "01 "),
            ],
            english_g2p=english_g2p,
        )

        self.assertEqual(len(query.voicegerSegments), 1)
        self.assertEqual(query.voicegerSegments[0].language, "en")
        self.assertEqual(query.voicegerSegments[0].text, "Caption 01")
        self.assertEqual(seen, ["Caption 01"])

        plan = build_mixed_synthesis_plan(query)
        self.assertEqual(plan.text, "Caption 01")
        self.assertEqual(
            plan.english_overrides,
            (("Caption 01", ["K", "AE1", "P", "SH", "AH0", "N"]),),
        )

    def test_japanese_english_selects_native_mixed_mode(self):
        segments = [
            VoicegerSegment(language="ja", text="今日は"),
            VoicegerSegment(language="en", text="OpenAI"),
        ]
        self.assertEqual(
            voiceger_text_language(segments),
            "Japanese-English Mixed",
        )

    def test_other_language_selects_multilingual_mode(self):
        segments = [
            VoicegerSegment(language="ja", text="今日は"),
            VoicegerSegment(language="ko", text="안녕"),
        ]
        self.assertEqual(
            voiceger_text_language(segments),
            "Multilingual Mixed",
        )

    def test_mixed_query_maps_only_japanese_to_accent_phrases(self):
        japanese = Pronunciation(
            phrases=(AccentPhrase(("キョ", "ー", "ワ"), 1),),
            terminator=None,
        )
        segments = [
            DetectedSegment("ja", "今日は"),
            DetectedSegment("en", "OpenAI"),
        ]

        with patch(
            "voiceger_editor.mixed_language.text_to_pronunciation",
            return_value=japanese,
        ):
            query = build_mixed_audio_query(
                "今日はOpenAI",
                segments=segments,
                english_g2p=lambda _: [
                    "OW1",
                    "P",
                    "AH0",
                    "N",
                    "EY1",
                ],
            )

        self.assertIsNone(query.kana)
        self.assertEqual(len(query.accent_phrases), 1)
        self.assertEqual(
            query.voicegerSegments[0].accentPhraseStart,
            0,
        )
        self.assertEqual(
            query.voicegerSegments[0].accentPhraseCount,
            1,
        )
        self.assertIsNone(
            query.voicegerSegments[1].accentPhraseStart
        )
        self.assertEqual(
            query.voicegerSegments[1].phonemes,
            ["OW1", "P", "AH0", "N", "EY1"],
        )

    def test_mixed_query_keeps_dictionary_pronunciations_in_segment_order(self):
        japanese_values = iter(
            (
                Pronunciation(
                    phrases=(AccentPhrase(("ズ", "ン", "ダ", "モ", "ン"), 3),),
                    terminator=None,
                ),
                Pronunciation(
                    phrases=(AccentPhrase(("ア", "メ"), 1),),
                    terminator="。",
                ),
            )
        )
        segments = (
            DetectedSegment("ja", "ずんだもん"),
            DetectedSegment("en", "Voiceger"),
            DetectedSegment("ja", "雨。"),
        )
        with patch(
            "voiceger_editor.mixed_language.text_to_pronunciation",
            side_effect=lambda _text: next(japanese_values),
        ):
            query = build_mixed_audio_query(
                "ずんだもんVoiceger雨。",
                segments=segments,
                english_g2p=lambda _text: ["V", "OY1", "AH0", "JH", "ER0"],
            )

        self.assertEqual(
            [segment.language for segment in query.voicegerSegments],
            ["ja", "en", "ja"],
        )
        self.assertEqual(
            [segment.text for segment in query.voicegerSegments],
            ["ずんだもん", "Voiceger", "雨。"],
        )
        self.assertEqual(query.voicegerSegments[1].phonemes[1], "OY1")
        readings = [
            "".join(mora.text for mora in phrase.moras)
            for phrase in query.accent_phrases
        ]
        self.assertEqual(readings, ["ズンダモン", "アメ"])

    def test_new_mixed_japanese_segments_store_explicit_terminator_state(self):
        for terminator, expected in (
            (None, ""),
            ("。", "。"),
            ("？", "？"),
            ("！", "！"),
        ):
            with self.subTest(terminator=terminator):
                pronunciation = Pronunciation(
                    phrases=(AccentPhrase(("ア", "メ"), 1),),
                    terminator=terminator,
                )
                with patch(
                    "voiceger_editor.mixed_language.text_to_pronunciation",
                    return_value=pronunciation,
                ):
                    query = build_mixed_audio_query(
                        "雨" + (terminator or "") + "hello",
                        segments=[
                            DetectedSegment("ja", "雨" + (terminator or "")),
                            DetectedSegment("en", "hello"),
                        ],
                    )

                self.assertEqual(
                    query.voicegerSegments[0].pronunciationTerminator,
                    expected,
                )
                self.assertIsNone(
                    query.voicegerSegments[1].pronunciationTerminator
                )

    def test_mixed_japanese_punctuation_survives_query_and_plan(self):
        pronunciation = parse_pronunciation("ア'メ、アメ'…ア'メ！")
        with patch(
            "voiceger_editor.mixed_language.text_to_pronunciation",
            return_value=pronunciation,
        ):
            query = build_mixed_audio_query(
                "雨、飴…雨！hello",
                segments=[
                    DetectedSegment("ja", "雨、飴…雨！"),
                    DetectedSegment("en", "hello"),
                ],
                english_g2p=lambda _text: ["HH", "AH0", "L", "OW1"],
            )

        japanese_segment = query.voicegerSegments[0]
        self.assertEqual(
            [
                (entry.afterAccentPhrase, entry.mark)
                for entry in japanese_segment.pronunciationPunctuation
            ],
            [(0, "、"), (1, "…"), (2, "！")],
        )

        with patch(
            "voiceger_editor.mixed_language.pronunciation_to_voiceger_tokens",
            side_effect=lambda value: [format_pronunciation(value)],
        ):
            plan = build_mixed_synthesis_plan(query)

        self.assertEqual(
            plan.japanese_overrides,
            (("雨、飴…雨！", ["ア'メ、アメ'…ア'メ！"]),),
        )
        self.assertEqual(
            plan.english_overrides,
            (("hello", ["HH", "AH0", "L", "OW1"]),),
        )

    def test_mixed_plan_uses_explicit_or_legacy_terminator_resolution(self):
        phrase = ApiAccentPhrase(
            moras=[Mora(text="ア", vowel="a")],
            accent=1,
        )
        cases = (
            ("。", None, "。"),
            ("?", None, "？"),
            ("!", None, "！"),
            ("雨。", "！", "！"),
            ("雨！", "", None),
        )
        for text, explicit, expected in cases:
            with self.subTest(text=text, explicit=explicit):
                segment = VoicegerSegment(
                    language="ja",
                    text=text,
                    accentPhraseStart=0,
                    accentPhraseCount=1,
                    pronunciationTerminator=explicit,
                )
                query = AudioQuery(
                    accent_phrases=[phrase],
                    voicegerSegments=[segment],
                )
                with patch(
                    "voiceger_editor.mixed_language.pronunciation_to_voiceger_tokens",
                    side_effect=lambda value: [value.terminator],
                ):
                    plan = build_mixed_synthesis_plan(query)

                self.assertEqual(plan.japanese_overrides, ((text, [expected]),))

    def test_pure_japanese_serialization_omits_extension(self):
        japanese = Pronunciation(
            phrases=(AccentPhrase(("ア", "メ"), 1),),
            terminator="。",
        )
        with patch(
            "voiceger_editor.mixed_language.text_to_pronunciation",
            return_value=japanese,
        ):
            query = build_mixed_audio_query(
                "雨。",
                segments=[DetectedSegment("ja", "雨。")],
            )

        serialized = query.model_dump()
        self.assertNotIn("voicegerSegments", serialized)

    def test_mixed_synthesis_plan_preserves_text_and_language(self):
        japanese = Pronunciation(
            phrases=(AccentPhrase(("キョ", "ー", "ワ"), 1),),
            terminator=None,
        )
        segments = [
            DetectedSegment("ja", "今日は"),
            DetectedSegment("en", "OpenAI"),
        ]

        with patch(
            "voiceger_editor.mixed_language.text_to_pronunciation",
            return_value=japanese,
        ):
            query = build_mixed_audio_query(
                "今日はOpenAI",
                segments=segments,
                english_g2p=lambda _: [
                    "OW1",
                    "P",
                    "AH0",
                    "N",
                    "EY1",
                ],
            )

        with patch(
            "voiceger_editor.mixed_language.pronunciation_to_voiceger_tokens",
            return_value=["dummy"],
        ):
            plan = build_mixed_synthesis_plan(query)

        self.assertEqual(plan.text, "今日はOpenAI")
        self.assertEqual(plan.text_language, "Japanese-English Mixed")
        self.assertEqual(
            plan.japanese_overrides,
            (("今日は", ["dummy"]),),
        )
        self.assertEqual(
            plan.english_overrides,
            (("OpenAI", ["OW1", "P", "AH0", "N", "EY1"]),),
        )

    def test_mixed_synthesis_plan_rejects_invalid_english_stress(self):
        query = build_mixed_audio_query(
            "hello",
            segments=[DetectedSegment("en", "hello")],
            english_g2p=lambda _: ["HH", "AH0", "L", "OW1"],
        )
        query.voicegerSegments[0].phonemes = ["HH", "AH3", "L", "OW1"]

        with self.assertRaisesRegex(
            ValueError,
            "unsupported English phoneme",
        ):
            build_mixed_synthesis_plan(query)


if __name__ == "__main__":
    unittest.main()
