"""Production MRTE timing provenance for mixed-language LAB output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .english_stress import normalize_english_phonemes
from .mixed_language import resolve_japanese_segment_terminator
from .voiceger_tokens import pronunciation_to_voiceger_tokens
from .voicevox_api_models import AudioQuery
from .voicevox_query import accent_phrases_to_pronunciation


_ONSET_THRESHOLDS_DB = (-40.0, -35.0, -30.0, -25.0)


@dataclass(frozen=True)
class MixedLabSegmentSpan:
    index: int
    language: str
    tokens: tuple[str, ...]
    phone_start: int
    phone_end: int


@dataclass(frozen=True)
class MixedLabProvenance:
    """Lightweight timing data retained with one generated mixed Take."""

    segment_languages: tuple[str, ...]
    boundary_seconds: tuple[float, ...]
    selected_attention_head: int


def build_mixed_lab_segment_spans(
    query: AudioQuery,
) -> tuple[MixedLabSegmentSpan, ...]:
    segments = query.voicegerSegments
    if not segments:
        raise ValueError("mixed LAB timing requires voicegerSegments")
    if {segment.language for segment in segments} != {"ja", "en"}:
        raise ValueError("mixed LAB timing requires Japanese and English segments")

    spans: list[MixedLabSegmentSpan] = []
    cursor = 0
    for index, segment in enumerate(segments):
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
            pronunciation = accent_phrases_to_pronunciation(
                query.accent_phrases[start:end],
                terminator=resolve_japanese_segment_terminator(segment),
            )
            tokens = tuple(pronunciation_to_voiceger_tokens(pronunciation))
        else:
            if segment.phonemes is None:
                raise ValueError(
                    "English voicegerSegments require adapter-owned phonemes"
                )
            tokens = tuple(normalize_english_phonemes(segment.phonemes))

        if not tokens:
            raise ValueError(
                f"mixed LAB segment {index} contains no target phones"
            )
        phone_end = cursor + len(tokens)
        spans.append(
            MixedLabSegmentSpan(
                index=index,
                language=segment.language,
                tokens=tokens,
                phone_start=cursor,
                phone_end=phone_end,
            )
        )
        cursor = phone_end
    return tuple(spans)


def voiceger_ids_for_spans(
    spans: tuple[MixedLabSegmentSpan, ...],
    *,
    cleaned_text_to_sequence: Callable,
    version: str,
) -> list[int]:
    """Map adapter tokens with Voiceger's unsupported-token -> UNK rule."""

    unk_id = int(cleaned_text_to_sequence(["UNK"], version)[0])
    result: list[int] = []
    for span in spans:
        for token in span.tokens:
            try:
                token_id = int(cleaned_text_to_sequence([token], version)[0])
            except KeyError:
                token_id = unk_id
            result.append(token_id)
    return result


def _compressed(values: np.ndarray) -> tuple[int, ...]:
    result: list[int] = []
    for value in values:
        item = int(value)
        if not result or result[-1] != item:
            result.append(item)
    return tuple(result)


def _relative_rms_onsets(
    samples: np.ndarray,
    *,
    frame_count: int,
) -> tuple[int, ...]:
    values = np.asarray(samples, dtype=np.float64)
    if values.ndim == 2 and values.shape[1] == 1:
        values = values[:, 0]
    if values.ndim != 1 or values.size == 0:
        raise ValueError("mixed LAB onset audio must be non-empty mono audio")
    if frame_count <= 0 or values.size < frame_count:
        raise ValueError("mixed LAB attention frame count is invalid")

    edges = np.rint(
        np.linspace(0, values.size, frame_count + 1)
    ).astype(np.int64)
    rms = np.empty(frame_count, dtype=np.float64)
    for frame_index in range(frame_count):
        frame = values[edges[frame_index] : edges[frame_index + 1]]
        if frame.size == 0:
            raise ValueError("mixed LAB onset mapping produced an empty frame")
        rms[frame_index] = np.sqrt(np.mean(frame * frame))

    peak = float(rms.max())
    if not np.isfinite(peak) or peak <= 0:
        raise ValueError("mixed LAB onset audio contains no measurable signal")
    floor = max(peak * 1e-12, np.finfo(np.float64).tiny)
    relative_db = 20.0 * np.log10(np.maximum(rms, floor) / peak)

    result: list[int] = []
    for threshold in _ONSET_THRESHOLDS_DB:
        matches = np.flatnonzero(relative_db >= threshold)
        if matches.size == 0:
            raise ValueError(
                f"no speech-onset frame reaches {threshold:g} dB relative RMS"
            )
        result.append(int(matches[0]))
    return tuple(result)


def _transition_frames(
    dominance: np.ndarray,
    *,
    segment_count: int,
    conservative_onset: int,
) -> tuple[int, ...]:
    frame_count = len(dominance)
    frame_indexes = np.arange(frame_count)
    result: list[int] = []
    for to_segment in range(1, segment_count):
        candidates = np.flatnonzero(
            (frame_indexes >= conservative_onset)
            & (dominance == to_segment)
        )
        if candidates.size == 0:
            raise RuntimeError(
                "monotonic MRTE attention head is missing a segment transition"
            )
        frame_index = int(candidates[0])
        if result and frame_index <= result[-1]:
            raise RuntimeError(
                "monotonic MRTE attention transitions are not increasing"
            )
        result.append(frame_index)
    return tuple(result)


