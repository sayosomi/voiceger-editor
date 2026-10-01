"""Production Japanese-English mixed forced alignment."""

from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Callable

from .lab_mixed_attention import MixedLabProvenance
from .voicevox_api_models import AudioQuery


LAB_UNITS_PER_SECOND = 10_000_000
SYNTHETIC_ALIGNMENT_PADDING_SECONDS = 0.20


def segment_alignment_query(
    query: AudioQuery,
    *,
    segment_index: int,
) -> AudioQuery:
    """Extract one exact adapter-owned mixed segment as a pure aligner query."""

    segments = query.voicegerSegments
    if not segments:
        raise ValueError("mixed LAB alignment requires voicegerSegments")
    if segment_index < 0 or segment_index >= len(segments):
        raise IndexError("mixed LAB segment index is out of range")

    segment = segments[segment_index]
    result = query.model_copy(deep=True)
    if segment.language == "ja":
        if (
            segment.accentPhraseStart is None
            or segment.accentPhraseCount is None
        ):
            raise ValueError(
                "Japanese voicegerSegments require accent phrase references"
            )
        start = segment.accentPhraseStart
        end = start + segment.accentPhraseCount
        if start < 0 or end > len(query.accent_phrases) or start == end:
            raise ValueError(
                "Japanese voicegerSegments accent phrase range is invalid"
            )
        result.accent_phrases = [
            phrase.model_copy(deep=True)
            for phrase in query.accent_phrases[start:end]
        ]
        result.voicegerSegments = None
        result.kana = None
        return result

    if segment.language == "en":
        if segment.phonemes is None:
            raise ValueError(
                "English voicegerSegments require adapter-owned phonemes"
            )
        result.accent_phrases = []
        result.voicegerSegments = [segment.model_copy(deep=True)]
        result.kana = None
        return result

    raise ValueError(
        "mixed LAB alignment supports only Japanese and English segments"
    )


def trim_synthetic_padding_lab(
    content: str,
    *,
    padding_seconds: float,
    core_duration_seconds: float,
) -> str:
    """Remove only symmetric synthetic pause padding from an English LAB."""

    if padding_seconds <= 0 or core_duration_seconds <= 0:
        raise ValueError("mixed LAB synthetic padding timing is invalid")

    padding_units = round(padding_seconds * LAB_UNITS_PER_SECOND)
    core_units = round(core_duration_seconds * LAB_UNITS_PER_SECOND)
    total_units = core_units + 2 * padding_units
    core_start = padding_units
    core_end = padding_units + core_units

    rows: list[tuple[int, int, str]] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        parts = raw_line.split()
        if len(parts) != 3:
            raise RuntimeError(
                f"invalid padded LAB row at line {line_number}"
            )
        try:
            start = int(parts[0])
            end = int(parts[1])
        except ValueError as exc:
            raise RuntimeError(
                f"invalid padded LAB timing at line {line_number}"
            ) from exc
        if start < 0 or end <= start:
            raise RuntimeError(
                f"invalid padded LAB interval at line {line_number}"
            )
        if rows and start != rows[-1][1]:
            raise RuntimeError("padded LAB contains a gap or overlap")
        rows.append((start, end, parts[2]))

    if not rows:
        raise RuntimeError("padded LAB contains no intervals")
    if rows[0][0] != 0 or rows[-1][1] != total_units:
        raise RuntimeError(
            "padded LAB does not cover the complete padded alignment WAV"
        )

    trimmed: list[tuple[int, int, str]] = []
    for start, end, phoneme in rows:
        if end <= core_start or start >= core_end:
            continue
        if phoneme != "pau" and (start < core_start or end > core_end):
            raise RuntimeError(
                "acoustic phone extends into synthetic alignment padding: "
                f"{phoneme!r} {start}:{end}"
            )

        clipped_start = max(start, core_start) - core_start
        clipped_end = min(end, core_end) - core_start
        if clipped_end <= clipped_start:
            continue
        if trimmed and clipped_start != trimmed[-1][1]:
            raise RuntimeError("trimmed LAB contains a gap or overlap")
        if trimmed and phoneme == "pau" and trimmed[-1][2] == "pau":
            previous_start, _previous_end, _ = trimmed[-1]
            trimmed[-1] = (previous_start, clipped_end, "pau")
        else:
            trimmed.append((clipped_start, clipped_end, phoneme))

    if not trimmed:
        raise RuntimeError("trimmed LAB contains no intervals")
    if trimmed[0][0] != 0 or trimmed[-1][1] != core_units:
        raise RuntimeError(
            "trimmed LAB does not cover the complete real-audio core"
        )
    return "".join(
        f"{start} {end} {phoneme}\n"
        for start, end, phoneme in trimmed
    )


