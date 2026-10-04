"""Help modal state and keyboard policy for the TUI."""

from __future__ import annotations

import curses
from enum import Enum

from .tui_shortcuts import resolve_shortcut


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


class HelpOutcome(Enum):
    CLOSED = "closed"
    QUIT = "quit"


class TuiHelpController:
    """Own Help visibility, scroll position, and key interaction policy."""

    def __init__(self) -> None:
        self.active = False
        self.scroll = 0

    def open(self) -> None:
        self.scroll = 0
        self.active = True

    def close(self) -> None:
        self.active = False

    def handle_key(
        self,
        key: object,
        *,
        height: int,
        max_scroll: int,
    ) -> HelpOutcome | None:
        if key in ("q", "Q", "\x03"):
            self.close()
            return HelpOutcome.QUIT

        if (
            key in {_ESCAPE, "?", *_ENTER_KEYS}
            or resolve_shortcut("help", key) is not None
        ):
            self.close()
            return HelpOutcome.CLOSED

        if key in {
            curses.KEY_UP,
            curses.KEY_DOWN,
            curses.KEY_PPAGE,
            curses.KEY_NPAGE,
        }:
            page_step = max(1, height - 3)
            delta = {
                curses.KEY_UP: -1,
                curses.KEY_DOWN: 1,
                curses.KEY_PPAGE: -page_step,
                curses.KEY_NPAGE: page_step,
            }[key]
            self.scroll = max(
                0,
                min(max(0, max_scroll), self.scroll + delta),
            )
        return None

    def clamp_scroll(self, max_scroll: int) -> None:
        self.scroll = max(0, min(max(0, max_scroll), self.scroll))
