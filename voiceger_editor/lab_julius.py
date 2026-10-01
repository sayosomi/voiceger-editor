"""Japanese forced alignment for production LAB sidecars."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from .lab_audio import ALIGNMENT_SAMPLE_RATE, prepare_alignment_wav
from .voicevox_api_models import AudioQuery, Mora


JULIUS_SEGMENTATION_KIT_COMMIT = "e0e8bbaf98e27d19dfc6fe8312be607ad03592ad"
JULIUS_HMM_FILENAME = "hmmdefs_monof_mix16_gid.binhmm"
JULIUS_HMM_URL = (
    "https://raw.githubusercontent.com/julius-speech/segmentation-kit/"
    f"{JULIUS_SEGMENTATION_KIT_COMMIT}/models/{JULIUS_HMM_FILENAME}"
)
LAB_UNITS_PER_SECOND = 10_000_000
_FRAME_SECONDS = 0.01
_ALIGNMENT_OFFSET_SECONDS = 0.0125


@dataclass(frozen=True)
class JuliusAlignment:
    start_frame: int
    end_frame: int
    phoneme: str


@dataclass(frozen=True)
class JuliusStripTimeMap:
    sample_rate: int
    original_sample_count: int
    retained_original_indices: tuple[int, ...]

    def to_original_seconds(self, stripped_seconds: float) -> float:
        sample = round(stripped_seconds * self.sample_rate)
        if sample <= 0:
            return 0.0
        if sample >= len(self.retained_original_indices):
            return self.original_sample_count / self.sample_rate
        return self.retained_original_indices[sample] / self.sample_rate


def japanese_query_phonemes(query: AudioQuery) -> list[str]:
    """Flatten exact Japanese mora phonemes from the accepted query snapshot."""

    segments = query.voicegerSegments
    if segments is not None and any(segment.language != "ja" for segment in segments):
        raise ValueError("Julius LAB alignment requires a pure Japanese query")

    phonemes: list[str] = []
    for phrase in query.accent_phrases:
        for mora in phrase.moras:
            phonemes.extend(_mora_phonemes(mora))
        if phrase.pause_mora is not None:
            phonemes.extend(_mora_phonemes(phrase.pause_mora))
    if not phonemes:
        raise ValueError("Japanese query contains no phonemes")
    return phonemes


def _mora_phonemes(mora: Mora) -> list[str]:
    result: list[str] = []
    if mora.consonant:
        result.append(mora.consonant)
    result.append(mora.vowel)
    return result


def to_julius_phoneme(phoneme: str) -> str:
    if phoneme == "cl":
        return "q"
    if phoneme in {"pau", "sil"}:
        return "sp"
    if phoneme in {"A", "I", "U", "E", "O"}:
        return phoneme.lower()
    return phoneme


def to_lab_phoneme(phoneme: str) -> str:
    if phoneme in {"silB", "silE", "sp", "pau", "sil"}:
        return "pau"
    if phoneme == "q":
        return "cl"
    if phoneme == "N":
        return "N"
    if phoneme in {"A", "I", "U", "E", "O"}:
        return phoneme.lower()
    return phoneme


def julius_strip_time_map(samples, sample_rate: int) -> JuliusStripTimeMap:
    """Mirror Julius strip_zero() so timestamps map back to the accepted WAV."""

    retained: list[int] = []
    run_start: int | None = None
    for index, value in enumerate(samples):
        invalid = int(value) in {0, -32767}
        if invalid:
            if run_start is None:
                run_start = index
            continue
        if run_start is not None:
            if index - run_start < 16:
                retained.extend(range(run_start, index))
            run_start = None
        retained.append(index)
    if run_start is not None and len(samples) - run_start < 16:
        retained.extend(range(run_start, len(samples)))
    if not retained:
        raise RuntimeError("Julius alignment WAV contains no retained audio samples")
    return JuliusStripTimeMap(
        sample_rate=sample_rate,
        original_sample_count=len(samples),
        retained_original_indices=tuple(retained),
    )


def _write_sequence_grammar(
    directory: Path,
    phonemes: list[str],
) -> tuple[Path, Path]:
    words = ["silB", *phonemes, "silE"]
    dfa_path = directory / "alignment.dfa"
    dict_path = directory / "alignment.dict"
    final_index = len(words)
    dfa_lines = [
        (
            f"{index} {final_index - 1 - index} {index + 1} 0 "
            f"{1 if index == 0 else 0}"
        )
        for index in range(len(words))
    ]
    dfa_lines.append(f"{final_index} -1 -1 1 0")
    dfa_path.write_text("\n".join(dfa_lines) + "\n", encoding="utf-8")
    dict_path.write_text(
        "\n".join(
            f"{index} [w_{index}] {phoneme}"
            for index, phoneme in enumerate(words)
        )
        + "\n",
        encoding="utf-8",
    )
    return dfa_path, dict_path


_ALIGNMENT_RE = re.compile(
    r"^\[\s*(\d+)\s+(\d+)\]\s+[-+0-9.eE]+\s+(.+?)\s*$"
)


def _central_phoneme(unit: str) -> str:
    value = unit.split()[0]
    value = value.split("[", 1)[0]
    if "-" in value and "+" in value:
        return value.split("-", 1)[1].split("+", 1)[0]
    if "+" in value:
        return value.split("+", 1)[0]
    if "-" in value:
        return value.rsplit("-", 1)[1]
    return value


def parse_julius_alignment(log: str) -> list[JuliusAlignment]:
    active = False
    result: list[JuliusAlignment] = []
    for line in log.splitlines():
        if "begin forced alignment" in line:
            active = True
            continue
        if "end forced alignment" in line:
            active = False
            continue
        if not active:
            continue
        match = _ALIGNMENT_RE.match(line.strip())
        if match is None:
            continue
        start_frame, end_frame, unit = match.groups()
        result.append(
            JuliusAlignment(
                start_frame=int(start_frame),
                end_frame=int(end_frame),
                phoneme=_central_phoneme(unit),
            )
        )
    if not result:
        raise RuntimeError("Julius returned no phoneme alignment")
    return result


def _seconds_from_frames(alignment: JuliusAlignment) -> tuple[float, float]:
    start = alignment.start_frame * _FRAME_SECONDS
    if alignment.start_frame != 0:
        start += _ALIGNMENT_OFFSET_SECONDS
    end = (
        (alignment.end_frame + 1) * _FRAME_SECONDS
        + _ALIGNMENT_OFFSET_SECONDS
    )
    return start, end


def render_julius_lab(
    alignments: list[JuliusAlignment],
    expected: list[str],
    *,
    time_map: JuliusStripTimeMap,
    wav_duration_seconds: float,
) -> str:
    actual = [to_lab_phoneme(item.phoneme) for item in alignments]
    if actual != expected:
        raise RuntimeError(
            "Julius aligned phoneme sequence does not match the accepted query: "
            f"expected={' '.join(expected)!r}, actual={' '.join(actual)!r}"
        )

    lines: list[str] = []
    previous_end: int | None = None
    last_index = len(alignments) - 1
    wav_end_units = round(wav_duration_seconds * LAB_UNITS_PER_SECOND)
    for index, (item, phoneme) in enumerate(zip(alignments, actual)):
        start_seconds, end_seconds = _seconds_from_frames(item)
        start_units = round(
            time_map.to_original_seconds(start_seconds) * LAB_UNITS_PER_SECOND
        )
        end_units = round(
            time_map.to_original_seconds(end_seconds) * LAB_UNITS_PER_SECOND
        )
        if previous_end is not None and start_units != previous_end:
            raise RuntimeError(
                "Julius alignment contains a gap or overlap after source-time mapping"
            )
        if index == last_index:
            if phoneme != "pau":
                raise RuntimeError("Julius alignment has no trailing boundary silence")
            if wav_end_units < start_units:
                raise RuntimeError("accepted WAV ends before Julius trailing silence")
            end_units = wav_end_units
        if end_units <= start_units:
            raise RuntimeError(
                f"Julius interval collapsed for phoneme {phoneme!r}"
            )
        lines.append(f"{start_units} {end_units} {phoneme}")
        previous_end = end_units
    return "\n".join(lines) + "\n"


def _default_cache_dir() -> Path:
    override = os.environ.get("VOICEGER_LAB_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "voiceger-editor" / "lab"
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return root / "voiceger-editor" / "lab"


def resolve_julius_executable() -> str:
    override = os.environ.get("VOICEGER_JULIUS")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Julius executable not found: {path}")
        return str(path.absolute())
    resolved = shutil.which("julius")
    if resolved is None:
        raise FileNotFoundError(
            "Julius executable not found; install Julius or set VOICEGER_JULIUS"
        )
    return resolved


def resolve_julius_model() -> Path:
    override = os.environ.get("VOICEGER_JULIUS_HMM")
    if override:
        path = Path(override).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Julius HMM model not found: {path}")
        return path.absolute()

    path = (
        _default_cache_dir()
        / "julius"
        / JULIUS_SEGMENTATION_KIT_COMMIT
        / JULIUS_HMM_FILENAME
    )
    if path.is_file():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=JULIUS_HMM_FILENAME + ".",
        suffix=".download",
        dir=path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        urllib.request.urlretrieve(JULIUS_HMM_URL, temporary)
        temporary.replace(path)
    except Exception as exc:
        raise RuntimeError(
            "could not download the pinned Julius segmentation model"
        ) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def _run_julius(
    *,
    julius: str,
    hmm_model: Path,
    wav_path: Path,
    phonemes: list[str],
    work_dir: Path,
) -> list[JuliusAlignment]:
    dfa_path, dict_path = _write_sequence_grammar(work_dir, phonemes)
    process = subprocess.run(
        [
            julius,
            "-h",
            str(hmm_model),
            "-dfa",
            str(dfa_path),
            "-v",
            str(dict_path),
            "-palign",
            "-input",
            "file",
        ],
        input=str(wav_path) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    log = process.stdout + "\n" + process.stderr
    if process.returncode != 0:
        detail = process.stderr.strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        raise RuntimeError(
            f"Julius exited with status {process.returncode}{suffix}"
        )
    return parse_julius_alignment(log)


def align_japanese_lab(wav_path: Path, query: AudioQuery) -> str:
    """Forced-align a pure-Japanese accepted WAV using the pinned Julius model."""

    adapter_phonemes = japanese_query_phonemes(query)
    julius_phonemes = [to_julius_phoneme(phone) for phone in adapter_phonemes]
    expected = [
        "pau",
        *[to_lab_phoneme(phone) for phone in adapter_phonemes],
        "pau",
    ]
    julius = resolve_julius_executable()
    hmm_model = resolve_julius_model()

    with tempfile.TemporaryDirectory(prefix="voiceger-lab-ja-") as temporary:
        work_dir = Path(temporary)
        alignment_wav = work_dir / "alignment.wav"
        prepared = prepare_alignment_wav(wav_path, alignment_wav)
        time_map = julius_strip_time_map(
            prepared.samples,
            ALIGNMENT_SAMPLE_RATE,
        )
        alignments = _run_julius(
            julius=julius,
            hmm_model=hmm_model,
            wav_path=alignment_wav,
            phonemes=julius_phonemes,
            work_dir=work_dir,
        )
        return render_julius_lab(
            alignments,
            expected,
            time_map=time_map,
            wav_duration_seconds=prepared.original_duration_seconds,
        )
