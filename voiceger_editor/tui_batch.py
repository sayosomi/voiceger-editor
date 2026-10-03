"""Batch List state, navigation, and key interpretation for the TUI."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Union

from .caption_batch import CaptionBatch
from .tui_navigation import TuiNavigation
from .tui_operations import OperationEffect, TakeAcceptedEffect, TuiOperations
from .tui_shortcuts import (
    resolve_batch_list_caption_shortcut,
    resolve_batch_list_shortcut,
    resolve_shortcut,
)


BatchFocusKey = tuple[str, Optional[int]]
SessionFactory = Callable[[str], Any]

_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"


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


@dataclass(frozen=True)
class BatchActionBindings:
    """Composition-root hooks needed to execute Batch List actions."""

    operations: TuiOperations
    navigation: TuiNavigation
    editor_controller: Any
    dictionary_controller: Any
    set_session: Callable[[Any | None], None]
    set_status: Callable[[str], None]
    open_caption_editor: Callable[[str | None], None]
    change_settings: Callable[..., None]
    open_settings_editor: Callable[[str | None], None]
    dispatch_editor_intents: Callable[[Sequence[Any]], None]
    dispatch_operation_effects: Callable[[Sequence[OperationEffect]], None]
    open_help: Callable[[], None]
    activate_quit: Callable[[], None]


class TuiBatchController:
    """Own Batch List state and policy without depending on the composition root."""

    def __init__(self, *, default_take_count: int) -> None:
        self.batch = CaptionBatch(default_take_count=default_take_count)
        self.focus_key: BatchFocusKey = ("takes", None)
        self._open_item_id: str | None = None
        self._pending_delete_item_id: str | None = None
        self._pending_delete_from_item = False
        self._delete_confirmation_selection = "delete"

    @property
    def item_index(self) -> int | None:
        if self._open_item_id is None:
            return None
        try:
            item = self.batch.get_item(self._open_item_id)
        except KeyError:
            self._open_item_id = None
            return None
        return self.batch.items.index(item)

    @property
    def open_item_id(self) -> str | None:
        return self._open_item_id

    @property
    def in_item(self) -> bool:
        return self.item_index is not None

    @property
    def open_item_accepted_take_number(self) -> int | None:
        item_id = self.open_item_id
        if item_id is None:
            return None
        try:
            return self.batch.get_item(item_id).accepted_take_number
        except KeyError:
            return None

    @property
    def sessions(self) -> tuple[Any, ...]:
        return tuple(item.session for item in self.batch.items)

    @property
    def delete_confirmation_active(self) -> bool:
        return self._pending_delete_item_id is not None

    @property
    def delete_confirmation_selection(self) -> str:
        return self._delete_confirmation_selection

    @property
    def delete_confirmation_caption(self) -> str | None:
        if self._pending_delete_item_id is None:
            return None
        try:
            return self.batch.get_item(self._pending_delete_item_id).caption
        except KeyError:
            self._pending_delete_item_id = None
            self._pending_delete_from_item = False
            self._delete_confirmation_selection = "delete"
            self._repair_focus()
            return None

    @property
    def item_title(self) -> str:
        if self.item_index is None:
            raise RuntimeError("No Batch Item is open")
        return "BATCH ITEM"

    @property
    def item_position(self) -> tuple[int, int]:
        if self.item_index is None:
            raise RuntimeError("No Batch Item is open")
        return self.item_index + 1, len(self.batch)

    def add_captions(self, text: str, *, session_factory: SessionFactory) -> None:
        self.batch.add_captions_from_text(text, session_factory=session_factory)
        self._repair_focus()

    def add_caption(self, caption: str, *, session_factory: SessionFactory) -> None:
        self.batch.add_caption(caption, session_factory=session_factory)
        self.focus_key = ("caption", len(self.batch) - 1)

    def request_delete_open_item(self) -> None:
        item_id = self.open_item_id
        if item_id is None:
            return
        self._pending_delete_item_id = item_id
        self._pending_delete_from_item = True
        self._delete_confirmation_selection = "delete"

    def open_item(self, index: int) -> Any:
        if not 0 <= index < len(self.batch):
            raise IndexError(index)
        item = self.batch.items[index]
        self._open_item_id = item.item_id
        return item.session

    def close_item(self) -> None:
        self._open_item_id = None
        self._repair_focus()

    def clear_open_item_acceptance(self) -> None:
        item_id = self.open_item_id
        if item_id is not None:
            self.batch.clear_acceptance(item_id)

    def complete_acceptance(self, item_id: str, take_number: int) -> None:
        self.batch.mark_accepted(item_id, take_number)

    def accept_open_item(
        self,
        number: int,
        *,
        pronunciation_index: int,
        bindings: BatchActionBindings,
    ) -> None:
        item_id = self.open_item_id
        if item_id is None:
            return
        item = self.batch.get_item(item_id)
        session = item.session
        had_active_batch = session.has_active_batch
        effects = bindings.operations.accept_take(
            session,
            number,
            busy=bindings.operations.busy,
            pronunciation_index=pronunciation_index,
        )
        bindings.dispatch_operation_effects(effects)
        saved = any(isinstance(effect, TakeAcceptedEffect) for effect in effects)
        if not had_active_batch or not saved:
            return
        self.complete_acceptance(item_id, number)

    def move_open_item(
        self,
        direction: int,
        *,
        bindings: BatchActionBindings,
    ) -> None:
        index = self.item_index
        if index is None or direction == 0:
            return
        if bindings.operations.busy:
            bindings.set_status(
                "Wait for the current synthesis operation to finish."
            )
            return
        target = index + (-1 if direction < 0 else 1)
        if target < 0:
            bindings.set_status("First Caption.")
            return
        if target >= len(self.batch):
            bindings.set_status("Last Caption.")
            return

        bindings.operations.stop_playback()
        bindings.operations.clear_current_take()
        bindings.editor_controller.clear_groupings()
        bindings.set_session(self.open_item(target))
        bindings.navigation.focus_key = ("batch_item", None)
        bindings.navigation.reset_pronunciation_index()
        bindings.set_status("")

    def close_sessions(self) -> None:
        for session in self.sessions:
            session.close()

    def dispatch_actions(
        self,
        actions: Sequence[BatchAction],
        bindings: BatchActionBindings,
    ) -> None:
        """Execute Batch List actions through explicit composition-root hooks."""

        for action in actions:
            if isinstance(action, OpenBatchItem):
                bindings.operations.stop_playback()
                bindings.operations.clear_current_take()
                bindings.editor_controller.clear_groupings()
                bindings.set_session(self.open_item(action.index))
                bindings.navigation.focus_key = ("batch_item", None)
                bindings.navigation.reset_pronunciation_index()
                bindings.set_status("")
            elif isinstance(action, AddCaptions):
                bindings.open_caption_editor("")
            elif isinstance(action, GenerateSelected):
                selected_ids = tuple(
                    item.item_id for item in self.batch.included_items
                )
                effects = bindings.operations.start_batch_generation(
                    self.batch,
                    navigation_revision=bindings.navigation.revision,
                )
                if (
                    bindings.operations.busy
                    and bindings.operations.worker_operation == "batch_generate"
                ):
                    for item_id in selected_ids:
                        self.batch.clear_acceptance(item_id)
                bindings.dispatch_operation_effects(effects)
            elif isinstance(action, AdjustBatchTakeCount):
                count = self.batch.default_take_count
                updated = min(100, max(1, count + action.direction))
                if updated != count:
                    bindings.change_settings(
                        take_count=updated,
                        report_success=False,
                    )
            elif isinstance(action, OpenBatchSettings):
                bindings.open_settings_editor("style_id")
            elif isinstance(action, OpenBatchDictionary):
                bindings.dispatch_editor_intents(
                    bindings.dictionary_controller.open_menu()
                )
            elif isinstance(action, OpenBatchHelp):
                bindings.open_help()
            elif isinstance(action, QuitBatch):
                bindings.activate_quit()

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

        if self.delete_confirmation_active:
            if key == "q":
                return (QuitBatch(),)
            if key == _ESCAPE:
                self._cancel_delete()
                return ()
            if key in (curses.KEY_UP, curses.KEY_DOWN):
                self._move_delete_confirmation(
                    -1 if key == curses.KEY_UP else 1
                )
                return ()
            shortcut = resolve_shortcut("batch_delete_confirmation", key)
            if shortcut is not None and shortcut.key == "delete":
                self._delete_confirmation_selection = "delete"
                self._confirm_delete()
                return ()
            if key in _ENTER_KEYS:
                if self._delete_confirmation_selection == "delete":
                    self._confirm_delete()
                else:
                    self._cancel_delete()
            return ()

        shortcut = resolve_batch_list_shortcut(key)
        if shortcut is not None:
            return self._activate((shortcut.navigation_key, None))

        caption_shortcut = resolve_batch_list_caption_shortcut(key)
        if caption_shortcut is not None:
            if (
                caption_shortcut.navigation_key == "delete_caption"
                and self.focus_key[0] == "caption"
                and self.focus_key[1] is not None
            ):
                index = self.focus_key[1]
                if 0 <= index < len(self.batch):
                    self._pending_delete_item_id = self.batch.items[index].item_id
                    self._pending_delete_from_item = False
                    self._delete_confirmation_selection = "delete"
            return ()

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

    def _move_delete_confirmation(self, delta: int) -> None:
        keys = ("delete", "cancel")
        try:
            index = keys.index(self._delete_confirmation_selection)
        except ValueError:
            index = 0
        target = min(max(index + delta, 0), len(keys) - 1)
        self._delete_confirmation_selection = keys[target]

    def _cancel_delete(self) -> None:
        self._pending_delete_item_id = None
        self._pending_delete_from_item = False
        self._delete_confirmation_selection = "delete"
        self._repair_focus()

    def _confirm_delete(self) -> None:
        item_id = self._pending_delete_item_id
        if item_id is None:
            return
        item = self.batch.get_item(item_id)
        index = self.batch.items.index(item)
        from_item = self._pending_delete_from_item
        removed = self.batch.remove_item(item_id)
        self._pending_delete_item_id = None
        self._pending_delete_from_item = False
        self._delete_confirmation_selection = "delete"
        removed.session.close()
        if from_item:
            self._open_item_id = None
        if len(self.batch):
            self.focus_key = ("caption", min(index, len(self.batch) - 1))
        else:
            self.focus_key = ("takes", None)

    def _next_unaccepted_generated_index(self, current_index: int) -> int | None:
        if len(self.batch) < 2:
            return None
        for offset in range(1, len(self.batch)):
            index = (current_index + offset) % len(self.batch)
            item = self.batch.items[index]
            if not item.is_accepted and item.session.candidates:
                return index
        return None

    def _repair_focus(self) -> None:
        items = self.navigation_items()
        if self.focus_key not in items:
            self.focus_key = (
                ("caption", 0) if len(self.batch) else ("takes", None)
            )
