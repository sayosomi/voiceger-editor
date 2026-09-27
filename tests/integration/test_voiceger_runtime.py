import os
from pathlib import Path
import subprocess
import unittest

from voiceger_accent_adapter.compatibility import SUPPORTED_VOICEGER_REVISION
from voiceger_accent_adapter.mixed_language import build_mixed_audio_query
from voiceger_accent_adapter.pronunciation import parse_pronunciation
from voiceger_accent_adapter.styles import get_style
from voiceger_accent_adapter.synthesis import synthesize_audio_query
from voiceger_accent_adapter.voiceger_adapter import VoicegerAdapter
from voiceger_accent_adapter.voicevox_query import build_audio_query


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
        query = build_audio_query(
            pronunciation=parse_pronunciation("キョ'ーワ/アメデスネ'。"),
        )
        result = synthesize_audio_query(
            adapter=self.adapter,
            query=query,
            style=self.style,
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

        result = synthesize_audio_query(
            adapter=self.adapter,
            query=query,
            style=self.style,
        )

        self.assertEqual(result["sampling_rate"], 32000)
        duration = len(result["audio"]) / result["sampling_rate"]
        self.assertGreater(duration, 0.5)
        self.assertLess(duration, 15.0)


if __name__ == "__main__":
    unittest.main()
