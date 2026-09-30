"""Accepted-take LAB sidecar dispatch, validation, and atomic publication."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Callable

from .voicevox_api_models import AudioQuery


LAB_UNITS_PER_SECOND = 10_000_000


@dataclass(frozen=True)
class LabSidecarResult:
    path: Path | None = None
    warning: str | None = None


def query_lab_language(query: AudioQuery) -> str:
    """Classify the accepted query for the production LAB dispatch boundary."""

    segments = query.voicegerSegments
    if segments is None:
        return "ja"
    languages = {segment.language for segment in segments}
    if languages == {"ja"}:
        return "ja"
    if languages == {"en"}:
        return "en"
    if languages == {"ja", "en"}:
        return "mixed"
    return "unsupported"


def normalize_and_validate_lab(
    content: str,
    *,
    wav_duration_seconds: float,
) -> str:
    """Validate full contiguous coverage and merge adjacent measured pauses."""

    duration_units = round(wav_duration_seconds * LAB_UNITS_PER_SECOND)
    if duration_units <= 0:
        raise ValueError("accepted WAV duration must be positive")

    intervals: list[tuple[int, int, str]] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        parts = raw_line.split()
        if len(parts) != 3:
            raise RuntimeError(f"invalid LAB row at line {line_number}")
        try:
            start = int(parts[0])
            end = int(parts[1])
        except ValueError as exc:
            raise RuntimeError(
                f"invalid LAB timing at line {line_number}"
            ) from exc
        phoneme = parts[2]
        if start < 0 or end <= start:
            raise RuntimeError(f"invalid LAB interval at line {line_number}")
        if intervals and start != intervals[-1][1]:
            raise RuntimeError(
                "LAB alignment contains an internal gap or overlap"
            )
        if intervals and phoneme == "pau" and intervals[-1][2] == "pau":
            previous_start, previous_end, _ = intervals[-1]
            if start != previous_end:
                raise RuntimeError(
                    "LAB pause intervals are not contiguous"
                )
            intervals[-1] = (previous_start, end, "pau")
        else:
            intervals.append((start, end, phoneme))

    if not intervals:
        raise RuntimeError("LAB alignment contains no intervals")
    if intervals[0][0] != 0:
        raise RuntimeError("LAB alignment does not start at the accepted WAV start")
    if intervals[-1][1] != duration_units:
        raise RuntimeError(
            "LAB alignment does not cover the accepted WAV duration"
        )
    return "".join(
        f"{start} {end} {phoneme}\n"
        for start, end, phoneme in intervals
    )


def _publish_lab(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"LAB sidecar already exists: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        if path.exists():
            raise FileExistsError(f"LAB sidecar already exists: {path}")
        temporary.replace(path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def save_lab_sidecar(
    *,
    wav_path: Path,
    query: AudioQuery,
    destination: Path | None = None,
    japanese_aligner: Callable[[Path, AudioQuery], str] | None = None,
    english_aligner: Callable[[Path, AudioQuery], str] | None = None,
) -> LabSidecarResult:
    """Generate one optional LAB sidecar without making WAV acceptance fail."""

    wav_path = Path(wav_path)
    lab_path = Path(destination) if destination is not None else wav_path.with_suffix(".lab")
    language = query_lab_language(query)

    if language == "mixed":
        return LabSidecarResult(
            warning=(
                "LAB not created: mixed Japanese-English alignment is not "
                "supported yet."
            )
        )
    if language == "unsupported":
        return LabSidecarResult(
            warning="LAB not created: this language combination is not supported."
        )

    try:
        if language == "ja":
            if japanese_aligner is None:
                from .lab_julius import align_japanese_lab
                japanese_aligner = align_japanese_lab
            content = japanese_aligner(wav_path, query)
        else:
            if english_aligner is None:
                from .lab_pocketsphinx import align_english_lab
                english_aligner = align_english_lab
            content = english_aligner(wav_path, query)

        import soundfile as sf

        normalized = normalize_and_validate_lab(
            content,
            wav_duration_seconds=float(sf.info(wav_path).duration),
        )
        _publish_lab(lab_path, normalized)
    except Exception as exc:
        return LabSidecarResult(
            warning=f"LAB generation failed: {exc}"
        )
    return LabSidecarResult(path=lab_path)
