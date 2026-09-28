"""UI-neutral pronunciation editing operations for AudioQuery values."""

from __future__ import annotations

from collections.abc import Sequence

from .english_stress import (
    EnglishPhonemeEditorState,
    editor_state_to_english_phonemes,
    english_phonemes_to_editor_state,
    move_primary_stress,
    normalize_english_phonemes,
    replace_editor_base_phonemes,
)
from .pronunciation import (
    Pronunciation,
    format_pronunciation,
    parse_pronunciation,
)
from .mixed_language import resolve_japanese_segment_terminator
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


def _pure_japanese_terminator(query: AudioQuery) -> str | None:
    # Keep notation edits aligned with the terminator rule used for synthesis.
    return _query_terminator(query)


def _parse_replacement(pronunciation: str) -> Pronunciation:
    if not isinstance(pronunciation, str):
        raise ValueError("pronunciation must be a string")
    return parse_pronunciation(pronunciation)


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
        terminator=resolve_japanese_segment_terminator(segment),
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
        parsed = _parse_replacement(pronunciation)
        updated = query.model_copy(deep=True)
        updated.accent_phrases = pronunciation_to_accent_phrases(parsed)
        updated.kana = format_pronunciation(parsed)
        return updated

    parsed = _parse_replacement(pronunciation)
    start = segment.accentPhraseStart
    count = segment.accentPhraseCount
    assert start is not None and count is not None

    updated = query.model_copy(deep=True)
    updated.accent_phrases = (
        updated.accent_phrases[:start]
        + pronunciation_to_accent_phrases(parsed)
        + updated.accent_phrases[start + count :]
    )
    assert updated.voicegerSegments is not None
    updated.voicegerSegments[segment_index].pronunciationTerminator = (
        parsed.terminator or ""
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


def japanese_preview_query(
    query: AudioQuery,
    pronunciation: str,
    *,
    segment_index: int | None = None,
) -> AudioQuery:
    """Return a query that previews only the selected Japanese segment.

    Pure Japanese input previews its whole utterance. For a mixed query, the
    selected segment is first edited with the canonical Japanese replacement
    semantics, then its resulting phrases are isolated into a pure Japanese
    query. The input and every unrelated segment remain untouched.
    """

    updated = replace_japanese_pronunciation(
        query,
        pronunciation,
        segment_index=segment_index,
    )
    if segment_index is None:
        return updated

    assert updated.voicegerSegments is not None
    segment = updated.voicegerSegments[segment_index]
    start = segment.accentPhraseStart
    count = segment.accentPhraseCount
    assert start is not None and count is not None
    phrases = updated.accent_phrases[start : start + count]
    pronunciation_value = accent_phrases_to_pronunciation(
        phrases,
        terminator=resolve_japanese_segment_terminator(segment),
    )

    preview = updated.model_copy(deep=True)
    preview.accent_phrases = preview.accent_phrases[start : start + count]
    preview.voicegerSegments = None
    preview.kana = format_pronunciation(pronunciation_value)
    return preview


def _japanese_phrase_range(
    query: AudioQuery,
    *,
    segment_index: int | None,
) -> tuple[int, int]:
    segment = _japanese_mode_segment(query, segment_index)
    if segment is None:
        return 0, len(query.accent_phrases)
    start = segment.accentPhraseStart
    count = segment.accentPhraseCount
    assert start is not None and count is not None
    return start, count


def _refresh_pure_japanese_kana(query: AudioQuery) -> None:
    if query.voicegerSegments is not None:
        query.kana = None
        return
    pronunciation = accent_phrases_to_pronunciation(
        query.accent_phrases,
        terminator=_pure_japanese_terminator(query),
    )
    query.kana = format_pronunciation(pronunciation)


def move_japanese_accent(
    query: AudioQuery,
    *,
    accent_phrase_index: int,
    direction: int,
    segment_index: int | None = None,
) -> AudioQuery:
    """Move one Japanese phrase accent by one mora in a copied query.

    At a phrase boundary this returns the original query unchanged. For mixed
    queries, ``accent_phrase_index`` is still the global AudioQuery phrase
    index, while ``segment_index`` proves that the phrase belongs to the
    selected Japanese segment.
    """

    _validate_query(query)
    if type(direction) is not int or direction not in {-1, 1}:
        raise ValueError("direction must be -1 or 1")
    start, count = _japanese_phrase_range(query, segment_index=segment_index)
    if type(accent_phrase_index) is not int:
        raise ValueError("accent_phrase_index must be an integer")
    if not start <= accent_phrase_index < start + count:
        raise ValueError("accent phrase is outside the selected Japanese segment")

    phrase = query.accent_phrases[accent_phrase_index]
    updated_accent = phrase.accent + direction
    if not 1 <= updated_accent <= len(phrase.moras):
        return query

    updated = query.model_copy(deep=True)
    updated.accent_phrases[accent_phrase_index].accent = updated_accent
    _refresh_pure_japanese_kana(updated)
    return updated


def replace_japanese_accent_phrase(
    query: AudioQuery,
    *,
    accent_phrase_index: int,
    morae: Sequence[str],
    accent: int,
    segment_index: int | None = None,
) -> AudioQuery:
    """Replace one phrase's reading while preserving phrase and segment structure."""

    _validate_query(query)
    start, count = _japanese_phrase_range(query, segment_index=segment_index)
    if type(accent_phrase_index) is not int:
        raise ValueError("accent_phrase_index must be an integer")
    if not start <= accent_phrase_index < start + count:
        raise ValueError("accent phrase is outside the selected Japanese segment")
    if isinstance(morae, (str, bytes)) or not isinstance(morae, Sequence):
        raise ValueError("morae must be a sequence of complete mora tokens")
    tokens = tuple(morae)
    if not tokens or any(not isinstance(token, str) or not token for token in tokens):
        raise ValueError("morae must contain non-empty complete mora tokens")
    if type(accent) is not int or not 1 <= accent <= len(tokens):
        raise ValueError("accent must point to a mora in the phrase")

    # Validate that the caller supplied complete morae (so キョ is one token,
    # and キ / ョ cannot accidentally become separate editable units).
    notation = "".join(
        token + ("'" if index == accent else "")
        for index, token in enumerate(tokens, start=1)
    )
    parsed = _parse_replacement(notation)
    if len(parsed.phrases) != 1 or parsed.phrases[0].morae != tokens:
        raise ValueError("morae must contain complete mora tokens")

    replacement = pronunciation_to_accent_phrases(parsed)[0]
    old_phrase = query.accent_phrases[accent_phrase_index]
    replacement.pause_mora = (
        old_phrase.pause_mora.model_copy(deep=True)
        if old_phrase.pause_mora
        else None
    )
    replacement.is_interrogative = old_phrase.is_interrogative

    updated = query.model_copy(deep=True)
    updated.accent_phrases[accent_phrase_index] = replacement
    _refresh_pure_japanese_kana(updated)
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


def english_word_preview_query(
    query: AudioQuery,
    *,
    segment_index: int,
    group_index: int,
    phoneme_groups: Sequence[Sequence[str]],
    draft_phonemes: Sequence[str],
) -> AudioQuery:
    """Return an English-only query for one segment with a word draft applied.

    ``phoneme_groups`` is the caller's current transient grouping of the
    canonical English segment. Only the selected group's phonemes are
    replaced; the other groups are copied verbatim into the resulting segment.
    """

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
    if isinstance(phoneme_groups, (str, bytes)) or not isinstance(
        phoneme_groups, Sequence
    ) or not phoneme_groups:
        raise ValueError("English phoneme groups must be a non-empty sequence")
    if type(group_index) is not int or not 0 <= group_index < len(phoneme_groups):
        raise ValueError("group_index is out of range")

    groups: list[tuple[str, ...]] = []
    flattened: list[str] = []
    for group in phoneme_groups:
        if isinstance(group, (str, bytes)) or not isinstance(group, Sequence):
            raise ValueError("each English phoneme group must be a sequence")
        values = tuple(group)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("English phoneme groups must contain strings")
        groups.append(values)
        flattened.extend(values)
    if tuple(flattened) != tuple(segment.phonemes):
        raise ValueError("English phoneme groups do not match the selected segment")
    if isinstance(draft_phonemes, (str, bytes)) or not isinstance(
        draft_phonemes, Sequence
    ):
        raise ValueError("draft_phonemes must be a sequence")
    replacement = tuple(normalize_english_phonemes(draft_phonemes))
    groups[group_index] = replacement

    updated = replace_english_phoneme_groups(
        query,
        segment_index=segment_index,
        phoneme_groups=tuple(groups),
    )
    assert updated.voicegerSegments is not None
    preview = updated.model_copy(deep=True)
    preview.accent_phrases = []
    preview.voicegerSegments = [
        preview.voicegerSegments[segment_index].model_copy(deep=True)
    ]
    preview.kana = None
    return preview


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
