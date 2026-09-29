from __future__ import annotations

from io import BytesIO
from pathlib import Path
import struct
import unittest
import warnings
import wave
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from voiceger_accent_adapter.api import app
from voiceger_accent_adapter.styles import VoicegerStyle


def _audio_query_payload() -> dict:
    return {
        "accent_phrases": [
            {
                "moras": [
                    {
                        "text": "ア",
                        "consonant": None,
                        "consonant_length": None,
                        "vowel": "a",
                        "vowel_length": 0.1,
                        "pitch": 0.0,
                    },
                    {
                        "text": "メ",
                        "consonant": None,
                        "consonant_length": None,
                        "vowel": "e",
                        "vowel_length": 0.1,
                        "pitch": 0.0,
                    },
                ],
                "accent": 1,
                "pause_mora": None,
                "is_interrogative": False,
            }
        ],
        "speedScale": 1.0,
        "pitchScale": 0.25,
        "intonationScale": 0.75,
        "volumeScale": 1.0,
        "prePhonemeLength": 0.1,
        "postPhonemeLength": 0.1,
        "pauseLength": None,
        "pauseLengthScale": 1.0,
        "outputSamplingRate": 16000,
        "outputStereo": True,
        "kana": "アメ。",
    }


class FakeAdapter:
    def __init__(self):
        import numpy as np

        self.voiceger_root = Path("/voiceger")
        self.synthesize_audio = Mock(
            return_value={
                "audio": np.array(
                    [0, 1000, 2000, 1000, 0, -1000, -2000, -1000],
                    dtype=np.int16,
                ),
                "sampling_rate": 32000,
                "resolved_pronunciation": "ア'メ。",
            }
        )
        self.synthesize_mixed_audio = Mock()


class ApiSynthesisCompatibilityTests(unittest.TestCase):
    def test_synthesis_accepts_unsupported_controls_and_honors_wav_format(self):
        adapter = FakeAdapter()
        style = VoicegerStyle(
            id=1,
            name="Test",
            filename="reference.wav",
            prompt_text="style prompt",
        )

        with patch(
            "voiceger_accent_adapter.api.get_adapter",
            return_value=adapter,
        ), patch(
            "voiceger_accent_adapter.api._resolve_style",
            return_value=style,
        ), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with TestClient(app) as client:
                response = client.post(
                    "/synthesis?speaker=1",
                    json=_audio_query_payload(),
                )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(caught), 1)
        self.assertEqual(
            str(caught[0].message),
            "ignored unsupported VOICEVOX AudioQuery fields: "
            "pitchScale, intonationScale",
        )
        adapter.synthesize_audio.assert_called_once()
        self.assertEqual(
            adapter.synthesize_audio.call_args.kwargs["speed"],
            1.0,
        )

        with wave.open(BytesIO(response.content), "rb") as wav_file:
            self.assertEqual(wav_file.getframerate(), 16000)
            self.assertEqual(wav_file.getnchannels(), 2)
            self.assertEqual(wav_file.getsampwidth(), 2)
            raw = wav_file.readframes(wav_file.getnframes())

        samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
        self.assertGreater(len(samples), 0)
        self.assertEqual(samples[0::2], samples[1::2])


if __name__ == "__main__":
    unittest.main()
