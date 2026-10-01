"""Parse the editable Japanese pronunciation notation.

The notation follows the core accent-position rules used by VOICEVOX's
AquesTalk-style kana notation, with one deliberate convenience: both hiragana
and katakana are accepted.

Rules:

- kana represent the spoken reading;
- `'` follows the mora selected as the accent position;
- every accent phrase must contain exactly one `'`;
- `/` separates adjacent accent phrases without explicit punctuation;
- supported punctuation is preserved in sequence and rendered canonically.

This module is Voiceger-independent and has no third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Union


_SMALL_KANA = frozenset(
    "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ"
)
_TERMINATORS = frozenset({"。", "？", "！"})
_CANONICAL_PUNCTUATION = frozenset({"。", "、", "？", "！", "…"})
_PUNCTUATION_ALIASES = {
    "。": "。",
    ".": "。",
    "、": "、",
    ",": "、",
    "，": "、",
    "：": "、",
    "；": "、",
    "·": "、",
    "？": "？",
    "?": "？",
    "！": "！",
    "!": "！",
    "…": "…",
}


class PronunciationSyntaxError(ValueError):
    """Raised when editable pronunciation notation is malformed."""


@dataclass(frozen=True)
class AccentPhrase:
    """One accent phrase.

    accent is a 1-based mora index, matching the editable notation:
    the apostrophe follows the mora at that index.
    """

    morae: tuple[str, ...]
    accent: int

    def __post_init__(self) -> None:
        if not self.morae:
            raise ValueError("accent phrase must contain at least one mora")
        if not (1 <= self.accent <= len(self.morae)):
            raise ValueError("accent must point to a mora in the phrase")

    @property
    def reading(self) -> str:
        return "".join(self.morae)

    @property
    def mora_count(self) -> int:
        return len(self.morae)


def canonicalize_punctuation(value: str) -> str | None:
    """Return the canonical editable punctuation mark for one character."""

    return _PUNCTUATION_ALIASES.get(value)


@dataclass(frozen=True)
class PronunciationPunctuation:
    """One ordered punctuation token in editable pronunciation data."""

    mark: str

    def __post_init__(self) -> None:
        if self.mark not in _CANONICAL_PUNCTUATION:
            raise ValueError(f"unsupported punctuation: {self.mark!r}")


PronunciationItem = Union[AccentPhrase, PronunciationPunctuation]


@dataclass(frozen=True, init=False)
class Pronunciation:
    """Parsed editable pronunciation with phrases and punctuation in sequence."""

    items: tuple[PronunciationItem, ...]

    def __init__(
        self,
        phrases: Sequence[AccentPhrase] | None = None,
        terminator: str | None = None,
        *,
        items: Sequence[PronunciationItem] | None = None,
    ) -> None:
        if items is not None:
            if phrases is not None or terminator is not None:
                raise ValueError(
                    "items cannot be combined with phrases or terminator"
                )
            resolved = tuple(items)
        else:
            if phrases is None:
                raise ValueError(
                    "pronunciation requires phrases or ordered items"
                )
            resolved_items: list[PronunciationItem] = list(phrases)
            if terminator is not None:
                canonical = canonicalize_punctuation(terminator)
                if canonical not in _TERMINATORS:
                    raise ValueError(
                        f"unsupported terminator: {terminator!r}"
                    )
                resolved_items.append(PronunciationPunctuation(canonical))
            resolved = tuple(resolved_items)

        object.__setattr__(self, "items", resolved)
        self.__post_init__()

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("pronunciation must contain at least one accent phrase")
        if not isinstance(self.items[0], AccentPhrase):
            raise ValueError("pronunciation cannot start with punctuation")
        if not any(isinstance(item, AccentPhrase) for item in self.items):
            raise ValueError("pronunciation must contain at least one accent phrase")
        if any(
            not isinstance(item, (AccentPhrase, PronunciationPunctuation))
            for item in self.items
        ):
            raise ValueError("pronunciation contains an unsupported item")

    @property
    def phrases(self) -> tuple[AccentPhrase, ...]:
        """Return accent phrases in their ordered pronunciation positions."""

        return tuple(
            item for item in self.items if isinstance(item, AccentPhrase)
        )

    @property
    def trailing_punctuation(self) -> str | None:
        """Return the final punctuation mark, including comma/ellipsis forms."""

        last = self.items[-1]
        if isinstance(last, PronunciationPunctuation):
            return last.mark
        return None

    @property
    def terminator(self) -> str | None:
        """Compatibility view of the legacy sentence-ending punctuation."""

        trailing = self.trailing_punctuation
        return trailing if trailing in _TERMINATORS else None


def _is_kana(ch: str) -> bool:
    return (
        "\u3041" <= ch <= "\u3096"
        or "\u30a1" <= ch <= "\u30fa"
        or ch in {"ー", "ゔ", "ヴ"}
    )


def _parse_phrase(source: str) -> AccentPhrase:
    if not source:
        raise PronunciationSyntaxError("empty accent phrase")

    morae: list[str] = []
    accent: int | None = None
    marker_just_seen = False

    for ch in source:
        if ch == "'":
            if accent is not None:
                raise PronunciationSyntaxError(
                    "an accent phrase must contain exactly one accent marker"
                )
            if not morae:
                raise PronunciationSyntaxError(
                    "accent marker must follow a mora"
                )
            accent = len(morae)
            marker_just_seen = True
            continue

        if not _is_kana(ch):
            raise PronunciationSyntaxError(
                f"unsupported character in pronunciation: {ch!r}"
            )

        if ch in _SMALL_KANA:
            if not morae:
                raise PronunciationSyntaxError(
                    f"small kana cannot start an accent phrase: {ch!r}"
                )
            if marker_just_seen:
                raise PronunciationSyntaxError(
                    "accent marker must follow the complete mora "
                    "(for example きゃ', not き'ゃ)"
                )
            morae[-1] += ch
        else:
            morae.append(ch)

        marker_just_seen = False

    if accent is None:
        raise PronunciationSyntaxError(
            "every accent phrase must contain exactly one accent marker"
        )

    return AccentPhrase(tuple(morae), accent)


def parse_pronunciation(source: str) -> Pronunciation:
    """Parse editable pronunciation notation into ordered canonical data."""

    if not source:
        raise PronunciationSyntaxError("pronunciation is empty")
    if source != source.strip():
        raise PronunciationSyntaxError(
            "leading or trailing whitespace is not allowed"
        )

    items: list[PronunciationItem] = []
    phrase_chars: list[str] = []
    boundary_pending = False

    def flush_phrase() -> None:
        nonlocal phrase_chars
        if not phrase_chars:
            raise PronunciationSyntaxError(
                "accent phrase boundary cannot create an empty phrase"
            )
        items.append(_parse_phrase("".join(phrase_chars)))
        phrase_chars = []

    for ch in source:
        if ch == "/":
            if boundary_pending or not phrase_chars:
                raise PronunciationSyntaxError(
                    "accent phrase boundary cannot create an empty phrase"
                )
            flush_phrase()
            boundary_pending = True
            continue

        punctuation = canonicalize_punctuation(ch)
        if punctuation is not None:
            if boundary_pending:
                raise PronunciationSyntaxError(
                    "accent phrase boundary cannot create an empty phrase"
                )
            if phrase_chars:
                flush_phrase()
            elif not items:
                raise PronunciationSyntaxError(
                    "pronunciation cannot start with punctuation"
                )
            items.append(PronunciationPunctuation(punctuation))
            continue

        phrase_chars.append(ch)
        boundary_pending = False

    if boundary_pending:
        raise PronunciationSyntaxError(
            "accent phrase boundary cannot create an empty phrase"
        )
    if phrase_chars:
        flush_phrase()

    return Pronunciation(items=tuple(items))


def _format_phrase(phrase: AccentPhrase) -> str:
    parts: list[str] = []
    for index, mora in enumerate(phrase.morae, start=1):
        parts.append(mora)
        if phrase.accent == index:
            parts.append("'")
    return "".join(parts)


def format_pronunciation(value: Pronunciation) -> str:
    """Serialize ordered pronunciation data back to editable notation."""

    rendered: list[str] = []
    previous_phrase = False

    for item in value.items:
        if isinstance(item, AccentPhrase):
            if previous_phrase:
                rendered.append("/")
            rendered.append(_format_phrase(item))
            previous_phrase = True
        else:
            rendered.append(item.mark)
            previous_phrase = False

    return "".join(rendered)
