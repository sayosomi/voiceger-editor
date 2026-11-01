"""Stable, validated English phoneme grouping for JA-origin sections.

The canonical phoneme sequence remains the only source for phoneme values.
Durable boundaries contain labels and counts only, never duplicate tokens.
"""

from __future__ import annotations

from .voicevox_api_models import (
    EnglishPhonemeGroupBoundary,
    VoicegerSegment,
)


def bound_english_groups(
    segment: VoicegerSegment,
) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    """Split a canonical EN sequence using explicit durable JA-origin boundaries."""

    if segment.englishGroups is None:
        return None
    if segment.language != "en" or segment.phonemes is None:
        raise ValueError("English group metadata requires an EN phoneme segment")
    if not segment.englishGroups:
        raise ValueError("English group boundaries must not be empty")
    groups: list[tuple[str, tuple[str, ...]]] = []
    offset = 0
    for entry in segment.englishGroups:
        if not isinstance(entry, EnglishPhonemeGroupBoundary):
            raise ValueError("English group boundaries contain invalid entries")
        if not entry.label.strip() or "\n" in entry.label or "\r" in entry.label:
            raise ValueError("English group label is invalid")
        end = offset + entry.count
        if end > len(segment.phonemes):
            raise ValueError("English group boundaries exceed the phoneme sequence")
        groups.append((entry.label, tuple(segment.phonemes[offset:end])))
        offset = end
    if offset != len(segment.phonemes):
        raise ValueError("English group boundaries do not cover all phonemes")
    return tuple(groups)
