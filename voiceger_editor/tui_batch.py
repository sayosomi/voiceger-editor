"""Batch List state, navigation, and key interpretation for the TUI."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union

from .caption_batch import CaptionBatch
from .tui_shortcuts import resolve_batch_list_shortcut


BatchFocusKey = tuple[str, Optional[int]]
SessionFactory = Callable[[str], Any]

_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}


@dataclass(frozen=True)
class OpenBatchItem:
    index: int


@dataclass(frozen=True)
class AddCaptions:
    pass


@dataclass(frozen=True)
class GenerateSelected:
    pass


@dataclass(frozen=True)
class AdjustBatchTakeCount:
    direction: int


@dataclass(frozen=True)
class OpenBatchSettings:
    pass


@dataclass(frozen=True)
class OpenBatchDictionary:
    pass


@dataclass(frozen=True)
class OpenBatchHelp:
    pass


@dataclass(frozen=True)
class QuitBatch:
    pass


BatchAction = Union[
    OpenBatchItem,
    AddCaptions,
    GenerateSelected,
    AdjustBatchTakeCount,
    OpenBatchSettings,
    OpenBatchDictionary,
    OpenBatchHelp,
    QuitBatch,
]


class TuiBatchController:
    """Own Batch List state and policy without depending on the composition root."""

    def __init__(self, *, default_take_count: int) -> None:
        self.batch = CaptionBatch(default_take_count=default_take_count)
        self.focus_key: BatchFocusKey = ("takes", None)
        self.item_index: int | None = None

    @property
    def in_item(self) -> bool:
        return self.item_index is not None

    @property
    def sessions(self) -> tuple[Any, ...]:
        return tuple(item.session for item in self.batch.items)

    @property
    def item_title(self) -> str:
        if self.item_index is None:
            raise RuntimeError("No Batch Item is open")
        return f"BATCH ITEM {self.item_index + 1}/{len(self.batch)}"

    def add_captions(self, text: str, *, session_factory: SessionFactory) -> None:
        self.batch.add_captions_from_text(text, session_factory=session_factory)
        self._repair_focus()

    def add_caption(self, caption: str, *, session_factory: SessionFactory) -> None:
        self.batch.add_caption(caption, session_factory=session_factory)
        self.focus_key = ("caption", len(self.batch) - 1)

    def open_item(self, index: int) -> Any:
        if not 0 <= index < len(self.batch):
            raise IndexError(index)
        self.item_index = index
        return self.batch.items[index].session

    def close_item(self) -> None:
        self.item_index = None
        self._repair_focus()

    def close_sessions(self) -> None:
        for session in self.sessions:
            session.close()

    def navigation_items(self) -> tuple[BatchFocusKey, ...]:
        return (
            (("takes", None),)
            + tuple(("caption", index) for index in range(len(self.batch)))
            + (
                ("add_captions", None),
                ("generate_selected", None),
                ("settings", None),
                ("dictionary", None),
                ("help", None),
                ("quit", None),
            )
        )

    def move(self, direction: int) -> None:
        items = self.navigation_items()
        try:
            index = items.index(self.focus_key)
        except ValueError:
            index = 0
        target = min(max(index + direction, 0), len(items) - 1)
        self.focus_key = items[target]

    def handle_key(self, key: Any) -> tuple[BatchAction, ...]:
        if key in ("Q", "\x03"):
            return (QuitBatch(),)

        shortcut = resolve_batch_list_shortcut(key)
        if shortcut is not None:
            return self._activate((shortcut.navigation_key, None))

        if key == curses.KEY_UP:
            self.move(-1)
            return ()
        if key == curses.KEY_DOWN:
            self.move(1)
            return ()
        if key == " ":
            if self.focus_key[0] == "caption" and self.focus_key[1] is not None:
                self.batch.toggle_included(self.batch.items[self.focus_key[1]].item_id)
            return ()
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            if self.focus_key == ("takes", None):
                return (
                    AdjustBatchTakeCount(
                        -1 if key == curses.KEY_LEFT else 1
                    ),
                )
            return ()
        if key in _ENTER_KEYS:
            return self._activate(self.focus_key)
        return ()

    def _activate(self, key: BatchFocusKey) -> tuple[BatchAction, ...]:
        name, index = key
        if name == "caption" and index is not None and 0 <= index < len(self.batch):
            return (OpenBatchItem(index),)
        if name == "add_captions":
            return (AddCaptions(),)
        if name == "generate_selected":
            return (GenerateSelected(),)
        if name == "settings":
            return (OpenBatchSettings(),)
        if name == "dictionary":
            return (OpenBatchDictionary(),)
        if name == "help":
            return (OpenBatchHelp(),)
        if name == "quit":
            return (QuitBatch(),)
        return ()

    def _repair_focus(self) -> None:
        items = self.navigation_items()
        if self.focus_key not in items:
            self.focus_key = (
                ("caption", 0) if len(self.batch) else ("takes", None)
            )
