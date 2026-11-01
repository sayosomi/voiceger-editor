"""Atomic JA-section→EN ARPAbet conversion over canonical AudioQuery."""

from __future__ import annotations

from .japanese_arpabet import (
    flatten_arpabet_groups,
    pronunciation_to_arpabet_groups,
)
from .pronunciation import parse_pronunciation
from .query_editing import (
    _validate_japanese_references,
    _replace_pitch_events,
    japanese_pronunciation,
)
from .voicevox_api_models import (
    AudioQuery,
    EnglishPhonemeGroupBoundary,
    VoicegerSegment,
)


def convert_japanese_section_to_arpabet(
    query: AudioQuery,
    pronunciation: str,
    *,
    segment_index: int | None = None,
    pure_japanese_utterance_text: str | None = None,
) -> AudioQuery:
    """Return converted query; never mutate source on error.

    `pronunciation` is the current Japanese editor draft, not text G2P.
    The original spoken section text is retained for runtime override matching.
    """

    if not isinstance(query, AudioQuery):
        raise TypeError("query must be an AudioQuery")
    if not isinstance(pronunciation, str) or not pronunciation.strip():
        raise ValueError("Japanese pronunciation draft must not be empty")
    parsed = parse_pronunciation(pronunciation)
    groups = pronunciation_to_arpabet_groups(parsed)
    phonemes = list(flatten_arpabet_groups(groups))
    boundaries = [
        EnglishPhonemeGroupBoundary(label=group.label, count=len(group.phonemes))
        for group in groups
    ]

    if query.voicegerSegments is None:
        if segment_index is not None:
            raise ValueError("pure Japanese conversion does not accept segment_index")
        source_text = pure_japanese_utterance_text
        if not isinstance(source_text, str) or not source_text.strip():
            raise ValueError("pure Japanese section source text is required")
        if "\n" in source_text or "\r" in source_text:
            raise ValueError("section source text must be a single line")
        if not query.accent_phrases:
            raise ValueError("Japanese query has no accent phrases")
        updated = query.model_copy(deep=True)
        updated.voicegerSegments = [
            VoicegerSegment(
                language="en",
                text=source_text,
                phonemes=phonemes,
                englishGroups=boundaries,
            )
        ]
        updated.accent_phrases = []
        updated.pronunciationPitchEvents = None
        updated.pronunciationPunctuation = None
        updated.kana = None
        return updated

    if type(segment_index) is not int or not 0 <= segment_index < len(query.voicegerSegments):
        raise ValueError("selected Japanese segment is out of range")
    _validate_japanese_references(query)
    original = query.voicegerSegments[segment_index]
    if original.language != "ja":
        raise ValueError("selected segment is not Japanese")
    start, count = original.accentPhraseStart, original.accentPhraseCount
    assert start is not None and count is not None

    updated = query.model_copy(deep=True)
    updated.accent_phrases = (
        updated.accent_phrases[:start]
        + updated.accent_phrases[start + count:]
    )
    _replace_pitch_events(updated, start=start, old_count=count, new_count=0)
    assert updated.voicegerSegments is not None
    updated.voicegerSegments[segment_index] = VoicegerSegment(
        language="en",
        text=original.text,
        phonemes=phonemes,
        englishGroups=boundaries,
    )
    next_offset = 0
    for segment in updated.voicegerSegments:
        if segment.language == "ja":
            segment.accentPhraseStart = next_offset
            assert segment.accentPhraseCount is not None
            next_offset += segment.accentPhraseCount
    updated.kana = None
    return updated
