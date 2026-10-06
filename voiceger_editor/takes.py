"""Temporary multi-take generation and candidate management."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping

from .filename import DEFAULT_FILENAME_TEMPLATE
from .lab import LabSidecarResult, save_lab_sidecar
from .output import SavedOutput, save_output_wav
from .voicevox_api_models import AudioQuery


_TAKE_TEMP_PREFIX = "voiceger-takes-"
_OWNER_PID_FILE = ".owner-pid"
_LEGACY_CLEANUP_GRACE_SECONDS = 24 * 60 * 60


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def cleanup_stale_take_directories(
    *,
    temp_root: Path | None = None,
    now: float | None = None,
    legacy_grace_seconds: float = _LEGACY_CLEANUP_GRACE_SECONDS,
) -> int:
    """Remove orphaned take directories without touching a live adapter process."""

    root = Path(tempfile.gettempdir()) if temp_root is None else Path(temp_root)
    current_time = time.time() if now is None else now
    removed = 0
    try:
        entries = tuple(root.glob(f"{_TAKE_TEMP_PREFIX}*"))
    except OSError:
        return 0

    for path in entries:
        try:
            if path.is_symlink() or not path.is_dir():
                continue
            marker = path / _OWNER_PID_FILE
            owner_pid = None
            if marker.is_file():
                try:
                    owner_pid = int(marker.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    owner_pid = None
            if owner_pid is not None:
                if _process_is_alive(owner_pid):
                    continue
            else:
                age = current_time - path.stat().st_mtime
                if age < legacy_grace_seconds:
                    continue
            shutil.rmtree(path)
            removed += 1
        except (FileNotFoundError, OSError):
            continue
    return removed


@dataclass(frozen=True)
class TakeCandidate:
    """Disk-backed take metadata and immutable generation provenance."""

    number: int
    wav_path: Path
    sampling_rate: int
    frame_count: int
    source_text: str
    style_name: str
    query: AudioQuery | None = None
    mixed_lab_provenance: Any | None = None
    mixed_lab_provenance_warning: str | None = None


class TakeBatch:
    """Sequentially generate, replace, audition, and accept temporary takes."""

    def __init__(
        self,
        *,
        take_count: int,
        synthesize_one: Callable[[], Mapping[str, Any]],
        style_name: str,
        source_text: str,
        query: AudioQuery | None = None,
    ) -> None:
        if (
            isinstance(take_count, bool)
            or not isinstance(take_count, int)
            or not 1 <= take_count <= 100
        ):
            raise ValueError("take_count must be an integer from 1 through 100")
        if not isinstance(source_text, str):
            raise TypeError("source_text must be a string")

        self.take_count = take_count
        self.synthesize_one = synthesize_one
        self._style_name = style_name
        self._source_text = source_text
        self._query = deepcopy(query)

        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix=_TAKE_TEMP_PREFIX
        )
        self._temporary_path = Path(self._temporary_directory.name)
        try:
            (self._temporary_path / _OWNER_PID_FILE).write_text(
                f"{os.getpid()}\n", encoding="ascii"
            )
        except BaseException:
            self._temporary_directory.cleanup()
            raise
        self._candidates: dict[int, TakeCandidate] = {}
        self._initial_generation_started = False
        self._closed = False

    @property
    def candidates(self) -> tuple[TakeCandidate, ...]:
        """Return completed candidates in take-number order."""

        return tuple(self._candidates[number] for number in sorted(self._candidates))

    @property
    def style_name(self) -> str:
        return self._style_name

    @property
    def source_text(self) -> str:
        return self._source_text

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

    def regenerate_all(
        self,
        take_count: int | None = None,
    ) -> Iterator[TakeCandidate]:
        """Regenerate and resize candidate slots progressively in take order."""

        self._ensure_open()
        if not self._candidates:
            raise RuntimeError("take regeneration requires a generated candidate")

        resizing = take_count is not None
        if resizing:
            target_count = take_count
            if (
                isinstance(target_count, bool)
                or not isinstance(target_count, int)
                or not 1 <= target_count <= 100
            ):
                raise ValueError(
                    "take_count must be an integer from 1 through 100"
                )
            numbers = tuple(range(1, target_count + 1))
        else:
            target_count = len(self._candidates)
            numbers = tuple(sorted(self._candidates))

        original_take_count = self.take_count
        if resizing and target_count > original_take_count:
            # Newly generated higher-numbered slots must remain valid even if
            # a later slot fails or the operation is cancelled.
            self.take_count = target_count

        def regenerate() -> Iterator[TakeCandidate]:
            completed = False
            try:
                for number in numbers:
                    previous = self._candidates.get(number)
                    replacement = self._generate_candidate(number)
                    self._candidates[number] = replacement
                    if previous is not None:
                        self._remove_candidate_file(previous)
                    yield replacement
                completed = True
            finally:
                if resizing and completed:
                    excess_numbers = tuple(
                        number
                        for number in sorted(self._candidates)
                        if number > target_count
                    )
                    for number in excess_numbers:
                        removed = self._candidates.pop(number)
                        self._remove_candidate_file(removed)
                    self.take_count = target_count
                elif (
                    resizing
                    and target_count < original_take_count
                ):
                    # A failed/cancelled shrink keeps the still-valid excess
                    # slots and their original acceptance range.
                    self.take_count = original_take_count

        return regenerate()

    def accept(
        self,
        take_number: int,
        *,
        output_dir: Path,
        save_text: bool,
        save_lab: bool = False,
        filename_template: str = DEFAULT_FILENAME_TEMPLATE,
    ) -> SavedOutput:
        """Save the selected candidate while keeping the review batch open."""

        self._ensure_open()
        number = self._validate_take_number(take_number)
        candidate = self._candidates.get(number)
        if candidate is None:
            raise ValueError(f"take {number} has no generated candidate")

        save_kwargs = {
            "wav_source": candidate.wav_path,
            "source_text": candidate.source_text,
            "style_name": candidate.style_name,
            "output_dir": output_dir,
            "save_text": save_text,
            "filename_template": filename_template,
        }
        if save_lab:
            save_kwargs["avoid_lab_collision"] = True
        saved = save_output_wav(**save_kwargs)

        if save_lab:
            if candidate.query is None:
                lab_result = LabSidecarResult(
                    warning="LAB generation failed: accepted take has no query snapshot"
                )
            else:
                lab_result = save_lab_sidecar(
                    wav_path=saved.wav_path,
                    query=deepcopy(candidate.query),
                    mixed_provenance=candidate.mixed_lab_provenance,
                    mixed_provenance_warning=(
                        candidate.mixed_lab_provenance_warning
                    ),
                )
            saved = replace(
                saved,
                lab_path=lab_result.path,
                lab_warning=lab_result.warning,
            )
        return saved

    def close(self) -> None:
        """Remove all candidate files and the owned temporary directory."""

        if self._closed:
            return
        self._candidates.clear()
        while True:
            try:
                self._temporary_directory.cleanup()
                break
            except KeyboardInterrupt:
                continue
        self._closed = True

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
            frame_count = int(sf.info(wav_path).frames)
        except BaseException:
            self._remove_candidate_file_path(wav_path)
            raise

        return TakeCandidate(
            number=number,
            wav_path=wav_path,
            sampling_rate=sampling_rate,
            frame_count=frame_count,
            source_text=self.source_text,
            style_name=self.style_name,
            query=deepcopy(self._query),
            mixed_lab_provenance=result.get("mixed_lab_provenance"),
            mixed_lab_provenance_warning=result.get(
                "mixed_lab_provenance_warning"
            ),
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
