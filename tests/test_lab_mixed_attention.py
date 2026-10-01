import unittest

import numpy as np

from voiceger_accent_adapter.lab_mixed_attention import (
    MixedLabSegmentSpan,
    derive_mixed_lab_provenance,
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

    def test_rejects_non_unique_monotonic_heads(self):
        with self.assertRaisesRegex(RuntimeError, "no unique monotonic"):
            derive_mixed_lab_provenance(
                self.spans(),
                self.attention(duplicate_monotonic=True),
                raw_speech_sample_count=20000,
                raw_speech_sampling_rate=1000,
                raw_audio=self.audio(),
            )


if __name__ == "__main__":
    unittest.main()
