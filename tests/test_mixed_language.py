import unittest

from voiceger_accent_adapter.mixed_language import (
    DetectedSegment,
    detect_language_segments,
    voiceger_text_language,
)
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


if __name__ == "__main__":
    unittest.main()
