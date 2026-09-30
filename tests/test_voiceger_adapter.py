import inspect
import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import patch

from voiceger_accent_adapter.output import SavedOutput
from voiceger_accent_adapter.pronunciation import AccentPhrase, Pronunciation
from voiceger_accent_adapter.runtime_locks import OPENJTALK_LOCK
from voiceger_accent_adapter.voiceger_adapter import (
    VoicegerAdapter,
    VoicegerAdapterError,
    pronunciation_to_spoken_text,
    resolve_pronunciation,
)
from voiceger_accent_adapter.user_dictionary import UserDictionaryCore


class ResolvePronunciationTests(unittest.TestCase):
    def test_adapter_error_is_available_for_api_import(self):
        self.assertTrue(issubclass(VoicegerAdapterError, RuntimeError))

    def test_sampling_defaults_match_voiceger_for_adapter_entry_points(self):
        for method_name in ("synthesize_audio", "synthesize_mixed_audio", "synthesize"):
            with self.subTest(method_name=method_name):
                parameters = inspect.signature(
                    getattr(VoicegerAdapter, method_name)
                ).parameters
                self.assertEqual(parameters["top_k"].default, 20)
                self.assertEqual(parameters["top_p"].default, 1.0)
                self.assertEqual(parameters["temperature"].default, 1.0)

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

    def test_source_terminators_keep_period_question_and_exclamation_distinct(self):
        for source, expected in (
            ("雨。", "。"),
            ("雨.", "。"),
            ("雨？", "？"),
            ("雨?", "？"),
            ("雨！", "！"),
            ("雨!", "！"),
        ):
            with self.subTest(source=source):
                text, _, resolved = resolve_pronunciation(source, "ア'メ")
                self.assertEqual(text, source)
                self.assertEqual(resolved, "ア'メ" + expected)

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
                    result = adapter.synthesize(
                        text=" 雨 ",
                        style_name="Sweet",
                        save_text=True,
                    )

            save_output.assert_called_once_with(
                audio=[0.0],
                sampling_rate=32000,
                source_text=" 雨 ",
                style_name="Sweet",
                output_dir=adapter.output_dir,
                save_text=True,
                filename_text="雨",
            )
            self.assertEqual(result["file_name"], wav_path.name)
            self.assertEqual(result["file_path"], str(wav_path))
            self.assertEqual(result["text_file_path"], str(text_path))

    def test_pure_synthesis_original_japanese_g2p_holds_openjtalk_lock(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "GPT-SoVITS").mkdir()
            ref_wav = root / "ref.wav"
            ref_wav.write_bytes(b"test")
            adapter = VoicegerAdapter(voiceger_root=root)

            def original_g2p(text, with_prosody=True):
                self.assertTrue(OPENJTALK_LOCK._is_owned())
                return ["NATIVE_JA"]

            japanese = SimpleNamespace(
                g2p=original_g2p,
                text_normalize=lambda text: text,
            )

            class FakeMhaPatched:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_get_tts_wav(**kwargs):
                self.assertEqual(
                    japanese.g2p("fallback", True),
                    ["NATIVE_JA"],
                )
                yield 32000, [0]

            adapter._loaded = True
            adapter._runtime = {
                "MhaPatched": FakeMhaPatched,
                "japanese": japanese,
                "get_tts_wav": fake_get_tts_wav,
            }

            with patch(
                "voiceger_accent_adapter.voiceger_adapter.pronunciation_to_voiceger_tokens",
                return_value=["a"],
            ):
                result = adapter.synthesize_audio(
                    text="雨",
                    pronunciation="ア'メ。",
                    ref_wav_path=ref_wav,
                    prompt_text="prompt",
                )

            self.assertEqual(result["sampling_rate"], 32000)

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

            def original_japanese_g2p(text, with_prosody=True):
                self.assertTrue(OPENJTALK_LOCK._is_owned())
                return ["NATIVE_JA"]
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
                    japanese.g2p("fallback", True),
                    ["NATIVE_JA"],
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


