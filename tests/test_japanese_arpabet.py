"""Focused regression contract for the front-end-neutral JA→ARPAbet converter."""

import unittest

from voiceger_editor.japanese_arpabet import (
    flatten_arpabet_groups,
    pronunciation_to_arpabet_groups,
)
from voiceger_editor.pronunciation import parse_pronunciation


def convert(source):
    return pronunciation_to_arpabet_groups(parse_pronunciation(source))


class JapaneseArpabetTests(unittest.TestCase):
    def test_three_phrase_sentence_preserves_each_boundary_and_stress(self):
        groups = convert("ズ'ンダモンハ/カシコ'イ/ノダ'！")
        self.assertEqual(
            [(group.label, group.phonemes) for group in groups],
            [
                ("ズンダモンハ", (
                    "Z", "UW1", "N", "D", "AA0", "M", "OW0", "N",
                    "HH", "AA0",
                )),
                ("カシコイ", ("K", "AA0", "SH", "IY0", "K", "OW1", "IY0")),
                ("ノダ", ("N", "OW0", "D", "AA1")),
                ("！", ("!",)),
            ],
        )
        self.assertEqual(len(flatten_arpabet_groups(groups)), 22)

    def test_hiragana_digraph_and_long_vowel(self):
        groups = convert("きゃ'く/がっこ'ー。")
        self.assertEqual(
            groups[0].phonemes, ("K", "Y", "AA1", "K", "UW0")
        )
        self.assertEqual(
            groups[1].phonemes,
            ("G", "AA0", "K", "K", "OW1", "OW0"),
        )
        self.assertEqual(groups[2].phonemes, (".",))

    def test_nasal_accent_uses_preceding_vowel(self):
        groups = convert("ホン'")
        self.assertEqual(groups[0].phonemes, ("HH", "OW1", "N"))

    def test_punctuation_in_middle_keeps_order(self):
        groups = convert("エ'？ソ'ウ！デ'モ、")
        self.assertEqual(
            [(group.label, group.phonemes[-1]) for group in groups],
            [
                ("エ", "EH1"), ("？", "?"),
                ("ソウ", "UW0"), ("！", "!"),
                ("デモ", "OW0"), ("、", ","),
            ],
        )

    def test_foreign_mora_and_yoon(self):
        groups = convert("シャ'/ティ'/ファ'/ヴォ'")
        self.assertEqual(
            tuple(group.phonemes for group in groups),
            (
                ("SH", "AA1"),
                ("T", "IY1"),
                ("F", "AA1"),
                ("V", "OW1"),
            ),
        )

    def test_explicit_pitch_events_are_rejected_not_flattened(self):
        source = "ア[メ]ノダ"
        # Existing syntax requires a valid explicit multi-peak marker pattern.
        from voiceger_editor.pronunciation import AccentPhrase, PitchEvent, Pronunciation
        phrase = AccentPhrase(
            ("ア", "メ", "ノ", "ダ"), 2,
            (PitchEvent(1, "["), PitchEvent(2, "]"), PitchEvent(3, "[")),
        )
        with self.assertRaisesRegex(ValueError, "multi-peak"):
            pronunciation_to_arpabet_groups(Pronunciation(phrases=(phrase,)))

    def test_consecutive_punctuation_rejected_before_mutation(self):
        with self.assertRaisesRegex(ValueError, "consecutive punctuation"):
            convert("エ'？！")

    def test_unsupported_mora_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, "ヷ"):
            convert("ヷ'")

    def test_sokuon_cannot_end_phrase(self):
        with self.assertRaisesRegex(ValueError, "end a phrase"):
            convert("アッ'")

    def test_no_stress_vowel_does_not_invent_one(self):
        with self.assertRaisesRegex(ValueError, "no preceding vowel"):
            convert("ン'")

    def test_flatten_groups_never_silently_strips_tokens(self):
        groups = convert("ア'、イ'！")
        self.assertEqual(flatten_arpabet_groups(groups), (
            "AA1", ",", "IY1", "!",
        ))


if __name__ == "__main__":
    unittest.main()
