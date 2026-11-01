"""Mora-aware Japanese pronunciation to editable Voiceger ARPAbet groups.

A frontend-neutral, deliberately approximate conversion. Phrase boundaries
are returned explicitly; callers must preserve them rather than asking
Voiceger's English tokenizer to reconstruct boundaries from Japanese text.
"""

from __future__ import annotations

from dataclasses import dataclass

from .english_stress import normalize_english_phonemes
from .pronunciation import AccentPhrase, Pronunciation, PronunciationPunctuation


_VOWELS = {"ア": "AA", "イ": "IY", "ウ": "UW", "エ": "EH", "オ": "OW"}
_SMALL_VOWELS = {"ァ": "AA", "ィ": "IY", "ゥ": "UW", "ェ": "EH", "ォ": "OW"}
_SYLLABLES: dict[str, tuple[tuple[str, ...], str]] = {}
for _kana, _onset in (
    ("アイウエオ", ()), ("カキクケコ", ("K",)), ("サシスセソ", ("S",)),
    ("タチツテト", ("T",)), ("ナニヌネノ", ("N",)),
    ("ハヒフヘホ", ("HH",)), ("マミムメモ", ("M",)),
    ("ラリルレロ", ("R",)), ("ガギグゲゴ", ("G",)),
    ("ザジズゼゾ", ("Z",)), ("ダヂヅデド", ("D",)),
    ("バビブベボ", ("B",)), ("パピプペポ", ("P",)),
):
    for _char, _vowel in zip(_kana, _VOWELS.values()):
        _SYLLABLES[_char] = (_onset, _vowel)
_SYLLABLES.update({
    "シ": (("SH",), "IY"), "チ": (("CH",), "IY"),
    "ツ": (("T", "S"), "UW"), "フ": (("F",), "UW"),
    "ジ": (("JH",), "IY"), "ヂ": (("JH",), "IY"),
    "ヅ": (("Z",), "UW"),
    "ヤ": (("Y",), "AA"), "ユ": (("Y",), "UW"),
    "ヨ": (("Y",), "OW"),
    "ワ": (("W",), "AA"), "ヲ": ((), "OW"),
    "ヴ": (("V",), "UW"),
})

_YOON_BASES = {
    "キ": ("K", "Y"), "ギ": ("G", "Y"),
    "ニ": ("N", "Y"), "ヒ": ("HH", "Y"),
    "ビ": ("B", "Y"), "ピ": ("P", "Y"),
    "ミ": ("M", "Y"), "リ": ("R", "Y"),
    "シ": ("SH",), "ジ": ("JH",),
    "チ": ("CH",), "ヂ": ("JH",),
}
_COMPOUNDS: dict[str, tuple[tuple[str, ...], str]] = {
    base + small: (onset, vowel)
    for base, onset in _YOON_BASES.items()
    for small, vowel in (("ャ", "AA"), ("ュ", "UW"), ("ョ", "OW"))
}
_COMPOUNDS.update({
    # Foreign-loanword digraphs. Unsupported combinations fail explicitly.
    **{("フ" + k): (("F",), v) for k, v in _SMALL_VOWELS.items()},
    **{("ヴ" + k): (("V",), v) for k, v in _SMALL_VOWELS.items()},
    **{("ウ" + k): (("W",), v) for k, v in (("ィ", "IY"), ("ェ", "EH"), ("ォ", "OW"))},
    "ティ": (("T",), "IY"), "ディ": (("D",), "IY"),
    "トゥ": (("T",), "UW"), "ドゥ": (("D",), "UW"),
    "シェ": (("SH",), "EH"), "ジェ": (("JH",), "EH"),
    "チェ": (("CH",), "EH"), "ツァ": (("T", "S"), "AA"),
    "ツィ": (("T", "S"), "IY"), "ツェ": (("T", "S"), "EH"),
    "ツォ": (("T", "S"), "OW"),
    "クァ": (("K", "W"), "AA"), "グァ": (("G", "W"), "AA"),
})
_PUNCTUATION = {"。": ".", "、": ",", "？": "?", "！": "!", "…": "…"}