class EnglishDictionaryAdapterTests(unittest.TestCase):
    def make_adapter(self, root: Path, data_dir: Path) -> VoicegerAdapter:
        voiceger_root = root / "voiceger"
        voiceger_root.mkdir()
        adapter = VoicegerAdapter(voiceger_root=voiceger_root)
        adapter.user_dictionary = UserDictionaryCore(
            voiceger_root,
            data_directory=data_dir,
            openjtalk_dictionary=object(),
        )
        return adapter

    def test_exact_dictionary_hit_bypasses_voiceger_for_both_apis(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = self.make_adapter(root, root / "adapter-state")
            expected = ["V", "OY1", "AH0", "JH", "ER0"]
            adapter.user_dictionary.set_english_entry("Voiceger", expected)
            with patch.object(
                adapter,
                "_require_text_paths",
                side_effect=AssertionError("Voiceger G2P should be bypassed"),
            ):
                self.assertEqual(adapter.english_phonemes("  VOICEGER  "), expected)
                self.assertEqual(
                    adapter.english_word_phoneme_groups("voiceger"),
                    (("voiceger", tuple(expected)),),
                )

    def test_dictionary_hit_applies_to_one_word_inside_larger_segment(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = self.make_adapter(root, root / "adapter-state")
            adapter.user_dictionary.set_english_entry(
                "record",
                ["R", "IH0", "K", "AO1", "R", "D"],
            )
            baseline = [
                "S", "EY1",
                "R", "EH1", "K", "ER0", "D",
                "N", "AW1",
            ]
            english = SimpleNamespace(
                text_normalize=lambda value: value,
                g2p=lambda value: list(baseline),
                word_tokenize=lambda value: ["say", "record", "now"],
                _g2p=lambda value: [
                    "S", "EY1", " ",
                    "R", "EH1", "K", "ER0", "D", " ",
                    "N", "AW1",
                ],
                replace_phs=lambda values: list(values),
            )
            text_package = ModuleType("text")
            text_package.__path__ = []
            text_package.english = english

            with patch.dict(
                sys.modules,
                {"text": text_package, "text.english": english},
            ), patch.object(adapter, "_require_text_paths"), patch.object(
                adapter, "_ensure_import_paths"
            ), patch(
                "voiceger_accent_adapter.voiceger_adapter._pushd",
                return_value=nullcontext(),
            ):
                groups = adapter.english_word_phoneme_groups("say record now")
                flattened = adapter.english_phonemes("say record now")

            self.assertEqual(
                groups,
                (
                    ("say", ("S", "EY1")),
                    ("record", ("R", "IH0", "K", "AO1", "R", "D")),
                    ("now", ("N", "AW1")),
                ),
            )
            self.assertEqual(
                flattened,
                [
                    "S", "EY1",
                    "R", "IH0", "K", "AO1", "R", "D",
                    "N", "AW1",
                ],
            )

    def test_dictionary_miss_uses_existing_voiceger_g2p_and_grouping(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = self.make_adapter(root, root / "adapter-state")
            english = SimpleNamespace(
                text_normalize=lambda value: value,
                g2p=lambda value: ["HH", "AH0"] if value == "hello" else [],
                word_tokenize=lambda value: [value],
                _g2p=lambda value: ["HH", "AH0"],
                replace_phs=lambda values: list(values),
            )
            text_package = ModuleType("text")
            text_package.__path__ = []
            text_package.english = english
            with patch.dict(
                sys.modules,
                {"text": text_package, "text.english": english},
            ), patch.object(adapter, "_require_text_paths"), patch.object(
                adapter, "_ensure_import_paths"
            ), patch(
                "voiceger_accent_adapter.voiceger_adapter._pushd",
                return_value=nullcontext(),
            ):
                self.assertEqual(adapter.english_phonemes("hello"), ["HH", "AH0"])
                self.assertEqual(
                    adapter.english_word_phoneme_groups("hello"),
                    (("hello", ("HH", "AH0")),),
                )


if __name__ == "__main__":
    unittest.main()