def _parse_local_lab(content: str) -> list[tuple[int, int, str]]:
    rows: list[tuple[int, int, str]] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        parts = raw_line.split()
        if len(parts) != 3:
            raise RuntimeError(
                f"invalid mixed LAB row at line {line_number}"
            )
        try:
            start = int(parts[0])
            end = int(parts[1])
        except ValueError as exc:
            raise RuntimeError(
                f"invalid mixed LAB timing at line {line_number}"
            ) from exc
        if start < 0 or end <= start:
            raise RuntimeError(
                f"invalid mixed LAB interval at line {line_number}"
            )
        if rows and start != rows[-1][1]:
            raise RuntimeError("mixed LAB region contains a gap or overlap")
        rows.append((start, end, parts[2]))
    if not rows:
        raise RuntimeError("mixed LAB region contains no intervals")
    return rows


def stitch_mixed_lab_regions(
    contents: tuple[str, ...],
    *,
    sample_edges: tuple[int, ...],
    sample_rate: int,
) -> str:
    """Map complete region LABs onto exact accepted-WAV sample boundaries."""

    if sample_rate <= 0:
        raise ValueError("mixed LAB sample rate must be positive")
    if len(sample_edges) != len(contents) + 1 or not contents:
        raise ValueError("mixed LAB region/sample boundary counts disagree")
    if sample_edges[0] != 0:
        raise ValueError("mixed LAB sample edges must start at zero")

    rendered: list[tuple[int, int, str]] = []
    for index, content in enumerate(contents):
        start_sample = sample_edges[index]
        end_sample = sample_edges[index + 1]
        if end_sample <= start_sample:
            raise ValueError("mixed LAB sample regions must be non-empty")

        rows = _parse_local_lab(content)
        local_duration_units = round(
            (end_sample - start_sample)
            * LAB_UNITS_PER_SECOND
            / sample_rate
        )
        if rows[0][0] != 0 or rows[-1][1] != local_duration_units:
            raise RuntimeError(
                "mixed LAB region does not cover its complete audio crop"
            )

        segment_start_units = round(
            start_sample * LAB_UNITS_PER_SECOND / sample_rate
        )
        segment_end_units = round(
            end_sample * LAB_UNITS_PER_SECOND / sample_rate
        )
        previous_global_end = segment_start_units

        for row_index, (_start, local_end, phoneme) in enumerate(rows):
            global_start = previous_global_end
            if row_index == len(rows) - 1:
                global_end = segment_end_units
            else:
                global_end = segment_start_units + local_end
            if global_end <= global_start:
                raise RuntimeError(
                    f"mixed LAB interval collapsed for {phoneme!r}"
                )

            if rendered and global_start != rendered[-1][1]:
                raise RuntimeError(
                    "mixed LAB contains a gap or overlap at a language seam"
                )
            if rendered and phoneme == "pau" and rendered[-1][2] == "pau":
                previous_start, _previous_end, _ = rendered[-1]
                rendered[-1] = (previous_start, global_end, "pau")
            else:
                rendered.append((global_start, global_end, phoneme))
            previous_global_end = global_end

    final_units = round(
        sample_edges[-1] * LAB_UNITS_PER_SECOND / sample_rate
    )
    if (
        not rendered
        or rendered[0][0] != 0
        or rendered[-1][1] != final_units
    ):
        raise RuntimeError(
            "mixed LAB does not cover the complete accepted WAV"
        )
    return "".join(
        f"{start} {end} {phoneme}\n"
        for start, end, phoneme in rendered
    )