def _select_consensus_head(
    dominance: np.ndarray,
    common_heads: set[int],
    *,
    segment_count: int,
    conservative_onset: int,
) -> tuple[int, tuple[int, ...]]:
    transitions = {
        head_index: _transition_frames(
            dominance[head_index],
            segment_count=segment_count,
            conservative_onset=conservative_onset,
        )
        for head_index in sorted(common_heads)
    }
    if len(transitions) == 1:
        head_index = next(iter(transitions))
        return head_index, transitions[head_index]

    vectors = np.asarray(tuple(transitions.values()), dtype=np.int64)
    spread = vectors.max(axis=0) - vectors.min(axis=0)
    if np.any(spread > 1):
        detail = ", ".join(
            f"{head}:{frames}" for head, frames in transitions.items()
        )
        raise RuntimeError(
            "monotonic MRTE attention heads disagree on segment transition "
            f"frames; transitions={{ {detail} }}"
        )

    medians = np.median(vectors, axis=0)
    selected_head = min(
        transitions,
        key=lambda head: (
            float(
                np.abs(
                    np.asarray(transitions[head], dtype=np.float64)
                    - medians
                ).sum()
            ),
            head,
        ),
    )
    return selected_head, transitions[selected_head]


def derive_mixed_lab_provenance(
    spans: tuple[MixedLabSegmentSpan, ...],
    attention: np.ndarray,
    *,
    raw_speech_sample_count: int,
    raw_speech_sampling_rate: int,
    raw_audio,
) -> MixedLabProvenance:
    """Select the unique monotonic attention head and return seam times."""

    if len(spans) < 2:
        raise ValueError("mixed LAB timing requires at least two segments")
    if raw_speech_sample_count <= 0 or raw_speech_sampling_rate <= 0:
        raise ValueError("mixed LAB raw speech timing is invalid")

    values = np.asarray(attention, dtype=np.float64)
    if values.ndim != 4:
        raise ValueError(
            "mixed LAB attention must have [batch, heads, frames, phones]"
        )
    batch, head_count, frame_count, phone_count = values.shape
    if batch != 1 or head_count <= 0 or frame_count <= 0:
        raise ValueError("mixed LAB attention shape is unsupported")
    expected_phone_count = spans[-1].phone_end
    if phone_count != expected_phone_count:
        raise ValueError(
            "mixed LAB attention phone count does not match adapter phones"
        )
    if not np.isfinite(values).all():
        raise ValueError("mixed LAB attention contains non-finite values")

    masses = np.stack(
        [
            np.stack(
                [
                    values[
                        0,
                        head_index,
                        :,
                        span.phone_start : span.phone_end,
                    ].sum(axis=1)
                    for span in spans
                ],
                axis=1,
            )
            for head_index in range(head_count)
        ],
        axis=0,
    )
    smoothed = np.empty_like(masses)
    for head_index in range(head_count):
        for frame_index in range(frame_count):
            start = max(0, frame_index - 2)
            end = min(frame_count, frame_index + 3)
            smoothed[head_index, frame_index] = (
                masses[head_index, start:end].mean(axis=0)
            )

    dominance = np.argmax(smoothed, axis=2)
    audio = np.asarray(raw_audio)
    if audio.ndim == 2 and audio.shape[1] == 1:
        audio = audio[:, 0]
    if audio.ndim != 1:
        raise ValueError("mixed LAB raw Voiceger audio must be mono")
    if len(audio) < raw_speech_sample_count:
        raise ValueError("mixed LAB raw speech exceeds returned Voiceger audio")
    onset_frames = _relative_rms_onsets(
        audio[:raw_speech_sample_count],
        frame_count=frame_count,
    )

    expected_path = tuple(range(len(spans)))
    matching_sets: list[set[int]] = []
    for onset_frame in onset_frames:
        matching = {
            head_index
            for head_index in range(head_count)
            if _compressed(dominance[head_index, onset_frame:])
            == expected_path
        }
        matching_sets.append(matching)

    common = set(range(head_count))
    for matching in matching_sets:
        common.intersection_update(matching)
    if not common:
        candidates = [tuple(sorted(items)) for items in matching_sets]
        raise RuntimeError(
            "no monotonic MRTE attention head survives every speech-onset "
            f"threshold; candidates={candidates}"
        )

    conservative_onset = max(onset_frames)
    selected_head, transition_frames = _select_consensus_head(
        dominance,
        common,
        segment_count=len(spans),
        conservative_onset=conservative_onset,
    )
    samples_per_frame = raw_speech_sample_count / frame_count
    boundary_seconds: list[float] = []
    previous_sample = 0

    for frame_index in transition_frames:
        sample_index = int(round(frame_index * samples_per_frame))
        if (
            sample_index <= previous_sample
            or sample_index >= raw_speech_sample_count
        ):
            raise RuntimeError(
                "mixed LAB attention boundaries are not strictly increasing"
            )
        boundary_seconds.append(sample_index / raw_speech_sampling_rate)
        previous_sample = sample_index

    return MixedLabProvenance(
        segment_languages=tuple(span.language for span in spans),
        boundary_seconds=tuple(boundary_seconds),
        selected_attention_head=selected_head,
    )
