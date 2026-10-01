from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from voiceger_editor.lab import (
    LabSidecarResult,
    normalize_and_validate_lab,
    query_lab_language,
    save_lab_sidecar,
)
from voiceger_editor.lab_julius import (
    JuliusAlignment,
    julius_strip_time_map,
    render_julius_lab,
    to_julius_phoneme,
    to_lab_phoneme,
)
from voiceger_editor.lab_pocketsphinx import (
    TimedAlignment,
    english_query_phonemes,
    render_pocketsphinx_lab,
    to_pocketsphinx_phonemes,
)
from voiceger_editor.output import SavedOutput, _reserve_output_paths
from voiceger_editor.takes import TakeBatch, TakeCandidate
from voiceger_editor.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


def japanese_query() -> AudioQuery:
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[
                    Mora(text="ず", consonant="z", vowel="U"),
                    Mora(text="ん", vowel="N"),
                    Mora(text="っ", vowel="cl"),
                ],
                accent=1,
            )
        ]
    )


def english_query() -> AudioQuery:
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(
                language="en",
                text="hello.",
                phonemes=["HH", "AH0", "L", "OW1", "."],
            )
        ],
    )


class LabCoreTests(unittest.TestCase):
    def test_language_dispatch_distinguishes_pure_and_mixed_queries(self):
        self.assertEqual(query_lab_language(japanese_query()), "ja")
        self.assertEqual(query_lab_language(english_query()), "en")
        self.assertEqual(
            query_lab_language(
                AudioQuery(
                    accent_phrases=[],
                    voicegerSegments=[
                        VoicegerSegment(language="ja", text="雨"),
                        VoicegerSegment(language="en", text="rain", phonemes=["R", "EY1", "N"]),
                    ],
                )
            ),
            "mixed",
        )

    def test_normalize_merges_adjacent_pause_rows_and_requires_full_coverage(self):
        self.assertEqual(
            normalize_and_validate_lab(
                "0 100 pau\n100 200 pau\n200 10000000 a\n",
                wav_duration_seconds=1.0,
            ),
            "0 200 pau\n200 10000000 a\n",
        )
        with self.assertRaisesRegex(RuntimeError, "gap or overlap"):
            normalize_and_validate_lab(
                "0 100 pau\n101 10000000 a\n",
                wav_duration_seconds=1.0,
            )
        with self.assertRaisesRegex(RuntimeError, "cover"):
            normalize_and_validate_lab(
                "0 9999999 a\n",
                wav_duration_seconds=1.0,
            )

    def test_mixed_language_missing_provenance_is_nonfatal(self):
        query = AudioQuery(
            accent_phrases=[],
            voicegerSegments=[
                VoicegerSegment(language="ja", text="雨"),
                VoicegerSegment(
                    language="en",
                    text="rain",
                    phonemes=["R", "EY1", "N"],
                ),
            ],
        )
        aligner = Mock()
        result = save_lab_sidecar(
            wav_path=Path("/not/read.wav"),
            query=query,
            mixed_aligner=aligner,
            mixed_provenance_warning="capture unavailable",
        )
        self.assertIsNone(result.path)
        self.assertIn("timing provenance", result.warning)
        self.assertIn("capture unavailable", result.warning)
        aligner.assert_not_called()

    def test_existing_lab_is_not_deleted_when_publication_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            wav_path = Path(directory) / "accepted.wav"
            lab_path = Path(directory) / "accepted.lab"
            wav_path.write_bytes(b"wav")
            lab_path.write_text("existing\n", encoding="utf-8")
            fake_soundfile = SimpleNamespace(
                info=lambda _path: SimpleNamespace(duration=1.0)
            )
            with patch.dict("sys.modules", {"soundfile": fake_soundfile}):
                result = save_lab_sidecar(
                    wav_path=wav_path,
                    query=english_query(),
                    english_aligner=lambda _wav, _query: "0 10000000 HH\n",
                )
            self.assertIsNone(result.path)
            self.assertIn("already exists", result.warning)
            self.assertEqual(lab_path.read_text(encoding="utf-8"), "existing\n")

    def test_lab_collision_uses_next_output_basename_without_reserving_partial_lab(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            (output_dir / "sample.lab").write_text("old", encoding="utf-8")
            wav_path, text_path, reserved = _reserve_output_paths(
                output_dir=output_dir,
                initial_name="sample.wav",
                save_text=True,
                avoid_lab_collision=True,
            )
            try:
                self.assertEqual(wav_path.name, "sample-2.wav")
                self.assertEqual(text_path.name, "sample-2.txt")
                self.assertFalse((output_dir / "sample-2.lab").exists())
            finally:
                for path in reserved:
                    path.unlink(missing_ok=True)


class JapaneseLabTests(unittest.TestCase):
    def test_mapping_matches_production_contract(self):
        self.assertEqual(to_julius_phoneme("cl"), "q")
        self.assertEqual(to_julius_phoneme("pau"), "sp")
        self.assertEqual(to_julius_phoneme("U"), "u")
        self.assertEqual(to_lab_phoneme("q"), "cl")
        self.assertEqual(to_lab_phoneme("silB"), "pau")
        self.assertEqual(to_lab_phoneme("N"), "N")

    def test_query_uses_exact_mora_phonemes(self):
        from voiceger_editor.lab_julius import japanese_query_phonemes

        self.assertEqual(
            japanese_query_phonemes(japanese_query()),
            ["z", "U", "N", "cl"],
        )

    def test_strip_time_map_restores_removed_zero_runs(self):
        samples = [0] * 20 + [100] * 100 + [0] * 20
        time_map = julius_strip_time_map(samples, 1000)
        self.assertEqual(time_map.to_original_seconds(0.05), 0.07)
        self.assertEqual(time_map.to_original_seconds(0.10), 0.14)

    def test_render_requires_exact_sequence_and_full_trailing_pause(self):
        time_map = julius_strip_time_map([100] * 200, 1000)
        rendered = render_julius_lab(
            [
                JuliusAlignment(0, 1, "silB"),
                JuliusAlignment(2, 3, "a"),
                JuliusAlignment(4, 5, "silE"),
            ],
            ["pau", "a", "pau"],
            time_map=time_map,
            wav_duration_seconds=0.2,
        )
        self.assertTrue(rendered.startswith("0 "))
        self.assertTrue(rendered.endswith(" 2000000 pau\n"))
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            render_julius_lab(
                [JuliusAlignment(0, 1, "silB")],
                ["pau", "a", "pau"],
                time_map=time_map,
                wav_duration_seconds=0.2,
            )


class EnglishLabTests(unittest.TestCase):
    def test_exact_query_tokens_are_preserved_until_acoustic_boundary(self):
        self.assertEqual(
            english_query_phonemes(english_query()),
            ["HH", "AH0", "L", "OW1", "."],
        )
        self.assertEqual(
            to_pocketsphinx_phonemes(
                ["HH", "AH0", "L", "OW1", ",", "ER", "IH", "."]
            ),
            ["HH", "AH", "L", "OW", "ER", "IH"],
        )
        with self.assertRaisesRegex(ValueError, "UNK"):
            to_pocketsphinx_phonemes(["HH", "UNK"])

    def test_render_rejects_internal_gap_overlap_and_sequence_mismatch(self):
        with self.assertRaisesRegex(RuntimeError, "internal gap"):
            render_pocketsphinx_lab(
                [
                    TimedAlignment(0.0, 0.10, "HH"),
                    TimedAlignment(0.20, 0.30, "AH"),
                ],
                ["HH", "AH"],
                wav_duration_seconds=0.30,
            )
        with self.assertRaisesRegex(RuntimeError, "overlapping"):
            render_pocketsphinx_lab(
                [
                    TimedAlignment(0.0, 0.20, "HH"),
                    TimedAlignment(0.10, 0.30, "AH"),
                ],
                ["HH", "AH"],
                wav_duration_seconds=0.30,
            )
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            render_pocketsphinx_lab(
                [TimedAlignment(0.0, 0.30, "EH")],
                ["AH"],
                wav_duration_seconds=0.30,
            )

    def test_render_maps_silence_to_pau_and_covers_full_wav(self):
        rendered = render_pocketsphinx_lab(
            [
                TimedAlignment(0.0, 0.05, "SIL"),
                TimedAlignment(0.05, 0.10, "HH"),
                TimedAlignment(0.10, 0.20, "AH"),
                TimedAlignment(0.20, 0.30, "SIL"),
            ],
            ["HH", "AH"],
            wav_duration_seconds=0.30,
        )
        self.assertEqual(
            rendered,
            "0 500000 pau\n"
            "500000 1000000 HH\n"
            "1000000 2000000 AH\n"
            "2000000 3000000 pau\n",
        )


class AcceptedTakeLabTests(unittest.TestCase):
    def test_lab_runs_only_when_take_is_accepted_and_uses_candidate_snapshot(self):
        query = english_query()
        batch = TakeBatch(
            take_count=1,
            synthesize_one=lambda: {"audio": object(), "sampling_rate": 32000},
            style_name="Neutral",
            source_text="hello.",
            query=query,
        )
        candidate_path = batch._temporary_path / "take.wav"
        candidate_path.write_bytes(b"candidate")
        provenance = object()
        candidate = TakeCandidate(
            number=1,
            wav_path=candidate_path,
            sampling_rate=32000,
            frame_count=1,
            source_text="hello.",
            style_name="Neutral",
            query=query.model_copy(deep=True),
            mixed_lab_provenance=provenance,
            mixed_lab_provenance_warning=None,
        )
        batch._candidates[1] = candidate

        saved = SavedOutput(
            wav_path=Path("/output/accepted.wav"),
            text_path=Path("/output/accepted.txt"),
        )
        lab_result = LabSidecarResult(path=Path("/output/accepted.lab"))
        with patch(
            "voiceger_editor.takes.save_output_wav",
            return_value=saved,
        ) as save_wav, patch(
            "voiceger_editor.takes.save_lab_sidecar",
            return_value=lab_result,
        ) as save_lab:
            self.assertEqual(save_lab.call_count, 0)
            result = batch.accept(
                1,
                output_dir=Path("/output"),
                save_text=True,
                save_lab=True,
            )

        save_wav.assert_called_once_with(
            wav_source=candidate_path,
            source_text="hello.",
            style_name="Neutral",
            output_dir=Path("/output"),
            save_text=True,
            avoid_lab_collision=True,
        )
        self.assertEqual(save_lab.call_count, 1)
        self.assertEqual(save_lab.call_args.kwargs["wav_path"], saved.wav_path)
        self.assertEqual(
            save_lab.call_args.kwargs["query"].model_dump(),
            query.model_dump(),
        )
        self.assertIs(
            save_lab.call_args.kwargs["mixed_provenance"],
            provenance,
        )
        self.assertIsNone(
            save_lab.call_args.kwargs["mixed_provenance_warning"]
        )
        self.assertEqual(result.lab_path, Path("/output/accepted.lab"))

    def test_lab_failure_is_nonfatal_after_wav_save(self):
        query = english_query()
        batch = TakeBatch(
            take_count=1,
            synthesize_one=lambda: {"audio": object(), "sampling_rate": 32000},
            style_name="Neutral",
            source_text="hello.",
            query=query,
        )
        candidate_path = batch._temporary_path / "take.wav"
        candidate_path.write_bytes(b"candidate")
        batch._candidates[1] = TakeCandidate(
            number=1,
            wav_path=candidate_path,
            sampling_rate=32000,
            frame_count=1,
            source_text="hello.",
            style_name="Neutral",
            query=query,
        )
        saved = SavedOutput(
            wav_path=Path("/output/accepted.wav"),
            text_path=None,
        )
        with patch(
            "voiceger_editor.takes.save_output_wav",
            return_value=saved,
        ), patch(
            "voiceger_editor.takes.save_lab_sidecar",
            return_value=LabSidecarResult(
                warning="LAB generation failed: dependency missing"
            ),
        ):
            result = batch.accept(
                1,
                output_dir=Path("/output"),
                save_text=False,
                save_lab=True,
            )
        self.assertEqual(result.wav_path, saved.wav_path)
        self.assertIsNone(result.lab_path)
        self.assertIn("dependency missing", result.lab_warning)


if __name__ == "__main__":
    unittest.main()
