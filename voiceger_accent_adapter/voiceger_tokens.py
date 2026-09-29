"""Convert editable pronunciation to Voiceger Japanese frontend tokens.

This layer is intentionally independent of Voiceger's source tree. It uses
pyopenjtalk only for mora-to-phoneme conversion and inserts the Japanese
prosody symbols produced by Voiceger's own OpenJTalk path.

Important: these are tokens returned at the `text.japanese.g2p()` hook point,
not the model's final symbol IDs. Voiceger v2's downstream `clean_text()`
preserves "[" and "]" and converts the OpenJTalk accent-phrase boundary "#"
to "UNK". To reproduce Voiceger's normal frontend semantics, "/" therefore
maps to "#" here and the existing cleaner is allowed to perform that conversion.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .pronunciation import AccentPhrase, Pronunciation
from .runtime_locks import OPENJTALK_LOCK


MoraG2P = Callable[[str], Sequence[str]]

_VOWELS = frozenset({"a", "i", "u", "e", "o", "A", "I", "U", "E", "O"})


class VoicegerTokenConversionError(ValueError):
    """Raised when pronunciation cannot be converted to Voiceger tokens."""


def _default_mora_g2p(mora: str) -> Sequence[str]:
    try:
        import pyopenjtalk
    except ImportError as exc:
        raise RuntimeError(
            "pyopenjtalk is required for Voiceger token conversion; "
            "run this from Voiceger's Python environment or install pyopenjtalk"
        ) from exc

    with OPENJTALK_LOCK:
        phones = pyopenjtalk.g2p(mora, kana=False, join=False)
    return tuple(phones)


def _last_vowel(tokens: Sequence[str]) -> str | None:
    for token in reversed(tokens):
        if token in _VOWELS:
            return token.lower()
    return None


def accent_phrase_to_voiceger_tokens(
    phrase: AccentPhrase,
    *,
    mora_g2p: MoraG2P | None = None,
) -> list[str]:
    """Convert one accent phrase to Voiceger's Japanese frontend tokens."""

    if mora_g2p is None:
        mora_g2p = _default_mora_g2p

    tokens: list[str] = []
    mora_count = len(phrase.morae)

    for mora_index, mora in enumerate(phrase.morae, start=1):
        if mora == "ー":
            vowel = _last_vowel(tokens)
            if vowel is None:
                raise VoicegerTokenConversionError(
                    "long-vowel mark requires a preceding vowel"
                )
            phones = [vowel]
        else:
            phones = list(mora_g2p(mora))
            if not phones:
                raise VoicegerTokenConversionError(
                    f"no phonemes generated for mora: {mora!r}"
                )

        tokens.extend(phones)

        # Mirrors the pitch-event shape produced by Voiceger's OpenJTalk path:
        # - atamadaka (accent=1): fall after mora 1;
        # - otherwise: rise after mora 1;
        # - nakadaka: fall after the selected accent mora;
        # - final accent position: no fall occurs inside the phrase.
        if mora_count > 1 and mora_index == 1:
            tokens.append("]" if phrase.accent == 1 else "[")

        if 1 < phrase.accent < mora_count and mora_index == phrase.accent:
            tokens.append("]")

    return tokens


def pronunciation_to_voiceger_tokens(
    value: Pronunciation,
    *,
    mora_g2p: MoraG2P | None = None,
) -> list[str]:
    """Convert Pronunciation to tokens for Voiceger's Japanese G2P hook."""

    tokens: list[str] = []
    for phrase_index, phrase in enumerate(value.phrases):
        if phrase_index > 0:
            # Match Voiceger/OpenJTalk's normal g2p() output exactly.
            # Voiceger v2's cleaner later maps this "#" to "UNK".
            tokens.append("#")

        tokens.extend(
            accent_phrase_to_voiceger_tokens(
                phrase,
                mora_g2p=mora_g2p,
            )
        )

    if value.terminator == "。":
        tokens.append(".")
    elif value.terminator == "？":
        tokens.append("?")
    elif value.terminator == "！":
        tokens.append("!")

    return tokens