def align_mixed_lab(
    wav_path: Path,
    query: AudioQuery,
    provenance: object,
    *,
    japanese_aligner: Callable[[Path, AudioQuery], str] | None = None,
    english_aligner: Callable[[Path, AudioQuery], str] | None = None,
) -> str:
    """Forced-align attention-defined Japanese/English regions."""

    if not isinstance(provenance, MixedLabProvenance):
        raise TypeError("mixed LAB timing provenance has an invalid type")
    segments = query.voicegerSegments
    if (
        not segments
        or {segment.language for segment in segments} != {"ja", "en"}
    ):
        raise ValueError(
            "mixed LAB alignment requires Japanese and English segments"
        )
    languages = tuple(segment.language for segment in segments)
    if provenance.segment_languages != languages:
        raise RuntimeError(
            "mixed LAB timing provenance does not match the accepted query"
        )
    if len(provenance.boundary_seconds) != len(segments) - 1:
        raise RuntimeError("mixed LAB timing provenance boundary count is invalid")

    if japanese_aligner is None:
        from .lab_julius import align_japanese_lab
        japanese_aligner = align_japanese_lab
    if english_aligner is None:
        from .lab_pocketsphinx import align_english_lab
        english_aligner = align_english_lab

    import numpy as np
    import soundfile as sf

    audio, sample_rate = sf.read(
        Path(wav_path),
        dtype="float32",
        always_2d=True,
    )
    frame_count = int(audio.shape[0])
    if frame_count <= 0 or sample_rate <= 0:
        raise ValueError("accepted mixed WAV contains no usable audio")

    boundary_samples: list[int] = []
    previous = 0
    for seconds in provenance.boundary_seconds:
        sample = int(round(seconds * sample_rate))
        if sample <= previous or sample >= frame_count:
            raise RuntimeError(
                "mixed LAB timing provenance falls outside accepted WAV"
            )
        boundary_samples.append(sample)
        previous = sample
    sample_edges = (0, *boundary_samples, frame_count)

    contents: list[str] = []
    with tempfile.TemporaryDirectory(prefix="voiceger-lab-mixed-") as temporary:
        root = Path(temporary)
        for index, segment in enumerate(segments):
            start = sample_edges[index]
            end = sample_edges[index + 1]
            crop = audio[start:end]
            crop_path = root / f"segment-{index:02d}-{segment.language}.wav"
            sf.write(
                crop_path,
                crop,
                sample_rate,
                subtype="PCM_16",
                format="WAV",
            )
            segment_query = segment_alignment_query(
                query,
                segment_index=index,
            )

            if segment.language == "ja":
                content = japanese_aligner(crop_path, segment_query)
            else:
                try:
                    content = english_aligner(crop_path, segment_query)
                except Exception as direct_error:
                    padding_frames = int(
                        round(
                            SYNTHETIC_ALIGNMENT_PADDING_SECONDS
                            * sample_rate
                        )
                    )
                    if padding_frames <= 0:
                        raise RuntimeError(
                            "mixed LAB synthetic padding collapsed"
                        ) from direct_error
                    padding = np.zeros(
                        (padding_frames, audio.shape[1]),
                        dtype=audio.dtype,
                    )
                    padded_path = (
                        root
                        / f"segment-{index:02d}-{segment.language}-padded.wav"
                    )
                    sf.write(
                        padded_path,
                        np.concatenate((padding, crop, padding), axis=0),
                        sample_rate,
                        subtype="PCM_16",
                        format="WAV",
                    )
                    try:
                        padded_content = english_aligner(
                            padded_path,
                            segment_query,
                        )
                    except Exception as fallback_error:
                        raise RuntimeError(
                            "direct and synthetic-padding PocketSphinx "
                            "alignment both failed; direct="
                            f"{type(direct_error).__name__}: {direct_error}; "
                            "fallback="
                            f"{type(fallback_error).__name__}: {fallback_error}"
                        ) from fallback_error
                    content = trim_synthetic_padding_lab(
                        padded_content,
                        padding_seconds=(
                            SYNTHETIC_ALIGNMENT_PADDING_SECONDS
                        ),
                        core_duration_seconds=(end - start) / sample_rate,
                    )
            contents.append(content)

    return stitch_mixed_lab_regions(
        tuple(contents),
        sample_edges=tuple(sample_edges),
        sample_rate=sample_rate,
    )
