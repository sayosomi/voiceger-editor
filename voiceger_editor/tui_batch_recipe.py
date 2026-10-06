"""Batch recipe Read/Write interaction state for the keyboard-first TUI."""

from __future__ import annotations

import curses
import os
from pathlib import Path
from typing import Any, Callable

from .batch_recipe import RECOMMENDED_SUFFIX, read_batch_recipe, write_batch_recipe
from .caption_batch import CaptionBatch
from .settings import Settings
from .tui_confirmation import handle_confirmation_key
from .tui_display import _display_width
from .tui_editors import (
    ClearAdjustmentFeedbackIntent,
    EditorState,
    OpenHelpIntent,
    QuitIntent,
    UpdateStatusIntent,
)
from .tui_output_path import BeginOutputPathEditIntent
from .tui_selection import move_clamped_selection
from .tui_shortcuts import menu_items, resolve_shortcut
from .tui_status import EMPTY_STATUS, error_status, info_status
from .tui_text_editing import apply_text_edit_key


_ENTER_KEYS = {"\n", "\r", curses.KEY_ENTER}
_ESCAPE = "\x1b"
_DEFAULT_RECIPE_FILENAME = f"batch{RECOMMENDED_SUFFIX}"


class TuiBatchRecipeController:
    """Own recipe path/confirmation UI while delegating file policy to core."""

    def __init__(
        self,
        *,
        adapter: Any,
        runtime_settings: Callable[[], Settings],
        current_batch: Callable[[], CaptionBatch],
        replace_batch: Callable[[CaptionBatch], None],
        output_dir: Callable[[], Path],
        input_prefix: Callable[[EditorState], str],
        reader: Callable[..., CaptionBatch] = read_batch_recipe,
        writer: Callable[..., Path] = write_batch_recipe,
    ) -> None:
        self._adapter = adapter
        self._runtime_settings = runtime_settings
        self._current_batch = current_batch
        self._replace_batch = replace_batch
        self._output_dir = output_dir
        self._input_prefix = input_prefix
        self._reader = reader
        self._writer = writer
        self.editor: EditorState | None = None
        self._pending_batch: CaptionBatch | None = None

    @property
    def active(self) -> bool:
        return self.editor is not None

    def _default_input_path(self) -> str:
        path = str(Path(self._output_dir()))
        return path if path.endswith(os.sep) else path + os.sep

    def _read_state(self, path: str | None = None) -> EditorState:
        return EditorState(
            kind="batch_recipe_read_path",
            title="READ BATCH",
            origin=("batch_list", None),
            selection="path",
            payload={
                "path": self._default_input_path() if path is None else path,
            },
        )

    @staticmethod
    def _write_state(file_name: str = _DEFAULT_RECIPE_FILENAME) -> EditorState:
        return EditorState(
            kind="batch_recipe_write_path",
            title="WRITE BATCH",
            origin=("batch_list", None),
            selection="file_name",
            payload={"file_name": file_name},
        )

    @staticmethod
    def _close_batch(batch: CaptionBatch) -> None:
        for item in batch.items:
            item.session.close()

    def _discard_pending_batch(self) -> None:
        pending = self._pending_batch
        self._pending_batch = None
        if pending is not None:
            self._close_batch(pending)

    def close(self) -> None:
        """Release any fully-read replacement batch that was never installed."""

        self._discard_pending_batch()
        self.editor = None

    def open_read(self) -> None:
        self._discard_pending_batch()
        self.editor = self._read_state()
        self._begin_field("path", str(self.editor.payload["path"]))

    def open_write(self) -> None:
        self._discard_pending_batch()
        self.editor = self._write_state()

    def _begin_field(self, name: str, value: str) -> None:
        editor = self.editor
        if editor is None:
            return
        editor.selection = name
        editor.active_field = name
        editor.input_value = value
        editor.input_original = value
        editor.input_cursor = len(value)
        editor.error = EMPTY_STATUS

    def _finish_field(self) -> tuple[Any, ...]:
        editor = self.editor
        if editor is None or editor.active_field is None:
            return ()
        name = editor.active_field
        editor.payload[name] = editor.input_value
        editor.active_field = None
        editor.input_original = editor.input_value
        editor.error = EMPTY_STATUS
        return (UpdateStatusIntent(""),)

    def _move_selection(self, direction: int) -> None:
        editor = self.editor
        if editor is None:
            return
        keys = [item.key for item in menu_items(editor.kind, editor.payload)]
        result = move_clamped_selection(editor.selection, keys, delta=direction)
        if result is not None:
            editor.selection = result.selection

    def _read(self) -> tuple[Any, ...]:
        editor = self.editor
        if editor is None:
            return ()
        path = str(editor.payload.get("path", ""))
        try:
            replacement = self._reader(
                path,
                adapter=self._adapter,
                runtime_settings=self._runtime_settings(),
            )
        except Exception as exc:
            editor.error = error_status(f"Batch was not read: {exc}")
            return ()

        editor.error = EMPTY_STATUS
        if len(self._current_batch()):
            self._discard_pending_batch()
            self._pending_batch = replacement
            self.editor = EditorState(
                kind="batch_recipe_replace_confirmation",
                title="REPLACE CURRENT BATCH?",
                origin=("batch_list", None),
                selection="cancel",
                payload={
                    "path": path,
                    "warning": (
                        "The current batch will be replaced. "
                        "Generated Takes and progress are not restored from recipe files."
                    ),
                },
            )
            return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

        self._replace_batch(replacement)
        self.editor = None
        return (
            UpdateStatusIntent(info_status(f"Batch read: {path}")),
            ClearAdjustmentFeedbackIntent(),
        )

    def _write(self) -> tuple[Any, ...]:
        editor = self.editor
        if editor is None:
            return ()
        file_name = str(editor.payload.get("file_name", ""))
        candidate = Path(file_name)
        if (
            not file_name
            or file_name in {".", ".."}
            or candidate.is_absolute()
            or candidate.name != file_name
            or "/" in file_name
            or "\\" in file_name
        ):
            editor.error = error_status(
                "Batch was not written: File name must be one file name."
            )
            return ()
        path = Path(self._output_dir()) / file_name
        try:
            target = self._writer(path, self._current_batch())
        except Exception as exc:
            editor.error = error_status(f"Batch was not written: {exc}")
            return ()
        self.editor = None
        return (
            UpdateStatusIntent(info_status(f"Batch written: {target}")),
            ClearAdjustmentFeedbackIntent(),
        )

    def _replace_pending(self) -> tuple[Any, ...]:
        editor = self.editor
        pending = self._pending_batch
        if editor is None or pending is None:
            return ()
        path = str(editor.payload.get("path", ""))
        self._pending_batch = None
        try:
            self._replace_batch(pending)
        except Exception as exc:
            self._pending_batch = pending
            editor.error = error_status(f"Batch was not replaced: {exc}")
            return ()
        self.editor = None
        return (
            UpdateStatusIntent(info_status(f"Batch read: {path}")),
            ClearAdjustmentFeedbackIntent(),
        )

    def _cancel_replace(self) -> tuple[Any, ...]:
        editor = self.editor
        path = (
            str(editor.payload.get("path", ""))
            if editor is not None
            else self._default_input_path()
        )
        self._discard_pending_batch()
        self.editor = self._read_state(path)
        self.editor.selection = "read"
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _close_editor(self) -> tuple[Any, ...]:
        self._discard_pending_batch()
        self.editor = None
        return (UpdateStatusIntent(""), ClearAdjustmentFeedbackIntent())

    def _activate(self) -> tuple[Any, ...]:
        editor = self.editor
        if editor is None:
            return ()
        selected = editor.selection
        if editor.kind == "batch_recipe_read_path":
            if selected == "path":
                self._begin_field("path", str(editor.payload.get("path", "")))
                return ()
            if selected == "read":
                return self._read()
            if selected == "back":
                return self._close_editor()
        if editor.kind == "batch_recipe_write_path":
            if selected == "output":
                return (BeginOutputPathEditIntent("batch_write"),)
            if selected == "file_name":
                self._begin_field(
                    "file_name",
                    str(editor.payload.get("file_name", "")),
                )
                return ()
            if selected == "write":
                return self._write()
            if selected == "back":
                return self._close_editor()
        return ()

    def handle_key(
        self,
        key: Any,
        *,
        screen_width: int = 80,
    ) -> tuple[Any, ...]:
        editor = self.editor
        if editor is None:
            return ()

        if editor.active_field is not None:
            if key in _ENTER_KEYS:
                return self._finish_field()
            if key == _ESCAPE:
                return self._close_editor()
            input_width = 1
            if key in (curses.KEY_UP, curses.KEY_DOWN):
                prefix = self._input_prefix(editor)
                input_width = max(
                    1,
                    screen_width - 1 - _display_width(prefix),
                )
            edit = apply_text_edit_key(
                editor.input_value,
                editor.input_cursor,
                key,
                input_width=input_width,
            )
            if edit.handled:
                editor.input_value = edit.value
                editor.input_cursor = edit.cursor
                if edit.edit_attempted:
                    editor.error = EMPTY_STATUS
            return ()

        if key in ("q", "Q", "\x03"):
            return (QuitIntent(),)
        if key == "?":
            return (OpenHelpIntent(),)

        if editor.kind == "batch_recipe_replace_confirmation":
            interaction = handle_confirmation_key(
                editor.kind,
                str(editor.selection),
                key,
                editor.payload,
            )
            if not interaction.handled:
                return ()
            editor.selection = interaction.selection
            editor.error = EMPTY_STATUS
            if interaction.activation == "replace":
                return self._replace_pending()
            if interaction.activation == "cancel":
                return self._cancel_replace()
            return ()

        shortcut = resolve_shortcut(editor.kind, key, editor.payload)
        if shortcut is not None:
            editor.selection = shortcut.key
            editor.error = EMPTY_STATUS
            if shortcut.shortcut_mode == "activate":
                return self._activate()
            return ()

        if key == _ESCAPE:
            return self._close_editor()
        if key == curses.KEY_UP:
            self._move_selection(-1)
            return ()
        if key == curses.KEY_DOWN:
            self._move_selection(1)
            return ()
        if key in _ENTER_KEYS:
            return self._activate()
        return ()
