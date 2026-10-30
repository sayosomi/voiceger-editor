"""Frontend-neutral user-dictionary pronunciation and preview helpers."""
from __future__ import annotations

from typing import Sequence
from .english_stress import normalize_english_phonemes
from .openjtalk_dictionary import expand_word_type
from .pronunciation import AccentPhrase as CoreAccentPhrase, PitchEvent, Pronunciation, format_pronunciation, parse_pronunciation
from .user_dictionary import JapaneseWordType
from .voicevox_api_models import AccentPhrase, AudioQuery, JapanesePitchEvent, Mora, PronunciationPitchEvents, VoicegerSegment

_WORD_TYPES = tuple(JapaneseWordType)

def _katakana_notation(value: str) -> str:
    """Normalize editable Japanese kana without changing pitch markers or punctuation."""
    return "".join(
        chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char
        for char in value
    )


def _reading_morae(reading: str) -> tuple[str, ...]:
    if "'" in reading or "/" in reading or any(ch in reading for ch in "。？！"):
        raise ValueError("Dictionary pronunciation must be one kana reading")
    parsed = parse_pronunciation(reading + "'")
    if len(parsed.phrases) != 1:
        raise ValueError("Dictionary pronunciation must contain one accent phrase")
    return parsed.phrases[0].morae


def _word_type_for_context(context_id: int) -> JapaneseWordType:
    for word_type in _WORD_TYPES:
        if expand_word_type(word_type.value)["context_id"] == context_id:
            return word_type
    raise ValueError(f"Unsupported Japanese dictionary word type context: {context_id}")


def _japanese_preview_query(
    morae: Sequence[str], accent: int, events: Sequence[PitchEvent] = (),
) -> AudioQuery:
    if not morae:
        raise ValueError("Japanese pronunciation must not be empty")
    preview_accent = accent if accent > 0 else len(morae)
    if events:
        CoreAccentPhrase(tuple(morae), preview_accent, tuple(events))
    return AudioQuery(
        accent_phrases=[
            AccentPhrase(
                moras=[Mora(text=mora, vowel="") for mora in morae],
                accent=preview_accent,
            )
        ],
        kana=None,
        pronunciationPitchEvents=[
            PronunciationPitchEvents(
                accentPhraseIndex=0,
                events=[JapanesePitchEvent(afterMora=e.after_mora, symbol=e.symbol) for e in events],
            )
        ] if events else None,
    )


def _english_preview_query(surface: str, phonemes: Sequence[str]) -> AudioQuery:
    if not surface.strip():
        raise ValueError("English dictionary Surface must not be empty")
    normalized = normalize_english_phonemes(phonemes)
    return AudioQuery(
        accent_phrases=[],
        voicegerSegments=[
            VoicegerSegment(
                language="en",
                text=surface,
                phonemes=normalized,
            )
        ],
    )



def japanese_word_notation(word, events=()):
    """Render an editable single-phrase reading, including saved multi-peaks."""
    morae = _reading_morae(word.pronunciation)
    phrase = CoreAccentPhrase(morae, word.accent_type or len(morae), tuple(events) or None)
    return format_pronunciation(Pronunciation(phrases=(phrase,)))


def parse_japanese_word(notation, *, opening=None, existing=None, pitch_events=()):
    """Validate a dictionary word, preserving an untouched legacy accent zero."""
    if not isinstance(notation, str) or not notation or len(notation) > 2000:
        raise ValueError("invalid Japanese pronunciation")
    if existing is not None and notation == opening:
        return existing.pronunciation, existing.accent_type, tuple(pitch_events)
    if any(ch.isspace() for ch in notation):
        raise ValueError("dictionary word must have one accent phrase")
    parsed = parse_pronunciation(_katakana_notation(notation))
    if len(parsed.items) != 1 or len(parsed.phrases) != 1:
        raise ValueError("dictionary word must have one accent phrase without punctuation")
    phrase = parsed.phrases[0]
    return phrase.reading, phrase.accent, tuple(phrase.pitch_events or ())
