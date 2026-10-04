"""Terminal input decoding for the curses TUI."""

from __future__ import annotations

import curses
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}


@dataclass(frozen=True)
class PasteText:
    """Text inferred to be part of one queued paste burst."""

    text: str


class TuiInputReader:
    """Decode queued paste newlines without changing terminal modes."""

    def __init__(
        self,
        *,
        normal_timeout_ms: int = 100,
        paste_lookahead_timeout_ms: int = 5,
    ) -> None:
        self._normal_timeout_ms = normal_timeout_ms
        self._paste_lookahead_timeout_ms = paste_lookahead_timeout_ms
        self._pending: Deque[Any] = deque()
        self._paste_burst_active = False

    def read(self, screen: Any) -> Any:
        try:
            key = (
                self._pending.popleft()
                if self._pending
                else screen.get_wch()
            )
        except curses.error:
            self._paste_burst_active = False
            return None

        if key not in _ENTER_KEYS:
            return key

        if self._paste_burst_active:
            return PasteText("\n")

        next_key = self._peek_queued_key(screen)
        if next_key is None:
            return key

        self._pending.append(next_key)
        self._paste_burst_active = True
        return PasteText("\n")

    def _peek_queued_key(self, screen: Any) -> Any | None:
        screen.timeout(self._paste_lookahead_timeout_ms)
        try:
            try:
                return screen.get_wch()
            except curses.error:
                return None
        finally:
            screen.timeout(self._normal_timeout_ms)
