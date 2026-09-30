from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import Mock, patch

from voiceger_accent_adapter.mixed_language import build_mixed_synthesis_plan
from voiceger_accent_adapter.styles import VoicegerStyle
from voiceger_accent_adapter.synthesis import synthesize_audio_query
from voiceger_accent_adapter.voicevox_api_models import (
    AccentPhrase,
    AudioQuery,
    Mora,
    VoicegerSegment,
)


def _accent_phrase(
    mora_texts: list[str],
    *,
    accent: int = 1,
    is_interrogative: bool = False,
) -> AccentPhrase:
    return AccentPhrase(
        moras=[
            Mora(text=text, vowel="a", vowel_length=0.1, pitch=0.0)
            for text in mora_texts
        ],
        accent=accent,
        is_interrogative=is_interrogative,
    )


def _query(*, kana: str | None = "編集済み。", **controls) -> AudioQuery:
    return AudioQuery(
        accent_phrases=[
            _accent_phrase(["キョ", "ー", "ワ"]),
            _accent_phrase(["ア", "メ"]),
        ],
        kana=kana,
        **controls,
    )


class FakeAdapter:
    def __init__(self, voiceger_root: Path | None = None):
        self.voiceger_root = voiceger_root or Path("/voiceger")
        self.synthesize_audio = Mock()
        self.synthesize_mixed_audio = Mock()


class SynthesisTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.style = VoicegerStyle(
            id=1,
            name="Test",
            filename="reference.wav",
            prompt_text="style prompt",
        )

    def test_unchanged_default_query_controls_are_accepted(self):
        result_mapping = {"audio": object(), "sampling_rate": 32000}
        self.adapter.synthesize_audio.return_value = result_mapping

        result = synthesize_audio_query(
            adapter=self.adapter,
            query=_query(),
            style=self.style,
        )

        self.assertIs(result, result_mapping)
        self.adapter.synthesize_audio.assert_called_once()

    def test_each_unsupported_prosody_control_is_warned_and_ignored(self):
        changes = {
            "pitchScale": 0.5,
            "intonationScale": 0.5,
            "volumeScale": 0.5,
            "prePhonemeLength": 0.2,
            "postPhonemeLength": 0.2,
            "pauseLength": 0.2,
            "pauseLengthScale": 0.5,
        }

        for field, value in changes.items():
            with self.subTest(field=field):
                result_mapping = {"audio": object(), "sampling_rate": 32000}
                adapter = FakeAdapter()
                adapter.synthesize_audio.return_value = result_mapping

                with self.assertWarnsRegex(
                    UserWarning,
                    rf"ignored unsupported VOICEVOX AudioQuery fields: {field}",
                ):
                    result = synthesize_audio_query(
                        adapter=adapter,
                        query=_query(**{field: value}),
                        style=self.style,
                    )

                self.assertIs(result, result_mapping)
                adapter.synthesize_audio.assert_called_once()
                adapter.synthesize_mixed_audio.assert_not_called()

    def test_multiple_ignored_fields_are_reported_together_in_stable_order(self):
        result_mapping = {"audio": object(), "sampling_rate": 32000}
        adapter = FakeAdapter()
        adapter.synthesize_audio.return_value = result_mapping
        query = _query(
            pitchScale=0.5,
            volumeScale=0.5,
            prePhonemeLength=0.2,
            pauseLength=0.2,
            pauseLengthScale=0.5,
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = synthesize_audio_query(
                adapter=adapter,
                query=query,
                style=self.style,
            )

        self.assertIs(result, result_mapping)
        self.assertEqual(len(caught), 1)
        self.assertEqual(
            str(caught[0].message),
            "ignored unsupported VOICEVOX AudioQuery fields: "
            "pitchScale, volumeScale, prePhonemeLength, pauseLength, "
            "pauseLengthScale",
        )

    def test_output_sampling_rate_resamples_pcm_and_updates_result_rate(self):
        import numpy as np

        source = np.arange(320, dtype=np.int16)
        self.adapter.synthesize_audio.return_value = {
            "audio": source,
            "sampling_rate": 32000,
            "resolved_pronunciation": "ア'メ。",
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = synthesize_audio_query(
                adapter=self.adapter,
                query=_query(outputSamplingRate=16000),
                style=self.style,
            )

        self.assertEqual(caught, [])
        self.assertEqual(result["sampling_rate"], 16000)
        self.assertEqual(result["audio"].dtype, source.dtype)
        self.assertEqual(result["audio"].shape, (160,))
        self.assertAlmostEqual(
            len(result["audio"]) / result["sampling_rate"],
            len(source) / 32000,
            delta=1 / result["sampling_rate"],
        )
        self.assertEqual(result["resolved_pronunciation"], "ア'メ。")

    def test_output_stereo_duplicates_mono_content(self):
        import numpy as np

        source = np.array([0, 1000, -1000, 500], dtype=np.int16)
        self.adapter.synthesize_audio.return_value = {
            "audio": source,
            "sampling_rate": 32000,
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = synthesize_audio_query(
                adapter=self.adapter,
                query=_query(outputStereo=True),
                style=self.style,
            )

        self.assertEqual(caught, [])
        self.assertEqual(result["sampling_rate"], 32000)
        self.assertEqual(result["audio"].shape, (4, 2))
        np.testing.assert_array_equal(result["audio"][:, 0], source)
        np.testing.assert_array_equal(result["audio"][:, 1], source)

    def test_pure_japanese_reconstructs_pronunciation_and_forwards_options(self):
        result_mapping = {"audio": object(), "sampling_rate": 32000}
        self.adapter.synthesize_audio.return_value = result_mapping
        query = _query(kana="編集済み。", speedScale=1.25)

        result = synthesize_audio_query(
            adapter=self.adapter,
            query=query,
            style=self.style,
            top_k=37,
            top_p=0.42,
            temperature=0.83,
        )

        self.assertIs(result, result_mapping)
        self.adapter.synthesize_audio.assert_called_once_with(
            text="キョーワアメ。",
            pronunciation="キョ'ーワ/ア'メ。",
            ref_wav_path=Path("/voiceger/reference/reference.wav"),
            prompt_text="style prompt",
            speed=1.25,
            top_k=37,
            top_p=0.42,
            temperature=0.83,
        )
        self.adapter.synthesize_mixed_audio.assert_not_called()

    def test_shared_sampling_defaults_match_voiceger(self):
        self.adapter.synthesize_audio.return_value = {
            "audio": object(),
            "sampling_rate": 32000,
        }

        synthesize_audio_query(
            adapter=self.adapter,
            query=_query(),
            style=self.style,
        )

        call = self.adapter.synthesize_audio.call_args.kwargs
        self.assertEqual(call["top_k"], 20)
        self.assertEqual(call["top_p"], 1.0)
        self.assertEqual(call["temperature"], 1.0)

    def test_pure_query_terminator_preserves_kana_and_interrogative_rules(self):
        cases = (
            ("文末。", True, "。"),
            ("文末？", False, "？"),
            ("文末！", False, "！"),
            ("文末", True, ""),
            (None, True, "？"),
            (None, False, "。"),
        )

        for kana, is_interrogative, expected in cases:
            with self.subTest(kana=kana, is_interrogative=is_interrogative):
                adapter = FakeAdapter()
                adapter.synthesize_audio.return_value = {
                    "audio": object(),
                    "sampling_rate": 32000,
                }
                query = AudioQuery(
                    accent_phrases=[
                        _accent_phrase(
                            ["ア", "メ"],
                            is_interrogative=is_interrogative,
                        )
                    ],
                    kana=kana,
                )

                synthesize_audio_query(
                    adapter=adapter,
                    query=query,
                    style=self.style,
                )

                self.assertTrue(adapter.synthesize_audio.called)
                if expected:
                    self.assertTrue(
                        adapter.synthesize_audio.call_args.kwargs[
                            "pronunciation"
                        ].endswith(expected)
                    )
                    self.assertTrue(
                        adapter.synthesize_audio.call_args.kwargs["text"].endswith(
                            expected
                        )
                    )
                else:
                    self.assertEqual(
                        adapter.synthesize_audio.call_args.kwargs[
                            "pronunciation"
                        ],
                        "ア'メ",
                    )
                    self.assertEqual(
                        adapter.synthesize_audio.call_args.kwargs["text"],
                        "アメ",
                    )

    def test_mixed_query_uses_plan_and_forwards_all_options(self):
        result_mapping = {"audio": object(), "sampling_rate": 32000}
        self.adapter.synthesize_mixed_audio.return_value = result_mapping
        query = AudioQuery(
            accent_phrases=[_accent_phrase(["キョ", "ー", "ワ"])],
            speedScale=0.87,
            voicegerSegments=[
                VoicegerSegment(
                    language="ja",
                    text="今日は",
                    accentPhraseStart=0,
                    accentPhraseCount=1,
                ),
                VoicegerSegment(
                    language="en",
                    text="hello",
                    phonemes=["HH", "AH0", "L", "OW1"],
                ),
            ],
        )

        with patch(
            "voiceger_accent_adapter.mixed_language.pronunciation_to_voiceger_tokens",
            return_value=["JA_TOKEN"],
        ):
            plan = build_mixed_synthesis_plan(query)

        with patch(
            "voiceger_accent_adapter.synthesis.build_mixed_synthesis_plan",
            return_value=plan,
        ) as plan_builder:
            result = synthesize_audio_query(
                adapter=self.adapter,
                query=query,
                style=self.style,
                top_k=41,
                top_p=0.73,
                temperature=0.28,
            )

        self.assertEqual(plan.text, "今日はhello")
        self.assertEqual(plan.text_language, "Japanese-English Mixed")
        self.assertEqual(plan.japanese_overrides, (("今日は", ["JA_TOKEN"]),))
        self.assertEqual(
            plan.english_overrides,
            (("hello", ["HH", "AH0", "L", "OW1"]),),
        )
        plan_builder.assert_called_once_with(query)
        self.assertIs(result, result_mapping)
        self.adapter.synthesize_mixed_audio.assert_called_once_with(
            text=plan.text,
            japanese_overrides=list(plan.japanese_overrides),
            text_language=plan.text_language,
            english_overrides=list(plan.english_overrides),
            ref_wav_path=Path("/voiceger/reference/reference.wav"),
            prompt_text="style prompt",
            speed=0.87,
            top_k=41,
            top_p=0.73,
            temperature=0.28,
        )
        self.adapter.synthesize_audio.assert_not_called()

    def test_shared_core_does_not_write_output_files(self):
        result_mapping = {"audio": object(), "sampling_rate": 32000}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            adapter = FakeAdapter(voiceger_root=root)
            adapter.synthesize_audio.return_value = result_mapping
            style = VoicegerStyle(
                id=1,
                name="Test",
                filename="reference.wav",
                prompt_text="style prompt",
            )

            result = synthesize_audio_query(
                adapter=adapter,
                query=_query(),
                style=style,
            )

            self.assertIs(result, result_mapping)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
