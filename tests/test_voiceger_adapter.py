import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from voiceger_accent_adapter.output import SavedOutput
from voiceger_accent_adapter.pronunciation import AccentPhrase, Pronunciation
from voiceger_accent_adapter.voiceger_adapter import (
    VoicegerAdapter,
    VoicegerAdapterError,
    pronunciation_to_spoken_text,
    resolve_pronunciation,
)


class ResolvePronunciationTests(unittest.TestCase):
    def test_adapter_error_is_available_for_api_import(self):
        self.assertTrue(issubclass(VoicegerAdapterError, RuntimeError))

    def test_manual_pronunciation_is_canonicalized(self):
        text, parsed, resolved = resolve_pronunciation(
            "今日は雨ですね。",
            "キョ'ーワ/アメデスネ'。",
        )
        self.assertEqual(text, "今日は雨ですね。")
        self.assertEqual(resolved, "キョ'ーワ/アメデスネ'。")
        self.assertEqual(parsed.phrases[1].accent, 5)

    def test_missing_manual_terminator_uses_text_terminator(self):
        text, _, resolved = resolve_pronunciation(
            "雨？",
            "ア'メ",
        )
        self.assertEqual(text, "雨？")
        self.assertEqual(resolved, "ア'メ？")

    def test_text_without_terminator_gets_period(self):
        fake = Pronunciation(
            phrases=(AccentPhrase(("ア", "メ"), 1),),
            terminator="。",
        )
        with patch(
            "voiceger_accent_adapter.voiceger_adapter.text_to_pronunciation",
            return_value=fake,
        ):
            text, _, resolved = resolve_pronunciation("雨")

        self.assertEqual(text, "雨。")
        self.assertEqual(resolved, "ア'メ。")

    def test_pronunciation_rebuilds_spoken_text_for_synthesis(self):
        value = Pronunciation(
            phrases=(
                AccentPhrase(("キョ", "ー", "ワ"), 1),
                AccentPhrase(("ア", "メ"), 1),
            ),
            terminator="。",
        )
        self.assertEqual(
            pronunciation_to_spoken_text(value),
            "キョーワアメ。",
        )

    def test_rejects_newlines(self):
        with self.assertRaises(ValueError):
            resolve_pronunciation("一行目\n二行目")

    def test_synthesize_uses_shared_output_saver_and_can_save_text(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wav_path = root / "output" / "20260927_175506_雨.wav"
            text_path = wav_path.with_suffix(".txt")
            adapter = VoicegerAdapter(
                voiceger_root=root,
                output_dir=wav_path.parent,
            )
            audio_result = {
                "audio": [0.0],
                "sampling_rate": 32000,
                "resolved_pronunciation": "ア'メ。",
            }
            with patch.object(
                adapter,
                "synthesize_audio",
                return_value=audio_result,
            ):
                with patch(
                    "voiceger_accent_adapter.voiceger_adapter.save_output",
                    return_value=SavedOutput(wav_path, text_path),
                ) as save_output:
                    result = adapter.synthesize(text=" 雨 ", save_text=True)

            save_output.assert_called_once_with(
                audio=[0.0],
                sampling_rate=32000,
                source_text=" 雨 ",
                output_dir=adapter.output_dir,
                save_text=True,
                filename_text="雨",
            )
            self.assertEqual(result["file_name"], wav_path.name)
            self.assertEqual(result["file_path"], str(wav_path))
            self.assertEqual(result["text_file_path"], str(text_path))

    def test_mixed_synthesis_injects_and_restores_english_clean_text(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sovits_dir = root / "GPT-SoVITS"
            sovits_dir.mkdir()
            ref_wav = root / "ref.wav"
            ref_wav.write_bytes(b"test")

            adapter = __import__(
                "voiceger_accent_adapter.voiceger_adapter",
                fromlist=["VoicegerAdapter"],
            ).VoicegerAdapter(voiceger_root=root)

            original_japanese_g2p = (
                lambda text, with_prosody=True: ["NATIVE_JA"]
            )
            english = SimpleNamespace(
                text_normalize=lambda text: text,
            )
            japanese = SimpleNamespace(
                g2p=original_japanese_g2p,
                text_normalize=lambda text: text,
            )
            original_clean_text_inf = (
                lambda text, language, version: (
                    ["NATIVE_EN"],
                    None,
                    text,
                )
            )
            inference_webui = SimpleNamespace(
                clean_text_inf=original_clean_text_inf,
                cleaned_text_to_sequence=lambda phones, version: list(phones),
            )

            class FakeMhaPatched:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_get_tts_wav(**kwargs):
                self.assertEqual(
                    japanese.g2p("今日は", True),
                    ["k", "y", "o"],
                )
                self.assertEqual(
                    inference_webui.clean_text_inf(
                        "record",
                        "en",
                        "v2",
                    )[0],
                    ["R", "IH0", "K", "AO1", "R", "D"],
                )
                self.assertEqual(
                    inference_webui.clean_text_inf(
                        ".record",
                        "en",
                        "v2",
                    )[0],
                    ["R", "IH0", "K", "AO1", "R", "D"],
                )
                yield 32000, [0]

            adapter._loaded = True
            adapter._runtime = {
                "MhaPatched": FakeMhaPatched,
                "english": english,
                "japanese": japanese,
                "inference_webui": inference_webui,
                "get_tts_wav": fake_get_tts_wav,
            }

            result = adapter.synthesize_mixed_audio(
                text="今日はrecord",
                japanese_overrides=[("今日は", ["k", "y", "o"])],
                english_overrides=[
                    ("record", ["R", "IH0", "K", "AO1", "R", "D"])
                ],
                text_language="Japanese-English Mixed",
                ref_wav_path=ref_wav,
                prompt_text="prompt",
            )

            self.assertEqual(result["sampling_rate"], 32000)
            self.assertIs(
                inference_webui.clean_text_inf,
                original_clean_text_inf,
            )
            self.assertIs(japanese.g2p, original_japanese_g2p)


if __name__ == "__main__":
    unittest.main()
