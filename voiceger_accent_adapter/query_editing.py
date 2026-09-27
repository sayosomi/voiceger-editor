"""UI-neutral pronunciation editing operations for AudioQuery values."""

from __future__ import annotations

from collections.abc import Sequence

from .english_stress import (
    EnglishPhonemeEditorState,
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    replace_editor_base_phonemes,
)
from .pronunciation import (
    Pronunciation,
    format_pronunciation,
    parse_pronunciation,
)
from .synthesis import _query_terminator
from .voicevox_api_models import AudioQuery, VoicegerSegment
from .voicevox_query import (
    accent_phrases_to_pronunciation,
    pronunciation_to_accent_phrases,
)


def _validate_query(query: AudioQuery) -> None:
    if not isinstance(query, AudioQuery):
        raise TypeError("query must be an AudioQuery instance")


def _validate_segment_index(index: int, segment_count: int) -> None:
    if type(index) is not int:
        raise ValueError("segment_index must be an integer")
    if not 0 <= index < segment_count:
        raise ValueError("segment_index is out of range")


def _japanese_mode_segment(
    query: AudioQuery,
    segment_index: int | None,
) -> VoicegerSegment | None:
    segments = query.voicegerSegments
    if segments is None:
        if segment_index is not None:
            raise ValueError("pure Japanese queries do not accept segment_index")
        return None

    if segment_index is None:
        raise ValueError("mixed queries require segment_index")
    _validate_segment_index(segment_index, len(segments))
    segment = segments[segment_index]
    if segment.language != "ja":
        raise ValueError("selected segment is not Japanese")
    _validate_japanese_references(query)
    return segment


def _validate_japanese_references(query: AudioQuery) -> None:
    segments = query.voicegerSegments
    if segments is None:
        raise ValueError("mixed queries require voicegerSegments")

    next_offset = 0
    for segment in segments:
        if segment.language != "ja":
            continue

        start = segment.accentPhraseStart
        count = segment.accentPhraseCount
        if type(start) is not int or type(count) is not int or count <= 0:
            raise ValueError("Japanese segments require valid accent phrase references")
        if start != next_offset:
            raise ValueError("Japanese accent phrase references must be contiguous")

        end = start + count
        if end > len(query.accent_phrases):
            raise ValueError("Japanese accent phrase reference is out of bounds")
        next_offset = end

    if next_offset != len(query.accent_phrases):
        raise ValueError("Japanese references must cover all accent phrases")


def _pure_japanese_terminator(query: AudioQuery) -> str:
    # Keep notation edits aligned with the terminator rule used for synthesis.
    return _query_terminator(query)


def _segment_japanese_terminator(segment_text: str) -> str | None:
    if segment_text.endswith(("？", "?")):
        return "？"
    if segment_text.endswith(("。", "！", "!")):
        return "。"
    return None


def _require_terminator(
    pronunciation: Pronunciation,
    expected: str | None,
) -> None:
    if pronunciation.terminator != expected:
        raise ValueError("replacement pronunciation must preserve its terminator")


def _parse_replacement(
    pronunciation: str,
    *,
    expected_terminator: str | None,
) -> Pronunciation:
    if not isinstance(pronunciation, str):
        raise ValueError("pronunciation must be a string")
    parsed = parse_pronunciation(pronunciation)
    _require_terminator(parsed, expected_terminator)
    return parsed


def japanese_pronunciation(
    query: AudioQuery,
    *,
    segment_index: int | None = None,
) -> str:
    """Render the editable Japanese notation for a pure or mixed query."""

    _validate_query(query)
    segment = _japanese_mode_segment(query, segment_index)
    if segment is None:
        pronunciation = accent_phrases_to_pronunciation(
            query.accent_phrases,
            terminator=_pure_japanese_terminator(query),
        )
        return format_pronunciation(pronunciation)

    start = segment.accentPhraseStart
    count = segment.accentPhraseCount
    assert start is not None and count is not None
    pronunciation = accent_phrases_to_pronunciation(
        query.accent_phrases[start : start + count],
        terminator=_segment_japanese_terminator(segment.text),
    )
    return format_pronunciation(pronunciation)


