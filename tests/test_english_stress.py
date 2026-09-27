import unittest

from voiceger_accent_adapter.english_stress import (
    normalize_english_phonemes,
)
from voiceger_accent_adapter.voicevox_api_models import VoicegerSegment


class EnglishStressTests(unittest.TestCase):
    def test_accepts_voiceger_arpabet_stress_tokens(self):
        self.assertEqual(
            normalize_english_phonemes(
                ["r", "ih0", "k", "ao1", "r", "d"]
            ),
            ["R", "IH0", "K", "AO1", "R", "D"],
        )

    def test_primary_secondary_and_unstressed_are_distinct(self):
        self.assertEqual(
            normalize_english_phonemes(["AH0", "AH1", "AH2"]),
            ["AH0", "AH1", "AH2"],
        )

    def test_rejects_invalid_stress_number(self):
        with self.assertRaisesRegex(
            ValueError,
            "unsupported English phoneme",
        ):
            normalize_english_phonemes(["AH3"])

    def test_rejects_empty_phoneme_list(self):
        with self.assertRaisesRegex(
            ValueError,
            "must not be empty",
        ):
            normalize_english_phonemes([])

    def test_segment_omits_phonemes_when_not_present(self):
        segment = VoicegerSegment(language="ja", text="今日は")
        self.assertNotIn("phonemes", segment.model_dump())

    def test_segment_serializes_editable_english_phonemes(self):
        segment = VoicegerSegment(
            language="en",
            text="record",
            phonemes=["R", "EH1", "K", "ER0", "D"],
        )
        self.assertEqual(
            segment.model_dump()["phonemes"],
            ["R", "EH1", "K", "ER0", "D"],
        )


if __name__ == "__main__":
    unittest.main()
