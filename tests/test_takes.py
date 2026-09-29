import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import patch

from voiceger_accent_adapter.output import SavedOutput
from voiceger_accent_adapter.takes import TakeBatch, TakeCandidate


class TakeBatchTests(unittest.TestCase):
    @staticmethod
    def fake_soundfile_module(write_error=None):
        module = ModuleType("soundfile")

        def write(path, audio, sampling_rate):
            if write_error is not None:
                raise write_error
            Path(path).write_bytes(f"{id(audio)}:{sampling_rate}".encode())

        def info(path):
            return SimpleNamespace(frames=1234)

        module.write = write
        module.info = info
        return module

    @staticmethod
    def make_batch(root, *, take_count=3, synthesize_one=None, **options):
        if synthesize_one is None:
            synthesize_one = lambda: {"audio": object(), "sampling_rate": 32000}
        return TakeBatch(
            take_count=take_count,
            synthesize_one=synthesize_one,
            style_name=options.pop("style_name", "Neutral"),
            source_text=options.pop("source_text", "generated source"),
        )

    def test_take_count_accepts_bounds_and_rejects_invalid_values(self):
        with tempfile.TemporaryDirectory() as directory:
            for count in (1, 100):
                batch = self.make_batch(directory, take_count=count)
                batch.close()

            for count in (0, 101, True, False):
                with self.subTest(take_count=count):
                    with self.assertRaises(ValueError):
                        self.make_batch(directory, take_count=count)

    def test_initial_generation_is_sequential_progressive_and_temporary(self):
        calls = []
        audios = [object(), object(), object()]

        def synthesize_one():
            calls.append(len(calls) + 1)
            return {"audio": audios[len(calls) - 1], "sampling_rate": 24000}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory, synthesize_one=synthesize_one)
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                iterator = batch.generate_all()
                first = next(iterator)
                self.assertEqual(calls, [1])
                self.assertEqual(batch.candidates, (first,))
                self.assertEqual(first.number, 1)
                self.assertTrue(first.wav_path.is_file())
                self.assertNotIn(Path(directory) / "final-output", first.wav_path.parents)

                second = next(iterator)
                self.assertEqual(calls, [1, 2])
                self.assertEqual(batch.candidates, (first, second))
                third = next(iterator)
                self.assertEqual(calls, [1, 2, 3])
                with self.assertRaises(StopIteration):
                    next(iterator)

            self.assertEqual(
                [candidate.number for candidate in batch.candidates], [1, 2, 3]
            )
            self.assertFalse(hasattr(first, "audio"))
            self.assertEqual(first.sampling_rate, 24000)
            self.assertEqual(first.frame_count, 1234)
            self.assertEqual(first.source_text, "generated source")
            self.assertEqual(first.style_name, "Neutral")
            with self.assertRaises(RuntimeError):
                batch.generate_all()
            batch.close()

    def test_later_synthesis_failure_keeps_completed_candidates_usable(self):
        failure = RuntimeError("synthesis failed")
        calls = []

        def synthesize_one():
            calls.append(None)
            if len(calls) == 3:
                raise failure
            return {"audio": object(), "sampling_rate": 32000}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory, synthesize_one=synthesize_one)
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                iterator = batch.generate_all()
                first = next(iterator)
                second = next(iterator)
                with self.assertRaises(RuntimeError) as raised:
                    next(iterator)

            self.assertIs(raised.exception, failure)
            self.assertEqual(batch.candidates, (first, second))
            self.assertTrue(first.wav_path.is_file())
            self.assertTrue(second.wav_path.is_file())
            batch.close()

    def test_failed_wav_write_leaves_no_broken_candidate_file(self):
        write_failure = OSError("cannot write wav")

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory)
            with patch.dict(
                "sys.modules",
                {"soundfile": self.fake_soundfile_module(write_failure)},
            ):
                with self.assertRaises(OSError) as raised:
                    next(batch.generate_all())

            self.assertIs(raised.exception, write_failure)
            self.assertEqual(batch.candidates, ())
            self.assertEqual(list(batch._temporary_path.iterdir()), [])
            batch.close()

    def test_successful_single_regeneration_replaces_only_selected_take(self):
        calls = []

        def synthesize_one():
            calls.append(len(calls) + 1)
            return {"audio": object(), "sampling_rate": 32000}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory, synthesize_one=synthesize_one)
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                first, old_second, third = list(batch.generate_all())
                replacement = batch.regenerate(2)

            self.assertEqual(calls, [1, 2, 3, 4])
            self.assertEqual(replacement.number, 2)
            self.assertEqual(batch.candidates, (first, replacement, third))
            self.assertIs(batch.candidates[0], first)
            self.assertIs(batch.candidates[2], third)
            self.assertFalse(old_second.wav_path.exists())
            self.assertTrue(replacement.wav_path.is_file())
            batch.close()

    def test_full_regeneration_requires_initial_generation(self):
        calls = []

        def synthesize_one():
            calls.append(None)
            return {"audio": object(), "sampling_rate": 32000}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory, synthesize_one=synthesize_one)
            with self.assertRaises(RuntimeError):
                batch.regenerate_all()

            self.assertEqual(calls, [])
            self.assertEqual(batch.candidates, ())
            self.assertEqual(list(batch._temporary_path.iterdir()), [])

            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                candidates = list(batch.generate_all())

            self.assertEqual(len(calls), batch.take_count)
            self.assertEqual(
                [candidate.number for candidate in candidates], [1, 2, 3]
            )
            batch.close()

    def test_full_regeneration_uses_only_existing_partial_slots_in_order(self):
        calls = []

        def synthesize_one():
            calls.append(None)
            return {"audio": object(), "sampling_rate": 32000}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(
                directory,
                take_count=100,
                synthesize_one=synthesize_one,
            )
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                generation = batch.generate_all()
                first = next(generation)
                second = next(generation)
                third = next(generation)
                regeneration = batch.regenerate_all()
                first_replacement = next(regeneration)
                self.assertEqual(first_replacement.number, 1)
                self.assertEqual(calls, [None, None, None, None])
                self.assertFalse(first.wav_path.exists())
                second_replacement = next(regeneration)
                third_replacement = next(regeneration)
                with self.assertRaises(StopIteration):
                    next(regeneration)

            self.assertEqual(
                [candidate.number for candidate in batch.candidates], [1, 2, 3]
            )
            self.assertEqual(
                batch.candidates,
                (first_replacement, second_replacement, third_replacement),
            )

            batch.close()

    def test_failed_single_regeneration_preserves_previous_candidate(self):
        failure = RuntimeError("replacement synthesis failed")
        calls = []

        def synthesize_one():
            calls.append(None)
            if len(calls) == 3:
                raise failure
            return {"audio": object(), "sampling_rate": 32000}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(
                directory, take_count=2, synthesize_one=synthesize_one
            )
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                first, second = list(batch.generate_all())
                with self.assertRaises(RuntimeError) as raised:
                    batch.regenerate(2)

            self.assertIs(raised.exception, failure)
            self.assertEqual(batch.candidates, (first, second))
            self.assertTrue(second.wav_path.is_file())
            batch.close()

    def test_full_regeneration_is_progressive_and_reuses_callback(self):
        calls = []

        def synthesize_one():
            calls.append(len(calls) + 1)
            return {"audio": object(), "sampling_rate": 44100}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory, synthesize_one=synthesize_one)
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                old = list(batch.generate_all())
                iterator = batch.regenerate_all()
                new_first = next(iterator)
                self.assertEqual(calls, [1, 2, 3, 4])
                self.assertEqual(batch.candidates, (new_first, old[1], old[2]))
                self.assertFalse(old[0].wav_path.exists())
                new_second = next(iterator)
                self.assertEqual(calls, [1, 2, 3, 4, 5])
                new_third = next(iterator)
                with self.assertRaises(StopIteration):
                    next(iterator)

            self.assertEqual(calls, [1, 2, 3, 4, 5, 6])
            self.assertEqual(
                batch.candidates, (new_first, new_second, new_third)
            )
            self.assertTrue(all(candidate.wav_path.is_file() for candidate in batch.candidates))
            self.assertTrue(all(not candidate.wav_path.exists() for candidate in old))
            batch.close()

    def test_accept_delegates_exact_options_and_cleans_all_candidates(self):
        audio_values = [object(), object(), object()]
        calls = []

        def synthesize_one():
            audio = audio_values[len(calls)]
            calls.append(audio)
            return {"audio": audio, "sampling_rate": 22050}

        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(
                directory,
                synthesize_one=synthesize_one,
                style_name="Sweet",
                save_text=True,
            )
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                candidates = list(batch.generate_all())
            temporary_paths = [candidate.wav_path for candidate in candidates]
            temporary_directory = temporary_paths[0].parent
            saved = SavedOutput(
                wav_path=Path(directory) / "saved.wav",
                text_path=Path(directory) / "saved.txt",
            )
            with patch(
                "voiceger_accent_adapter.takes.save_output_wav", return_value=saved
            ) as save_output_wav:
                result = batch.accept(2, output_dir=Path(directory), save_text=True)

            self.assertIs(result, saved)
            save_output_wav.assert_called_once_with(
                wav_source=temporary_paths[1],
                source_text="generated source",
                style_name="Sweet",
                output_dir=Path(directory),
                save_text=True,
            )
            self.assertTrue(all(not path.exists() for path in temporary_paths))
            self.assertFalse(temporary_directory.exists())
            self.assertEqual(batch.candidates, ())

    def test_failed_acceptance_preserves_all_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory)
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                candidates = list(batch.generate_all())
            with patch(
                "voiceger_accent_adapter.takes.save_output_wav",
                side_effect=OSError("save failed"),
            ):
                with self.assertRaisesRegex(OSError, "save failed"):
                    batch.accept(1, output_dir=Path(directory), save_text=False)

            self.assertEqual(batch.candidates, tuple(candidates))
            self.assertTrue(all(candidate.wav_path.is_file() for candidate in candidates))
            batch.close()

    def test_close_is_idempotent_and_operations_after_close_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = self.make_batch(directory)
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                candidate = next(batch.generate_all())
            temporary_directory = candidate.wav_path.parent

            batch.close()
            batch.close()

            self.assertFalse(candidate.wav_path.exists())
            self.assertFalse(temporary_directory.exists())
            self.assertEqual(batch.candidates, ())
            with self.assertRaises(RuntimeError):
                batch.generate_all()
            with self.assertRaises(RuntimeError):
                batch.regenerate(1)
            with self.assertRaises(RuntimeError):
                batch.regenerate_all()
            with self.assertRaises(RuntimeError):
                batch.accept(1, output_dir=Path(directory), save_text=False)

    def test_context_manager_closes_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                "sys.modules", {"soundfile": self.fake_soundfile_module()}
            ):
                with self.make_batch(directory) as batch:
                    candidate = next(batch.generate_all())
                    temporary_directory = candidate.wav_path.parent

            self.assertFalse(temporary_directory.exists())
            self.assertEqual(batch.candidates, ())

    def test_candidate_is_frozen(self):
        candidate = TakeCandidate(
            number=1,
            wav_path=Path("candidate.wav"),
            sampling_rate=32000,
            frame_count=100,
            source_text="source",
            style_name="Neutral",
        )
        with self.assertRaises(AttributeError):
            candidate.number = 2


if __name__ == "__main__":
    unittest.main()
