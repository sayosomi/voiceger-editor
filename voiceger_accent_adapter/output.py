"""Reusable, collision-safe output saving for synthesized audio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import errno
from pathlib import Path
import shutil
from typing import Any, Optional

from .filename import build_output_filename


@dataclass(frozen=True)
class SavedOutput:
    """Paths written by :func:`save_output`."""

    wav_path: Path
    text_path: Optional[Path]


def _reserve(path: Path) -> None:
    """Create an empty file without replacing a path that already exists."""

    with path.open("xb"):
        pass


def _remove_reservations(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _reserve_output_paths(
    *,
    output_dir: Path,
    initial_name: str,
    save_text: bool,
) -> tuple[Path, Path | None, list[Path]]:
    """Reserve a collision-safe WAV/TXT basename and return owned paths."""

    stem = initial_name[:-4]
    collision_number = 1
    while True:
        suffix = "" if collision_number == 1 else f"-{collision_number}"
        wav_path = output_dir / f"{stem}{suffix}.wav"
        text_path = output_dir / f"{stem}{suffix}.txt" if save_text else None
        reserved: list[Path] = []

        try:
            _reserve(wav_path)
            reserved.append(wav_path)
            if text_path is not None:
                _reserve(text_path)
                reserved.append(text_path)
        except FileExistsError:
            _remove_reservations(reserved)
            collision_number += 1
            continue
        except OSError as exc:
            _remove_reservations(reserved)
            if exc.errno == errno.ENAMETOOLONG:
                raise OSError(
                    errno.ENAMETOOLONG,
                    "Output filename is too long; the source text was not truncated automatically.",
                    str(exc.filename or wav_path),
                ) from exc
            raise
        except BaseException:
            _remove_reservations(reserved)
            raise

        return wav_path, text_path, reserved


def save_output(
    *,
    audio: Any,
    sampling_rate: int,
    source_text: str,
    style_name: str,
    output_dir: Path,
    save_text: bool = False,
    timestamp: Optional[datetime] = None,
    filename_text: Optional[str] = None,
) -> SavedOutput:
    """Write a WAV and optionally its exact source text using a free basename.

    Files are exclusively reserved before writing, so an existing output is
    never replaced. Paired WAV/TXT output reserves both paths before either is
    written. ``filename_text`` can preserve an adapter's established naming
    text while ``source_text`` remains byte-for-byte the text saved to TXT.
    """

    import soundfile as sf

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    initial_name = build_output_filename(
        style_name=style_name,
        text=filename_text if filename_text is not None else source_text,
        timestamp=timestamp,
    )
    wav_path, text_path, reserved = _reserve_output_paths(
        output_dir=output_dir,
        initial_name=initial_name,
        save_text=save_text,
    )

    try:
        sf.write(wav_path, audio, sampling_rate)
        if text_path is not None:
            with text_path.open("w", encoding="utf-8", newline="") as text_file:
                text_file.write(source_text)
    except BaseException:
        _remove_reservations(reserved)
        raise

    return SavedOutput(wav_path=wav_path, text_path=text_path)


def save_output_wav(
    *,
    wav_source: Path,
    source_text: str,
    style_name: str,
    output_dir: Path,
    save_text: bool = False,
    timestamp: Optional[datetime] = None,
) -> SavedOutput:
    """Copy an existing WAV to a reserved output path without decoding it."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    initial_name = build_output_filename(
        style_name=style_name,
        text=source_text,
        timestamp=timestamp,
    )
    wav_path, text_path, reserved = _reserve_output_paths(
        output_dir=output_dir,
        initial_name=initial_name,
        save_text=save_text,
    )

    try:
        shutil.copyfile(wav_source, wav_path)
        if text_path is not None:
            with text_path.open("w", encoding="utf-8", newline="") as text_file:
                text_file.write(source_text)
    except BaseException:
        _remove_reservations(reserved)
        raise

    return SavedOutput(wav_path=wav_path, text_path=text_path)
