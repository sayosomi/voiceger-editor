"""Validation helpers for Voiceger's English ARPAbet tokens."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import List, Optional, Tuple


_VOWELS = frozenset(
    {
        "AA",
        "AE",
        "AH",
        "AO",
        "AW",
        "AY",
        "EH",
        "ER",
        "EY",
        "IH",
        "IY",
        "OW",
        "OY",
        "UH",
        "UW",
    }
)
_CONSONANTS = frozenset(
    {
        "B",
        "CH",
        "D",
        "DH",
        "F",
        "G",
        "HH",
        "JH",
        "K",
        "L",
        "M",
        "N",
        "NG",
        "P",
        "R",
        "S",
        "SH",
        "T",
        "TH",
        "V",
        "W",
        "Y",
        "Z",
        "ZH",
    }
)
_PUNCTUATION = frozenset({"!", "?", "…", ",", ".", "-", "UNK"})
_STRESSED_VOWELS = frozenset(
    f"{vowel}{stress}"
    for vowel in _VOWELS
    for stress in (0, 1, 2)
)
_ALLOWED = _CONSONANTS | _STRESSED_VOWELS | {"ER", "IH"} | _PUNCTUATION


@dataclass(frozen=True)
class EnglishPhonemeEditorState:
    """Stress-free ARPAbet tokens and stress values in vowel order.

    ``vowel_stresses`` is indexed by vowel position, not by phoneme position.
    ``None`` is reserved for the legacy unmarked ``ER`` and ``IH`` tokens
    accepted by :func:`normalize_english_phonemes`.
    """

    base_phonemes: Tuple[str, ...]
    vowel_stresses: Tuple[Optional[int], ...]

    @property
    def primary_stress_vowel_positions(self) -> Tuple[int, ...]:
        """Return every vowel position that currently has primary stress."""

        return tuple(
            position
            for position, stress in enumerate(self.vowel_stresses)
            if stress == 1
        )

    @property
    def secondary_stress_vowel_positions(self) -> Tuple[int, ...]:
        """Return every vowel position that currently has secondary stress."""

        return tuple(
            position
            for position, stress in enumerate(self.vowel_stresses)
            if stress == 2
        )


def normalize_english_phonemes(phonemes: Sequence[str]) -> List[str]:
    """Validate and canonicalize editable Voiceger English phonemes."""

    if not phonemes:
        raise ValueError("English phonemes must not be empty")

    result: List[str] = []
    for raw in phonemes:
        if not isinstance(raw, str):
            raise ValueError("English phonemes must be strings")

        token = raw.strip()
        if not token:
            raise ValueError("English phonemes must not contain empty tokens")

        if token not in _PUNCTUATION:
            token = token.upper()

        if token not in _ALLOWED:
            raise ValueError(f"unsupported English phoneme: {raw!r}")

        result.append(token)

    return result


def english_phonemes_to_editor_state(
    phonemes: Sequence[str],
) -> EnglishPhonemeEditorState:
    """Convert Voiceger's stressed ARPAbet tokens to a UI-neutral state."""

    normalized = normalize_english_phonemes(phonemes)
    base_phonemes: List[str] = []
    vowel_stresses: List[Optional[int]] = []

    for token in normalized:
        if token in _STRESSED_VOWELS:
            base_phonemes.append(token[:-1])
            vowel_stresses.append(int(token[-1]))
        elif token in _VOWELS:
            # normalize_english_phonemes currently accepts unmarked ER and IH.
            base_phonemes.append(token)
            vowel_stresses.append(None)
        else:
            base_phonemes.append(token)

    return EnglishPhonemeEditorState(
        base_phonemes=tuple(base_phonemes),
        vowel_stresses=tuple(vowel_stresses),
    )


def editor_state_to_english_phonemes(
    state: EnglishPhonemeEditorState,
) -> List[str]:
    """Rebuild valid Voiceger ARPAbet tokens from editor state."""

    if not isinstance(state, EnglishPhonemeEditorState):
        raise ValueError("English editor state has an invalid type")

    raw_base_phonemes = state.base_phonemes
    raw_vowel_stresses = state.vowel_stresses
    if isinstance(raw_base_phonemes, (str, bytes)) or not isinstance(
        raw_base_phonemes, Sequence
    ):
        raise ValueError("English editor base phonemes must be a sequence")
    if isinstance(raw_vowel_stresses, (str, bytes)) or not isinstance(
        raw_vowel_stresses, Sequence
    ):
        raise ValueError("English editor vowel stresses must be a sequence")
    if not raw_base_phonemes:
        raise ValueError("English phonemes must not be empty")

    base_phonemes: List[str] = []
    vowel_count = 0
    for raw in raw_base_phonemes:
        if not isinstance(raw, str):
            raise ValueError("English editor base phonemes must be strings")

        token = raw.strip()
        if not token:
            raise ValueError("English editor base phonemes must not be empty")
        if token not in _PUNCTUATION:
            token = token.upper()

        if token in _VOWELS:
            vowel_count += 1
        elif token not in _CONSONANTS and token not in _PUNCTUATION:
            raise ValueError(f"unsupported English phoneme: {raw!r}")
        base_phonemes.append(token)

    if len(raw_vowel_stresses) != vowel_count:
        raise ValueError("English editor vowel stresses must match its vowels")

    vowel_stresses: List[Optional[int]] = []
    for stress in raw_vowel_stresses:
        if stress is None:
            vowel_stresses.append(None)
        elif type(stress) is int and stress in (0, 1, 2):
            vowel_stresses.append(stress)
        else:
            raise ValueError("English editor stress values must be 0, 1, 2, or None")

    result: List[str] = []
    vowel_position = 0
    for token in base_phonemes:
        if token in _VOWELS:
            stress = vowel_stresses[vowel_position]
            vowel_position += 1
            if stress is None:
                if token not in {"ER", "IH"}:
                    raise ValueError(
                        "only legacy ER and IH vowels may have unspecified stress"
                    )
                result.append(token)
            else:
                result.append(f"{token}{stress}")
        else:
            result.append(token)

    return normalize_english_phonemes(result)


