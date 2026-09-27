import unittest
from unittest.mock import patch

from voiceger_accent_adapter.mixed_language import (
    DetectedSegment,
    build_mixed_audio_query,
    build_mixed_synthesis_plan,
    detect_language_segments,
    voiceger_text_language,
)
from voiceger_accent_adapter.pronunciation import AccentPhrase, Pronunciation
from voiceger_accent_adapter.voicevox_api_models import VoicegerSegment


class MixedLanguageTests(unittest.TestCase):
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
            "voiceger_accent_adapter.mixed_language.text_to_pronunciation",
            return_value=japanese,
        ):
            query = build_mixed_audio_query(
                "今日はOpenAI",
                segments=segments,
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

    def test_pure_japanese_serialization_omits_extension(self):
        japanese = Pronunciation(
            phrases=(AccentPhrase(("ア", "メ"), 1),),
            terminator="。",
        )
        with patch(
            "voiceger_accent_adapter.mixed_language.text_to_pronunciation",
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
            "voiceger_accent_adapter.mixed_language.text_to_pronunciation",
            return_value=japanese,
        ):
            query = build_mixed_audio_query(
                "今日はOpenAI",
                segments=segments,
            )

        with patch(
            "voiceger_accent_adapter.mixed_language.pronunciation_to_voiceger_tokens",
            return_value=["dummy"],
        ):
            plan = build_mixed_synthesis_plan(query)

        self.assertEqual(plan.text, "今日はOpenAI")
        self.assertEqual(plan.text_language, "Japanese-English Mixed")
        self.assertEqual(
            plan.japanese_overrides,
            (("今日は", ["dummy"]),),
        )


if __name__ == "__main__":
    unittest.main()
