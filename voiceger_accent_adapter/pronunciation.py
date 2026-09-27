"""Parse the editable Japanese pronunciation notation.

The initial notation follows the core accent-position rules used by
VOICEVOX's AquesTalk-style kana notation, with one deliberate convenience:
both hiragana and katakana are accepted.

Initial subset:

- kana represent the spoken reading;
- `'` follows the mora selected as the accent position;
- every accent phrase must contain exactly one `'`;
- `/` separates accent phrases without an explicit pause;
- an optional final `。`, `？`, or `！` is preserved as the utterance terminator.

Examples:

- `あ'め` -> accent=1
- `あめ'` -> accent=2

This module is Voiceger-independent and has no third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass


_SMALL_KANA = frozenset(
    "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ"
)
_TERMINATORS = frozenset({"。", "？", "！"})


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
            if phrase.accent == index:
                parts.append("'")
        rendered.append("".join(parts))

    result = "/".join(rendered)
    if value.terminator is not None:
        result += value.terminator
    return result