def replace_editor_base_phonemes(
    state: EnglishPhonemeEditorState,
    base_phonemes: Sequence[str],
) -> EnglishPhonemeEditorState:
    """Replace stress-free phonemes while keeping stress by vowel ordinal."""

    # Validate hand-built states through the same canonical conversion used by
    # all editor operations before carrying their stress into the new sequence.
    validated_state = english_phonemes_to_editor_state(
        editor_state_to_english_phonemes(state)
    )

    if isinstance(base_phonemes, (str, bytes)) or not isinstance(
        base_phonemes, Sequence
    ):
        raise ValueError("English base phonemes must be a sequence")
    if not base_phonemes:
        raise ValueError("English phonemes must not be empty")

    normalized: List[str] = []
    new_vowels: List[str] = []
    for raw in base_phonemes:
        if not isinstance(raw, str):
            raise ValueError("English base phonemes must be strings")

        token = raw.strip()
        if not token:
            raise ValueError("English base phonemes must not contain empty tokens")
        if token not in _PUNCTUATION:
            token = token.upper()

        unstressed_base = token.rstrip("012")
        if token != unstressed_base and unstressed_base in _VOWELS:
            raise ValueError("English base phonemes must not include stress digits")
        if token in _VOWELS:
            new_vowels.append(token)
        elif token not in _CONSONANTS and token not in _PUNCTUATION:
            raise ValueError(f"unsupported English phoneme: {raw!r}")
        normalized.append(token)

    vowel_stresses: List[Optional[int]] = []
    old_stresses = validated_state.vowel_stresses
    for position, vowel in enumerate(new_vowels):
        if position >= len(old_stresses):
            vowel_stresses.append(0)
            continue

        stress = old_stresses[position]
        # Legacy unmarked ER/IH can keep their unspecified status only while
        # the replacement ordinal is still one of those legacy vowels.
        if stress is None and vowel not in {"ER", "IH"}:
            stress = 0
        vowel_stresses.append(stress)

    replacement = EnglishPhonemeEditorState(
        base_phonemes=tuple(normalized),
        vowel_stresses=tuple(vowel_stresses),
    )
    return english_phonemes_to_editor_state(
        editor_state_to_english_phonemes(replacement)
    )


def move_primary_stress(
    state: EnglishPhonemeEditorState,
    source_vowel_position: int,
    target_vowel_position: int,
) -> EnglishPhonemeEditorState:
    """Move one primary marker between vowel positions in an English segment."""

    # Reuse the canonical parser and validator so hand-built editor states are
    # checked against the same ARPAbet contract as converted G2P output.
    validated_state = english_phonemes_to_editor_state(
        editor_state_to_english_phonemes(state)
    )

    for name, position in (
        ("source", source_vowel_position),
        ("target", target_vowel_position),
    ):
        if type(position) is not int or not 0 <= position < len(
            validated_state.vowel_stresses
        ):
            raise ValueError(f"{name} vowel position is out of range")

    if source_vowel_position == target_vowel_position:
        raise ValueError("source and target must be different vowel positions")
    if validated_state.vowel_stresses[source_vowel_position] != 1:
        raise ValueError("source vowel does not have primary stress")

    vowel_stresses = list(validated_state.vowel_stresses)
    source_stress = vowel_stresses[source_vowel_position]
    target_stress = vowel_stresses[target_vowel_position]
    vowel_bases = [
        token for token in validated_state.base_phonemes if token in _VOWELS
    ]
    if target_stress is None and vowel_bases[source_vowel_position] not in {
        "ER",
        "IH",
    }:
        # The legacy bare ER/IH representation has no digit to swap back to
        # an ordinary vowel, so use its unstressed equivalent there.
        target_stress = 0
    vowel_stresses[source_vowel_position] = target_stress
    vowel_stresses[target_vowel_position] = source_stress

    return EnglishPhonemeEditorState(
        base_phonemes=validated_state.base_phonemes,
        vowel_stresses=tuple(vowel_stresses),
    )
