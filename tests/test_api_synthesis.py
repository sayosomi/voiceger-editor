from __future__ import annotations

from io import BytesIO
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
import warnings
import wave
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from voiceger_editor import api
from voiceger_editor.api import app
from voiceger_editor.styles import VoicegerStyle
from voiceger_editor.terms_acceptance import (
    OFFICIAL_TERMS_URL,
    ACCEPTANCE_COMMAND,
    VoicegerTermsAcceptanceError,
)


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
        "pitchScale": 0.1,
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
        self.character_name = "ずんだもん"
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
    def test_speakers_exposes_voicevox_ids_for_available_references(self):
        adapter = FakeAdapter()
        with TemporaryDirectory() as directory:
            adapter.voiceger_root = Path(directory)
            references = adapter.voiceger_root / "reference"
            references.mkdir()
            for filename in (
                "01_ref_emoNormal026.wav",
                "02_ref_emoAma026.wav",
                "05_ref_emoSasa026.wav",
            ):
                (references / filename).write_bytes(b"")

            with patch(
                "voiceger_editor.api.get_adapter",
                return_value=adapter,
            ), TestClient(app) as client:
                response = client.get("/speakers")

        self.assertEqual(response.status_code, 200, response.text)
        styles = response.json()[0]["styles"]
        self.assertEqual(
            [(style["id"], style["name"]) for style in styles],
            [(3, "Neutral"), (1, "Sweet"), (22, "Whispering")],
        )

    def test_unavailable_speaker_id_fails_clearly(self):
        adapter = FakeAdapter()
        with TemporaryDirectory() as directory:
            adapter.voiceger_root = Path(directory)
            references = adapter.voiceger_root / "reference"
            references.mkdir()
            (references / "01_ref_emoNormal026.wav").write_bytes(b"")

            with patch(
                "voiceger_editor.api.get_adapter",
                return_value=adapter,
            ), TestClient(app) as client:
                response = client.post(
                    "/audio_query",
                    params={"text": "雨", "speaker": 2},
                )

        self.assertEqual(response.status_code, 422)
        self.assertIn("unsupported speaker/style id 2", response.json()["detail"])
        self.assertIn("available style ids: 3", response.json()["detail"])

    def test_synthesis_accepts_unsupported_controls_and_honors_wav_format(self):
        adapter = FakeAdapter()
        style = VoicegerStyle(
            id=3,
            name="Test",
            filename="reference.wav",
            prompt_text="style prompt",
        )

        with patch(
            "voiceger_editor.api.get_adapter",
            return_value=adapter,
        ), patch(
            "voiceger_editor.api.require_current_acceptance",
        ), patch(
            "voiceger_editor.api._resolve_style",
            return_value=style,
        ), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with TestClient(app) as client:
                response = client.post(
                    "/synthesis?speaker=3",
                    json=_audio_query_payload(),
                )

        if response.status_code != 200:
            self.fail(f"unexpected synthesis response: {response.status_code} {response.text}")
        compatibility_warnings = [
            item
            for item in caught
            if str(item.message).startswith(
                "ignored unsupported VOICEVOX AudioQuery fields:"
            )
        ]
        self.assertEqual(len(compatibility_warnings), 1)
        self.assertEqual(
            str(compatibility_warnings[0].message),
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

    def test_synthesis_without_acceptance_returns_actionable_403_before_work(self):
        adapter = FakeAdapter()
        error = VoicegerTermsAcceptanceError(
            "Terms acceptance required. "
            f"Read {OFFICIAL_TERMS_URL} and run {ACCEPTANCE_COMMAND}."
        )
        with patch(
            "voiceger_editor.api.require_current_acceptance",
            side_effect=error,
        ), patch(
            "voiceger_editor.api.get_adapter",
            return_value=adapter,
        ) as get_adapter, patch(
            "voiceger_editor.api._resolve_style",
        ) as resolve_style, patch(
            "voiceger_editor.api.synthesize_audio_query",
        ) as synthesize_audio_query, TestClient(app) as client:
            response = client.post(
                "/synthesis?speaker=3",
                json=_audio_query_payload(),
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn(OFFICIAL_TERMS_URL, response.json()["detail"])
        self.assertIn(ACCEPTANCE_COMMAND, response.json()["detail"])
        get_adapter.assert_not_called()
        resolve_style.assert_not_called()
        synthesize_audio_query.assert_not_called()
        adapter.synthesize_audio.assert_not_called()

    def test_get_adapter_requires_acceptance_before_environment_setup(self):
        error = VoicegerTermsAcceptanceError("terms acceptance required")
        with patch(
            "voiceger_editor.api.require_current_acceptance",
            side_effect=error,
        ), patch(
            "voiceger_editor.api.require_voiceger_environment",
        ) as require_environment:
            with self.assertRaises(VoicegerTermsAcceptanceError):
                api.get_adapter.__wrapped__()

        require_environment.assert_not_called()

    def test_root_and_version_remain_available_without_acceptance(self):
        error = VoicegerTermsAcceptanceError("terms acceptance required")
        with patch(
            "voiceger_editor.api.require_current_acceptance",
            side_effect=error,
        ), TestClient(app) as client:
            root_response = client.get("/")
            version_response = client.get("/version")

        self.assertEqual(root_response.status_code, 200)
        self.assertEqual(version_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
