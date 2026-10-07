import tempfile
import unittest
import errno
import subprocess
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from voiceger_editor.filename import build_output_filename
from voiceger_editor.output import (
    MP3_BITRATES,
    available_output_formats,
    save_output,
    save_output_audio,
    save_output_wav,
)


class OutputSaveTests(unittest.TestCase):
    timestamp = datetime(2026, 9, 27, 17, 55, 6)

    @staticmethod
    def fake_soundfile_module():
        module = ModuleType("soundfile")

        def write(path, audio, sampling_rate):
            Path(path).write_bytes(b"new wav")

        module.write = write
        return module

    def save(self, root, source_text, *, save_text=False, style_name="Neutral"):
        with patch.dict(
            "sys.modules",
            {"soundfile": self.fake_soundfile_module()},
        ):
            return save_output(
                audio=[0.0],
                sampling_rate=32000,
                source_text=source_text,
                style_name=style_name,
                output_dir=root,
                save_text=save_text,
                timestamp=self.timestamp,
            )

    def test_style_does_not_change_output_basename(self):
        source_text = "ファイル名"
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first = self.save(
                Path(first_directory),
                source_text,
                style_name="Neutral",
            )
            second = self.save(
                Path(second_directory),
                source_text,
                style_name="Sweet",
            )

        self.assertEqual(first.wav_path.name, "202609271755_ファイル名.wav")
        self.assertEqual(second.wav_path.name, first.wav_path.name)

    def test_custom_template_uses_style_and_keeps_extension_outside_template(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                "sys.modules",
                {"soundfile": self.fake_soundfile_module()},
            ):
                saved = save_output(
                    audio=[0.0],
                    sampling_rate=32000,
                    source_text="今日は雨なのだ。",
                    style_name="Neutral",
                    output_dir=root,
                    timestamp=datetime(2026, 10, 7, 19, 45, 23),
                    filename_template="{YYYY-MM-DD}_{HHmmss}_{style}_{text}",
                )

        self.assertEqual(
            saved.wav_path.name,
            "2026-10-07_194523_Neutral_今日は雨なのだ。.wav",
        )

    def test_wav_collision_adds_deterministic_suffix_without_overwriting(self):
        source_text = "今日は雨ですね。"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / build_output_filename(
                text=source_text,
                timestamp=self.timestamp,
            )
            existing.write_bytes(b"keep existing")

            saved = self.save(root, source_text)

            self.assertEqual(saved.wav_path.stem, existing.stem + "-2")
            self.assertEqual(existing.read_bytes(), b"keep existing")
            self.assertEqual(saved.wav_path.read_bytes(), b"new wav")
            self.assertIsNone(saved.text_path)

    def test_paired_output_skips_basename_if_either_target_exists(self):
        source_text = "雨です。\r\n 次です。"
        initial_wav = build_output_filename(
            text=source_text,
            timestamp=self.timestamp,
        )
        initial_stem = Path(initial_wav).stem

        for extension in (".wav", ".txt"):
            with self.subTest(existing_extension=extension):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    existing = root / f"{initial_stem}{extension}"
                    existing.write_bytes(b"keep existing")

                    saved = self.save(root, source_text, save_text=True)

                    self.assertEqual(saved.wav_path.stem, initial_stem + "-2")
                    self.assertEqual(saved.text_path.stem, saved.wav_path.stem)
                    self.assertEqual(saved.text_path.suffix, ".txt")
                    self.assertEqual(existing.read_bytes(), b"keep existing")
                    self.assertEqual(
                        saved.text_path.read_bytes(),
                        source_text.encode("utf-8"),
                    )
                    self.assertEqual(saved.wav_path.read_bytes(), b"new wav")

    def test_filename_too_long_fails_without_truncating_or_leaving_reservations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                "sys.modules",
                {"soundfile": self.fake_soundfile_module()},
            ), patch("voiceger_editor.output._reserve") as reserve:
                def reserve_then_fail(path):
                    if reserve.call_count == 1:
                        with path.open("xb"):
                            pass
                        return None
                    raise OSError(errno.ENAMETOOLONG, "filename too long", str(path))

                reserve.side_effect = reserve_then_fail
                with self.assertRaisesRegex(
                    OSError,
                    "Output filename is too long; the source text was not truncated automatically",
                ) as raised:
                    save_output(
                        audio=[0.0],
                        sampling_rate=32000,
                        source_text="a very long source text",
                        style_name="Neutral",
                        output_dir=root,
                        save_text=True,
                        timestamp=self.timestamp,
                    )

            self.assertEqual(raised.exception.errno, errno.ENAMETOOLONG)
            self.assertEqual(list(root.iterdir()), [])

    def test_disk_backed_save_copies_exact_wav_and_uses_provenance_for_name_and_txt(self):
        source_text = "生成時の source"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_wav = root / "candidate.wav"
            candidate_bytes = b"selected candidate wav bytes\x00\x01"
            candidate_wav.write_bytes(candidate_bytes)

            saved = save_output_wav(
                wav_source=candidate_wav,
                source_text=source_text,
                style_name="Sweet",
                output_dir=root / "output",
                save_text=True,
                timestamp=self.timestamp,
            )

            expected_name = build_output_filename(
                text=source_text,
                timestamp=self.timestamp,
            )
            self.assertEqual(saved.wav_path.name, expected_name)
            self.assertEqual(saved.wav_path.read_bytes(), candidate_bytes)
            self.assertEqual(saved.text_path.name, Path(expected_name).with_suffix(".txt").name)
            self.assertEqual(saved.text_path.read_text(encoding="utf-8"), source_text)

    def test_disk_backed_save_collision_reservation_and_failure_cleanup(self):
        source_text = "同じ basename"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate_wav = root / "candidate.wav"
            candidate_wav.write_bytes(b"wav")
            output_dir = root / "output"
            output_dir.mkdir()
            initial_name = build_output_filename(
                text=source_text,
                timestamp=self.timestamp,
            )
            existing = output_dir / initial_name
            existing.write_bytes(b"keep")

            with patch("voiceger_editor.output.shutil.copyfile") as copyfile:
                copyfile.side_effect = OSError("copy failed")
                with self.assertRaisesRegex(OSError, "copy failed"):
                    save_output_wav(
                        wav_source=candidate_wav,
                        source_text=source_text,
                        style_name="Neutral",
                        output_dir=output_dir,
                        save_text=True,
                        timestamp=self.timestamp,
                    )

            self.assertEqual(existing.read_bytes(), b"keep")
            self.assertEqual(list(output_dir.iterdir()), [existing])


    def test_generic_wav_source_preserves_candidate_bytes_without_reencoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.wav"
            original = b"exact candidate wav bytes\\x00\\x01"
            candidate.write_bytes(original)

            saved = save_output_audio(
                wav_source=candidate,
                source_text="source",
                style_name="Neutral",
                output_dir=root / "output",
                output_format="wav",
                output_encoding="source",
                timestamp=self.timestamp,
            )

            self.assertEqual(saved.audio_path.suffix, ".wav")
            self.assertEqual(saved.audio_path.read_bytes(), original)

    def test_explicit_wav_and_flac_encodings_write_requested_soundfile_subtypes(self):
        import soundfile as sf

        cases = (
            ("wav", "pcm16", "WAV", "PCM_16"),
            ("wav", "pcm24", "WAV", "PCM_24"),
            ("wav", "float32", "WAV", "FLOAT"),
            ("flac", "pcm16", "FLAC", "PCM_16"),
            ("flac", "pcm24", "FLAC", "PCM_24"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.wav"
            sf.write(candidate, [0.0, 0.25, -0.25], 32000, format="WAV", subtype="FLOAT")

            for output_format, encoding, expected_format, expected_subtype in cases:
                with self.subTest(output_format=output_format, encoding=encoding):
                    saved = save_output_audio(
                        wav_source=candidate,
                        source_text=f"{output_format}-{encoding}",
                        style_name="Neutral",
                        output_dir=root / "output",
                        output_format=output_format,
                        output_encoding=encoding,
                        save_text=True,
                        timestamp=self.timestamp,
                    )
                    info = sf.info(saved.audio_path)
                    self.assertEqual(info.format, expected_format)
                    self.assertEqual(info.subtype, expected_subtype)
                    self.assertEqual(saved.audio_path.suffix, f".{output_format}")
                    self.assertEqual(saved.text_path.stem, saved.audio_path.stem)


    def test_available_output_formats_only_include_mp3_when_ffmpeg_is_discoverable(self):
        with patch("voiceger_editor.output.ffmpeg_executable", return_value=None):
            self.assertEqual(available_output_formats(), ("wav", "flac"))

        with patch(
            "voiceger_editor.output.ffmpeg_executable",
            return_value="/usr/local/bin/ffmpeg",
        ):
            self.assertEqual(available_output_formats(), ("wav", "flac", "mp3"))

    def test_each_mp3_bitrate_maps_to_ffmpeg_and_preserves_candidate_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.wav"
            original = b"candidate wav bytes"
            candidate.write_bytes(original)

            def fake_run(command, **kwargs):
                Path(command[-1]).write_bytes(b"encoded mp3")
                return None

            with (
                patch(
                    "voiceger_editor.output.ffmpeg_executable",
                    return_value="/usr/local/bin/ffmpeg",
                ),
                patch(
                    "voiceger_editor.output.subprocess.run",
                    side_effect=fake_run,
                ) as run,
            ):
                for bitrate in MP3_BITRATES:
                    with self.subTest(bitrate=bitrate):
                        saved = save_output_audio(
                            wav_source=candidate,
                            source_text=f"mp3-{bitrate}",
                            style_name="Neutral",
                            output_dir=root / "output",
                            output_format="mp3",
                            output_encoding=bitrate,
                            save_text=True,
                            timestamp=self.timestamp,
                        )

                        command = run.call_args.args[0]
                        self.assertEqual(
                            command[:8],
                            [
                                "/usr/local/bin/ffmpeg",
                                "-hide_banner",
                                "-loglevel",
                                "error",
                                "-y",
                                "-i",
                                str(candidate),
                                "-b:a",
                            ],
                        )
                        self.assertEqual(command[8], bitrate)
                        self.assertEqual(command[9], str(saved.audio_path))
                        self.assertEqual(
                            run.call_args.kwargs,
                            {
                                "check": True,
                                "stdout": subprocess.DEVNULL,
                                "stderr": subprocess.PIPE,
                                "text": True,
                            },
                        )
                        self.assertEqual(saved.audio_path.suffix, ".mp3")
                        self.assertEqual(saved.audio_path.read_bytes(), b"encoded mp3")
                        self.assertEqual(saved.text_path.stem, saved.audio_path.stem)
                        self.assertEqual(saved.text_path.read_text(encoding="utf-8"), f"mp3-{bitrate}")
                        self.assertEqual(candidate.read_bytes(), original)

    def test_mp3_collision_reservation_keeps_a_free_basename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.wav"
            candidate.write_bytes(b"candidate")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"encoded")
                return None

            with (
                patch(
                    "voiceger_editor.output.ffmpeg_executable",
                    return_value="/usr/bin/ffmpeg",
                ),
                patch(
                    "voiceger_editor.output.subprocess.run",
                    side_effect=fake_run,
                ),
            ):
                first = save_output_audio(
                    wav_source=candidate,
                    source_text="same",
                    style_name="Neutral",
                    output_dir=root / "output",
                    output_format="mp3",
                    output_encoding="192k",
                    timestamp=self.timestamp,
                )
                second = save_output_audio(
                    wav_source=candidate,
                    source_text="same",
                    style_name="Neutral",
                    output_dir=root / "output",
                    output_format="mp3",
                    output_encoding="192k",
                    timestamp=self.timestamp,
                )

            self.assertEqual(first.audio_path.suffix, ".mp3")
            self.assertEqual(second.audio_path.suffix, ".mp3")
            self.assertEqual(second.audio_path.stem, first.audio_path.stem + "-2")

    def test_mp3_conversion_failure_removes_reserved_outputs_and_preserves_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.wav"
            candidate.write_bytes(b"candidate")
            output_dir = root / "output"

            failure = subprocess.CalledProcessError(
                1,
                ["ffmpeg"],
                stderr="encoder failed",
            )
            with (
                patch(
                    "voiceger_editor.output.ffmpeg_executable",
                    return_value="/usr/bin/ffmpeg",
                ),
                patch(
                    "voiceger_editor.output.subprocess.run",
                    side_effect=failure,
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "MP3 conversion failed: encoder failed",
                ):
                    save_output_audio(
                        wav_source=candidate,
                        source_text="failed",
                        style_name="Neutral",
                        output_dir=output_dir,
                        output_format="mp3",
                        output_encoding="192k",
                        save_text=True,
                        timestamp=self.timestamp,
                    )

            self.assertEqual(candidate.read_bytes(), b"candidate")
            self.assertEqual(list(output_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
