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
    """Render stress-free ARPAbet, marking primary-stress anchors visually."""

    state = english_phonemes_to_editor_state(phonemes)
    result: list[str] = []
    vowel_position = 0
    for token in state.base_phonemes:
        if token in _VOWELS:
            stress = state.vowel_stresses[vowel_position]
            selected = vowel_position == selected_primary
            if selected:
                rendered = f"▶[{token}]"
            elif stress == 1:
                rendered = f"[{token}]"
            else:
                rendered = token
            result.append(rendered)
            vowel_position += 1
        else:
            result.append(token)
    return " ".join(result)


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
    """Wrap visible text at character boundaries without changing stored text."""

    if not value:
        return []
    width = max(1, width)
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for character in value:
        cell_width = _display_width(character)
        if current and used + cell_width > width:
            lines.append("".join(current))
            current = []
            used = 0
        current.append(character)
        used += cell_width
    if current:
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


def _phoneme_state_tokens(state: EnglishPhonemeEditorState) -> list[str]:
    result: list[str] = []
    vowel_index = 0
    for token in state.base_phonemes:
        if token in _VOWELS:
            if state.vowel_stresses[vowel_index] == 1:
                result.append(f"[{token}]")
            else:
                result.append(token)
            vowel_index += 1
        else:
            result.append(token)
    return result


def _phonemes_as_ui_tokens(phonemes: Sequence[str]) -> list[str]:
    return _phoneme_state_tokens(english_phonemes_to_editor_state(phonemes))


def _english_display_tokens(phonemes: Sequence[str]) -> list[str]:
    return _phonemes_as_ui_tokens(phonemes)


def _wrapped_ranges(value: str, width: int) -> list[tuple[int, int]]:
    width = max(1, width)
    if not value:
        return [(0, 0)]
    rows: list[tuple[int, int]] = []
    start = 0
    used = 0
    for index, character in enumerate(value):
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
