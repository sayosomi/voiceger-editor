"""Shared low-level text-editing mechanics for TUI editable fields."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any

from .tui_display import _move_wrapped_cursor


@dataclass(frozen=True)
class TextEditResult:
    """Updated text/cursor state for one shared editable-field key."""

    value: str
    cursor: int
    handled: bool
    text_changed: bool = False
    edit_attempted: bool = False


def apply_text_edit_key(
    value: str,
    cursor: int,
    key: Any,
    *,
    input_width: int = 1,
) -> TextEditResult:
    """Apply one feature-neutral text-editing key to text/cursor state."""

    if key == curses.KEY_LEFT:
        return TextEditResult(value, max(0, cursor - 1), True)
    if key == curses.KEY_RIGHT:
        return TextEditResult(value, min(len(value), cursor + 1), True)
    if key == curses.KEY_HOME or key == "\x01":
        return TextEditResult(value, 0, True)
    if key == curses.KEY_END or key == "\x05":
        return TextEditResult(value, len(value), True)
    if key in (curses.KEY_UP, curses.KEY_DOWN):
        return TextEditResult(
            value,
            _move_wrapped_cursor(
                value,
                cursor,
                -1 if key == curses.KEY_UP else 1,
                max(1, input_width),
            ),
            True,
        )
    if key in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
        if not cursor:
            return TextEditResult(
                value,
                cursor,
                True,
                edit_attempted=True,
            )
        return TextEditResult(
            value[: cursor - 1] + value[cursor:],
            cursor - 1,
            True,
            text_changed=True,
            edit_attempted=True,
        )
    if key == curses.KEY_DC:
        if cursor >= len(value):
            return TextEditResult(
                value,
                cursor,
                True,
                edit_attempted=True,
            )
        return TextEditResult(
            value[:cursor] + value[cursor + 1 :],
            cursor,
            True,
            text_changed=True,
            edit_attempted=True,
        )
    if isinstance(key, str) and key and all(
        character.isprintable() or character == "　" for character in key
    ):
        return TextEditResult(
            value[:cursor] + key + value[cursor:],
            cursor + len(key),
            True,
            text_changed=True,
            edit_attempted=True,
        )
    return TextEditResult(value, cursor, False)
