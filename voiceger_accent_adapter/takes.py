"""Temporary multi-take generation and candidate management."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterator, Mapping, Optional

from .output import SavedOutput, save_output


@dataclass(frozen=True)
class TakeCandidate:
    """One generated take, retaining audio in memory for final acceptance."""

    number: int
    wav_path: Path
    audio: Any
    sampling_rate: int


class TakeBatch:
    """Sequentially generate, replace, audition, and accept temporary takes."""

    def __init__(
        self,
        *,
        take_count: int,
        synthesize_one: Callable[[], Mapping[str, Any]],
        source_text: str,
        output_dir: Path,
        save_text: bool = False,
        filename_text: Optional[str] = None,
    ) -> None:
        if (
            isinstance(take_count, bool)
            or not isinstance(take_count, int)
            or not 1 <= take_count <= 8
        ):
            raise ValueError("take_count must be an integer from 1 through 8")

        self.take_count = take_count
        self.synthesize_one = synthesize_one
        self.source_text = source_text
        self.output_dir = Path(output_dir)
        self.save_text = save_text
        self.filename_text = filename_text

        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="voiceger-takes-"
        )
        self._temporary_path = Path(self._temporary_directory.name)
        self._candidates: dict[int, TakeCandidate] = {}
        self._initial_generation_started = False
        self._closed = False

    @property
    def candidates(self) -> tuple[TakeCandidate, ...]:
        """Return completed candidates in take-number order."""

        return tuple(self._candidates[number] for number in sorted(self._candidates))

    def generate_all(self) -> Iterator[TakeCandidate]:
        """Generate the initial batch progressively, one take at a time."""

        self._ensure_open()
        if self._initial_generation_started:
            raise RuntimeError("initial take generation has already started")
        self._initial_generation_started = True

        def generate() -> Iterator[TakeCandidate]:
            for number in range(1, self.take_count + 1):
                candidate = self._generate_candidate(number)
                self._candidates[number] = candidate
                yield candidate

        return generate()

    def regenerate(self, take_number: int) -> TakeCandidate:
        """Replace one existing candidate after its new WAV is ready."""

        self._ensure_open()
        number = self._validate_take_number(take_number)
        previous = self._candidates.get(number)
        if previous is None:
            raise ValueError(f"take {number} has no generated candidate")

        replacement = self._generate_candidate(number)
        self._candidates[number] = replacement
        self._remove_candidate_file(previous)
        return replacement

    def regenerate_all(self) -> Iterator[TakeCandidate]:
        """Regenerate all configured slots progressively in take order."""

        self._ensure_open()

        def regenerate() -> Iterator[TakeCandidate]:
            for number in range(1, self.take_count + 1):
                previous = self._candidates.get(number)
                replacement = self._generate_candidate(number)
                self._candidates[number] = replacement
                if previous is not None:
                    self._remove_candidate_file(previous)
                yield replacement

        return regenerate()

    def accept(self, take_number: int) -> SavedOutput:
        """Save a selected candidate and clean up the temporary batch."""

        self._ensure_open()
        number = self._validate_take_number(take_number)
        candidate = self._candidates.get(number)
        if candidate is None:
            raise ValueError(f"take {number} has no generated candidate")

        saved = save_output(
            audio=candidate.audio,
            sampling_rate=candidate.sampling_rate,
            source_text=self.source_text,
            output_dir=self.output_dir,
            save_text=self.save_text,
            filename_text=self.filename_text,
        )
        self.close()
        return saved

    def close(self) -> None:
        """Remove all candidate files and the owned temporary directory."""

        if self._closed:
            return
        self._closed = True
        self._candidates.clear()
        self._temporary_directory.cleanup()

    def __enter__(self) -> TakeBatch:
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _generate_candidate(self, number: int) -> TakeCandidate:
        self._ensure_open()
        result = self.synthesize_one()
        if not isinstance(result, Mapping):
            raise TypeError("synthesize_one must return a mapping")
        if "audio" not in result or "sampling_rate" not in result:
            raise ValueError(
                "synthesize_one result must include audio and sampling_rate"
            )

        audio = result["audio"]
        sampling_rate = int(result["sampling_rate"])
        descriptor, path_string = tempfile.mkstemp(
            prefix=f"take-{number}-",
            suffix=".wav",
            dir=self._temporary_path,
        )
        os.close(descriptor)
        wav_path = Path(path_string)
        try:
            import soundfile as sf

            sf.write(wav_path, audio, sampling_rate)
        except BaseException:
            self._remove_candidate_file_path(wav_path)
            raise

        return TakeCandidate(
            number=number,
            wav_path=wav_path,
            audio=audio,
            sampling_rate=sampling_rate,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("take batch is closed")

    def _validate_take_number(self, take_number: int) -> int:
        if (
            isinstance(take_number, bool)
            or not isinstance(take_number, int)
            or not 1 <= take_number <= self.take_count
        ):
            raise ValueError(
                f"take_number must be an integer from 1 through {self.take_count}"
            )
        return take_number

    @staticmethod
    def _remove_candidate_file(candidate: TakeCandidate) -> None:
        TakeBatch._remove_candidate_file_path(candidate.wav_path)

    @staticmethod
    def _remove_candidate_file_path(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
