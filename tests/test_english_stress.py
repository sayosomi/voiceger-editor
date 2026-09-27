import unittest

from voiceger_accent_adapter.english_stress import (
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    normalize_english_phonemes,
)
from voiceger_accent_adapter.voicevox_api_models import VoicegerSegment


class EnglishStressTests(unittest.TestCase):
    def test_editor_state_separates_base_phonemes_and_vowel_stress(self):
        state = english_phonemes_to_editor_state(["HH", "AH0", "L", "OW1"])

        self.assertEqual(state.base_phonemes, ("HH", "AH", "L", "OW"))
        self.assertEqual(state.vowel_stresses, (0, 1))
        self.assertEqual(state.primary_stress_vowel_positions, (1,))
        self.assertEqual(state.secondary_stress_vowel_positions, ())

    def test_editor_state_round_trips_stressed_g2p_output(self):
        phonemes = ["R", "EH1", "K", "ER0", "D", ",", "HH", "AH0", "."]

        self.assertEqual(
            editor_state_to_english_phonemes(
                english_phonemes_to_editor_state(phonemes)
            ),
            phonemes,
        )

    def test_editor_state_keeps_primary_and_secondary_stress_distinct(self):
        state = english_phonemes_to_editor_state(["AH0", "AH1", "AH2"])

        self.assertEqual(state.vowel_stresses, (0, 1, 2))
        self.assertEqual(state.primary_stress_vowel_positions, (1,))
        self.assertEqual(state.secondary_stress_vowel_positions, (2,))

    def test_move_primary_stress_preserves_other_markers(self):
        state = english_phonemes_to_editor_state(
            ["AH1", "K", "EH0", "OW2", "IY1"]
        )

        moved = move_primary_stress(state, 0, 1)

        self.assertEqual(moved.vowel_stresses, (0, 1, 2, 1))
        self.assertEqual(moved.primary_stress_vowel_positions, (1, 3))
        self.assertEqual(moved.secondary_stress_vowel_positions, (2,))
        self.assertEqual(
            editor_state_to_english_phonemes(moved),
            ["AH0", "K", "EH1", "OW2", "IY1"],
        )

    def test_move_primary_stress_replaces_secondary_on_target(self):
        state = english_phonemes_to_editor_state(["AH1", "EH2"])

        moved = move_primary_stress(state, 0, 1)

        self.assertEqual(moved.vowel_stresses, (0, 1))
        self.assertEqual(
            editor_state_to_english_phonemes(moved), ["AH0", "EH1"]
        )

    def test_move_primary_stress_rejects_non_primary_source(self):
        state = english_phonemes_to_editor_state(["AH0", "EH1"])

        with self.assertRaisesRegex(ValueError, "source vowel"):
            move_primary_stress(state, 0, 1)

    def test_move_primary_stress_rejects_invalid_target(self):
        state = english_phonemes_to_editor_state(["AH1", "EH0"])

        with self.assertRaisesRegex(ValueError, "target vowel position"):
            move_primary_stress(state, 0, 2)

        with self.assertRaisesRegex(ValueError, "different vowel positions"):
            move_primary_stress(state, 0, 0)

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
