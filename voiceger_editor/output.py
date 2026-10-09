"""Reusable, collision-safe output saving for synthesized audio."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import errno
from pathlib import Path
import shutil
import subprocess
from typing import Any, Optional

from .filename import DEFAULT_FILENAME_TEMPLATE, build_output_filename


OUTPUT_FORMATS = ("wav", "flac", "mp3")
WAV_ENCODINGS = ("source", "pcm16", "pcm24", "float32")
FLAC_ENCODINGS = ("pcm16", "pcm24")
MP3_BITRATES = ("96k", "128k", "160k", "192k", "256k", "320k")
DEFAULT_MP3_BITRATE = "192k"

_OUTPUT_EXTENSIONS = {
    "wav": ".wav",
    "flac": ".flac",
    "mp3": ".mp3",
}
_OUTPUT_SUBTYPES = {
    ("wav", "pcm16"): "PCM_16",
    ("wav", "pcm24"): "PCM_24",
    ("wav", "float32"): "FLOAT",
    ("flac", "pcm16"): "PCM_16",
    ("flac", "pcm24"): "PCM_24",
}


@dataclass(frozen=True)
class SavedOutput:
    """Paths written by accepted-output persistence."""

    wav_path: Path
    text_path: Optional[Path]
    lab_path: Optional[Path] = None
    lab_warning: Optional[str] = None

    @property
    def audio_path(self) -> Path:
        """Return the accepted audio path, regardless of its selected format."""

        return self.wav_path


def ffmpeg_executable() -> str | None:
    """Return the ffmpeg executable available from the current environment."""

    return shutil.which("ffmpeg")


def available_output_formats() -> tuple[str, ...]:
    """Return accepted-output formats currently usable on this machine."""

    if ffmpeg_executable() is None:
        return tuple(value for value in OUTPUT_FORMATS if value != "mp3")
    return OUTPUT_FORMATS


def output_extension(output_format: str) -> str:
    """Return the file extension for one validated accepted-output format."""

    try:
        return _OUTPUT_EXTENSIONS[output_format]
    except KeyError as exc:
        raise ValueError(f"unsupported output format: {output_format!r}") from exc


def _validate_output_selection(output_format: str, output_encoding: str) -> None:
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"unsupported output format: {output_format!r}")
    if output_format == "wav":
        allowed = WAV_ENCODINGS
        label = "encoding"
    elif output_format == "flac":
        allowed = FLAC_ENCODINGS
        label = "encoding"
    else:
        allowed = MP3_BITRATES
        label = "bitrate"
    if output_encoding not in allowed:
        raise ValueError(
            f"unsupported {output_format.upper()} {label}: {output_encoding!r}"
        )


def _write_mp3(*, wav_source: Path, destination: Path, bitrate: str) -> None:
    executable = ffmpeg_executable()
    if executable is None:
        raise RuntimeError("MP3 output requires ffmpeg to be installed and discoverable on PATH.")

    try:
        subprocess.run(
            [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(wav_source),
                "-b:a",
                bitrate,
                str(destination),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        if detail:
            raise RuntimeError(f"MP3 conversion failed: {detail}") from exc
        raise RuntimeError(
            f"MP3 conversion failed: ffmpeg exited with status {exc.returncode}."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"MP3 conversion failed: {exc}") from exc


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
    audio_extension: str,
    save_text: bool,
    avoid_lab_collision: bool = False,
) -> tuple[Path, Path | None, list[Path]]:
    """Reserve a collision-safe audio/TXT basename and return owned paths."""

    stem = initial_name[:-4]
    collision_number = 1
    while True:
        suffix = "" if collision_number == 1 else f"-{collision_number}"
        audio_path = output_dir / f"{stem}{suffix}{audio_extension}"
        text_path = output_dir / f"{stem}{suffix}.txt" if save_text else None
        lab_path = output_dir / f"{stem}{suffix}.lab"
        reserved: list[Path] = []

        if avoid_lab_collision and lab_path.exists():
            collision_number += 1
            continue

        try:
            _reserve(audio_path)
            reserved.append(audio_path)
            if text_path is not None:
                _reserve(text_path)
                reserved.append(text_path)
            if avoid_lab_collision and lab_path.exists():
                raise FileExistsError(str(lab_path))
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
                    str(exc.filename or audio_path),
                ) from exc
            raise
        except BaseException:
            _remove_reservations(reserved)
            raise

        return audio_path, text_path, reserved


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
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
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
        text=filename_text if filename_text is not None else source_text,
        style=style_name,
        timestamp=timestamp,
        filename_template=filename_template,
    )
    wav_path, text_path, reserved = _reserve_output_paths(
        output_dir=output_dir,
        initial_name=initial_name,
        audio_extension=".wav",
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


def save_output_audio(
    *,
    wav_source: Path,
    source_text: str,
    style_name: str,
    output_dir: Path,
    output_format: str = "wav",
    output_encoding: str = "source",
    save_text: bool = False,
    timestamp: Optional[datetime] = None,
    avoid_lab_collision: bool = False,
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
) -> SavedOutput:
    """Persist a candidate WAV using the selected accepted-output format.

    For accepted output, source_text is the current Caption, not the query text.
    WAV Source copies candidate bytes without decoding; other WAV encodings,
    FLAC, and optional MP3 convert only the final accepted output.
    """

    _validate_output_selection(output_format, output_encoding)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    initial_name = build_output_filename(
        text=source_text,
        style=style_name,
        timestamp=timestamp,
        filename_template=filename_template,
    )
    audio_path, text_path, reserved = _reserve_output_paths(
        output_dir=output_dir,
        initial_name=initial_name,
        audio_extension=output_extension(output_format),
        save_text=save_text,
        avoid_lab_collision=avoid_lab_collision,
    )

    try:
        if output_format == "wav" and output_encoding == "source":
            shutil.copyfile(wav_source, audio_path)
        elif output_format == "mp3":
            _write_mp3(
                wav_source=Path(wav_source),
                destination=audio_path,
                bitrate=output_encoding,
            )
        else:
            import soundfile as sf

            audio, sampling_rate = sf.read(wav_source)
            sf.write(
                audio_path,
                audio,
                sampling_rate,
                format=output_format.upper(),
                subtype=_OUTPUT_SUBTYPES[(output_format, output_encoding)],
            )
        if text_path is not None:
            with text_path.open("w", encoding="utf-8", newline="") as text_file:
                text_file.write(source_text)
    except BaseException:
        _remove_reservations(reserved)
        raise

    return SavedOutput(wav_path=audio_path, text_path=text_path)


def save_output_wav(
    *,
    wav_source: Path,
    source_text: str,
    style_name: str,
    output_dir: Path,
    save_text: bool = False,
    timestamp: Optional[datetime] = None,
    avoid_lab_collision: bool = False,
    filename_template: str = DEFAULT_FILENAME_TEMPLATE,
) -> SavedOutput:
    """Copy an existing WAV to a reserved output path without decoding it."""

    return save_output_audio(
        wav_source=wav_source,
        source_text=source_text,
        style_name=style_name,
        output_dir=output_dir,
        output_format="wav",
        output_encoding="source",
        save_text=save_text,
        timestamp=timestamp,
        avoid_lab_collision=avoid_lab_collision,
        filename_template=filename_template,
    )
