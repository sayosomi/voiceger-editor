"""Parse the editable Japanese pronunciation notation.

The initial notation intentionally implements only a small AquesTalk-inspired
subset:

- kana represent the spoken reading;
- `'` follows the mora that carries the accent nucleus;
- no `'` in an accent phrase means heiban (no lexical pitch fall);
- `/` separates accent phrases without an explicit pause;
- an optional final `。` or `？` is preserved as the utterance terminator.

This module is Voiceger-independent and has no third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


_SMALL_KANA = frozenset(
    "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ"
)
_TERMINATORS = frozenset({"。", "？"})


class PronunciationSyntaxError(ValueError):
    """Raised when editable pronunciation notation is malformed."""


@dataclass(frozen=True)
class AccentPhrase:
    """One accent phrase.

    nucleus is a 1-based mora index. None means heiban/no pitch fall.
    """

    morae: tuple[str, ...]
    nucleus: int | None = None

    def __post_init__(self) -> None:
        if not self.morae:
            raise ValueError("accent phrase must contain at least one mora")
        if self.nucleus is not None and not (1 <= self.nucleus <= len(self.morae)):
            raise ValueError("nucleus must point to a mora in the phrase")

    @property
    def reading(self) -> str:
        return "".join(self.morae)

    @property
    def mora_count(self) -> int:
        return len(self.morae)


@dataclass(frozen=True)
class Pronunciation:
    """Parsed editable pronunciation."""

    phrases: tuple[AccentPhrase, ...]
    terminator: str | None = None

    def __post_init__(self) -> None:
        if not self.phrases:
            raise ValueError("pronunciation must contain at least one accent phrase")
        if self.terminator is not None and self.terminator not in _TERMINATORS:
            raise ValueError(f"unsupported terminator: {self.terminator!r}")


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
    nucleus: int | None = None
    marker_just_seen = False

    for ch in source:
        if ch == "'":
            if nucleus is not None:
                raise PronunciationSyntaxError(
                    "an accent phrase may contain at most one accent marker"
                )
            if not morae:
                raise PronunciationSyntaxError(
                    "accent marker must follow a mora"
                )
            nucleus = len(morae)
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

    return AccentPhrase(tuple(morae), nucleus)


def parse_pronunciation(source: str) -> Pronunciation:
    """Parse editable pronunciation notation into a canonical data model."""

    if not source:
        raise PronunciationSyntaxError("pronunciation is empty")
    if source != source.strip():
        raise PronunciationSyntaxError(
            "leading or trailing whitespace is not allowed"
        )

    terminator: str | None = None
    body = source
    if body[-1] in _TERMINATORS:
        terminator = body[-1]
        body = body[:-1]

    if not body:
        raise PronunciationSyntaxError("pronunciation has no reading")
    if any(ch in _TERMINATORS for ch in body):
        raise PronunciationSyntaxError(
            "sentence terminators are only supported at the end"
        )

    phrase_sources = body.split("/")
    if any(not phrase for phrase in phrase_sources):
        raise PronunciationSyntaxError(
            "accent phrase boundary cannot create an empty phrase"
        )

    return Pronunciation(
        tuple(_parse_phrase(phrase) for phrase in phrase_sources),
        terminator,
    )


def format_pronunciation(value: Pronunciation) -> str:
    """Serialize the canonical data model back to editable notation."""

    rendered: list[str] = []
    for phrase in value.phrases:
        parts: list[str] = []
        for index, mora in enumerate(phrase.morae, start=1):
            parts.append(mora)
            if phrase.nucleus == index:
                parts.append("'")
        rendered.append("".join(parts))

    result = "/".join(rendered)
    if value.terminator is not None:
        result += value.terminator
    return result
