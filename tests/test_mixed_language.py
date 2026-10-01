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

    def test_detects_and_merges_adjacent_segments(self):
        def fake(_):
            return [
                {"lang": "ja", "text": "今日は"},
                {"lang": "en", "text": "Open"},
                {"lang": "en", "text": "AI"},
                {"lang": "ja", "text": "を使う。"},
            ]

        segments = detect_language_segments(
            "今日はOpenAIを使う。",
            get_texts=fake,
        )

        self.assertEqual(
            [(segment.language, segment.text) for segment in segments],
            [
                ("ja", "今日は"),
                ("en", "OpenAI"),
                ("ja", "を使う。"),
            ],
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
