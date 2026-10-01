import unittest
from unittest.mock import patch

import numpy as np

from voiceger_accent_adapter.pronunciation import format_pronunciation
from voiceger_accent_adapter.lab_mixed_attention import (
    MixedLabSegmentSpan,
    _select_consensus_head,
    build_mixed_lab_segment_spans,
    derive_mixed_lab_provenance,
)
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    PronunciationPunctuation,
    VoicegerSegment,
)


class MixedLabAttentionTests(unittest.TestCase):
    def spans(self):
        return (
            MixedLabSegmentSpan(0, "ja", ("a",), 0, 1),
            MixedLabSegmentSpan(1, "en", ("HH",), 1, 2),
            MixedLabSegmentSpan(2, "ja", ("i",), 2, 3),
        )

    def attention(self, *, duplicate_monotonic=False):
        attention = np.zeros((1, 2, 20, 3), dtype=np.float64)
        attention[0, 0, :2, 2] = 1.0
        attention[0, 0, 2:8, 0] = 1.0
        attention[0, 0, 8:14, 1] = 1.0
        attention[0, 0, 14:, 2] = 1.0
        if duplicate_monotonic:
            attention[0, 1] = attention[0, 0]
        else:
            attention[0, 1, :, 0] = 1.0
        return attention

    @staticmethod
    def audio():
        return np.concatenate((np.zeros(2000), np.ones(18000)))

    def test_segment_spans_preserve_japanese_punctuation_tokens(self):
        query = AudioQuery(
            accent_phrases=[
                AccentPhrase(
                    moras=[Mora(text="ア", vowel="a")],
                    accent=1,
                ),
                AccentPhrase(
                    moras=[Mora(text="メ", vowel="e")],
                    accent=1,
                ),
            ],
            voicegerSegments=[
                VoicegerSegment(
                    language="ja",
                    text="あ、め！",
                    accentPhraseStart=0,
                    accentPhraseCount=2,
                    pronunciationPunctuation=[
                        PronunciationPunctuation(
                            afterAccentPhrase=0,
                            mark="、",
                        ),
                        PronunciationPunctuation(
                            afterAccentPhrase=1,
                            mark="！",
                        ),
                    ],
                ),
                VoicegerSegment(
                    language="en",
                    text="hello",
                    phonemes=["HH", "AH0"],
                ),
            ],
        )

        with patch(
            "voiceger_accent_adapter.lab_mixed_attention.pronunciation_to_voiceger_tokens",
            side_effect=lambda value: [format_pronunciation(value)],
        ):
            spans = build_mixed_lab_segment_spans(query)

        self.assertEqual(spans[0].tokens, ("ア'、メ'！",))
        self.assertEqual(spans[1].tokens, ("HH", "AH0"))

    def test_selects_unique_monotonic_head_after_speech_onset(self):
        provenance = derive_mixed_lab_provenance(
            self.spans(),
            self.attention(),
            raw_speech_sample_count=20000,
            raw_speech_sampling_rate=1000,
            raw_audio=self.audio(),
        )

        self.assertEqual(provenance.segment_languages, ("ja", "en", "ja"))
        self.assertEqual(provenance.selected_attention_head, 0)
        self.assertEqual(len(provenance.boundary_seconds), 2)
        self.assertLess(
            provenance.boundary_seconds[0],
            provenance.boundary_seconds[1],
        )

    def test_accepts_duplicate_monotonic_heads_with_identical_boundaries(self):
        provenance = derive_mixed_lab_provenance(
            self.spans(),
            self.attention(duplicate_monotonic=True),
            raw_speech_sample_count=20000,
            raw_speech_sampling_rate=1000,
            raw_audio=self.audio(),
        )

        self.assertEqual(provenance.selected_attention_head, 0)
        self.assertEqual(len(provenance.boundary_seconds), 2)

    def test_prefers_human_validated_head_when_multiple_heads_survive(self):
        head_0 = np.asarray(
            [0] * 28 + [1] * 20 + [2] * 7,
            dtype=np.int64,
        )
        shifted_head = np.asarray(
            [0] * 25 + [1] * 20 + [2] * 10,
            dtype=np.int64,
        )
        dominance = np.stack((head_0, shifted_head), axis=0)

        selected, transitions = _select_consensus_head(
            dominance,
            {0, 1},
            segment_count=3,
            conservative_onset=0,
        )

        self.assertEqual(selected, 0)
        self.assertEqual(transitions, (28, 48))

    def test_fallback_consensus_accepts_close_heads_when_validated_head_absent(self):
        unused = np.zeros(50, dtype=np.int64)
        head_1 = np.asarray(
            [0] * 25 + [1] * 18 + [2] * 7,
            dtype=np.int64,
        )
        head_2 = np.asarray(
            [0] * 23 + [1] * 18 + [2] * 9,
            dtype=np.int64,
        )
        dominance = np.stack((unused, head_1, head_2), axis=0)

        selected, transitions = _select_consensus_head(
            dominance,
            {1, 2},
            segment_count=3,
            conservative_onset=0,
        )

        self.assertEqual(selected, 1)
        self.assertEqual(transitions, (25, 43))

    def test_consensus_rejects_heads_with_material_transition_disagreement(self):
        unused = np.zeros(50, dtype=np.int64)
        head_1 = np.asarray(
            [0] * 25 + [1] * 18 + [2] * 7,
            dtype=np.int64,
        )
        head_2 = np.asarray(
            [0] * 22 + [1] * 18 + [2] * 10,
            dtype=np.int64,
        )
        dominance = np.stack((unused, head_1, head_2), axis=0)

        with self.assertRaisesRegex(
            RuntimeError,
            "disagree on segment transition frames",
        ) as context:
            _select_consensus_head(
                dominance,
                {1, 2},
                segment_count=3,
                conservative_onset=0,
            )

        message = str(context.exception)
        self.assertIn("1:(25, 43)", message)
        self.assertIn("2:(22, 40)", message)


if __name__ == "__main__":
    unittest.main()
