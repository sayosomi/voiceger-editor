"""Pure display formatting and terminal-cell layout helpers for the TUI."""

from __future__ import annotations

import unicodedata
from typing import Sequence

from .english_stress import (
    EnglishPhonemeEditorState,
    english_phonemes_to_editor_state,
)


_VOWELS = frozenset(
    {
        "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
        "IH", "IY", "OW", "OY", "UH", "UW",
    }
)


def format_english_phonemes(
    phonemes: Sequence[str],
    *,
    selected_primary: int | None = None,
) -> str:
    """Render stressed ARPAbet, marking primary-stress anchors visually."""

    state = english_phonemes_to_editor_state(phonemes)
    return " ".join(
        _phoneme_state_tokens(state, selected_primary=selected_primary)
    )


def _display_width(value: str) -> int:
    return sum(
        0
        if unicodedata.combining(character) or character == "\u200d"
        else 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
        for character in value
    )


def _adjustable_value(value: str, direction: int | None = None) -> str:
    """Render fixed-width ASCII controls with one-frame pressed feedback."""

    if direction is not None and direction < 0:
        return f"<<{value} >"
    if direction is not None and direction > 0:
        return f"< {value}>>"
    return f"< {value} >"


def _wrap_text(value: str, width: int) -> list[str]:
    """Wrap visible text while preserving explicit line boundaries."""

    if not value:
        return []
    width = max(1, width)
    lines: list[str] = []
    for logical_line in value.split("\n"):
        if not logical_line:
            lines.append("")
            continue
        current: list[str] = []
        used = 0
        for character in logical_line:
            cell_width = _display_width(character)
            if current and used + cell_width > width:
                lines.append("".join(current))
                current = []
                used = 0
            current.append(character)
            used += cell_width
        lines.append("".join(current))
    return lines


def _truncate_display(value: str, width: int) -> str:
    """Trim a display-only value at a complete character boundary."""

    width = max(0, width)
    result: list[str] = []
    used = 0
    for character in value:
        cells = _display_width(character)
        if used + cells > width:
            break
        result.append(character)
        used += cells
    return "".join(result)


def _wrap_labeled_tokens(
    label: str,
    tokens: Sequence[str],
    width: int,
) -> list[str]:
    """Wrap a phoneme sequence only between complete display tokens."""

    width = max(1, width)
    continuation = " " * _display_width(label)
    lines: list[str] = []
    current = label
    used = _display_width(label)
    values = list(tokens) or ["(none)"]
    first_line = True
    line_has_tokens = False
    for token in values:
        separator = (
            1
            if line_has_tokens or (first_line and label and not label[-1].isspace())
            else 0
        )
        token_width = _display_width(token)
        if used + separator + token_width > width and line_has_tokens:
            lines.append(current)
            current = continuation
            used = _display_width(continuation)
            first_line = False
            line_has_tokens = False
            separator = 0
        if separator:
            current += " "
            used += 1
        current += token
        used += token_width
        line_has_tokens = True
    lines.append(current)
    return lines


def _phoneme_state_tokens(
    state: EnglishPhonemeEditorState,
    *,
    selected_primary: int | None = None,
) -> list[str]:
    result: list[str] = []
    vowel_index = 0
    for token in state.base_phonemes:
        if token in _VOWELS:
            stress = state.vowel_stresses[vowel_index]
            display_token = f"{token}{stress}" if stress is not None else token
            if vowel_index == selected_primary:
                result.append(f"▶[{display_token}]")
            elif stress == 1:
                result.append(f"[{display_token}]")
            else:
                result.append(display_token)
            vowel_index += 1
        else:
            result.append(token)
    return result


def _phonemes_as_ui_tokens(phonemes: Sequence[str]) -> list[str]:
    return _phoneme_state_tokens(english_phonemes_to_editor_state(phonemes))


def _english_display_tokens(phonemes: Sequence[str]) -> list[str]:
    return _phonemes_as_ui_tokens(phonemes)


def _japanese_mora_tokens(
    morae: Sequence[str],
    accent: int,
) -> list[str]:
    """Show a Japanese phrase as complete, space-separated mora tokens."""

    return [
        f"[{mora}]" if index == accent else mora
        for index, mora in enumerate(morae, start=1)
    ]


def _wrap_tokens_with_prefixes(
    first_prefix: str,
    continuation_prefix: str,
    tokens: Sequence[str],
    width: int,
    *,
    cursor_index: int | None = None,
) -> tuple[list[str], tuple[int, int] | None]:
    """Wrap complete tokens and optionally locate a token-boundary cursor."""

    width = max(1, width)
    lines: list[str] = []
    current_prefix = first_prefix
    current = first_prefix
    used = _display_width(first_prefix)
    has_token = False
    cursor: tuple[int, int] | None = None
    line_index = 0
    values = list(tokens)

    for index, token in enumerate(values):
        token_width = _display_width(token)
        separator_width = 1 if has_token else 0
        if (
            used + separator_width + token_width > width
            and has_token
        ) or (
            used + token_width > width
            and not has_token
            and current_prefix != continuation_prefix
        ):
            lines.append(current)
            line_index += 1
            current_prefix = continuation_prefix
            current = continuation_prefix
            used = _display_width(continuation_prefix)
            has_token = False
            separator_width = 0

        if cursor_index == index:
            cursor = (line_index, used + separator_width)
        if separator_width:
            current += " "
            used += 1
        current += token
        used += token_width
        has_token = True

    if cursor_index == len(values):
        cursor = (line_index, used)
    lines.append(current)
    return lines, cursor


def _wrapped_ranges(value: str, width: int) -> list[tuple[int, int]]:
    width = max(1, width)
    if not value:
        return [(0, 0)]
    rows: list[tuple[int, int]] = []
    start = 0
    used = 0
    for index, character in enumerate(value):
        if character == "\n":
            rows.append((start, index))
            start = index + 1
            used = 0
            continue
        cell_width = _display_width(character)
        if index > start and used + cell_width > width:
            rows.append((start, index))
            start = index
            used = 0
        used += cell_width
    rows.append((start, len(value)))
    return rows


def _wrap_active_input(
    value: str,
    cursor: int,
    width: int,
) -> tuple[list[str], int, int]:
    """Wrap an active input line and locate its cursor in terminal cells."""

    ranges = _wrapped_ranges(value, width)
    cursor = min(max(cursor, 0), len(value))
    cursor_row = len(ranges) - 1
    for index, (start, end) in enumerate(ranges):
        if start <= cursor < end:
            cursor_row = index
            break
        if cursor == start:
            cursor_row = index
            break
        if cursor == end and end < len(value) and value[end] == "\n":
            cursor_row = index
            break
        if cursor == end and index == len(ranges) - 1:
            cursor_row = index
            break
    start, _end = ranges[cursor_row]
    return (
        [value[row_start:row_end] for row_start, row_end in ranges],
        cursor_row,
        _display_width(value[start:cursor]),
    )


def _move_wrapped_cursor(value: str, cursor: int, delta: int, width: int) -> int:
    """Move a code-point cursor between wrapped visual lines when possible."""

    rows = _wrapped_ranges(value, width)
    cursor = min(max(cursor, 0), len(value))
    _wrapped, current_row, current_column = _wrap_active_input(
        value, cursor, width
    )
    target_row = min(max(current_row + delta, 0), len(rows) - 1)
    if target_row == current_row:
        return cursor
    row_start, row_end = rows[target_row]
    target = row_start
    used = 0
    for index in range(row_start, row_end):
        cell_width = _display_width(value[index])
        if used + cell_width > current_column:
            break
        used += cell_width
        target = index + 1
    return target