@dataclass(frozen=True)
class ArpabetPhraseGroup:
    """One preserved JA accent phrase, or one ordered punctuation token."""

    label: str
    phonemes: tuple[str, ...]


def _canonical_kana(mora: str) -> str:
    return "".join(
        chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char
        for char in mora
    )


def _mora_tokens(mora: str) -> tuple[tuple[str, ...], str]:
    canonical = _canonical_kana(mora)
    mapped = _COMPOUNDS.get(canonical) or _SYLLABLES.get(canonical)
    if mapped is None:
        raise ValueError(f"ARPAbet conversion does not support mora {mora!r}")
    return mapped


def _phrase_group(phrase: AccentPhrase) -> ArpabetPhraseGroup:
    if phrase.pitch_events is not None:
        raise ValueError(
            "ARPAbet conversion cannot represent explicit Japanese multi-peak "
            "[ ] pitch markers; simplify this phrase first"
        )

    tokens: list[str] = []
    vowel_positions: list[int | None] = []
    last_vowel: str | None = None
    for index, mora in enumerate(phrase.morae):
        canonical = _canonical_kana(mora)
        if canonical == "ン":
            tokens.append("N")
            vowel_positions.append(None)
            continue
        if canonical == "ッ":
            if index + 1 >= len(phrase.morae):
                raise ValueError("ARPAbet conversion cannot end a phrase with ッ")
            onset, _ = _mora_tokens(phrase.morae[index + 1])
            if not onset:
                raise ValueError("ARPAbet conversion cannot resolve ッ before a vowel")
            tokens.append(onset[0])
            vowel_positions.append(None)
            continue
        if canonical == "ー":
            if last_vowel is None:
                raise ValueError("ARPAbet conversion requires a vowel before ー")
            tokens.append(last_vowel + "0")
            vowel_positions.append(len(tokens) - 1)
            continue
        onset, vowel = _mora_tokens(mora)
        tokens.extend(onset)
        tokens.append(vowel + "0")
        last_vowel = vowel
        vowel_positions.append(len(tokens) - 1)

    stress_mora = phrase.accent - 1
    stress_index = vowel_positions[stress_mora]
    if stress_index is None:
        # A nasal coda has no stress-bearing vowel; attach its accent to the
        # preceding vowel when possible, never invent an unvoiced vowel.
        stress_index = next(
            (position for position in reversed(vowel_positions[:stress_mora])
             if position is not None),
            None,
        )
    if stress_index is None:
        raise ValueError(
            "ARPAbet conversion cannot place stress: phrase has no preceding vowel"
        )
    tokens[stress_index] = tokens[stress_index][:-1] + "1"
    normalized = tuple(normalize_english_phonemes(tokens))
    return ArpabetPhraseGroup("".join(phrase.morae), normalized)


def pronunciation_to_arpabet_groups(
    pronunciation: Pronunciation,
) -> tuple[ArpabetPhraseGroup, ...]:
    """Convert every phrase in order; reject data that would be silently lost."""

    if not isinstance(pronunciation, Pronunciation):
        raise TypeError("pronunciation must be parsed Japanese Pronunciation")
    groups: list[ArpabetPhraseGroup] = []
    previous_punctuation = False
    for item in pronunciation.items:
        if isinstance(item, AccentPhrase):
            groups.append(_phrase_group(item))
            previous_punctuation = False
        elif isinstance(item, PronunciationPunctuation):
            if previous_punctuation:
                raise ValueError(
                    "ARPAbet conversion cannot preserve consecutive punctuation "
                    "with the pinned Voiceger English normalizer"
                )
            groups.append(
                ArpabetPhraseGroup(item.mark, (_PUNCTUATION[item.mark],))
            )
            previous_punctuation = True
        else:
            raise TypeError("unsupported Japanese pronunciation item")
    return tuple(groups)


def flatten_arpabet_groups(
    groups: tuple[ArpabetPhraseGroup, ...],
) -> tuple[str, ...]:
    """Return Voiceger's canonical flat EN phonemes without losing any token."""

    return tuple(
        normalize_english_phonemes(
            [phoneme for group in groups for phoneme in group.phonemes]
        )
    )
