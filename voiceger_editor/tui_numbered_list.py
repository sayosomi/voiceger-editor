"""Shared numbered-list direct jump and explicit arbitrary-number input state."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"
_BACKSPACE_KEYS = {"\b", "\x7f", curses.KEY_BACKSPACE}


@dataclass(frozen=True)
class NumberedListJumpOutcome:
    """One key interpretation result from a numbered-list jump interaction."""

    handled: bool
    target_number: int | None = None
    warning: str | None = None


class NumberedListJump:
    """Own reusable 1-based numeric shortcuts without feature-specific actions."""

    def __init__(self) -> None:
        self._active = False
        self._digits = ""

    @property
    def active(self) -> bool:
        return self._active

    @property
    def value(self) -> str:
        return self._digits

    def reset(self) -> None:
        self._active = False
        self._digits = ""

    def handle_key(
        self,
        key: Any,
        *,
        item_count: int,
    ) -> NumberedListJumpOutcome:
        if self._active:
            return self._handle_active_key(key, item_count=item_count)

        if isinstance(key, str) and len(key) == 1 and key in "123456789":
            target = int(key)
            return NumberedListJumpOutcome(
                handled=True,
                target_number=target if target <= item_count else None,
            )

        if key == "0" and item_count >= 10:
            self._active = True
            self._digits = ""
            return NumberedListJumpOutcome(handled=True)

        return NumberedListJumpOutcome(handled=False)

    def _handle_active_key(
        self,
        key: Any,
        *,
        item_count: int,
    ) -> NumberedListJumpOutcome:
        if key == _ESCAPE:
            self.reset()
            return NumberedListJumpOutcome(handled=True)

        if key in _BACKSPACE_KEYS:
            self._digits = self._digits[:-1]
            return NumberedListJumpOutcome(handled=True)

        if isinstance(key, str) and len(key) == 1 and key.isdigit():
            self._digits += key
            return NumberedListJumpOutcome(handled=True)

        if key in _ENTER_KEYS:
            target = int(self._digits) if self._digits else 0
            if not 1 <= target <= item_count:
                return NumberedListJumpOutcome(
                    handled=True,
                    warning=f"Enter a number from 1 to {item_count}.",
                )
            self.reset()
            return NumberedListJumpOutcome(
                handled=True,
                target_number=target,
            )

        # While the explicit number editor is active, all other list actions stay inert.
        return NumberedListJumpOutcome(handled=True)
