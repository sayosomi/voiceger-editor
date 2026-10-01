from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from voiceger_accent_adapter.lab_mixed import (
    align_mixed_lab,
    segment_alignment_query,
    stitch_mixed_lab_regions,
    trim_synthetic_padding_lab,
)
from voiceger_accent_adapter.lab_mixed_attention import MixedLabProvenance
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    PronunciationPunctuation,
    VoicegerSegment,
)


def mixed_query():
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text="こ", consonant="k", vowel="o")],
                accent=1,
            ),
            AccentPhrase(
                moras=[Mora(text="だ", consonant="d", vowel="a")],
                accent=1,
            ),
        ],
        voicegerSegments=[
            VoicegerSegment(
                language="ja",
                text="こ",
                accentPhraseStart=0,
                accentPhraseCount=1,
                pronunciationTerminator="",
            ),
            VoicegerSegment(
                language="en",
                text="hello",
                phonemes=["HH", "AH0", "L", "OW1"],
            ),
            VoicegerSegment(
                language="ja",
                text="だ。",
                accentPhraseStart=1,
                accentPhraseCount=1,
                pronunciationTerminator="。",
                pronunciationPunctuation=[
                    PronunciationPunctuation(
                        afterAccentPhrase=0,
                        mark="。",
                    )
                ],
            ),
        ],
    )


class MixedLabTests(unittest.TestCase):
    def test_extracts_exact_segment_queries(self):
        query = mixed_query()
        japanese = segment_alignment_query(query, segment_index=2)
        english = segment_alignment_query(query, segment_index=1)

        self.assertIsNone(japanese.voicegerSegments)
        self.assertEqual(len(japanese.accent_phrases), 1)
        self.assertEqual(
            [
                (entry.afterAccentPhrase, entry.mark)
                for entry in japanese.pronunciationPunctuation
            ],
            [(0, "。")],
        )
        self.assertEqual(english.accent_phrases, [])
        self.assertIsNone(english.pronunciationPunctuation)
        self.assertEqual(
            english.voicegerSegments[0].phonemes,
            ["HH", "AH0", "L", "OW1"],
        )

    def test_trims_only_synthetic_pause_padding(self):
        rendered = trim_synthetic_padding_lab(
            "0 2000000 pau\n"
            "2000000 5000000 HH\n"
            "5000000 7000000 pau\n",
            padding_seconds=0.2,
            core_duration_seconds=0.3,
        )
        self.assertEqual(rendered, "0 3000000 HH\n")

    def test_stitch_uses_exact_sample_boundaries(self):
        rendered = stitch_mixed_lab_regions(
            (
                "0 3000000 a\n",
                "0 3000000 HH\n",
                "0 4000000 a\n",
            ),
            sample_edges=(0, 300, 600, 1000),
            sample_rate=1000,
        )
        self.assertEqual(
            rendered,
            "0 3000000 a\n"
            "3000000 6000000 HH\n"
            "6000000 10000000 a\n",
        )

    def test_stitch_extends_boundary_pauses_to_exact_crop_edges(self):
        rendered = stitch_mixed_lab_regions(
            (
                "100000 500000 pau\n"
                "500000 3000000 HH\n",
                "0 2500000 a\n"
                "2500000 2900000 pau\n",
            ),
            sample_edges=(0, 300, 600),
            sample_rate=1000,
        )

        self.assertEqual(
            rendered,
            "0 500000 pau\n"
            "500000 3000000 HH\n"
            "3000000 5500000 a\n"
            "5500000 6000000 pau\n",
        )

    def test_stitch_rejects_uncovered_non_pause_crop_edge(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "uncovered leading crop edge before non-pause",
        ):
            stitch_mixed_lab_regions(
                ("100000 3000000 HH\n",),
                sample_edges=(0, 300),
                sample_rate=1000,
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "uncovered trailing crop edge after non-pause",
        ):
            stitch_mixed_lab_regions(
                ("0 2900000 HH\n",),
                sample_edges=(0, 300),
                sample_rate=1000,
            )

    def test_stitch_rejects_local_lab_outside_crop(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "extends outside its audio crop",
        ):
            stitch_mixed_lab_regions(
                ("0 3100000 pau\n",),
                sample_edges=(0, 300),
                sample_rate=1000,
            )

    def test_short_english_direct_failure_uses_padding_fallback(self):
        query = mixed_query()
        provenance = MixedLabProvenance(
            segment_languages=("ja", "en", "ja"),
            boundary_seconds=(0.3, 0.6),
            selected_attention_head=0,
        )
        english_calls = []

        def japanese_aligner(path, _query):
            duration = sf.info(path).duration
            return f"0 {round(duration * 10000000)} a\n"

        def english_aligner(path, _query):
            duration = sf.info(path).duration
            english_calls.append(duration)
            if len(english_calls) == 1:
                raise RuntimeError("no hypothesis")
            self.assertAlmostEqual(duration, 0.7, places=3)
            return (
                "0 2000000 pau\n"
                "2000000 5000000 HH\n"
                "5000000 7000000 pau\n"
            )

        with tempfile.TemporaryDirectory() as directory:
            wav_path = Path(directory) / "accepted.wav"
            sf.write(
                wav_path,
                np.zeros(1000, dtype=np.float32),
                1000,
                subtype="PCM_16",
            )
            rendered = align_mixed_lab(
                wav_path,
                query,
                provenance,
                japanese_aligner=japanese_aligner,
                english_aligner=english_aligner,
            )

        self.assertEqual(len(english_calls), 2)
        self.assertEqual(
            rendered,
            "0 3000000 a\n"
            "3000000 6000000 HH\n"
            "6000000 10000000 a\n",
        )


if __name__ == "__main__":
    unittest.main()
