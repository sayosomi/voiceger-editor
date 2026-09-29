"""Convert between core pronunciation data and VOICEVOX-like API models."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .pronunciation import (
    AccentPhrase as CoreAccentPhrase,
    Pronunciation,
    format_pronunciation,
)
from .runtime_locks import OPENJTALK_LOCK
from .voicevox_api_models import AccentPhrase, AudioQuery, Mora


_VOWEL_LIKE = frozenset(
    {"a", "i", "u", "e", "o", "A", "I", "U", "E", "O", "N", "cl"}
)


def _mora_phones(
    text: str,
    previous_vowel: Optional[str],
) -> Tuple[Optional[str], str]:
    if text == "ー":
        if previous_vowel is None:
            raise ValueError("long-vowel mark requires a preceding vowel")
        return None, previous_vowel

    try:
        import pyopenjtalk
    except ImportError as exc:
        raise RuntimeError(
            "pyopenjtalk is required; run this from Voiceger's Python environment"
        ) from exc

    with OPENJTALK_LOCK:
        phones = list(pyopenjtalk.g2p(text, kana=False, join=False))
    if len(phones) == 1:
        return None, phones[0]
    if len(phones) == 2:
        return phones[0], phones[1]
    raise ValueError(
        f"unsupported mora phoneme sequence for {text!r}: {phones!r}"
    )


def pronunciation_to_accent_phrases(
    value: Pronunciation,
) -> List[AccentPhrase]:
    result: List[AccentPhrase] = []

    for phrase_index, phrase in enumerate(value.phrases):
        moras: List[Mora] = []
        previous_vowel: Optional[str] = None

        for mora_text in phrase.morae:
            consonant, vowel = _mora_phones(mora_text, previous_vowel)
            moras.append(
                Mora(
                    text=mora_text,
                    consonant=consonant,
                    consonant_length=0 if consonant is not None else None,
                    vowel=vowel,
                    vowel_length=0,
                    pitch=0,
                )
            )
            if vowel in _VOWEL_LIKE:
                previous_vowel = vowel.lower() if len(vowel) == 1 else vowel

        result.append(
            AccentPhrase(
                moras=moras,
                accent=phrase.accent,
                pause_mora=None,
                is_interrogative=(
                    value.terminator == "？"
                    and phrase_index == len(value.phrases) - 1
                ),
            )
        )

    return result


def accent_phrases_to_pronunciation(
    accent_phrases: Sequence[AccentPhrase],
    *,
    terminator: Optional[str],
) -> Pronunciation:
    if not accent_phrases:
        raise ValueError("accent_phrases must not be empty")

    core_phrases = []
    for phrase in accent_phrases:
        morae = tuple(mora.text for mora in phrase.moras)
        if not morae:
            raise ValueError("accent phrase must contain at least one mora")
        core_phrases.append(
            CoreAccentPhrase(
                morae=morae,
                accent=phrase.accent,
            )
        )

    return Pronunciation(tuple(core_phrases), terminator=terminator)


def build_audio_query(
    *,
    pronunciation: Pronunciation,
    output_sampling_rate: int = 32000,
) -> AudioQuery:
    return AudioQuery(
        accent_phrases=pronunciation_to_accent_phrases(pronunciation),
        speedScale=1,
        pitchScale=0,
        intonationScale=1,
        volumeScale=1,
        prePhonemeLength=0.1,
        postPhonemeLength=0.1,
        pauseLength=None,
        pauseLengthScale=1,
        outputSamplingRate=output_sampling_rate,
        outputStereo=False,
        kana=format_pronunciation(pronunciation),
    )
