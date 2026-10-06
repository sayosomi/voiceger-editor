"""Shared inline editor for the persisted TUI Output directory."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .tui_display import _display_width
from .tui_status import EMPTY_STATUS, Status, info_status
from .tui_text_editing import apply_text_edit_key


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"
_OUTPUT_PREFIX = "▶ [F] Output: "

OutputPathOwner = Literal["batch_item", "dictionary_export", "batch_write"]


@dataclass(frozen=True)
class BeginOutputPathEditIntent:
    owner: OutputPathOwner


@dataclass
class OutputPathEditState:
    owner: OutputPathOwner
    value: str
    cursor: int


class TuiOutputPathController:
    """Edit and persist the one shared Settings.output_dir without changing screens."""

    def __init__(
        self,
        *,
        get_output_dir: Callable[[], Any],
        save_output_dir: Callable[[str], bool],
        busy: Callable[[], bool],
        set_status: Callable[[Status], None],
    ) -> None:
        self._get_output_dir = get_output_dir
        self._save_output_dir = save_output_dir
        self._busy = busy
        self._set_status = set_status
        self.state: OutputPathEditState | None = None

    @property
    def active(self) -> bool:
        return self.state is not None

    def begin(self, owner: OutputPathOwner) -> bool:
        if self._busy():
            self._set_status(
                info_status("Wait for synthesis to finish before changing Output.")
            )
            return False
        value = str(self._get_output_dir())
        self.state = OutputPathEditState(
            owner=owner,
            value=value,
            cursor=len(value),
        )
        self._set_status(EMPTY_STATUS)
        return True

    def close(self) -> None:
        self.state = None

    def handle_key(self, key: Any, *, screen_width: int = 80) -> bool:
        state = self.state
        if state is None:
            return False
        if key in _ENTER_KEYS:
            if self._save_output_dir(state.value):
                self.state = None
            return True
        if key == _ESCAPE:
            self.state = None
            return True

        input_width = max(
            1,
            screen_width - 1 - _display_width(_OUTPUT_PREFIX),
        )
        edit = apply_text_edit_key(
            state.value,
            state.cursor,
            key,
            input_width=input_width,
        )
        if edit.handled:
            state.value = edit.value
            state.cursor = edit.cursor
        return True
