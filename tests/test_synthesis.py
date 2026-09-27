from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
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

    def test_each_unsupported_control_is_rejected_with_its_field_name(self):
        changes = {
            "pitchScale": 0.5,
            "intonationScale": 0.5,
            "volumeScale": 0.5,
            "prePhonemeLength": 0.2,
            "postPhonemeLength": 0.2,
            "pauseLength": 0.2,
            "pauseLengthScale": 0.5,
            "outputSamplingRate": 44100,
            "outputStereo": True,
        }

        for field, value in changes.items():
            with self.subTest(field=field):
                query = _query(**{field: value})
                adapter = FakeAdapter()

                with self.assertRaises(ValueError) as raised:
                    synthesize_audio_query(
                        adapter=adapter,
                        query=query,
                        style=self.style,
                    )

                self.assertEqual(
                    str(raised.exception),
                    "currently unsupported AudioQuery fields were changed: "
                    + field,
                )
                adapter.synthesize_audio.assert_not_called()
                adapter.synthesize_mixed_audio.assert_not_called()

    def test_multiple_unsupported_fields_keep_existing_message_order(self):
        query = _query(
            pitchScale=0.5,
            volumeScale=0.5,
            prePhonemeLength=0.2,
            pauseLength=0.2,
            outputSamplingRate=44100,
            outputStereo=True,
        )

        with self.assertRaises(ValueError) as raised:
            synthesize_audio_query(
                adapter=FakeAdapter(),
                query=query,
                style=self.style,
            )

        self.assertEqual(
            str(raised.exception),
            "currently unsupported AudioQuery fields were changed: "
            "pitchScale, volumeScale, prePhonemeLength, pauseLength, "
            "outputSamplingRate, outputStereo",
        )

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
