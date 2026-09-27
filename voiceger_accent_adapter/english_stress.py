"""Validation helpers for Voiceger's English ARPAbet tokens."""

from __future__ import annotations

from collections.abc import Sequence
from typing import List


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
