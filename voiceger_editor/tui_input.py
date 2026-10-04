"""Terminal input decoding for the curses TUI."""

from __future__ import annotations

import curses
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque


_ESCAPE = "\x1b"
_PASTE_START_REST = "[200~"
_PASTE_END = "\x1b[201~"
_BRACKETED_PASTE_ENABLE = b"\x1b[?2004h"
_BRACKETED_PASTE_DISABLE = b"\x1b[?2004l"


@dataclass(frozen=True)
class PasteText:
    """One bracketed-paste payload decoded from the terminal."""

    text: str


class TuiInputReader:
    """Decode terminal input while preserving ordinary curses key behavior."""

    def __init__(
        self,
        *,
        normal_timeout_ms: int = 100,
        sequence_timeout_ms: int = 5,
    ) -> None:
        self._normal_timeout_ms = normal_timeout_ms
        self._sequence_timeout_ms = sequence_timeout_ms
        self._pending: Deque[Any] = deque()
        self._bracketed_paste_enabled = False
        self._paste_buffer = ""
        self._in_paste = False

    def set_bracketed_paste(self, enabled: bool) -> None:
        if enabled == self._bracketed_paste_enabled:
            return
        try:
            curses.putp(
                _BRACKETED_PASTE_ENABLE if enabled else _BRACKETED_PASTE_DISABLE
            )
        except (AttributeError, curses.error):
            pass
        self._bracketed_paste_enabled = enabled

    def close(self) -> None:
        self.set_bracketed_paste(False)

    def read(self, screen: Any) -> Any:
        if self._pending:
            return self._pending.popleft()
        if self._in_paste:
            return self._continue_paste(screen)

        try:
            key = screen.get_wch()
        except curses.error:
            return None

        if not self._bracketed_paste_enabled or key != _ESCAPE:
            return key

        if not self._consume_paste_start(screen):
            return _ESCAPE

        self._in_paste = True
        self._paste_buffer = ""
        return self._continue_paste(screen)

    def _consume_paste_start(self, screen: Any) -> bool:
        consumed: list[Any] = []
        screen.timeout(self._sequence_timeout_ms)
        try:
            for expected in _PASTE_START_REST:
                try:
                    key = screen.get_wch()
                except curses.error:
                    self._pending.extend(consumed)
                    return False
                consumed.append(key)
                if key != expected:
                    self._pending.extend(consumed)
                    return False
        finally:
            screen.timeout(self._normal_timeout_ms)
        return True

    def _continue_paste(self, screen: Any) -> PasteText | None:
        while True:
            try:
                key = screen.get_wch()
            except curses.error:
                return None
            if key == curses.KEY_ENTER:
                key = "\n"
            elif not isinstance(key, str):
                continue
            self._paste_buffer += key
            if not self._paste_buffer.endswith(_PASTE_END):
                continue

            text = self._paste_buffer[: -len(_PASTE_END)]
            self._paste_buffer = ""
            self._in_paste = False
            return PasteText(text.replace("\r\n", "\n").replace("\r", "\n"))
