import os
from pathlib import Path
import subprocess
import unittest

from voiceger_accent_adapter.compatibility import SUPPORTED_VOICEGER_REVISION
from voiceger_accent_adapter.mixed_language import (
    build_mixed_audio_query,
    build_mixed_synthesis_plan,
)
from voiceger_accent_adapter.styles import get_style
from voiceger_accent_adapter.voiceger_adapter import VoicegerAdapter


RUN_INTEGRATION = os.environ.get("VOICEGER_RUN_INTEGRATION") == "1"


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set VOICEGER_RUN_INTEGRATION=1 to run real Voiceger integration tests",
)
class VoicegerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.voiceger_root = Path(
            os.environ.get("VOICEGER_ROOT", str(Path.home() / "voiceger_v2"))
        ).expanduser().resolve()
        cls.adapter = VoicegerAdapter(voiceger_root=cls.voiceger_root)
        cls.style = get_style(cls.voiceger_root, 1)

    def test_recorded_voiceger_revision(self):
        revision = subprocess.check_output(
            [
                "git",
                "-C",
                str(self.voiceger_root),
                "rev-parse",
                "HEAD",
            ],
            text=True,
        ).strip()

        self.assertEqual(revision, SUPPORTED_VOICEGER_REVISION)

    def test_manual_japanese_accent_synthesizes_without_runaway(self):
        result = self.adapter.synthesize_audio(
            text="今日は雨ですね。",
            pronunciation="キョ'ーワ/アメデスネ'。",
            ref_wav_path=self.style.reference_path(self.voiceger_root),
            prompt_text=self.style.prompt_text,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.5)
        self.assertLess(duration, 10.0)
        self.assertEqual(
            result["resolved_pronunciation"],
            "キョ'ーワ/アメデスネ'。",
        )

    def test_japanese_english_mixed_synthesizes_without_runaway(self):
        query = build_mixed_audio_query(
            "今日はhelloと言うよ。",
            english_g2p=self.adapter.english_phonemes,
        )
        self.assertIsNotNone(query.voicegerSegments)

        english_segment = next(
            segment
            for segment in query.voicegerSegments
            if segment.language == "en"
        )
        self.assertTrue(english_segment.phonemes)

        for index, token in enumerate(english_segment.phonemes):
            if token[-1:] in {"0", "1", "2"}:
                english_segment.phonemes[index] = (
                    token[:-1] + ("2" if token[-1] != "2" else "1")
                )
                break
        else:
            self.fail("English G2P returned no stress-bearing vowel")

        plan = build_mixed_synthesis_plan(query)
        self.assertEqual(plan.text_language, "Japanese-English Mixed")

        result = self.adapter.synthesize_mixed_audio(
            text=plan.text,
            japanese_overrides=list(plan.japanese_overrides),
            text_language=plan.text_language,
            english_overrides=list(plan.english_overrides),
            ref_wav_path=self.style.reference_path(self.voiceger_root),
            prompt_text=self.style.prompt_text,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.5)
        self.assertLess(duration, 15.0)


if __name__ == "__main__":
    unittest.main()