def replace_japanese_pronunciation(
    query: AudioQuery,
    pronunciation: str,
    *,
    segment_index: int | None = None,
) -> AudioQuery:
    """Return a deep-copied query with the selected Japanese notation replaced."""

    _validate_query(query)
    segment = _japanese_mode_segment(query, segment_index)
    if segment is None:
        expected_terminator = _pure_japanese_terminator(query)
        parsed = _parse_replacement(
            pronunciation,
            expected_terminator=expected_terminator,
        )
        updated = query.model_copy(deep=True)
        updated.accent_phrases = pronunciation_to_accent_phrases(parsed)
        updated.kana = format_pronunciation(parsed)
        return updated

    expected_terminator = _segment_japanese_terminator(segment.text)
    parsed = _parse_replacement(
        pronunciation,
        expected_terminator=expected_terminator,
    )
    start = segment.accentPhraseStart
    count = segment.accentPhraseCount
    assert start is not None and count is not None

    updated = query.model_copy(deep=True)
    updated.accent_phrases = (
        updated.accent_phrases[:start]
        + pronunciation_to_accent_phrases(parsed)
        + updated.accent_phrases[start + count :]
    )

    next_offset = 0
    for index, updated_segment in enumerate(updated.voicegerSegments or []):
        if updated_segment.language != "ja":
            continue
        updated_segment.accentPhraseStart = next_offset
        if index == segment_index:
            updated_segment.accentPhraseCount = len(parsed.phrases)
        segment_count = updated_segment.accentPhraseCount
        assert segment_count is not None
        next_offset += segment_count

    updated.kana = None
    return updated


def english_editor_state(
    query: AudioQuery,
    *,
    segment_index: int,
) -> EnglishPhonemeEditorState:
    """Return a validated stress-free editor state for one English segment."""

    _validate_query(query)
    segments = query.voicegerSegments
    if segments is None:
        raise ValueError("English editing requires voicegerSegments")
    _validate_segment_index(segment_index, len(segments))

    segment = segments[segment_index]
    if segment.language != "en":
        raise ValueError("selected segment is not English")
    if segment.phonemes is None:
        raise ValueError("selected English segment has no phonemes")
    return english_phonemes_to_editor_state(segment.phonemes)


def replace_english_editor_state(
    query: AudioQuery,
    *,
    segment_index: int,
    state: EnglishPhonemeEditorState,
) -> AudioQuery:
    """Return a deep-copied query with one English editor state applied."""

    english_editor_state(query, segment_index=segment_index)
    replacement_phonemes = editor_state_to_english_phonemes(state)

    updated = query.model_copy(deep=True)
    assert updated.voicegerSegments is not None
    updated.voicegerSegments[segment_index].phonemes = replacement_phonemes
    return updated


def replace_english_base_phonemes(
    query: AudioQuery,
    *,
    segment_index: int,
    base_phonemes: Sequence[str],
) -> AudioQuery:
    """Replace stress-free English phonemes while retaining stress by ordinal."""

    state = english_editor_state(query, segment_index=segment_index)
    replacement_state = replace_editor_base_phonemes(state, base_phonemes)
    return replace_english_editor_state(
        query,
        segment_index=segment_index,
        state=replacement_state,
    )


def replace_english_phoneme_groups(
    query: AudioQuery,
    *,
    segment_index: int,
    phoneme_groups: Sequence[Sequence[str]],
) -> AudioQuery:
    """Apply a completed transient word grouping to one flat query segment.

    Group boundaries belong to the caller's editing session; AudioQuery keeps
    only its canonical flat Voiceger phoneme sequence.
    """

    english_editor_state(query, segment_index=segment_index)
    if isinstance(phoneme_groups, (str, bytes)) or not isinstance(
        phoneme_groups, Sequence
    ) or not phoneme_groups:
        raise ValueError("English phoneme groups must be a non-empty sequence")

    flattened: list[str] = []
    for group in phoneme_groups:
        if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
            raise ValueError("each English phoneme group must be a sequence")
        flattened.extend(group)

    replacement_state = english_phonemes_to_editor_state(flattened)
    return replace_english_editor_state(
        query,
        segment_index=segment_index,
        state=replacement_state,
    )


def move_english_primary_stress(
    query: AudioQuery,
    *,
    segment_index: int,
    source_vowel_position: int,
    target_vowel_position: int,
) -> AudioQuery:
    """Move one selected primary marker in a copied English query segment."""

    state = english_editor_state(query, segment_index=segment_index)
    moved_state = move_primary_stress(
        state,
        source_vowel_position,
        target_vowel_position,
    )
    return replace_english_editor_state(
        query,
        segment_index=segment_index,
        state=moved_state,
    )
